"""Tests for the environment service handlers."""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.growspace_manager.models import EnvironmentConfig
from custom_components.growspace_manager.services.environment import (
    handle_configure_environment,
    handle_remove_environment,
    handle_set_dehumidifier_control,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_coordinator():
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.services = MagicMock()
    coordinator.services.save = AsyncMock()
    coordinator.services.request_refresh = AsyncMock()
    coordinator._strain_library = MagicMock()
    _fan_coord_mock = MagicMock()
    _fan_coord_mock.async_restart = AsyncMock()
    coordinator._subsystem_manager = MagicMock()
    coordinator._subsystem_manager.get_circulation_fan_controller = MagicMock(
        return_value=_fan_coord_mock
    )
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Mock the StrainLibrary."""
    return Mock()


@pytest.mark.asyncio
async def test_handle_configure_environment_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test successful environment configuration."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {"gs1": growspace}

    call = Mock()
    call.data = {
        "growspace_id": "gs1",
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
        "circulation_fan_entities": ["switch.fan"],
        "stress_threshold": 0.8,
        "mold_threshold": 0.85,
    }

    await handle_configure_environment(hass, mock_coordinator, call)

    assert growspace.environment_config == EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor="sensor.hum",
        vpd_sensor="sensor.vpd",
        co2_sensor="sensor.co2",
        circulation_fan_entities=["switch.fan"],
        stress_threshold=0.8,
        mold_threshold=0.85,
        substrate_temperature_sensors=[],
        camera_entities=[],
        energy_sensors=[],
        electricity_cost_per_kwh=None,
    )
    mock_coordinator.services.save.assert_awaited_once()
    mock_coordinator.services.request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_configure_environment_missing_growspace(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test environment configuration with missing growspace."""
    mock_coordinator.growspaces = {}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    with pytest.raises(ServiceValidationError, match="Growspace.*not found"):
        await handle_configure_environment(hass, mock_coordinator, call)

    mock_coordinator.services.save.assert_not_called()


@pytest.mark.asyncio
async def test_handle_remove_environment_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test successful environment removal."""
    growspace = Mock(
        name="Test Growspace",
        environment_config=EnvironmentConfig(light_sensors=["sensor.light_1"]),
    )
    mock_coordinator.growspaces = {"gs1": growspace}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    await handle_remove_environment(hass, mock_coordinator, call)

    assert growspace.environment_config == EnvironmentConfig()
    mock_coordinator.services.save.assert_awaited_once()
    mock_coordinator.services.request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_remove_environment_missing_growspace(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test environment removal with missing growspace."""
    mock_coordinator.growspaces = {}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    with pytest.raises(ServiceValidationError, match="Growspace.*not found"):
        await handle_remove_environment(hass, mock_coordinator, call)

    mock_coordinator.services.save.assert_not_called()


@pytest.mark.asyncio
async def test_handle_set_dehumidifier_control_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test setting dehumidifier control."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.environment_config = EnvironmentConfig()
    mock_coordinator.growspaces = {"gs1": growspace}

    call = Mock()
    call.data = {"growspace_id": "gs1", "enabled": True}

    await handle_set_dehumidifier_control(hass, mock_coordinator, call)

    assert growspace.environment_config.control_dehumidifier is True
    mock_coordinator.services.save.assert_awaited_once()
    mock_coordinator.services.request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_set_dehumidifier_control_missing_growspace(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test setting dehumidifier control with missing growspace."""
    mock_coordinator.growspaces = {}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    with pytest.raises(ServiceValidationError, match="Growspace.*not found"):
        await handle_set_dehumidifier_control(hass, mock_coordinator, call)

    mock_coordinator.services.save.assert_not_called()
