from pathlib import Path
import json
import csv


class InputValidationError(Exception):
    """Raised when required Workflow 08 inputs are missing or invalid."""


def find_files(filename, search_roots):
    """Find exact filenames under known project folders."""
    matches = []

    for root in search_roots:
        root = Path(root)
        if root.exists():
            matches.extend(
                path for path in root.rglob(filename)
                if path.is_file()
            )

    # Remove duplicate paths while preserving order
    unique = []
    seen = set()

    for path in matches:
        resolved = str(path.resolve())
        if resolved not in seen:
            seen.add(resolved)
            unique.append(path)

    return unique


def inspect_geojson(path):
    """Read GeoJSON metadata without changing the file."""
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        data = json.load(file)

    if data.get("type") != "FeatureCollection":
        raise InputValidationError(
            f"{path.name} is not a GeoJSON FeatureCollection."
        )

    features = data.get("features", [])
    geometry_types = {}
    property_keys = set()

    for feature in features:
        geometry = feature.get("geometry") or {}
        geometry_type = geometry.get("type", "Missing")
        geometry_types[geometry_type] = (
            geometry_types.get(geometry_type, 0) + 1
        )
        property_keys.update(
            (feature.get("properties") or {}).keys()
        )

    return {
        "path": str(path),
        "feature_count": len(features),
        "geometry_types": geometry_types,
        "property_keys": sorted(property_keys),
    }


def inspect_csv(path):
    """Read CSV headers and row count without changing the file."""
    path = Path(path)

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        columns = reader.fieldnames or []
        row_count = sum(1 for _ in reader)

    return {
        "path": str(path),
        "row_count": row_count,
        "columns": columns,
    }


def inspect_dxf(path):
    """Confirm that a DXF exists and report its file size."""
    path = Path(path)

    if not path.is_file():
        raise InputValidationError(f"DXF not found: {path}")

    return {
        "path": str(path),
        "size_bytes": path.stat().st_size,
    }


def discover_workflow08_inputs(working_dir, app_dir):
    """
    Discover expected inputs by exact filename.
    Does not choose between duplicate matches silently.
    """
    roots = [Path(working_dir), Path(app_dir)]

    expected = {
        "master_dxf":
            "Narowal_Master_Plan_Local_Coordinates_Text_Preserved_No_Dimensions.dxf",
        "zones_geojson":
            "coolplan_zones(1).geojson",
        "boundary_geojson":
            "coolplan_confirmed_boundary.geojson",
        "workflow07_register":
            "workflow_07_USER_APPROVED_DECISIONS.csv",
    }

    results = {}

    for key, filename in expected.items():
        matches = find_files(filename, roots)

        if len(matches) == 0:
            results[key] = {
                "status": "MISSING",
                "matches": [],
            }
        elif len(matches) == 1:
            results[key] = {
                "status": "FOUND",
                "path": str(matches[0]),
                "matches": [str(matches[0])],
            }
        else:
            results[key] = {
                "status": "MULTIPLE_MATCHES",
                "matches": [str(path) for path in matches],
            }

    return results
