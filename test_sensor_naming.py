
import sys
from unittest.mock import MagicMock, patch

# Mock the necessary Home Assistant modules
MOCK_MODULES = [
    'homeassistant',
    'homeassistant.components.persistent_notification',
    'homeassistant.config_entries',
    'homeassistant.const',
    'homeassistant.core',
    'homeassistant.helpers',
    'homeassistant.helpers.aiohttp_client',
    'homeassistant.helpers.device_registry',
    'homeassistant.helpers.entity_registry',
    'homeassistant.helpers.update_coordinator',
    'homeassistant.helpers.storage',
    'homeassistant.helpers.typing',
    'homeassistant.exceptions',
    'homeassistant.components.sensor',
    'homeassistant.helpers.entity',
    'homeassistant.helpers.entity_platform',
    'dateutil',
    'dateutil.parser',
]

# Create a mock for homeassistant and its submodules
for module in MOCK_MODULES:
    if 'homeassistant' in module:
        sys.modules[module] = MagicMock()

# Now, we can import our components
import asyncio
from unittest.mock import MagicMock, AsyncMock

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.sensor import GrowspaceOverviewSensor
from custom_components.growspace_manager.const import DOMAIN

class CapturingSensorEntity:
    def __init__(self, *args, **kwargs):
        self._attr_name = ""
        self._attr_unique_id = ""
        self._attr_entity_id = ""
        self._attr_device_info = {}
        self._attr_has_entity_name = False

def run_test():
    """Runs the test to check sensor naming."""

    with patch('custom_components.growspace_manager.sensor.SensorEntity', new=CapturingSensorEntity):
        # Mock Home Assistant
        hass = MagicMock()
        hass.data = {}

        # Mock the store
        store = MagicMock()
        store.async_load = AsyncMock(return_value={})
        store.async_save = AsyncMock()

        # Create a coordinator instance
        coordinator = GrowspaceCoordinator(hass)
        coordinator.store = store

        # Create a growspace
        growspace_id = "some_uuid_123"
        growspace_name = "4x4"
        growspace = Growspace(id=growspace_id, name=growspace_name)
        coordinator.growspaces[growspace_id] = growspace

        # Create the sensor
        sensor = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)

        # Print the generated IDs from the internal attributes
        print(f"Growspace Name: {growspace.name}")
        print(f"Growspace ID: {growspace.id}")
        print(f"Sensor Name: {sensor._attr_name}")
        print(f"Sensor Unique ID: {sensor._attr_unique_id}")
        print(f"Sensor Entity ID: {sensor._attr_entity_id}")

# Run the test
if __name__ == "__main__":
    run_test()
