"""Tests for the environment service handlers."""

from unittest.mock import AsyncMock, Mock, patch
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.growspace_manager.services.environment import (
    handle_configure_environment,
    handle_remove_environment,
    handle_set_dehumidifier_control,
)


@pytest.fixture
def mock_coordinator():
    """Mock the GrowspaceCoordinator."""
    coordinator = Mock()
    coordinator.growspaces = {}
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Mock the StrainLibrary."""
    return Mock()


@pytest.mark.asyncio
async def test_handle_configure_environment_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test successful environment configuration."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.environment_config = {}
    mock_coordinator.growspaces = {"gs1": growspace}

    call = Mock()
    call.data = {
        "growspace_id": "gs1",
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
        "circulation_fan": "switch.fan",
        "stress_threshold": 0.8,
        "mold_threshold": 0.85,
    }

    await handle_configure_environment(
        hass, mock_coordinator, mock_strain_library, call
    )

    assert growspace.environment_config == {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
        "circulation_fan": "switch.fan",
        "stress_threshold": 0.8,
        "mold_threshold": 0.85,
    }
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_handle_configure_environment_missing_growspace(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test environment configuration with missing growspace."""
    mock_coordinator.growspaces = {}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    with pytest.raises(ServiceValidationError, match="Growspace.*not found"):
        await handle_configure_environment(
            hass, mock_coordinator, mock_strain_library, call
        )

    mock_coordinator.async_save.assert_not_called()


@pytest.mark.asyncio
async def test_handle_remove_environment_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test successful environment removal."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.environment_config = {"some": "config"}
    mock_coordinator.growspaces = {"gs1": growspace}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    await handle_remove_environment(hass, mock_coordinator, mock_strain_library, call)

    assert growspace.environment_config == {}
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_handle_remove_environment_missing_growspace(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test environment removal with missing growspace."""
    mock_coordinator.growspaces = {}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    with pytest.raises(ServiceValidationError, match="Growspace.*not found"):
        await handle_remove_environment(
            hass, mock_coordinator, mock_strain_library, call
        )

    mock_coordinator.async_save.assert_not_called()


@pytest.mark.asyncio
async def test_handle_set_dehumidifier_control_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test setting dehumidifier control."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.environment_config = {}
    mock_coordinator.growspaces = {"gs1": growspace}

    call = Mock()
    call.data = {"growspace_id": "gs1", "enabled": True}

    await handle_set_dehumidifier_control(
        hass, mock_coordinator, mock_strain_library, call
    )

    assert growspace.environment_config["control_dehumidifier"] is True
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_handle_set_dehumidifier_control_init_config(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test setting dehumidifier control initializes config if None."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.environment_config = None
    mock_coordinator.growspaces = {"gs1": growspace}

    call = Mock()
    call.data = {"growspace_id": "gs1", "enabled": True}

    await handle_set_dehumidifier_control(
        hass, mock_coordinator, mock_strain_library, call
    )

    assert growspace.environment_config == {"control_dehumidifier": True}
    mock_coordinator.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_handle_set_dehumidifier_control_missing_growspace(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test setting dehumidifier control with missing growspace."""
    mock_coordinator.growspaces = {}

    call = Mock()
    call.data = {"growspace_id": "gs1"}

    with pytest.raises(ServiceValidationError, match="Growspace.*not found"):
        await handle_set_dehumidifier_control(
            hass, mock_coordinator, mock_strain_library, call
        )

    mock_coordinator.async_save.assert_not_called()
