"""
Workflow 09 — Intervention Proposal Agent

Responsibilities:
- Prepare a focused task context.
- Retrieve existing RAG evidence.
- Ask the configured LLM for intervention proposals.
- Validate and normalize the returned JSON.

This module does NOT:
- Calculate ISS or component scores.
- Approve hard constraints.
- Modify screening GeoJSON or source environmental values.
- Guarantee site suitability.
"""

import json
import re


ALLOWED_INTERVENTIONS = {
    "cool_roof",
    "green_roof",
    "cool_pavement",
    "shade_structure",
    "strategic_vegetation",
    "permeable_green_infrastructure",
}


SYSTEM_PROMPT = """
You are the intervention-proposal component of CoolPlan AI.

Use only the supplied task information and retrieved evidence.
Propose interventions relevant to the stated environmental issues
and identified site features.

Rules:
1. Do not invent site measurements, available space, water supply,
   budget, structural capacity, or technical feasibility.
2. Do not calculate ISS, component scores, or numerical heat reduction.
3. Do not claim an intervention is feasible or approved.
4. Proposals are candidates for deterministic constraint screening.
5. Retrieved evidence may be U.S.-based. Do not claim it is validated
   for Pakistan.
6. Use only these exact intervention identifiers:
   cool_roof, green_roof, cool_pavement, shade_structure,
   strategic_vegetation, permeable_green_infrastructure.
7. Return only valid JSON matching the requested schema.
"""


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def build_task_query(task):
    """Build a compact retrieval query from relevant task fields."""
    parts = []

    for field in (
        "intervention",
        "identified_features",
        "environmental_issues",
        "environmental_evidence",
    ):
        value = task.get(field)
        if value:
            parts.append(f"{field}: {value}")

    return "\n".join(parts)[:2500]


def build_messages(task, design_selections, evidence_context):
    """Create a bounded prompt using only task-relevant information."""
    compact_task = {
        "zone_id": task.get("zone_id"),
        "intervention": task.get("intervention"),
        "identified_features": _as_list(
            task.get("identified_features")
        ),
        "environmental_issues": _as_list(
            task.get("environmental_issues")
        ),
        "environmental_evidence": _as_list(
            task.get("environmental_evidence")
        ),
        "design_selections": {
            key: design_selections.get(key)
            for key in (
                "available_space",
                "water_availability",
                "project_budget",
                "maintenance_capacity",
            )
        },
    }

    user_prompt = {
        "task": compact_task,
        "retrieved_evidence": evidence_context[:2728],
        "required_output": {
            "proposals": [
                {
                    "intervention": "one exact allowed identifier",
                    "rationale": "brief explanation tied to the task",
                    "evidence_chunk_ids": [
                        "chunk ID from supplied evidence"
                    ],
                    "uncertainties": [
                        "unknown site conditions or checks required"
                    ],
                }
            ]
        },
        "limits": {
            "maximum_proposals": 6,
            "rationale_max_words": 70,
            "no_scores": True,
            "no_feasibility_approval": True,
        },
    }

    return [
        {"role": "system", "content": SYSTEM_PROMPT.strip()},
        {
            "role": "user",
            "content": json.dumps(
                user_prompt,
                ensure_ascii=False,
                default=str,
            ),
        },
    ]


def _extract_json(content):
    """Parse a JSON object, allowing a surrounding JSON code fence."""
    if not isinstance(content, str) or not content.strip():
        raise ValueError("LLM response is empty.")

    text = content.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)

    data = json.loads(text)

    if not isinstance(data, dict):
        raise ValueError("LLM response must be a JSON object.")

    return data


def validate_proposals(data, retrieved_evidence, max_proposals=6):
    """Validate proposals and attach only relevant retrieved evidence IDs."""
    if not isinstance(data, dict):
        raise TypeError("data must be a dictionary.")

    proposals = data.get("proposals")
    if not isinstance(proposals, list):
        raise ValueError("Response must contain a proposals list.")

    # Intervention-to-RAG category mapping.
    category_map = {
        "cool_roof": {"cool roofs"},
        "green_roof": {"green roofs"},
        "cool_pavement": {"cool pavements"},
        "strategic_vegetation": {"trees and vegetation"},
    }

    evidence_by_id = {
        item.get("chunk_id"): item
        for item in retrieved_evidence
        if isinstance(item, dict) and item.get("chunk_id")
    }
    valid_chunk_ids = set(evidence_by_id)

    cleaned = []
    seen = set()

    for proposal in proposals[:max_proposals]:
        if not isinstance(proposal, dict):
            continue

        intervention = proposal.get("intervention")
        if intervention not in ALLOWED_INTERVENTIONS:
            continue
        if intervention in seen:
            continue

        rationale = proposal.get("rationale")
        if not isinstance(rationale, str) or not rationale.strip():
            continue

        # Retain valid IDs supplied by the model.
        raw_ids = _as_list(proposal.get("evidence_chunk_ids"))
        evidence_ids = [
            chunk_id for chunk_id in raw_ids
            if isinstance(chunk_id, str) and chunk_id in valid_chunk_ids
        ]

        # Fill missing links only from retrieved chunks whose category
        # matches this intervention. Never fabricate IDs or evidence.
        allowed_categories = category_map.get(intervention, set())
        for chunk_id, item in evidence_by_id.items():
            category = str(item.get("intervention_category", "")).strip().lower()
            if category in allowed_categories and chunk_id not in evidence_ids:
                evidence_ids.append(chunk_id)

        uncertainties = _as_list(proposal.get("uncertainties"))
        uncertainties = [
            item.strip()
            for item in uncertainties
            if isinstance(item, str) and item.strip()
        ]

        cleaned.append({
            "intervention": intervention,
            "rationale": rationale.strip()[:1000],
            "evidence_chunk_ids": evidence_ids,
            "uncertainties": uncertainties[:10],
            "status": "PROPOSED_PENDING_CONSTRAINTS",
        })
        seen.add(intervention)

    return cleaned


class Workflow09Agent:
    """Thin orchestration layer over the existing retriever and API client."""

    def __init__(self, retriever, api_client):
        self.retriever = retriever
        self.api_client = api_client

    def propose_interventions(
        self,
        task,
        design_selections,
        top_k=5,
        category=None,
        max_output_tokens=500,
    ):
        if not isinstance(task, dict):
            raise TypeError("task must be a dictionary.")

        if not isinstance(design_selections, dict):
            raise TypeError("design_selections must be a dictionary.")

        query = build_task_query(task)
        if not query.strip():
            return {
                "status": "PENDING",
                "error": "TASK_CONTEXT_MISSING",
                "proposals": [],
                "evidence": [],
            }

        # Map intervention IDs to the exact categories in the existing RAG.
        category_map = {
            "cool_roof": "Cool Roofs",
            "green_roof": "Green Roofs",
            "cool_pavement": "Cool Pavements",
            "strategic_vegetation": "Trees and Vegetation",
            # No dedicated archive category: retrieve broadly.
            "shade_structure": None,
            "permeable_green_infrastructure": None,
        }

        retrieval_category = category_map.get(category, category)

        evidence_context, evidence = self.retriever.retrieve_context(
            query=query,
            top_k=top_k,
            category=retrieval_category,
        )

        if not evidence:
            return {
                "status": "PENDING",
                "error": "NO_RAG_EVIDENCE",
                "proposals": [],
                "evidence": [],
            }

        messages = build_messages(
            task=task,
            design_selections=design_selections,
            evidence_context=evidence_context,
        )

        # The caller should use this method from a worker/background task,
        # not from an interactive UI's main thread.
        response = self.api_client.call(
            messages,
            max_output_tokens=max_output_tokens,
            use_cache=True,
        )

        if not isinstance(response, dict):
            return {
                "status": "PENDING",
                "error": "INVALID_API_RESPONSE",
                "proposals": [],
                "evidence": evidence,
            }

        if response.get("status") != "COMPLETED":
            return {
                "status": response.get("status", "PENDING"),
                "error": response.get("error", "AI_REQUEST_INCOMPLETE"),
                "proposals": [],
                "evidence": evidence,
            }

        try:
            parsed = _extract_json(response.get("content"))
            proposals = validate_proposals(parsed, evidence)
        except (ValueError, TypeError, json.JSONDecodeError) as exc:
            return {
                "status": "PENDING",
                "error": "INVALID_AGENT_OUTPUT",
                "message": str(exc),
                "proposals": [],
                "evidence": evidence,
            }

        return {
            "status": "COMPLETED",
            "error": None,
            "zone_id": task.get("zone_id"),
            "proposals": proposals,
            "evidence": evidence,
            "notes": [
                "Proposals are not final suitability decisions.",
                "Hard constraints and component inputs require separate assessment.",
                "No environmental source values or screening statuses were changed.",
            ],
        }
