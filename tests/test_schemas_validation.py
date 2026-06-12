"""Tests for schema validation in Growspace Manager."""

import pytest
import voluptuous as vol

from custom_components.growspace_manager.schemas import (
    ADD_STRAIN_SCHEMA,
    SET_IRRIGATION_SETTINGS_SCHEMA,
    SET_IRRIGATION_STRATEGY_SCHEMA,
    UPDATE_STRAIN_META_SCHEMA,
)


def test_set_irrigation_settings_schema_valid() -> None:
    """Test valid irrigation settings."""
    valid_data = {
        "growspace_id": "gs1",
        "irrigation_pump_entity": "switch.pump_1",
        "drain_pump_entity": "switch.pump_2",
        "irrigation_duration": 30,
        "drain_duration": 60,
    }
    # Should not raise
    SET_IRRIGATION_SETTINGS_SCHEMA(valid_data)


def test_set_irrigation_settings_schema_partial_valid() -> None:
    """Test partially filled valid irrigation settings."""
    valid_data = {
        "growspace_id": "gs1",
        "irrigation_pump_entity": "switch.pump_1",
        # drain_pump_entity missing is allowed as it is Optional
    }
    # Should not raise
    SET_IRRIGATION_SETTINGS_SCHEMA(valid_data)


def test_set_irrigation_settings_schema_same_pump_invalid() -> None:
    """Test that same pump for irrigation and drain raises Invalid."""
    invalid_data = {
        "growspace_id": "gs1",
        "irrigation_pump_entity": "switch.shared_pump",
        "drain_pump_entity": "switch.shared_pump",
    }
    with pytest.raises(
        vol.Invalid, match="Irrigation and drain pump cannot be the same entity"
    ):
        SET_IRRIGATION_SETTINGS_SCHEMA(invalid_data)


def test_set_irrigation_settings_schema_different_pumps_valid() -> None:
    """Test that different pumps for irrigation and drain is valid."""
    valid_data = {
        "growspace_id": "gs1",
        "irrigation_pump_entity": "switch.irrigation_pump",
        "drain_pump_entity": "switch.drain_pump",
    }
    # Should not raise
    SET_IRRIGATION_SETTINGS_SCHEMA(valid_data)


def test_set_irrigation_settings_schema_phase_trigger_flags_valid() -> None:
    """Phase trigger booleans and threshold are accepted by the schema."""
    valid_data = {
        "growspace_id": "gs1",
        "auto_advance_p1_to_p2": True,
        "auto_advance_p2_to_p3": False,
        "halt_on_runoff_ec_threshold": 3.5,
    }
    result = SET_IRRIGATION_SETTINGS_SCHEMA(valid_data)
    assert result["auto_advance_p1_to_p2"] is True
    assert result["auto_advance_p2_to_p3"] is False
    assert result["halt_on_runoff_ec_threshold"] == pytest.approx(3.5)


def test_set_irrigation_settings_schema_halt_threshold_none_valid() -> None:
    """halt_on_runoff_ec_threshold=None (disabled) is accepted."""
    valid_data = {
        "growspace_id": "gs1",
        "halt_on_runoff_ec_threshold": None,
    }
    result = SET_IRRIGATION_SETTINGS_SCHEMA(valid_data)
    assert result["halt_on_runoff_ec_threshold"] is None


# ---------------------------------------------------------------------------
# IrrigationStrategy schema — issue 379
# ---------------------------------------------------------------------------


def test_set_irrigation_strategy_schema_accepts_auto_light_tracking() -> None:
    """auto_light_tracking can be set by external callers."""
    data = {"growspace_id": "gs1", "auto_light_tracking": True}
    result = SET_IRRIGATION_STRATEGY_SCHEMA(data)
    assert result["auto_light_tracking"] is True


def test_set_irrigation_strategy_schema_rejects_detected_lights_on_time() -> None:
    """detected_lights_on_time is write-protected — external callers cannot set it."""
    data = {"growspace_id": "gs1", "detected_lights_on_time": "08:00:00"}
    with pytest.raises(vol.Invalid):
        SET_IRRIGATION_STRATEGY_SCHEMA(data)


@pytest.mark.parametrize(
    "field_name",
    [
        "p1_shot_duration_seconds",
        "p1_shot_interval_minutes",
        "p2_shot_duration_seconds",
        "p2_shot_interval_minutes",
        "shot_duration_seconds",
        "shot_interval_minutes",
    ],
)
def test_set_irrigation_strategy_schema_accepts_shot_fields(field_name: str) -> None:
    """Per-phase shot fields and the deprecated shared aliases all validate."""
    data = {"growspace_id": "gs1", field_name: 12}
    result = SET_IRRIGATION_STRATEGY_SCHEMA(data)
    assert result[field_name] == 12


@pytest.mark.parametrize(
    ("schema", "sativa", "indica"),
    [
        (ADD_STRAIN_SCHEMA, 10, 90),
        (ADD_STRAIN_SCHEMA, 50, 50),
        (ADD_STRAIN_SCHEMA, 100, 0),
        (ADD_STRAIN_SCHEMA, None, None),
        (ADD_STRAIN_SCHEMA, None, 100),
        (ADD_STRAIN_SCHEMA, 80, None),
        (UPDATE_STRAIN_META_SCHEMA, 10, 90),
        (UPDATE_STRAIN_META_SCHEMA, 50, 50),
        (UPDATE_STRAIN_META_SCHEMA, 100, 0),
        (UPDATE_STRAIN_META_SCHEMA, None, None),
        (UPDATE_STRAIN_META_SCHEMA, None, 100),
        (UPDATE_STRAIN_META_SCHEMA, 80, None),
    ],
)
def test_genetic_percentages_valid(
    schema: vol.Schema, sativa: int | None, indica: int | None
) -> None:
    """Test valid genetic percentages for strain schemas."""
    data = {
        "strain": "Test Strain",
        "sativa_percentage": sativa,
        "indica_percentage": indica,
    }
    # Should not raise any validation error
    schema(data)


@pytest.mark.parametrize(
    ("schema", "sativa", "indica"),
    [
        (ADD_STRAIN_SCHEMA, 60, 50),
        (ADD_STRAIN_SCHEMA, 100, 1),
        (UPDATE_STRAIN_META_SCHEMA, 60, 50),
        (UPDATE_STRAIN_META_SCHEMA, 100, 1),
    ],
)
def test_genetic_percentages_invalid(
    schema: vol.Schema, sativa: int, indica: int
) -> None:
    """Test invalid genetic percentages (sum > 100) raise vol.Invalid."""
    data = {
        "strain": "Test Strain",
        "sativa_percentage": sativa,
        "indica_percentage": indica,
    }
    with pytest.raises(vol.Invalid, match="exceeds 100%"):
        schema(data)
