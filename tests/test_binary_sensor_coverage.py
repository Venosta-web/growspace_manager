"""Additional tests for binary_sensor coverage."""

import contextlib
from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.binary_sensor import (
    LightCycleVerificationSensor,
)
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from homeassistant.core import HomeAssistant

from .common import create_plant


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        "test_growspace": Growspace(
            id="test_growspace",
            name="Test Growspace",
        )
    }
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.calculate_days = MagicMock(return_value=0)
    coordinator.async_add_listener = MagicMock()
    # Explicitly mock async_commit as MagicMock to prevent "coroutine never awaited" warnings
    coordinator.async_commit = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()

    def async_create_task(coro: object) -> MagicMock:
        """Mock async_create_task that closes the coroutine to avoid warnings."""
        if coro:
            with contextlib.suppress(AttributeError):
                # Try to close if it has a close method (coroutines do)
                coro.close()  # type: ignore[attr-defined]
        return MagicMock()

    hass.async_create_task = MagicMock(side_effect=async_create_task)
    return hass


@pytest.fixture
def env_config() -> EnvironmentConfig:
    """Environment config fixture."""
    return EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.humidity",
        light_sensors=["binary_sensor.light"],
    )


async def test_light_cycle_sensor_no_light_entity(
    mock_hass: MagicMock, mock_coordinator: MagicMock, env_config: EnvironmentConfig
) -> None:
    """Test LightCycleVerificationSensor with no light entity configured."""
    # Remove light sensor from config
    env_config.light_sensors = []

    sensor = LightCycleVerificationSensor(
        mock_coordinator, "test_growspace", env_config
    )
    sensor.hass = mock_hass
    sensor.async_write_ha_state = MagicMock()

    # This should hit lines 1088-1091
    await sensor.async_update()

    assert sensor._is_schedule_matched is False
    assert sensor._is_correct is False
    sensor.async_write_ha_state.assert_called_once()


async def test_light_cycle_sensor_coordinator_update_callback(
    mock_hass: MagicMock, mock_coordinator: MagicMock, env_config: EnvironmentConfig
) -> None:
    """Test _handle_coordinator_update callback."""
    sensor = LightCycleVerificationSensor(
        mock_coordinator, "test_growspace", env_config
    )
    sensor.hass = mock_hass

    sensor._handle_coordinator_update()

    mock_hass.async_create_task.assert_called_once()


async def test_light_cycle_sensor_light_sensor_changed_callback(
    mock_hass: MagicMock, mock_coordinator: MagicMock, env_config: EnvironmentConfig
) -> None:
    """Test _async_light_sensor_changed callback."""
    sensor = LightCycleVerificationSensor(
        mock_coordinator, "test_growspace", env_config
    )
    sensor.hass = mock_hass

    # This should hit line 1078
    sensor._async_light_sensor_changed(None)

    mock_hass.async_create_task.assert_called_once()


async def test_light_cycle_sensor_flower_stage_early(
    mock_hass: MagicMock, mock_coordinator: MagicMock, env_config: EnvironmentConfig
) -> None:
    """Test _get_current_stage_key with early flower stage."""
    sensor = LightCycleVerificationSensor(
        mock_coordinator, "test_growspace", env_config
    )
    sensor.hass = mock_hass

    # Mock plants with flower_start
    plants = [
        create_plant(
            plant_id="plant1",
            growspace_id="test_growspace",
            strain="Test Strain",
            flower_start="2024-12-10",  # 11 days ago (< 21)
        )
    ]
    mock_coordinator.get_growspace_plants.return_value = plants
    mock_coordinator.calculate_days.return_value = 11

    stage_info = sensor._get_growth_stage_info()
    stage_key = sensor._get_current_stage_key(stage_info)

    assert stage_key == "flower_early"


async def test_light_cycle_sensor_flower_stage_mid(
    mock_hass: MagicMock, mock_coordinator: MagicMock, env_config: EnvironmentConfig
) -> None:
    """Test _get_current_stage_key with mid flower stage."""
    sensor = LightCycleVerificationSensor(
        mock_coordinator, "test_growspace", env_config
    )
    sensor.hass = mock_hass

    # Mock plants with flower_start
    plants = [
        create_plant(
            plant_id="plant1",
            growspace_id="test_growspace",
            strain="Test Strain",
            flower_start="2024-11-20",  # 31 days ago (21-42)
        )
    ]
    mock_coordinator.get_growspace_plants.return_value = plants
    mock_coordinator.calculate_days.return_value = 31

    stage_info = sensor._get_growth_stage_info()
    stage_key = sensor._get_current_stage_key(stage_info)

    assert stage_key == "flower_mid"


async def test_light_cycle_sensor_flower_stage_late(
    mock_hass: MagicMock, mock_coordinator: MagicMock, env_config: EnvironmentConfig
) -> None:
    """Test _get_current_stage_key with late flower stage."""
    sensor = LightCycleVerificationSensor(
        mock_coordinator, "test_growspace", env_config
    )
    sensor.hass = mock_hass

    # Mock plants with flower_start
    plants = [
        create_plant(
            plant_id="plant1",
            growspace_id="test_growspace",
            strain="Test Strain",
            flower_start="2024-10-10",  # 72 days ago (>= 42)
        )
    ]
    mock_coordinator.get_growspace_plants.return_value = plants
    mock_coordinator.calculate_days.return_value = 72

    stage_info = sensor._get_growth_stage_info()
    stage_key = sensor._get_current_stage_key(stage_info)

    assert stage_key == "flower_late"


async def test_light_cycle_sensor_update_state_with_light(
    mock_hass: MagicMock, mock_coordinator: MagicMock, env_config: EnvironmentConfig
) -> None:
    """Test _update_state with light sensor configured."""
    sensor = LightCycleVerificationSensor(
        mock_coordinator, "test_growspace", env_config
    )
    sensor.hass = mock_hass

    # Mock light state
    mock_light_state = MagicMock()
    mock_light_state.state = "on"
    mock_hass.states.get.return_value = mock_light_state

    sensor._update_state()

    assert sensor._is_schedule_matched is True
