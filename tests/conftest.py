import pytest
from unittest.mock import AsyncMock, MagicMock
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.const import DOMAIN

MOCK_CONFIG_ENTRY_ID = "test_entry"


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.options = {}
    coordinator.growspaces = {"gs1": MagicMock(name="Growspace 1")}
    coordinator.plants = {}
    coordinator.get_growspace_plants.return_value = []
    coordinator.get_sorted_growspace_options.return_value = [("gs1", "Growspace 1")]
    coordinator.async_add_growspace = AsyncMock()
    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_update_growspace = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_update_plant = AsyncMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator):
    """Fixture for a mock Home Assistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {
        DOMAIN: {
            MOCK_CONFIG_ENTRY_ID: {
                "coordinator": mock_coordinator,
            }
        }
    }
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.bus = MagicMock()
    hass.bus.async_listen = MagicMock()
    return hass
