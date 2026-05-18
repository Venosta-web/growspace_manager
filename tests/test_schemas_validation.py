"""Tests for schema validation in Growspace Manager."""

import pytest
import voluptuous as vol

from custom_components.growspace_manager.schemas import SET_IRRIGATION_SETTINGS_SCHEMA


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
