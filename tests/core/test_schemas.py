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
