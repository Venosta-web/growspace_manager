"""Tests for the Debug services."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.strain_library import StrainLibrary
from custom_components.growspace_manager.services.debug import (
    handle_test_notification,
    debug_cleanup_legacy,
    debug_list_growspaces,
    debug_reset_special_growspaces,
    debug_consolidate_duplicate_special,
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
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.data = {"growspaces": {}, "plants": {}}
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Fixture for a mock StrainLibrary instance."""
    return MagicMock(spec=StrainLibrary)


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    call = MagicMock(spec=ServiceCall)
    call.data = {}
    return call


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.debug.create_notification")
async def test_handle_test_notification(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_test_notification service."""
    mock_call.data = {"message": "Test Message"}

    await handle_test_notification(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_create_notification.assert_called_once_with(
        mock_hass, "Test Message", title="Growspace Manager Test"
    )


@pytest.mark.asyncio
async def test_debug_cleanup_legacy(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service."""
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
        "cure_overview_1": {},
        "regular_gs": {},
    }
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=["dry", "cure"])
    mock_coordinator.get_growspace_plants.return_value = [MagicMock(plant_id="p1")]
    mock_coordinator.plants = {"p1": {"growspace_id": "dry_overview_1"}}
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_cleanup_legacy(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert "dry_overview_1" not in mock_coordinator.growspaces
    assert "cure_overview_1" not in mock_coordinator.growspaces
    mock_coordinator.async_save.assert_awaited_once()

@pytest.mark.asyncio
async def test_debug_cleanup_legacy_dry_only(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service with dry_only flag."""
    mock_call.data = {"dry_only": True}
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
        "cure_overview_1": {},
        "regular_gs": {},
    }
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=["dry"])
    mock_coordinator.get_growspace_plants.return_value = [MagicMock(plant_id="p1")]
    mock_coordinator.plants = {"p1": {"growspace_id": "dry_overview_1"}}
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_cleanup_legacy(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert "dry_overview_1" not in mock_coordinator.growspaces
    assert "cure_overview_1" in mock_coordinator.growspaces
    mock_coordinator.async_save.assert_awaited_once()

@pytest.mark.asyncio
async def test_debug_cleanup_legacy_cure_only(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service with cure_only flag."""
    mock_call.data = {"cure_only": True}
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
        "cure_overview_1": {},
        "regular_gs": {},
    }
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=["cure"])
    mock_coordinator.get_growspace_plants.return_value = [MagicMock(plant_id="p1")]
    mock_coordinator.plants = {"p1": {"growspace_id": "cure_overview_1"}}
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_cleanup_legacy(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert "dry_overview_1" in mock_coordinator.growspaces
    assert "cure_overview_1" not in mock_coordinator.growspaces
    mock_coordinator.async_save.assert_awaited_once()

@pytest.mark.asyncio
async def test_debug_list_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_list_growspaces service."""
    mock_coordinator.growspaces = {"gs1": {"name": "Test GS"}}
    plant = MagicMock()
    plant.strain = "OG Kush"
    plant.plant_id = "p1"
    plant.row = 1
    plant.col = 1
    mock_coordinator.get_growspace_plants.return_value = [plant]

    with patch("logging.Logger.debug") as mock_debug:
        await debug_list_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_debug.call_count > 0


@pytest.mark.asyncio
async def test_debug_reset_special_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_reset_special_growspaces service."""
    mock_coordinator.growspaces = {"dry": {}, "cure": {}}
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=["dry", "cure"])

    await debug_reset_special_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_save.assert_awaited_once()

@pytest.mark.asyncio
async def test_debug_reset_special_growspaces_preserve_plants(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_reset_special_growspaces service with preserve_plants flag."""
    mock_call.data = {"preserve_plants": True}
    mock_coordinator.growspaces = {"dry": {}, "cure": {}}
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=["dry", "cure"])
    mock_coordinator.get_growspace_plants.return_value = [MagicMock(plant_id="p1")]
    mock_coordinator.plants = {"p1": {"growspace_id": "dry"}}
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_reset_special_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_save.assert_awaited_once()

@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_consolidate_duplicate_special service."""
    mock_coordinator.growspaces = {
        "dry": {"name": "Dry"},
        "dry_1": {"name": "Dry"},
        "cure": {"name": "Cure"},
    }
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=["dry", "cure"])

    with patch(
        "custom_components.growspace_manager.services.debug._consolidate_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_consolidate:
        await debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_consolidate.call_count > 0
        mock_coordinator.async_save.assert_awaited_once()

@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_no_duplicates(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_consolidate_duplicate_special service with no duplicates."""
    mock_coordinator.growspaces = {
        "dry": {"name": "Dry"},
        "cure": {"name": "Cure"},
    }

    with patch(
        "custom_components.growspace_manager.services.debug._consolidate_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_consolidate:
        await debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_consolidate.call_count == 0
        mock_coordinator.async_save.assert_awaited_once()

@pytest.mark.asyncio
async def test_debug_cleanup_legacy_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service with an exception."""
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
    }
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=Exception("Test Exception"))

    with pytest.raises(Exception):
        await debug_cleanup_legacy(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

@pytest.mark.asyncio
async def test_debug_reset_special_growspaces_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_reset_special_growspaces service with an exception."""
    mock_coordinator.growspaces = {"dry": {}}
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=Exception("Test Exception"))

    with pytest.raises(Exception):
        await debug_reset_special_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )

@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_consolidate_duplicate_special service with an exception."""
    mock_coordinator.growspaces = {
        "dry_1": {"name": "Dry"},
        "dry_2": {"name": "Dry"},
    }
    mock_coordinator.ensure_special_growspace = MagicMock(side_effect=Exception("Test Exception"))

    with pytest.raises(Exception):
        await debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
