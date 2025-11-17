"""Tests for the Strain Library services."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.services.strain_library import (
    handle_get_strain_library,
    handle_export_strain_library,
    handle_import_strain_library,
    handle_clear_strain_library,
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
    coordinator.async_save = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Fixture for a mock StrainLibrary instance."""
    strain_library = MagicMock(spec=StrainLibrary)
    strain_library.load = AsyncMock()
    strain_library.strains = {"Strain A", "Strain B"}
    strain_library.import_strains = AsyncMock(return_value=2)
    strain_library.clear_strains = AsyncMock(return_value=2)
    return strain_library


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    return MagicMock(spec=ServiceCall)


@pytest.mark.asyncio
async def test_handle_get_strain_library(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_get_strain_library service."""
    strains = await handle_get_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.load.assert_awaited_once()
    assert set(strains) == {"Strain A", "Strain B"}
    fired_event = mock_hass.bus.async_fire.call_args[0][0]
    fired_data = mock_hass.bus.async_fire.call_args[0][1]
    assert fired_event == f"{DOMAIN}_strain_library_fetched"
    assert set(fired_data["strains"]) == {"Strain A", "Strain B"}


@pytest.mark.asyncio
async def test_handle_export_strain_library(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_export_strain_library service."""
    await handle_export_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_save.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()
    fired_event = mock_hass.bus.async_fire.call_args[0][0]
    fired_data = mock_hass.bus.async_fire.call_args[0][1]
    assert fired_event == f"{DOMAIN}_strain_library_exported"
    assert set(fired_data["strains"]) == {"Strain A", "Strain B"}


@pytest.mark.asyncio
async def test_handle_import_strain_library(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_import_strain_library service."""
    mock_call.data = {"strains": ["Strain C", "Strain D"], "replace": True}

    await handle_import_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.import_strains.assert_awaited_once_with(
        strains=["Strain C", "Strain D"], replace=True
    )
    mock_coordinator.async_save.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_strain_library_imported", {"added_count": 2, "replace": True}
    )


@pytest.mark.asyncio
async def test_handle_import_strain_library_no_strains(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_import_strain_library with no strains."""
    mock_call.data = {"strains": [], "replace": False}

    await handle_import_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.import_strains.assert_not_called()


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.strain_library.create_notification")
async def test_handle_import_strain_library_exception(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_import_strain_library with an exception."""
    mock_call.data = {"strains": ["Strain C"], "replace": False}
    mock_strain_library.import_strains.side_effect = Exception("Import failed")

    with pytest.raises(Exception, match="Import failed"):
        await handle_import_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()


@pytest.mark.asyncio
async def test_handle_clear_strain_library(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test handle_clear_strain_library service."""
    await handle_clear_strain_library(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_strain_library.clear_strains.assert_awaited_once()
    mock_coordinator.async_save.assert_awaited_once()
    mock_coordinator.async_request_refresh.assert_awaited_once()
    mock_hass.bus.async_fire.assert_called_once_with(
        f"{DOMAIN}_strain_library_cleared", {"cleared_count": 2}
    )


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.strain_library.create_notification")
async def test_handle_clear_strain_library_attribute_error(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_clear_strain_library with AttributeError."""
    mock_strain_library.clear_strains.side_effect = AttributeError("Method not found")

    with pytest.raises(AttributeError, match="Method not found"):
        await handle_clear_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.strain_library.create_notification")
async def test_handle_clear_strain_library_exception(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_clear_strain_library with a generic exception."""
    mock_strain_library.clear_strains.side_effect = Exception("Clear failed")

    with pytest.raises(Exception, match="Clear failed"):
        await handle_clear_strain_library(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

    mock_create_notification.assert_called_once()
