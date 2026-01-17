"""Unit test for coordinator pump logic."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    Growspace,
    GrowspaceType,
    IrrigationConfig,
)
from .conftest import create_plant



@pytest.fixture
def mock_managers():
    with (
        patch("custom_components.growspace_manager.coordinator.StrainLibrary"),
        patch("custom_components.growspace_manager.coordinator.GrowspaceValidator"),
        patch("custom_components.growspace_manager.coordinator.StorageManager"),
        patch("custom_components.growspace_manager.coordinator.EnvironmentAnalyzer"),
        patch("custom_components.growspace_manager.coordinator.NotificationManager"),
        patch("custom_components.growspace_manager.coordinator.ImportExportManager"),
        patch("custom_components.growspace_manager.coordinator.PlantLifecycleManager"),
        patch("custom_components.growspace_manager.coordinator.NutrientManager"),
        patch("custom_components.growspace_manager.coordinator.DataRepository"),
        patch("custom_components.growspace_manager.coordinator.SubsystemManager"),
        patch("custom_components.growspace_manager.coordinator.PlantService"),
        patch("custom_components.growspace_manager.coordinator.GrowspaceService"),
    ):
        yield


@pytest.mark.asyncio
async def test_async_update_irrigation_config_normalizes_empty_strings(
    hass: HomeAssistant, mock_managers
) -> None:
    """Test that empty strings in pump entities are converted to None."""
    entry = MagicMock()

    # Initialize coordinator with mocks to avoid side effects
    coordinator = GrowspaceCoordinator(hass, entry, data={})

    # Mock internal methods
    coordinator._invalidate_cache = MagicMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()

    # Create test growspace
    growspace_id = "gs1"
    growspace = Growspace(
        id=growspace_id,
        name="Test",
        growspace_type=GrowspaceType.FLOWER,
        irrigation_config=IrrigationConfig(drain_pump_entity="switch.old"),
    )
    coordinator.growspaces = {growspace_id: growspace}

    # Test Input: Empty String for drain_pump_entity
    user_input = {
        "irrigation_pump_entity": "switch.new_irrigation",
        "drain_pump_entity": "",  # THIS SHOULD BE NORMALIZED TO None
        "irrigation_duration": 120,
    }

    # Execute
    await coordinator.async_update_irrigation_config(growspace_id, user_input)

    # Assertions
    assert growspace.irrigation_config.irrigation_pump_entity == "switch.new_irrigation"
    assert growspace.irrigation_config.drain_pump_entity is None, (
        "Empty string should be normalized to None"
    )
