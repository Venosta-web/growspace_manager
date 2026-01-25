from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant


@pytest.mark.asyncio
async def test_ghost_plant_bug(hass: HomeAssistant) -> None:
    """Test that deleted plants do not reappear after refresh."""
    coordinator = GrowspaceCoordinator(hass, {}, {}, AsyncMock(), AsyncMock())

    # Mock the async_refresh method properly to avoid "Cannot assign to a method" error
    with patch.object(coordinator, "async_refresh", new_callable=AsyncMock):
        # Setup initial state
        gs = await coordinator._growspace_service.add_growspace("Test Growspace")
        plant = await coordinator._plant_service.add_plant(gs.id, "Test Plant")

        assert plant.plant_id in coordinator.plants

        # Remove the plant
        await coordinator.async_remove_plant(plant.plant_id)
        assert plant.plant_id not in coordinator.plants

        # Refresh the coordinator
        await coordinator.async_refresh()

        # Assert plant is still gone
        assert plant.plant_id not in coordinator.plants
