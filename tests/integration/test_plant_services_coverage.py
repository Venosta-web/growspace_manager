"""Test plant services coverage."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, PropertyMock, patch

import pytest

from custom_components.growspace_manager.const import (
    ATTR_NOTES,
    ATTR_PLANT_ID,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.plant_facade import PlantFacade
from custom_components.growspace_manager.services.plant_lifecycle import (
    handle_harvest_plant,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError


async def test_handle_add_timeline_note_service_call() -> None:
    """Test handle_add_timeline_note delegates to facade."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.add_timeline_note = AsyncMock()
    strain_library = MagicMock()

    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {
        ATTR_PLANT_ID: "plant1", 
        ATTR_NOTES: "Service call note"
    }

    with patch(
        "custom_components.growspace_manager.services.plant_facade._ensure_plant_loaded"
    ), patch(
        "custom_components.growspace_manager.services.plant_facade._resolve_plant_id",
        return_value="plant1",
    ):
        await PlantFacade(coordinator).add_timeline_note_from_call(
            hass, strain_library, mock_call
        )
        
    coordinator.services.add_timeline_note.assert_awaited_once_with(
        plant_id="plant1",
        notes="Service call note",
        timestamp=None,
        images_base64=[],
        tags=[],
        ph=None,
        ec=None,
        amount_ml=None,
        external_metadata={},
    )


@pytest.mark.asyncio
async def test_handle_add_plants_success() -> None:
    """Test handle_add_plants service."""
    hass = MagicMock()
    mock_coordinator = MagicMock()
    mock_coordinator.services = MagicMock()
    mock_coordinator.services.plants.add_plant = AsyncMock()
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)

    mock_strain_library = MagicMock()

    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {
        "growspace_id": "gs1",
        "strain": "Strain A",
        "amount": 2,
        "start_number": 10,
    }

    facade = PlantFacade(mock_coordinator)
    facade.add_plant = mock_coordinator.services.plants.add_plant
    await facade.add_plants_from_call(hass, mock_strain_library, mock_call)

    assert mock_coordinator.services.plants.add_plant.call_count == 2
    # Check that phenotype uses start_number
    args = mock_coordinator.services.plants.add_plant.call_args_list[0].kwargs
    assert args["phenotype"] == "Strain A #10"





@pytest.mark.asyncio
async def test_handle_harvest_plant_not_loaded() -> None:
    """Test handle_harvest_plant when plant is not loaded."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.services = MagicMock()
    coordinator.services.plants.transition_plant = AsyncMock()
    coordinator.async_load = AsyncMock()
    strain_library = MagicMock()

    # Empty plants dict
    coordinator.plants = {}

    call = MagicMock(spec=ServiceCall)
    call.data = {ATTR_PLANT_ID: "plant1"}

    with pytest.raises(ServiceValidationError, match=".*not found and could not be reloaded.*"):
        await handle_harvest_plant(hass, coordinator, strain_library, call)


@pytest.mark.asyncio
async def test_handle_add_plants_errors() -> None:
    """Test handle_add_plants error paths."""
    hass = MagicMock()
    mock_coordinator = MagicMock()
    mock_coordinator.services = MagicMock()
    mock_coordinator.services.plants.add_plant = AsyncMock()
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)

    mock_call = MagicMock(spec=ServiceCall)

    facade = PlantFacade(mock_coordinator)
    facade.add_plant = mock_coordinator.services.plants.add_plant

    # 1. Growspace not found (245-246)
    mock_call.data = {"growspace_id": "missing", "strain": "S1", "amount": 1}
    with pytest.raises(ServiceValidationError, match=".*does not exist.*"):
        await facade.add_plants_from_call(hass, MagicMock(), mock_call)

    # 2. GrowspaceError during add (297-299)
    mock_call.data = {"growspace_id": "gs1", "strain": "S1", "amount": 2}
    mock_coordinator.services.plants.add_plant = AsyncMock(
        side_effect=GrowspaceError("Fail")
    )
    facade.add_plant = mock_coordinator.services.plants.add_plant
    await facade.add_plants_from_call(hass, MagicMock(), mock_call)
    assert (
        mock_coordinator.services.plants.add_plant.call_count == 1
    )  # Stopped after first error

    # 3. Unexpected exception (308-310)
    mock_coordinator.validator.find_first_available_position.side_effect = Exception(
        "Boom"
    )
    with pytest.raises(ServiceValidationError, match="Failed to batch add plants"):
        await facade.add_plants_from_call(hass, MagicMock(), mock_call)


@pytest.mark.asyncio
async def test_handle_add_plants_full() -> None:
    """Test handle_add_plants when growspace is full (276-284)."""
    hass = MagicMock()
    mock_coordinator = MagicMock()
    mock_coordinator.services = MagicMock()
    mock_coordinator.services.plants.add_plant = AsyncMock()
    mock_coordinator.growspaces = {"gs1": MagicMock()}
    mock_call = MagicMock(spec=ServiceCall)
    mock_call.data = {"growspace_id": "gs1", "strain": "S1", "amount": 2}

    facade = PlantFacade(mock_coordinator)
    facade.add_plant = mock_coordinator.services.plants.add_plant

    # Case: Full from the start (282)
    mock_coordinator.validator.find_first_available_position.return_value = (None, None)
    with pytest.raises(ServiceValidationError, match=".*is full.*"):
        await facade.add_plants_from_call(hass, MagicMock(), mock_call)

    # Case: Becomes full during batch (284)
    # 1. find_first_available_position (initial check)
    # 2. find_first_available_position (first plant)
    # 3. find_first_available_position (second plant - returns None)
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (0, 0),
        (0, 0),
        (None, None),
    ]
    await facade.add_plants_from_call(hass, MagicMock(), mock_call)
    assert mock_coordinator.services.plants.add_plant.call_count == 1
