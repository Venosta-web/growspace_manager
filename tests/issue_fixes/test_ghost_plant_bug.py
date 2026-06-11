from unittest.mock import AsyncMock, patch

import pytest

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN


@pytest.mark.asyncio
async def test_ghost_plant_bug(hass: HomeAssistant) -> None:
    """Test that deleted plants do not reappear after refresh."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})

    # Mock the async_refresh method properly to avoid "Cannot assign to a method" error
    with patch.object(coordinator, "async_refresh", new_callable=AsyncMock):
        # Setup initial state
        gs = await coordinator._growspace_manager.add_growspace("Test Growspace")
        plant = await coordinator._plant_manager.add_plant(gs.id, "Test Plant")

        assert plant.plant_id in coordinator.plants

        # Remove the plant
        await coordinator.services.plants.remove_plant(plant.plant_id)
        assert plant.plant_id not in coordinator.plants

        # Refresh the coordinator
        await coordinator.services.request_refresh()

        # Assert plant is still gone
        assert plant.plant_id not in coordinator.plants
