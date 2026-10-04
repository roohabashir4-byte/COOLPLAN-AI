from pathlib import Path
import json


class Workflow08ConfigError(Exception):
    """Raised when Workflow 08 configuration is invalid."""


def load_json_config(config_path):
    """Load a JSON configuration without modifying the source file."""
    path = Path(config_path)

    if not path.exists():
        raise Workflow08ConfigError(
            f"Configuration file not found: {path}"
        )

    try:
        with path.open("r", encoding="utf-8") as file:
            data = json.load(file)
    except json.JSONDecodeError as exc:
        raise Workflow08ConfigError(
            f"Invalid JSON configuration: {exc}"
        ) from exc

    if not isinstance(data, dict):
        raise Workflow08ConfigError(
            "The configuration root must be a JSON object."
        )

    return data


def find_values_by_key(data, target_key):
    """Find matching keys recursively, preserving their full paths."""
    matches = []

    def walk(value, path=""):
        if isinstance(value, dict):
            for key, child in value.items():
                child_path = f"{path}.{key}" if path else key

                if key.lower() == target_key.lower():
                    matches.append((child_path, child))

                walk(child, child_path)

        elif isinstance(value, list):
            for index, child in enumerate(value):
                walk(child, f"{path}[{index}]")

    walk(data)
    return matches


def build_alignment_plan(config):
    """
    Read the existing alignment settings.

    This function does not transform geometry.
    It reports the configured operations for a later CAD stage.
    """
    rotation_values = find_values_by_key(config, "rotation")
    scale_values = find_values_by_key(config, "scale")
    translation_values = find_values_by_key(config, "translation")

    # Do not infer a rotation from a missing value.
    rotation_required = False
    rotation_value = None

    for key_path, value in rotation_values:
        if value is None:
            continue

        if isinstance(value, (int, float)) and value != 0:
            rotation_required = True
            rotation_value = value
            break

        if isinstance(value, str):
            normalized = value.strip().lower()

            if normalized not in {
                "", "none", "null", "0", "0.0",
                "false", "not required", "no rotation"
            }:
                rotation_required = True
                rotation_value = value
                break

    return {
        "rotation_required": rotation_required,
        "rotation_value": rotation_value,
        "rotation_config_entries": rotation_values,
        "scale_config_entries": scale_values,
        "translation_config_entries": translation_values,
        "geometry_modified": False,
    }
