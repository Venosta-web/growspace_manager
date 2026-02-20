"""Tests for the StorageManager."""

import glob
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.storage_manager import StorageManager
from homeassistant.core import HomeAssistant


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.growspaces = {}
    mock.plants = {}
    mock.notifications_sent = {}
    mock.notifications_enabled = {}
    return mock


@pytest.fixture
def nutrient_manager_mock():
    """Mock the NutrientManager."""
    mock = MagicMock()
    mock.nutrient_presets = {}
    mock.ipm_presets = {}
    mock.inventory = None
    mock.get_serialization_data.return_value = {}
    return mock


@pytest.fixture
def storage(hass, repository_mock, nutrient_manager_mock):
    """Provide a StorageManager instance."""
    return StorageManager(hass, repository_mock, nutrient_manager_mock)


@pytest.mark.asyncio
async def test_load_growspaces_uses_mashumaro(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, storage
) -> None:
    """Test that loading growspaces correctly uses Mashumaro deserialization."""

    # Mock data
    raw_data = {
        "growspaces": {
            "gs1": {
                "id": "gs1",
                "name": "Test",
                "rows": 2,
                "plants_per_row": 3,
                "irrigation_config": {
                    "irrigation_times": [{"time": "08:00:00", "duration": 60}]
                },
            }
        }
    }

    # Setup store mocks
    with patch("homeassistant.helpers.storage.Store.async_load") as mock_load:
        mock_load.return_value = raw_data

        await storage.async_load()

        # VERIFICATION: Ensure growspaces were loaded into repository
        assert len(repository_mock.growspaces) == 1
        assert "gs1" in repository_mock.growspaces
        assert repository_mock.growspaces["gs1"].name == "Test"


@pytest.mark.asyncio
async def test_backup_logic_with_corrupt_data(
    hass: HomeAssistant,
    repository_mock,
    nutrient_manager_mock,
    storage,
    tmp_path: Path,
) -> None:
    """Test that corrupt data triggers a backup file creation."""

    # Mock hass.config.path to return a temp directory
    with patch.object(hass.config, "path", return_value=str(tmp_path)):
        # Trigger load with structural corruption (not just single item)
        # to trigger the outer try-except block that calls _backup_corrupt_data
        corrupt_data = MagicMock()
        corrupt_data.get.side_effect = Exception("Structural corruption!")

        storage._load_growspaces(corrupt_data)

        # Verify empty growspaces set (reset happened)
        assert repository_mock.growspaces == {}

        # Verify backup file creation
        files = glob.glob(f"{tmp_path}/growspace_manager_growspaces_CORRUPT_*.json")
        assert len(files) >= 1, "Backup file was not created"

        # Cleanup
        for f in files:
            Path(f).unlink()
