"""Tests for plant spatial service handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_NEW_COL,
    ATTR_NEW_ROW,
    ATTR_PLANT1_ID,
    ATTR_PLANT2_ID,
    ATTR_PLANT_ID,
)
from custom_components.growspace_manager.services.plant_spatial import (
    handle_move_plant,
    handle_switch_plants,
)
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def coordinator() -> MagicMock:
    mock = MagicMock()
    mock.plants = {}
    mock.services = MagicMock()
    mock.services.plants.switch_plants = AsyncMock()
    mock.services.plants.move_plant = AsyncMock()
    mock.services.growspaces.get_growspace_plants = MagicMock(return_value=[])
    return mock


@pytest.mark.asyncio
async def test_switch_plants_delegates_to_facade(coordinator: MagicMock) -> None:
    """Handler calls switch_plants with both plant IDs."""
    coordinator.plants = {"p1": MagicMock(), "p2": MagicMock()}
    call = MagicMock()
    call.data = {ATTR_PLANT1_ID: "p1", ATTR_PLANT2_ID: "p2"}

    await handle_switch_plants(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.switch_plants.assert_awaited_once_with("p1", "p2")


@pytest.mark.asyncio
async def test_switch_plants_raises_when_plant1_missing(coordinator: MagicMock) -> None:
    """Handler raises when first plant is not in coordinator."""
    coordinator.plants = {"p2": MagicMock()}
    call = MagicMock()
    call.data = {ATTR_PLANT1_ID: "ghost", ATTR_PLANT2_ID: "p2"}

    with pytest.raises(ServiceValidationError, match="ghost does not exist"):
        await handle_switch_plants(MagicMock(), coordinator, MagicMock(), call)


@pytest.mark.asyncio
async def test_switch_plants_raises_when_plant2_missing(coordinator: MagicMock) -> None:
    """Handler raises when second plant is not in coordinator."""
    coordinator.plants = {"p1": MagicMock()}
    call = MagicMock()
    call.data = {ATTR_PLANT1_ID: "p1", ATTR_PLANT2_ID: "ghost"}

    with pytest.raises(ServiceValidationError, match="ghost does not exist"):
        await handle_switch_plants(MagicMock(), coordinator, MagicMock(), call)


@pytest.mark.asyncio
async def test_move_plant_to_empty_position_delegates_move(coordinator: MagicMock) -> None:
    """When target position is empty, calls move_plant on the facade."""
    plant = MagicMock(row=1, col=1, growspace_id="gs1", strain="Test")
    coordinator.plants = {"p1": plant}
    coordinator.services.growspaces.get_growspace_plants.return_value = [plant]
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p1", ATTR_NEW_ROW: 2, ATTR_NEW_COL: 3}

    await handle_move_plant(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.move_plant.assert_awaited_once_with("p1", 2, 3)
    coordinator.services.plants.switch_plants.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_plant_to_occupied_position_switches(coordinator: MagicMock) -> None:
    """When target position is occupied, calls switch_plants instead of move_plant."""
    plant1 = MagicMock(plant_id="p1", row=1, col=1, growspace_id="gs1", strain="A")
    plant2 = MagicMock(plant_id="p2", row=2, col=3, growspace_id="gs1", strain="B")
    coordinator.plants = {"p1": plant1, "p2": plant2}
    coordinator.services.growspaces.get_growspace_plants.return_value = [plant1, plant2]
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p1", ATTR_NEW_ROW: 2, ATTR_NEW_COL: 3}

    await handle_move_plant(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.switch_plants.assert_awaited_once_with("p1", "p2")
    coordinator.services.plants.move_plant.assert_not_awaited()


@pytest.mark.asyncio
async def test_move_plant_raises_when_plant_missing(coordinator: MagicMock) -> None:
    """Handler raises when the plant to move is not in coordinator."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "ghost", ATTR_NEW_ROW: 1, ATTR_NEW_COL: 1}

    with pytest.raises(ServiceValidationError, match="ghost does not exist"):
        await handle_move_plant(MagicMock(), coordinator, MagicMock(), call)
