"""Tests for the facade adapters onto the Irrigation Change seam (ADR-0046).

The seam's own behaviour is covered in ``test_irrigation_change.py``; what is
left here is that each named facade method reaches it as the operation the
grower asked for, and hands back the result describing what it did.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import ShotSizingMode, SteeringMode
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.growspace_facade import (
    GrowspaceFacade,
)
from custom_components.growspace_manager.services.irrigation_change import (
    IrrigationChangeOperation,
)


def _facade(growspace: Growspace) -> tuple[GrowspaceFacade, MagicMock]:
    coordinator = MagicMock()
    coordinator.growspaces = {growspace.id: growspace}
    coordinator.cache = MagicMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.hass = MagicMock()
    return GrowspaceFacade(coordinator), coordinator


@pytest.mark.asyncio
async def test_apply_steering_mode_stamps_through_the_seam() -> None:
    """The named mode reaches the strategy as preset values plus the intent."""
    growspace = Growspace(id="tent1", name="Test Tent")
    facade, _coordinator = _facade(growspace)

    result = await facade.apply_steering_mode("tent1", SteeringMode.GENERATIVE)

    strategy = growspace.irrigation_strategy
    assert strategy.declared_steering_mode is SteeringMode.GENERATIVE
    assert strategy.maintenance_dryback_percent == 5.0
    assert result.operation is IrrigationChangeOperation.STEERING_MODE


@pytest.mark.asyncio
async def test_apply_steering_mode_unknown_growspace_raises() -> None:
    """Stamping a missing growspace raises before anything is written."""
    growspace = Growspace(id="tent1", name="Test Tent")
    facade, coordinator = _facade(growspace)

    with pytest.raises(GrowspaceNotFoundError):
        await facade.apply_steering_mode("nope", SteeringMode.BALANCED)

    coordinator.async_commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_clear_irrigation_resets_through_the_seam() -> None:
    """The clear adapter resets the config and switches steering off."""
    growspace = Growspace(id="tent1", name="Test Tent")
    growspace.irrigation_config.irrigation_pump_entity = "switch.pump"
    growspace.irrigation_strategy.enabled = True
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.VOLUME
    facade, _coordinator = _facade(growspace)

    result = await facade.clear_irrigation("tent1")

    assert growspace.irrigation_config.irrigation_pump_entity is None
    assert growspace.irrigation_strategy.enabled is False
    assert result.operation is IrrigationChangeOperation.CLEAR
    assert "irrigation_pump_entity" in result.changed_config_fields


@pytest.mark.asyncio
async def test_clear_irrigation_unknown_growspace_raises() -> None:
    """Clearing a missing growspace raises before anything is written."""
    growspace = Growspace(id="tent1", name="Test Tent")
    facade, coordinator = _facade(growspace)

    with pytest.raises(GrowspaceNotFoundError):
        await facade.clear_irrigation("nope")

    coordinator.async_commit.assert_not_awaited()
