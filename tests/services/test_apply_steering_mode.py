"""Tests for GrowspaceFacade.apply_steering_mode (the Steering Mode stamp, ADR-0012)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ShotSizingMode,
    SteeringMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import Growspace, SubstrateProfile
from custom_components.growspace_manager.services.growspace_facade import (
    GrowspaceFacade,
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
async def test_stamp_writes_volume_preset_into_explicit_fields() -> None:
    """Stamping generative in Volume Mode writes percent + agronomic fields."""
    coordinator = _make_coordinator()
    strategy = coordinator.growspaces["tent1"].irrigation_strategy
    strategy.shot_sizing_mode = ShotSizingMode.VOLUME
    strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.COCO, liters_per_pot=5.0
    )
    facade = GrowspaceFacade(coordinator)

    await facade.apply_steering_mode("tent1", SteeringMode.GENERATIVE)

    assert strategy.p2_shot_volume_percent == 4.0
    assert strategy.p2_shot_interval_minutes == 60
    assert strategy.maintenance_dryback_percent == 5.0
    assert strategy.p2_stop_before_lights_off_minutes == 210
    assert strategy.pore_ec_target_min == 4.0
    assert strategy.pore_ec_target_max == 6.5


@pytest.mark.asyncio
async def test_stamp_records_declared_intent() -> None:
    """Stamping persists the chosen mode as the declared intent."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    await facade.apply_steering_mode("tent1", SteeringMode.VEGETATIVE)

    strategy = coordinator.growspaces["tent1"].irrigation_strategy
    assert strategy.declared_steering_mode == SteeringMode.VEGETATIVE


@pytest.mark.asyncio
async def test_stamp_in_seconds_mode_writes_seconds_not_percent() -> None:
    """Seconds Mode stamp writes seconds; percent fields keep their value."""
    coordinator = _make_coordinator()
    strategy = coordinator.growspaces["tent1"].irrigation_strategy
    # Default sizing mode is SECONDS.
    strategy.p2_shot_volume_percent = 9.9  # sentinel that must NOT be overwritten
    facade = GrowspaceFacade(coordinator)

    await facade.apply_steering_mode("tent1", SteeringMode.GENERATIVE)

    assert strategy.p2_shot_duration_seconds == 12
    assert strategy.p2_shot_volume_percent == 9.9


@pytest.mark.asyncio
async def test_re_stamp_overwrites_hand_tweaks() -> None:
    """Re-selecting the same mode re-applies the preset, discarding edits."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)
    await facade.apply_steering_mode("tent1", SteeringMode.GENERATIVE)
    strategy = coordinator.growspaces["tent1"].irrigation_strategy
    strategy.maintenance_dryback_percent = 99.0  # grower hand-tweak

    await facade.apply_steering_mode("tent1", SteeringMode.GENERATIVE)

    assert strategy.maintenance_dryback_percent == 5.0


@pytest.mark.asyncio
async def test_stamp_uses_coco_when_profile_unset() -> None:
    """With no configured profile the stamp falls back to the coco column."""
    coordinator = _make_coordinator()
    strategy = coordinator.growspaces["tent1"].irrigation_strategy
    assert strategy.substrate_profile.is_configured is False
    facade = GrowspaceFacade(coordinator)

    await facade.apply_steering_mode("tent1", SteeringMode.GENERATIVE)

    # Coco generative dryback is 5.0 (rockwool would be 4.0, soil 3.0).
    assert strategy.maintenance_dryback_percent == 5.0


@pytest.mark.asyncio
async def test_stamp_commits_and_refreshes() -> None:
    """Stamping persists and requests a refresh."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    await facade.apply_steering_mode("tent1", SteeringMode.BALANCED)

    coordinator.async_commit.assert_awaited_once()
    coordinator.async_request_refresh.assert_awaited_once()


@pytest.mark.asyncio
async def test_stamp_unknown_growspace_raises() -> None:
    """Stamping a missing growspace raises GrowspaceNotFoundError."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    with pytest.raises(GrowspaceNotFoundError):
        await facade.apply_steering_mode("nope", SteeringMode.BALANCED)


@pytest.mark.asyncio
async def test_stamp_writes_logbook_entry() -> None:
    """Stamping fires one growspace log entry naming the mode and media."""
    coordinator = _make_coordinator()
    facade = GrowspaceFacade(coordinator)

    await facade.apply_steering_mode("tent1", SteeringMode.GENERATIVE)

    coordinator.hass.bus.async_fire.assert_called_once()
    _event, data = coordinator.hass.bus.async_fire.call_args.args
    assert "generative" in data["message"]
    assert "coco" in data["message"]
