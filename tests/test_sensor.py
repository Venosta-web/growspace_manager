"""Tests for the sensor platform of the Growspace Manager integration.

This file contains tests for the various sensor entities created by the
integration, including `GrowspaceOverviewSensor`, `PlantEntity`,
`StrainLibrarySensor`, and `GrowspaceListSensor`. It ensures that these sensors
correctly report their state and attributes based on the data provided by the
coordinator.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager import sensor as sensor_module
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.sensor import (
    AirExchangeSensor,
    CalculatedVpdSensor,
    GrowspaceListSensor,
    GrowspaceOverviewSensor,
    PlantEntity,
    StrainLibrarySensor,
    VpdSensor,
    async_setup_entry,
)


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


@pytest.mark.asyncio
async def test_async_setup_entry_adds_entities(mock_coordinator) -> None:
    """Test that `async_setup_entry` correctly adds all expected sensor entities."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

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
    mock_coordinator.get_growspace_plants = Mock(
        return_value=[
            Mock(plant_id="p1", growspace_id="gs1", strain="Strain A", row=1, col=1)
        ]
    )
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()
    mock_coordinator.options = {}

    added_entities = []

    # Regular function, not async
    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    await async_setup_entry(
        hass,
        Mock(
            entry_id="entry_1",
            options={},
            runtime_data=Mock(coordinator=mock_coordinator, created_entities=[]),
        ),
        async_add_entities,
    )

    # Now entities should be added
    assert added_entities
    assert any(isinstance(e, StrainLibrarySensor) for e in added_entities)
    assert any(isinstance(e, GrowspaceOverviewSensor) for e in added_entities)
    assert any(isinstance(e, GrowspaceListSensor) for e in added_entities)
    assert any(isinstance(e, GrowspaceListSensor) for e in added_entities)
    assert any(isinstance(e, AirExchangeSensor) for e in added_entities)
    assert any(isinstance(e, PlantEntity) for e in added_entities)
    assert any(isinstance(e, PlantEntity) for e in added_entities)


@pytest.mark.asyncio
async def test_async_setup_entry_calculated_vpd(mock_coordinator) -> None:
    """Test that `async_setup_entry` creates CalculatedVpdSensor."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    # Growspace with temp/humidity but no VPD sensor
    mock_coordinator.growspaces = {
        "gs1": Mock(
            id="gs1",
            name="Growspace 1",
            rows=2,
            plants_per_row=2,
            environment_config={
                "temperature_sensor": "sensor.temp",
                "humidity_sensor": "sensor.humidity",
                # "vpd_sensor": "sensor.vpd", # Missing
                "lst_offset": -1.5,
            },
        )
    }
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()
    mock_coordinator.options = {}

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    with (
        patch(
            "custom_components.growspace_manager.sensor.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.sensor.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ),
    ):
        await async_setup_entry(
            hass,
            Mock(
                entry_id="entry_1",
                options={},
                runtime_data=Mock(coordinator=mock_coordinator, created_entities=[]),
            ),
            async_add_entities,
        )

    # Check for CalculatedVpdSensor
    calc_vpd = next(
        (e for e in added_entities if isinstance(e, CalculatedVpdSensor)), None
    )
    assert calc_vpd is not None
    assert calc_vpd._lst_offset == -1.5
    assert calc_vpd._temp_sensor == "sensor.temp"
    assert calc_vpd._humidity_sensor == "sensor.humidity"

    # Check that environment_config was updated
    assert (
        mock_coordinator.growspaces["gs1"].environment_config["vpd_sensor"]
        == "sensor.gs1_calculated_vpd"
    )


@pytest.mark.asyncio
async def test_async_setup_entry_global_vpd(mock_coordinator) -> None:
    """Test that `async_setup_entry` creates global VPD sensors."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    mock_coordinator.growspaces = {}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()

    # Global settings in options
    options = {
        "global_settings": {
            "weather_entity": "weather.home",
            "lung_room_temp_sensor": "sensor.lung_temp",
            "lung_room_humidity_sensor": "sensor.lung_hum",
        }
    }

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    await async_setup_entry(
        hass,
        Mock(
            entry_id="entry_1",
            options=options,
            runtime_data=Mock(coordinator=mock_coordinator, created_entities=[]),
        ),
        async_add_entities,
    )

    # Check for global VPD sensors
    outside_vpd = next(
        (
            e
            for e in added_entities
            if isinstance(e, VpdSensor) and e._location_id == "outside"
        ),
        None,
    )
    assert outside_vpd is not None
    assert outside_vpd._weather_entity == "weather.home"

    lung_room_vpd = next(
        (
            e
            for e in added_entities
            if isinstance(e, VpdSensor) and e._location_id == "lung_room"
        ),
        None,
    )
    assert lung_room_vpd is not None
    assert lung_room_vpd._temp_sensor == "sensor.lung_temp"
    assert lung_room_vpd._humidity_sensor == "sensor.lung_hum"


@pytest.mark.asyncio
async def test_async_setup_entry_dynamic_updates(mock_coordinator) -> None:
    """Test dynamic addition and removal of entities."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    mock_coordinator.hass = hass

    mock_coordinator.growspaces = {}
    mock_coordinator.plants = {}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()
    mock_coordinator.options = {}

    # Capture the listener
    listener_callback = None

    def async_add_listener(callback):
        nonlocal listener_callback
        listener_callback = callback

    mock_coordinator.async_add_listener = async_add_listener

    # Capture added entities
    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    # Setup with empty coordinator
    await async_setup_entry(
        hass,
        Mock(
            entry_id="entry_1",
            options={},
            runtime_data=Mock(coordinator=mock_coordinator, created_entities=[]),
        ),
        async_add_entities,
    )

    assert listener_callback is not None

    # 1. Add a growspace and a plant
    new_gs = Mock(id="gs_new", name="New Growspace", environment_config={})
    new_plant = Mock(
        plant_id="p_new", growspace_id="gs_new", strain="New Strain", row=1, col=1
    )

    mock_coordinator.growspaces = {"gs_new": new_gs}
    mock_coordinator.plants = {"p_new": new_plant}

    # Trigger update
    # The listener schedules a task, we need to execute the task
    captured_coro = None

    def mock_create_task(coro):
        nonlocal captured_coro
        captured_coro = coro

    hass.async_create_task = mock_create_task

    # Clear added_entities to track new ones
    added_entities.clear()

    # Trigger listener
    listener_callback()

    # Await the captured coroutine
    if captured_coro:
        await captured_coro

    # Check if new entities were added
    assert any(
        isinstance(e, GrowspaceOverviewSensor) and e.growspace_id == "gs_new"
        for e in added_entities
    )
    assert any(
        isinstance(e, PlantEntity) and e._plant.plant_id == "p_new"
        for e in added_entities
    )

    # 2. Remove the growspace and plant
    mock_coordinator.growspaces = {}
    mock_coordinator.plants = {}

    # Capture removed entities
    # We need to access the entities stored in the closure.
    # Since we can't easily inspect the closure, we can mock the async_remove method of the entities.
    # The entities in added_entities are the ones we added.

    gs_entity = next(
        e for e in added_entities if isinstance(e, GrowspaceOverviewSensor)
    )
    plant_entity = next(e for e in added_entities if isinstance(e, PlantEntity))

    gs_entity.async_remove = AsyncMock()
    plant_entity.async_remove = AsyncMock()
    plant_entity.registry_entry = Mock(entity_id="sensor.plant_entity")

    # Mock entity registry for plant removal
    mock_registry = MagicMock()
    mock_registry.async_get.return_value = Mock(entity_id="sensor.plant_entity")

    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=mock_registry
    ):
        listener_callback()
        if captured_coro:
            await captured_coro

    gs_entity.async_remove.assert_awaited_once()
    plant_entity.async_remove.assert_awaited_once()
    mock_registry.async_remove.assert_called_once()


@pytest.mark.asyncio
async def test_async_create_derivative_sensors(mock_coordinator) -> None:
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
    config_entry.runtime_data = Mock(created_entities=[])

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

        created_entities = config_entry.runtime_data.created_entities
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
def test_vpd_sensor_weather_entity(mock_coordinator) -> None:
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


def test_vpd_sensor_temp_humidity_entities(mock_coordinator) -> None:
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


def test_vpd_sensor_invalid_states(mock_coordinator) -> None:
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


def test_vpd_sensor_value_error(mock_coordinator) -> None:
    """Test VpdSensor handles ValueError during float conversion."""
    hass = MagicMock()
    temp_state = MagicMock()
    temp_state.state = "invalid"
    humidity_state = MagicMock()
    humidity_state.state = "invalid"
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
def test_growspace_overview_sensor_state_and_attributes(mock_coordinator) -> None:
    """Test the state and basic attributes of the `GrowspaceOverviewSensor`.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    gs_mock = mock_coordinator.growspaces["gs1"]
    gs_mock.irrigation_config = {"irrigation_times": [], "drain_times": []}
    gs_mock.environment_config = {}  # Ensure this is also a dict

    gs = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=gs_mock,
    )

    # State should return number of plants
    assert gs.state == 1

    attrs = gs.extra_state_attributes
    assert attrs["total_plants"] == 1
    assert "grid" in attrs
    # Grid positions
    assert attrs["grid"]["position_1_1"]["plant_id"] == "p1"


def test_growspace_overview_sensor_environment_attributes(mock_coordinator) -> None:
    """Test GrowspaceOverviewSensor environment attributes."""
    gs_mock = mock_coordinator.growspaces["gs1"]
    gs_mock.irrigation_config = {}
    gs_mock.environment_config = {
        "dehumidifier_entity": "switch.dehumidifier",
        "control_dehumidifier": True,
        "exhaust_sensor": "sensor.exhaust",
        "humidifier_sensor": "sensor.humidifier",
    }

    hass = MagicMock()

    # Mock states
    dehum_state = MagicMock()
    dehum_state.state = "on"
    dehum_state.attributes = {"humidity": 50, "current_humidity": 55, "mode": "auto"}

    exhaust_state = MagicMock()
    exhaust_state.state = "100"

    humidifier_state = MagicMock()
    humidifier_state.state = "off"

    def get_state(entity_id):
        return {
            "switch.dehumidifier": dehum_state,
            "sensor.exhaust": exhaust_state,
            "sensor.humidifier": humidifier_state,
        }.get(entity_id)

    hass.states.get.side_effect = get_state

    mock_coordinator.hass = hass

    gs = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=gs_mock,
    )

    attrs = gs.extra_state_attributes

    assert attrs["dehumidifier_entity"] == "switch.dehumidifier"
    assert attrs["dehumidifier_state"] == "on"
    assert attrs["dehumidifier_humidity"] == 50
    assert attrs["dehumidifier_current_humidity"] == 55
    assert attrs["dehumidifier_mode"] == "auto"
    assert attrs["dehumidifier_control_enabled"] is True

    assert attrs["exhaust_entity"] == "sensor.exhaust"
    assert attrs["exhaust_state"] == "100"

    assert attrs["humidifier_entity"] == "sensor.humidifier"
    assert attrs["humidifier_state"] == "off"


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
) -> None:
    """Test GrowspaceOverviewSensor for special growspaces."""
    special_growspace = Mock(id=special_id, name=special_name)
    sensor = GrowspaceOverviewSensor(mock_coordinator, special_id, special_growspace)
    assert sensor.unique_id == f"{DOMAIN}_{special_id}"


# --------------------
# PlantEntity
# --------------------
def test_plant_entity_state_and_attributes(mock_coordinator) -> None:
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


def test_plant_entity_missing_plant(mock_coordinator) -> None:
    """Test PlantEntity when the plant is missing from the coordinator."""
    plant = mock_coordinator.plants["p1"]
    entity = PlantEntity(mock_coordinator, plant)
    mock_coordinator.plants = {}
    assert entity.state == "unknown"
    assert entity.extra_state_attributes == {}


@pytest.mark.asyncio
async def test_plant_entity_added_to_hass(mock_coordinator) -> None:
    """Test PlantEntity registers listener when added to hass."""
    plant = list(mock_coordinator.plants.values())[0]
    entity = PlantEntity(mock_coordinator, plant)
    entity.async_write_ha_state = Mock()

    await entity.async_added_to_hass()

    mock_coordinator.async_add_listener.assert_called_once_with(
        entity.async_write_ha_state
    )


# --------------------
# StrainLibrarySensor
# --------------------
def test_strain_library_sensor_state_and_attributes(mock_coordinator) -> None:
    """Test the state and attributes of the `StrainLibrarySensor`.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    # Mock the new data structure from StrainLibrary.get_all()
    # Structure: {strain_name: { "phenotypes": { pheno_name: { "harvests": [], ...meta... } }, "meta": {} }}
    mock_coordinator.strain_library.get_all.return_value = {
        "Strain A": {
            "phenotypes": {
                "Pheno A": {
                    "harvests": [
                        {"veg_days": 30, "flower_days": 60},
                        {"veg_days": 35, "flower_days": 65},
                    ],
                    "description": "A very nice pheno",
                    "image_path": "/local/img.jpg",
                }
            },
            "meta": {"breeder": "Breeder A"},
        },
        "Strain B": {
            "phenotypes": {
                "default": {
                    "harvests": [{"veg_days": 40, "flower_days": 70}],
                    # No extra metadata
                }
            },
            "meta": {},
        },
        "Strain C": {
            "phenotypes": {
                "Pheno C": {
                    "harvests": [],  # No harvests
                    "description": "Not harvested yet",
                }
            },
            "meta": {},
        },
    }

    # Mock get_analytics to return what we expect, since the sensor calls it directly
    mock_coordinator.strain_library.get_analytics.return_value = {
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
                }
            },
            "Strain B": {
                "phenotypes": {
                    "default": {
                        "avg_veg_days": 40,
                        "total_harvests": 1,
                    }
                }
            },
            "Strain C": {
                "phenotypes": {
                    "Pheno C": {
                        "avg_veg_days": 0,
                        "total_harvests": 0,
                        "description": "Not harvested yet",
                    }
                }
            },
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
def test_growspace_list_sensor_state_and_attributes(mock_coordinator) -> None:
    """Test the state and attributes of the `GrowspaceListSensor`.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    sensor = GrowspaceListSensor(mock_coordinator)
    assert sensor.state == 1
    attrs = sensor.extra_state_attributes
    assert "growspaces" in attrs
    assert attrs["growspaces"] == ["gs1"]


# --------------------
# CalculatedVpdSensor
# --------------------
def test_calculated_vpd_sensor(mock_coordinator) -> None:
    """Test CalculatedVpdSensor."""

    hass = MagicMock()
    temp_state = MagicMock()
    temp_state.state = "25"
    humidity_state = MagicMock()
    humidity_state.state = "60"
    hass.states.get.side_effect = [temp_state, humidity_state]
    mock_coordinator.hass = hass

    sensor = CalculatedVpdSensor(
        mock_coordinator,
        "gs1",
        "Growspace 1",
        "sensor.temp",
        "sensor.humidity",
        lst_offset=-2.0,
    )

    assert sensor.native_value is not None
    assert sensor.extra_state_attributes["lst_offset"] == -2.0
    assert (
        sensor.extra_state_attributes["calculation_method"]
        == "Calculated from temperature and humidity"
    )


def test_calculated_vpd_sensor_invalid_states(mock_coordinator) -> None:
    hass = MagicMock()
    temp_state = MagicMock()
    temp_state.state = "unknown"
    humidity_state = MagicMock()
    humidity_state.state = "unavailable"
    hass.states.get.side_effect = [temp_state, humidity_state]
    mock_coordinator.hass = hass

    sensor = CalculatedVpdSensor(
        mock_coordinator, "gs1", "Growspace 1", "sensor.temp", "sensor.humidity"
    )

    assert sensor.native_value is None


def test_calculated_vpd_sensor_value_error(mock_coordinator) -> None:
    """Test CalculatedVpdSensor handles ValueError."""
    hass = MagicMock()
    temp_state = MagicMock()
    temp_state.state = "invalid"
    humidity_state = MagicMock()
    humidity_state.state = "invalid"
    hass.states.get.side_effect = [temp_state, humidity_state]
    mock_coordinator.hass = hass

    sensor = CalculatedVpdSensor(
        mock_coordinator, "gs1", "Growspace 1", "sensor.temp", "sensor.humidity"
    )

    assert sensor.native_value is None


# --------------------
# AirExchangeSensor
# --------------------
def test_air_exchange_sensor(mock_coordinator) -> None:
    """Test AirExchangeSensor."""
    mock_coordinator.data = {"air_exchange_recommendations": {"gs1": "Open Window"}}

    sensor = AirExchangeSensor(mock_coordinator, "gs1")

    assert sensor.state == "Open Window"
    assert sensor.unique_id == f"{DOMAIN}_gs1_air_exchange"
