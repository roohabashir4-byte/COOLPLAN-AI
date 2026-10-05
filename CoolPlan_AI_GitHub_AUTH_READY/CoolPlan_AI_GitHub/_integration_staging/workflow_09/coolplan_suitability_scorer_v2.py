
"""
CoolPlan AI — Intervention Suitability Scorer v2

ISS weights from the finalized CoolPlan methodology:
CP 30%, SS 20%, WC 15%, SC 15%, CF 10%, IF 10%.

Scores are deterministic and transparent.
The component-scoring rules are configurable project rules,
not universally validated engineering standards.
"""

from typing import Any, Dict, Optional


ISS_WEIGHTS = {
    "cooling_effectiveness": 0.35,
    "site_compatibility": 0.30,
    "resource_feasibility": 0.15,
    "implementation_feasibility": 0.20,
}

INTERVENTION_CONSTRAINTS = {
    "cool_roof": [
        "roof_feasibility",
        "technical_feasibility",
        "budget_available",
        "maintenance_capacity",
    ],
    "green_roof": [
        "roof_feasibility",
        "structural_feasibility",
        "technical_feasibility",
        "water_available",
        "budget_available",
        "maintenance_capacity",
    ],
    "cool_pavement": [
        "pavement_feasibility",
        "space_available",
        "technical_feasibility",
        "budget_available",
        "maintenance_capacity",
    ],
    "shade_structure": [
        "space_available",
        "technical_feasibility",
        "budget_available",
        "maintenance_capacity",
    ],
    "strategic_vegetation": [
        "space_available",
        "technical_feasibility",
        "water_available",
        "budget_available",
        "maintenance_capacity",
    ],
    "permeable_green_infrastructure": [
        "space_available",
        "infiltration_drainage_feasibility",
        "technical_feasibility",
        "budget_available",
        "maintenance_capacity",
    ],
}

VALID_CONSTRAINT_VALUES = {"yes", "limited", "no", "unknown"}

# A score of 100 means the criterion is fully supported by available evidence.
# "limited" is represented as 50 only where a criterion uses this scale.
LIMITED_SCORE = 50.0


def _validate_score(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{name} must be a numeric score from 0 to 100.")

    value = float(value)
    if not 0 <= value <= 100:
        raise ValueError(f"{name} must be between 0 and 100.")

    return value


def score_cooling_potential(
    environmental_need: float,
    intervention_response: float,
) -> float:
    """
    CP:
    - environmental_need: severity/relevance of the identified cooling need
    - intervention_response: evidence-based relevance of this intervention
      to that need

    Both inputs are 0–100. Equal weighting is a transparent initial rule.
    """
    need = _validate_score(environmental_need, "environmental_need")
    response = _validate_score(intervention_response, "intervention_response")
    return (need + response) / 2


def score_site_suitability(
    feature_compatibility: float,
    site_function_compatibility: float,
) -> float:
    """
    SS:
    - feature_compatibility: match to the confirmed physical feature
    - site_function_compatibility: match to how that feature is used

    Both inputs are 0–100. Incompatible candidates should normally be
    removed during eligibility screening rather than ranked.
    """
    feature = _validate_score(feature_compatibility, "feature_compatibility")
    function = _validate_score(
        site_function_compatibility, "site_function_compatibility"
    )
    return (feature + function) / 2


def score_water_compatibility(
    water_demand_compatibility: float,
) -> float:
    """
    WC:
    Score reflects how well the intervention's water demand matches
    documented site water availability. Use 0–100 evidence-based input.
    For interventions with no material water requirement, use 100 only
    when that assumption is documented for the specific option.
    """
    return _validate_score(
        water_demand_compatibility, "water_demand_compatibility"
    )


def score_space_compatibility(
    spatial_fit: float,
) -> float:
    """
    SC:
    Score reflects available suitable area, layout, access, and conflicts.
    A confirmed critical space conflict should be handled as a hard
    constraint, not hidden by this score.
    """
    return _validate_score(spatial_fit, "spatial_fit")


def score_cost_feasibility(
    budget_fit: float,
) -> float:
    """
    CF:
    Score reflects fit with the user's/project's available budget.
    Do not infer actual construction cost without cost data.
    """
    return _validate_score(budget_fit, "budget_fit")


def score_implementation_feasibility(
    technical_feasibility: float,
    operational_feasibility: float,
    maintenance_feasibility: float,
) -> float:
    """
    IF:
    Equal-weight average of technical, operational, and maintenance
    feasibility. These subweights are configurable in a later revision
    if the project establishes a documented rationale.
    """
    values = [
        _validate_score(technical_feasibility, "technical_feasibility"),
        _validate_score(operational_feasibility, "operational_feasibility"),
        _validate_score(maintenance_feasibility, "maintenance_feasibility"),
    ]
    return sum(values) / len(values)


def check_hard_constraints(
    intervention: str,
    constraints: Dict[str, str],
) -> Dict[str, Any]:
    """
    Only constraints listed for this intervention are evaluated.

    'no'      -> excluded
    'unknown' or missing -> pending
    'yes'     -> passes
    'limited' -> requires review; not automatically treated as a pass
    """
    if intervention not in INTERVENTION_CONSTRAINTS:
        return {
            "status": "UNKNOWN_INTERVENTION",
            "failed": [],
            "unknown": [],
            "limited": [],
            "applicable": [],
        }

    applicable = INTERVENTION_CONSTRAINTS[intervention]
    failed, unknown, limited = [], [], []

    for key in applicable:
        value = str(constraints.get(key, "unknown")).strip().lower()

        if value not in VALID_CONSTRAINT_VALUES:
            raise ValueError(
                f"Invalid value for constraint '{key}': {value!r}. "
                f"Use one of {sorted(VALID_CONSTRAINT_VALUES)}."
            )

        if value == "no":
            failed.append(key)
        elif value == "unknown":
            unknown.append(key)
        elif value == "limited":
            limited.append(key)

    if failed:
        status = "EXCLUDED_HARD_CONSTRAINT"
    elif unknown:
        status = "PENDING_CONSTRAINTS"
    elif limited:
        status = "REQUIRES_REVIEW"
    else:
        status = "ELIGIBLE"

    return {
        "status": status,
        "failed": failed,
        "unknown": unknown,
        "limited": limited,
        "applicable": applicable,
    }


def calculate_iss(component_scores: Dict[str, float]) -> Dict[str, Any]:
    """
    Calculate ISS using the four-category weights.

    All four category scores must be supplied. Missing scores are not silently
    redistributed across the remaining weights.
    """
    missing = [key for key in ISS_WEIGHTS if key not in component_scores]
    if missing:
        raise ValueError(f"Missing ISS components: {missing}")

    scores = {
        key: _validate_score(component_scores[key], key)
        for key in ISS_WEIGHTS
    }

    contributions = {
        key: scores[key] * weight
        for key, weight in ISS_WEIGHTS.items()
    }

    iss = sum(contributions.values())

    return {
        "ISS": round(iss, 2),
        "component_scores": scores,
        "weights": dict(ISS_WEIGHTS),
        "weighted_contributions": {
            key: round(value, 2)
            for key, value in contributions.items()
        },
        "weight_total": round(sum(ISS_WEIGHTS.values()), 4),
        "interpretation": (
            "Weighted suitability score, not a predicted temperature "
            "reduction or a validated probability of success."
        ),
    }


def score_intervention(
    intervention: str,
    constraints: Dict[str, str],
    component_inputs: Dict[str, float],
) -> Dict[str, Any]:
    """
    Check constraints first. Calculate ISS only when all applicable
    constraints are confirmed 'yes'. A 'limited' constraint requires
    review; it is not silently converted into an eligible result.
    """
    constraint_result = check_hard_constraints(intervention, constraints)

    if constraint_result["status"] != "ELIGIBLE":
        return {
            "intervention": intervention,
            "status": constraint_result["status"],
            "constraint_check": constraint_result,
            "ISS": None,
            "reason": (
                "Suitability score withheld until eligibility and "
                "applicable constraints are resolved."
            ),
        }

    # Category 1: Cooling Effectiveness (35%)
    cooling_effectiveness = score_cooling_potential(
        component_inputs["environmental_need"],
        component_inputs["intervention_response"],
    )

    # Category 2: Site Compatibility (30%)
    site_compatibility = (
        _validate_score(
            component_inputs["feature_compatibility"],
            "feature_compatibility",
        )
        + _validate_score(
            component_inputs["site_function_compatibility"],
            "site_function_compatibility",
        )
        + score_space_compatibility(component_inputs["spatial_fit"])
    ) / 3

    # Category 3: Resource Feasibility (15%)
    resource_feasibility = score_water_compatibility(
        component_inputs["water_demand_compatibility"]
    )

    # Category 4: Implementation Feasibility (20%)
    # Includes budget, technical, operational, and maintenance factors.
    implementation_values = [
        score_cost_feasibility(component_inputs["budget_fit"]),
        _validate_score(
            component_inputs["technical_feasibility"],
            "technical_feasibility",
        ),
        _validate_score(
            component_inputs["operational_feasibility"],
            "operational_feasibility",
        ),
        _validate_score(
            component_inputs["maintenance_feasibility"],
            "maintenance_feasibility",
        ),
    ]
    implementation_feasibility = (
        sum(implementation_values) / len(implementation_values)
    )

    result = calculate_iss({
        "cooling_effectiveness": cooling_effectiveness,
        "site_compatibility": site_compatibility,
        "resource_feasibility": resource_feasibility,
        "implementation_feasibility": implementation_feasibility,
    })

    return {
        "intervention": intervention,
        "status": "SCORED",
        "constraint_check": constraint_result,
        **result,
    }
