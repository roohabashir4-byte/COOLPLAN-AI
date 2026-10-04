
"""Workflow 05: manual boundary placement utilities."""

import json
from pathlib import Path

import numpy as np
from pyproj import Transformer
from shapely.geometry import Polygon, mapping


def place_boundary(
    cad_points,
    target_longitude,
    target_latitude,
    scale_m_per_unit,
    rotation_degrees=0.0,
):
    """
    Place CAD boundary coordinates around a selected map location.

    scale_m_per_unit:
        Number of projected metres per CAD drawing unit.
        This must be chosen/verified by the user.

    rotation_degrees:
        Counter-clockwise rotation in projected map coordinates.
    """
    if len(cad_points) < 3:
        raise ValueError("Boundary must contain at least 3 points.")

    if scale_m_per_unit <= 0:
        raise ValueError("Scale must be greater than zero.")

    points = np.asarray(cad_points, dtype=float)

    if points.ndim != 2 or points.shape[1] != 2:
        raise ValueError("CAD points must be X/Y coordinate pairs.")

    if not np.isfinite(points).all():
        raise ValueError("Boundary contains invalid coordinates.")

    # Select the UTM zone from the target location.
    zone = int((float(target_longitude) + 180) // 6) + 1
    zone = max(1, min(zone, 60))
    hemisphere = "326" if float(target_latitude) >= 0 else "327"
    utm_epsg = f"EPSG:{hemisphere}{zone:02d}"

    to_utm = Transformer.from_crs(
        "EPSG:4326", utm_epsg, always_xy=True
    )
    center_e, center_n = to_utm.transform(
        float(target_longitude), float(target_latitude)
    )

    # Work relative to the CAD boundary's centroid.
    centroid = points.mean(axis=0)
    local = (points - centroid) * float(scale_m_per_unit)

    angle = np.radians(float(rotation_degrees))
    rotation = np.array([
        [np.cos(angle), -np.sin(angle)],
        [np.sin(angle),  np.cos(angle)],
    ])

    rotated = local @ rotation.T
    projected = rotated + np.array([center_e, center_n])

    polygon = Polygon(projected)

    if not polygon.is_valid or polygon.is_empty:
        raise ValueError("Placed boundary is not a valid polygon.")

    to_wgs84 = Transformer.from_crs(
        utm_epsg, "EPSG:4326", always_xy=True
    )

    geographic = [
        to_wgs84.transform(float(x), float(y))
        for x, y in polygon.exterior.coords
    ]

    geographic_polygon = Polygon(geographic)

    return {
        "geometry": mapping(geographic_polygon),
        "target_crs": "EPSG:4326",
        "projected_crs": utm_epsg,
        "placement": {
            "center_longitude": float(target_longitude),
            "center_latitude": float(target_latitude),
            "scale_m_per_unit": float(scale_m_per_unit),
            "rotation_degrees": float(rotation_degrees),
            "status": "approximate_manual_placement",
        },
    }


def save_placement(result, output_path):
    """Save the placement result as JSON."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open("w", encoding="utf-8") as file:
        json.dump(result, file, indent=2)
