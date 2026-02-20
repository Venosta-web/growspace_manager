"""Tests for batch actions service."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_STAGE,
    ATTR_TARGET_GROWSPACE_ID,
    ATTR_TRANSITION_DATE,
)
from custom_components.growspace_manager.services.batch import handle_batch_action
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_hass() -> MagicMock:
    return MagicMock()


@pytest.fixture
def mock_coordinator() -> MagicMock:
    coord = MagicMock()
    coord.plant_manager = MagicMock()
    coord.plant_manager.transition_plant_stage = AsyncMock()
    coord.async_harvest_plant = AsyncMock()
    coord.async_remove_plant = AsyncMock()
    return coord


@pytest.mark.asyncio
async def test_batch_transition(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test batch transition action."""
    call = MagicMock()
    call.data = {
        "entity_ids": ["plant1", "plant2"],
        "action": "transition",
        "data": {ATTR_STAGE: "flower", ATTR_TRANSITION_DATE: "2023-01-01"},
    }

    await handle_batch_action(mock_hass, mock_coordinator, call)

    assert mock_coordinator.plant_manager.transition_plant_stage.call_count == 2
    mock_coordinator.plant_manager.transition_plant_stage.assert_any_call(
        plant_id="plant1", new_stage="flower", transition_date="2023-01-01"
    )
    mock_coordinator.plant_manager.transition_plant_stage.assert_any_call(
        plant_id="plant2", new_stage="flower", transition_date="2023-01-01"
    )


@pytest.mark.asyncio
async def test_batch_harvest(mock_hass: MagicMock, mock_coordinator: MagicMock) -> None:
    """Test batch harvest action."""
    call = MagicMock()
    call.data = {
        "entity_ids": ["plant1"],
        "action": "harvest",
        "data": {ATTR_TARGET_GROWSPACE_ID: "drying_room"},
    }

    await handle_batch_action(mock_hass, mock_coordinator, call)

    mock_coordinator.async_harvest_plant.assert_called_once_with(
        plant_id="plant1",
        target_growspace_id="drying_room",
        target_growspace_name=None,
        transition_date=None,
    )


@pytest.mark.asyncio
async def test_batch_remove(mock_hass: MagicMock, mock_coordinator: MagicMock) -> None:
    """Test batch remove action."""
    call = MagicMock()
    call.data = {"entity_ids": ["plant1", "plant2"], "action": "remove"}

    await handle_batch_action(mock_hass, mock_coordinator, call)

    assert mock_coordinator.async_remove_plant.call_count == 2
    mock_coordinator.async_remove_plant.assert_any_call(plant_id="plant1")
    mock_coordinator.async_remove_plant.assert_any_call(plant_id="plant2")


@pytest.mark.asyncio
async def test_batch_error_handling(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test that one failure does not stop the batch."""
    # First call fails, second succeeds
    mock_coordinator.async_remove_plant.side_effect = [Exception("Test Error"), None]

    call = MagicMock()
    call.data = {"entity_ids": ["plant1", "plant2"], "action": "remove"}

    # Implementation logs error and raises ServiceValidationError at the end.
    with pytest.raises(ServiceValidationError):
        await handle_batch_action(mock_hass, mock_coordinator, call)

    assert mock_coordinator.async_remove_plant.call_count == 2


@pytest.mark.asyncio
async def test_unknown_action(
    mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test unknown action is handled."""
    call = MagicMock()
    call.data = {"entity_ids": ["plant1"], "action": "unknown_action"}

    # Should raise ServiceValidationError
    with pytest.raises(ServiceValidationError):
        await handle_batch_action(mock_hass, mock_coordinator, call)

    # Should result in no coordinator calls
    mock_coordinator.plant_manager.transition_plant_stage.assert_not_called()
    mock_coordinator.async_harvest_plant.assert_not_called()
    mock_coordinator.async_remove_plant.assert_not_called()
