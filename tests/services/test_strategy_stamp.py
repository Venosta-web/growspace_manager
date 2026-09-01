"""Tests for the shared Strategy Stamp write-and-record seam (ADR-0012)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import SteeringMode
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.services.strategy_stamp import (
    StrategyStamp,
    async_apply_strategy_stamp,
)


def _make_coordinator(growspace_id: str = "tent1") -> MagicMock:
    growspace = Growspace(id=growspace_id, name="Test Tent")
    coordinator = MagicMock()
    coordinator.growspaces = {growspace_id: growspace}
    coordinator.cache = MagicMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.hass = MagicMock()
    return coordinator


@pytest.mark.asyncio
async def test_stamp_writes_values_and_records_provenance() -> None:
    """Both halves land on the strategy: the setpoints and what stamped them."""
    coordinator = _make_coordinator()

    await async_apply_strategy_stamp(
        coordinator,
        "tent1",
        StrategyStamp(
            values={"maintenance_dryback_percent": 5.0, "p2_shot_interval_minutes": 60},
            records={"declared_steering_mode": SteeringMode.GENERATIVE},
        ),
    )

    strategy = coordinator.growspaces["tent1"].irrigation_strategy
    assert strategy.maintenance_dryback_percent == 5.0
    assert strategy.p2_shot_interval_minutes == 60
    assert strategy.declared_steering_mode == SteeringMode.GENERATIVE


@pytest.mark.asyncio
async def test_stamp_always_writes_over_hand_tweaks() -> None:
    """Re-stamping the same values is a reset, never a skipped no-op."""
    coordinator = _make_coordinator()
    stamp = StrategyStamp(values={"maintenance_dryback_percent": 5.0})
    await async_apply_strategy_stamp(coordinator, "tent1", stamp)
    strategy = coordinator.growspaces["tent1"].irrigation_strategy
    strategy.maintenance_dryback_percent = 99.0

    await async_apply_strategy_stamp(coordinator, "tent1", stamp)

    assert strategy.maintenance_dryback_percent == 5.0


@pytest.mark.asyncio
async def test_stamp_invalidates_commits_and_refreshes() -> None:
    """The effects half runs in full: cache, store, then a refresh."""
    coordinator = _make_coordinator()

    await async_apply_strategy_stamp(
        coordinator, "tent1", StrategyStamp(values={"p0_duration_minutes": 45})
    )

    coordinator.cache.invalidate.assert_called_once_with("tent1")
    coordinator.async_commit.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_stamp_writes_the_logbook_message() -> None:
    """A stamp carrying a message fires exactly one growspace log entry."""
    coordinator = _make_coordinator()

    await async_apply_strategy_stamp(
        coordinator,
        "tent1",
        StrategyStamp(values={}, logbook_message="Applied balanced steering mode"),
    )

    coordinator.hass.bus.async_fire.assert_called_once()
    _event, data = coordinator.hass.bus.async_fire.call_args.args
    assert data["message"] == "Applied balanced steering mode"
    assert data["category"] == "irrigation"


@pytest.mark.asyncio
async def test_stamp_respects_the_logbook_opt_out() -> None:
    """A growspace with logbook entries disabled gets the write but no entry."""
    coordinator = _make_coordinator()
    coordinator.growspaces["tent1"].irrigation_config.log_to_logbook = False

    await async_apply_strategy_stamp(
        coordinator,
        "tent1",
        StrategyStamp(
            values={"p0_duration_minutes": 45}, logbook_message="Applied something"
        ),
    )

    coordinator.hass.bus.async_fire.assert_not_called()
    assert coordinator.growspaces["tent1"].irrigation_strategy.p0_duration_minutes == 45


@pytest.mark.asyncio
async def test_stamp_without_a_message_writes_no_entry() -> None:
    """Not every stamp source narrates itself; None means no logbook entry."""
    coordinator = _make_coordinator()

    await async_apply_strategy_stamp(
        coordinator, "tent1", StrategyStamp(values={"p0_duration_minutes": 45})
    )

    coordinator.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_stamp_unknown_growspace_raises() -> None:
    """An unknown growspace is refused before anything is written."""
    coordinator = _make_coordinator()

    with pytest.raises(GrowspaceNotFoundError):
        await async_apply_strategy_stamp(
            coordinator, "nope", StrategyStamp(values={"p0_duration_minutes": 45})
        )

    coordinator.async_commit.assert_not_awaited()


def test_stamp_snapshots_its_mappings() -> None:
    """The resolved mappings are copied, so a caller's dict cannot mutate later."""
    values = {"maintenance_dryback_percent": 5.0}
    stamp = StrategyStamp(values=values)
    values["maintenance_dryback_percent"] = 99.0

    assert stamp.values["maintenance_dryback_percent"] == 5.0
