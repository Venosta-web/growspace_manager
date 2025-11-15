"""Tests for the environment services."""
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from homeassistant.core import HomeAssistant, ServiceCall
from custom_components.growspace_manager.services.environment import (
    handle_configure_environment,
    handle_remove_environment,
)

@pytest.mark.asyncio
async def test_handle_configure_environment(hass: HomeAssistant):
    """Test the handle_configure_environment service."""
    mock_coordinator = MagicMock()
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.async_refresh = AsyncMock()

    call_data = {
        "growspace_id": "gs1",
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.hum",
        "vpd_sensor": "sensor.vpd",
        "co2_sensor": "sensor.co2",
        "circulation_fan": "switch.fan",
        "stress_threshold": 0.8,
        "mold_threshold": 0.9,
    }
    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = call_data

    with patch("custom_components.growspace_manager.services.environment.create_notification") as mock_create_notification:
        await handle_configure_environment(hass, mock_coordinator, MagicMock(), mock_call)

        assert mock_growspace.environment_config == {
            "temperature_sensor": "sensor.temp",
            "humidity_sensor": "sensor.hum",
            "vpd_sensor": "sensor.vpd",
            "co2_sensor": "sensor.co2",
            "circulation_fan": "switch.fan",
            "stress_threshold": 0.8,
            "mold_threshold": 0.9,
        }
        mock_coordinator.async_save.assert_called_once()
        mock_coordinator.async_refresh.assert_called_once()
        mock_create_notification.assert_called_once()

@pytest.mark.asyncio
async def test_handle_remove_environment(hass: HomeAssistant):
    """Test the handle_remove_environment service."""
    mock_coordinator = MagicMock()
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.async_refresh = AsyncMock()

    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {"growspace_id": "gs1"}

    with patch("custom_components.growspace_manager.services.environment.create_notification") as mock_create_notification:
        await handle_remove_environment(hass, mock_coordinator, MagicMock(), mock_call)

        assert mock_growspace.environment_config is None
        mock_coordinator.async_save.assert_called_once()
        mock_coordinator.async_refresh.assert_called_once()
        mock_create_notification.assert_called_once()

@pytest.mark.asyncio
async def test_environment_service_growspace_not_found(hass: HomeAssistant):
    """Test environment services with a growspace that is not found."""
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {}

    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {"growspace_id": "gs1"}

    with patch("custom_components.growspace_manager.services.environment.create_notification") as mock_create_notification:
        await handle_configure_environment(hass, mock_coordinator, MagicMock(), mock_call)
        mock_create_notification.assert_called_once_with(
            hass,
            "Growspace 'gs1' not found",
            title="Growspace Manager - Environment Config Error",
        )

        await handle_remove_environment(hass, mock_coordinator, MagicMock(), mock_call)
        mock_create_notification.assert_called_with(
            hass,
            "Growspace 'gs1' not found",
            title="Growspace Manager - Environment Config Error",
        )
