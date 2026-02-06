from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
    IrrigationTank,
    Plant,
    SensorGroup,
)
from custom_components.growspace_manager.presentation.growspace_view_model import (
    GrowspaceViewModelBuilder,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def builder(hass: HomeAssistant) -> GrowspaceViewModelBuilder:
    """Fixture for GrowspaceViewModelBuilder."""
    return GrowspaceViewModelBuilder(hass)


def test_growspace_view_model_build_basic(hass: HomeAssistant, builder):
    """Test basic build functionality."""
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.temp", humidity_sensor="sensor.hum"
    )
    growspace = Growspace(
        id="gs1",
        name="Test Room",
        rows=2,
        plants_per_row=2,
        environment_config=env_config,
    )

    plant1 = Plant(plant_id="p1", growspace_id="gs1", row=1, col=1)
    plants = [plant1]

    # Mock EntityQueries and PlantViewModelBuilder on the builder instance
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_overview_entity_id.return_value = (
        "sensor.gs1_overview"
    )
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"

    builder.plant_builder = MagicMock()
    builder.plant_builder.build.return_value = {"plant_id": "p1", "rich": True}

    result = builder.build(
        growspace=growspace,
        plants=plants,
        biological_metrics={"metrics": True},
        max_veg_days=10,
        max_flower_days=20,
    )

    assert result["growspace_id"] == "gs1"
    assert result["name"] == "Test Room"
    assert result["total_plants"] == 1
    assert result["veg_week"] == 2
    assert result["flower_week"] == 3
    assert result["metrics"] is True
    assert result["grid"]["position_1_1"]["rich"] is True
    assert result["grid"]["position_1_2"] is None


def test_get_sensor_types(builder):
    """Test mapping of entity IDs to sensor types."""
    env_config = EnvironmentConfig(
        temperature_sensors=["sensor.t1", "sensor.t2"],
        humidity_sensors=["sensor.h1"],
        vpd_sensor="sensor.v1",
        light_sensors=["sensor.l1"],
        co2_sensor="sensor.co2",
        soil_moisture_sensor="sensor.soil",
        exhaust_fan_entities=["switch.exhaust"],
        circulation_fan_entities=["switch.circ"],
        humidifier_entities=["switch.hum"],
        dehumidifier_entities=["switch.dehum"],
        irrigation_tanks=[IrrigationTank(sensor_entity="sensor.tank", name="Tank 1")],
    )
    irr_config = IrrigationConfig(
        irrigation_pump_entity="switch.pump", drain_pump_entity="switch.drain"
    )
    growspace = Growspace(
        id="gs1",
        name="Test",
        environment_config=env_config,
        irrigation_config=irr_config,
    )

    types = builder._get_sensor_types(growspace)

    assert types["sensor.t1"] == "temperature"
    assert types["sensor.t2"] == "temperature"
    assert types["sensor.h1"] == "humidity"
    assert types["sensor.v1"] == "vpd"
    assert types["sensor.l1"] == "light"
    assert types["sensor.co2"] == "co2"
    assert types["sensor.soil"] == "soil_moisture"
    assert types["switch.exhaust"] == "exhaust"
    assert types["switch.circ"] == "circulation"
    assert types["switch.hum"] == "humidifier"
    assert types["switch.dehum"] == "dehumidifier"
    assert types["switch.pump"] == "irrigation_pump"
    assert types["switch.drain"] == "drain_pump"
    assert types["sensor.tank"] == "irrigation_tank"


def test_get_environment_attributes(hass: HomeAssistant, builder):
    """Test extraction of environment attributes from hass states."""
    env_config = EnvironmentConfig(
        dehumidifier_entities=["humidifier.dehum"],
        exhaust_fan_entities=["fan.exhaust"],
        vpd_sensor="sensor.vpd",
        soil_moisture_sensor="sensor.soil",
        temperature_sensor="sensor.temp",
        irrigation_tanks=[
            IrrigationTank(
                sensor_entity="sensor.tank", name="Test Tank", warning_level=20
            )
        ],
        sensor_groups=[SensorGroup(id="g1", name="Group 1", x=1, y=2)],
    )
    growspace = Growspace(
        id="gs1",
        name="Test",
        environment_config=env_config,
        irrigation_config=IrrigationConfig(irrigation_pump_entity="switch.pump"),
    )

    # Mock states
    hass.states.async_set(
        "humidifier.dehum",
        "on",
        {"humidity": 50, "current_humidity": 55, "mode": "Normal"},
    )
    hass.states.async_set("fan.exhaust", "on")
    hass.states.async_set("sensor.vpd", "1.2")
    hass.states.async_set("sensor.soil", "45")
    hass.states.async_set("switch.pump", "off")
    hass.states.async_set("sensor.tank", "15")  # Below warning level

    with patch.object(builder.entity_queries, "parse_tank_level", return_value=15.0):
        attrs = builder._get_environment_attributes(growspace)

        assert attrs["dehumidifier_state"] == "on"
        assert attrs["dehumidifier_humidity"] == 50
        assert attrs["exhaust_state"] == "on"
        assert attrs["vpd"] == "1.2"
        assert attrs["soil_moisture_value"] == "45"
        assert attrs["irrigation_pump_state"] == "off"
        assert len(attrs["irrigation_tanks"]) == 1
        assert attrs["irrigation_tanks"][0]["is_warning"] is True
        assert attrs["sensor_groups"][0]["id"] == "g1"


def test_build_special_growspace_types(builder):
    """Test building payload for special growspace IDs."""
    builder.entity_queries = MagicMock()
    builder.plant_builder = MagicMock()

    for gs_id in ("mother", "clone", "dry", "cure"):
        growspace = Growspace(id=gs_id, name=gs_id.capitalize())
        result = builder.build(growspace, [], {})
        assert result["type"] == gs_id


def test_air_exchange_recommendation(hass: HomeAssistant, builder):
    """Test air exchange recommendation lookup."""
    hass.data[DOMAIN] = {"air_exchange_recommendations": {"gs1": "High"}}
    growspace = Growspace(id="gs1", name="Test")

    # Use a minimal mock for helpers that are called during build
    with (
        patch.multiple(
            builder,
            _build_rich_plant_grid=MagicMock(return_value={}),
            _get_sensor_types=MagicMock(return_value={}),
            _get_environment_attributes=MagicMock(return_value={}),
        ),
        patch.object(
            builder.entity_queries,
            "lookup_overview_entity_id",
            return_value="sensor.ov",
        ),
    ):
        result = builder.build(growspace, [], {})
        assert result["air_exchange"] == "High"


def test_missing_environment_config(builder):
    """Test functionality when environment_config is missing."""
    growspace = Growspace(id="gs1", name="Test Room", environment_config=None)

    # Line 194: _get_sensor_types
    sensor_types = builder._get_sensor_types(growspace)
    assert sensor_types == {}

    # Line 270: _get_environment_attributes
    attrs = builder._get_environment_attributes(growspace)
    assert attrs == {}

    # Verify build still works
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_overview_entity_id.return_value = "sensor.ov"
    result = builder.build(growspace, [], {})
    assert result["growspace_id"] == "gs1"
    assert result["sensor_types"] == {}
