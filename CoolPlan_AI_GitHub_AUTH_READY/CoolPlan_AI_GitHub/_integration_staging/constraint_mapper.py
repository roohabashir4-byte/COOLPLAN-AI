"""Map project-level design selections for CoolPlan AI."""

from design_constraints import validate_design_constraints


def map_design_constraints(selections):
    """Validate and normalize the four design-stage selections."""

    validate_design_constraints(selections)

    space_mapping = {
        "Available": "yes",
        "Limited": "limited",
        "Not available": "no",
    }

    water_mapping = {
        "Adequate": "yes",
        "Limited": "limited",
        "Not available": "no",
    }

    return {
        "project_constraints": {
            "space_available": space_mapping[
                selections["available_space"]
            ],
            "water_available": water_mapping[
                selections["water_availability"]
            ],
        },
        "project_context": {
            "project_budget": selections["project_budget"],
            "maintenance_capacity": selections["maintenance_capacity"],
        },
        "mapping_notes": {
            "budget": (
                "Assess affordability against the specific intervention's "
                "cost requirements."
            ),
            "maintenance": (
                "Assess capacity against the specific intervention's "
                "maintenance requirements."
            ),
            "feature_specific_constraints": (
                "Roof, structural, pavement, drainage, and technical "
                "feasibility must be assessed separately."
            ),
        },
    }
