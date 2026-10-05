"""
CoolPlan AI — Workflow 09 API Client

Features:
- Groq Qwen 3.8 27B
- Conservative request/token budgets
- Local response cache
- Bounded retries
- Request queue through a single worker
- Background execution using Futures
- Structured errors; no uncontrolled retries

This module does not calculate suitability scores.
"""

import os
import json
import time
import hashlib
import threading
from pathlib import Path
from collections import deque
from concurrent.futures import ThreadPoolExecutor


MODEL = "qwen/qwen3.8-27b"

# Conservative internal budgets for a Free-plan deployment.
MAX_REQUESTS_PER_MINUTE = 10
MAX_ESTIMATED_TOKENS_PER_MINUTE = 4000

MAX_REQUESTS_PER_DAY = 700
MAX_ESTIMATED_TOKENS_PER_DAY = 140000

MAX_INPUT_TOKENS = 2000
MAX_OUTPUT_TOKENS = 500

MAX_RETRIES = 1
REQUEST_TIMEOUT_SECONDS = 30

DEFAULT_CACHE_PATH = Path(
    "/content/CoolPlan_Constraints_Development/"
    "workflow09_api_cache.json"
)

DEFAULT_USAGE_PATH = Path(
    "/content/CoolPlan_Constraints_Development/"
    "workflow09_api_usage.json"
)


def estimate_tokens(text):
    """
    Conservative rough estimate.
    This is a budget guard, not an exact tokenizer.
    """
    if not text:
        return 0
    return max(1, (len(text) + 2) // 3)


def _stable_hash(value):
    encoded = json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        default=str
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Workflow09APIClient:

    def __init__(
        self,
        api_key=None,
        model=MODEL,
        cache_path=DEFAULT_CACHE_PATH,
        usage_path=DEFAULT_USAGE_PATH,
        timeout=REQUEST_TIMEOUT_SECONDS,
    ):
        self.api_key = api_key or os.getenv("GROQ_API_KEY")
        self.model = model
        self.cache_path = Path(cache_path)
        self.usage_path = Path(usage_path)
        self.timeout = timeout

        self._lock = threading.Lock()
        self._minute_requests = deque()
        self._minute_tokens = deque()
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="workflow09-ai"
        )
        self._inflight = {}

        self.cache_path.parent.mkdir(
            parents=True, exist_ok=True
        )
        self.usage_path.parent.mkdir(
            parents=True, exist_ok=True
        )

    def _read_json(self, path, default):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return default

    def _write_json(self, path, data):
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        temp_path.replace(path)

    def _daily_usage(self):
        data = self._read_json(self.usage_path, {})
        today = time.strftime("%Y-%m-%d")
        if data.get("date") != today:
            data = {
                "date": today,
                "requests": 0,
                "estimated_tokens": 0,
            }
        return data

    def _record_daily_usage(self, estimated_tokens):
        data = self._daily_usage()
        data["requests"] += 1
        data["estimated_tokens"] += estimated_tokens
        self._write_json(self.usage_path, data)

    def _check_daily_budget(self, estimated_tokens):
        data = self._daily_usage()

        if data["requests"] >= MAX_REQUESTS_PER_DAY:
            return False, "DAILY_REQUEST_BUDGET_REACHED"

        if (
            data["estimated_tokens"] + estimated_tokens
            > MAX_ESTIMATED_TOKENS_PER_DAY
        ):
            return False, "DAILY_TOKEN_BUDGET_REACHED"

        return True, "OK"

    def _wait_for_minute_budget(self, estimated_tokens):
        """
        Wait only inside the background worker.
        The UI should not wait on Future.result() while processing.
        """
        while True:
            now = time.time()

            while (
                self._minute_requests
                and now - self._minute_requests[0][0] >= 60
            ):
                self._minute_requests.popleft()

            while (
                self._minute_tokens
                and now - self._minute_tokens[0][0] >= 60
            ):
                self._minute_tokens.popleft()

            request_count = len(self._minute_requests)
            token_count = sum(
                item[1] for item in self._minute_tokens
            )

            if request_count < MAX_REQUESTS_PER_MINUTE:
                if (
                    token_count + estimated_tokens
                    <= MAX_ESTIMATED_TOKENS_PER_MINUTE
                ):
                    return

            waits = [1.0]

            if self._minute_requests:
                waits.append(
                    max(
                        0.1,
                        60 - (now - self._minute_requests[0][0])
                    )
                )

            if self._minute_tokens:
                waits.append(
                    max(
                        0.1,
                        60 - (now - self._minute_tokens[0][0])
                    )
                )

            time.sleep(min(waits))

    def _reserve_budget(self, estimated_tokens):
        """
        Reserve capacity atomically.
        Never hold the shared lock while sleeping for capacity.
        Reservations count conservatively, including failed calls.
        """
        while True:
            wait_seconds = None

            with self._lock:
                allowed, reason = self._check_daily_budget(
                    estimated_tokens
                )
                if not allowed:
                    return False, reason

                now = time.time()

                while (
                    self._minute_requests
                    and now - self._minute_requests[0][0] >= 60
                ):
                    self._minute_requests.popleft()

                while (
                    self._minute_tokens
                    and now - self._minute_tokens[0][0] >= 60
                ):
                    self._minute_tokens.popleft()

                request_count = len(self._minute_requests)
                token_count = sum(
                    item[1] for item in self._minute_tokens
                )

                request_room = (
                    request_count < MAX_REQUESTS_PER_MINUTE
                )
                token_room = (
                    token_count + estimated_tokens
                    <= MAX_ESTIMATED_TOKENS_PER_MINUTE
                )

                if request_room and token_room:
                    self._minute_requests.append((now, 1))
                    self._minute_tokens.append(
                        (now, estimated_tokens)
                    )
                    self._record_daily_usage(estimated_tokens)
                    return True, "OK"

                waits = [1.0]

                if self._minute_requests:
                    waits.append(max(
                        0.1,
                        60 - (now - self._minute_requests[0][0])
                    ))

                if self._minute_tokens:
                    waits.append(max(
                        0.1,
                        60 - (now - self._minute_tokens[0][0])
                    ))

                wait_seconds = min(waits)

            # The lock has been released before sleeping.
            time.sleep(wait_seconds)

    def _cache_key(self, messages, max_output_tokens):
        return _stable_hash({
            "model": self.model,
            "messages": messages,
            "max_output_tokens": max_output_tokens,
            "client_version": "workflow09-api-v1",
        })

    def _get_cache(self, key):
        cache = self._read_json(self.cache_path, {})
        return cache.get(key)

    def _save_cache(self, key, result):
        cache = self._read_json(self.cache_path, {})
        cache[key] = result
        self._write_json(self.cache_path, cache)

    def call(
        self,
        messages,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        use_cache=True,
    ):
        """
        Synchronous call.
        Prefer submit() from an interactive app so the UI stays responsive.
        """
        if not isinstance(messages, list) or not messages:
            return {
                "status": "FAILED",
                "error": "INVALID_MESSAGES",
                "content": None,
                "cached": False,
            }

        if not self.api_key:
            return {
                "status": "FAILED",
                "error": "GROQ_API_KEY_NOT_CONFIGURED",
                "content": None,
                "cached": False,
            }

        if not 1 <= max_output_tokens <= MAX_OUTPUT_TOKENS:
            return {
                "status": "FAILED",
                "error": "OUTPUT_TOKEN_BUDGET_EXCEEDED",
                "content": None,
                "cached": False,
            }

        prompt_text = json.dumps(
            messages, ensure_ascii=False, default=str
        )
        input_tokens = estimate_tokens(prompt_text)

        if input_tokens > MAX_INPUT_TOKENS:
            return {
                "status": "PENDING",
                "error": "INPUT_TOKEN_BUDGET_EXCEEDED",
                "estimated_input_tokens": input_tokens,
                "content": None,
                "cached": False,
            }

        estimated_total = input_tokens + max_output_tokens
        cache_key = self._cache_key(
            messages, max_output_tokens
        )

        if use_cache:
            cached = self._get_cache(cache_key)
            if cached is not None:
                return {
                    **cached,
                    "cached": True,
                }

        allowed, reason = self._reserve_budget(
            estimated_total
        )

        if not allowed:
            return {
                "status": "PENDING",
                "error": reason,
                "content": None,
                "cached": False,
            }

        try:
            from groq import Groq
        except ImportError:
            return {
                "status": "FAILED",
                "error": "GROQ_PACKAGE_NOT_INSTALLED",
                "content": None,
                "cached": False,
            }

        client = Groq(
            api_key=self.api_key,
            timeout=self.timeout,
            max_retries=0,
        )

        last_error = "UNKNOWN_API_ERROR"

        for attempt in range(MAX_RETRIES + 1):
            try:
                response = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    max_tokens=max_output_tokens,
                    temperature=0.2,
                )

                content = response.choices[0].message.content

                result = {
                    "status": "COMPLETED",
                    "error": None,
                    "content": content,
                    "model": self.model,
                    "cached": False,
                    "estimated_input_tokens": input_tokens,
                    "estimated_budget_tokens": estimated_total,
                }

                if use_cache:
                    self._save_cache(cache_key, result)

                return result

            except Exception as exc:
                status_code = getattr(exc, "status_code", None)
                last_error = (
                    f"API_ERROR_{status_code}"
                    if status_code
                    else type(exc).__name__
                )

                # Do not retry oversized requests or bad credentials.
                if status_code in (400, 401, 403, 413):
                    break

                # Retry only once for rate limits or server/network errors.
                if attempt < MAX_RETRIES:
                    retry_after = None
                    response_obj = getattr(exc, "response", None)

                    if response_obj is not None:
                        try:
                            retry_after = response_obj.headers.get(
                                "retry-after"
                            )
                        except Exception:
                            retry_after = None

                    try:
                        delay = float(retry_after)
                    except (TypeError, ValueError):
                        delay = 2.0

                    time.sleep(min(max(delay, 1.0), 15.0))

        return {
            "status": "PENDING",
            "error": last_error,
            "content": None,
            "cached": False,
            "message": (
                "AI request did not complete. "
                "The application can continue."
            ),
        }

    def submit(
        self,
        messages,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        use_cache=True,
    ):
        """
        Queue work in the background.
        Identical queued/running requests share one Future.
        Do not call Future.result() from the UI's main thread.
        """
        if not use_cache:
            return self._executor.submit(
                self.call,
                messages,
                max_output_tokens,
                use_cache,
            )

        key = self._cache_key(messages, max_output_tokens)

        with self._lock:
            existing = self._inflight.get(key)
            if existing is not None:
                return existing

            future = self._executor.submit(
                self.call,
                messages,
                max_output_tokens,
                use_cache,
            )
            self._inflight[key] = future

        def remove_completed(_future):
            with self._lock:
                if self._inflight.get(key) is _future:
                    self._inflight.pop(key, None)

        future.add_done_callback(remove_completed)
        return future

    def close(self, wait=False):
        self._executor.shutdown(
            wait=wait,
            cancel_futures=True,
        )
