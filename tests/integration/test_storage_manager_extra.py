"""Extra coverage tests for StorageManager."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.models import (
    Growspace,
    Plant,
)
from custom_components.growspace_manager.storage_manager import StorageManager
from homeassistant.core import HomeAssistant


@pytest.fixture
def repository_mock():
    """Mock the GrowspaceRepository."""
    mock = MagicMock()
    mock.growspaces = {}
    mock.plants = {}
    return mock


@pytest.fixture
def nutrient_manager_mock():
    """Mock the NutrientManager."""
    return MagicMock()


@pytest.fixture
def storage(hass: HomeAssistant, repository_mock, nutrient_manager_mock):
    """Provide a StorageManager instance."""
    return StorageManager(hass, repository_mock, nutrient_manager_mock)


def test_load_plants_generic_exception(storage, repository_mock) -> None:
    """Trigger the generic Exception catch in _load_plants."""
    # data.get raising an unexpected Exception (not ValueError, KeyError, TypeError)
    data = MagicMock()
    data.get.side_effect = RuntimeError("Generic Crash")

    with patch.object(storage, "_backup_corrupt_data") as mock_backup:
        storage._load_plants(data)
        mock_backup.assert_called_once_with("plants", data)
        assert repository_mock.plants == {}


def test_load_growspaces_generic_exception(storage, repository_mock) -> None:
    """Trigger the generic Exception catch in _load_growspaces."""
    # data.get raising an unexpected Exception
    data = MagicMock()
    data.get.side_effect = RuntimeError("Generic Crash")

    with patch.object(storage, "_backup_corrupt_data") as mock_backup:
        storage._load_growspaces(data)
        mock_backup.assert_called_once_with("growspaces", data)
        assert repository_mock.growspaces == {}


def test_load_plants_inner_data_mismatch(storage, repository_mock) -> None:
    """Trigger the ValueError, KeyError, TypeError catch in _load_plants for a specific plant."""
    data = {"plants": {"p1": {"some": "data"}}}
    with (
        patch(
            "custom_components.growspace_manager.models.Plant.from_dict",
            side_effect=ValueError("Data structure mismatch"),
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_log_exc,
    ):
        storage._load_plants(data)
        # Verify it logged "mismatch" (line 198)
        mock_log_exc.assert_called_with(
            "Failed to load plant %s due to data structure mismatch", "p1"
        )
        assert repository_mock.plants == {}


def test_load_growspaces_inner_data_mismatch(storage, repository_mock) -> None:
    """Trigger the ValueError, KeyError, TypeError catch in _load_growspaces for a specific growspace."""
    data = {"growspaces": {"gs1": {"some": "data"}}}
    with (
        patch(
            "custom_components.growspace_manager.models.Growspace.from_dict",
            side_effect=ValueError("Data structure mismatch"),
        ),
        patch(
            "custom_components.growspace_manager.storage_manager._LOGGER.exception"
        ) as mock_log_exc,
    ):
        storage._load_growspaces(data)
        # Verify it logged "mismatch" (line 242)
        mock_log_exc.assert_called_with(
            "Failed to load growspace %s due to data structure mismatch", "gs1"
        )
        assert repository_mock.growspaces == {}


def test_load_plants_outer_data_mismatch(storage, repository_mock) -> None:
    """Trigger the outer (ValueError, KeyError, TypeError) catch in _load_plants."""
    # This happens if data.get("plants", {}) raises one of these
    data = MagicMock()
    data.get.side_effect = TypeError("Outer mismatch")

    with patch.object(storage, "_backup_corrupt_data") as mock_backup:
        storage._load_plants(data)
        # Verify line 207-209 was hit
        mock_backup.assert_called_once_with("plants", data)
        assert repository_mock.plants == {}


def test_load_growspaces_outer_data_mismatch(storage, repository_mock) -> None:
    """Trigger the outer (ValueError, KeyError, TypeError) catch in _load_growspaces."""
    data = MagicMock()
    data.get.side_effect = TypeError("Outer mismatch")

    with patch.object(storage, "_backup_corrupt_data") as mock_backup:
        storage._load_growspaces(data)
        # Verify line 254-256 was hit
        mock_backup.assert_called_once_with("growspaces", data)
        assert repository_mock.growspaces == {}
