"""Fixtures for Growspace Manager tests."""

import pytest


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(enable_custom_integrations):
    """Enable custom integrations defined in the test environment."""
    yield
from unittest.mock import AsyncMock, MagicMock, Mock

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator


@pytest.fixture
async def mock_store(hass):
    """Create a mock store."""
    store = MagicMock(spec=Store)
    store.async_load = AsyncMock(
        return_value={
            "growspaces": {},
            "plants": {},
            "notifications_sent": {},
            "strain_library": [],
            "notifications_enabled": {},
        }
    )
    store.async_save = AsyncMock()
    return store


@pytest.fixture
async def config_entry(hass):
    """Create a mock config entry."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Test Growspace Manager"},
        entry_id="test_entry_id",
        options={},
    )
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
async def coordinator(hass: HomeAssistant, config_entry, mock_store):
    """Create and return a real coordinator instance for testing."""
    # Initialize hass.data structure
    hass.data.setdefault(DOMAIN, {})

    # Create the coordinator with empty data dict
    coordinator = GrowspaceCoordinator(hass, data={})

    # Replace the store with our mock
    coordinator._store = mock_store

    # Initialize with empty data
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator._notifications_sent = {}
    coordinator._notifications_enabled = {}

    # Update data property
    coordinator.data = {
        "growspaces": coordinator.growspaces,
        "plants": coordinator.plants,
        "notifications_sent": coordinator._notifications_sent,
        "notifications_enabled": coordinator._notifications_enabled,
    }

    # Store in hass.data so tests can access it
    hass.data[DOMAIN][config_entry.entry_id] = {
        "coordinator": coordinator,
        "store": mock_store,
    }

    return coordinator


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator for config flow tests."""
    coordinator = Mock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.notifications_sent = {}
    coordinator.data = {
        "growspaces": {},
        "plants": {},
        "notifications_sent": {},
        "notifications_enabled": {},
    }

    # ✅ Use AsyncMock for async methods ONLY
    coordinator.async_save = AsyncMock()

    # ✅ Use regular MagicMock for sync methods (don't await this!)
    coordinator.async_set_updated_data = MagicMock()

    # Mock internal non-async methods that are called in the migration logic
    coordinator._migrate_plants_to_growspace = Mock()
    coordinator.update_data_property = Mock()

    # Mock ensure_special_growspace to return the growspace_id
    coordinator.ensure_special_growspace = MagicMock(
        side_effect=lambda gs_id, name, rows, ppr: gs_id
    )

    # Additional mocks for config flow tests
    coordinator.async_add_growspace = AsyncMock(return_value=Mock(id="growspace_1"))
    coordinator.async_update_growspace = AsyncMock()
    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_add_plant = AsyncMock(return_value=Mock(plant_id="plant_1"))
    coordinator.async_update_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.get_growspace_plants = Mock(return_value=[])
    coordinator.get_strain_options = Mock(return_value=["Strain1", "Strain2"])

    return coordinator


# er(hass, initial_data)


@pytest.fixture
def plant_data():
    """Provides a dictionary with a single test plant."""
    return {
        "p1": {
            "plant_id": "p1",
            "growspace_id": "gs1",
            "strain": "Test Strain",
            "phenotype": "",
            "row": 1,
            "col": 1,
            "stage": "veg",
            "type": "normal",
            "device_id": None,
            "seedling_start": None,
            "mother_start": None,
            "clone_start": None,
            "veg_start": "2024-01-01",
            "flower_start": None,
            "dry_start": None,
            "cure_start": None,
            "created_at": "2024-01-01",
            "updated_at": None,
            "source_mother": "",
        }
    }


@pytest.fixture
def growspace_data():
    """Provides a dictionary with a single test growspace."""
    return {
        "gs1": {
            "id": "gs1",
            "name": "Test Growspace",
            "rows": 4,
            "plants_per_row": 4,
            "notification_target": None,
            "created_at": "2024-01-01",
            "device_id": None,
        }
    }


@pytest.fixture
def initial_manager_data(plant_data, growspace_data):
    """
    Provides a complete initial data dictionary for the GrowspaceManager,
    combining plant and growspace fixtures.
    """
    return {
        "plants": plant_data,
        "growspaces": growspace_data,
        "notifications_sent": {},
        "notifications_enabled": {"gs1": True},
    }
