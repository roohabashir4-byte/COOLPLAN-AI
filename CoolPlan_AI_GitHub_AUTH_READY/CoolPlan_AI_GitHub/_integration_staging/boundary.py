
from pathlib import Path
import ezdxf
from shapely.geometry import Polygon


def extract_boundary(dxf_path, layer_name="BOUNDARY"):
    """Extract one valid, closed boundary polyline from a DXF."""

    path = Path(dxf_path)
    if not path.exists():
        raise FileNotFoundError(f"DXF file not found: {path}")

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    candidates = []

    for entity in msp:
        if entity.dxftype() == "LWPOLYLINE":
            if str(entity.dxf.layer).upper() != layer_name.upper():
                continue
            if not entity.closed:
                continue

            points = [
                (float(p[0]), float(p[1]))
                for p in entity.get_points("xy")
            ]

        elif entity.dxftype() == "POLYLINE":
            if str(entity.dxf.layer).upper() != layer_name.upper():
                continue
            if not entity.is_closed:
                continue

            points = [
                (float(v.dxf.location.x), float(v.dxf.location.y))
                for v in entity.vertices
            ]
        else:
            continue

        if len(points) < 3:
            continue

        polygon = Polygon(points)
        if polygon.is_valid and not polygon.is_empty and polygon.area > 0:
            candidates.append({
                "handle": entity.dxf.handle,
                "layer": str(entity.dxf.layer),
                "points": points,
                "area": float(polygon.area),
                "bounds": tuple(float(v) for v in polygon.bounds),
            })

    if not candidates:
        raise ValueError(
            f"No valid closed boundary polyline found on layer '{layer_name}'."
        )

    if len(candidates) > 1:
        candidates.sort(key=lambda item: item["area"], reverse=True)

    result = candidates[0]
    result["candidate_count"] = len(candidates)
    return result
