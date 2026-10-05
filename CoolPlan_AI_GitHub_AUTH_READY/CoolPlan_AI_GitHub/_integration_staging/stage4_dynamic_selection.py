from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

import pandas as pd


REQUIRED_STAGE3_COLUMNS = [
    "stage2_row",
    "feature_label",
    "interpreted_feature",
    "standard_feature",
    "feature_group",
    "feature_handle",
    "feature_layer",
    "zone_id",
    "HPS",
    "HPS_class",
    "LST_C",
    "NDVI",
    "NDBI",
    "VEGETATION_DEFICIT",
    "overlap_area_cad_units2",
    "zone_overlap_fraction",
    "feature_overlap_fraction",
    "association_method",
    "review_status",
]


def validate_stage3_dataframe(stage3_df: pd.DataFrame) -> None:
    """Validate the frozen Stage 3 dataframe contract."""

    if not isinstance(stage3_df, pd.DataFrame):
        raise TypeError(
            "Stage 3 result must be a pandas DataFrame."
        )

    missing = [
        column
        for column in REQUIRED_STAGE3_COLUMNS
        if column not in stage3_df.columns
    ]

    if missing:
        raise ValueError(
            "Stage 3 result is missing required columns: "
            + ", ".join(missing)
        )


def _clean(value: Any) -> str:
    if value is None:
        return ""

    if pd.isna(value):
        return ""

    return str(value).strip()


def _numeric(value: Any):
    try:
        if value is None or pd.isna(value):
            return None

        number = float(value)

        if pd.isna(number):
            return None

        return number

    except (TypeError, ValueError):
        return None


def _unique_clean(values) -> List[str]:
    result = []

    for value in values:
        cleaned = _clean(value)

        if cleaned and cleaned not in result:
            result.append(cleaned)

    return result


def _aggregate_numeric(
    rows: pd.DataFrame,
    column: str,
    method: str,
):
    values = [
        _numeric(value)
        for value in rows[column].tolist()
    ]

    values = [
        value
        for value in values
        if value is not None
    ]

    if not values:
        return None

    if method == "max":
        return max(values)

    if method == "min":
        return min(values)

    if method == "mean":
        return sum(values) / len(values)

    raise ValueError(
        f"Unsupported aggregation method: {method}"
    )


def _environmental_issues(
    hps,
    lst_c,
    ndvi,
    ndbi,
    vegetation_deficit,
) -> List[str]:
    """
    Derive only descriptive environmental flags from
    values already present in Stage 3.

    No fixed site thresholds are introduced here.
    """

    issues = []

    if hps is not None:
        issues.append("heat_priority_present")

    if lst_c is not None:
        issues.append("surface_temperature_present")

    if ndvi is not None:
        issues.append("vegetation_signal_present")

    if vegetation_deficit is not None:
        issues.append("vegetation_deficit_present")

    if ndbi is not None:
        issues.append("built_up_signal_present")

    return issues


def _feature_records(rows: pd.DataFrame) -> List[Dict[str, Any]]:
    records = []

    for _, row in rows.iterrows():

        records.append(
            {
                "stage2_row": _clean(
                    row["stage2_row"]
                ),
                "feature_label": _clean(
                    row["feature_label"]
                ),
                "interpreted_feature": _clean(
                    row["interpreted_feature"]
                ),
                "standard_feature": _clean(
                    row["standard_feature"]
                ),
                "feature_group": _clean(
                    row["feature_group"]
                ),
                "feature_handle": _clean(
                    row["feature_handle"]
                ),
                "feature_layer": _clean(
                    row["feature_layer"]
                ),
                "review_status": _clean(
                    row["review_status"]
                ),
            }
        )

    return records


def build_stage4_selection(
    stage3_df: pd.DataFrame,
) -> Dict[str, Any]:
    """
    Build a dynamic Stage 4 selection context from
    the current Stage 3 runtime results.

    This function does not use hard-coded zone IDs,
    environmental values, or feature-to-intervention
    mappings.
    """

    validate_stage3_dataframe(stage3_df)

    working = stage3_df.copy()

    working["zone_id"] = (
        working["zone_id"]
        .astype(str)
        .str.strip()
    )

    # A row is usable for zone-level Stage 4 selection
    # only when Stage 3 supplied both a zone and HPS.
    usable_mask = (
        working["zone_id"].ne("")
        & working["zone_id"].ne("nan")
        & working["HPS"].apply(
            lambda value: _numeric(value) is not None
        )
    )

    usable = working.loc[usable_mask].copy()
    review_required = working.loc[~usable_mask].copy()

    zones = []

    for zone_id, zone_rows in usable.groupby(
        "zone_id",
        sort=True,
    ):

        hps = _aggregate_numeric(
            zone_rows,
            "HPS",
            "max",
        )

        lst_c = _aggregate_numeric(
            zone_rows,
            "LST_C",
            "max",
        )

        ndvi = _aggregate_numeric(
            zone_rows,
            "NDVI",
            "min",
        )

        ndbi = _aggregate_numeric(
            zone_rows,
            "NDBI",
            "max",
        )

        vegetation_deficit = _aggregate_numeric(
            zone_rows,
            "VEGETATION_DEFICIT",
            "max",
        )

        hps_classes = _unique_clean(
            zone_rows["HPS_class"].tolist()
        )

        features = _feature_records(zone_rows)

        standard_features = _unique_clean(
            zone_rows["standard_feature"].tolist()
        )

        feature_groups = _unique_clean(
            zone_rows["feature_group"].tolist()
        )

        issues = _environmental_issues(
            hps=hps,
            lst_c=lst_c,
            ndvi=ndvi,
            ndbi=ndbi,
            vegetation_deficit=vegetation_deficit,
        )

        zones.append(
            {
                "zone_id": zone_id,
                "original_hps": hps,
                "hps_class": (
                    hps_classes[0]
                    if hps_classes
                    else ""
                ),
                "lst_c": lst_c,
                "ndvi": ndvi,
                "ndbi": ndbi,
                "vegetation_deficit": vegetation_deficit,
                "standard_features": standard_features,
                "feature_groups": feature_groups,
                "features": features,
                "environmental_issues": issues,
                "stage3_row_count": int(
                    len(zone_rows)
                ),
                "stage3_source_rows": [
                    _clean(value)
                    for value in zone_rows[
                        "stage2_row"
                    ].tolist()
                ],
                "screening_status": (
                    "READY_FOR_INTERVENTION_ASSESSMENT"
                ),
                "intervention_candidates": [],
                "intervention_selection_status": (
                    "NOT_ASSIGNED"
                ),
            }
        )

    result = {
        "stage4_version": "dynamic_stage3_only_v2",
        "source": "current_stage3_runtime_results",
        "zones": zones,
        "review_required_rows": int(
            len(review_required)
        ),
        "usable_stage3_rows": int(
            len(usable)
        ),
        "zone_count": int(
            len(zones)
        ),
        "intervention_mapping_status": (
            "NOT_ASSIGNED"
        ),
    }

    return result


def build_stage4_dataframe(
    stage3_df: pd.DataFrame,
) -> pd.DataFrame:
    """Return one dynamic Stage 4 row per usable Stage 3 zone."""

    result = build_stage4_selection(
        stage3_df
    )

    rows = []

    for zone in result["zones"]:

        rows.append(
            {
                "zone_id": zone["zone_id"],
                "HPS": zone["original_hps"],
                "HPS_class": zone["hps_class"],
                "LST_C": zone["lst_c"],
                "NDVI": zone["ndvi"],
                "NDBI": zone["ndbi"],
                "VEGETATION_DEFICIT": zone[
                    "vegetation_deficit"
                ],
                "standard_features": "; ".join(
                    zone["standard_features"]
                ),
                "feature_groups": "; ".join(
                    zone["feature_groups"]
                ),
                "environmental_issues": "; ".join(
                    zone["environmental_issues"]
                ),
                "stage3_row_count": zone[
                    "stage3_row_count"
                ],
                "screening_status": zone[
                    "screening_status"
                ],
                "intervention_candidates": "",
                "intervention_selection_status": zone[
                    "intervention_selection_status"
                ],
            }
        )

    return pd.DataFrame(rows)


def build_stage4_task_context(
    stage4_result: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """
    Convert Stage 4 zone results into compact contexts
    for the Workflow 09 intervention-proposal stage.

    No intervention is invented here.
    """

    tasks = []

    for zone in stage4_result.get("zones", []):

        tasks.append(
            {
                "zone_id": zone["zone_id"],
                "identified_features": zone[
                    "features"
                ],
                "environmental_issues": zone[
                    "environmental_issues"
                ],
                "environmental_evidence": {
                    "HPS": zone["original_hps"],
                    "HPS_class": zone["hps_class"],
                    "LST_C": zone["lst_c"],
                    "NDVI": zone["ndvi"],
                    "NDBI": zone["ndbi"],
                    "VEGETATION_DEFICIT": zone[
                        "vegetation_deficit"
                    ],
                },
                "intervention_candidates": [],
                "status": (
                    "PENDING_INTERVENTION_SELECTION"
                ),
            }
        )

    return tasks
