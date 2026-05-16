"""Unit test for coordinator pump logic."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    Growspace,
    GrowspaceType,
    IrrigationConfig,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_managers():
    with (
        patch("custom_components.growspace_manager.coordinator.StrainLibrary"),
        patch("custom_components.growspace_manager.coordinator.GrowspaceValidator"),
        patch("custom_components.growspace_manager.coordinator.StorageManager"),
        patch("custom_components.growspace_manager.coordinator.EnvironmentAnalyzer"),
        patch("custom_components.growspace_manager.coordinator.NotificationManager"),
        patch("custom_components.growspace_manager.coordinator.ImportExportManager"),
        patch("custom_components.growspace_manager.coordinator.PlantManager"),
        patch("custom_components.growspace_manager.coordinator.NutrientManager"),
        patch("custom_components.growspace_manager.coordinator.GrowspaceRepository"),
        patch("custom_components.growspace_manager.coordinator.SubsystemManager"),
        patch("custom_components.growspace_manager.coordinator.GrowspaceManager"),
        patch("custom_components.growspace_manager.coordinator.ViewModelBuilder"),
    ):
        yield


@pytest.mark.asyncio
async def test_async_update_irrigation_config_normalizes_empty_strings(
    hass: HomeAssistant, mock_managers: Any
) -> None:
    """Test that empty strings in pump entities are converted to None."""
    entry = MagicMock()

    # Initialize coordinator
    coordinator = GrowspaceCoordinator(hass, entry, data={})

    # Sub-managers created in __init__ are MagicMocks due to patching.
    # We must make the awaited methods AsyncMocks.
    coordinator.storage_manager.async_force_save = AsyncMock()
    coordinator.storage_manager.async_save = AsyncMock()

    # Mock other internal methods/properties
    coordinator.cache = MagicMock()
    coordinator.cache.invalidate = MagicMock()

    # The view_model_builder needs to return something for the 'data' property
    coordinator.view_model_builder.build_data_property.return_value = {}

    # Create test growspace
    growspace_id = "gs1"
    growspace = Growspace(
        id=growspace_id,
        name="Test",
        growspace_type=GrowspaceType.FLOWER,
        irrigation_config=IrrigationConfig(drain_pump_entity="switch.old"),
    )

    # Ensure the repository (which the facade now uses) has the growspace
    coordinator.growspaces = {growspace_id: growspace}
    coordinator.data_repository.growspaces = coordinator.growspaces
    coordinator.data_repository.get_growspace.return_value = growspace

    # Test Input: Empty String for drain_pump_entity
    user_input = {
        "irrigation_pump_entity": "switch.new_irrigation",
        "drain_pump_entity": "",  # THIS SHOULD BE NORMALIZED TO None
        "irrigation_duration": 120,
    }

    # Execute
    await coordinator.services.update_irrigation_config(growspace_id, user_input)

    # Assertions
    assert growspace.irrigation_config.irrigation_pump_entity == "switch.new_irrigation"
    assert growspace.irrigation_config.drain_pump_entity is None, (
        "Empty string should be normalized to None"
    )

    # Verify the save was actually attempted
    coordinator.storage_manager.async_force_save.assert_awaited_once()
