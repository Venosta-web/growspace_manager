"""Tests for plant lifecycle service handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    ATTR_NEW_STAGE,
    ATTR_PLANT_ID,
    ATTR_WET_WEIGHT,
)
from custom_components.growspace_manager.services.plant_lifecycle import (
    handle_harvest_plant,
    handle_transition_plant_stage,
)
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def coordinator() -> MagicMock:
    mock = MagicMock()
    mock.plants = {}
    mock.services = MagicMock()
    mock.services.plants.transition_plant_stage = AsyncMock()
    mock.services.plants.transition_plant = AsyncMock()
    return mock


@pytest.mark.asyncio
async def test_transition_plant_stage_delegates_to_facade(coordinator: MagicMock) -> None:
    """Handler passes plant_id and new_stage to the facade."""
    coordinator.plants["p1"] = MagicMock()
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p1", ATTR_NEW_STAGE: "flower"}

    await handle_transition_plant_stage(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.transition_plant_stage.assert_awaited_once_with(
        plant_id="p1",
        new_stage="flower",
        transition_date=None,
    )


@pytest.mark.asyncio
async def test_transition_plant_stage_raises_when_plant_missing(coordinator: MagicMock) -> None:
    """Handler raises ServiceValidationError when plant_id is not in coordinator."""
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "ghost", ATTR_NEW_STAGE: "flower"}

    with pytest.raises(ServiceValidationError, match="ghost does not exist"):
        await handle_transition_plant_stage(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.transition_plant_stage.assert_not_awaited()


@pytest.mark.asyncio
async def test_harvest_plant_delegates_to_facade(coordinator: MagicMock) -> None:
    """Harvest handler passes plant_id and metrics to the facade."""
    coordinator.plants["p2"] = MagicMock()
    call = MagicMock()
    call.data = {ATTR_PLANT_ID: "p2", ATTR_WET_WEIGHT: 55.0}

    with patch(
        "custom_components.growspace_manager.services.plant_lifecycle._ensure_plant_loaded",
        new_callable=AsyncMock,
        return_value=True,
    ):
        result = await handle_harvest_plant(MagicMock(), coordinator, MagicMock(), call)

    coordinator.services.plants.transition_plant.assert_awaited_once()
    call_kwargs = coordinator.services.plants.transition_plant.call_args.kwargs
    assert call_kwargs["plant_id"] == "p2"
    assert call_kwargs["wet_weight"] == 55.0
    assert result[ATTR_PLANT_ID] == "p2"


@pytest.mark.asyncio
async def test_harvest_plant_raises_when_plant_id_missing(coordinator: MagicMock) -> None:
    """Harvest handler raises when plant_id field is absent from call data."""
    call = MagicMock()
    call.data = {}

    with pytest.raises(ServiceValidationError, match="Missing plant_id"):
        await handle_harvest_plant(MagicMock(), coordinator, MagicMock(), call)
