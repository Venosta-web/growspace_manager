"""Tests for the Growspace Manager services."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.growspace_manager.services.growspace import (
    handle_add_growspace,
    handle_remove_growspace,
)
from custom_components.growspace_manager.services.plant import (
    handle_add_plant,
    handle_remove_plant,
    handle_move_plant
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace


@pytest.fixture
def mock_coordinator() -> GrowspaceCoordinator:
    """Fixture for a mock coordinator."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.async_add_growspace = AsyncMock()
    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_move_plant = AsyncMock()
    coordinator.growspaces = {
        "test_growspace": Growspace(id="test_growspace", name="Test Growspace", rows=2, plants_per_row=2)
    }
    return coordinator


@pytest.fixture
def mock_strain_library() -> MagicMock:
    """Fixture for a mock strain library."""
    return MagicMock()


async def test_handle_add_growspace(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator, mock_strain_library: MagicMock
) -> None:
    """Test the handle_add_growspace service."""
    call = ServiceCall(
        "growspace_manager",
        "add_growspace",
        {"name": "New Growspace", "rows": 3, "plants_per_row": 3},
    )
    with patch("homeassistant.helpers.device_registry.async_get", MagicMock()):
        await handle_add_growspace(hass, mock_coordinator, mock_strain_library, call)
    mock_coordinator.async_add_growspace.assert_called_once_with(
        name="New Growspace", rows=3, plants_per_row=3, notification_target=None
    )


async def test_handle_remove_growspace(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator, mock_strain_library: MagicMock
) -> None:
    """Test the handle_remove_growspace service."""
    call = ServiceCall(
        "growspace_manager", "remove_growspace", {"growspace_id": "test_growspace"}
    )
    await handle_remove_growspace(hass, mock_coordinator, mock_strain_library, call)
    mock_coordinator.async_remove_growspace.assert_called_once_with("test_growspace")


async def test_handle_add_plant(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator, mock_strain_library: MagicMock
) -> None:
    """Test the handle_add_plant service."""
    call = ServiceCall(
        "growspace_manager",
        "add_plant",
        {
            "growspace_id": "test_growspace",
            "strain": "Test Strain",
            "row": 1,
            "col": 1,
        },
    )
    mock_coordinator.get_growspace_plants.return_value = []
    await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)
    mock_coordinator.async_add_plant.assert_called_once()


async def test_handle_remove_plant(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator, mock_strain_library: MagicMock
) -> None:
    """Test the handle_remove_plant service."""
    mock_coordinator.plants = {"test_plant": MagicMock()}
    call = ServiceCall(
        "growspace_manager", "remove_plant", {"plant_id": "test_plant"}
    )
    await handle_remove_plant(hass, mock_coordinator, mock_strain_library, call)
    mock_coordinator.async_remove_plant.assert_called_once_with("test_plant")

async def test_handle_move_plant(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator, mock_strain_library: MagicMock
) -> None:
    """Test the handle_move_plant service."""
    mock_coordinator.plants = {"test_plant": MagicMock(growspace_id="test_growspace", row=1, col=1)}
    mock_coordinator.get_growspace_plants.return_value = []
    call = ServiceCall(
        "growspace_manager", "move_plant", {"plant_id": "test_plant", "new_row": 2, "new_col": 2}
    )
    await handle_move_plant(hass, mock_coordinator, mock_strain_library, call)
    mock_coordinator.async_move_plant.assert_called_once_with("test_plant", 2, 2)
