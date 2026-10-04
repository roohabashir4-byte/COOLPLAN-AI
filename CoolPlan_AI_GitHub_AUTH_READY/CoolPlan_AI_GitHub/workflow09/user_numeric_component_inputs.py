"""
CoolPlan AI — Workflow 09 numeric user component inputs.

Maps the four finalized 1–100 user inputs directly to the
corresponding suitability-score component inputs.

No categorical conversion is performed.
No hard constraints are inferred.
"""

USER_NUMERIC_INPUTS = {
    "available_space": "spatial_fit",
    "water_availability": "water_demand_compatibility",
    "project_budget": "budget_fit",
    "maintenance_capacity": "maintenance_feasibility",
}


def _validate_1_to_100(value, field_name):
    if isinstance(value, bool):
        raise ValueError(
            f"{field_name} must be a numeric value from 1 to 100."
        )

    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"{field_name} must be a numeric value from 1 to 100."
        ) from exc

    if not 1 <= numeric <= 100:
        raise ValueError(
            f"{field_name} must be between 1 and 100."
        )

    return numeric


def build_user_component_inputs(
    available_space,
    water_availability,
    project_budget,
    maintenance_capacity,
):
    values = {
        "available_space": available_space,
        "water_availability": water_availability,
        "project_budget": project_budget,
        "maintenance_capacity": maintenance_capacity,
    }

    return {
        USER_NUMERIC_INPUTS[field]:
            _validate_1_to_100(value, field)
        for field, value in values.items()
    }


def merge_user_component_inputs(
    existing_component_inputs,
    user_component_inputs,
):
    merged = dict(existing_component_inputs or {})
    merged.update(user_component_inputs or {})
    return merged
