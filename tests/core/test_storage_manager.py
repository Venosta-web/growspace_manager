"""Tests for the StorageManager."""

import glob
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.models import Growspace
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
def serializer_mock():
    """Mock the GrowspaceSerializer."""
    mock = MagicMock()

    def deserialize_gs(data):
        return {gid: Growspace.from_dict(gdata) for gid, gdata in data.items()}

    mock.deserialize_growspaces.side_effect = deserialize_gs
    mock.deserialize_plants.return_value = {}
    return mock


@pytest.mark.asyncio
async def test_load_growspaces_uses_serializer(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, serializer_mock
) -> None:
    """Test that loading growspaces delegates to the serializer."""
    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, serializer_mock
    )

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

        # Override the side effect to return a mock result to prove it was called
        mock_result = {"gs1": MagicMock()}
        serializer_mock.deserialize_growspaces.side_effect = None
        serializer_mock.deserialize_growspaces.return_value = mock_result

        await storage.async_load()

        # VERIFICATION: Ensure serializer.deserialize_growspaces was called
        serializer_mock.deserialize_growspaces.assert_called_once_with(
            raw_data["growspaces"]
        )

        # Verify the result was assigned to repository
        assert repository_mock.growspaces == mock_result


@pytest.mark.asyncio
async def test_backup_logic_with_corrupt_data(
    hass: HomeAssistant,
    repository_mock,
    nutrient_manager_mock,
    serializer_mock,
    tmp_path: Path,
) -> None:
    """Test that corrupt data triggers a backup file creation."""
    serializer_mock.deserialize_growspaces.side_effect = Exception("Corruption!")

    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, serializer_mock
    )

    # Mock hass.config.path to return a temp directory
    with patch.object(hass.config, "path", return_value=str(tmp_path)):
        # Corrupt data
        bad_data = {"growspaces": {"bad_id": "bad_data"}}

        # Trigger load which should fail
        storage._load_growspaces(bad_data)

        # Verify empty growspaces set (reset happened)
        assert repository_mock.growspaces == {}

        # Verify backup file creation
        files = glob.glob(f"{tmp_path}/growspace_manager_growspaces_CORRUPT_*.json")
        assert len(files) >= 1, "Backup file was not created"

        # Cleanup
        for f in files:
            Path(f).unlink()
