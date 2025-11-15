"""Tests for the Growspace Manager coordinator."""
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant


@pytest.fixture
def mock_store_with_data():
    """Fixture for a mock store with some initial data."""
    store = MagicMock()
    store.async_load = AsyncMock(
        return_value={
            "growspaces": {
                "test_growspace": {
                    "id": "test_growspace",
                    "name": "Test Growspace",
                    "rows": 2,
                    "plants_per_row": 2,
                }
            },
            "plants": {
                "test_plant": {
                    "plant_id": "test_plant",
                    "growspace_id": "test_growspace",
                    "strain": "Test Strain",
                    "row": 1,
                    "col": 1,
                }
            },
        }
    )
    store.async_save = AsyncMock()
    return store


async def test_coordinator_load_data(
    hass: HomeAssistant, mock_store_with_data: MagicMock
) -> None:
    """Test that the coordinator correctly loads data from storage."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = mock_store_with_data
    await coordinator.async_load()

    assert len(coordinator.growspaces) == 1
    assert "test_growspace" in coordinator.growspaces
    assert coordinator.growspaces["test_growspace"].name == "Test Growspace"

    assert len(coordinator.plants) == 1
    assert "test_plant" in coordinator.plants
    assert coordinator.plants["test_plant"].strain == "Test Strain"


async def test_coordinator_add_growspace(hass: HomeAssistant) -> None:
    """Test adding a growspace to the coordinator."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = MagicMock()
    coordinator.store.async_save = AsyncMock()

    growspace = await coordinator.async_add_growspace(
        name="New Growspace", rows=3, plants_per_row=4
    )

    assert growspace.id in coordinator.growspaces
    assert coordinator.growspaces[growspace.id].name == "New Growspace"
    assert coordinator.growspaces[growspace.id].rows == 3
    assert coordinator.growspaces[growspace.id].plants_per_row == 4
    coordinator.store.async_save.assert_called_once()


async def test_coordinator_remove_growspace(hass: HomeAssistant) -> None:
    """Test removing a growspace from the coordinator."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = MagicMock()
    coordinator.store.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()

    growspace = await coordinator.async_add_growspace(name="Growspace to Remove")
    growspace_id = growspace.id

    await coordinator.async_remove_growspace(growspace_id)

    assert growspace_id not in coordinator.growspaces
    coordinator.store.async_save.assert_called()


async def test_coordinator_update_growspace(hass: HomeAssistant) -> None:
    """Test updating a growspace in the coordinator."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = MagicMock()
    coordinator.store.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()

    growspace = await coordinator.async_add_growspace(name="Original Name")
    growspace_id = growspace.id

    await coordinator.async_update_growspace(
        growspace_id, name="Updated Name", rows=5
    )

    assert coordinator.growspaces[growspace_id].name == "Updated Name"
    assert coordinator.growspaces[growspace_id].rows == 5
    coordinator.store.async_save.assert_called_once()
    coordinator.async_set_updated_data.assert_called_once()


async def test_coordinator_add_plant(hass: HomeAssistant) -> None:
    """Test adding a plant to the coordinator."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = MagicMock()
    coordinator.store.async_save = AsyncMock()

    growspace = await coordinator.async_add_growspace(name="Test Growspace")

    plant = await coordinator.async_add_plant(
        growspace_id=growspace.id, strain="Test Plant", row=1, col=1
    )

    assert plant.plant_id in coordinator.plants
    assert coordinator.plants[plant.plant_id].strain == "Test Plant"
    coordinator.store.async_save.assert_called()


async def test_coordinator_remove_plant(hass: HomeAssistant) -> None:
    """Test removing a plant from the coordinator."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = MagicMock()
    coordinator.store.async_save = AsyncMock()

    growspace = await coordinator.async_add_growspace(name="Test Growspace")
    plant = await coordinator.async_add_plant(
        growspace_id=growspace.id, strain="Test Plant"
    )
    plant_id = plant.plant_id

    await coordinator.async_remove_plant(plant_id)

    assert plant_id not in coordinator.plants
    coordinator.store.async_save.assert_called()


async def test_coordinator_update_plant(hass: HomeAssistant) -> None:
    """Test updating a plant in the coordinator."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = MagicMock()
    coordinator.store.async_save = AsyncMock()

    growspace = await coordinator.async_add_growspace(name="Test Growspace")
    plant = await coordinator.async_add_plant(
        growspace_id=growspace.id, strain="Original Strain"
    )
    plant_id = plant.plant_id

    await coordinator.async_update_plant(plant_id, strain="Updated Strain", row=2)

    assert coordinator.plants[plant_id].strain == "Updated Strain"
    assert coordinator.plants[plant_id].row == 2
    coordinator.store.async_save.assert_called()


async def test_ensure_special_growspaces(hass: HomeAssistant) -> None:
    """Test that special growspaces are created if they don't exist."""
    coordinator = GrowspaceCoordinator(hass)
    coordinator.store = MagicMock()
    coordinator.store.async_save = AsyncMock()

    coordinator._ensure_special_growspace("dry", "Dry Zone")
    assert "dry" in coordinator.growspaces
    assert coordinator.growspaces["dry"].name == "Dry Zone"

    coordinator._ensure_special_growspace("cure", "Cure Zone")
    assert "cure" in coordinator.growspaces
    assert coordinator.growspaces["cure"].name == "Cure Zone"

    coordinator.store.async_save.assert_called()
