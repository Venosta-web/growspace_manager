"""Tests for the EC State seam (ADR-0015, issue #463).

The resolver is pure: every dependency is injected, so these drive it with a
plain ``IrrigationStrategy`` and a lambda pore-EC reader — no coordinator, no
Home Assistant.
"""

from collections.abc import Callable
from datetime import timedelta

import pytest

from custom_components.growspace_manager.domain.ec_state import (
    ECRecommendation,
    ECState,
    ECStateResolver,
    record_drain_reading,
    resolve_active_feed_ec,
    resolve_feed_stage_week,
)
from custom_components.growspace_manager.models import (
    DrainConfig,
    DrainReading,
    ECRampCurve,
    ECRampPoint,
    ECTargetRange,
    IrrigationStrategy,
    Plant,
)
from homeassistant.util import dt as dt_util


def _strategy(
    *,
    enabled: bool = True,
    band_min: float | None = 2.0,
    band_max: float | None = 3.0,
) -> IrrigationStrategy:
    """Return a strategy with the given pore-EC band and opt-in flag."""
    return IrrigationStrategy(
        ec_modulation_enabled=enabled,
        pore_ec_target_min=band_min,
        pore_ec_target_max=band_max,
    )


def _resolve(
    strategy: IrrigationStrategy, read_pore_ec: Callable[[], float | None]
) -> ECState:
    """Resolve an ECState for the given strategy and pore reader."""
    return ECStateResolver(strategy, read_pore_ec).resolve()


def test_modulation_disabled_is_unavailable() -> None:
    """Opt-in off → UNAVAILABLE and no pore reading carried, even with a band."""
    state = _resolve(_strategy(enabled=False), lambda: 5.0)
    assert state.recommendation is ECRecommendation.UNAVAILABLE
    assert state.pore_ec is None


@pytest.mark.parametrize(
    ("band_min", "band_max"),
    [(None, 3.0), (2.0, None), (None, None), (3.0, 3.0), (3.0, 2.0)],
)
def test_absent_or_inverted_band_is_unavailable(
    band_min: float | None, band_max: float | None
) -> None:
    """A missing or non-increasing band → UNAVAILABLE (graceful, no raise)."""
    state = _resolve(_strategy(band_min=band_min, band_max=band_max), lambda: 2.5)
    assert state.recommendation is ECRecommendation.UNAVAILABLE
    assert state.pore_ec is None


def test_no_pore_reading_is_unavailable() -> None:
    """Enabled with a valid band but no reading → UNAVAILABLE."""
    state = _resolve(_strategy(), lambda: None)
    assert state.recommendation is ECRecommendation.UNAVAILABLE
    assert state.pore_ec is None


@pytest.mark.parametrize(
    ("pore_ec", "expected"),
    [
        (1.0, ECRecommendation.STACK),  # below band
        (2.5, ECRecommendation.HOLD),  # within band
        (4.0, ECRecommendation.FLUSH),  # above band
        (2.0, ECRecommendation.HOLD),  # exactly at band_min → within (strict)
        (3.0, ECRecommendation.HOLD),  # exactly at band_max → within (strict)
    ],
)
def test_classification_against_band(
    pore_ec: float, expected: ECRecommendation
) -> None:
    """Direction matches the factor helper's strict above/within/below split."""
    state = _resolve(_strategy(), lambda: pore_ec)
    assert state.recommendation is expected
    assert state.pore_ec == pytest.approx(pore_ec)


def test_runoff_fields_default_absent() -> None:
    """Runoff fields (issue #465) default to absent."""
    state = _resolve(_strategy(), lambda: 2.5)
    assert state.runoff_ec is None
    assert state.feed_to_runoff_delta is None


# ── Active Feed EC Target (#464) ─────────────────────────────────────────────


def _plant(plant_id: str, **starts_days_ago: int) -> Plant:
    """Build a plant with the given stage starts set ``N`` days in the past."""
    fields = {
        field: (dt_util.now() - timedelta(days=days)).isoformat()
        for field, days in starts_days_ago.items()
    }
    return Plant(plant_id=plant_id, growspace_id="tent1", **fields)


def test_feed_stage_week_picks_furthest_along_live_stage() -> None:
    """A mixed veg+flower tent resolves to flower (the more advanced live stage)."""
    plants = [
        _plant("veg1", veg_start=10),
        _plant("flwr1", veg_start=40, flower_start=8),
    ]
    stage, week = resolve_feed_stage_week(plants)
    assert stage == "flower"
    assert week == 2  # 8 days in flower → week 2


def test_feed_stage_week_excludes_dry_and_cure() -> None:
    """Dry/cure plants are off the irrigation line and never drive the target."""
    plants = [
        _plant("veg1", veg_start=10),
        _plant("dry1", veg_start=60, flower_start=50, dry_start=3),
    ]
    stage, _ = resolve_feed_stage_week(plants)
    assert stage == "veg"


def test_feed_stage_week_no_live_plants_returns_none() -> None:
    """No plants (or only dry/cure) → no stage to resolve a target for."""
    assert resolve_feed_stage_week([]) == (None, 0)
    assert resolve_feed_stage_week([_plant("cure1", cure_start=2)]) == (None, 0)


def _curve(stage: str) -> ECRampCurve:
    """Two-point ramp curve for a stage: week 1 = 2.0–2.5, week 2 = 2.5–3.0."""
    return ECRampCurve(
        id=f"c_{stage}",
        stage=stage,
        points=[
            ECRampPoint(week=1, ec_min=2.0, ec_max=2.5),
            ECRampPoint(week=2, ec_min=2.5, ec_max=3.0),
        ],
    )


def test_active_feed_ec_ramp_curve_wins_over_range() -> None:
    """A matching ramp curve is preferred over a per-stage range."""
    ranges = [ECTargetRange(stage="flower", feed_ec_min=1.0, feed_ec_max=1.5)]
    band, source = resolve_active_feed_ec(
        "flower", 2, {"c_flower": _curve("flower")}, ranges
    )
    assert band == (2.5, 3.0)
    assert source == "ramp_curve"


def test_active_feed_ec_week_beyond_last_point_holds_last() -> None:
    """Past the last defined ramp week, the final point holds."""
    band, source = resolve_active_feed_ec(
        "flower", 9, {"c_flower": _curve("flower")}, []
    )
    assert band == (2.5, 3.0)
    assert source == "ramp_curve"


def test_active_feed_ec_falls_back_to_stage_range() -> None:
    """No ramp curve for the stage → the per-stage range supplies the target."""
    ranges = [ECTargetRange(stage="veg", feed_ec_min=1.2, feed_ec_max=1.8)]
    band, source = resolve_active_feed_ec("veg", 1, {}, ranges)
    assert band == (1.2, 1.8)
    assert source == "stage_range"


@pytest.mark.parametrize(
    ("stage", "curves", "ranges"),
    [
        (None, {}, []),  # no live stage
        ("flower", {}, []),  # nothing configured for the stage
    ],
)
def test_active_feed_ec_unresolved_is_none(
    stage: str | None,
    curves: dict[str, ECRampCurve],
    ranges: list[ECTargetRange],
) -> None:
    """An unknown stage or no configured target → graceful (None, 'none')."""
    assert resolve_active_feed_ec(stage, 1, curves, ranges) == (None, "none")


def test_resolver_carries_feed_target_even_when_modulation_unavailable() -> None:
    """Feed EC is display data: present even with modulation opted out."""
    state = ECStateResolver(
        _strategy(enabled=False),
        lambda: 5.0,
        lambda: ((2.0, 3.0), "ramp_curve"),
    ).resolve()
    assert state.recommendation is ECRecommendation.UNAVAILABLE
    assert state.active_feed_ec == (2.0, 3.0)
    assert state.feed_ec_source == "ramp_curve"


# ── Runoff measurements + drain recording (#465) ─────────────────────────────


def test_resolver_populates_runoff_from_latest_reading() -> None:
    """runoff_ec and feed_to_runoff_delta come from the latest drain reading."""
    reading = DrainReading(timestamp="t", feed_ec=1.5, drain_ec=2.7)
    state = ECStateResolver(
        _strategy(), lambda: 2.5, read_drain=lambda: reading
    ).resolve()
    assert state.runoff_ec == pytest.approx(2.7)
    assert state.feed_to_runoff_delta == pytest.approx(1.2)


def test_resolver_runoff_none_without_reading() -> None:
    """No drain reading → runoff fields stay None (graceful absence)."""
    state = ECStateResolver(_strategy(), lambda: 2.5).resolve()
    assert state.runoff_ec is None
    assert state.feed_to_runoff_delta is None


def test_record_drain_reading_appends_and_flags_alert() -> None:
    """A reading is recorded and the over-threshold alert is flagged."""
    drain_config = DrainConfig(enabled=True, max_ec_delta=0.5)
    record = record_drain_reading(drain_config, feed_ec=1.0, drain_ec=2.0)
    assert len(drain_config.readings) == 1
    assert drain_config.readings[-1].drain_ec == pytest.approx(2.0)
    assert record.ec_delta == pytest.approx(1.0)
    assert record.alert is True


@pytest.mark.parametrize(
    ("enabled", "max_ec_delta", "drain_ec"),
    [
        (False, 0.5, 2.0),  # monitoring disabled → no alert (still recorded)
        (True, 1.0, 1.5),  # delta 0.5 below threshold 1.0 → no alert
    ],
)
def test_record_drain_reading_no_alert(
    enabled: bool, max_ec_delta: float, drain_ec: float
) -> None:
    """The reading is always recorded; alert only when enabled and over delta."""
    drain_config = DrainConfig(enabled=enabled, max_ec_delta=max_ec_delta)
    record = record_drain_reading(drain_config, feed_ec=1.0, drain_ec=drain_ec)
    assert len(drain_config.readings) == 1
    assert record.alert is False


def test_record_drain_reading_enforces_rolling_window() -> None:
    """The rolling window trims to max_readings, keeping the newest."""
    drain_config = DrainConfig(max_readings=3)
    for i in range(5):
        record_drain_reading(drain_config, feed_ec=1.0, drain_ec=1.0 + i)
    assert len(drain_config.readings) == 3
    assert drain_config.readings[-1].drain_ec == pytest.approx(5.0)  # newest kept
