from pathlib import Path
import json
import math


class HPSDataError(Exception):
    """Raised when HPS zone data is invalid."""


EXPECTED_CLASSES = {
    "Low": (0, 25),
    "Moderate": (26, 50),
    "High": (51, 75),
    "Very High": (76, 100),
}


def expected_hps_class(value):
    """Return the project's configured HPS class for a numeric value."""
    if value <= 25:
        return "Low"
    if value <= 50:
        return "Moderate"
    if value <= 75:
        return "High"
    if value <= 100:
        return "Very High"
    return None


def load_hps_zones(geojson_path):
    """
    Load and validate HPS zone features.

    Original geometries and source properties are retained.
    No clipping, rotation, or geometry modification is performed.
    """
    path = Path(geojson_path)

    if not path.is_file():
        raise HPSDataError(f"HPS GeoJSON not found: {path}")

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if data.get("type") != "FeatureCollection":
        raise HPSDataError("HPS input must be a FeatureCollection.")

    features = data.get("features", [])
    if not features:
        raise HPSDataError("HPS GeoJSON contains no features.")

    prepared = []
    errors = []
    seen_ids = set()

    for index, feature in enumerate(features):
        props = feature.get("properties") or {}
        geometry = feature.get("geometry")

        zone_id = props.get("zone_id")
        hps_raw = props.get("HPS")
        hps_class = props.get("HPS_class")

        if zone_id is None or str(zone_id).strip() == "":
            errors.append(f"Feature {index}: missing zone_id")
            continue

        zone_id = str(zone_id).strip()

        if zone_id in seen_ids:
            errors.append(f"Feature {index}: duplicate zone_id {zone_id}")
        seen_ids.add(zone_id)

        if not isinstance(geometry, dict):
            errors.append(f"Zone {zone_id}: missing geometry")
            continue

        if geometry.get("type") != "Polygon":
            errors.append(
                f"Zone {zone_id}: expected Polygon, "
                f"found {geometry.get('type')}"
            )
            continue

        coordinates = geometry.get("coordinates")
        if not coordinates or not coordinates[0]:
            errors.append(f"Zone {zone_id}: empty polygon coordinates")
            continue

        try:
            hps = float(hps_raw)
        except (TypeError, ValueError):
            errors.append(f"Zone {zone_id}: HPS is not numeric")
            continue

        if not math.isfinite(hps) or not 0 <= hps <= 100:
            errors.append(f"Zone {zone_id}: HPS outside 0–100")
            continue

        calculated_class = expected_hps_class(hps)
        if calculated_class is None:
            errors.append(f"Zone {zone_id}: cannot assign HPS class")
            continue

        if hps_class is None:
            errors.append(f"Zone {zone_id}: missing HPS_class")
            continue

        if str(hps_class).strip().lower() != calculated_class.lower():
            errors.append(
                f"Zone {zone_id}: source class '{hps_class}' "
                f"does not match HPS {hps} "
                f"(expected '{calculated_class}')"
            )

        prepared.append({
            "zone_id": zone_id,
            "hps": hps,
            "hps_class": str(hps_class).strip(),
            "calculated_hps_class": calculated_class,
            "geometry": geometry,
            "properties": props,
            "source_feature_index": index,
        })

    if errors:
        preview = "\n".join(f"- {error}" for error in errors[:30])
        remaining = len(errors) - 30
        if remaining > 0:
            preview += f"\n- ...and {remaining} more error(s)"
        raise HPSDataError(
            f"HPS validation found {len(errors)} issue(s):\n{preview}"
        )

    return prepared


def summarize_hps_zones(zones):
    """Summarize validated zones without changing source data."""
    class_counts = {}

    for zone in zones:
        label = zone["hps_class"]
        class_counts[label] = class_counts.get(label, 0) + 1

    values = [zone["hps"] for zone in zones]

    return {
        "zone_count": len(zones),
        "unique_zone_ids": len({z["zone_id"] for z in zones}),
        "minimum_hps": min(values),
        "maximum_hps": max(values),
        "mean_hps_unweighted": sum(values) / len(values),
        "class_counts": class_counts,
    }
