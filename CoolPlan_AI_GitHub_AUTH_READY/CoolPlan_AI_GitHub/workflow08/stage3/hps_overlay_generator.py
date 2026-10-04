"""
CoolPlan AI
Workflow 08 — Stage 3
HPS Overlay + Feature-to-Zone Association

This module is intentionally separate from app.py.

Responsibilities:
    1. Read the current environmental zones.
    2. Read the current Test Project boundary.
    3. Apply the established Workflow 06 CAD placement.
    4. Generate current HPS zone geometry.
    5. Overlay current HPS zones on the current master-plan DXF.
    6. Associate current Stage 2 CAD features with current HPS zones.
    7. Save the generated DXF and association CSV.

Important:
    - No Stage 3 result is hardcoded.
    - Existing Stage 3 CSV outputs are NOT used as current results.
    - Existing environmental HPS values are preserved.
    - Stage 1 and Stage 2 are not modified.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple
import json
import os
import math
import re
import requests

import ezdxf
import pandas as pd

from shapely.geometry import Point, Polygon, shape
from shapely.ops import transform
from shapely.geometry import Polygon

try:
    from pyproj import Transformer
except Exception:
    Transformer = None


# ============================================================
# CONSTANTS
# ============================================================

WGS84_EPSG = "EPSG:4326"
UTM43N_EPSG = "EPSG:32643"

DEFAULT_MASTER_UNITS_PER_SURVEY_UNIT = 12.0
DEFAULT_SURVEY_METRES_PER_UNIT = 0.3048

FEATURE_NEAREST_TOLERANCE = 150.0


# ============================================================
# HELPERS
# ============================================================

def _safe_name(value: Any) -> str:
    text = str(value).strip().upper()
    text = re.sub(r"[^A-Z0-9_]+", "_", text)
    text = re.sub(r"_+", "_", text)
    return text.strip("_") or "UNKNOWN"


def _read_geojson(path_or_data: Any) -> Dict[str, Any]:
    if isinstance(path_or_data, dict):
        return path_or_data

    path = Path(path_or_data)

    if not path.exists():
        raise FileNotFoundError(f"GeoJSON not found: {path}")

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _iter_features(geojson: Dict[str, Any]):
    for feature in geojson.get("features", []):
        geometry = feature.get("geometry")
        properties = feature.get("properties") or {}
        if geometry:
            yield feature, properties, geometry


def _get_zone_id(properties: Dict[str, Any]) -> Optional[str]:
    for key in (
        "zone_id",
        "ZONE_ID",
        "zone",
        "ZONE",
        "id",
        "ID",
    ):
        value = properties.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()

    return None


def _find_property(properties: Dict[str, Any], names: Iterable[str], default=None):
    lowered = {
        str(k).strip().casefold(): v
        for k, v in properties.items()
    }

    for name in names:
        key = str(name).strip().casefold()
        if key in lowered:
            return lowered[key]

    return default


def _numeric(value, default=None):
    try:
        if value is None:
            return default

        if isinstance(value, str):
            value = value.strip().replace(",", "")

        return float(value)
    except Exception:
        return default


def _make_transformer():
    if Transformer is None:
        raise ImportError(
            "pyproj is required for Stage 3 CAD placement."
        )

    return Transformer.from_crs(
        WGS84_EPSG,
        UTM43N_EPSG,
        always_xy=True,
    )


def _load_alignment_config(app_root: Path) -> Dict[str, Any]:
    candidates = [
        app_root
        / "_integration_staging"
        / "workflow_08"
        / "config"
        / "coolplan_alignment_config.json",

        app_root
        / "_integration_staging"
        / "workflow_06"
        / "coolplan_alignment_config.json",

        app_root
        / "_integration_staging"
        / "workflow_08"
        / "coolplan_alignment_config.json",
    ]

    for path in candidates:
        if path.exists():
            with path.open("r", encoding="utf-8") as f:
                return json.load(f)

    return {}


# ============================================================
# BOUNDARY → UTM
# ============================================================

def _boundary_utm_bounds(boundary_geojson: Dict[str, Any]):
    transformer = _make_transformer()

    xs = []
    ys = []

    for _, _, geometry in _iter_features(boundary_geojson):
        geom = shape(geometry)

        if geom.is_empty:
            continue

        if geom.geom_type == "Polygon":
            geoms = [geom]
        elif geom.geom_type == "MultiPolygon":
            geoms = list(geom.geoms)
        else:
            continue

        for polygon in geoms:
            for x, y in polygon.exterior.coords:
                ux, uy = transformer.transform(x, y)
                xs.append(ux)
                ys.append(uy)

            for interior in polygon.interiors:
                for x, y in interior.coords:
                    ux, uy = transformer.transform(x, y)
                    xs.append(ux)
                    ys.append(uy)

    if not xs or not ys:
        raise ValueError(
            "Could not obtain valid UTM coordinates from the project boundary."
        )

    return min(xs), max(xs), min(ys), max(ys)


# ============================================================
# WGS84 ENVIRONMENTAL ZONES → CURRENT CAD SPACE
# ============================================================

def _build_cad_zone_records(
    zones_geojson: Dict[str, Any],
    boundary_geojson: Dict[str, Any],
    alignment_config: Dict[str, Any],
) -> List[Dict[str, Any]]:

    transformer = _make_transformer()

    min_x, max_x, min_y, max_y = _boundary_utm_bounds(
        boundary_geojson
    )

    survey_metres_per_unit = _numeric(
        alignment_config.get("survey_metres_per_unit"),
        DEFAULT_SURVEY_METRES_PER_UNIT,
    )

    master_units_per_survey_unit = _numeric(
        alignment_config.get("master_units_per_survey_unit"),
        DEFAULT_MASTER_UNITS_PER_SURVEY_UNIT,
    )

    scale = (
        master_units_per_survey_unit
        / survey_metres_per_unit
    )

    records = []

    for feature, properties, geometry in _iter_features(
        zones_geojson
    ):
        zone_id = _get_zone_id(properties)

        if not zone_id:
            continue

        source_geom = shape(geometry)

        if source_geom.is_empty:
            continue

        def wgs_to_cad(x, y, z=None):
            ux, uy = transformer.transform(x, y)

            # Established Workflow 06 placement convention.
            #
            # This is the same placement relationship used by
            # the verified Individual HPS Overlay:
            #
            #   CAD X = (max boundary UTM Y - UTM Y) * scale
            #   CAD Y = (UTM X - min boundary UTM X) * scale
            #
            # Do not replace with arbitrary extents matching.
            if z is None:
                return (
                    (max_y - uy) * scale,
                    (ux - min_x) * scale,
                )

            return (
                (max_y - uy) * scale,
                (ux - min_x) * scale,
                z,
            )

        cad_geom = transform(wgs_to_cad, source_geom)

        if cad_geom.is_empty:
            continue

        records.append(
            {
                "zone_id": zone_id,
                "geometry": cad_geom,
                "HPS": _numeric(
                    _find_property(
                        properties,
                        ["HPS"],
                    )
                ),
                "HPS_class": _find_property(
                    properties,
                    ["HPS_class", "HPS_CLASS"],
                ),
                "LST_C": _numeric(
                    _find_property(
                        properties,
                        ["LST_C", "LST"],
                    )
                ),
                "NDVI": _numeric(
                    _find_property(
                        properties,
                        ["NDVI"],
                    )
                ),
                "NDBI": _numeric(
                    _find_property(
                        properties,
                        ["NDBI"],
                    )
                ),
                "VEGETATION_DEFICIT": _numeric(
                    _find_property(
                        properties,
                        [
                            "VEGETATION_DEFICIT",
                            "vegetation_deficit",
                        ],
                    )
                ),
            }
        )

    if not records:
        raise ValueError(
            "No valid environmental zones could be transformed into CAD space."
        )

    return records


# ============================================================
# DXF LAYER HELPERS
# ============================================================

def _ensure_layer(doc, name: str, color: int = 7):
    if name not in doc.layers:
        doc.layers.add(name=name, color=color)


def _add_zone_polygon_to_dxf(
    msp,
    doc,
    zone_record: Dict[str, Any],
):
    zone_id = zone_record["zone_id"]
    geom = zone_record["geometry"]

    hps_class = str(
        zone_record.get("HPS_class") or "UNKNOWN"
    )

    layer_name = f"CP08_HPS_{_safe_name(hps_class)}"

    # Preserve the verified V11 HPS visual convention.
    hps_layer_colors = {
        "LOW": 3,          # Green
        "MODERATE": 2,     # Yellow
        "HIGH": 30,        # Orange
        "VERY_HIGH": 1,    # Red
    }

    hps_color = hps_layer_colors.get(
        _safe_name(hps_class),
        7,
    )

    _ensure_layer(
        doc,
        layer_name,
        color=hps_color,
    )

    # HPS overlay must remain transparent so the
    # original master-plan drawing stays visible.
    try:
        doc.layers.get(layer_name).transparency = 0.70
    except Exception:
        pass

    label_layer = "CP08_ZONE_LABELS"
    _ensure_layer(doc, label_layer)

    geometries = []

    if geom.geom_type == "Polygon":
        geometries = [geom]
    elif geom.geom_type == "MultiPolygon":
        geometries = list(geom.geoms)

    for polygon in geometries:
        coords = list(polygon.exterior.coords)

        if len(coords) < 3:
            continue

        points = [
            (float(x), float(y))
            for x, y in coords
        ]

        msp.add_lwpolyline(
            points,
            close=True,
            dxfattribs={
                "layer": layer_name,
            },
        )

        # Hatch is supplementary. Failure must not prevent
        # the boundary/overlay from being generated.
        try:
            hatch = msp.add_hatch(
                color=hps_color,
                dxfattribs={
                    "layer": layer_name,
                },
            )

            # 70% transparent fill:
            # original drawing remains clearly visible underneath.
            try:
                hatch.transparency = 0.70
            except Exception:
                pass

            hatch.paths.add_polyline_path(
                points,
                is_closed=True,
            )
        except Exception:
            pass

    centroid = geom.centroid

    hps = zone_record.get("HPS")

    if hps is None:
        label = zone_id
    else:
        label = f"{zone_id} | HPS {hps:.1f}"

    msp.add_text(
        label,
        dxfattribs={
            "layer": label_layer,
            "height": 8.0,
        },
    ).set_placement(
        (float(centroid.x), float(centroid.y))
    )


# ============================================================
# CURRENT MASTER PLAN GEOMETRY
# ============================================================

def _extract_closed_lwpolylines(doc):
    results = []

    msp = doc.modelspace()

    for entity in msp:
        if entity.dxftype() != "LWPOLYLINE":
            continue

        try:
            if not entity.closed:
                continue

            points = [
                (float(point[0]), float(point[1]))
                for point in entity.get_points()
            ]

            if len(points) < 3:
                continue

            polygon = Polygon(points)

            if polygon.is_empty:
                continue

            if not polygon.is_valid:
                polygon = polygon.buffer(0)

            if polygon.is_empty:
                continue

            if polygon.area <= 0:
                continue

            results.append(
                {
                    "handle": entity.dxf.handle,
                    "layer": str(entity.dxf.layer),
                    "entity_type": entity.dxftype(),
                    "polygon": polygon,
                }
            )

        except Exception:
            continue

    return results


# ============================================================
# STAGE 2 FEATURE GEOMETRY MATCHING
# ============================================================

def _feature_point(row):
    x = _numeric(row.get("x"))
    y = _numeric(row.get("y"))

    if x is None or y is None:
        return None

    return Point(x, y)



# ============================================================
# STAGE3_AI_GEOMETRY_MATCH_V1
# ============================================================

def _stage3_ai_normalize(value):
    """
    Normalize text for Stage 3 semantic comparison.

    This is not an exact-text requirement.
    """

    if value is None:
        return ""

    value = str(value).upper()
    value = value.replace("\\P", " ")

    return " ".join(value.split()).strip()


def _stage3_safe_float(value, default=None):
    try:
        value = float(value)

        if not math.isfinite(value):
            return default

        return value

    except Exception:
        return default


def _stage3_build_ai_candidate(
    polygon_record,
    text_item,
    distance,
):
    """
    Build a compact candidate description.

    Only feature-specific CAD evidence is supplied to AI.
    """

    polygon = polygon_record.get("polygon")

    area = None

    if polygon is not None:
        try:
            area = float(polygon.area)
        except Exception:
            pass

    centroid_x = None
    centroid_y = None

    if polygon is not None:
        try:
            centroid = polygon.centroid
            centroid_x = float(centroid.x)
            centroid_y = float(centroid.y)
        except Exception:
            pass

    return {
        "cad_handle": str(
            polygon_record.get("handle", "")
        ),

        "cad_layer": str(
            polygon_record.get("layer", "")
        ),

        "geometry_type": "closed_lwpolyline",

        "area_cad_units2": area,

        "centroid_x": centroid_x,
        "centroid_y": centroid_y,

        "drawing_text": str(
            text_item.get("text", "")
        ),

        "drawing_text_layer": str(
            text_item.get("layer", "")
        ),

        "drawing_text_handle": str(
            text_item.get("handle", "")
        ),

        "text_x": _stage3_safe_float(
            text_item.get("x")
        ),

        "text_y": _stage3_safe_float(
            text_item.get("y")
        ),

        "text_to_geometry_distance":
            _stage3_safe_float(distance),
    }


def _extract_stage3_drawing_text(doc):
    """
    Extract drawing text and positions from the current
    master-plan DXF.

    Text is evidence for feature-to-geometry identification.
    """

    found = []

    for entity in doc.modelspace():

        kind = entity.dxftype()

        if kind in {"TEXT", "MTEXT", "ATTRIB"}:

            try:
                raw = (
                    entity.dxf.text
                    if kind in {"TEXT", "ATTRIB"}
                    else entity.text
                )
            except Exception:
                continue

            text = str(raw or "").strip()

            if not text:
                continue

            try:
                point = entity.dxf.insert
                x = float(point.x)
                y = float(point.y)
            except Exception:
                continue

            found.append(
                {
                    "text": text,
                    "layer": str(
                        getattr(
                            entity.dxf,
                            "layer",
                            ""
                        )
                    ),
                    "entity_type": kind,
                    "handle": str(
                        getattr(
                            entity.dxf,
                            "handle",
                            ""
                        )
                    ),
                    "x": x,
                    "y": y,
                    "point": Point(x, y),
                }
            )

        elif kind == "INSERT":

            try:

                for attrib in entity.attribs:

                    text = str(
                        getattr(
                            attrib.dxf,
                            "text",
                            ""
                        ) or ""
                    ).strip()

                    if not text:
                        continue

                    try:
                        point = attrib.dxf.insert
                        x = float(point.x)
                        y = float(point.y)
                    except Exception:
                        continue

                    found.append(
                        {
                            "text": text,
                            "layer": str(
                                getattr(
                                    attrib.dxf,
                                    "layer",
                                    ""
                                )
                            ),
                            "entity_type": "ATTRIB",
                            "handle": str(
                                getattr(
                                    attrib.dxf,
                                    "handle",
                                    ""
                                )
                            ),
                            "x": x,
                            "y": y,
                            "point": Point(x, y),
                        }
                    )

            except Exception:
                pass

    return found


def _stage3_ai_resolve_features(
    unresolved_features,
    api_key,
    model="qwen/qwen3.8-27b",
):
    """
    Resolve only unresolved/ambiguous Stage 2 features.

    AI may only select an existing CAD handle.

    AI does NOT:
      - calculate HPS
      - calculate environmental values
      - calculate zone intersections
      - create geometry
    """

    if not unresolved_features:
        return {}

    if not api_key:
        print(
            "[Stage 3 AI] GROQ_API_KEY not available. "
            "AI resolution skipped."
        )
        return {}

    compact_features = []

    for feature in unresolved_features:

        compact_features.append(
            {
                "feature_id":
                    feature["feature_id"],

                "stage2_label":
                    feature["stage2_label"],

                "interpreted_feature":
                    feature.get(
                        "interpreted_feature",
                        ""
                    ),

                "standard_feature":
                    feature.get(
                        "standard_feature",
                        ""
                    ),

                "feature_group":
                    feature.get(
                        "feature_group",
                        ""
                    ),

                "drawing_text_candidates":
                    feature.get(
                        "drawing_text_candidates",
                        []
                    ),

                "cad_candidates":
                    feature.get(
                        "cad_candidates",
                        []
                    ),
            }
        )

    system_prompt = """
You are the Stage 3 CAD feature matching agent for CoolPlan AI.

Your ONLY task is to identify which EXISTING CAD geometry
represents each CURRENT Stage 2 feature.

Rules:

1. Stage 2 feature identity is authoritative.
2. Drawing text is evidence, not an exact-string requirement.
3. Stage 2 interpretation may use wording different from
   the original drawing text.
4. Use semantic meaning, drawing text, CAD layer,
   geometry characteristics, and spatial evidence.
5. You may select ONLY a CAD handle supplied in the
   candidate list.
6. Never invent a CAD handle.
7. Never calculate HPS.
8. Never calculate environmental values.
9. Never create new geometry.
10. If evidence is insufficient, return UNRESOLVED.
11. If two candidates are plausible and cannot be separated,
    return REVIEW_REQUIRED.

Return ONLY valid JSON:

{
  "matches": [
    {
      "feature_id": "...",
      "decision": "CONFIRMED",
      "cad_handle": "...",
      "confidence": 0.0,
      "reason": "..."
    }
  ]
}

Allowed decisions:
CONFIRMED
REVIEW_REQUIRED
UNRESOLVED
"""

    user_prompt = (
        "Resolve these CURRENT Stage 2 feature-to-CAD "
        "geometry matches.\n\n"
        + json.dumps(
            compact_features,
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )

    payload = {
        "model": model,
        "temperature": 0,
        "max_tokens": 3000,
        "messages": [
            {
                "role": "system",
                "content": system_prompt.strip(),
            },
            {
                "role": "user",
                "content": user_prompt,
            },
        ],
    }

    try:

        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization":
                    f"Bearer {api_key}",

                "Content-Type":
                    "application/json",
            },
            json=payload,
            timeout=90,
        )

        response.raise_for_status()

        data = response.json()

        content = (
            data
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
        )

        content = str(content).strip()

        if content.startswith("```"):

            content = re.sub(
                r"^```(?:json)?",
                "",
                content,
                flags=re.IGNORECASE,
            )

            content = re.sub(
                r"```$",
                "",
                content,
            ).strip()

        result = json.loads(content)

        matches = result.get(
            "matches",
            []
        )

        resolved = {}

        for item in matches:

            if not isinstance(item, dict):
                continue

            feature_id = str(
                item.get(
                    "feature_id",
                    ""
                )
            ).strip()

            if not feature_id:
                continue

            decision = str(
                item.get(
                    "decision",
                    ""
                )
            ).strip().upper()

            if decision not in {
                "CONFIRMED",
                "REVIEW_REQUIRED",
                "UNRESOLVED",
            }:
                decision = "UNRESOLVED"

            resolved[feature_id] = {
                "decision": decision,

                "cad_handle": str(
                    item.get(
                        "cad_handle",
                        ""
                    )
                ).strip(),

                "confidence":
                    _stage3_safe_float(
                        item.get(
                            "confidence"
                        ),
                        0.0,
                    ),

                "reason": str(
                    item.get(
                        "reason",
                        ""
                    )
                ).strip(),
            }

        return resolved

    except Exception as exc:

        print(
            "[Stage 3 AI] Resolution failed:",
            repr(exc),
        )

        return {}






# ============================================================
# STAGE3_LEADER_AWARE_MATCH_V2
# ============================================================

def _stage3_extract_leaders(doc):
    """
    Extract LEADER geometry from the original master plan.

    Stage 2 labels in this drawing are frequently annotations
    connected to the actual feature by a CAD LEADER.

    This function does not identify or create features.
    It only extracts existing CAD leader geometry.
    """

    leaders = []

    for entity in doc.modelspace():

        if entity.dxftype() != "LEADER":
            continue

        try:
            vertices = list(entity.vertices())
        except Exception:
            continue

        if len(vertices) < 2:
            continue

        points = []

        for vertex in vertices:

            try:
                points.append(
                    Point(
                        float(vertex.x),
                        float(vertex.y),
                    )
                )
            except Exception:
                continue

        if len(points) < 2:
            continue

        leaders.append(
            {
                "handle": str(
                    getattr(
                        entity.dxf,
                        "handle",
                        "",
                    )
                ),
                "layer": str(
                    getattr(
                        entity.dxf,
                        "layer",
                        "",
                    )
                ),
                "points": points,
            }
        )

    return leaders


def _stage3_find_leader_for_text(
    text_point,
    leaders,
    max_text_distance=500.0,
):
    """
    Find the nearest LEADER to a Stage 2 drawing label.

    The leader vertex nearest the text is treated as the
    annotation-side point.

    The farthest leader vertex from that annotation-side
    point is treated as the feature-side anchor.
    """

    if text_point is None:
        return None

    best = None

    for leader in leaders:

        points = leader.get("points", [])

        if len(points) < 2:
            continue

        distances = []

        for point in points:

            try:
                d = float(
                    point.distance(
                        text_point
                    )
                )
            except Exception:
                continue

            distances.append(
                (d, point)
            )

        if len(distances) < 2:
            continue

        distances.sort(
            key=lambda item: item[0]
        )

        text_distance, text_side = distances[0]

        if text_distance > max_text_distance:
            continue

        # Select the leader endpoint/vertex farthest
        # from the annotation side.
        feature_side = max(
            distances[1:],
            key=lambda item: item[0]
        )

        candidate = {
            "leader_handle": leader.get(
                "handle",
                "",
            ),
            "text_distance": float(
                text_distance
            ),
            "anchor": feature_side[1],
        }

        if best is None:
            best = candidate
        elif (
            candidate["text_distance"]
            < best["text_distance"]
        ):
            best = candidate

    return best


def _match_feature_polygons(
    stage2_df: pd.DataFrame,
    closed_polygons: List[Dict[str, Any]],
    doc,
):
    """
    Match CURRENT Stage 2 feature identities to CURRENT CAD
    feature polygons.

    Matching strategy:

        1. Strong deterministic semantic/text evidence
        2. Candidate geometry generation
        3. AI resolution for unresolved/ambiguous features
        4. Geometry conflict protection

    The AI is ONLY used for feature-to-geometry identity.
    Environmental association remains deterministic.
    """

    matched = []

    feature_layers = {
        "BUILDING",
        "ROAD",
        "EX-ROAD",
        "PATH",
        "PARKING",
        "PLOTS",
        "CRICKET",
        "TRACK",
        "BOUNDARY",
        "BOUNDRY",
    }

    text_items = _extract_stage3_drawing_text(doc)

    if not text_items:
        return matched

    # --------------------------------------------------------
    # STAGE3_LEADER_AWARE_MATCH_V2
    # --------------------------------------------------------
    #
    # Keep existing drawing-text matching.
    # Add actual CAD LEADER geometry as an additional
    # spatial anchor.
    # --------------------------------------------------------

    leader_records = _stage3_extract_leaders(doc)

    # --------------------------------------------------------
    # Prepare Stage 2 features.
    # --------------------------------------------------------

    stage2_rows = []

    for row_index, row in stage2_df.iterrows():

        label = str(
            row.get("label")
            or row.get("interpreted_feature")
            or ""
        ).strip()

        interpreted = str(
            row.get("interpreted_feature")
            or ""
        ).strip()

        standard = str(
            row.get("standard_feature")
            or ""
        ).strip()

        feature_group = str(
            row.get("feature_group")
            or ""
        ).strip()

        if not label and not interpreted:
            continue

        stage2_rows.append(
            {
                "row_index": row_index,
                "row": row.to_dict(),
                "label": label,
                "interpreted_feature": interpreted,
                "standard_feature": standard,
                "feature_group": feature_group,
            }
        )

    unresolved_for_ai = []
    deterministic_matches = []

    # --------------------------------------------------------
    # Candidate generation
    # --------------------------------------------------------

    for feature in stage2_rows:

        stage2_label = feature["label"]
        stage2_interpreted = feature["interpreted_feature"]
        stage2_standard = feature["standard_feature"]
        stage2_group = feature["feature_group"]

        identity_terms = []

        for value in [
            stage2_label,
            stage2_interpreted,
            stage2_standard,
        ]:

            value = str(value).strip()

            if value:
                identity_terms.append(
                    _stage3_ai_normalize(value)
                )

        identity_terms = list(
            dict.fromkeys(identity_terms)
        )

        candidates_for_ai = []

        # ----------------------------------------------------
        # Evaluate drawing text
        # ----------------------------------------------------

        for text_item in text_items:

            text_value = str(
                text_item.get("text", "")
            ).strip()

            text_normalized = _stage3_ai_normalize(
                text_value
            )

            if not text_normalized:
                continue

            if (
                len(text_normalized) <= 1
                or text_normalized.isdigit()
            ):
                continue

            text_point = text_item["point"]

            # ------------------------------------------------
            # Find the CAD LEADER associated with this label.
            # ------------------------------------------------

            leader_info = (
                _stage3_find_leader_for_text(
                    text_point,
                    leader_records,
                )
            )

            leader_anchor = None

            if leader_info is not None:
                leader_anchor = leader_info.get(
                    "anchor"
                )

            text_similarity = 0

            for term in identity_terms:

                if not term:
                    continue

                if text_normalized == term:

                    text_similarity = max(
                        text_similarity,
                        100,
                    )

                elif (
                    text_normalized in term
                    or term in text_normalized
                ):

                    text_similarity = max(
                        text_similarity,
                        60,
                    )

            # ------------------------------------------------
            # Find compatible CAD polygons
            # ------------------------------------------------

            polygon_candidates = []

            for polygon_record in closed_polygons:

                layer = str(
                    polygon_record.get(
                        "layer",
                        "",
                    )
                ).upper()

                if layer not in feature_layers:
                    continue

                polygon = polygon_record.get(
                    "polygon"
                )

                if polygon is None:
                    continue

                try:

                    # Existing distance from label text.
                    text_distance = float(
                        polygon.distance(
                            text_point
                        )
                    )

                    # Additional distance from the actual
                    # feature-side LEADER anchor.
                    leader_distance = float(
                        "inf"
                    )

                    if leader_anchor is not None:

                        leader_distance = float(
                            polygon.distance(
                                leader_anchor
                            )
                        )

                    # Use the stronger spatial anchor.
                    if leader_distance < text_distance:

                        distance = leader_distance

                        spatial_anchor = (
                            "leader_feature_endpoint"
                        )

                    else:

                        distance = text_distance

                        spatial_anchor = (
                            "text_insertion_point"
                        )

                except Exception:

                    continue

                polygon_candidates.append(
                    (
                        distance,
                        polygon_record,
                    )
                )

            if not polygon_candidates:
                continue

            polygon_candidates.sort(
                key=lambda item: item[0]
            )

            # Keep only the closest five candidates
            # for this drawing text.
            for distance, polygon_record in (
                polygon_candidates[:5]
            ):

                candidate = _stage3_build_ai_candidate(
                    polygon_record,
                    text_item,
                    distance,
                )

                candidate[
                    "text_semantic_score"
                ] = text_similarity

                candidate[
                    "spatial_anchor"
                ] = spatial_anchor

                candidate[
                    "leader_handle"
                ] = (
                    leader_info.get(
                        "leader_handle",
                        "",
                    )
                    if leader_info
                    else ""
                )

                candidates_for_ai.append(
                    candidate
                )

                # Strong exact text + close geometry
                # can be accepted deterministically.
                if (
                    text_similarity >= 100
                    and distance <= 150
                ):

                    deterministic_matches.append(
                        {
                            "stage2_row":
                                feature["row"],

                            "feature_polygon":
                                polygon_record[
                                    "polygon"
                                ],

                            "cad_handle":
                                str(
                                    polygon_record[
                                        "handle"
                                    ]
                                ),

                            "cad_layer":
                                polygon_record[
                                    "layer"
                                ],

                            "match_method":
                                "exact_drawing_text_spatial",

                            "match_distance":
                                float(distance),

                            "matched_text":
                                text_value,

                            "matched_text_handle":
                                text_item[
                                    "handle"
                                ],

                            "spatial_anchor":
                                spatial_anchor,

                            "leader_handle":
                                (
                                    leader_info.get(
                                        "leader_handle",
                                        "",
                                    )
                                    if leader_info
                                    else ""
                                ),
                        }
                    )

                    break

        # ----------------------------------------------------
        # Determine whether deterministic matching resolved it
        # ----------------------------------------------------

        already_resolved = any(
            str(
                item["stage2_row"].get(
                    "label",
                    "",
                )
            )
            == stage2_label
            for item in deterministic_matches
        )

        if already_resolved:
            continue

        # ----------------------------------------------------
        # Deduplicate candidates by CAD handle
        # ----------------------------------------------------

        candidate_map = {}

        for candidate in candidates_for_ai:

            handle = str(
                candidate.get(
                    "cad_handle",
                    "",
                )
            ).strip()

            if not handle:
                continue

            existing = candidate_map.get(
                handle
            )

            if existing is None:

                candidate_map[
                    handle
                ] = candidate

            else:

                old_score = existing.get(
                    "text_semantic_score",
                    0,
                )

                new_score = candidate.get(
                    "text_semantic_score",
                    0,
                )

                old_distance = existing.get(
                    "text_to_geometry_distance",
                    float("inf"),
                )

                new_distance = candidate.get(
                    "text_to_geometry_distance",
                    float("inf"),
                )

                if (
                    new_score > old_score
                    or (
                        new_score == old_score
                        and new_distance < old_distance
                    )
                ):

                    candidate_map[
                        handle
                    ] = candidate

        candidates_for_ai = list(
            candidate_map.values()
        )

        candidates_for_ai.sort(
            key=lambda item: (
                -float(
                    item.get(
                        "text_semantic_score",
                        0,
                    )
                ),
                float(
                    item.get(
                        "text_to_geometry_distance",
                        float("inf"),
                    )
                ),
            )
        )

        # Never send a large geometry candidate list.
        candidates_for_ai = candidates_for_ai[:8]

        unresolved_for_ai.append(
            {
                "feature_id":
                    f"stage2_{feature['row_index']}",

                "stage2_label":
                    stage2_label,

                "interpreted_feature":
                    stage2_interpreted,

                "standard_feature":
                    stage2_standard,

                "feature_group":
                    stage2_group,

                "drawing_text_candidates":
                    [
                        {
                            "text":
                                c.get(
                                    "drawing_text",
                                    "",
                                ),

                            "layer":
                                c.get(
                                    "drawing_text_layer",
                                    "",
                                ),

                            "handle":
                                c.get(
                                    "drawing_text_handle",
                                    "",
                                ),

                            "distance":
                                c.get(
                                    "text_to_geometry_distance"
                                ),
                        }

                        for c in candidates_for_ai
                    ],

                "cad_candidates":
                    candidates_for_ai,

                "stage2_row":
                    feature["row"],
            }
        )

    # --------------------------------------------------------
    # AI resolution
    # --------------------------------------------------------

    api_key = os.environ.get(
        "GROQ_API_KEY"
    )

    ai_results = {}

    if unresolved_for_ai:

        # Recovered Stage 3 configuration:
        # two features per AI request.
        batch_size = 2

        batches = [
            unresolved_for_ai[i:i + batch_size]
            for i in range(
                0,
                len(unresolved_for_ai),
                batch_size,
            )
        ]

        print(
            f"[Stage 3 AI] Unresolved features: "
            f"{len(unresolved_for_ai)}"
        )

        print(
            f"[Stage 3 AI] Batches: "
            f"{len(batches)} "
            f"(batch size {batch_size})"
        )

        for batch_index, batch in enumerate(
            batches,
            start=1,
        ):

            print(
                f"[Stage 3 AI] "
                f"Processing batch "
                f"{batch_index}/{len(batches)}"
            )

            result = _stage3_ai_resolve_features(
                batch,
                api_key,
                model="qwen/qwen3.8-27b",
            )

            if not result:

                print(
                    f"[Stage 3 AI] "
                    f"Batch {batch_index} "
                    f"returned no usable decisions."
                )

                continue

            ai_results.update(result)

    # --------------------------------------------------------
    # Add deterministic matches
    # --------------------------------------------------------

    matched.extend(
        deterministic_matches
    )

    # --------------------------------------------------------
    # Add AI-confirmed matches
    # --------------------------------------------------------

    for feature in unresolved_for_ai:

        feature_id = feature[
            "feature_id"
        ]

        decision = ai_results.get(
            feature_id
        )

        if not decision:
            continue

        if decision.get(
            "decision"
        ) != "CONFIRMED":
            continue

        selected_handle = str(
            decision.get(
                "cad_handle",
                "",
            )
        ).strip()

        if not selected_handle:
            continue

        # ----------------------------------------------------
        # AI may ONLY select a handle supplied in its candidates
        # ----------------------------------------------------

        selected_candidate = None

        for candidate in feature[
            "cad_candidates"
        ]:

            if str(
                candidate.get(
                    "cad_handle",
                    "",
                )
            ).strip() == selected_handle:

                selected_candidate = candidate
                break

        if selected_candidate is None:

            print(
                "[Stage 3 AI] Rejected invented "
                f"CAD handle {selected_handle} "
                f"for {feature['stage2_label']}"
            )

            continue

        # ----------------------------------------------------
        # Locate actual polygon
        # ----------------------------------------------------

        actual_polygon_record = None

        for polygon_record in closed_polygons:

            if str(
                polygon_record.get(
                    "handle",
                    "",
                )
            ).strip() == selected_handle:

                actual_polygon_record = polygon_record
                break

        if actual_polygon_record is None:
            continue

        matched.append(
            {
                "stage2_row":
                    feature["stage2_row"],

                "feature_polygon":
                    actual_polygon_record[
                        "polygon"
                    ],

                "cad_handle":
                    selected_handle,

                "cad_layer":
                    actual_polygon_record.get(
                        "layer",
                        "",
                    ),

                "match_method":
                    "stage3_ai_geometry_identification",

                "match_distance":
                    selected_candidate.get(
                        "text_to_geometry_distance"
                    ),

                "matched_text":
                    selected_candidate.get(
                        "drawing_text",
                        "",
                    ),

                "ai_confidence":
                    decision.get(
                        "confidence",
                        0.0,
                    ),

                "ai_reason":
                    decision.get(
                        "reason",
                        "",
                    ),
            }
        )

        print(
            "[Stage 3 AI] CONFIRMED: "
            f"{feature['stage2_label']} "
            f"-> {selected_handle}"
        )

    # --------------------------------------------------------
    # Remove exact duplicate Stage2/CAD matches
    # --------------------------------------------------------

    unique = {}

    for item in matched:

        key = (
            str(
                item["stage2_row"].get(
                    "label",
                    "",
                )
            ),

            str(
                item.get(
                    "cad_handle",
                    "",
                )
            ),
        )

        if key not in unique:
            unique[key] = item

    matched = list(
        unique.values()
    )

    # --------------------------------------------------------
    # Geometry conflict protection
    # --------------------------------------------------------

    by_handle = {}

    for item in matched:

        handle = str(
            item.get(
                "cad_handle",
                "",
            )
        )

        by_handle.setdefault(
            handle,
            []
        ).append(item)

    final_matches = []

    for handle, items in by_handle.items():

        if len(items) == 1:

            final_matches.append(
                items[0]
            )

            continue

        # Prefer exactly one AI-confirmed identity.
        ai_items = [
            item
            for item in items
            if item.get(
                "match_method"
            )
            == "stage3_ai_geometry_identification"
        ]

        if len(ai_items) == 1:

            final_matches.append(
                ai_items[0]
            )

            continue

        # Otherwise retain the strongest spatial match
        # but explicitly flag the conflict.
        chosen = sorted(
            items,
            key=lambda item: float(
                item.get(
                    "match_distance",
                    float("inf"),
                )
                if item.get(
                    "match_distance"
                ) is not None
                else float("inf")
            )
        )[0]

        chosen = dict(chosen)

        chosen[
            "geometry_conflict"
        ] = True

        chosen[
            "review_required"
        ] = True

        chosen[
            "review_reason"
        ] = (
            "Multiple Stage 2 features "
            "matched the same CAD geometry."
        )

        chosen[
            "competing_stage2_labels"
        ] = [
            str(
                item["stage2_row"].get(
                    "label",
                    "",
                )
            )
            for item in items
        ]

        final_matches.append(
            chosen
        )

        print(
            "[Stage 3] Geometry conflict: "
            f"{handle} -> "
            f"{chosen['stage2_row'].get('label', '')}"
        )

    print(
        "[Stage 3] Feature→geometry matching: "
        f"{len(stage2_rows)} Stage 2 features -> "
        f"{len(final_matches)} resolved CAD geometries"
    )

    return final_matches


def _calculate_associations(
    matched_features,
    zone_records,
):
    rows = []

    for feature in matched_features:

        feature_row = feature["stage2_row"]
        feature_polygon = feature["feature_polygon"]

        feature_area = float(feature_polygon.area)

        if feature_area <= 0:
            continue

        for zone in zone_records:

            zone_polygon = zone["geometry"]

            try:
                intersection = feature_polygon.intersection(
                    zone_polygon
                )
            except Exception:
                continue

            if intersection.is_empty:
                continue

            overlap_area = float(intersection.area)

            if overlap_area <= 0:
                continue

            zone_area = float(zone_polygon.area)

            if zone_area <= 0:
                continue

            rows.append(
                {
                    "cad_feature_id": feature_row.get(
                        "group_id"
                    )
                    or feature_row.get("label")
                    or feature["cad_handle"],

                    "cad_handle": feature["cad_handle"],

                    "cad_layer": feature["cad_layer"],

                    "drawing_label": feature_row.get(
                        "label"
                    ),

                    "interpreted_feature": feature_row.get(
                        "interpreted_feature"
                    ),

                    "standard_feature": feature_row.get(
                        "standard_feature"
                    ),

                    "feature_group": feature_row.get(
                        "feature_group"
                    ),

                    "zone_id": zone["zone_id"],

                    "overlap_area_cad_units2": overlap_area,

                    "feature_area_cad_units2": feature_area,

                    "zone_area_cad_units2": zone_area,

                    "zone_overlap_fraction": (
                        overlap_area / zone_area
                    ),

                    "feature_overlap_fraction": (
                        overlap_area / feature_area
                    ),

                    "HPS": zone.get("HPS"),

                    "HPS_class": zone.get("HPS_class"),

                    "LST_C": zone.get("LST_C"),

                    "NDVI": zone.get("NDVI"),

                    "NDBI": zone.get("NDBI"),

                    "VEGETATION_DEFICIT": zone.get(
                        "VEGETATION_DEFICIT"
                    ),

                    "association_method":
                        "closed_polygon_intersection",

                    "feature_geometry_match":
                        feature["match_method"],

                    "feature_geometry_match_distance":
                        feature["match_distance"],

                    "review_status":
                        "candidate_not_approved",
                }
            )

    return rows


# ============================================================
# MAIN PUBLIC FUNCTION
# ============================================================



# ============================================================
# COOLPLAN_STAGE3_V11_SPATIAL_BASE
# ============================================================
#
# V11 is the verified CAD-space spatial reference for Stage 3.
#
# Environmental attributes continue to come from the CURRENT
# Environmental Analysis GeoJSON.
#
# Spatial geometry for Stage 3 comes from V11:
#
#   current zone_id
#          ↓
#   V11 Z_### label
#          ↓
#   V11 HPS polygon
#
# Stage 2 feature identity remains authoritative.
# No new LLM classification is performed here.
# ============================================================

V11_FEATURE_LAYERS = {
    "ROAD",
    "BUILDING",
    "PATH",
    "BOUNDRY",
    "CRICKET",
}

V11_HPS_LAYERS = {
    "CP08_HPS_LOW",
    "CP08_HPS_MODERATE",
    "CP08_HPS_HIGH",
    "CP08_HPS_VERY_HIGH",
}


def _v11_polygon_from_lwpolyline(entity):
    """Convert a closed V11 LWPOLYLINE into a valid Shapely polygon."""

    if entity.dxftype() != "LWPOLYLINE":
        return None

    if not bool(entity.closed):
        return None

    points = [
        (float(point[0]), float(point[1]))
        for point in entity.get_points("xy")
    ]

    if len(points) < 3:
        return None

    if points[0] != points[-1]:
        points.append(points[0])

    try:
        polygon = Polygon(points)

        if not polygon.is_valid:
            polygon = polygon.buffer(0)

        if polygon.is_empty:
            return None

        if polygon.area <= 0:
            return None

        return polygon

    except Exception:
        return None


def _v11_clean_text(value):
    """Clean AutoCAD text formatting used by V11 zone labels."""

    return (
        str(value)
        .replace("\\A1;", "")
        .replace("\\P", " ")
        .strip()
    )


def _load_v11_spatial_base(v11_path):
    """
    Load the verified Workflow 08 V11 spatial base.

    Returns:
        {
            "doc": V11 DXF document,
            "feature_polygons": [...],
            "zone_polygons": [...],
            "zone_label_map": {...}
        }
    """

    v11_path = Path(v11_path)

    if not v11_path.exists():
        raise FileNotFoundError(
            f"V11 spatial base not found: {v11_path}"
        )

    v11_doc = ezdxf.readfile(str(v11_path))
    v11_msp = v11_doc.modelspace()

    feature_polygons = []
    zone_polygons = []

    # --------------------------------------------------------
    # Extract V11 feature polygons
    # --------------------------------------------------------

    for entity in v11_msp:

        if entity.dxftype() != "LWPOLYLINE":
            continue

        layer = str(
            entity.dxf.layer
        ).upper()

        if layer not in V11_FEATURE_LAYERS:
            continue

        polygon = _v11_polygon_from_lwpolyline(entity)

        if polygon is None:
            continue

        feature_polygons.append(
            {
                "handle": entity.dxf.handle,
                    "layer": layer,
                    "cad_handle": entity.dxf.handle,
                "cad_layer": layer,
                "geometry_type": "LWPOLYLINE",
                "polygon": polygon,
                "area_cad_units2": float(
                    polygon.area
                ),
                "centroid_x": float(
                    polygon.centroid.x
                ),
                "centroid_y": float(
                    polygon.centroid.y
                ),
            }
        )

    # --------------------------------------------------------
    # Extract V11 HPS polygons
    # --------------------------------------------------------

    for entity in v11_msp:

        if entity.dxftype() != "LWPOLYLINE":
            continue

        layer = str(
            entity.dxf.layer
        ).upper()

        if layer not in V11_HPS_LAYERS:
            continue

        polygon = _v11_polygon_from_lwpolyline(entity)

        if polygon is None:
            continue

        zone_polygons.append(
            {
                "cad_handle": entity.dxf.handle,
                "cad_layer": layer,
                "hps_class": layer.replace(
                    "CP08_HPS_",
                    "",
                ),
                "polygon": polygon,
                "area_cad_units2": float(
                    polygon.area
                ),
                "centroid_x": float(
                    polygon.centroid.x
                ),
                "centroid_y": float(
                    polygon.centroid.y
                ),
            }
        )

    # --------------------------------------------------------
    # Extract CP08_ZONE_LABELS
    #
    # Each V11 HPS polygon has two labels:
    #
    #   Z_001
    #   HPS 27.1
    #
    # The Z_### label is the authoritative zone identifier.
    # --------------------------------------------------------

    label_records = []

    for entity in v11_msp:

        if entity.dxftype() not in {
            "TEXT",
            "MTEXT",
        }:
            continue

        layer = str(
            entity.dxf.layer
        ).upper()

        if layer != "CP08_ZONE_LABELS":
            continue

        if entity.dxftype() == "TEXT":
            text = _v11_clean_text(
                entity.dxf.text
            )

            x = float(
                entity.dxf.insert.x
            )

            y = float(
                entity.dxf.insert.y
            )

        else:
            text = _v11_clean_text(
                entity.text
            )

            x = float(
                entity.dxf.insert.x
            )

            y = float(
                entity.dxf.insert.y
            )

        if not text:
            continue

        label_records.append(
            {
                "text": text,
                "x": x,
                "y": y,
            }
        )

    # --------------------------------------------------------
    # Match Z_### labels to HPS polygons
    # --------------------------------------------------------

    zone_label_map = {}

    for label in label_records:

        text = label["text"]

        if not re.fullmatch(
            r"Z_\d+",
            text,
            flags=re.IGNORECASE,
        ):
            continue

        point = Point(
            label["x"],
            label["y"],
        )

        containing = []

        for zone in zone_polygons:

            polygon = zone["polygon"]

            if (
                polygon.contains(point)
                or polygon.touches(point)
            ):
                containing.append(zone)

        if len(containing) != 1:
            raise ValueError(
                "V11 zone label does not map "
                "uniquely to an HPS polygon: "
                f"{text} "
                f"(matches={len(containing)})"
            )

        zone = containing[0]

        zone_label_map[text] = zone

    if len(zone_label_map) != len(zone_polygons):
        raise ValueError(
            "V11 zone mapping is incomplete: "
            f"{len(zone_label_map)} zone labels for "
            f"{len(zone_polygons)} HPS polygons."
        )

    if len(feature_polygons) != 131:
        raise ValueError(
            "Unexpected V11 feature polygon count: "
            f"{len(feature_polygons)}; expected 131."
        )

    if len(zone_polygons) != 147:
        raise ValueError(
            "Unexpected V11 HPS polygon count: "
            f"{len(zone_polygons)}; expected 147."
        )

    return {
        "doc": v11_doc,
        "feature_polygons": feature_polygons,
        "zone_polygons": zone_polygons,
        "zone_label_map": zone_label_map,
    }


def _replace_zone_geometry_with_v11(
    zone_records,
    v11_zone_label_map,
):
    """
    Preserve current Environmental Analysis attributes while
    replacing only the spatial geometry with verified V11
    geometry.

    Current zone_id remains authoritative.
    """

    replaced = []

    for record in zone_records:

        zone_id = str(
            record.get("zone_id", "")
        ).strip()

        v11_zone = v11_zone_label_map.get(
            zone_id
        )

        if v11_zone is None:
            raise ValueError(
                "Current environmental zone "
                f"{zone_id!r} has no matching "
                "V11 Z_### polygon."
            )

        updated = dict(record)

        # Only spatial geometry is replaced.
        updated["geometry"] = v11_zone[
            "polygon"
        ]

        updated["v11_cad_handle"] = (
            v11_zone["cad_handle"]
        )

        updated["v11_hps_class"] = (
            v11_zone["hps_class"]
        )

        replaced.append(updated)

    if not replaced:
        raise ValueError(
            "No environmental zone records "
            "were available for V11 geometry replacement."
        )

    return replaced



def _match_stage2_features_to_v11(
    stage2_df,
    v11_feature_polygons,
    base_plan_doc=None,
):
    """
    Stage 3 feature matching wrapper.

    IMPORTANT ARCHITECTURE
    ----------------------

    Stage 2:
        Determines what each feature is.

    Master plan:
        Provides the actual CAD geometry used for
        feature identity matching.

    AI:
        Resolves only ambiguous/unresolved
        Stage 2 feature -> master-plan geometry identity.

    V11:
        Remains the environmental/presentation canvas.
        Its feature polygons are NOT used to determine
        Stage 2 feature identity.

    Environmental association:
        Remains deterministic and is performed later
        by _calculate_associations().
    """

    if base_plan_doc is None:
        raise ValueError(
            "Stage 3 requires the original master-plan "
            "DXF document for feature geometry matching."
        )

    # --------------------------------------------------------
    # Extract actual closed feature geometry from the
    # ORIGINAL master plan.
    #
    # This is the same drawing used for Stage 2.
    # --------------------------------------------------------

    closed_polygons = _extract_closed_lwpolylines(
        base_plan_doc
    )

    if not closed_polygons:
        raise ValueError(
            "No closed master-plan feature polygons "
            "were found for Stage 3 matching."
        )

    print(
        "[Stage 3] Master-plan closed polygons: "
        f"{len(closed_polygons)}"
    )

    # --------------------------------------------------------
    # Use the restored AI-capable matcher.
    #
    # AI is only used for unresolved feature identity.
    # --------------------------------------------------------

    matched_features = _match_feature_polygons(
        stage2_df,
        closed_polygons,
        base_plan_doc,
    )

    print(
        "[Stage 3] AI-capable feature matching complete: "
        f"{len(matched_features)} matched geometries"
    )

    return matched_features


def generate_stage3_overlay(
    master_plan_path,
    zones_geojson,
    boundary_geojson,
    output_dir,
    stage2_results=None,
    project_hash=None,
    alignment_config_path=None,
):
    """
    Generate the current Test Project Stage 3 overlay.

    Parameters
    ----------
    master_plan_path:
        Current Stage 2 master-plan DXF.

    zones_geojson:
        Current environmental analysis zones GeoJSON.

    boundary_geojson:
        Current Test Project boundary GeoJSON.

    output_dir:
        Directory for Stage 3 generated outputs.

    stage2_results:
        Stage 2 runtime classification dataframe/list/dict.

    project_hash:
        Hash identifying the current Stage 2 project.

    alignment_config_path:
        Optional explicit Workflow 06 alignment config.

    Returns
    -------
    dict
        success/status/output paths/association dataframe/counts.
    """

    master_plan_path = Path(master_plan_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if not master_plan_path.exists():
        raise FileNotFoundError(
            f"Current Stage 2 master-plan DXF not found:\n"
            f"{master_plan_path}"
        )

    # --------------------------------------------------------
    # Stage 2 results
    # --------------------------------------------------------

    if stage2_results is None:
        raise ValueError(
            "Stage 3 requires the current Stage 2 results."
        )

    if isinstance(stage2_results, pd.DataFrame):
        stage2_df = stage2_results.copy()

    elif isinstance(stage2_results, list):
        stage2_df = pd.DataFrame(stage2_results)

    elif isinstance(stage2_results, dict):
        stage2_df = pd.DataFrame(stage2_results)

    else:
        raise TypeError(
            "Unsupported stage2_results type."
        )

    if stage2_df.empty:
        raise ValueError(
            "Current Stage 2 result contains no features."
        )

    # --------------------------------------------------------
    # Current environmental data
    # --------------------------------------------------------

    zones_data = _read_geojson(zones_geojson)
    boundary_data = _read_geojson(boundary_geojson)

    if alignment_config_path:
        alignment_path = Path(alignment_config_path)

        if alignment_path.exists():
            with alignment_path.open(
                "r",
                encoding="utf-8",
            ) as f:
                alignment_config = json.load(f)
        else:
            alignment_config = {}
    else:
        alignment_config = _load_alignment_config(
            master_plan_path.parents[3]
            if len(master_plan_path.parents) >= 4
            else master_plan_path.parent
        )

    # --------------------------------------------------------
    # Generate current CAD-space HPS zones
    # --------------------------------------------------------

    zone_records = _build_cad_zone_records(
        zones_data,
        boundary_data,
        alignment_config,
    )

    # --------------------------------------------------------
    # Open current master plan.
    #
    # The current master plan remains the output drawing
    # container. It is NOT used as the Stage 3 spatial
    # reference for feature → zone association.
    # --------------------------------------------------------

    doc = ezdxf.readfile(
        str(master_plan_path)
    )

    # Keep a completely separate copy of the ORIGINAL master
    # plan for Stage 3 feature identity matching.
    #
    # IMPORTANT:
    # `doc` becomes the final output drawing and later receives
    # the 147 V11 HPS zone polygons.
    #
    # `base_plan_doc` must remain untouched so Stage 3 sees
    # ONLY the original master-plan geometry.
    base_plan_doc = ezdxf.readfile(
        str(master_plan_path)
    )

    msp = doc.modelspace()

    # --------------------------------------------------------
    # Load verified V11 spatial base.
    #
    # V11 supplies:
    #   - final HPS presentation geometry
    #   - HPS zone geometry
    #
    # The actual master plan supplies feature geometry.
    #
    # Current Environmental Analysis supplies:
    #   - zone_id
    #   - HPS
    #   - HPS_class
    #   - LST_C
    #   - NDVI
    #   - NDBI
    #   - VEGETATION_DEFICIT
    # --------------------------------------------------------

    v11_candidates = [
        master_plan_path.parent
        / "Workflow08_Review"
        / "CoolPlan_Workflow08_Individual_HPS_Overlay_v11.dxf",

        master_plan_path.parent.parent
        / "Workflow08_Review"
        / "CoolPlan_Workflow08_Individual_HPS_Overlay_v11.dxf",

        Path(
            "/content/CoolPlan_Stage3_Recovery/"
            "Workflow_08/Workflow08_Review/"
            "CoolPlan_Workflow08_Individual_HPS_Overlay_v11.dxf"
        ),

        Path(
            "/content/Integrated_App/Integrated_App/"
            "_integration_staging/workflow_08/stage3_integration/"
            "CoolPlan_Workflow08_Individual_HPS_Overlay_v11.dxf"
        ),
    ]

    v11_path = next(
        (
            path
            for path in v11_candidates
            if path.exists()
        ),
        None,
    )

    if v11_path is None:
        raise FileNotFoundError(
            "Verified Workflow 08 V11 spatial base "
            "could not be located."
        )

    v11_base = _load_v11_spatial_base(
        v11_path
    )

    # --------------------------------------------------------
    # Replace only zone geometry.
    #
    # Environmental Analysis values remain untouched.
    # --------------------------------------------------------

    zone_records = _replace_zone_geometry_with_v11(
        zone_records,
        v11_base["zone_label_map"],
    )

    # --------------------------------------------------------
    # Add the verified V11 HPS geometry to the output
    # drawing using the current environmental attributes.
    # --------------------------------------------------------

    for zone in zone_records:
        _add_zone_polygon_to_dxf(
            msp,
            doc,
            zone,
        )

    # --------------------------------------------------------
    # Match verified Stage 2 feature identities against
    # the actual master-plan feature geometry.
    #
    # V11 is NOT used to identify the feature.
    # No new AI classification is performed by this step.
    # --------------------------------------------------------

    matched_features = _match_stage2_features_to_v11(
        stage2_df,
        v11_base["feature_polygons"],
        base_plan_doc=base_plan_doc,
    )

    # --------------------------------------------------------
    # Calculate deterministic V11 feature → zone
    # association.
    # --------------------------------------------------------

    association_rows = _calculate_associations(
        matched_features,
        zone_records,
    )

    association_df = pd.DataFrame(
        association_rows
    )

    # --------------------------------------------------------
    # Add simple Stage 3 visual markers for associated
    # features without altering the source geometry.
    # --------------------------------------------------------

    _ensure_layer(
        doc,
        "CP08_FEATURE_ASSOCIATIONS",
        6,
    )

    _ensure_layer(
        doc,
        "CP08_FEATURE_LABELS",
        7,
    )

    seen_handles = set()

    for feature in matched_features:

        handle = feature["cad_handle"]

        if handle in seen_handles:
            continue

        seen_handles.add(handle)

        polygon = feature["feature_polygon"]
        centroid = polygon.centroid

        try:
            msp.add_circle(
                (
                    float(centroid.x),
                    float(centroid.y),
                ),
                radius=10.0,
                dxfattribs={
                    "layer": "CP08_FEATURE_ASSOCIATIONS",
                    "color": 6,
                },
            )

            label = (
                feature["stage2_row"].get("label")
                or feature["stage2_row"].get(
                    "interpreted_feature"
                )
                or "FEATURE"
            )

            msp.add_text(
                str(label),
                dxfattribs={
                    "layer": "CP08_FEATURE_LABELS",
                    "color": 7,
                    "height": 10.0,
                },
            ).set_placement(
                (
                    float(centroid.x) + 12.0,
                    float(centroid.y) + 12.0,
                )
            )

        except Exception:
            pass

    # --------------------------------------------------------
    # Output names
    # --------------------------------------------------------

    # --------------------------------------------------------
    # Master-plan closed polygon count for Stage 3 report
    # --------------------------------------------------------
    # Use the SAME original master-plan DXF that Stage 3
    # feature-to-geometry matching uses.
    # This is reporting only and does not alter matching.
    # Report ONLY the original master-plan closed polygons.
    # Do not count the 147 V11 HPS polygons added to `doc`.
    closed_polygons = _extract_closed_lwpolylines(
        base_plan_doc
    )

    hash_part = (
        str(project_hash)[:12]
        if project_hash
        else "current"
    )

    overlay_path = (
        output_dir
        / f"current_test_project_master_plan_hps_overlay_{hash_part}.dxf"
    )

    association_path = (
        output_dir
        / f"current_test_project_feature_zone_associations_{hash_part}.csv"
    )

    report_path = (
        output_dir
        / f"stage3_runtime_report_{hash_part}.json"
    )

    # --------------------------------------------------------
    # Save outputs
    # --------------------------------------------------------

    doc.saveas(
        str(overlay_path)
    )

    association_df.to_csv(
        association_path,
        index=False,
    )

    report = {
        "success": True,
        "stage": "Stage 3",
        "project_hash": project_hash,
        "master_plan_source": str(
            master_plan_path
        ),
        "zone_count": len(zone_records),
        "stage2_feature_count": int(
            len(stage2_df)
        ),
        "matched_feature_count": int(
            len(matched_features)
        ),
        "association_row_count": int(
            len(association_df)
        ),
        "closed_master_plan_polygon_count": int(
            len(closed_polygons)
        ),
        "overlay_path": str(
            overlay_path
        ),
        "association_path": str(
            association_path
        ),
        "association_method":
            "v11_closed_polygon_intersection",
        "spatial_reference": "Workflow08_V11",
        "review_required": True,
    }

    report_path.write_text(
        json.dumps(
            report,
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )

    return {
        **report,
        "association_df": association_df,
    }
