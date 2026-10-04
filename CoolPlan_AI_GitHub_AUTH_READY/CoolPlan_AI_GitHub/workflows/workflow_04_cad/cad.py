
import math
from typing import Dict, List, Tuple, Any


BOUNDARY_LAYER = "BOUNDARY"
CONNECTION_TOLERANCE = 5.0


def safe_layer(entity) -> str:
    """Safely return an entity layer name."""
    try:
        return str(entity.dxf.layer)
    except Exception:
        return ""


def xy(point) -> Tuple[float, float]:
    """Convert a CAD point to 2D coordinates."""
    return float(point[0]), float(point[1])


def get_line_points(entity) -> List[Tuple[float, float]]:
    """Return representative points for supported CAD entities."""

    points = []

    try:
        entity_type = entity.dxftype()

        if entity_type == "LINE":

            points = [
                xy(entity.dxf.start),
                xy(entity.dxf.end)
            ]

        elif entity_type == "ARC":

            center = entity.dxf.center
            radius = float(entity.dxf.radius)

            start_angle = math.radians(
                float(entity.dxf.start_angle)
            )

            end_angle = math.radians(
                float(entity.dxf.end_angle)
            )

            points = [
                (
                    float(center.x)
                    + radius * math.cos(start_angle),

                    float(center.y)
                    + radius * math.sin(start_angle)
                ),

                (
                    float(center.x)
                    + radius * math.cos(end_angle),

                    float(center.y)
                    + radius * math.sin(end_angle)
                )
            ]

        elif entity_type == "LWPOLYLINE":

            points = [
                (float(x), float(y))
                for x, y, *_ in entity.get_points()
            ]

    except Exception:
        pass

    return points


def endpoint_distance(
    point_a: Tuple[float, float],
    point_b: Tuple[float, float]
) -> float:

    return math.sqrt(
        (point_a[0] - point_b[0]) ** 2
        +
        (point_a[1] - point_b[1]) ** 2
    )


def get_boundary_entities(msp) -> List[Any]:
    """Extract entities from the main BOUNDARY layer."""

    return [
        entity
        for entity in msp
        if safe_layer(entity) == BOUNDARY_LAYER
    ]


def find_boundary_components(
    boundary_entities: List[Any],
    tolerance: float = CONNECTION_TOLERANCE
) -> List[List[int]]:
    """
    Group boundary entities into connected components
    using endpoint proximity.
    """

    if not boundary_entities:
        return []

    endpoints = []

    for entity in boundary_entities:

        points = get_line_points(entity)

        if len(points) >= 2:
            endpoints.append(
                (points[0], points[-1])
            )
        else:
            endpoints.append(
                (None, None)
            )

    visited = set()
    components = []

    for start_index in range(len(boundary_entities)):

        if start_index in visited:
            continue

        component = [start_index]
        visited.add(start_index)

        changed = True

        while changed:

            changed = False

            for i in range(len(boundary_entities)):

                if i not in component:
                    continue

                p1, p2 = endpoints[i]

                if p1 is None:
                    continue

                for j in range(len(boundary_entities)):

                    if j in visited:
                        continue

                    q1, q2 = endpoints[j]

                    if q1 is None:
                        continue

                    distances = [
                        endpoint_distance(p1, q1),
                        endpoint_distance(p1, q2),
                        endpoint_distance(p2, q1),
                        endpoint_distance(p2, q2)
                    ]

                    if min(distances) <= tolerance:

                        component.append(j)
                        visited.add(j)
                        changed = True

        components.append(component)

    return components


def find_component_open_points(
    component: List[int],
    boundary_entities: List[Any],
    tolerance: float = CONNECTION_TOLERANCE
) -> List[Dict[str, Any]]:
    """Find endpoints that are not connected to another endpoint."""

    endpoint_records = []

    for index in component:

        entity = boundary_entities[index]
        points = get_line_points(entity)

        if len(points) < 2:
            continue

        endpoint_records.append({
            "entity_index": index,
            "point": points[0]
        })

        endpoint_records.append({
            "entity_index": index,
            "point": points[-1]
        })

    open_points = []

    for record in endpoint_records:

        connected = False

        for other in endpoint_records:

            if record is other:
                continue

            if endpoint_distance(
                record["point"],
                other["point"]
            ) <= tolerance:

                connected = True
                break

        if not connected:

            if not any(
                endpoint_distance(
                    record["point"],
                    existing["point"]
                ) <= tolerance
                for existing in open_points
            ):

                open_points.append(record)

    return open_points


def analyze_cad_boundary(msp) -> Dict[str, Any]:
    """
    Analyze CAD plot-boundary geometry.

    Does NOT automatically close gaps.
    """

    boundary_entities = get_boundary_entities(msp)

    components = find_boundary_components(
        boundary_entities
    )

    component_results = []

    for number, component in enumerate(
        components,
        start=1
    ):

        points = []

        for index in component:

            points.extend(
                get_line_points(
                    boundary_entities[index]
                )
            )

        if not points:
            continue

        xs = [p[0] for p in points]
        ys = [p[1] for p in points]

        open_points = find_component_open_points(
            component,
            boundary_entities
        )

        component_results.append({

            "component_id": number,

            "entity_count": len(component),

            "min_x": min(xs),
            "max_x": max(xs),

            "min_y": min(ys),
            "max_y": max(ys),

            "width": max(xs) - min(xs),

            "height": max(ys) - min(ys),

            "closed": len(open_points) == 0,

            "open_points": [
                record["point"]
                for record in open_points
            ]
        })

    return {

        "boundary_layer": BOUNDARY_LAYER,

        "boundary_entity_count":
            len(boundary_entities),

        "component_count":
            len(component_results),

        "components":
            component_results,

        "status":
            "BOUNDARY_REQUIRES_CONFIRMATION"
            if any(
                not c["closed"]
                for c in component_results
            )
            else "BOUNDARY_CLOSED"
    }
