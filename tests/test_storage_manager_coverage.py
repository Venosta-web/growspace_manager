"""Coverage tests for StorageManager."""

from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    NutrientInventory,
)
from custom_components.growspace_manager.storage_manager import StorageManager


@pytest.fixture
def mock_coordinator():
    """Mock the coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.options = {}
    coordinator.nutrient_manager = MagicMock()
    coordinator.serializer = MagicMock()
    return coordinator


@pytest.mark.asyncio
async def test_storage_apply_options_object(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test applying options when they are already an object (Line 198)."""
    env_config = EnvironmentConfig(temperature_sensor="sensor.temp")
    mock_coordinator.options = {"gs1": env_config}
    mock_coordinator.growspaces = {"gs1": Growspace(id="gs1", name="Test")}

    storage = StorageManager(mock_coordinator, hass)
    storage._apply_options_to_growspaces()

    assert mock_coordinator.growspaces["gs1"].environment_config == env_config


@pytest.mark.asyncio
async def test_storage_load_nutrient_inventory_exception(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test exception handling in _load_nutrient_inventory (Lines 226-228)."""
    storage = StorageManager(mock_coordinator, hass)

    with patch(
        "custom_components.growspace_manager.models.NutrientInventory.from_dict",
        side_effect=ValueError("Test Error"),
    ):
        result = storage._load_nutrient_inventory({"nutrient_inventory": {}})
        assert isinstance(result, NutrientInventory)
        # Should return a fresh NutrientInventory on error


@pytest.mark.asyncio
async def test_storage_backup_corrupt_data_exception(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test exception handling in _backup_corrupt_data (Lines 156-157)."""
    # This covers the catch-all exception in backup logic
    storage = StorageManager(mock_coordinator, hass)

    with patch("builtins.open", side_effect=PermissionError("No way")):
        # This should log an error but not raise
        storage._backup_corrupt_data("test", {"some": "data"})
