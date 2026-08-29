"""Structural guard for the public Irrigation Change action metadata."""

from pathlib import Path

import voluptuous as vol
import yaml

from custom_components.growspace_manager.schemas import (
    SET_IRRIGATION_SETTINGS_SCHEMA,
    SET_IRRIGATION_STRATEGY_SCHEMA,
)
from custom_components.growspace_manager.services.irrigation_change import (
    IRRIGATION_CONFIG_CHANGE_FIELDS,
    IRRIGATION_STRATEGY_CHANGE_FIELDS,
)

ROOT = Path(__file__).resolve().parents[2]
SERVICES_YAML = ROOT / "custom_components" / "growspace_manager" / "services.yaml"

_STRATEGY_WIRE_FIELDS = {
    "shot_duration_seconds",
    "shot_interval_minutes",
    "substrate_media_type",
    "substrate_liters_per_pot",
}


def _fields(schema: vol.Schema) -> set[str]:
    """Return marker names from one voluptuous mapping schema."""
    return {marker.schema for marker in schema.schema if isinstance(marker, vol.Marker)}


def test_irrigation_action_metadata_matches_change_interface() -> None:
    """Both action schemas and metadata expose exactly their owned fields."""
    metadata = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))
    settings_schema = SET_IRRIGATION_SETTINGS_SCHEMA.validators[0]
    expected_settings = {"growspace_id"} | set(IRRIGATION_CONFIG_CHANGE_FIELDS)
    expected_strategy = (
        {"growspace_id"}
        | (set(IRRIGATION_STRATEGY_CHANGE_FIELDS) - {"substrate_profile"})
        | _STRATEGY_WIRE_FIELDS
    )

    assert _fields(settings_schema) == expected_settings
    assert _fields(SET_IRRIGATION_STRATEGY_SCHEMA) == expected_strategy
    assert set(metadata["set_irrigation_settings"]["fields"]) == expected_settings
    assert set(metadata["set_irrigation_strategy"]["fields"]) == expected_strategy
