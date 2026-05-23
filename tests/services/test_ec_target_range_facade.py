"""Tests for ECTargetRange upsert behavior in GrowspaceFacade and view model round-trip."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import (
    ECTargetRange,
    Growspace,
    IrrigationConfig,
)
from custom_components.growspace_manager.services.growspace_facade import (
    GrowspaceFacade,
)


def _make_coordinator(growspace_id: str = "tent1") -> MagicMock:
    """Build a minimal coordinator mock with one growspace."""
    growspace = Growspace(
        id=growspace_id,
        name="Test Tent",
    )
    coordinator = MagicMock()
    coordinator.growspaces = {growspace_id: growspace}
    coordinator.cache = MagicMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


@pytest.mark.asyncio
async def test_set_ec_target_range_new_stage() -> None:
    """Setting a range for a stage that has no entry yet appends it."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    await facade.set_ec_target_range(
        growspace_id="tent1",
        stage="veg",
        feed_ec_min=1.2,
        feed_ec_max=1.8,
    )

    ranges = coordinator.growspaces["tent1"].irrigation_config.ec_target_ranges
    assert len(ranges) == 1
    assert ranges[0].stage == "veg"
    assert ranges[0].feed_ec_min == 1.2
    assert ranges[0].feed_ec_max == 1.8


@pytest.mark.asyncio
async def test_set_ec_target_range_updates_existing_stage() -> None:
    """Setting a range for an existing stage updates in-place without duplication."""
    coordinator = _make_coordinator()
    growspace = coordinator.growspaces["tent1"]
    growspace.irrigation_config.ec_target_ranges.append(
        ECTargetRange(stage="veg", feed_ec_min=1.0, feed_ec_max=1.5)
    )
    facade = GrowspaceFacade(coordinator)

    await facade.set_ec_target_range(
        growspace_id="tent1",
        stage="veg",
        feed_ec_min=1.4,
        feed_ec_max=2.0,
    )

    ranges = growspace.irrigation_config.ec_target_ranges
    assert len(ranges) == 1
    assert ranges[0].feed_ec_min == 1.4
    assert ranges[0].feed_ec_max == 2.0


@pytest.mark.asyncio
async def test_set_ec_target_range_persists() -> None:
    """set_ec_target_range commits and requests a refresh."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    await facade.set_ec_target_range("tent1", "flower", 1.8, 2.4)

    coordinator.async_commit.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


def test_view_model_ec_target_ranges_serialization() -> None:
    """ec_target_ranges is serialized correctly as a list of dicts."""
    irrigation_config = IrrigationConfig(
        ec_target_ranges=[
            ECTargetRange(stage="veg", feed_ec_min=1.2, feed_ec_max=1.8),
            ECTargetRange(stage="flower", feed_ec_min=2.0, feed_ec_max=2.6),
        ]
    )

    serialized = [
        {
            "stage": r.stage,
            "feed_ec_min": r.feed_ec_min,
            "feed_ec_max": r.feed_ec_max,
        }
        for r in irrigation_config.ec_target_ranges
    ]

    assert len(serialized) == 2
    assert serialized[0] == {"stage": "veg", "feed_ec_min": 1.2, "feed_ec_max": 1.8}
    assert serialized[1] == {"stage": "flower", "feed_ec_min": 2.0, "feed_ec_max": 2.6}


@pytest.mark.asyncio
async def test_round_trip_set_then_read() -> None:
    """Set a range via facade, read it back from the model — values match."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    await facade.set_ec_target_range("tent1", "veg", 1.2, 1.8)
    await facade.set_ec_target_range("tent1", "flower", 2.0, 2.6)

    ranges = coordinator.growspaces["tent1"].irrigation_config.ec_target_ranges
    assert len(ranges) == 2
    veg_range = next(r for r in ranges if r.stage == "veg")
    flower_range = next(r for r in ranges if r.stage == "flower")
    assert veg_range.feed_ec_min == 1.2
    assert veg_range.feed_ec_max == 1.8
    assert flower_range.feed_ec_min == 2.0
    assert flower_range.feed_ec_max == 2.6
