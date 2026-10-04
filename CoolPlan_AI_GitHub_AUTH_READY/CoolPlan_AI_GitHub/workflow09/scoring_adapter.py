"""Safe adapter for the existing CoolPlan suitability scorer.

This module does not invent component scores or alter scorer rules.
"""

import sys
from pathlib import Path

SCORER_DIR = Path("/content")
if str(SCORER_DIR) not in sys.path:
    sys.path.insert(0, str(SCORER_DIR))

from .coolplan_suitability_scorer_v2 import score_intervention, check_hard_constraints
from .constraint_mapper import map_design_constraints


REQUIRED_COMPONENT_INPUTS = {
    "environmental_need",
    "intervention_response",
    "feature_compatibility",
    "site_function_compatibility",
    "water_demand_compatibility",
    "spatial_fit",
    "budget_fit",
    "technical_feasibility",
    "operational_feasibility",
    "maintenance_feasibility",
}


def assess_intervention(
    intervention,
    design_selections,
    feature_constraints,
    component_inputs=None,
):
    """Validate hard constraints before checking component inputs."""

    mapped = map_design_constraints(design_selections)

    if not isinstance(feature_constraints, dict):
        raise TypeError("feature_constraints must be a dictionary.")

    if component_inputs is None:
        component_inputs = {}
    if not isinstance(component_inputs, dict):
        raise TypeError("component_inputs must be a dictionary.")

    constraints = {
        **mapped["project_constraints"],
        **feature_constraints,
    }

    constraint_result = check_hard_constraints(
        intervention=intervention,
        constraints=constraints,
    )

    constraint_status = constraint_result["status"]

    if constraint_status in {
        "EXCLUDED_HARD_CONSTRAINT",
        "PENDING_CONSTRAINTS",
        "REQUIRES_REVIEW",
    }:
        return {
            "intervention": intervention,
            **constraint_result,
            "ISS": None,
            "project_context": mapped["project_context"],
        }

    missing = sorted(
        REQUIRED_COMPONENT_INPUTS - set(component_inputs)
    )

    if missing:
        return {
            "intervention": intervention,
            "status": "PENDING_COMPONENT_INPUTS",
            "missing_component_inputs": missing,
            "ISS": None,
            "constraint_result": constraint_result,
            "project_context": mapped["project_context"],
            "reason": (
                "Hard constraints passed. Provide all required "
                "evidence-based component inputs before suitability scoring."
            ),
        }

    result = score_intervention(
        intervention=intervention,
        constraints=constraints,
        component_inputs=component_inputs,
    )

    result["project_context"] = mapped["project_context"]
    result["constraint_result"] = constraint_result

    return result
