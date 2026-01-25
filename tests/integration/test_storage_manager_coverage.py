"""Coverage tests for StorageManager."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    NutrientInventory,
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
def serializer_mock():
    """Mock the GrowspaceSerializer."""
    return MagicMock()


@pytest.mark.asyncio
async def test_storage_apply_options_object(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, serializer_mock
) -> None:
    """Test applying options when they are already an object."""
    env_config = EnvironmentConfig(temperature_sensor="sensor.temp")
    options = {"gs1": env_config}
    repository_mock.growspaces = {"gs1": Growspace(id="gs1", name="Test")}

    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, serializer_mock
    )
    storage._apply_options_to_growspaces(options)

    assert repository_mock.growspaces["gs1"].environment_config == env_config


@pytest.mark.asyncio
async def test_storage_load_nutrient_inventory_exception(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, serializer_mock
) -> None:
    """Test exception handling in _load_nutrient_inventory."""
    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, serializer_mock
    )

    with patch(
        "custom_components.growspace_manager.models.NutrientInventory.from_dict",
        side_effect=ValueError("Test Error"),
    ):
        result = storage._load_nutrient_inventory({"nutrient_inventory": {}})
        assert isinstance(result, NutrientInventory)


@pytest.mark.asyncio
async def test_storage_backup_corrupt_data_exception(
    hass: HomeAssistant, repository_mock, nutrient_manager_mock, serializer_mock
) -> None:
    """Test exception handling in _backup_corrupt_data."""
    storage = StorageManager(
        hass, repository_mock, nutrient_manager_mock, serializer_mock
    )

    with patch("builtins.open", side_effect=PermissionError("No way")):
        # This should log an error but not raise
        storage._backup_corrupt_data("test", {"some": "data"})
