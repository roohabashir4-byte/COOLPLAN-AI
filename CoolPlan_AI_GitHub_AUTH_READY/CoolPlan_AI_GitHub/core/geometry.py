from shapely.geometry import shape
from shapely.validation import explain_validity


class GeometryPreparationError(Exception):
    """Raised when zone polygon geometry cannot be prepared."""


def prepare_zone_geometries(zones):
    """
    Convert GeoJSON polygons to Shapely geometries.

    Areas are planar coordinate-unit areas. They are not assumed
    to be square metres unless the source CRS/units establish that.
    Source geometries are not altered.
    """
    prepared = []
    errors = []

    for zone in zones:
        zone_id = zone["zone_id"]

        try:
            geom = shape(zone["geometry"])
        except Exception as exc:
            errors.append(f"{zone_id}: geometry could not be read: {exc}")
            continue

        if geom.is_empty:
            errors.append(f"{zone_id}: empty geometry")
            continue

        if not geom.is_valid:
            errors.append(
                f"{zone_id}: invalid geometry — "
                f"{explain_validity(geom)}"
            )
            continue

        if geom.geom_type != "Polygon":
            errors.append(
                f"{zone_id}: expected Polygon, got {geom.geom_type}"
            )
            continue

        area = float(geom.area)

        if area <= 0:
            errors.append(f"{zone_id}: non-positive polygon area")
            continue

        prepared.append({
            **zone,
            "geometry_object": geom,
            "area_coordinate_units2": area,
        })

    if errors:
        sample = "\n".join(f"- {e}" for e in errors[:25])
        raise GeometryPreparationError(
            f"{len(errors)} geometry issue(s):\n{sample}"
        )

    return prepared


def summarize_zone_areas(zones):
    """Return area statistics in the source coordinate units."""
    areas = [z["area_coordinate_units2"] for z in zones]

    return {
        "zone_count": len(zones),
        "total_area_sum": sum(areas),
        "minimum_zone_area": min(areas),
        "maximum_zone_area": max(areas),
        "mean_zone_area": sum(areas) / len(areas),
    }
