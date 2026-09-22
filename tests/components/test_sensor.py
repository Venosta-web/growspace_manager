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
from custom_components.growspace_manager.models import (
    DryingData,
    EnvironmentConfig,
    HarvestMetrics,
    IrrigationTank,
)
from custom_components.growspace_manager.models.plant import PhenotypeScore
from custom_components.growspace_manager.sensor import (
    AirExchangeSensor,
    CalculatedVpdSensor,
    GrowspaceListSensor,
    GrowspaceOverviewSensor,
    PlantEntity,
    StrainLibrarySensor,
    VisionCheckupSensor,
    VpdSensor,
    async_setup_entry,
)


# --------------------
# Fixtures
# --------------------
@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Create a mock GrowspaceCoordinator for sensor testing.

    Returns:
        A mock coordinator object with pre-populated growspace and plant data.
    """
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    gs1 = MagicMock(
        id="gs1",
        rows=2,
        plants_per_row=2,
        notification_target="notify_me",
    )
    gs1.name = "Growspace 1"
    coordinator.growspaces = {"gs1": gs1}
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
            drying_data=DryingData(),
            harvest_metrics=HarvestMetrics(),
            phenotype_score=PhenotypeScore(),
            phi_clearance_date=None,
        )
    }
    coordinator.services.growspaces.get_growspace_plants.return_value = list(
        coordinator.plants.values()
    )
    coordinator.serializer = MagicMock()

    coordinator.services.notifications.should_send_notification.return_value = True
    coordinator.services.notifications.mark_notification_sent = AsyncMock()
    coordinator.async_add_listener = Mock()
    coordinator.services.config.get_strain_options.return_value = [
        "Strain A",
        "Strain B",
    ]
    coordinator.services.get_growspace_options.return_value = ["gs1"]
    coordinator.strains = MagicMock()
    coordinator.created_entity_ids = []

    # Mock data for serialized growspaces
    coordinator.data = {
        "serialized_growspaces": {
            "gs1": {
                "total_plants": 1,
                "grid": [],
                # Default empty values for environment to prevent KeyErrors in tests
                "dehumidifier_entity": None,
                "dehumidifier_state": None,
                "dehumidifier_humidity": None,
                "dehumidifier_current_humidity": None,
                "dehumidifier_mode": None,
                "dehumidifier_control_enabled": None,
                "exhaust_entity": None,
                "exhaust_state": None,
                "humidifier_entity": None,
                "humidifier_state": None,
            }
        }
    }

    return coordinator


# --------------------
# async_setup_entry
# --------------------


@pytest.mark.asyncio
async def test_async_setup_entry_adds_entities(mock_coordinator: MagicMock) -> None:
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
            environment_config=EnvironmentConfig(),
            subareas=[],
        )
    }
    mock_coordinator.get_growspace_plants = Mock(
        return_value=[
            Mock(plant_id="p1", growspace_id="gs1", strain="Strain A", row=1, col=1)
        ]
    )
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._growspace_manager.ensure_special_growspace = Mock(
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
            runtime_data=mock_coordinator,
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
async def test_async_setup_entry_calculated_vpd(mock_coordinator: MagicMock) -> None:
    """Test that `async_setup_entry` creates CalculatedVpdSensor."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    # Growspace with temp/humidity but no VPD sensor
    gs_mock = Mock(
        id="gs1",
        rows=2,
        plants_per_row=2,
        environment_config=EnvironmentConfig(
            temperature_sensor="sensor.temp",
            humidity_sensor="sensor.humidity",
            lst_offset=-1.5,
        ),
        subareas=[],
    )
    gs_mock.name = "Growspace 1"
    mock_coordinator.growspaces = {"gs1": gs_mock}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._growspace_manager.ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()
    mock_coordinator.options = {}

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ),
    ):
        await async_setup_entry(
            hass,
            Mock(
                entry_id="entry_1",
                options={},
                runtime_data=mock_coordinator,
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

    assert calc_vpd._humidity_sensor == "sensor.humidity"

    # Note: Config patching was moved to coordinator._ensure_calculated_sensors,
    # so environment_config is NOT updated by async_setup_entry.


@pytest.mark.asyncio
async def test_async_setup_entry_vision_sensor(mock_coordinator: MagicMock) -> None:
    """Test that async_setup_entry creates VisionCheckupSensor."""

    hass = MagicMock()
    hass.config.config_dir = "/config"

    # Growspace with camera_entities
    gs_mock = Mock(
        id="gs_vision",
        name="Vision Growspace",
        rows=2,
        plants_per_row=2,
        environment_config=EnvironmentConfig(camera_entities=["camera.cam1"]),
        subareas=[],
    )
    mock_coordinator.growspaces = {"gs_vision": gs_mock}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._growspace_manager.ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()
    mock_coordinator.options = {}

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ),
    ):
        await async_setup_entry(
            hass,
            Mock(
                entry_id="entry_1",
                options={},
                runtime_data=mock_coordinator,
            ),
            async_add_entities,
        )

    # Check for VisionCheckupSensor
    vision_sensor = next(
        (e for e in added_entities if isinstance(e, VisionCheckupSensor)), None
    )
    assert vision_sensor is not None
    assert vision_sensor.unique_id == "gs_vision_vision_checkup"


@pytest.mark.asyncio
async def test_async_setup_entry_global_vpd(mock_coordinator: MagicMock) -> None:
    """Test that `async_setup_entry` creates global VPD sensors."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    mock_coordinator.growspaces = {}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._growspace_manager.ensure_special_growspace = Mock(
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
            runtime_data=mock_coordinator,
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
async def test_async_setup_entry_dynamic_updates(mock_coordinator: MagicMock) -> None:
    """Test dynamic addition and removal of entities."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    mock_coordinator.hass = hass

    mock_coordinator.growspaces = {}
    mock_coordinator.plants = {}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._growspace_manager.ensure_special_growspace = Mock(
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

    # Trigger update
    # The listener schedules a task, we need to execute the task
    captured_coro = None

    def mock_create_background_task(hass_obj, coro, name):
        nonlocal captured_coro
        captured_coro = coro
        return Mock()

    # The config_entry is the Mock we passed to async_setup_entry
    config_entry = Mock(
        entry_id="entry_1",
        options={},
        runtime_data=mock_coordinator,
    )
    config_entry.async_create_background_task = mock_create_background_task
    mock_coordinator.config_entry = config_entry

    # Setup with empty coordinator and our mock config_entry
    await async_setup_entry(
        hass,
        config_entry,
        async_add_entities,
    )

    assert listener_callback is not None

    # 1. Add a growspace and a plant
    new_gs = Mock(
        id="gs_new",
        name="New Growspace",
        environment_config=EnvironmentConfig(),
        irrigation_strategy=Mock(enabled=False),
        subareas=[],
    )
    new_plant = Mock(
        plant_id="p_new", growspace_id="gs_new", strain="New Strain", row=1, col=1
    )

    mock_coordinator.growspaces = {"gs_new": new_gs}
    mock_coordinator.plants = {"p_new": new_plant}

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
async def test_async_create_derivative_sensors(mock_coordinator: MagicMock) -> None:
    """Test that _async_create_derivative_sensors creates trend and statistics sensors."""
    hass = MagicMock()
    config_entry = Mock(entry_id="entry_1")
    growspace = Mock(id="gs1")
    growspace.name = "Growspace 1"
    growspace.environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        vpd_sensor="sensor.vpd",
    )
    config_entry.runtime_data = mock_coordinator

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ) as mock_setup_trend,
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
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
            hass, "sensor.temp", "gs1", "Growspace 1", "temperature"
        )
        mock_setup_stats.assert_any_call(
            hass, "sensor.temp", "gs1", "Growspace 1", "temperature"
        )

        created_entity_ids = config_entry.runtime_data.created_entity_ids
        assert ("binary_sensor", "trend", "trend_1") in created_entity_ids
        assert ("sensor", "statistics", "stats_1") in created_entity_ids
        assert ("binary_sensor", "trend", "trend_2") in created_entity_ids
        assert ("sensor", "statistics", "stats_2") in created_entity_ids
        assert ("binary_sensor", "trend", "trend_3") in created_entity_ids
        assert ("sensor", "statistics", "stats_3") in created_entity_ids
        assert len(created_entity_ids) == 6


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
    sensor.hass = hass
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
    sensor.hass = hass
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
    sensor.hass = hass
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
    sensor.hass = hass
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
    gs_mock.environment_config = EnvironmentConfig()

    gs = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=gs_mock,
    )
    gs.platform = Mock()
    gs.platform.platform_name = "growspace_manager"
    gs.platform_data = gs.platform
    gs.platform.domain = "sensor"

    # State should return number of plants
    assert gs.state == 1

    attrs = gs.extra_state_attributes
    assert attrs["total_plants"] == 1
    attrs = gs.extra_state_attributes
    assert attrs["total_plants"] == 1
    assert "grid" not in attrs


def test_growspace_overview_sensor_environment_attributes(mock_coordinator) -> None:
    """Test GrowspaceOverviewSensor environment attributes."""
    gs_mock = mock_coordinator.growspaces["gs1"]

    # Configure mock coordinator data with expected environment attributes
    mock_coordinator.data = {
        "serialized_growspaces": {
            "gs1": {
                "dehumidifier_entity": "switch.dehumidifier",
                "dehumidifier_state": "on",
                "dehumidifier_humidity": 50,
                "dehumidifier_current_humidity": 55,
                "dehumidifier_mode": "auto",
                "dehumidifier_control_enabled": True,
                "exhaust_entity": "sensor.exhaust",
                "exhaust_state": "100",
                "humidifier_entity": "sensor.humidifier",
                "humidifier_state": "off",
            }
        }
    }

    gs = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=gs_mock,
    )
    gs.platform = Mock()
    gs.platform.platform_name = "growspace_manager"
    gs.platform_data = gs.platform
    gs.platform.domain = "sensor"

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
    ("special_id", "special_name"),
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
    sensor.platform = Mock()
    sensor.platform.platform_name = "growspace_manager"
    sensor.platform_data = sensor.platform
    sensor.platform.domain = "sensor"
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
    entity.platform = MagicMock()
    entity.platform_data = entity.platform
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
    entity.platform = MagicMock()
    entity.platform_data = entity.platform
    mock_coordinator.plants = {}
    assert entity.state == "unknown"
    assert entity.extra_state_attributes == {}


@pytest.mark.asyncio
async def test_plant_entity_added_to_hass(mock_coordinator: MagicMock) -> None:
    """Test PlantEntity registers listener when added to hass."""
    plant = list(mock_coordinator.plants.values())[0]
    entity = PlantEntity(mock_coordinator, plant)
    entity.async_write_ha_state = Mock()

    await entity.async_added_to_hass()

    mock_coordinator.async_add_listener.assert_called_once_with(
        entity._handle_coordinator_update, None
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
    mock_coordinator._strain_library.get_all.return_value = {
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
    mock_coordinator._strain_library.get_analytics.return_value = {
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
        },
        "strain_list": ["Strain A", "Strain B", "Strain C"],
    }

    # Mirror setup on the facade path the sensor actually reads
    mock_coordinator.services.config.strain_library.get_all.return_value = (
        mock_coordinator._strain_library.get_all.return_value
    )
    mock_coordinator.services.config.strain_library.get_analytics.return_value = (
        mock_coordinator._strain_library.get_analytics.return_value
    )

    sensor = StrainLibrarySensor(mock_coordinator)
    sensor.platform = Mock()
    sensor.platform.platform_name = "growspace_manager"
    sensor.platform_data = sensor.platform
    sensor.platform.domain = "sensor"

    # State should be the number of unique strains
    assert sensor.native_value == 3

    attrs = sensor.extra_state_attributes

    # Verify summary attributes are present
    assert attrs["strain_count"] == 3
    assert "Strain A" in attrs["strain_list"]
    assert "Strain B" in attrs["strain_list"]
    assert "Strain C" in attrs["strain_list"]
    assert "last_updated" in attrs
    assert "note" in attrs

    # Verify large data is NOT present
    assert "strains" not in attrs


# --------------------
# Coverage Gaps
# --------------------


@pytest.mark.asyncio
async def test_sensor_coverage_gaps(mock_coordinator: MagicMock) -> None:
    """Test specific coverage gaps identified in sensor.py."""
    hass = MagicMock()
    config_entry = Mock(entry_id="entry_1")
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.hass = hass

    # 1. Test BaseVpdSensor abstract methods and helpers
    class ConcreteVpdSensor(sensor_module.BaseVpdSensor):
        @property
        def native_value(self):
            return 0.0

        @property
        def entities_to_track(self):
            return super().entities_to_track

    base_sensor = ConcreteVpdSensor()
    base_sensor.hass = hass

    # Test NotImplementedError for entities_to_track
    with pytest.raises(NotImplementedError):
        _ = base_sensor.entities_to_track

    # Test _get_float_state with None entity
    assert base_sensor._get_float_state(None) is None

    # Test _handle_source_update
    base_sensor.async_write_ha_state = Mock()
    await base_sensor._handle_source_update(None)
    base_sensor.async_write_ha_state.assert_called_once()

    # 2. Test GrowspaceOverviewSensor with missing coordinator data
    gs_mock = Mock(id="gs_empty", name="Empty GS", environment_config={})
    sensor = GrowspaceOverviewSensor(mock_coordinator, "gs_empty", gs_mock)
    mock_coordinator.data = None
    assert sensor.extra_state_attributes == {}

    # 3. Test CalculatedVpdSensor creation logic fallback and defaults

    # Test object-based environment config (vs dict)
    env_config_obj = EnvironmentConfig(
        temperature_sensor="sensor.t",
        humidity_sensor="sensor.h",
        vpd_sensor=None,  # Trigger creation
    )
    gs_obj_config = Mock(id="gs_obj", name="GS Obj", environment_config=env_config_obj)

    calc_sensors = sensor_module._check_calculated_vpd_sensor(
        mock_coordinator, gs_obj_config
    )
    assert calc_sensors
    assert calc_sensors[0]._lst_offset == -2.0  # Default value
    assert calc_sensors[0].entities_to_track == ["sensor.t", "sensor.h"]

    # Test creation failure (return None) if sensors missing
    gs_missing = Mock(id="gs_miss", environment_config={"temperature_sensor": None})
    assert (
        sensor_module._check_calculated_vpd_sensor(mock_coordinator, gs_missing) == []
    )

    # 4. Test VpdSensor.entities_to_track with all entities
    vpd_sensor = VpdSensor(
        mock_coordinator, "loc", "Name", "weather.x", "sensor.t", "sensor.h"
    )
    assert "weather.x" in vpd_sensor.entities_to_track
    assert "sensor.t" in vpd_sensor.entities_to_track
    assert "sensor.h" in vpd_sensor.entities_to_track


@pytest.mark.asyncio
async def test_update_growspace_entities_removal_registry(
    mock_coordinator: MagicMock,
) -> None:
    """Test removal of entities from registry in _update_growspace_entities."""
    hass = MagicMock()
    config_entry = Mock()

    # Mock entity registry
    registry = MagicMock()
    with patch(
        "homeassistant.helpers.entity_registry.async_get", return_value=registry
    ):
        # Setup existing entity
        gs_id = "gs_deleted"
        entity = MagicMock()
        entity.registry_entry = Mock(entity_id="sensor.gs_deleted_overview")
        entity.async_remove = AsyncMock()

        entities = {gs_id: entity}

        # Coordinator has NO growspaces, triggering removal
        mock_coordinator.growspaces = {}

        await sensor_module._update_growspace_entities(
            hass, mock_coordinator, config_entry, entities, Mock(), set(), set()
        )

        # Verify removal
        registry.async_remove.assert_called_with("sensor.gs_deleted_overview")
        entity.async_remove.assert_awaited_once()


@pytest.mark.asyncio
async def test_async_create_derivative_sensors_object_config(
    mock_coordinator: MagicMock,
) -> None:
    """Test _async_create_derivative_sensors with object-based config."""
    hass = MagicMock()
    config_entry = Mock()
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.created_entity_ids = []

    env_config = EnvironmentConfig(
        temperature_sensor="sensor.t", humidity_sensor="sensor.h", vpd_sensor="sensor.v"
    )
    growspace = Mock(id="gs_obj", name="GS Obj", environment_config=env_config)

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ) as mock_trend,
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ) as mock_stats,
    ):
        mock_trend.return_value = "unique_id"
        mock_stats.return_value = "unique_id"

        await sensor_module._async_create_derivative_sensors(
            hass, config_entry, growspace
        )

        # Should be called for t, h, v (3 times each)
        assert mock_trend.call_count == 3
        assert mock_stats.call_count == 3


# --------------------
# GrowspaceListSensor
# --------------------
def test_growspace_list_sensor_state_and_attributes(
    mock_coordinator: MagicMock,
) -> None:
    """Test the state and attributes of the `GrowspaceListSensor`.

    Args:
        mock_coordinator: The mock coordinator fixture.
    """
    sensor = GrowspaceListSensor(mock_coordinator)
    sensor.platform = MagicMock()
    sensor.platform_data = sensor.platform
    attrs = sensor.extra_state_attributes
    assert "growspaces" in attrs
    assert attrs["growspaces"] == {"gs1": {"name": "Growspace 1", "total_plants": 1}}


def test_growspace_list_sensor_plant_counts_per_growspace() -> None:
    """GrowspaceListSensor reports correct plant counts for each growspace in a single pass."""
    coordinator = MagicMock()
    gs1 = MagicMock()
    gs1.name = "Tent 1"
    gs2 = MagicMock()
    gs2.name = "Tent 2"
    coordinator.growspaces = {"gs1": gs1, "gs2": gs2}
    coordinator.plants = {
        "p1": MagicMock(growspace_id="gs1"),
        "p2": MagicMock(growspace_id="gs1"),
        "p3": MagicMock(growspace_id="gs2"),
    }
    coordinator.async_add_listener = MagicMock()

    sensor = GrowspaceListSensor(coordinator)
    attrs = sensor.extra_state_attributes

    assert attrs["growspaces"]["gs1"]["total_plants"] == 2
    assert attrs["growspaces"]["gs2"]["total_plants"] == 1
    assert attrs["growspaces"]["gs1"]["name"] == "Tent 1"
    assert attrs["growspaces"]["gs2"]["name"] == "Tent 2"


# --------------------
# CalculatedVpdSensor
# --------------------
def test_calculated_vpd_sensor(mock_coordinator: MagicMock) -> None:
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
    sensor.hass = hass

    assert sensor.native_value is not None
    assert sensor.extra_state_attributes["lst_offset"] == -2.0
    assert (
        sensor.extra_state_attributes["calculation_method"]
        == "Calculated from temperature and humidity"
    )


def test_calculated_vpd_sensor_invalid_states(mock_coordinator: MagicMock) -> None:
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
    sensor.hass = hass

    assert sensor.native_value is None


def test_calculated_vpd_sensor_value_error(mock_coordinator: MagicMock) -> None:
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
    sensor.hass = hass

    assert sensor.native_value is None


# --------------------
# AirExchangeSensor
# --------------------
def test_air_exchange_sensor(mock_coordinator: MagicMock) -> None:
    """Test AirExchangeSensor."""
    mock_coordinator.data = {"air_exchange_recommendations": {"gs1": "Open Window"}}

    sensor = AirExchangeSensor(mock_coordinator, "gs1")
    sensor.platform = Mock(platform_name="growspace_manager", domain="sensor")
    sensor.platform_data = sensor.platform

    assert sensor.state == "Open Window"
    assert sensor.unique_id == f"{DOMAIN}_gs1_air_exchange"


@pytest.mark.asyncio
async def test_async_setup_entry_recreates_calculated_vpd(
    mock_coordinator: MagicMock,
) -> None:
    """Test that `async_setup_entry` recreates calculated VPD sensor even if configured."""
    hass = MagicMock()
    hass.config.config_dir = "/config"

    # Growspace with temp/humidity and EXISTING calculated VPD sensor config
    # This simulates the state after a restart where coordinator has persisted the ID
    gs_mock = Mock(
        id="gs1",
        rows=2,
        plants_per_row=2,
        environment_config=EnvironmentConfig(
            temperature_sensor="sensor.temp",
            humidity_sensor="sensor.humidity",
            vpd_sensor="sensor.growspace_1_calculated_vpd",  # Matches expected ID format
            lst_offset=-1.5,
        ),
        subareas=[],
    )
    gs_mock.name = "Growspace 1"
    mock_coordinator.growspaces = {"gs1": gs_mock}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._growspace_manager.ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x
    )
    mock_coordinator.async_set_updated_data = AsyncMock()
    mock_coordinator.options = {}

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ),
    ):
        await async_setup_entry(
            hass,
            Mock(
                entry_id="entry_1",
                options={},
                runtime_data=mock_coordinator,
            ),
            async_add_entities,
        )

    # Check for CalculatedVpdSensor
    # This SHOULD pass if we fix the bug, currently it should fail
    calc_vpd = next(
        (e for e in added_entities if isinstance(e, CalculatedVpdSensor)), None
    )
    assert calc_vpd is not None, "Calculated VPD sensor was not recreated on restart"


# --------------------
# Coverage Gaps
# --------------------


@pytest.mark.asyncio
async def test_growspace_overview_sensor_handle_sensor_update(
    mock_coordinator: MagicMock,
) -> None:
    """Test GrowspaceOverviewSensor._handle_sensor_update method.

    This method should call async_refresh_growspace_data on the coordinator
    and then update the entity state.
    """
    gs_mock = mock_coordinator.growspaces["gs1"]
    gs_mock.environment_config = None

    sensor = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=gs_mock,
    )
    sensor.async_write_ha_state = Mock()

    # Mock the coordinator's async_refresh_growspace_data method
    mock_coordinator.async_refresh_growspace_data = AsyncMock()

    # Mock event
    mock_event = Mock()

    # Call the handler
    await sensor._handle_sensor_update(mock_event)

    # Verify coordinator method was called with correct growspace_id
    mock_coordinator.async_refresh_growspace_data.assert_awaited_once_with("gs1")

    # Verify state update was triggered
    sensor.async_write_ha_state.assert_called_once()


def test_growspace_overview_sensor_get_trackable_sensors(
    mock_coordinator: MagicMock,
) -> None:
    """Test GrowspaceOverviewSensor._get_trackable_sensors method."""
    gs_mock = mock_coordinator.growspaces["gs1"]

    # Test with no environment config
    gs_mock.environment_config = None
    sensor = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=gs_mock,
    )
    assert sensor._get_trackable_sensors() == []

    # Test with environment config containing sensors
    env_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        soil_moisture_sensor="sensor.moisture",
        vpd_sensor="sensor.vpd",
        dehumidifier_entities=["switch.dehumidifier"],
        exhaust_fan_entities=["fan.exhaust"],
        humidifier_entities=[],  # Not configured
        circulation_fan_entities=["fan.circulation"],
    )
    gs_mock.environment_config = env_config

    sensors = sensor._get_trackable_sensors()

    # Should include all configured sensors
    assert "sensor.temp" in sensors
    assert "sensor.humidity" in sensors
    assert "sensor.moisture" in sensors
    assert "sensor.vpd" in sensors
    assert "switch.dehumidifier" in sensors
    assert "fan.exhaust" in sensors
    assert "fan.circulation" in sensors
    # Should not include None values
    assert len(sensors) == 7


def test_growspace_overview_sensor_trackable_attrs_constant() -> None:
    """Test that TRACKABLE_ENVIRONMENT_ATTRS is defined as a class constant."""
    # Verify the constant exists and contains expected attributes
    expected_attrs = (
        "soil_moisture_sensor",
        "temperature_sensor",
        "humidity_sensor",
        "vpd_sensor",
        "dehumidifier_entities",
        "exhaust_fan_entities",
        "humidifier_entities",
        "circulation_fan_entities",
    )

    assert hasattr(GrowspaceOverviewSensor, "TRACKABLE_ENVIRONMENT_ATTRS")
    assert expected_attrs == GrowspaceOverviewSensor.TRACKABLE_ENVIRONMENT_ATTRS


def test_growspace_overview_sensor_get_trackable_sensors_missing_growspace(
    mock_coordinator,
) -> None:
    """Test _get_trackable_sensors when growspace is missing."""
    gs_mock = mock_coordinator.growspaces["gs1"]

    sensor = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=gs_mock,
    )

    # Remove the growspace from coordinator
    mock_coordinator.growspaces = {}

    # Should return empty list
    assert sensor._get_trackable_sensors() == []


@pytest.mark.asyncio
async def test_async_setup_entry_dataclass_tank(mock_coordinator: MagicMock) -> None:
    """Test async_setup_entry with IrrigationTank dataclass instead of dict."""
    hass = MagicMock()

    # Growspace with dataclass tank
    tank = IrrigationTank(
        sensor_entity="sensor.tank", name="Tank 1", enable_prediction=True
    )

    env_config = EnvironmentConfig(irrigation_tanks=[tank])
    gs_mock = Mock(
        id="gs1",
        rows=2,
        plants_per_row=2,
        environment_config=env_config,
        subareas=[],
    )
    gs_mock.name = "Growspace 1"
    mock_coordinator.growspaces = {"gs1": gs_mock}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.options = {}

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    with patch(
        "custom_components.growspace_manager.sensor._setup.TankDepletionPredictor"
    ) as mock_predictor_cls:
        mock_predictor = mock_predictor_cls.return_value
        mock_predictor.async_update = AsyncMock()
        await async_setup_entry(
            hass,
            Mock(
                entry_id="entry_1",
                options={},
                runtime_data=mock_coordinator,
            ),
            async_add_entities,
        )

    # If it didn't crash and we covered the lines, we're good.
    # Lines 280-281: elif hasattr(tank, "enable_prediction"): enable_prediction = tank.enable_prediction
    assert any(isinstance(e, GrowspaceOverviewSensor) for e in added_entities)
