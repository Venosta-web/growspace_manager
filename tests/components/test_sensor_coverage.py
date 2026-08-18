"""Additional tests for sensor.py to reach 100% coverage."""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.sensor import (
    DryingWeightSensor,
    ECTargetSensor,
    GrowspaceListSensor,
    _async_create_derivative_sensors,
    _check_subarea_calculated_vpd_sensors,
    _create_initial_entities,
    _get_env_config_val,
    _update_growspace_entities,
)


@pytest.fixture
def setup_sensor_for_test() -> Callable[..., None]:
    """Fixture to set up a sensor with necessary Home Assistant attributes for testing."""

    def _setup(sensor: Any, _coordinator: MagicMock | None = None) -> None:
        # Reuse the coordinator's hass so preconfigured state mocks remain active
        if hasattr(sensor, "coordinator") and hasattr(sensor.coordinator, "hass"):
            sensor.hass = sensor.coordinator.hass
        else:
            sensor.hass = MagicMock()
        sensor.entity_id = "sensor.test_sensor"
        # Ensure platform is mocked to avoid AttributeError: 'NoneType' object has no attribute 'domain'
        sensor.platform = MagicMock()
        sensor.platform.domain = DOMAIN
        # Do not overwrite coordinator if it's already there
        if not hasattr(sensor, "coordinator"):
            sensor.coordinator = MagicMock()
        if not hasattr(sensor.coordinator, "hass"):
            sensor.coordinator.hass = sensor.hass

    return _setup


@pytest.mark.asyncio
async def test_async_create_derivative_sensors_skips_none() -> None:
    """Test that _async_create_derivative_sensors skips None source sensors (Line 116)."""
    hass = MagicMock()
    config_entry = Mock()
    config_entry.runtime_data = Mock()
    config_entry.runtime_data.created_entity_ids = []

    growspace = Mock()
    growspace.id = "gs_test"
    growspace.name = "Test GS"
    # Provide a list with None to trigger Line 116
    growspace.environment_config = Mock(
        temperature_sensors=[None, "sensor.valid_temp"],
        humidity_sensors=[],
        vpd_sensors=[],
        temperature_sensor=None,
        humidity_sensor=None,
        vpd_sensor=None,
    )

    with (
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_trend_sensor",
            new_callable=AsyncMock,
        ) as mock_trend,
        patch(
            "custom_components.growspace_manager.sensor._setup.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ),
    ):
        await _async_create_derivative_sensors(hass, config_entry, growspace)

        # Verify it was called for the valid sensor but not for None
        # Metric map has 3 sensors. temperature has [None, "sensor.valid_temp"].
        # i=0, source_sensor=None -> continue
        # i=1, source_sensor="sensor.valid_temp" -> setup
        mock_trend.assert_any_call(
            hass, "sensor.valid_temp", "gs_test", "Test GS 2", "temperature"
        )


def test_growspace_list_sensor_native_value(
    mock_coordinator: MagicMock,
) -> None:
    """Test GrowspaceListSensor.native_value to cover lines 918-919."""
    # Populate coordinator with at least one growspace
    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}

    sensor = GrowspaceListSensor(mock_coordinator)

    # Initially coordinator has 1 gs
    assert sensor.native_value == 1

    # Add another gs to coordinator
    mock_coordinator.growspaces["gs2"] = Mock(name="Growspace 2")

    # native_value should call _update_growspaces and return 2
    assert sensor.native_value == 2


@pytest.mark.asyncio
async def test_create_initial_entities_subarea_vpd(
    mock_coordinator: MagicMock,
) -> None:
    """Test _create_initial_entities covers subarea calculated VPD entity setup (Lines 287-288)."""
    hass = MagicMock()
    config_entry = Mock()

    subarea = Mock()
    subarea.id = "sub1"
    subarea.name = "Subarea 1"
    subarea.environment_config = {
        "temperature_sensors": ["sensor.temp1"],
        "humidity_sensors": ["sensor.hum1"],
        "vpd_sensors": [],
    }

    growspace = Mock()
    growspace.id = "gs1"
    growspace.name = "GS1"
    growspace.subareas = [subarea]
    growspace.environment_config = {}

    mock_coordinator.growspaces = {"gs1": growspace}
    mock_coordinator.get_growspace_plants.return_value = []

    initial_entities = []
    growspace_entities = {}
    plant_entities = {}
    calculated_vpd_growspace_ids = set()
    calculated_subarea_vpd_ids = set()

    with patch(
        "custom_components.growspace_manager.sensor._setup._async_create_derivative_sensors",
        new_callable=AsyncMock,
    ):
        await _create_initial_entities(
            hass,
            mock_coordinator,
            config_entry,
            initial_entities,
            growspace_entities,
            plant_entities,
            calculated_vpd_growspace_ids,
            calculated_subarea_vpd_ids,
            set(),
        )

    # Verify calculated_subarea_vpd_ids has the unique_id
    assert len(calculated_subarea_vpd_ids) == 1
    # Check that SubareaCalculatedVpdSensor was added to initial_entities
    subarea_vpd_sensors = [
        e
        for e in initial_entities
        if e.__class__.__name__ == "SubareaCalculatedVpdSensor"
    ]
    assert len(subarea_vpd_sensors) == 1


@pytest.mark.asyncio
async def test_update_growspace_entities_new_subarea_vpd(
    mock_coordinator: MagicMock,
) -> None:
    """Test _update_growspace_entities covers dynamic subarea VPD additions (Lines 447-449)."""
    hass = MagicMock()
    config_entry = Mock()

    subarea = Mock()
    subarea.id = "sub1"
    subarea.name = "Subarea 1"
    subarea.environment_config = {
        "temperature_sensors": ["sensor.temp1"],
        "humidity_sensors": ["sensor.hum1"],
        "vpd_sensors": [],
    }

    growspace = Mock()
    growspace.id = "gs1"
    growspace.name = "GS1"
    growspace.subareas = [subarea]
    growspace.environment_config = {}

    mock_coordinator.growspaces = {"gs1": growspace}

    growspace_entities = {}
    async_add_entities = MagicMock()
    calculated_vpd_growspace_ids = set()
    calculated_subarea_vpd_ids = set()

    with patch(
        "custom_components.growspace_manager.sensor._setup._async_create_derivative_sensors",
        new_callable=AsyncMock,
    ):
        await _update_growspace_entities(
            hass,
            mock_coordinator,
            config_entry,
            growspace_entities,
            async_add_entities,
            calculated_vpd_growspace_ids,
            calculated_subarea_vpd_ids,
        )

    assert async_add_entities.called
    assert len(calculated_subarea_vpd_ids) == 1


def test_get_env_config_val_dict_and_attribute_error() -> None:
    """Test _get_env_config_val dictionary and AttributeError fallbacks (Lines 990 & 992-993)."""
    # 1. Test dictionary path (Line 990)
    config_dict = {"my_key": "my_val"}
    assert _get_env_config_val(config_dict, "my_key") == "my_val"
    assert _get_env_config_val(config_dict, "nonexistent", "fallback") == "fallback"

    # 2. Test AttributeError path (Lines 992-993)
    config_obj = Mock()
    orig_getattr = getattr

    def mock_getattr(obj, name, default=None):
        if name == "my_key":
            raise AttributeError("Access error")
        return orig_getattr(obj, name, default)

    with patch(
        "custom_components.growspace_manager.sensor._setup.getattr",
        side_effect=mock_getattr,
    ):
        assert _get_env_config_val(config_obj, "my_key", "default_val") == "default_val"


def test_check_subarea_calculated_vpd_sensors_singular_fallback(
    mock_coordinator: MagicMock,
) -> None:
    """Test _check_subarea_calculated_vpd_sensors fallback to singular vpd_sensor (Line 1017)."""
    subarea = Mock()
    subarea.id = "sub1"
    subarea.name = "Subarea 1"
    # We want temp_sensors/hum_sensors empty to trigger fallbacks to singular keys,
    # and vpd_sensors empty to fallback to vpd_sensor (Line 1017)
    subarea.environment_config = {
        "temperature_sensor": "sensor.temp1",
        "humidity_sensor": "sensor.hum1",
        "vpd_sensor": "sensor.physical_vpd",
    }

    growspace = Mock()
    growspace.id = "gs1"
    growspace.name = "GS1"
    growspace.subareas = [subarea]

    entities = _check_subarea_calculated_vpd_sensors(mock_coordinator, growspace)
    # Since physical_vpd exists and does not contain "calculated_vpd", it shouldn't create a calculated sensor
    assert len(entities) == 0


def test_ec_target_sensor_week_out_of_range(
    mock_coordinator: MagicMock,
    setup_sensor_for_test: Callable[..., None],
) -> None:
    """Test ECTargetSensor native_value returns None when week is out of range (Line 1836)."""
    sensor = ECTargetSensor(mock_coordinator, "test_id", "Test Grow")
    setup_sensor_for_test(sensor)

    mock_curve = MagicMock()
    mock_point = MagicMock()
    mock_point.week = 3
    mock_point.ec_min = 1.0
    mock_point.ec_max = 2.0
    mock_curve.points = [mock_point]
    mock_curve.stage = "flower"
    mock_curve.name = "Standard"

    sensor._get_active_curve = MagicMock(return_value=mock_curve)

    # Test week less than last point's week, should return None (Line 1836)
    sensor._get_current_week = MagicMock(return_value=1)
    assert sensor.native_value is None

    # Verify the week >= last.week check returns midpoint
    sensor._get_current_week = MagicMock(return_value=4)
    assert sensor.native_value == 1.5


def test_drying_weight_sensor_no_plant(
    mock_coordinator: MagicMock,
    setup_sensor_for_test: Callable[..., None],
) -> None:
    """Test DryingWeightSensor returns empty attributes if plant is missing (Line 2016)."""
    mock_plant = MagicMock()
    mock_plant.plant_id = "plant_1"
    mock_plant.growspace_id = "gs_1"

    # Set up plants and growspaces in coordinator
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.growspaces = {"gs_1": MagicMock()}
    mock_coordinator._data_repository.get_plant.side_effect = lambda plant_id: (
        mock_coordinator.plants.get(plant_id)
    )

    sensor = DryingWeightSensor(mock_coordinator, mock_plant)
    setup_sensor_for_test(sensor)

    # 1. Access attributes when plant exists
    mock_plant.harvest_metrics.wet_weight = 100.0
    mock_plant.drying_data.weight_log = []

    attrs = sensor.extra_state_attributes
    assert attrs["weight_lost_pct"] is None

    # 2. Remove plant so _get_plant() returns None, hitting Line 2016
    mock_coordinator.plants = {}
    assert sensor.extra_state_attributes == {}
