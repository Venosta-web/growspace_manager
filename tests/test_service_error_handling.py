"""Tests for service error handling wrapper."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.growspace_manager.const import (
    ATTR_AMOUNT,
    ATTR_COL,
    ATTR_GROWSPACE_ID,
    ATTR_ROW,
    ATTR_STRAIN,
)
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.irrigation_watering import (
    handle_water_growspace,
    handle_water_plant,
)
from custom_components.growspace_manager.services.plant import (
    handle_add_plant,
    handle_add_plants,
)


@pytest.fixture
def mock_coordinator():
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock()}  # Basic existence
    coordinator.plants = {"p1": MagicMock()}
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_water_plant = AsyncMock()
    coordinator.async_water_growspace = AsyncMock()
    coordinator.validator.find_first_available_position = MagicMock(return_value=(1, 1))
    return coordinator


@pytest.fixture
def mock_strain_library():
    return MagicMock()


async def test_handle_add_plant_wraps_error(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_add_plant wraps generic exceptions."""
    # Setup - simulate generic exception
    mock_coordinator.async_add_plant.side_effect = Exception("Boom")

    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "gs1",
        ATTR_STRAIN: "OG Kush",
        ATTR_ROW: 1,
        ATTR_COL: 1,
    }

    with pytest.raises(ServiceValidationError, match="Failed to add plant: Boom"):
        await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)


async def test_handle_add_plants_wraps_error(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
) -> None:
    """Test handle_add_plants wraps generic exceptions."""
    # Setup - simulate exception
    mock_coordinator.async_add_plant.side_effect = Exception("Boom Batch")
    # Need to mock find_first_available_position to prevent early exit
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)

    call = MagicMock()
    call.data = {
        ATTR_GROWSPACE_ID: "gs1",
        ATTR_STRAIN: "OG Kush",
        ATTR_AMOUNT: 3,
    }

    with pytest.raises(
        ServiceValidationError, match="Failed to batch add plants: Boom Batch"
    ):
        await handle_add_plants(hass, mock_coordinator, mock_strain_library, call)


async def test_handle_water_plant_wraps_growspace_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test handle_water_plant wraps GrowspaceError."""
    # Setup
    mock_coordinator.async_water_plant.side_effect = GrowspaceError("Not Found")

    call = MagicMock()
    call.data = {"plant_id": "p1", "amount": 1.0}

    with pytest.raises(ServiceValidationError, match="Not Found"):
        await handle_water_plant(hass, mock_coordinator, call)


async def test_handle_water_plant_wraps_generic_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test handle_water_plant wraps generic exceptions."""
    # Setup
    mock_coordinator.async_water_plant.side_effect = Exception("Pump Failure")

    call = MagicMock()
    call.data = {"plant_id": "p1", "amount": 1.0}

    with pytest.raises(
        ServiceValidationError, match="Failed to water plant: Pump Failure"
    ):
        await handle_water_plant(hass, mock_coordinator, call)


async def test_handle_water_growspace_wraps_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test handle_water_growspace wraps exceptions."""
    # Setup
    mock_coordinator.async_water_growspace.side_effect = Exception("Valve Error")

    call = MagicMock()
    call.data = {"growspace_id": "gs1", "amount_per_plant": 1.0}

    with pytest.raises(
        ServiceValidationError, match="Failed to water growspace: Valve Error"
    ):
        await handle_water_growspace(hass, mock_coordinator, call)
