"""Tests for the debug services."""
import pytest
from unittest.mock import patch, MagicMock, call, AsyncMock
from homeassistant.core import HomeAssistant, ServiceCall
from custom_components.growspace_manager.services.debug import (
    handle_test_notification,
    debug_list_growspaces,
    debug_cleanup_legacy,
)

@pytest.mark.asyncio
async def test_handle_test_notification_custom_message(hass: HomeAssistant):
    """Test the handle_test_notification service with a custom message."""
    with patch("custom_components.growspace_manager.services.debug.create_notification") as mock_create_notification:
        mock_call = MagicMock(spec=ServiceCall)
        mock_call.data = {"message": "Test Message"}
        await handle_test_notification(hass, MagicMock(), MagicMock(), mock_call)
        mock_create_notification.assert_called_once_with(hass, "Test Message", title="Growspace Manager Test")

@pytest.mark.asyncio
async def test_handle_test_notification_default_message(hass: HomeAssistant):
    """Test the handle_test_notification service with the default message."""
    with patch("custom_components.growspace_manager.services.debug.create_notification") as mock_create_notification:
        mock_call = MagicMock(spec=ServiceCall)
        mock_call.data = {}
        await handle_test_notification(hass, MagicMock(), MagicMock(), mock_call)
        mock_create_notification.assert_called_once_with(hass, "Test notification from Growspace Manager", title="Growspace Manager Test")

@pytest.mark.asyncio
async def test_debug_list_growspaces(hass: HomeAssistant):
    """Test the debug_list_growspaces service."""
    # Setup mock coordinator
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {
        "gs1": {"name": "Veg Tent", "rows": 2, "plants_per_row": 2},
        "gs2": {"name": "Flower Room"},
    }

    # Setup mock plants
    plant1 = MagicMock()
    plant1.strain = "OG Kush"
    plant1.plant_id = "p1"
    plant1.row = 0
    plant1.col = 0
    plant2 = MagicMock()
    plant2.strain = "Sour Diesel"
    plant2.plant_id = "p2"
    plant2.row = 1
    plant2.col = 1

    # Configure mock get_growspace_plants to return plants for gs1 only
    mock_coordinator.get_growspace_plants.side_effect = lambda gs_id: [plant1, plant2] if gs_id == "gs1" else []

    with patch("custom_components.growspace_manager.services.debug._LOGGER") as mock_logger:
        await debug_list_growspaces(hass, mock_coordinator, MagicMock(), MagicMock())

        # Define expected log calls
        expected_calls = [
            call.debug("=== Current Growspaces ==="),
            call.debug(
                "%s -> name='%s', plants=%d, rows=%s, cols=%s",
                "gs1", "Veg Tent", 2, 2, 2
            ),
            call.debug(
                "%s -> name='%s', plants=%d, rows=%s, cols=%s",
                "gs2", "Flower Room", 0, None, None
            ),
            call.debug("=== Plants by Growspace ==="),
            call.debug("%s has %d plants:", "gs1", 2),
            call.debug("  - %s (%s) at (%s,%s)", "OG Kush", "p1", 0, 0),
            call.debug("  - %s (%s) at (%s,%s)", "Sour Diesel", "p2", 1, 1),
            call.debug("%s has 0 plants.", "gs2"),
        ]
        # Assert that the logger was called as expected
        mock_logger.assert_has_calls(expected_calls, any_order=False)


@pytest.mark.asyncio
async def test_debug_list_growspaces_no_growspaces(hass: HomeAssistant):
    """Test the debug_list_growspaces service when no growspaces exist."""
    # Setup mock coordinator with no growspaces
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {}

    with patch("custom_components.growspace_manager.services.debug._LOGGER") as mock_logger:
        await debug_list_growspaces(hass, mock_coordinator, MagicMock(), MagicMock())

        # Define expected log calls
        expected_calls = [
            call.debug("=== Current Growspaces ==="),
            call.debug("No growspaces found."),
        ]
        # Assert that the logger was called as expected
        mock_logger.assert_has_calls(expected_calls, any_order=False)

@pytest.mark.asyncio
async def test_debug_cleanup_legacy_dry_growspace(hass: HomeAssistant):
    """Test debug_cleanup_legacy for dry growspaces."""
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {"dry_overview_1": {"name": "Legacy Dry"}}
    mock_coordinator.plants = {"plant_1": {"growspace_id": "dry_overview_1"}}
    mock_coordinator.data = {"growspaces": mock_coordinator.growspaces, "plants": mock_coordinator.plants}
    mock_coordinator.async_save = AsyncMock()

    plant1 = MagicMock()
    plant1.plant_id = "plant_1"
    plant1.strain = "Test Strain"
    mock_coordinator.get_growspace_plants.return_value = [plant1]
    mock_coordinator.ensure_special_growspace.return_value = "dry"
    mock_coordinator.find_first_available_position.return_value = (0, 0)

    call = MagicMock(spec=ServiceCall)
    call.data = {}

    await debug_cleanup_legacy(hass, mock_coordinator, MagicMock(), call)

    assert "dry_overview_1" not in mock_coordinator.growspaces
    assert mock_coordinator.plants["plant_1"]["growspace_id"] == "dry"
    mock_coordinator.async_save.assert_called_once()

@pytest.mark.asyncio
async def test_debug_cleanup_legacy_cure_growspace(hass: HomeAssistant):
    """Test debug_cleanup_legacy for cure growspaces."""
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {"cure_overview_1": {"name": "Legacy Cure"}}
    mock_coordinator.plants = {"plant_1": {"growspace_id": "cure_overview_1"}}
    mock_coordinator.data = {"growspaces": mock_coordinator.growspaces, "plants": mock_coordinator.plants}
    mock_coordinator.async_save = AsyncMock()

    plant1 = MagicMock()
    plant1.plant_id = "plant_1"
    plant1.strain = "Test Strain"
    mock_coordinator.get_growspace_plants.return_value = [plant1]
    mock_coordinator.ensure_special_growspace.return_value = "cure"
    mock_coordinator.find_first_available_position.return_value = (0, 0)

    call = MagicMock(spec=ServiceCall)
    call.data = {}

    await debug_cleanup_legacy(hass, mock_coordinator, MagicMock(), call)

    assert "cure_overview_1" not in mock_coordinator.growspaces
    assert mock_coordinator.plants["plant_1"]["growspace_id"] == "cure"
    mock_coordinator.async_save.assert_called_once()

@pytest.mark.asyncio
async def test_debug_cleanup_legacy_dry_only(hass: HomeAssistant):
    """Test debug_cleanup_legacy with dry_only=True."""
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {
        "dry_overview_1": {"name": "Legacy Dry"},
        "cure_overview_1": {"name": "Legacy Cure"},
    }
    mock_coordinator.plants = {
        "plant_1": {"growspace_id": "dry_overview_1"},
        "plant_2": {"growspace_id": "cure_overview_1"},
    }
    mock_coordinator.data = {"growspaces": mock_coordinator.growspaces, "plants": mock_coordinator.plants}
    mock_coordinator.async_save = AsyncMock()

    plant1 = MagicMock()
    plant1.plant_id = "plant_1"
    plant1.strain = "Test Strain"

    def get_plants(gs_id):
        if gs_id == "dry_overview_1":
            return [plant1]
        return []

    mock_coordinator.get_growspace_plants.side_effect = get_plants
    mock_coordinator.ensure_special_growspace.return_value = "dry"
    mock_coordinator.find_first_available_position.return_value = (0, 0)

    call = MagicMock(spec=ServiceCall)
    call.data = {"dry_only": True}

    await debug_cleanup_legacy(hass, mock_coordinator, MagicMock(), call)

    assert "dry_overview_1" not in mock_coordinator.growspaces
    assert "cure_overview_1" in mock_coordinator.growspaces

@pytest.mark.asyncio
async def test_debug_cleanup_legacy_cure_only(hass: HomeAssistant):
    """Test debug_cleanup_legacy with cure_only=True."""
    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {
        "dry_overview_1": {"name": "Legacy Dry"},
        "cure_overview_1": {"name": "Legacy Cure"},
    }
    mock_coordinator.plants = {
        "plant_1": {"growspace_id": "dry_overview_1"},
        "plant_2": {"growspace_id": "cure_overview_1"},
    }
    mock_coordinator.data = {"growspaces": mock_coordinator.growspaces, "plants": mock_coordinator.plants}
    mock_coordinator.async_save = AsyncMock()

    plant2 = MagicMock()
    plant2.plant_id = "plant_2"
    plant2.strain = "Test Strain 2"

    def get_plants(gs_id):
        if gs_id == "cure_overview_1":
            return [plant2]
        return []

    mock_coordinator.get_growspace_plants.side_effect = get_plants
    mock_coordinator.ensure_special_growspace.return_value = "cure"
    mock_coordinator.find_first_available_position.return_value = (0, 0)

    call = MagicMock(spec=ServiceCall)
    call.data = {"cure_only": True}

    await debug_cleanup_legacy(hass, mock_coordinator, MagicMock(), call)

    assert "dry_overview_1" in mock_coordinator.growspaces
    assert "cure_overview_1" not in mock_coordinator.growspaces
