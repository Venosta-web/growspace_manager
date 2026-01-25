"""Tests for serializers coverage gaps."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationTank,
    Plant,
    PlantGenetics,
    SensorGroup,
)
from custom_components.growspace_manager.serializers import GrowspaceSerializer
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant


@pytest.fixture
def serializer(hass: HomeAssistant):
    """Return a serializer instance."""
    return GrowspaceSerializer(hass)


def test_deserialize_irrigation_config_veg_hours(
    serializer: GrowspaceSerializer,
) -> None:
    """Test sanitization of veg_day_hours in irrigation config."""
    raw_data = {
        "gs1": {
            "id": "gs1",
            "name": "GS 1",
            "irrigation_config": {
                "veg_day_hours": "18",  # String to be converted to int
            },
        }
    }

    growspaces = serializer.deserialize_growspaces(raw_data)
    gs = growspaces["gs1"]

    # Line 153 coverage
    assert gs.irrigation_config.veg_day_hours == 18


def test_deserialize_irrigation_strategy_dict_sanitization(
    serializer: GrowspaceSerializer,
) -> None:
    """Test sanitization of irrigation strategy when provided as a dict."""
    # This covers lines 185-194 in _sanitize_irrigation_strategy
    raw_data = {
        "gs1": {
            "id": "gs1",
            "name": "GS 1",
            "irrigation_strategy": {
                "p0_duration_minutes": "5",
                "p2_stop_before_lights_off_minutes": "120.0",
                "shot_duration_seconds": "15",
                "shot_interval_minutes": 30,
            },
        }
    }

    growspaces = serializer.deserialize_growspaces(raw_data)
    gs = growspaces["gs1"]

    strat = gs.irrigation_strategy
    # Verify values were sanitized/converted and loaded into the object
    assert strat.p0_duration_minutes == 5
    assert strat.p2_stop_before_lights_off_minutes == 120
    assert strat.shot_duration_seconds == 15
    assert strat.shot_interval_minutes == 30


def test_parse_tank_level_fallback(serializer: GrowspaceSerializer) -> None:
    """Test _parse_tank_level with malformed input."""
    # Line 373-386 path
    assert serializer._parse_tank_level("not a number") is None
    assert serializer._parse_tank_level(None) is None
    assert serializer._parse_tank_level("123") == 123.0
    # Test European format
    assert serializer._parse_tank_level("50,5 %") == 50.5


def test_get_environment_attributes_tank_state(
    serializer: GrowspaceSerializer, hass: HomeAssistant
) -> None:
    """Test get_environment_attributes including tank state."""

    tank = IrrigationTank(sensor_entity="sensor.tank1", name="Water Tank")
    gs = Growspace(
        id="gs1",
        name="GS 1",
        environment_config=EnvironmentConfig(irrigation_tanks=[tank]),
    )

    mock_state = MagicMock()
    mock_state.state = "45.0"
    # Reach into the serializer to mock its hass
    serializer.hass.states = MagicMock()
    serializer.hass.states.get.return_value = mock_state

    attrs = serializer._get_environment_attributes(gs)
    # Check if we got anything
    assert "irrigation_tanks" in attrs
    assert len(attrs["irrigation_tanks"]) == 1
    assert attrs["irrigation_tanks"][0]["fill_level"] == 45.0


def test_get_sensor_types_mapping(
    serializer: GrowspaceSerializer, hass: HomeAssistant
) -> None:
    """Test get_sensor_types mapping for all device types."""

    env = EnvironmentConfig(
        circulation_fan_entities=["switch.fan1"],
        humidifier_entities=["switch.hum1"],
        dehumidifier_entities=["switch.dehum1"],
    )
    gs = Growspace(id="gs1", name="GS 1", environment_config=env)

    sensor_types = serializer._get_sensor_types(gs)
    # Line 597, 599, 601 paths
    assert sensor_types["switch.fan1"] == "circulation"
    assert sensor_types["switch.hum1"] == "humidifier"
    assert sensor_types["switch.dehum1"] == "dehumidifier"


def test_get_sensor_types_no_env(serializer: GrowspaceSerializer) -> None:
    """Test get_sensor_types when environment_config is missing."""

    gs = Growspace(id="gs1", name="GS 1", environment_config=None)
    # Line 559 path
    assert serializer._get_sensor_types(gs) == {}


def test_serialize_growspace_full(
    serializer: GrowspaceSerializer, hass: HomeAssistant
) -> None:
    """Test full serialization of a growspace to cover attribute helpers."""
    env = EnvironmentConfig(
        temperature_sensor="sensor.t1",
        humidity_sensor="sensor.h1",
        vpd_sensor="sensor.v1",
        co2_sensor="sensor.c1",
        soil_moisture_sensor="sensor.s1",
        dehumidifier_entities=["switch.d1"],
        humidifier_entities=["switch.hum1"],
        exhaust_fan_entities=["switch.e1"],
        circulation_fan_entities=["switch.cf1"],
        temperature_sensors=["sensor.t1"],
        humidity_sensors=["sensor.h1"],
        vpd_sensors=["sensor.v1"],
        light_sensors=["sensor.l1"],
        control_dehumidifier=True,
    )
    # Add sensor groups to cover 547
    env.sensor_groups = [
        SensorGroup(id="g1", name="G1", x=1.0, y=2.0, temperature_sensors=["sensor.s1"])
    ]
    # Add two tanks to cover multi-tank loop
    env.irrigation_tanks = [
        IrrigationTank(sensor_entity="sensor.tank1", name="T1"),
        IrrigationTank(sensor_entity="sensor.tank2", name="T2"),
    ]

    # Add sensors that are ONLY in single fields to cover 567, 571, 579
    env.temperature_sensor = "sensor.t_single"
    env.temperature_sensors = []
    env.co2_sensor = "sensor.c_single"
    env.soil_moisture_sensor = "sensor.sm_single"

    # Special ID to cover line 217
    gs = Growspace(id="cure", name="Curing Area", environment_config=env)
    # Add irrigation pump to cover 510-511
    gs.irrigation_config = IrrigationConfig(
        irrigation_pump_entity="switch.pump1", drain_pump_entity="switch.drain1"
    )

    # Mock sensors to return numeric strings for all sensors
    mock_state = MagicMock()
    mock_state.state = "25.0"
    serializer.hass.states = MagicMock()
    serializer.hass.states.get.return_value = mock_state

    # Add a plant
    plant = Plant(
        plant_id="p1",
        growspace_id="gs1",
        row=1,
        col=1,
        genetics=PlantGenetics(strain_name="S1"),
    )

    # This should trigger most _get_*_attributes helpers
    serialized = serializer.serialize_growspace(
        gs, plants=[plant], biological_metrics={}
    )
    assert serialized["name"] == "Curing Area"
    assert serialized["type"] == "cure"
    assert len(serialized["irrigation_tanks"]) == 2
    assert "sensor_groups" in serialized
    # Check plural keys which are guaranteed to be there
    assert "humidity_sensors" in serialized

    # Environmental attributes use plural list keys or specific constants
    assert "temperature_sensors" in serialized
    assert "humidity_sensors" in serialized
    assert "vpd_sensors" in serialized
    assert "co2_sensor" in serialized
    assert "soil_moisture_sensor" in serialized


def test_deserialize_plants(serializer: GrowspaceSerializer) -> None:
    """Test plant deserialization."""
    raw_plants = {
        "p1": {
            "plant_id": "p1",
            "growspace_id": "gs1",
            "genetics": {"strain_name": "S1"},
            "row": "1",
            "col": "2",
        }
    }
    plants = serializer.deserialize_plants(raw_plants)
    assert plants["p1"].plant_id == "p1"
    assert plants["p1"].row == 1


def test_ensure_int(serializer: GrowspaceSerializer) -> None:
    """Test _ensure_int helper."""
    # Line 62-63 path
    assert serializer._ensure_int("30.0") == 30
    assert serializer._ensure_int(None) == 0
    assert serializer._ensure_int(123) == 123


def test_get_sensor_value_edge_cases(serializer: GrowspaceSerializer) -> None:
    """Test _get_sensor_value edge cases."""

    # Line 355-363 paths
    assert serializer._get_sensor_value(None) is None

    # Mock sensors to return numeric strings for all sensors
    mock_state = MagicMock()
    mock_state.state = "25.0"
    mock_state.attributes = {"humidity": 50, "current_humidity": 45, "mode": "dry"}

    with patch.object(serializer.hass, "states", MagicMock()) as mock_states:
        mock_states.get.return_value = mock_state
        assert serializer._get_sensor_value("sensor.s1") == 25.0

        mock_states.get.return_value = None
        assert serializer._get_sensor_value("sensor.s1") is None

        mock_state_unknown = MagicMock()
        mock_state_unknown.state = STATE_UNKNOWN
        mock_states.get.return_value = mock_state_unknown
        assert serializer._get_sensor_value("sensor.s1") is None

        mock_state_invalid = MagicMock()
        mock_state_invalid.state = "invalid"
        mock_states.get.return_value = mock_state_invalid
        assert serializer._get_sensor_value("sensor.s1") is None


def test_serialize_plant(serializer: GrowspaceSerializer) -> None:
    """Test plant serialization."""

    plant = Plant(
        plant_id="p1", growspace_id="gs1", genetics=PlantGenetics(strain_name="S1")
    )
    serialized = serializer.serialize_plant(plant)
    assert serialized["plant_id"] == "p1"


def test_raise_invalid_data_type(serializer: GrowspaceSerializer) -> None:
    """Test _raise_invalid_data_type exception (line 172)."""
    with pytest.raises(TypeError):
        serializer._raise_invalid_data_type("id", {}, "int")


def test_deserialize_plants_invalid(serializer: GrowspaceSerializer) -> None:
    """Test deserialize_plants with invalid key (lines 78-83)."""
    # Keys should be IDs, but we test the 'not isinstance' branches
    assert serializer.deserialize_plants({"p1": "not a dict"}) == {}


def test_deserialize_growspaces_invalid(serializer: GrowspaceSerializer) -> None:
    """Test deserialize_growspaces with invalid key (lines 111-116)."""
    assert serializer.deserialize_growspaces({"gs1": "not a dict"}) == {}


def test_grid_generation(serializer: GrowspaceSerializer) -> None:
    """Test rich grid generation."""

    gs = Growspace(id="gs1", name="GS 1", rows=2, plants_per_row=2)
    p1 = Plant(
        plant_id="p1",
        growspace_id="gs1",
        row=1,
        col=1,
        genetics=PlantGenetics(strain_name="S1"),
    )

    grid = serializer._generate_rich_plant_grid(gs, [p1])
    assert len(grid) == 4  # 2x2 = 4 positions
    assert grid["position_1_1"]["plant_id"] == "p1"
    assert grid["position_1_2"] is None
