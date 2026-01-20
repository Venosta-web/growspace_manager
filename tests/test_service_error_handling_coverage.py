"""Tests for service error handling across all services to close coverage gaps."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_ITEMS,
    ATTR_NAME,
    ATTR_PRESET_ID,
    ATTR_TECHNIQUE,
    ATTR_TIME,
    ATTR_TYPE,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.ipm import (
    handle_apply_ipm,
    handle_remove_ipm_preset,
    handle_save_ipm_preset,
)
from custom_components.growspace_manager.services.irrigation import (
    handle_add_drain_time,
    handle_add_irrigation_time,
    handle_remove_drain_time,
    handle_remove_irrigation_time,
    handle_set_irrigation_settings,
)
from custom_components.growspace_manager.services.irrigation_watering import (
    handle_water_growspace,
    handle_water_plant,
)
from custom_components.growspace_manager.services.nutrient_presets import (
    handle_remove_nutrient_preset,
    handle_save_nutrient_preset,
)
from custom_components.growspace_manager.services.training import (
    handle_log_training_event,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.config_entries = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = MagicMock()
    coordinator.async_save_ipm_preset = AsyncMock()
    coordinator.async_remove_ipm_preset = AsyncMock()
    coordinator.async_apply_ipm = AsyncMock()
    coordinator.async_save_nutrient_preset = AsyncMock()
    coordinator.async_remove_nutrient_preset = AsyncMock()
    coordinator.async_log_training_event = AsyncMock()
    coordinator.async_water_plant = AsyncMock()
    coordinator.async_water_growspace = AsyncMock()
    return coordinator


@pytest.fixture
def mock_irrigation_coordinator():
    """Create a mock irrigation coordinator."""
    coord = MagicMock()
    coord.async_set_settings = AsyncMock()
    coord.async_add_schedule_item = AsyncMock()
    coord.async_remove_schedule_item = AsyncMock()
    coord.get_default_duration = MagicMock(return_value=300)
    return coord


async def setup_irrigation_mock(hass: HomeAssistant, irrigation_coord):
    """Utility to setup irrigation coordinator lookup."""
    entry = MagicMock()
    entry.runtime_data = MagicMock()
    entry.runtime_data.irrigation_coordinators = {"gs1": irrigation_coord}
    hass.config_entries.async_entries.return_value = [entry]


@pytest.mark.asyncio
async def test_ipm_error_handling(mock_hass, mock_coordinator) -> None:
    """Test error handling in IPM services."""
    call = MagicMock(spec=ServiceCall)
    call.data = {
        ATTR_NAME: "Test",
        ATTR_TYPE: "foliar",
        ATTR_ITEMS: [],
        ATTR_PRESET_ID: "p1",
    }

    # Save IPM Preset - GrowspaceError
    mock_coordinator.async_save_ipm_preset.side_effect = GrowspaceError("Save failed")
    with pytest.raises(ServiceValidationError, match="Save failed"):
        await handle_save_ipm_preset(mock_hass, mock_coordinator, call)

    # Save IPM Preset - Generic Exception
    mock_coordinator.async_save_ipm_preset.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to save IPM preset"):
        await handle_save_ipm_preset(mock_hass, mock_coordinator, call)

    # Remove IPM Preset - GrowspaceError
    call.data = {ATTR_PRESET_ID: "p1"}
    mock_coordinator.async_remove_ipm_preset.side_effect = GrowspaceError(
        "Remove failed"
    )
    with pytest.raises(ServiceValidationError, match="Remove failed"):
        await handle_remove_ipm_preset(mock_hass, mock_coordinator, call)

    # Remove IPM Preset - Generic Exception
    mock_coordinator.async_remove_ipm_preset.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to remove IPM preset"):
        await handle_remove_ipm_preset(mock_hass, mock_coordinator, call)

    # Apply IPM - GrowspaceError
    mock_coordinator.async_apply_ipm.side_effect = GrowspaceError("Apply failed")
    with pytest.raises(ServiceValidationError, match="Apply failed"):
        await handle_apply_ipm(mock_hass, mock_coordinator, call)

    # Apply IPM - Generic Exception
    mock_coordinator.async_apply_ipm.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to apply IPM"):
        await handle_apply_ipm(mock_hass, mock_coordinator, call)


@pytest.mark.asyncio
async def test_irrigation_error_handling(
    mock_hass, mock_coordinator, mock_irrigation_coordinator
) -> None:
    """Test error handling in Irrigation services."""
    await setup_irrigation_mock(mock_hass, mock_irrigation_coordinator)
    call = MagicMock(spec=ServiceCall)
    call.data = {ATTR_GROWSPACE_ID: "gs1", ATTR_TIME: "08:00:00"}

    # Set Settings - GrowspaceError
    mock_irrigation_coordinator.async_set_settings.side_effect = GrowspaceError(
        "Set failed"
    )
    with pytest.raises(ServiceValidationError, match="Set failed"):
        await handle_set_irrigation_settings(mock_hass, mock_coordinator, call)

    # Set Settings - Generic Exception
    mock_irrigation_coordinator.async_set_settings.side_effect = Exception("Crash")
    with pytest.raises(
        ServiceValidationError, match="Failed to set irrigation settings"
    ):
        await handle_set_irrigation_settings(mock_hass, mock_coordinator, call)

    # Add Irrigation Time - GrowspaceError
    mock_irrigation_coordinator.async_add_schedule_item.side_effect = GrowspaceError(
        "Add failed"
    )
    with pytest.raises(ServiceValidationError, match="Add failed"):
        await handle_add_irrigation_time(mock_hass, mock_coordinator, call)

    # Add Irrigation Time - Generic Exception
    mock_irrigation_coordinator.async_add_schedule_item.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to add irrigation time"):
        await handle_add_irrigation_time(mock_hass, mock_coordinator, call)

    # Remove Irrigation Time - GrowspaceError
    mock_irrigation_coordinator.async_remove_schedule_item.side_effect = GrowspaceError(
        "Remove failed"
    )
    with pytest.raises(ServiceValidationError, match="Remove failed"):
        await handle_remove_irrigation_time(mock_hass, mock_coordinator, call)

    # Remove Irrigation Time - Generic Exception
    mock_irrigation_coordinator.async_remove_schedule_item.side_effect = Exception(
        "Crash"
    )
    with pytest.raises(
        ServiceValidationError, match="Failed to remove irrigation time"
    ):
        await handle_remove_irrigation_time(mock_hass, mock_coordinator, call)

    # Add Drain Time - GrowspaceError
    mock_irrigation_coordinator.async_add_schedule_item.side_effect = GrowspaceError(
        "Add failed"
    )
    with pytest.raises(ServiceValidationError, match="Add failed"):
        await handle_add_drain_time(mock_hass, mock_coordinator, call)

    # Add Drain Time - Generic Exception
    mock_irrigation_coordinator.async_add_schedule_item.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to add drain time"):
        await handle_add_drain_time(mock_hass, mock_coordinator, call)

    # Remove Drain Time - GrowspaceError
    mock_irrigation_coordinator.async_remove_schedule_item.side_effect = GrowspaceError(
        "Remove failed"
    )
    with pytest.raises(ServiceValidationError, match="Remove failed"):
        await handle_remove_drain_time(mock_hass, mock_coordinator, call)

    # Remove Drain Time - Generic Exception
    mock_irrigation_coordinator.async_remove_schedule_item.side_effect = Exception(
        "Crash"
    )
    with pytest.raises(ServiceValidationError, match="Failed to remove drain time"):
        await handle_remove_drain_time(mock_hass, mock_coordinator, call)


@pytest.mark.asyncio
async def test_nutrient_error_handling(mock_hass, mock_coordinator) -> None:
    """Test error handling in Nutrient Preset services."""
    call = MagicMock(spec=ServiceCall)
    call.data = {ATTR_NAME: "Test", "nutrients": {}, ATTR_PRESET_ID: "n1"}

    # Save Nutrient - GrowspaceError
    mock_coordinator.async_save_nutrient_preset.side_effect = GrowspaceError(
        "Save failed"
    )
    with pytest.raises(ServiceValidationError, match="Save failed"):
        await handle_save_nutrient_preset(mock_hass, mock_coordinator, call)

    # Save Nutrient - Generic Exception
    mock_coordinator.async_save_nutrient_preset.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to save nutrient preset"):
        await handle_save_nutrient_preset(mock_hass, mock_coordinator, call)

    # Remove Nutrient - GrowspaceError
    call.data = {ATTR_PRESET_ID: "n1"}
    mock_coordinator.async_remove_nutrient_preset.side_effect = GrowspaceError(
        "Remove failed"
    )
    with pytest.raises(ServiceValidationError, match="Remove failed"):
        await handle_remove_nutrient_preset(mock_hass, mock_coordinator, call)

    # Remove Nutrient - Generic Exception
    mock_coordinator.async_remove_nutrient_preset.side_effect = Exception("Crash")
    with pytest.raises(
        ServiceValidationError, match="Failed to remove nutrient preset"
    ):
        await handle_remove_nutrient_preset(mock_hass, mock_coordinator, call)


@pytest.mark.asyncio
async def test_training_error_handling(mock_hass, mock_coordinator) -> None:
    """Test error handling in Training services."""
    call = MagicMock(spec=ServiceCall)
    call.data = {ATTR_TECHNIQUE: "topping"}

    # Log Training - GrowspaceError
    mock_coordinator.async_log_training_event.side_effect = GrowspaceError("Log failed")
    with pytest.raises(ServiceValidationError, match="Log failed"):
        await handle_log_training_event(mock_hass, mock_coordinator, call)

    # Log Training - Generic Exception
    mock_coordinator.async_log_training_event.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to log training event"):
        await handle_log_training_event(mock_hass, mock_coordinator, call)


@pytest.mark.asyncio
async def test_irrigation_watering_error_handling(mock_hass, mock_coordinator) -> None:
    """Test error handling and success in irrigation_watering services."""
    call = MagicMock(spec=ServiceCall)
    call.data = {
        "plant_id": "p1",
        "amount": 1.0,
        "growspace_id": "gs1",
        "amount_per_plant": 1.0,
    }

    # Success cases
    # For AsyncMock, we just need to ensure it's awaitable (default)
    mock_coordinator.async_water_growspace.return_value = 5

    await handle_water_plant(mock_hass, mock_coordinator, call)
    result = await handle_water_growspace(mock_hass, mock_coordinator, call)
    assert result == {"plants_watered": 5}

    # Water Plant - GrowspaceError
    mock_coordinator.async_water_plant.side_effect = GrowspaceError("Water failed")
    with pytest.raises(ServiceValidationError, match="Water failed"):
        await handle_water_plant(mock_hass, mock_coordinator, call)

    # Water Plant - Generic Exception
    mock_coordinator.async_water_plant.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to water plant"):
        await handle_water_plant(mock_hass, mock_coordinator, call)

    # Water Growspace - GrowspaceError
    mock_coordinator.async_water_growspace.side_effect = GrowspaceError(
        "Water gs failed"
    )
    with pytest.raises(ServiceValidationError, match="Water gs failed"):
        await handle_water_growspace(mock_hass, mock_coordinator, call)

    # Water Growspace - Generic Exception
    mock_coordinator.async_water_growspace.side_effect = Exception("Crash")
    with pytest.raises(ServiceValidationError, match="Failed to water growspace"):
        await handle_water_growspace(mock_hass, mock_coordinator, call)
