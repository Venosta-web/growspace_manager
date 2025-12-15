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
    CalculatedVpdSensor,
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
            irrigation_config={},
            environment_config={},
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
        "gs1": Mock(
            id="gs1",
            name="Growspace 1",
            rows=2,
            plants_per_row=2,
            environment_config={},
        )
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

    await async_setup_entry(
        hass, Mock(entry_id="entry_1", options={}), async_add_entities
    )

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

    with (
        patch(
            "custom_components.growspace_manager.sensor.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ) as mock_setup_trend,
        patch(
            "custom_components.growspace_manager.sensor.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ) as mock_setup_stats,
    ):
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

    sensor = VpdSensor(
        mock_coordinator, "outside", "Outside VPD", "weather.test", None, None
    )
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

    sensor = VpdSensor(
        mock_coordinator,
        "lung_room",
        "Lung Room VPD",
        None,
        "sensor.temp",
        "sensor.humidity",
    )
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

    sensor = VpdSensor(
        mock_coordinator,
        "lung_room",
        "Lung Room VPD",
        None,
        "sensor.temp",
        "sensor.humidity",
    )
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
def test_growspace_overview_sensor_special_growspaces(
    mock_coordinator, special_id, special_name
):
    """Test GrowspaceOverviewSensor for special growspaces."""
    special_growspace = Mock(id=special_id, name=special_name)
    sensor = GrowspaceOverviewSensor(mock_coordinator, special_id, special_growspace)
    assert sensor.unique_id == f"{DOMAIN}_{special_id}"


def test_growspace_overview_sensor_days_since_invalid_date(mock_coordinator):
    """Test _days_since with an invalid date string."""
    sensor = GrowspaceOverviewSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"]
    )
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
    plant.growspace_id = "gs1"  # Reset

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
    # Mock the return value of StrainLibrary.get_analytics()
    # The sensor calls get_analytics() directly.
    # The test expects attrs["strains"] - assuming get_analytics returns { "strains": ... }
    # Based on test structure, the analytics dict structure is:
    analytics_data = {
        "strains": {
            "Strain A": {
                "phenotypes": {
                    "Pheno A": {
                        "avg_veg_days": 32,
                        "avg_flower_days": 62,
                        "total_harvests": 2,
                        "description": "A very nice pheno",
                        "image_path": "/local/img.jpg",
                    }
                },
                "meta": {"breeder": "Breeder A"},
            },
            "Strain B": {
                "phenotypes": {
                    "default": {
                        "avg_veg_days": 40,
                        "total_harvests": 1,
                        # No extra metadata
                    }
                },
                "meta": {},
            },
            "Strain C": {
                "phenotypes": {
                    "Pheno C": {
                        "avg_veg_days": 0,
                        "total_harvests": 0,
                        "description": "Not harvested yet",
                    }
                },
                "meta": {},
            },
        }
    }
    mock_coordinator.strains.get_analytics.return_value = analytics_data
    # Also mock get_all just in case, though it seems unused by the sensor now
    mock_coordinator.strains.get_all.return_value = {}

    sensor = StrainLibrarySensor(mock_coordinator)

    # State should be the number of unique strains (handled by state property which uses get_all in original code!)
    # Wait, check sensor.py: state() calls len(self.coordinator.strains.get_all())
    # So we DO need get_all mocked correctly for state.

    mock_coordinator.strains.get_all.return_value = {
        "Strain A": {},
        "Strain B": {},
        "Strain C": {},
    }

    assert sensor.state == 3

    attrs = sensor.extra_state_attributes
    strains_data = attrs["strains"]

    # Check Strain A (with metadata)
    assert "Strain A" in strains_data
    strain_a = strains_data["Strain A"]
    pheno_a = strain_a["phenotypes"]["Pheno A"]

    # Check stats
    assert pheno_a["avg_veg_days"] == 32
    assert pheno_a["avg_flower_days"] == 62
    assert pheno_a["total_harvests"] == 2

    # Check metadata inclusion
    assert pheno_a["description"] == "A very nice pheno"
    assert pheno_a["image_path"] == "/local/img.jpg"

    # Check Strain B (no metadata)
    assert "Strain B" in strains_data
    pheno_b = strains_data["Strain B"]["phenotypes"]["default"]
    assert pheno_b["avg_veg_days"] == 40
    assert pheno_b["total_harvests"] == 1

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


# =============================================================================
# CalculatedVpdSensor
# =============================================================================


def test_calculated_vpd_sensor_init():
    """Test CalculatedVpdSensor initialization."""
    from custom_components.growspace_manager.sensor import CalculatedVpdSensor

    coordinator = Mock()
    coordinator.hass = MagicMock()

    sensor = CalculatedVpdSensor(
        coordinator,
        "gs1",
        "Growspace 1",
        "sensor.temp",
        "sensor.humidity",
        -2.0,
    )

    assert sensor._attr_name == "Growspace 1 Calculated VPD"
    assert sensor._attr_unique_id == f"{DOMAIN}_gs1_calculated_vpd"
    assert sensor._lst_offset == -2.0


def test_calculated_vpd_sensor_native_value():
    """Test CalculatedVpdSensor native_value calculation."""
    from custom_components.growspace_manager.sensor import CalculatedVpdSensor

    coordinator = Mock()
    hass = MagicMock()

    temp_state = MagicMock()
    temp_state.state = "25"
    humidity_state = MagicMock()
    humidity_state.state = "60"

    hass.states.get.side_effect = (
        lambda x: temp_state if "temp" in x else humidity_state
    )
    coordinator.hass = hass

    sensor = CalculatedVpdSensor(
        coordinator,
        "gs1",
        "Growspace 1",
        "sensor.temp",
        "sensor.humidity",
        -2.0,
    )

    value = sensor.native_value
    assert value is not None
    assert isinstance(value, float)


def test_calculated_vpd_sensor_invalid_states():
    """Test CalculatedVpdSensor with invalid sensor states."""
    from custom_components.growspace_manager.sensor import CalculatedVpdSensor

    coordinator = Mock()
    hass = MagicMock()

    temp_state = MagicMock()
    temp_state.state = "unknown"
    humidity_state = MagicMock()
    humidity_state.state = "unavailable"

    hass.states.get.side_effect = (
        lambda x: temp_state if "temp" in x else humidity_state
    )
    coordinator.hass = hass

    sensor = CalculatedVpdSensor(
        coordinator,
        "gs1",
        "Growspace 1",
        "sensor.temp",
        "sensor.humidity",
    )

    assert sensor.native_value is None


def test_calculated_vpd_sensor_value_error():
    """Test CalculatedVpdSensor when float conversion fails."""
    from custom_components.growspace_manager.sensor import CalculatedVpdSensor

    coordinator = Mock()
    hass = MagicMock()

    temp_state = MagicMock()
    temp_state.state = "not_a_number"
    humidity_state = MagicMock()
    humidity_state.state = "60"

    hass.states.get.side_effect = (
        lambda x: temp_state if "temp" in x else humidity_state
    )
    coordinator.hass = hass

    sensor = CalculatedVpdSensor(
        coordinator,
        "gs1",
        "Growspace 1",
        "sensor.temp",
        "sensor.humidity",
    )

    # Should return None due to ValueError on float conversion
    assert sensor.native_value is None


def test_calculated_vpd_sensor_extra_state_attributes():
    """Test CalculatedVpdSensor extra_state_attributes."""
    from custom_components.growspace_manager.sensor import CalculatedVpdSensor

    coordinator = Mock()
    coordinator.hass = MagicMock()

    sensor = CalculatedVpdSensor(
        coordinator,
        "gs1",
        "Growspace 1",
        "sensor.temp",
        "sensor.humidity",
        -3.0,
    )

    attrs = sensor.extra_state_attributes
    assert attrs["temperature_sensor"] == "sensor.temp"
    assert attrs["humidity_sensor"] == "sensor.humidity"
    assert attrs["lst_offset"] == -3.0
    assert "calculation_method" in attrs


# =============================================================================
# AirExchangeSensor
# =============================================================================


def test_air_exchange_sensor_state(mock_coordinator):
    """Test AirExchangeSensor state property."""
    mock_coordinator.data = {"air_exchange_recommendations": {"gs1": "Open Window"}}

    sensor = AirExchangeSensor(mock_coordinator, "gs1")
    assert sensor.state == "Open Window"


def test_air_exchange_sensor_state_idle(mock_coordinator):
    """Test AirExchangeSensor state returns Idle when no recommendation."""
    mock_coordinator.data = {}

    sensor = AirExchangeSensor(mock_coordinator, "gs1")
    assert sensor.state == "Idle"


def test_air_exchange_sensor_state_missing_growspace(mock_coordinator):
    """Test AirExchangeSensor state when growspace has no specific recommendation."""
    mock_coordinator.data = {"air_exchange_recommendations": {"other_gs": "Ventilate"}}

    sensor = AirExchangeSensor(mock_coordinator, "gs1")
    assert sensor.state == "Idle"


# =============================================================================
# GrowspaceOverviewSensor - Environment Config Attributes
# =============================================================================


def test_growspace_overview_sensor_with_environment_config(mock_coordinator):
    """Test GrowspaceOverviewSensor with environment config attributes."""
    # Mock environment config
    mock_coordinator.growspaces["gs1"].environment_config = {
        "dehumidifier_entity": "humidifier.test",
        "exhaust_sensor": "sensor.exhaust",
        "humidifier_sensor": "sensor.humidifier",
    }

    # Mock hass states
    dehumidifier_state = MagicMock()
    dehumidifier_state.state = "on"
    dehumidifier_state.attributes = {
        "humidity": 50,
        "current_humidity": 65,
        "mode": "auto",
    }

    exhaust_state = MagicMock()
    exhaust_state.state = "75"

    humidifier_state = MagicMock()
    humidifier_state.state = "on"

    def get_state(entity_id):
        if "humidifier.test" in entity_id:
            return dehumidifier_state
        elif "exhaust" in entity_id:
            return exhaust_state
        elif "humidifier" in entity_id:
            return humidifier_state
        return None

    mock_coordinator.hass.states.get = get_state

    sensor = GrowspaceOverviewSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"]
    )
    attrs = sensor.extra_state_attributes

    assert attrs["dehumidifier_entity"] == "humidifier.test"
    assert attrs["dehumidifier_state"] == "on"
    assert attrs["dehumidifier_humidity"] == 50
    assert attrs["dehumidifier_current_humidity"] == 65
    assert attrs["dehumidifier_mode"] == "auto"
    assert attrs["exhaust_entity"] == "sensor.exhaust"
    assert attrs["exhaust_value"] == "75"
    assert attrs["humidifier_entity"] == "sensor.humidifier"
    assert attrs["humidifier_value"] == "on"


def test_growspace_overview_sensor_environment_config_missing_states(mock_coordinator):
    """Test GrowspaceOverviewSensor when environment entities have no state."""
    mock_coordinator.growspaces["gs1"].environment_config = {
        "dehumidifier_entity": "humidifier.missing",
    }

    mock_coordinator.hass.states.get = MagicMock(return_value=None)

    sensor = GrowspaceOverviewSensor(
        mock_coordinator, "gs1", mock_coordinator.growspaces["gs1"]
    )
    attrs = sensor.extra_state_attributes

    assert attrs["dehumidifier_entity"] == "humidifier.missing"
    assert attrs["dehumidifier_state"] is None


# =============================================================================
# PlantEntity - _determine_stage edge cases
# =============================================================================


def test_plant_entity_determine_stage_mother(mock_coordinator):
    """Test _determine_stage for mother growspace."""
    plant = mock_coordinator.plants["p1"]
    plant.growspace_id = "mother"
    entity = PlantEntity(mock_coordinator, plant)
    assert entity._determine_stage(plant) == "mother"


def test_plant_entity_determine_stage_clone(mock_coordinator):
    """Test _determine_stage for clone growspace."""
    plant = mock_coordinator.plants["p1"]
    plant.growspace_id = "clone"
    entity = PlantEntity(mock_coordinator, plant)
    assert entity._determine_stage(plant) == "clone"


def test_plant_entity_determine_stage_cure(mock_coordinator):
    """Test _determine_stage for cure growspace."""
    plant = mock_coordinator.plants["p1"]
    plant.growspace_id = "cure"
    entity = PlantEntity(mock_coordinator, plant)
    assert entity._determine_stage(plant) == "cure"


def test_plant_entity_determine_stage_fallback_to_seedling(mock_coordinator):
    """Test _determine_stage fallback to seedling when no dates or valid stage."""
    plant = mock_coordinator.plants["p1"]
    plant.growspace_id = "gs1"
    plant.flower_start = None
    plant.veg_start = None
    plant.seedling_start = None
    plant.stage = "unknown_stage"

    entity = PlantEntity(mock_coordinator, plant)
    assert entity._determine_stage(plant) == "seedling"


def test_plant_entity_days_to_week():
    """Test PlantEntity._days_to_week helper."""
    assert PlantEntity._days_to_week(0) == 0
    assert PlantEntity._days_to_week(-1) == 0
    assert PlantEntity._days_to_week(1) == 1
    assert PlantEntity._days_to_week(7) == 1
    assert PlantEntity._days_to_week(8) == 2
    assert PlantEntity._days_to_week(14) == 2
    assert PlantEntity._days_to_week(15) == 3


# =============================================================================
# async_setup_entry - Global Settings
# =============================================================================


@pytest.mark.asyncio
async def test_async_setup_entry_with_global_settings(mock_coordinator):
    """Test async_setup_entry creates global VPD sensors when configured."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    mock_coordinator.growspaces = {}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()

    hass.data = {
        "growspace_manager": {
            "entry_1": {"coordinator": mock_coordinator, "created_entities": []}
        }
    }

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    # Config entry with global settings
    config_entry = Mock(
        entry_id="entry_1",
        options={
            "global_settings": {
                "weather_entity": "weather.home",
                "lung_room_temp_sensor": "sensor.lung_temp",
                "lung_room_humidity_sensor": "sensor.lung_humidity",
            }
        },
    )

    await async_setup_entry(hass, config_entry, async_add_entities)

    # Check that VPD sensors were added
    vpd_sensors = [e for e in added_entities if isinstance(e, VpdSensor)]
    assert len(vpd_sensors) == 2
    assert any(s._location_id == "outside" for s in vpd_sensors)
    assert any(s._location_id == "lung_room" for s in vpd_sensors)


@pytest.mark.asyncio
async def test_async_setup_entry_creates_calculated_vpd_sensor(mock_coordinator):
    """Test async_setup_entry creates CalculatedVpdSensor when no VPD sensor configured."""
    from custom_components.growspace_manager.sensor import CalculatedVpdSensor

    hass = MagicMock()
    hass.config.config_dir = "/config"

    mock_coordinator.growspaces = {
        "gs1": Mock(
            id="gs1",
            name="Growspace 1",
            rows=2,
            plants_per_row=2,
            environment_config={
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                # No vpd_sensor - should trigger calculated VPD creation
            },
        )
    }
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()

    hass.data = {
        "growspace_manager": {
            "entry_1": {"coordinator": mock_coordinator, "created_entities": []}
        }
    }

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    config_entry = Mock(entry_id="entry_1", options={})

    with patch(
        "custom_components.growspace_manager.sensor._async_create_derivative_sensors",
        new_callable=AsyncMock,
    ):
        await async_setup_entry(hass, config_entry, async_add_entities)

    # Check that CalculatedVpdSensor was created
    calc_vpd_sensors = [e for e in added_entities if isinstance(e, CalculatedVpdSensor)]
    assert len(calc_vpd_sensors) == 1
    assert calc_vpd_sensors[0]._growspace_id == "gs1"


@pytest.mark.asyncio
async def test_async_setup_entry_recreates_calculated_vpd_sensor_on_restart(
    mock_coordinator,
):
    """Test that CalculatedVpdSensor is recreated if the config already points to it (restart scenario)."""
    hass = MagicMock()
    hass.config.config_dir = "/config"
    hass.data = {
        DOMAIN: {
            "entry_id": {
                "coordinator": mock_coordinator,
                "created_entities": [],
            }
        }
    }

    # Setup growspace with:
    # 1. Temp and Humidity sensors present
    # 2. VPD sensor configured as the EXPECTED calculated ID (simulating a restart)
    # The expected ID is now based on NAME, not ID
    gs_id = "gs_restart"
    gs_name = "Restart Growspace"
    # slugify("Restart Growspace Calculated VPD") -> "restart_growspace_calculated_vpd"
    calculated_id = "sensor.restart_growspace_calculated_vpd"

    # Create valid mock environment config
    env_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": calculated_id,
        "lst_offset": -2.0,
    }

    # Create mock growspace and ensure name is a string, not a Mock object
    gs_mock = Mock(id=gs_id)
    gs_mock.environment_config = env_config
    # Must assign name explicitly because Mock(name=...) is special
    gs_mock.name = gs_name

    mock_coordinator.growspaces = {gs_id: gs_mock}
    mock_coordinator.get_growspace_plants.return_value = []
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._ensure_special_growspace = Mock(return_value="mock_id")

    config_entry = Mock(entry_id="entry_id")
    async_add_entities = Mock()

    # Mock the helper functions to verify call order and execution
    with (
        patch(
            "custom_components.growspace_manager.sensor.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ) as mock_trend,
        patch(
            "custom_components.growspace_manager.sensor.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ) as mock_stats,
    ):
        await async_setup_entry(hass, config_entry, async_add_entities)

        # Verify CalculatedVpdSensor was added to entities
        # async_add_entities is called multiple times (initial, global, air exchange), so we need to inspect all calls
        all_added_entities = []
        for call in async_add_entities.call_args_list:
            all_added_entities.extend(call[0][0])

        calculated_sensors = [
            e for e in all_added_entities if isinstance(e, CalculatedVpdSensor)
        ]
        assert len(calculated_sensors) == 1
        assert calculated_sensors[0].unique_id == f"{DOMAIN}_{gs_id}_calculated_vpd"

        # Verify derivative sensors were created for VPD (which confirms setup_derivative called AFTER creation)
        # Check that setup_trend/stats was called with our calculated ID
        expected_calls = [
            (hass, "sensor.temp", gs_id, "Restart Growspace", "temperature"),
            (hass, "sensor.hum", gs_id, "Restart Growspace", "humidity"),
            (hass, calculated_id, gs_id, "Restart Growspace", "vpd"),
        ]

        # Check call args for trend sensor
        trend_call_args = [call.args for call in mock_trend.call_args_list]
        for expected in expected_calls:
            assert expected in trend_call_args, (
                f"Expected call {expected} not found in trend setup calls"
            )


@pytest.mark.asyncio
async def test_async_setup_entry_migrates_legacy_uuid_vpd_sensor(
    mock_coordinator,
):
    """Test that CalculatedVpdSensor is recreated and config migrated if pointing to legacy UUID ID."""
    hass = MagicMock()
    hass.config.config_dir = "/config"
    hass.data = {
        DOMAIN: {
            "entry_id": {
                "coordinator": mock_coordinator,
                "created_entities": [],
            }
        }
    }

    # Setup growspace with legacy UUID-based VPD sensor configured
    gs_id = "gs_legacy"
    gs_name = "Legacy Growspace"
    old_uuid_id = f"sensor.{gs_id}_calculated_vpd"

    # Create valid mock environment config with the OLD ID
    env_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": old_uuid_id,
        "lst_offset": -2.0,
    }

    # Mock growspace
    gs_mock = Mock(id=gs_id)
    gs_mock.environment_config = env_config
    gs_mock.name = gs_name

    mock_coordinator.growspaces = {gs_id: gs_mock}
    mock_coordinator.get_growspace_plants.return_value = []
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._ensure_special_growspace = Mock(return_value="mock_id")

    config_entry = Mock(entry_id="entry_id")
    async_add_entities = Mock()

    with (
        patch(
            "custom_components.growspace_manager.sensor.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ) as mock_trend,
        patch(
            "custom_components.growspace_manager.sensor.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ) as mock_stats,
    ):
        await async_setup_entry(hass, config_entry, async_add_entities)

        # Verify CalculatedVpdSensor was created
        all_added_entities = []
        for call in async_add_entities.call_args_list:
            all_added_entities.extend(call[0][0])

        calculated_sensors = [
            e for e in all_added_entities if isinstance(e, CalculatedVpdSensor)
        ]
        assert len(calculated_sensors) == 1

        # Verify config was updated to the NEW Name-based ID
        from homeassistant.util import slugify

        expected_new_id = f"sensor.{slugify('Legacy Growspace Calculated VPD')}"
        assert gs_mock.environment_config["vpd_sensor"] == expected_new_id
