import pytest
from unittest.mock import AsyncMock
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator


@pytest.mark.asyncio
async def test_add_and_remove_growspace():
    coordinator = GrowspaceCoordinator(hass=None)

    # Add
    growspace_id = await coordinator.async_add_growspace("TestSpace", 2, 3)
    assert growspace_id in coordinator.growspaces
    assert coordinator.growspaces[growspace_id]["name"] == "TestSpace"

    # Remove
    await coordinator.async_remove_growspace(growspace_id)
    assert growspace_id not in coordinator.growspaces


@pytest.mark.asyncio
async def test_add_and_remove_plant():
    coordinator = GrowspaceCoordinator(hass=None)
    growspace_id = await coordinator.async_add_growspace("TestSpace", 2, 3)

    # Add plant
    plant_id = await coordinator.async_add_plant(
        growspace_id, "OG Kush", "fem", "clone", (1, 1)
    )
    assert plant_id in coordinator.plants

    # Remove plant
    await coordinator.async_remove_plant(plant_id)
    assert plant_id not in coordinator.plants
