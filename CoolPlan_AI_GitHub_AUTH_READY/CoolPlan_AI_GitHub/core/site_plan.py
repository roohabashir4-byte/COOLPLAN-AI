"""
CoolPlan AI — Workflow 2: Site Plan Processing & User Verification

Independent module for PDF/JPG/PNG site-plan processing.

Workflow:
1. Read PDF/JPG/PNG.
2. Extract drawing text where available.
3. Render PDF to an image for visual analysis.
4. Use an accessible Groq vision model to estimate site composition.
5. Normalize estimates to 100%.
6. Return estimates with confidence and reasons.
7. Let the calling application verify/edit percentages.
8. Return confirmed composition only after validation.

Important:
- Estimates are approximate MVP estimates, not surveyed quantities.
- No hard-coded project percentages are used.
- The test project filename is NOT hard-coded.
- This module does not calculate heat scores or interventions.
"""

from __future__ import annotations

import base64
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any, Dict, List

import pymupdf
from groq import Groq


FEATURE_KEYWORDS = {
    "site_boundary": ["PLOT BOUNDRY", "PLOT BOUNDARY"],
    "buildings_facilities": [
        "FACULTY", "HOSTEL", "COMMERCIAL", "FACILITY", "EXHIBITION HALL"
    ],
    "roads": ["ROAD", "R.O.W"],
    "parking": ["CAR PARKING", "BUS PARKING"],
    "green_landscape": [
        "LANDSCAPE GARDEN", "OPEN AREA (GREEN)", "PARK"
    ],
    "footpaths": ["FOOTPATH"],
    "sports_recreation": [
        "CRICKET GROUND", "HOCKEY GROUND", "TENNIS COURTS"
    ],
    "water_infrastructure": [
        "UNDER GROUND WATER TANK", "TUBE WELL", "FOUNTAIN"
    ],
    "future_development": ["FUTURE", "FUTURE EXTENSION"],
}

CATEGORIES = [
    "Buildings / Facilities",
    "Roads / Circulation",
    "Parking",
    "Green / Landscape",
    "Sports / Recreation",
    "Footpaths",
    "Water / Drainage Areas",
    "Other / Unclassified",
]


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def extract_pdf_text(file_path: str | Path) -> str:
    """Extract all available text from a PDF."""
    path = Path(file_path)
    with pymupdf.open(path) as doc:
        return "\n".join(page.get_text() for page in doc)


def detect_plan_labels(text: str) -> Dict[str, List[str]]:
    """
    Detect plan labels from extracted text.

    Detection also uses a whitespace-stripped copy so labels such as
    'F O O T P A T H' can still be detected.
    """
    text_upper = (text or "").upper()
    compact = re.sub(r"\s+", "", text_upper)

    detected: Dict[str, List[str]] = {}
    for category, keywords in FEATURE_KEYWORDS.items():
        matches = []
        for keyword in keywords:
            if keyword in text_upper or keyword.replace(" ", "") in compact:
                matches.append(keyword)
        if matches:
            detected[category] = sorted(set(matches))
    return detected


def render_first_page(file_path: str | Path, dpi: int = 150) -> str:
    """
    Render the first PDF page to a temporary PNG and return its path.

    The caller is responsible for deleting the returned temporary file.
    """
    path = Path(file_path)
    doc = pymupdf.open(path)
    try:
        if len(doc) == 0:
            raise ValueError("The PDF contains no pages.")
        page = doc[0]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.close()
        pix.save(tmp.name)
        return tmp.name
    finally:
        doc.close()


def _image_to_data_url(image_path: str | Path) -> str:
    data = Path(image_path).read_bytes()
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


def _find_accessible_vision_model(client: Groq) -> str:
    """
    Find a vision-capable model from the models available to the API key.

    Preference is given to Qwen vision models, while avoiding a hard-coded
    unavailable model ID.
    """
    models = client.models.list()
    ids = [getattr(m, "id", "") for m in models.data]

    preferred = [
        m for m in ids
        if "qwen" in m.lower() and ("vision" in m.lower() or "qwen3.8" in m.lower())
    ]
    if preferred:
        return preferred[0]

    # Fallback to any model whose ID suggests vision/multimodal capability.
    vision_like = [
        m for m in ids
        if any(term in m.lower() for term in ("vision", "vl", "multimodal"))
    ]
    if vision_like:
        return vision_like[0]

    raise RuntimeError(
        "No accessible vision-capable Groq model was found for this API key."
    )


def _parse_json_response(raw: str) -> Dict[str, Any]:
    raw = (raw or "").strip()

    # Remove common markdown fences if the model returns them.
    raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            return json.loads(raw[start:end + 1])
        raise ValueError("Groq returned a response that was not valid JSON.")


def _normalize_estimates(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    cleaned = []

    for item in items:
        category = str(item.get("category", "")).strip()
        if category not in CATEGORIES:
            continue

        try:
            percentage = float(item.get("percentage", 0))
        except (TypeError, ValueError):
            percentage = 0.0

        percentage = max(0.0, percentage)

        cleaned.append({
            "category": category,
            "percentage": percentage,
            "confidence": str(item.get("confidence", "Low")).strip().title(),
            "reason": _clean_text(str(item.get("reason", ""))),
        })

    # Ensure every controlled category exists.
    existing = {x["category"] for x in cleaned}
    for category in CATEGORIES:
        if category not in existing:
            cleaned.append({
                "category": category,
                "percentage": 0.0,
                "confidence": "Low",
                "reason": "Not clearly identified from the available plan evidence.",
            })

    total = sum(x["percentage"] for x in cleaned)
    if total <= 0:
        raise ValueError("The AI returned no usable site-composition percentages.")

    # Normalize to exactly 100 while preserving relative estimates.
    for x in cleaned:
        x["percentage"] = round(x["percentage"] * 100.0 / total, 2)

    # Correct rounding drift on the final category.
    drift = round(100.0 - sum(x["percentage"] for x in cleaned), 2)
    cleaned[-1]["percentage"] = round(cleaned[-1]["percentage"] + drift, 2)

    return cleaned


def analyze_site_plan(
    file_path: str | Path,
    groq_api_key: str | None = None,
    vision_model: str | None = None,
    dpi: int = 150,
) -> Dict[str, Any]:
    """
    Analyze a site-plan PDF with Groq vision.

    Returns a dictionary containing:
      - file_name
      - extracted_text
      - detected_labels
      - estimated_composition
      - total_percentage
      - verification_required
      - vision_model
    """
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Site plan not found: {path}")

    if path.suffix.lower() != ".pdf":
        raise ValueError(
            "Workflow 2 currently packages the tested PDF path. "
            "JPG/PNG support can be added using the same visual-analysis interface."
        )

    api_key = groq_api_key or os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY was not provided.")

    text = extract_pdf_text(path)
    detected = detect_plan_labels(text)

    rendered_path = render_first_page(path, dpi=dpi)
    try:
        client = Groq(api_key=api_key)
        model = vision_model or _find_accessible_vision_model(client)
        image_url = _image_to_data_url(rendered_path)

        prompt = f"""
You are analyzing a site development master plan for CoolPlan AI.

This is a NEW DEVELOPMENT test scenario. Estimate the approximate percentage
of the SITE AREA occupied by each category below. These are preliminary
planning estimates, NOT surveyed quantities.

Categories:
{json.dumps(CATEGORIES, indent=2)}

Rules:
1. Use the drawing image as the primary visual evidence.
2. Use the extracted drawing text as supporting evidence.
3. Do NOT invent exact measured areas.
4. Give approximate percentages that reflect visible site composition.
5. The percentages must sum to 100 before returning them.
6. Confidence must be High, Medium, or Low.
7. Explain briefly why each estimate was made.
8. If a category is unclear, use a low estimate and explain the uncertainty.
9. Return JSON only.

Extracted drawing text:
{text[:12000]}

Detected labels:
{json.dumps(detected, indent=2)}
"""

        response = client.chat.completions.create(
            model=model,
            temperature=0,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": image_url},
                        },
                    ],
                }
            ],
        )

        raw = response.choices[0].message.content
        parsed = _parse_json_response(raw)

        items = parsed.get("composition", parsed.get("site_composition", []))
        if not isinstance(items, list):
            raise ValueError("Groq JSON did not contain a composition list.")

        estimates = _normalize_estimates(items)

        return {
            "file_name": path.name,
            "extracted_text": text,
            "detected_labels": detected,
            "estimated_composition": estimates,
            "total_percentage": round(
                sum(x["percentage"] for x in estimates), 2
            ),
            "verification_required": True,
            "vision_model": model,
            "status": "estimated",
        }

    finally:
        try:
            os.remove(rendered_path)
        except OSError:
            pass


def validate_confirmed_composition(
    composition: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Validate user-confirmed/edited composition.

    The values must be non-negative and sum to 100 (within a small tolerance).
    """
    if not composition:
        raise ValueError("Composition is empty.")

    values = []
    for item in composition:
        category = str(item.get("category", "")).strip()
        if category not in CATEGORIES:
            raise ValueError(f"Unknown category: {category}")

        try:
            percentage = float(item.get("percentage"))
        except (TypeError, ValueError):
            raise ValueError(f"Invalid percentage for {category}.")

        if percentage < 0:
            raise ValueError(f"Percentage cannot be negative: {category}")

        values.append({
            "category": category,
            "percentage": round(percentage, 2),
        })

    total = round(sum(x["percentage"] for x in values), 2)

    if abs(total - 100.0) > 0.01:
        raise ValueError(
            f"Confirmed composition must total 100%. Current total: {total}%."
        )

    return {
        "composition": values,
        "total_percentage": total,
        "status": "confirmed",
    }
