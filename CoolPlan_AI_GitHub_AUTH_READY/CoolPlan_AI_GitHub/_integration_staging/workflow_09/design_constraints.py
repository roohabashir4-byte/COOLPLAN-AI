"""Design-stage constraints for CoolPlan AI.

This module is separate from the working application.
"""

CONSTRAINT_OPTIONS = {
    "available_space": [
        "Available",
        "Limited",
        "Not available",
    ],
    "water_availability": [
        "Adequate",
        "Limited",
        "Not available",
    ],
    "project_budget": [
        "Low",
        "Moderate",
        "High",
    ],
    "maintenance_capacity": [
        "Low",
        "Moderate",
        "High",
    ],
}


def validate_design_constraints(constraints):
    """Validate that all four design-stage selections are provided."""

    if not isinstance(constraints, dict):
        raise TypeError("Constraints must be provided as a dictionary.")

    errors = []

    for field, options in CONSTRAINT_OPTIONS.items():
        value = constraints.get(field)

        if value not in options:
            errors.append(
                f"{field}: select one of {', '.join(options)}"
            )

    if errors:
        raise ValueError("Invalid design constraints:\n- " + "\n- ".join(errors))

    return True
