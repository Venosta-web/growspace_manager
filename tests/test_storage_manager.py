"""Tests for the StorageManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.storage_manager import StorageManager

GROWSPACE_ID = "test_growspace"
PLANT_ID = "test_plant"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator._notifications_sent = {}
    coordinator._notifications_enabled = {}
    coordinator.options = {}
    coordinator.migration_manager = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_store():
    """Mock the Store class."""
    with patch(
        "custom_components.growspace_manager.storage_manager.Store"
    ) as mock_store_cls:
        mock_store_instance = mock_store_cls.return_value
        mock_store_instance.async_load = AsyncMock()
        mock_store_instance.async_save = AsyncMock()
        yield mock_store_instance


@pytest.fixture
def storage_manager(mock_coordinator, mock_hass, mock_store) -> StorageManager:
    """Fixture for StorageManager."""
    return StorageManager(mock_coordinator, mock_hass)


async def test_initialization(
    storage_manager: StorageManager, mock_coordinator, mock_hass
):
    """Test initialization."""
    assert storage_manager.coordinator == mock_coordinator
    assert storage_manager.hass == mock_hass
    assert storage_manager.store is not None


async def test_async_save(
    storage_manager: StorageManager, mock_coordinator, mock_store
):
    """Test saving data."""
    # Setup data
    growspace = Growspace(id=GROWSPACE_ID, name="Test GS")
    plant = Plant(plant_id=PLANT_ID, growspace_id=GROWSPACE_ID, strain="Strain A")

    mock_coordinator.growspaces = {GROWSPACE_ID: growspace}
    mock_coordinator.plants = {PLANT_ID: plant}
    mock_coordinator._notifications_sent = {"some_id": True}
    mock_coordinator._notifications_enabled = {GROWSPACE_ID: True}

    await storage_manager.async_save()

    mock_store.async_save.assert_awaited_once()
    saved_data = mock_store.async_save.call_args[0][0]

    assert GROWSPACE_ID in saved_data["growspaces"]
    assert PLANT_ID in saved_data["plants"]
    assert saved_data["notifications_sent"] == {"some_id": True}
    assert saved_data["notifications_enabled"] == {GROWSPACE_ID: True}


async def test_async_load_no_data(
    storage_manager: StorageManager, mock_store, mock_coordinator
):
    """Test loading when no data exists."""
    mock_store.async_load.return_value = None

    await storage_manager.async_load()

    assert mock_coordinator.growspaces == {}
    assert mock_coordinator.plants == {}


async def test_async_load_success(
    storage_manager: StorageManager, mock_store, mock_coordinator
):
    """Test successful data loading."""
    data = {
        "growspaces": {
            GROWSPACE_ID: {
                "id": GROWSPACE_ID,
                "name": "Test GS",
                "rows": 3,
                "plants_per_row": 3,
            }
        },
        "plants": {
            PLANT_ID: {
                "plant_id": PLANT_ID,
                "growspace_id": GROWSPACE_ID,
                "strain": "Strain A",
            }
        },
        "notifications_sent": {"some_id": True},
        "notifications_enabled": {GROWSPACE_ID: False},
    }
    mock_store.async_load.return_value = data

    await storage_manager.async_load()

    assert GROWSPACE_ID in mock_coordinator.growspaces
    assert isinstance(mock_coordinator.growspaces[GROWSPACE_ID], Growspace)

    assert PLANT_ID in mock_coordinator.plants
    assert isinstance(mock_coordinator.plants[PLANT_ID], Plant)

    assert mock_coordinator._notifications_sent == {"some_id": True}
    assert mock_coordinator._notifications_enabled == {GROWSPACE_ID: False}

    # Verify migration called
    mock_coordinator.migration_manager.migrate_legacy_growspaces.assert_called_once()

    # Verify save called after migration
    mock_store.async_save.assert_awaited()


async def test_async_load_with_options(
    storage_manager: StorageManager, mock_store, mock_coordinator
):
    """Test loading data and applying options."""
    data = {
        "growspaces": {
            GROWSPACE_ID: {
                "id": GROWSPACE_ID,
                "name": "Test GS",
            }
        }
    }
    mock_store.async_load.return_value = data

    mock_coordinator.options = {GROWSPACE_ID: {"temp_min": 20}}

    await storage_manager.async_load()

    assert mock_coordinator.growspaces[GROWSPACE_ID].environment_config == {
        "temp_min": 20
    }


async def test_async_load_corrupted_data(
    storage_manager: StorageManager, mock_store, mock_coordinator
):
    """Test loading corrupted data."""
    # Corrupted plants
    mock_store.async_load.return_value = {
        "plants": {"invalid": "not a dict"},
        "growspaces": {},
    }

    await storage_manager.async_load()

    assert mock_coordinator.plants == {}

    # Corrupted growspaces
    mock_store.async_load.return_value = {
        "plants": {},
        "growspaces": {"invalid": "not a dict"},
    }

    await storage_manager.async_load()

    assert mock_coordinator.growspaces == {}
