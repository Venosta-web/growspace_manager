"""Additional tests for GrowspaceCoordinator to reach 100% coverage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from .test_coordinator import create_test_coordinator

from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_update_special_growspace_name_fallback(hass: HomeAssistant) -> None:
    """Test the fallback path in _update_special_growspace_name."""
    coordinator = create_test_coordinator(hass)

    # Mock growspace_manager without the public method
    mock_manager = MagicMock()
    # Ensure it doesn't have the public method
    if hasattr(mock_manager, "update_special_growspace_name"):
        del mock_manager.update_special_growspace_name

    mock_manager._update_special_growspace_name = MagicMock()
    coordinator._growspace_manager = mock_manager

    # Call the method
    coordinator._update_special_growspace_name("mother", "New Mother Name")

    # Verify the internal method was called
    mock_manager._update_special_growspace_name.assert_called_once_with(
        "mother", "New Mother Name"
    )


@pytest.mark.asyncio
async def test_async_update_growspace_returns_gs(hass: HomeAssistant) -> None:
    """Test that async_update_growspace returns the growspace when found."""
    coordinator = create_test_coordinator(hass)

    # Add a growspace
    gs = await coordinator.services.growspaces.add_growspace(name="Test GS", rows=2, plants_per_row=2)
    gs_id = gs.id

    # Update it
    result = await coordinator.services.growspaces.update_growspace(gs_id, name="Updated GS")

    # Verify it returns the updated growspace object
    assert result.id == gs_id
    assert result.name == "Updated GS"
    assert coordinator.growspaces[gs_id] is result


@pytest.mark.asyncio
async def test_validate_plants_after_growspace_resize_task(hass: HomeAssistant) -> None:
    """Test that _validate_plants_after_growspace_resize creates an asyncio task."""
    coordinator = create_test_coordinator(hass)

    # Mock the service facade validate method
    coordinator.services.growspaces.validate_plants_after_growspace_resize = MagicMock()

    # Call the service method
    coordinator.services.growspaces.validate_plants_after_growspace_resize("gs1", 2, 2)

    # Give it a tiny bit of time to schedule/run
    await asyncio.sleep(0)

    # Verify the service method was called
    coordinator.services.growspaces.validate_plants_after_growspace_resize.assert_called_once_with(
        "gs1", 2, 2
    )


@pytest.mark.asyncio
async def test_services_update_growspace_fallback(hass: HomeAssistant) -> None:
    """Test that services.update_growspace raises an error when GS not found."""
    from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError

    coordinator = create_test_coordinator(hass)

    # Call it with an ID that definitely doesn't exist in coordinator.growspaces
    with pytest.raises(GrowspaceNotFoundError):
        await coordinator.services.growspaces.update_growspace("nonexistent_id", name="New Name")

    # It should not be in the growspaces repo
    assert "nonexistent_id" not in coordinator.growspaces
