"""Focused tests to increase coverage for GrowspaceCoordinator."""

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest
from tests.common import async_capture_events
from tests.core.test_coordinator import create_test_coordinator

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    Growspace,
    GrowspaceType,
    NutrientInventory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr


@pytest.fixture
async def coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Fixture for GrowspaceCoordinator."""
    coordinator = create_test_coordinator(hass)
    coordinator.async_set_updated_data = MagicMock()
    coordinator.async_commit = AsyncMock()
    yield coordinator
    # Ensure coordinator is shut down to avoid event loop issues
    await coordinator.async_shutdown()


@pytest.mark.asyncio
async def test_coordinator_getters_setters(coordinator: GrowspaceCoordinator) -> None:
    """Test various property getters and setters in GrowspaceCoordinator."""
    # Line 167: dehumidifier_coordinators
    coordinator.subsystem_manager.dehumidifier_coordinators = {"test": MagicMock()}
    assert coordinator.dehumidifier_coordinators == {
        "test": coordinator.subsystem_manager.dehumidifier_coordinators["test"]
    }

    # notifications_sent/enabled are now read-only properties from notification_state
    coordinator.notification_state.sent = {"gs1": {"stage": {"1": True}}}
    assert coordinator.notifications_sent == {"gs1": {"stage": {"1": True}}}

    coordinator.notification_state.enabled = {"gs1": True}
    assert coordinator.notifications_enabled == {"gs1": True}

    # Line 234: growspace_service getter
    assert coordinator.growspace_service == coordinator.growspace_manager

    # Line 239: plant_service getter
    assert coordinator.plant_service == coordinator.plant_manager


@pytest.mark.asyncio
async def test_nutrient_inventory_loaded(coordinator: GrowspaceCoordinator) -> None:
    """Test on_nutrient_inventory_loaded."""
    # Line 352
    mock_inventory = MagicMock(spec=NutrientInventory)
    coordinator.nutrient_manager.load_data = MagicMock()
    coordinator.on_nutrient_inventory_loaded(mock_inventory)
    coordinator.nutrient_manager.load_data.assert_called_once()


@pytest.mark.asyncio
async def test_date_helper_delegation(coordinator: GrowspaceCoordinator) -> None:
    """Test _to_date delegation."""
    # Line 420
    test_date = date(2025, 1, 1)
    assert coordinator._to_date(test_date) == test_date
    assert coordinator._to_date("2025-01-01") == test_date


@pytest.mark.asyncio
async def test_update_special_growspace_name(coordinator: GrowspaceCoordinator) -> None:
    """Test _update_special_growspace_name delegation."""
    # Line 447
    coordinator._special_growspace_manager.update_special_growspace_name = MagicMock()
    coordinator._update_special_growspace_name("gs1", "New Name")
    coordinator._special_growspace_manager.update_special_growspace_name.assert_called_once_with(
        "gs1", "New Name"
    )


@pytest.mark.asyncio
async def test_async_add_growspace_coverage(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """Test async_add_growspace and associated device registration."""
    # Lines 515-535
    mock_gs = MagicMock(spec=Growspace)
    mock_gs.id = "new_gs_id"
    mock_gs.name = "New GS"
    mock_gs.growspace_type = GrowspaceType.FLOWER

    coordinator.growspace_manager.add_growspace = AsyncMock(return_value=mock_gs)
    coordinator.subsystem_manager.async_setup_growspace_sub_coordinators = AsyncMock()

    result = await coordinator.services.add_growspace(name="New GS")

    assert result == mock_gs
    coordinator.growspace_manager.add_growspace.assert_called_once()

    # Verify device registration
    device_registry = dr.async_get(hass)
    device = device_registry.async_get_device(identifiers={(DOMAIN, "new_gs_id")})
    assert device is not None
    assert device.name == "New GS"

    # Verify sub-coordinators setup
    coordinator.subsystem_manager.async_setup_growspace_sub_coordinators.assert_called_once_with(
        "new_gs_id", mock_gs
    )


@pytest.mark.asyncio
async def test_async_update_growspace_delegation(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test services.update_growspace delegation."""
    gs = Growspace(id="gs1", name="Old Name")
    coordinator.data_repository.add_growspace(gs)
    coordinator.growspace_manager.update_growspace = AsyncMock(return_value=gs)

    result = await coordinator.services.update_growspace("gs1", name="New Name")

    coordinator.growspace_manager.update_growspace.assert_called_once_with(
        "gs1", name="New Name"
    )
    assert result is gs


@pytest.mark.asyncio
async def test_strain_library_coverage(coordinator: GrowspaceCoordinator) -> None:
    """Test strain library related methods."""
    # Lines 1448-1450, 1458
    coordinator.strain_library = MagicMock()
    coordinator.strain_library.get_all.return_value = {"Strain A": {}, "Strain B": {}}

    assert coordinator.services.get_strain_options() == ["Strain A", "Strain B"]
    assert coordinator.services.export_strain_library() == ["Strain A", "Strain B"]

    # Line 1466-1468
    coordinator.strain_library.clear = AsyncMock(return_value=2)
    assert await coordinator.services.clear_strains() == 2

    # Test without strain library
    coordinator.strain_library = None
    assert coordinator.services.get_strain_options() == []
    assert await coordinator.services.clear_strains() == 0


@pytest.mark.asyncio
async def test_fire_event_coverage(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator
) -> None:
    """Test fire_event."""
    # Lines 1578-1579
    events = async_capture_events(hass, "growspace_manager_updated")

    coordinator.fire_event("test_event", {"foo": "bar"})
    await hass.async_block_till_done()

    assert len(events) == 1
    assert events[0].data == {"event_type": "test_event", "data": {"foo": "bar"}}


@pytest.mark.asyncio
async def test_async_log_training_event_empty_plants_with_gs(
    coordinator: GrowspaceCoordinator,
) -> None:
    """Test async_log_training_event with empty plants but provided growspace_id (Line 1184)."""
    # Line 1184
    gs_id = "test_gs"
    # Use real Growspace object to avoid asdict() errors
    gs = Growspace(id=gs_id, name="Test GS")
    coordinator.data_repository.growspaces = {gs_id: gs}

    # Mock add_event at the event bus level since it's now called through TrainingService
    original_add_event = coordinator.add_event
    coordinator.add_event = MagicMock()
    # Also need to mock it on the service
    coordinator._training_service.add_event = coordinator.add_event

    await coordinator.services.log_training_event(gs_id, "topping")

    # Verify add_event was called with the gs_id
    coordinator.add_event.assert_called_once()
    event = coordinator.add_event.call_args[0][1]
    assert event.growspace_id == gs_id

    # Restore original
    coordinator.add_event = original_add_event
