"""Workflow 05, Step 1: inspect survey DXF metadata before any spatial alignment.

This module deliberately does not georeference drawings or claim alignment.
It reports what can be established from the DXF itself and flags missing
information that must be resolved before connecting the plan to satellite data.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
import re


def _safe_header(doc: Any, key: str, default: Any = None) -> Any:
    try:
        value = doc.header.get(key, default)
        if value is None:
            return default
        return value
    except Exception:
        return default


def _unit_name(code: Any) -> str:
    names = {
        0: "Unitless / not specified", 1: "Inches", 2: "Feet",
        3: "Miles", 4: "Millimeters", 5: "Centimeters",
        6: "Meters", 7: "Kilometers", 8: "Microinches",
        9: "Mils", 10: "Yards", 11: "Angstroms",
        12: "Nanometers", 13: "Microns", 14: "Decimeters",
        15: "Dekameters", 16: "Hectometers", 17: "Gigameters",
        18: "Astronomical units", 19: "Light years", 20: "Parsecs",
    }
    try:
        return names.get(int(code), f"Unknown INSUNITS code: {code}")
    except (TypeError, ValueError):
        return "Unitless / not specified"


def _entity_points(entity) -> List[Tuple[float, float]]:
    """Extract 2D points from common survey geometry entities."""
    typ = entity.dxftype()
    points: List[Tuple[float, float]] = []
    try:
        if typ == "LINE":
            points = [(float(entity.dxf.start.x), float(entity.dxf.start.y)),
                      (float(entity.dxf.end.x), float(entity.dxf.end.y))]
        elif typ == "LWPOLYLINE":
            points = [(float(p[0]), float(p[1])) for p in entity.get_points("xy")]
        elif typ == "POLYLINE":
            points = [(float(v.dxf.location.x), float(v.dxf.location.y))
                      for v in entity.vertices]
        elif typ == "POINT":
            p = entity.dxf.location
            points = [(float(p.x), float(p.y))]
        elif typ in {"TEXT", "MTEXT"}:
            p = entity.dxf.insert
            points = [(float(p.x), float(p.y))]
    except Exception:
        return []
    return points


def _text_value(entity) -> str:
    try:
        typ = entity.dxftype()
        if typ == "TEXT":
            return str(entity.dxf.text)
        if typ == "MTEXT":
            return str(entity.text)
    except Exception:
        pass
    return ""


def inspect_survey_dxf(path: str | Path) -> Dict[str, Any]:
    """Inspect a DXF and return a conservative survey-readiness report.

    Requires ezdxf. Does not modify the drawing.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Survey file not found: {path}")
    if path.suffix.lower() != ".dxf":
        raise ValueError("Workflow 05 Step 1 currently accepts DXF files only.")

    try:
        import ezdxf
    except ImportError as exc:
        raise ImportError("Install ezdxf to inspect survey DXF files: pip install ezdxf") from exc

    doc = ezdxf.readfile(str(path))
    msp = doc.modelspace()
    entity_counts = Counter()
    layer_counts = Counter()
    points: List[Tuple[float, float]] = []
    text_items: List[Dict[str, str]] = []

    for entity in msp:
        typ = entity.dxftype()
        entity_counts[typ] += 1
        try:
            layer_counts[str(entity.dxf.layer)] += 1
        except Exception:
            layer_counts["(unknown)"] += 1
        points.extend(_entity_points(entity))
        value = _text_value(entity).strip()
        if value:
            text_items.append({"layer": str(getattr(entity.dxf, "layer", "")), "text": value})

    units_code = _safe_header(doc, "$INSUNITS", 0)
    unit_name = _unit_name(units_code)
    if points:
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        extents = {"min_x": min(xs), "min_y": min(ys),
                   "max_x": max(xs), "max_y": max(ys),
                   "width": max(xs) - min(xs), "height": max(ys) - min(ys)}
    else:
        extents = None

    text_blob = "\n".join(item["text"] for item in text_items)
    has_easting = bool(re.search(r"\b(easting|east|\bE\s*[:=])\b", text_blob, re.I))
    has_northing = bool(re.search(r"\b(northing|north|\bN\s*[:=])\b", text_blob, re.I))
    has_coordinate_system_hint = bool(re.search(
        r"\b(UTM|WGS\s*84|EPSG|CRS|coordinate system|grid zone|datum)\b",
        text_blob, re.I))

    warnings = []
    if units_code in (None, 0):
        warnings.append("Drawing units are not specified in DXF metadata; do not assume metres or feet.")
    if not has_coordinate_system_hint:
        warnings.append("No clear CRS/datum/UTM-zone label was detected in drawing text.")
    if not (has_easting and has_northing):
        warnings.append("Explicit Easting/Northing labels were not both detected; inspect survey annotations before georeferencing.")
    if not points:
        warnings.append("No supported geometric points were extracted from model space.")

    ready = bool(points) and units_code not in (None, 0) and has_coordinate_system_hint and has_easting and has_northing
    return {
        "file_name": path.name,
        "format": "DXF",
        "entity_count": sum(entity_counts.values()),
        "entity_types": dict(sorted(entity_counts.items())),
        "layers": dict(sorted(layer_counts.items())),
        "units_code": units_code,
        "units": unit_name,
        "extents": extents,
        "text_item_count": len(text_items),
        "text_samples": text_items[:100],
        "detected_easting_label": has_easting,
        "detected_northing_label": has_northing,
        "detected_crs_hint": has_coordinate_system_hint,
        "survey_ready_for_alignment": ready,
        "alignment_performed": False,
        "warnings": warnings,
        "next_action": (
            "Proceed to plan/survey relationship analysis, then independently validate alignment."
            if ready else
            "Resolve units and coordinate reference information from the survey notes/title block before attempting georeferencing."
        ),
    }
