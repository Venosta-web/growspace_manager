"""Tests for the Growspace services."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.services.growspace import (
    handle_add_growspace,
    handle_remove_growspace,
)
from custom_components.growspace_manager.const import DOMAIN


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.async_add_growspace = AsyncMock(return_value="gs1")
    coordinator.async_remove_growspace = AsyncMock()
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Fixture for a mock StrainLibrary instance."""
    return MagicMock(spec=StrainLibrary)


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    return MagicMock(spec=ServiceCall)


@pytest.mark.asyncio
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace(
    mock_async_get,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_add_growspace service."""
    mock_call.data = {
        "name": "Test GS",
        "rows": 2,
        "plants_per_row": 3,
        "notification_target": "mobile_app_test",
    }
    mock_device = MagicMock()
    mock_device.name = "mobile_app_test"
    mock_device.config_entries = {"mobile_app_test"}
    mock_async_get.return_value.devices = {"device_id": mock_device}

    await handle_add_growspace(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_add_growspace.assert_awaited_once_with(
        name="Test GS", rows=2, plants_per_row=3, notification_target="mobile_app_test"
    )
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_growspace_added", {"growspace_id": "gs1", "name": "Test GS"}
    )


@pytest.mark.asyncio
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace_no_mobile_app_notification(
    mock_async_get,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_add_growspace when notification_target is not a mobile app."""
    mock_call.data = {
        "name": "Test GS",
        "rows": 2,
        "plants_per_row": 3,
        "notification_target": "non_existent_mobile_app",
    }
    mock_async_get.return_value.devices = {}  # No mobile devices registered

    await handle_add_growspace(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_add_growspace.assert_awaited_once_with(
        name="Test GS", rows=2, plants_per_row=3, notification_target=None
    )
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_growspace_added", {"growspace_id": "gs1", "name": "Test GS"}
    )


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.growspace.create_notification"
)
@patch("homeassistant.helpers.device_registry.async_get")
async def test_handle_add_growspace_exception(
    mock_async_get,
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_add_growspace with an exception."""
    mock_call.data = {"name": "Test GS", "rows": 2, "plants_per_row": 3}
    mock_coordinator.async_add_growspace.side_effect = Exception("Add failed")
    mock_async_get.return_value.devices = {}

    with pytest.raises(Exception, match="Add failed"):
        await handle_add_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()


@pytest.mark.asyncio
async def test_handle_remove_growspace(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_remove_growspace service."""
    mock_call.data = {"growspace_id": "gs1"}

    await handle_remove_growspace(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_remove_growspace.assert_awaited_once_with("gs1")
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_growspace_removed", {"growspace_id": "gs1"}
    )


@pytest.mark.asyncio
@patch(
    "custom_components.growspace_manager.services.growspace.create_notification"
)
async def test_handle_remove_growspace_exception(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_remove_growspace with an exception."""
    mock_call.data = {"growspace_id": "gs1"}
    mock_coordinator.async_remove_growspace.side_effect = Exception("Remove failed")

    with pytest.raises(Exception, match="Remove failed"):
        await handle_remove_growspace(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()
