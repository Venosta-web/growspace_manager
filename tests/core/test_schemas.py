import pytest
import voluptuous as vol

from custom_components.growspace_manager.const import (
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDITY_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_TEMP_SENSOR,
)
from custom_components.growspace_manager.schemas import CONFIGURE_ENVIRONMENT_SCHEMA


def test_configure_environment_schema_supports_multi_entities() -> None:
    """Test that CONFIGURE_ENVIRONMENT_SCHEMA accepts multi-entity selection lists."""

    # Payload with multi-entity lists
    payload = {
        "growspace_id": "test_growspace_id",
        CONF_TEMP_SENSOR: "sensor.temp",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        # Multi-entity fields
        CONF_CIRCULATION_FAN_ENTITIES: ["switch.fan1", "switch.fan2"],
        CONF_LIGHT_SENSORS: ["sensor.light1", "sensor.light2"],
        CONF_EXHAUST_FAN_ENTITIES: ["switch.exhaust1"],
        CONF_HUMIDIFIER_ENTITIES: ["switch.humidifier1"],
        CONF_DEHUMIDIFIER_ENTITIES: ["switch.dehumidifier1", "switch.dehumidifier2"],
    }

    # Should not raise
    try:
        validated = CONFIGURE_ENVIRONMENT_SCHEMA(payload)
    except vol.Error as e:
        pytest.fail(f"Schema validation failed for multi-entity payload: {e}")

    # Verify the lists are preserved
    assert validated[CONF_CIRCULATION_FAN_ENTITIES] == ["switch.fan1", "switch.fan2"]
    assert validated[CONF_LIGHT_SENSORS] == ["sensor.light1", "sensor.light2"]
    assert validated[CONF_EXHAUST_FAN_ENTITIES] == ["switch.exhaust1"]


def test_configure_environment_schema_accepts_vpd_optimal_overrides() -> None:
    """Test that CONFIGURE_ENVIRONMENT_SCHEMA accepts vpd_optimal_overrides."""
    payload = {
        "growspace_id": "test_growspace_id",
        CONF_TEMP_SENSOR: "sensor.temp",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        "vpd_optimal_overrides": {
            "flower_mid": {
                "day": {"low": 0.5, "high": 1.45},
                "night": {"low": 0.6, "high": 1.0},
            },
        },
    }
    try:
        validated = CONFIGURE_ENVIRONMENT_SCHEMA(payload)
    except vol.Error as e:
        pytest.fail(f"Schema rejected vpd_optimal_overrides: {e}")

    assert validated["vpd_optimal_overrides"]["flower_mid"]["day"]["low"] == 0.5


def test_configure_environment_schema_supports_single_entities() -> None:
    """Test that schema still supports single entities passed via list (frontend behavior)."""
    # The frontend now sends lists for these fields even if single selection,
    # but let's ensure the schema handles the basic required fields.

    payload = {
        "growspace_id": "test_growspace_id",
        CONF_TEMP_SENSOR: "sensor.temp",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
    }
    # Should not raise
    try:
        CONFIGURE_ENVIRONMENT_SCHEMA(payload)
    except vol.Error as e:
        pytest.fail(f"Schema validation failed for minimal payload: {e}")


def test_configure_environment_schema_accepts_ac_infinity_devices() -> None:
    """CONFIGURE_ENVIRONMENT_SCHEMA validates AC Infinity bundle lists (ADR-0022)."""
    payload = {
        "growspace_id": "test_growspace_id",
        "exhaust_fan_ac_infinity_devices": [
            {
                "mode_entity": "select.tent_port1_mode",
                "speed_entity": "number.tent_port1_on_speed",
                "on_speed": 8,
            }
        ],
        "humidifier_ac_infinity_devices": [
            {"mode_entity": "select.hum_mode", "speed_entity": "number.hum_speed"}
        ],
    }
    validated = CONFIGURE_ENVIRONMENT_SCHEMA(payload)

    assert validated["exhaust_fan_ac_infinity_devices"][0]["on_speed"] == 8
    # on_speed defaults to 10 when omitted
    assert validated["humidifier_ac_infinity_devices"][0]["on_speed"] == 10


def test_configure_environment_schema_rejects_incomplete_ac_infinity_device() -> None:
    """An AC Infinity bundle missing required entities is rejected."""
    payload = {
        "growspace_id": "test_growspace_id",
        "exhaust_fan_ac_infinity_devices": [{"mode_entity": "select.only_mode"}],
    }
    with pytest.raises(vol.Error):
        CONFIGURE_ENVIRONMENT_SCHEMA(payload)


def test_configure_environment_schema_rejects_out_of_range_on_speed() -> None:
    """on_speed outside the 1-10 AC Infinity intensity range is rejected."""
    payload = {
        "growspace_id": "test_growspace_id",
        "exhaust_fan_ac_infinity_devices": [
            {
                "mode_entity": "select.m",
                "speed_entity": "number.s",
                "on_speed": 11,
            }
        ],
    }
    with pytest.raises(vol.Error):
        CONFIGURE_ENVIRONMENT_SCHEMA(payload)
