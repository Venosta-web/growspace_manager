"""Structural guard for the public Irrigation Change action metadata."""

from pathlib import Path

import voluptuous as vol
import yaml

from custom_components.growspace_manager.schemas import (
    SET_IRRIGATION_SETTINGS_SCHEMA,
    SET_IRRIGATION_STRATEGY_SCHEMA,
    SET_STEERING_PHASE_SCHEMA,
)
from custom_components.growspace_manager.services.irrigation_change import (
    IRRIGATION_CONFIG_CHANGE_FIELDS,
    IRRIGATION_PHASE_CHANGE_FIELDS,
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
# [[Dripper Throughput]]: an input spelling of pump_flow_rate_ml_per_sec that
# the change seam collapses during normalization, so it is on the wire but
# never in the stored field set.
_SETTINGS_WIRE_FIELDS = {
    "dripper_liters_per_hour",
    "emitter_count",
}


def _fields(schema: vol.Schema) -> set[str]:
    """Return marker names from one voluptuous mapping schema."""
    return {marker.schema for marker in schema.schema if isinstance(marker, vol.Marker)}


def test_irrigation_action_metadata_matches_change_interface() -> None:
    """Both action schemas and metadata expose exactly their owned fields."""
    metadata = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))
    settings_schema = SET_IRRIGATION_SETTINGS_SCHEMA.validators[0]
    expected_settings = (
        {"growspace_id"} | set(IRRIGATION_CONFIG_CHANGE_FIELDS) | _SETTINGS_WIRE_FIELDS
    )
    expected_strategy = (
        {"growspace_id"}
        | (set(IRRIGATION_STRATEGY_CHANGE_FIELDS) - {"substrate_profile"})
        | _STRATEGY_WIRE_FIELDS
    )

    assert _fields(settings_schema) == expected_settings
    assert _fields(SET_IRRIGATION_STRATEGY_SCHEMA) == expected_strategy
    assert set(metadata["set_irrigation_settings"]["fields"]) == expected_settings
    assert set(metadata["set_irrigation_strategy"]["fields"]) == expected_strategy


def test_steering_phase_action_owns_the_phase_alone() -> None:
    """The phase is writable by its own action and by no other.

    The action names the input ``steering_phase`` — beside ``steering_mode`` —
    for the one stored field ``active_steering_phase``; the derived
    ``phase_changed_at`` is never on the wire.
    """
    metadata = yaml.safe_load(SERVICES_YAML.read_text(encoding="utf-8"))
    expected = {"growspace_id", "steering_phase"}

    assert {"active_steering_phase"} == IRRIGATION_PHASE_CHANGE_FIELDS
    assert _fields(SET_STEERING_PHASE_SCHEMA) == expected
    assert set(metadata["set_steering_phase"]["fields"]) == expected

    settings_schema = SET_IRRIGATION_SETTINGS_SCHEMA.validators[0]
    assert "active_steering_phase" not in _fields(settings_schema)
    assert "steering_phase" not in _fields(settings_schema)
