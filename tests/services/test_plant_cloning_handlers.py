"""Tests for plant cloning service handlers."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_MOTHER_PLANT_ID,
    ATTR_NUM_CLONES,
    ATTR_PLANT_ID,
    ATTR_TARGET_GROWSPACE_ID,
)
from custom_components.growspace_manager.services.plant_cloning import (
    handle_move_clone,
    handle_take_clone,
)
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def coordinator() -> MagicMock:
    mock = MagicMock()
    mock.plants = {}
    mock.services = MagicMock()
    mock.services.plants.take_clones = AsyncMock(return_value=[MagicMock(), MagicMock()])
    mock.services.plants.promote_clone = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_take_clone_delegates_to_facade(coordinator: MagicMock) -> None:
    """Handler passes mother_plant_id, num_clones, and target_growspace_id to the facade."""
    coordinator.plants["mother1"] = MagicMock()
    call = MagicMock()
    call.data = {
        ATTR_MOTHER_PLANT_ID: "mother1",
        ATTR_NUM_CLONES: 2,
        ATTR_TARGET_GROWSPACE_ID: "clone_gs",
    }

    await handle_take_clone(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.take_clones.assert_awaited_once()
    call_kwargs = coordinator.services.plants.take_clones.call_args.kwargs
    assert call_kwargs["mother_plant_id"] == "mother1"
    assert call_kwargs["num_clones"] == 2
    assert call_kwargs["target_growspace_id"] == "clone_gs"


@pytest.mark.asyncio
async def test_take_clone_raises_when_mother_missing(coordinator: MagicMock) -> None:
    """Handler raises when the mother plant is not in coordinator."""
    call = MagicMock()
    call.data = {ATTR_MOTHER_PLANT_ID: "ghost_mother", ATTR_NUM_CLONES: 1}

    with pytest.raises(ServiceValidationError, match="ghost_mother not found"):
        await handle_take_clone(MagicMock(), coordinator, MagicMock(), call)


@pytest.mark.asyncio
async def test_take_clone_raises_when_num_clones_not_positive(coordinator: MagicMock) -> None:
    """Handler rejects non-positive num_clones before touching the coordinator."""
    coordinator.plants["m1"] = MagicMock()
    call = MagicMock()
    call.data = {ATTR_MOTHER_PLANT_ID: "m1", ATTR_NUM_CLONES: 0}

    with pytest.raises(ServiceValidationError, match="must be positive"):
        await handle_take_clone(MagicMock(), coordinator, MagicMock(), call)


@pytest.mark.asyncio
async def test_move_clone_delegates_to_facade(coordinator: MagicMock) -> None:
    """Handler passes clone_id and target_growspace_id to promote_clone."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "clone1", ATTR_TARGET_GROWSPACE_ID: "veg_gs"}

    await handle_move_clone(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.promote_clone.assert_awaited_once()
    call_kwargs = coordinator.services.plants.promote_clone.call_args.kwargs
    assert call_kwargs["clone_id"] == "clone1"
    assert call_kwargs["target_growspace_id"] == "veg_gs"


@pytest.mark.asyncio
async def test_move_clone_raises_when_ids_missing(coordinator: MagicMock) -> None:
    """Handler raises when plant_id or target_growspace_id is absent."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "clone1"}

    with pytest.raises(ServiceValidationError, match="Missing plant_id or target_growspace_id"):
        await handle_move_clone(MagicMock(), coordinator, MagicMock(), call)
