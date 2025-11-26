"""Tests for the sensor platform of the Growspace Manager integration.

This file contains tests for the various sensor entities created by the
integration, including `GrowspaceOverviewSensor`, `PlantEntity`,
`StrainLibrarySensor`, and `GrowspaceListSensor`. It ensures that these sensors
correctly report their state and attributes based on the data provided by the
coordinator.
"""

import pytest
from unittest.mock import Mock, AsyncMock, MagicMock, patch
from datetime import date, timedelta

from custom_components.growspace_manager.sensor import (
    GrowspaceOverviewSensor,
    PlantEntity,
    StrainLibrarySensor,
    GrowspaceListSensor,
    VpdSensor,
    AirExchangeSensor,
    async_setup_entry,
)
from custom_components.growspace_manager import sensor as sensor_module
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.const import DOMAIN


# --------------------
# Fixtures
# --------------------
@pytest.fixture
def mock_coordinator():
    """Create a mock GrowspaceCoordinator for sensor testing.

    Returns:
        A mock coordinator object with pre-populated growspace and plant data.
    """
    coordinator = Mock()
    coordinator.hass = Mock()
    coordinator.growspaces = {
        "gs1": Mock(
            id="gs1",
            name="Growspace 1",
            rows=2,
            plants_per_row=2,
            notification_target="notify_me",
        )
    }
    coordinator.plants = {
        "p1": Mock(
            plant_id="p1",
            growspace_id="gs1",
            strain="Strain A",
            phenotype="A",
            row=1,
            col=1,
            stage="veg",
            seedling_start=str(date.today() - timedelta(days=5)),
            veg_start=str(date.today() - timedelta(days=3)),
            flower_start=None,
            mother_start=None,
            clone_start=None,
            dry_start=None,
            cure_start=None,
        )
    }
    coordinator.get_growspace_plants.return_value = list(coordinator.plants.values())
    coordinator.calculate_days_in_stage.side_effect = lambda plant, stage: 1
    coordinator.should_send_notification.return_value = True
    coordinator.mark_notification_sent = AsyncMock()
    coordinator.async_add_listener = Mock()
    coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]
    coordinator.get_growspace_options.return_value = ["gs1"]
    coordinator.strains = MagicMock()
    return coordinator


# --------------------
# async_setup_entry
# --------------------
from homeassistant.helpers import entity_registry as er

@pytest.mark.asyncio
async def test_async_setup_entry_adds_entities(mock_coordinator):
    """Test that `async_setup_entry` correctly adds all expected sensor entities."""
    hass = MagicMock()
    hass.config.config_dir = "/config"
    entity_registry = er.async_get(hass)


    # Coordinator mock
    mock_coordinator.growspaces = {
        "gs1": Mock(id="gs1", name="Growspace 1", rows=2, plants_per_row=2, environment_config={})
    }
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()
    mock_coordinator.options = {}

    hass.data = {
        "growspace_manager": {
            "entry_1": {"coordinator": mock_coordinator, "created_entities": []}
        }
    }

    added_entities = []

    # Regular function, not async
    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    await async_setup_entry(hass, Mock(entry_id="entry_1", options={}), async_add_entities)

    # Now entities should be added
    assert added_entities
    assert any(isinstance(e, StrainLibrarySensor) for e in added_entities)
    assert any(isinstance(e, GrowspaceOverviewSensor) for e in added_entities)
    assert any(isinstance(e, GrowspaceListSensor) for e in added_entities)
    assert any(isinstance(e, AirExchangeSensor) for e in added_entities)


@pytest.mark.asyncio
async def test_async_create_derivative_sensors(mock_coordinator):
    """Test that _async_create_derivative_sensors creates trend and statistics sensors."""
    hass = MagicMock()
    config_entry = Mock(entry_id="entry_1")
    growspace = Mock(
        id="gs1",
        name="Growspace 1",
        environment_config={
            "temperature_sensor": "sensor.temp",
            "humidity_sensor": "sensor.humidity",
            "vpd_sensor": "sensor.vpd",
        },
    )
    hass.data = {DOMAIN: {config_entry.entry_id: {"created_entities": []}}}

    with patch(
        "custom_components.growspace_manager.sensor.async_setup_trend_sensor",
        new_callable=AsyncMock,
    ) as mock_setup_trend, patch(
        "custom_components.growspace_manager.sensor.async_setup_statistics_sensor",
        new_callable=AsyncMock,
    ) as mock_setup_stats:
        mock_setup_trend.side_effect = ["trend_1", "trend_2", "trend_3"]
        mock_setup_stats.side_effect = ["stats_1", "stats_2", "stats_3"]

        await sensor_module._async_create_derivative_sensors(
            hass, config_entry, growspace
        )

        assert mock_setup_trend.call_count == 3
        assert mock_setup_stats.call_count == 3

        mock_setup_trend.assert_any_call(
            hass, "sensor.temp", "gs1", growspace.name, "temperature"
        )
        mock_setup_stats.assert_any_call(
            hass, "sensor.temp", "gs1", growspace.name, "temperature"
        )

        created_entities = hass.data[DOMAIN][config_entry.entry_id]["created_entities"]
        assert "trend_1" in created_entities
        assert "stats_1" in created_entities
        assert "trend_2" in created_entities
        assert "stats_2" in created_entities
        assert "trend_3" in created_entities
        assert "stats_3" in created_entities
        assert len(created_entities) == 6



# --------------------
# VpdSensor
# --------------------
def test_vpd_sensor_weather_entity(mock_coordinator):
    """Test VpdSensor with a weather entity."""
    hass = MagicMock()
    weather_state = MagicMock()
    weather_state.attributes = {"temperature": 25, "humidity": 60}
    hass.states.get.return_value = weather_state
    mock_coordinator.hass = hass

    sensor = VpdSensor(mock_coordinator, "outside", "Outside VPD", "weather.test", None, None)
    assert sensor.native_value is not None

def test_vpd_sensor_temp_humidity_entities(mock_coordinator):
    """Test VpdSensor with temperature and humidity sensors."""
    hass = MagicMock()
    temp_state = MagicMock()
    temp_state.state = "25"
    humidity_state = MagicMock()
    humidity_state.state = "60"
    hass.states.get.side_effect = [temp_state, humidity_state]
    mock_coordinator.hass = hass

    sensor = VpdSensor(mock_coordinator, "lung_room", "Lung Room VPD", None, "sensor.temp", "sensor.humidity")
    assert sensor.native_value is not None

def test_vpd_sensor_invalid_states(mock_coordinator):
    """Test VpdSensor with invalid sensor states."""
    hass = MagicMock()
    temp_state = MagicMock()
    temp_state.state = "unknown"
    humidity_state = MagicMock()
    humidity_state.state = "unavailable"
    hass.states.get.side_effect = [temp_state, humidity_state]
    mock_coordinator.hass = hass

    sensor = VpdSensor(mock_coordinator, "lung_room", "Lung Room VPD", None, "sensor.temp", "sensor.humidity")
    assert sensor.native_value is None

# --------------------
# GrowspaceOverviewSensor
# --------------------
def test_growspace_overview_sensor_state_and_attributes(mock_coordinator):
    """Test the state and basic attributes of the `GrowspaceOverviewSensor`.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    gs = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=mock_coordinator.growspaces["gs1"],
    )

    # State should return number of plants
    assert gs.state == 1

    attrs = gs.extra_state_attributes
    assert attrs["total_plants"] == 1
    assert "grid" in attrs
    # Grid positions
    assert attrs["grid"]["position_1_1"]["plant_id"] == "p1"

@pytest.mark.parametrize(
    "special_id, special_name",
    [
        ("dry", "Dry"),
        ("cure", "Cure"),
        ("mother", "Mother"),
        ("clone", "Clone"),
    ],
)
def test_growspace_overview_sensor_special_growspaces(mock_coordinator, special_id, special_name):
    """Test GrowspaceOverviewSensor for special growspaces."""
    special_growspace = Mock(id=special_id, name=special_name)
    sensor = GrowspaceOverviewSensor(mock_coordinator, special_id, special_growspace)
    assert sensor.unique_id == f"{DOMAIN}_{special_id}"

def test_growspace_overview_sensor_days_since_invalid_date(mock_coordinator):
    """Test _days_since with an invalid date string."""
    sensor = GrowspaceOverviewSensor(mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"])
    assert sensor._days_since("not a date") == 0

# --------------------
# PlantEntity
# --------------------
def test_plant_entity_state_and_attributes(mock_coordinator):
    """Test the state and attributes of the `PlantEntity` sensor.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    plant = list(mock_coordinator.plants.values())[0]
    entity = PlantEntity(mock_coordinator, plant)
    state = entity.state
    assert state in [
        "veg",
        "seedling",
        "flower",
        "dry",
        "cure",
        "clone",
        "mother",
        "unknown",
    ]

    attrs = entity.extra_state_attributes
    assert attrs["plant_id"] == plant.plant_id
    assert attrs["strain"] == plant.strain
    assert "veg_days" in attrs

def test_plant_entity_determine_stage(mock_coordinator):
    """Test the _determine_stage method of PlantEntity."""
    plant = mock_coordinator.plants["p1"]
    entity = PlantEntity(mock_coordinator, plant)

    # Test stage hierarchy
    plant.growspace_id = "dry"
    assert entity._determine_stage(plant) == "dry"
    plant.growspace_id = "gs1" # Reset

    plant.flower_start = str(date.today())
    assert entity._determine_stage(plant) == "flower"

    plant.flower_start = None
    plant.veg_start = str(date.today())
    assert entity._determine_stage(plant) == "veg"

    plant.veg_start = None
    plant.seedling_start = str(date.today())
    assert entity._determine_stage(plant) == "seedling"

    plant.seedling_start = None
    plant.stage = "clone"
    assert entity._determine_stage(plant) == "clone"

def test_plant_entity_missing_plant(mock_coordinator):
    """Test PlantEntity when the plant is missing from the coordinator."""
    plant = mock_coordinator.plants["p1"]
    entity = PlantEntity(mock_coordinator, plant)
    mock_coordinator.plants = {}
    assert entity.state == "unknown"
    assert entity.extra_state_attributes == {}

def test_plant_entity_parse_date_invalid(mock_coordinator):
    """Test _parse_date with an invalid date string."""
    entity = PlantEntity(mock_coordinator, mock_coordinator.plants["p1"])
    assert entity._parse_date("not a date") is None

# --------------------
# StrainLibrarySensor
# --------------------
def test_strain_library_sensor_state_and_attributes(mock_coordinator):
    """Test the state and attributes of the `StrainLibrarySensor`.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    # Mock the new data structure from StrainLibrary.get_all()
    # Structure: {strain_name: { "phenotypes": { pheno_name: { "harvests": [], ...meta... } }, "meta": {} }}
    mock_coordinator.strains.get_all.return_value = {
        "Strain A": {
            "phenotypes": {
                "Pheno A": {
                    "harvests": [
                        {"veg_days": 30, "flower_days": 60},
                        {"veg_days": 35, "flower_days": 65},
                    ],
                    "description": "A very nice pheno",
                    "image_path": "/local/img.jpg"
                }
            },
            "meta": {"breeder": "Breeder A"}
        },
        "Strain B": {
            "phenotypes": {
                "default": {
                    "harvests": [{"veg_days": 40, "flower_days": 70}],
                    # No extra metadata
                }
            },
            "meta": {}
        },
        "Strain C": {
            "phenotypes": {
                "Pheno C": {
                    "harvests": [], # No harvests
                    "description": "Not harvested yet"
                }
            },
            "meta": {}
        }
    }

    sensor = StrainLibrarySensor(mock_coordinator)

    # State should be the number of unique strains
    assert sensor.state == 3

    attrs = sensor.extra_state_attributes
    strains_data = attrs["strains"]

    # Check Strain A (with metadata)
    assert "Strain A" in strains_data
    strain_a = strains_data["Strain A"]
    pheno_a = strain_a["phenotypes"]["Pheno A"]

    # Check stats
    assert pheno_a["avg_veg_days"] == 32  # round(65/2)
    assert pheno_a["avg_flower_days"] == 62 # round(125/2)
    assert pheno_a["total_harvests"] == 2

    # Check metadata inclusion
    assert pheno_a["description"] == "A very nice pheno"
    assert pheno_a["image_path"] == "/local/img.jpg"

    # Check harvest exclusion
    assert "harvests" not in pheno_a

    # Check Strain B (no metadata)
    assert "Strain B" in strains_data
    pheno_b = strains_data["Strain B"]["phenotypes"]["default"]
    assert pheno_b["avg_veg_days"] == 40
    assert pheno_b["total_harvests"] == 1
    assert "harvests" not in pheno_b

    # Check Strain C (no harvests but metadata)
    assert "Strain C" in strains_data
    pheno_c = strains_data["Strain C"]["phenotypes"]["Pheno C"]
    assert pheno_c["avg_veg_days"] == 0
    assert pheno_c["total_harvests"] == 0
    assert pheno_c["description"] == "Not harvested yet"

# --------------------
# GrowspaceListSensor
# --------------------
def test_growspace_list_sensor_state_and_attributes(mock_coordinator):
    """Test the state and attributes of the `GrowspaceListSensor`.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    sensor = GrowspaceListSensor(mock_coordinator)
    assert sensor.state == 1
    attrs = sensor.extra_state_attributes
    assert "growspaces" in attrs
    assert attrs["growspaces"] == ["gs1"]
