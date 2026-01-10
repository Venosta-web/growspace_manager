"""Tests for the StorageManager."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.const import (
    STORAGE_KEY,
    STORAGE_KEY_CONFIG,
    STORAGE_KEY_PLANTS,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    Plant,
)
from custom_components.growspace_manager.storage_manager import StorageManager

GROWSPACE_ID = "test_growspace"
PLANT_ID = "test_plant"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.nutrient_presets = {}
    coordinator.ipm_presets = {}
    coordinator._notifications_sent = {}
    coordinator._notifications_enabled = {}
    coordinator.options = {}

    return coordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    return MagicMock(spec=HomeAssistant)


@pytest.fixture
def mock_stores():
    """Mock the Store class to return different stores based on key."""
    with patch(
        "custom_components.growspace_manager.storage_manager.Store"
    ) as mock_store_cls:
        config_store = MagicMock()
        config_store.async_load = AsyncMock(return_value=None)
        config_store.async_delay_save = MagicMock()
        config_store.async_save = AsyncMock()

        plants_store = MagicMock()
        plants_store.async_load = AsyncMock(return_value=None)
        plants_store.async_delay_save = MagicMock()
        plants_store.async_save = AsyncMock()

        legacy_store = MagicMock()
        legacy_store.async_load = AsyncMock(return_value=None)
        legacy_store.async_save = AsyncMock()

        def store_side_effect(hass: HomeAssistant, version, key):
            if key == STORAGE_KEY_CONFIG:
                return config_store
            elif key == STORAGE_KEY_PLANTS:
                return plants_store
            elif key == STORAGE_KEY:
                return legacy_store
            return MagicMock()

        mock_store_cls.side_effect = store_side_effect

        yield {
            "config": config_store,
            "plants": plants_store,
            "legacy": legacy_store,
            "cls": mock_store_cls,
        }


@pytest.fixture
def storage_manager(mock_coordinator, mock_hass, mock_stores) -> StorageManager:
    """Fixture for StorageManager."""
    return StorageManager(mock_coordinator, mock_hass)


async def test_initialization(
    storage_manager: StorageManager, mock_coordinator, mock_hass, mock_stores
) -> None:
    """Test initialization."""
    assert storage_manager.coordinator == mock_coordinator
    assert storage_manager.hass == mock_hass
    assert storage_manager.config_store == mock_stores["config"]
    assert storage_manager.plants_store == mock_stores["plants"]
    assert storage_manager.legacy_store == mock_stores["legacy"]


async def test_async_save_debounced(
    storage_manager: StorageManager, mock_coordinator, mock_stores
) -> None:
    """Test saving data is debounced using async_delay_save."""
    # Setup data
    growspace = Growspace(id=GROWSPACE_ID, name="Test GS")
    plant = Plant(plant_id=PLANT_ID, growspace_id=GROWSPACE_ID, strain="Strain A")

    mock_coordinator.growspaces = {GROWSPACE_ID: growspace}
    mock_coordinator.plants = {PLANT_ID: plant}
    mock_coordinator._notifications_sent = {"some_id": True}
    mock_coordinator._notifications_enabled = {GROWSPACE_ID: True}

    await storage_manager.async_save()

    # Check delays
    mock_stores["config"].async_delay_save.assert_called_once()
    mock_stores["plants"].async_delay_save.assert_called_once()

    # Check delay value (10s)
    args_config = mock_stores["config"].async_delay_save.call_args
    assert args_config[0][1] == 10

    args_plants = mock_stores["plants"].async_delay_save.call_args
    assert args_plants[0][1] == 10

    # Verify content generator
    config_callback = args_config[0][0]
    plants_callback = args_plants[0][0]

    config_data = config_callback()
    plants_data = plants_callback()

    assert GROWSPACE_ID in config_data["growspaces"]
    assert PLANT_ID in plants_data["plants"]
    assert config_data["notifications_enabled"] == {GROWSPACE_ID: True}


async def test_async_load_new_storage(
    storage_manager: StorageManager, mock_stores, mock_coordinator
) -> None:
    """Test loading from new segmented storage."""
    config_data = {
        "growspaces": {
            GROWSPACE_ID: {
                "id": GROWSPACE_ID,
                "name": "Test GS",
            }
        },
        "notifications_enabled": {GROWSPACE_ID: False},
    }
    plants_data = {
        "plants": {
            PLANT_ID: {
                "plant_id": PLANT_ID,
                "growspace_id": GROWSPACE_ID,
                "strain": "Strain A",
            }
        }
    }

    mock_stores["config"].async_load.return_value = config_data
    mock_stores["plants"].async_load.return_value = plants_data

    await storage_manager.async_load()

    assert GROWSPACE_ID in mock_coordinator.growspaces
    assert PLANT_ID in mock_coordinator.plants
    assert mock_coordinator._notifications_enabled == {GROWSPACE_ID: False}


async def test_async_load_legacy_migration(
    storage_manager: StorageManager, mock_stores, mock_coordinator
) -> None:
    """Test migration from legacy storage."""
    # New stores empty
    mock_stores["config"].async_load.return_value = None
    mock_stores["plants"].async_load.return_value = None

    # Legacy store has data
    legacy_data = {
        "growspaces": {
            GROWSPACE_ID: {
                "id": GROWSPACE_ID,
                "name": "Legacy GS",
            }
        },
        "plants": {
            PLANT_ID: {
                "plant_id": PLANT_ID,
                "growspace_id": GROWSPACE_ID,
                "strain": "Legacy Strain",
            }
        },
        "notifications_enabled": {GROWSPACE_ID: True},
    }
    mock_stores["legacy"].async_load.return_value = legacy_data

    await storage_manager.async_load()

    # Loaded correctly
    assert mock_coordinator.growspaces[GROWSPACE_ID].name == "Legacy GS"
    assert mock_coordinator.plants[PLANT_ID].strain == "Legacy Strain"

    # Assert saved to new stores immediate
    mock_stores["config"].async_save.assert_awaited_once()
    mock_stores["plants"].async_save.assert_awaited_once()


async def test_async_load_no_data(
    storage_manager: StorageManager, mock_stores, mock_coordinator
) -> None:
    """Test loading when no data exists anywhere."""
    mock_stores["config"].async_load.return_value = None
    mock_stores["plants"].async_load.return_value = None
    mock_stores["legacy"].async_load.return_value = None

    await storage_manager.async_load()

    assert mock_coordinator.growspaces == {}
    assert mock_coordinator.plants == {}

    # Verify forced initial save creates files
    storage_manager.config_store.async_delay_save.assert_called()
    storage_manager.plants_store.async_delay_save.assert_called()


async def test_apply_options_to_growspaces_with_environment_config_object(
    storage_manager: StorageManager, mock_coordinator
) -> None:
    """Test _apply_options_to_growspaces when options is already an EnvironmentConfig object.

    This covers line 160 in storage_manager.py.
    """
    # Create a growspace
    growspace = Growspace(id=GROWSPACE_ID, name="Test GS")
    mock_coordinator.growspaces = {GROWSPACE_ID: growspace}

    # Set options as an EnvironmentConfig object (not a dict)
    env_config = EnvironmentConfig(lst_offset=-5.0)  # Create with custom value
    mock_coordinator.options = {GROWSPACE_ID: env_config}

    # Call the method
    storage_manager._apply_options_to_growspaces()

    # Verify it was set directly without from_dict conversion
    assert mock_coordinator.growspaces[GROWSPACE_ID].environment_config is env_config
    assert (
        mock_coordinator.growspaces[GROWSPACE_ID].environment_config.lst_offset == -5.0
    )


async def test_load_ipm_presets_with_invalid_data(
    storage_manager: StorageManager, mock_coordinator
) -> None:
    """Test _load_ipm_presets error handling with corrupted data.

    This covers lines 180-182 in storage_manager.py.
    """
    # Create invalid preset data that will cause IPMPreset.from_dict to fail
    invalid_data = {
        "ipm_presets": {
            "preset1": {
                # Missing required fields, or invalid data structure
                "invalid_key": "this will cause an error"
            }
        }
    }

    # Call the method - should not raise, but log and set empty dict
    storage_manager._load_ipm_presets(invalid_data)

    # Should have set empty dict due to error
    assert mock_coordinator.ipm_presets == {}
