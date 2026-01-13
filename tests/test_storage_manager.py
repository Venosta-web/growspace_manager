"""Tests for the StorageManager."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.storage_manager import StorageManager


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.nutrient_presets = {}
    coordinator.ipm_presets = {}
    coordinator._notifications_sent = {}
    coordinator._notifications_enabled = {}
    coordinator.options = {}

    # Mock serializer behavior
    coordinator.serializer = MagicMock()

    def deserialize_gs(data):
        return {gid: Growspace.from_dict(gdata) for gid, gdata in data.items()}

    coordinator.serializer.deserialize_growspaces.side_effect = deserialize_gs
    coordinator.serializer.deserialize_plants.return_value = {}

    return coordinator


@pytest.mark.asyncio
async def test_load_growspaces_uses_serializer(hass: HomeAssistant, mock_coordinator):
    """Test that loading growspaces delegates to the serializer."""
    storage = StorageManager(mock_coordinator, hass)

    # Mock data with legacy irrigation format
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
        mock_result = {"gs1": MagicMock(spec=Growspace)}
        mock_coordinator.serializer.deserialize_growspaces.side_effect = None
        mock_coordinator.serializer.deserialize_growspaces.return_value = mock_result

        await storage.async_load()

        # VERIFICATION: Ensure serializer.deserialize_growspaces was called
        mock_coordinator.serializer.deserialize_growspaces.assert_called_once_with(
            raw_data["growspaces"]
        )

        # Verify the result was assigned to coordinator
        assert mock_coordinator.growspaces == mock_result


@pytest.mark.asyncio
async def test_backup_logic_with_corrupt_data(hass: HomeAssistant, mock_coordinator):
    """Test that corrupt data triggers a backup file creation."""
    mock_coordinator.serializer.deserialize_growspaces.side_effect = Exception(
        "Corruption!"
    )

    storage = StorageManager(mock_coordinator, hass)

    # Mock hass.config.path to return a temp directory
    with patch.object(hass.config, "path", return_value="/tmp") as mock_path:
        # Corrupt data
        bad_data = {"growspaces": {"bad_id": "bad_data"}}

        # Trigger load which should fail
        # We need to test _load_growspaces specifically or async_load
        # using the internal method for direct testing as in the safety test
        storage._load_growspaces(bad_data)

        # Verify empty growspaces set (reset happened)
        assert mock_coordinator.growspaces == {}

        # Verify backup file creation
        import glob
        import json
        from pathlib import Path

        files = glob.glob("/tmp/growspace_manager_growspaces_CORRUPT_*.json")
        assert len(files) >= 1, "Backup file was not created"

        # Read the file and check content
        last_file = files[-1]
        with open(last_file) as f:
            saved_data = json.load(f)
            assert saved_data == bad_data

        # Cleanup
        Path(last_file).unlink()
