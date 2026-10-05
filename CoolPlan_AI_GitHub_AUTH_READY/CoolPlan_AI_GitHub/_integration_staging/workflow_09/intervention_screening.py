
"""
CoolPlan AI — intervention-potential screening

Standalone, deterministic screening stage.

Input:
  - GeoJSON FeatureCollection of individual environmental zones.
  - Optional zone-to-feature mapping keyed by zone_id.
  - Optional constraints dictionary.

Important:
  - Does NOT modify HPS or any input properties.
  - Does NOT use grouped HPS.
  - Does NOT make final intervention recommendations or suitability scores.
  - Uses transparent within-site percentile flags for environmental indicators.
    These are screening heuristics, not regulatory or engineering thresholds.
"""

from copy import deepcopy
from typing import Any, Dict, List, Optional


INDICATORS = {
    "LST_C": "high_surface_heat",
    "NDBI": "high_built_up_signal",
    "VEGETATION_DEFICIT": "vegetation_deficiency",
    "NDVI": "low_vegetation_signal",
}


# Candidate categories recovered from the original Workflow 09 screening
# implementation.
FEATURE_CANDIDATES = {
    "building": [
        "cool_roof",
        "green_roof",
    ],
    "roof": [
        "cool_roof",
        "green_roof",
    ],
    "road": [
        "cool_pavement",
        "strategic_vegetation",
    ],
    "parking": [
        "shade_structure",
        "cool_pavement",
        "permeable_green_infrastructure",
        "strategic_vegetation",
    ],
    "footpath": [
        "shade_structure",
        "cool_pavement",
        "strategic_vegetation",
    ],
    "pedestrian": [
        "shade_structure",
        "cool_pavement",
        "strategic_vegetation",
    ],
    "walkway": [
        "shade_structure",
        "cool_pavement",
        "strategic_vegetation",
    ],
    "open green space": [
        "strategic_vegetation",
        "shade_structure",
        "permeable_green_infrastructure",
    ],
    "green space": [
        "strategic_vegetation",
        "shade_structure",
        "permeable_green_infrastructure",
    ],
    "park": [
        "strategic_vegetation",
        "shade_structure",
        "permeable_green_infrastructure",
    ],
    "sports ground": [
        "strategic_vegetation",
        "shade_structure",
    ],
    "sports court": [
        "shade_structure",
        "strategic_vegetation",
    ],
    "playground": [
        "strategic_vegetation",
        "shade_structure",
    ],
}


def _num(value):
    try:
        if value is None or isinstance(value, bool):
            return None

        return float(value)

    except (TypeError, ValueError):
        return None


def _percentile(values, value):
    """
    Empirical percentile rank in [0, 1], ties included.
    """

    if not values or value is None:
        return None

    return (
        sum(
            v <= value
            for v in values
        )
        / len(values)
    )


def _feature_candidates(
    feature: Optional[str]
) -> List[str]:

    if not feature:
        return []

    f = (
        " ".join(
            str(feature)
            .strip()
            .lower()
            .replace("_", " ")
            .split()
        )
    )

    for key, candidates in FEATURE_CANDIDATES.items():

        if key in f:
            return list(candidates)

    return []


def screen_zones(
    geojson: Dict[str, Any],
    zone_features: Optional[
        Dict[str, Dict[str, Any]]
    ] = None,
    constraints: Optional[
        Dict[str, Any]
    ] = None,
    percentile_cutoff: float = 0.75,
) -> Dict[str, Any]:
    """
    Screen zones using one or multiple confirmed features per zone.
    """

    if (
        not isinstance(geojson, dict)
        or geojson.get("type")
        != "FeatureCollection"
    ):
        raise ValueError(
            "geojson must be a GeoJSON FeatureCollection"
        )

    if not (
        0.5
        < percentile_cutoff
        < 1
    ):
        raise ValueError(
            "percentile_cutoff must be between 0.5 and 1.0"
        )

    zone_features = (
        zone_features
        or {}
    )

    constraints = (
        constraints
        or {}
    )

    features = geojson.get(
        "features",
        []
    )

    # -------------------------------------------------------------------------
    # Calculate within-site distributions from the ORIGINAL zone values.
    # -------------------------------------------------------------------------

    values_by_indicator = {}

    for field in INDICATORS:

        vals = [
            _num(
                (
                    f.get("properties")
                    or {}
                ).get(field)
            )
            for f in features
        ]

        values_by_indicator[field] = [
            v
            for v in vals
            if v is not None
        ]

    # -------------------------------------------------------------------------
    # Work on a copy.
    # -------------------------------------------------------------------------

    output = deepcopy(
        geojson
    )

    counts = {
        "ELIGIBLE": 0,
        "NO_INTERVENTION_IDENTIFIED": 0,
        "INSUFFICIENT_DATA": 0,
    }

    # -------------------------------------------------------------------------
    # Screen every environmental zone.
    # -------------------------------------------------------------------------

    for item in output.get(
        "features",
        []
    ):

        props = item.setdefault(
            "properties",
            {}
        )

        zone_id = (
            props.get("zone_id")
            or item.get("id")
        )

        matched = zone_features.get(
            str(zone_id),
            {}
        )

        # -------------------------------------------------------------
        # Recover one or multiple confirmed features for this zone.
        # -------------------------------------------------------------

        raw = matched.get(
            "features"
        )

        if raw is None:

            raw = [
                matched.get("feature")
                or matched.get(
                    "identified_feature"
                )
            ]

        if isinstance(
            raw,
            (str, dict)
        ):
            raw = [raw]

        identified = []
        seen_names = set()

        for entry in raw or []:

            if isinstance(
                entry,
                str
            ):

                name = entry.strip()

                confidence = (
                    matched.get(
                        "feature_confidence"
                    )
                )

            elif isinstance(
                entry,
                dict
            ):

                name = (
                    entry.get("feature")
                    or entry.get(
                        "identified_feature"
                    )
                    or entry.get(
                        "APPROVED_INTERPRETATION"
                    )
                    or ""
                )

                name = str(
                    name
                ).strip()

                confidence = entry.get(
                    "feature_confidence",
                    matched.get(
                        "feature_confidence"
                    )
                )

            else:
                continue

            if (
                name
                and name.casefold()
                not in seen_names
            ):

                seen_names.add(
                    name.casefold()
                )

                identified.append(
                    {
                        "feature": name,
                        "feature_confidence": confidence,
                    }
                )

        # -------------------------------------------------------------
        # Determine candidate interventions from confirmed features.
        # -------------------------------------------------------------

        breakdown = []

        all_candidates = []

        seen_candidates = set()

        for feature_info in identified:

            candidates = (
                _feature_candidates(
                    feature_info["feature"]
                )
                or []
            )

            breakdown.append(
                {
                    "feature": feature_info[
                        "feature"
                    ],
                    "feature_confidence": feature_info[
                        "feature_confidence"
                    ],
                    "candidate_interventions": candidates,
                }
            )

            for candidate in candidates:

                if candidate not in seen_candidates:

                    seen_candidates.add(
                        candidate
                    )

                    all_candidates.append(
                        candidate
                    )

        # -------------------------------------------------------------
        # Determine environmental concerns.
        # -------------------------------------------------------------

        issues = []
        evidence = []

        for field, issue_name in INDICATORS.items():

            value = _num(
                props.get(field)
            )

            rank = _percentile(
                values_by_indicator[field],
                value
            )

            if rank is None:
                continue

            concern = (
                rank >= percentile_cutoff
                if field != "NDVI"
                else rank
                <= 1 - percentile_cutoff
            )

            if concern:

                issues.append(
                    issue_name
                )

                evidence.append(
                    {
                        "indicator": field,
                        "value": value,
                        "within_site_percentile": round(
                            rank,
                            4
                        ),
                        "rule": (
                            f"{'upper' if field != 'NDVI' else 'lower'} "
                            f"{round((1 - percentile_cutoff) * 100)}% "
                            "within-site rank"
                        ),
                    }
                )

        # -------------------------------------------------------------
        # Final screening status.
        # -------------------------------------------------------------

        if (
            not identified
            or not all_candidates
        ):

            status = (
                "INSUFFICIENT_DATA"
            )

            reason = (
                "No usable identified feature "
                "or no feature-specific "
                "candidate mapping."
            )

        elif not issues:

            status = (
                "NO_INTERVENTION_IDENTIFIED"
            )

            reason = (
                "No environmental indicator "
                "crossed the configured "
                "within-site screening rank."
            )

        else:

            status = "ELIGIBLE"

            reason = (
                "Environmental concern(s) and "
                "feature-relevant candidate "
                "intervention(s) identified."
            )

        # -------------------------------------------------------------
        # Attach Workflow 09 screening result.
        # -------------------------------------------------------------

        props[
            "intervention_screening"
        ] = {

            "status": status,

            "screening_reason": reason,

            "zone_id": zone_id,

            "original_hps": props.get(
                "HPS"
            ),

            "original_hps_class": props.get(
                "HPS_class"
            ),

            "identified_feature": (
                identified[0]["feature"]
                if len(identified) == 1
                else None
            ),

            "identified_features": identified,

            "feature_confidence": (
                identified[0][
                    "feature_confidence"
                ]
                if len(identified) == 1
                else None
            ),

            "feature_candidate_breakdown":
                breakdown,

            "environmental_issues":
                issues,

            "evidence":
                evidence,

            "eligible_interventions": (
                all_candidates
                if status == "ELIGIBLE"
                else []
            ),

            "constraints_for_suitability_stage":
                deepcopy(
                    constraints
                ),

            "screening_method": {

                "type":
                    "within_site_percentile_heuristic",

                "percentile_cutoff":
                    percentile_cutoff,

                "warning":
                    (
                        "Screening heuristic only; "
                        "not a regulatory threshold "
                        "or a prediction of temperature "
                        "reduction."
                    ),
            },
        }

        counts[
            status
        ] += 1

    # -------------------------------------------------------------------------
    # Return Workflow 09 FeatureCollection.
    # -------------------------------------------------------------------------

    return {

        "type":
            "FeatureCollection",

        "name":
            "CoolPlan_Intervention_Screening",

        "features":
            output["features"],

        "screening_summary": {

            "total_zones":
                len(
                    output.get(
                        "features",
                        []
                    )
                ),

            **counts,

            "grouped_hps_used":
                False,

            "original_hps_modified":
                False,
        },
    }
