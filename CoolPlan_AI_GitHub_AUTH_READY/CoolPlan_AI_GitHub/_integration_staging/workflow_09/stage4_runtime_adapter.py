
"""
CoolPlan AI — Workflow 09 Stage 4 Runtime Adapter

Purpose:
    Consume the EXISTING Stage 3 runtime outputs and run
    Workflow 09 intervention screening.

Important:
    - Does not rerun Stage 2.
    - Does not rerun Stage 3.
    - Does not modify environmental values.
    - Does not calculate a new HPS.
    - Does not identify CAD features.
    - Uses the Stage 3 association_df exactly as supplied.
    - Uses the existing zones_geojson exactly as supplied.
    - Keeps Workflow 09 screening deterministic.
"""

from copy import deepcopy
from typing import Any, Dict

import pandas as pd

from intervention_screening import screen_zones


REQUIRED_STAGE3_COLUMNS = [
    "zone_id",
    "standard_feature",
    "interpreted_feature",
    "feature_group",
    "HPS",
    "HPS_class",
    "LST_C",
    "NDVI",
    "NDBI",
    "VEGETATION_DEFICIT",
]


def validate_stage3_result(
    stage3_result: Dict[str, Any]
) -> pd.DataFrame:
    """
    Validate and return the existing Stage 3 association DataFrame.

    No values are recalculated.
    """

    if not isinstance(
        stage3_result,
        dict
    ):
        raise ValueError(
            "stage3_result must be a dictionary."
        )

    association_df = stage3_result.get(
        "association_df"
    )

    if not isinstance(
        association_df,
        pd.DataFrame
    ):
        raise ValueError(
            "Stage 3 result does not contain "
            "association_df as a pandas DataFrame."
        )

    missing = [
        column
        for column in REQUIRED_STAGE3_COLUMNS
        if column not in association_df.columns
    ]

    if missing:
        raise ValueError(
            "Stage 3 association_df is missing required "
            "columns: "
            + ", ".join(missing)
        )

    return association_df.copy()


def build_zone_feature_map(
    association_df: pd.DataFrame
) -> Dict[str, Dict[str, Any]]:
    """
    Build the Workflow 09 zone-to-feature input from the
    already-confirmed Stage 3 associations.

    No new feature classification is performed.
    """

    zone_features = {}

    usable = association_df[
        association_df[
            "zone_id"
        ].astype(str).str.strip().ne("")
        &
        association_df[
            "zone_id"
        ].astype(str).str.lower().ne("nan")
    ].copy()

    for zone_id, group in usable.groupby(
        "zone_id",
        sort=False
    ):

        features = []
        seen = set()

        for _, row in group.iterrows():

            feature_name = str(
                row.get(
                    "standard_feature",
                    ""
                )
            ).strip()

            if not feature_name:

                feature_name = str(
                    row.get(
                        "interpreted_feature",
                        ""
                    )
                ).strip()

            if not feature_name:
                continue

            key = feature_name.casefold()

            if key in seen:
                continue

            seen.add(key)

            features.append(
                {
                    "feature": feature_name,
                    "feature_confidence":
                        "Stage3_confirmed",
                }
            )

        zone_features[
            str(zone_id)
        ] = {
            "features": features
        }

    return zone_features


def run_stage4_from_stage3(
    stage3_result: Dict[str, Any],
    zones_geojson: Dict[str, Any],
    constraints: Dict[str, Any] | None = None,
    percentile_cutoff: float = 0.75,
) -> Dict[str, Any]:
    """
    Run Workflow 09 Stage 4 directly from current Stage 3
    runtime results.

    Environmental values come from zones_geojson.
    Feature associations come from Stage 3 association_df.
    """

    if not isinstance(
        zones_geojson,
        dict
    ):
        raise ValueError(
            "zones_geojson must be a GeoJSON dictionary."
        )

    if zones_geojson.get(
        "type"
    ) != "FeatureCollection":

        raise ValueError(
            "zones_geojson must be a "
            "GeoJSON FeatureCollection."
        )

    association_df = validate_stage3_result(
        stage3_result
    )

    zone_features = build_zone_feature_map(
        association_df
    )

    screening_result = screen_zones(
        geojson=deepcopy(
            zones_geojson
        ),
        zone_features=zone_features,
        constraints=(
            constraints
            or {}
        ),
        percentile_cutoff=percentile_cutoff,
    )

    # --------------------------------------------------------
    # Build clean Stage 4 records for downstream Stage 5.
    # --------------------------------------------------------

    stage4_zones = []

    for feature in screening_result.get(
        "features",
        []
    ):

        properties = feature.get(
            "properties",
            {}
        )

        screening = properties.get(
            "intervention_screening",
            {}
        )

        zone_id = screening.get(
            "zone_id"
        )

        if not zone_id:
            continue

        candidates = screening.get(
            "eligible_interventions",
            []
        )

        stage4_zones.append(
            {
                "zone_id":
                    zone_id,

                "status":
                    screening.get(
                        "status"
                    ),

                "screening_reason":
                    screening.get(
                        "screening_reason"
                    ),

                "HPS":
                    screening.get(
                        "original_hps"
                    ),

                "HPS_class":
                    screening.get(
                        "original_hps_class"
                    ),

                "identified_features":
                    screening.get(
                        "identified_features",
                        []
                    ),

                "environmental_issues":
                    screening.get(
                        "environmental_issues",
                        []
                    ),

                "environmental_evidence":
                    screening.get(
                        "evidence",
                        []
                    ),

                "intervention_candidates":
                    candidates,

                "intervention_selection_status":
                    (
                        "READY_FOR_SELECTION"
                        if candidates
                        else "NO_CANDIDATE"
                    ),
            }
        )

    return {
        "stage": "Stage 4",
        "stage4_version":
            "workflow09_runtime_adapter_v1",
        "source":
            "current_stage3_runtime_results",
        "screening":
            screening_result,
        "zones":
            stage4_zones,
        "zone_count":
            len(stage4_zones),
        "eligible_zone_count":
            sum(
                x["status"] == "ELIGIBLE"
                for x in stage4_zones
            ),
        "intervention_mapping_status":
            "FROM_WORKFLOW09_SCREENING",
    }
