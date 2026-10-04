
import sys
from pathlib import Path

import ee


# ============================================================
# TEST CONFIGURATION
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parents[2]

TEST_LATITUDE = 31.5007
TEST_LONGITUDE = 74.2847

EXPECTED_ZONE_COUNT = 135

REQUIRED_COLUMNS = [
    "zone_id",
    "LST_C",
    "NDVI",
    "NDBI",
    "vegetation_deficit",
    "HPS",
    "HPS_class",
    "dominant_feature",
    "site_conditions",
    "activity_exposure",
]

VALID_HPS_CLASSES = {
    "Low",
    "Moderate",
    "High",
    "Very High",
    "No Data",
}


# ============================================================
# IMPORT PROJECT MODULES
# ============================================================

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.environmental import run_environmental_analysis
from core.zones import (
    classify_zone_hps,
    create_zone_grid,
    calculate_zone_values,
    zones_to_dataframe,
)


# ============================================================
# TEST 1 — HPS CLASSIFICATION
# ============================================================

def test_hps_classification():

    test_cases = {
        10: "Low",
        25: "Low",
        26: "Moderate",
        50: "Moderate",
        51: "High",
        75: "High",
        76: "Very High",
        100: "Very High",
    }

    for hps, expected in test_cases.items():

        actual = classify_zone_hps(hps)

        assert actual == expected, (
            f"HPS {hps}: expected {expected}, got {actual}"
        )

    print("✓ HPS classification test passed")


# ============================================================
# TEST 2 — FULL ENVIRONMENTAL → ZONE PIPELINE
# ============================================================

def test_zone_pipeline():

    environmental_result = run_environmental_analysis(
        latitude=TEST_LATITUDE,
        longitude=TEST_LONGITUDE,
    )

    assert environmental_result is not None
    assert "study_area" in environmental_result
    assert "lst_composite" in environmental_result
    assert "ndvi_composite" in environmental_result
    assert "ndbi_composite" in environmental_result
    assert "vegetation_deficit" in environmental_result
    assert "heat_priority" in environmental_result

    print("✓ Environmental analysis passed")

    grid = create_zone_grid(
        environmental_result["study_area"],
        cell_size_m=100,
    )

    assert grid is not None

    print("✓ Zone grid creation passed")

    zones = calculate_zone_values(
        grid,
        environmental_result,
    )

    assert zones is not None

    print("✓ Zone value calculation passed")

    zone_df = zones_to_dataframe(zones)

    assert zone_df is not None
    assert len(zone_df) == EXPECTED_ZONE_COUNT

    print(f"✓ Zone count passed: {len(zone_df)} zones")

    for column in REQUIRED_COLUMNS:

        assert column in zone_df.columns, (
            f"Missing required column: {column}"
        )

    print("✓ Required columns passed")

    assert zone_df["HPS"].notna().all()

    print("✓ HPS completeness passed")

    actual_classes = set(
        zone_df["HPS_class"].dropna().unique()
    )

    unexpected_classes = (
        actual_classes - VALID_HPS_CLASSES
    )

    assert not unexpected_classes, (
        f"Unexpected HPS classes: {unexpected_classes}"
    )

    print("✓ HPS class validation passed")

    print("\nZone distribution:")
    print(zone_df["HPS_class"].value_counts())

    print("\nSample zones:")
    print(zone_df.head())


# ============================================================
# MAIN
# ============================================================

def main():

    print("=" * 60)
    print("COOLPLAN AI — WORKFLOW 03 ZONE ENGINE TEST")
    print("=" * 60)

    print("\nInitializing Earth Engine...")

    ee.Initialize(project="cool-plan-ai")

    print("✓ Earth Engine initialized")

    print("\nRunning tests...\n")

    test_hps_classification()
    test_zone_pipeline()

    print("\n" + "=" * 60)
    print("✓ WORKFLOW 03 TEST PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
