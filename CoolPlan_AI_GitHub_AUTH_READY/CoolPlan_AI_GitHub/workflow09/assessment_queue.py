"""Prepare screening candidates for the CoolPlan assessment agent.

This module does not change screening results or calculate suitability scores.
"""

from .constraint_mapper import map_design_constraints


def build_assessment_queue(screening_result, design_selections):
    """Create one assessment task per zone and candidate intervention."""

    if not isinstance(screening_result, dict):
        raise TypeError("screening_result must be a dictionary.")

    if screening_result.get("type") != "FeatureCollection":
        raise ValueError("screening_result must be a GeoJSON FeatureCollection.")

    mapped = map_design_constraints(design_selections)
    tasks = []

    for feature in screening_result.get("features", []):
        properties = feature.get("properties") or {}
        screening = properties.get("intervention_screening") or {}

        # Only zones with screening candidates enter the assessment queue.
        if screening.get("status") != "ELIGIBLE":
            continue

        zone_id = screening.get("zone_id")
        candidates = screening.get("eligible_interventions") or []

        for intervention in candidates:
            tasks.append({
                "zone_id": zone_id,
                "intervention": intervention,
                "identified_features": screening.get(
                    "identified_features", []
                ),
                "environmental_issues": screening.get(
                    "environmental_issues", []
                ),
                "environmental_evidence": screening.get(
                    "evidence", []
                ),
                "screening_method": screening.get(
                    "screening_method", {}
                ),
                "project_constraints": dict(
                    mapped["project_constraints"]
                ),
                "project_context": dict(
                    mapped["project_context"]
                ),
                "feature_constraints_required": True,
                "component_scores_required": True,
                "assessment_status": "PENDING_ASSESSMENT",
            })

    return {
        "queue_name": "CoolPlan_Intervention_Assessment_Queue",
        "task_count": len(tasks),
        "tasks": tasks,
        "notes": [
            "Screening eligibility is not final design eligibility.",
            "Feature-specific constraints must be assessed separately.",
            "Component scores must be evidence-based.",
            "No HPS or environmental source values are modified.",
        ],
    }
