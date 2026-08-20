"""Unit tests for the Pump Cycle Gate (ADR-0021).

These tests are pure: they build an ``IrrigationConfig`` and plain
``TankReading``s, then assert the ``CycleVerdict``. No Home Assistant instance,
coordinator, or sensor is involved — the gate's interface is the test surface.
They pin the skip/fire precedence, the irrigation-vs-drain split, the
manual-bypasses-dark rule, and the exact logbook message text.
"""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.domain.pump_cycle import (
    CycleVerdict,
    SkipReason,
    TankReading,
    cycle_volume_liters,
    decide_cycle,
    first_low_tank,
    safety_cap_blocks,
)
from custom_components.growspace_manager.models import IrrigationConfig


def _config(**overrides: object) -> IrrigationConfig:
    """Build an IrrigationConfig with permissive defaults, overriding fields."""
    config = IrrigationConfig()
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


def _decide(config: IrrigationConfig, **overrides: object) -> CycleVerdict:
    """Call decide_cycle with sensible all-clear defaults, overriding kwargs."""
    kwargs: dict[str, object] = {
        "event_type": "irrigation",
        "is_manual": False,
        "config": config,
        "tank_readings": [],
        "lights_dark": False,
        "cycles_today": 0,
        "volume_today": 0.0,
        "cycle_volume_l": 0.0,
    }
    kwargs.update(overrides)
    return decide_cycle(**kwargs)  # type: ignore[arg-type]


# --- cycle_volume_liters -----------------------------------------------------


@pytest.mark.parametrize(
    ("flow_rate", "duration", "expected"),
    [
        (0.0, 30, 0.0),  # no flow rate configured -> disables volume cap
        (100.0, 30, 3.0),  # 100 ml/s * 30 s = 3000 ml = 3.0 L
        (50.0, 10, 0.5),
    ],
)
def test_cycle_volume_liters(flow_rate: float, duration: int, expected: float) -> None:
    """Cycle volume is runtime * flow rate, zero when unconfigured."""
    config = _config(pump_flow_rate_ml_per_sec=flow_rate)
    assert cycle_volume_liters(config, duration) == expected


# --- first_low_tank ----------------------------------------------------------


def test_first_low_tank_none_when_all_above() -> None:
    """No tank below its warning level returns None."""
    readings = [
        TankReading("A", level=50.0, warning_level=30.0),
        TankReading("B", level=40.0, warning_level=30.0),
    ]
    assert first_low_tank(readings) is None


def test_first_low_tank_returns_first_below_in_order() -> None:
    """The first below-warning tank in list order is returned."""
    readings = [
        TankReading("A", level=50.0, warning_level=30.0),
        TankReading("B", level=10.0, warning_level=30.0),
        TankReading("C", level=5.0, warning_level=30.0),
    ]
    assert first_low_tank(readings) == TankReading("B", 10.0, 30.0)


# --- safety_cap_blocks -------------------------------------------------------


def test_safety_cap_blocks_under_limits() -> None:
    """No cap or limit configured -> None."""
    assert (
        safety_cap_blocks(
            _config(), cycles_today=5, volume_today=10.0, cycle_volume_l=1.0
        )
        is None
    )


def test_safety_cap_blocks_cycle_limit() -> None:
    """At or over the daily cycle limit -> CYCLE_LIMIT."""
    config = _config(max_cycles_per_day=2)
    assert (
        safety_cap_blocks(config, cycles_today=2, volume_today=0.0, cycle_volume_l=0.0)
        is SkipReason.CYCLE_LIMIT
    )


def test_safety_cap_blocks_volume_cap() -> None:
    """Adding the cycle volume would exceed the daily cap -> VOLUME_CAP."""
    config = _config(daily_volume_cap_liters=1.0)
    assert (
        safety_cap_blocks(config, cycles_today=0, volume_today=0.0, cycle_volume_l=3.0)
        is SkipReason.VOLUME_CAP
    )


def test_safety_cap_blocks_zero_volume_never_caps() -> None:
    """A zero cycle volume (no flow rate) never trips the volume cap."""
    config = _config(daily_volume_cap_liters=1.0)
    assert (
        safety_cap_blocks(config, cycles_today=0, volume_today=5.0, cycle_volume_l=0.0)
        is None
    )


# --- decide_cycle: precedence and the irrigation/drain split -----------------


def test_decide_all_clear_fires() -> None:
    """No blocking condition -> fire with no reason."""
    verdict = _decide(_config())
    assert verdict == CycleVerdict(fire=True)


def test_decide_low_tank_beats_caps() -> None:
    """Low tank is checked first, even when caps would also block."""
    config = _config(max_cycles_per_day=1)
    verdict = _decide(
        config,
        tank_readings=[TankReading("Res", level=5.0, warning_level=30.0)],
        cycles_today=5,
    )
    assert verdict.fire is False
    assert verdict.reason is SkipReason.LOW_TANK
    assert verdict.low_tank == TankReading("Res", 5.0, 30.0)
    assert verdict.message == "Irrigation skipped — tank 'Res' is low (5.0% < 30.0%)"


def test_decide_low_tank_ignored_when_pause_disabled() -> None:
    """pause_on_low_tank False -> a low tank does not block."""
    config = _config(pause_on_low_tank=False)
    verdict = _decide(config, tank_readings=[TankReading("Res", 5.0, 30.0)])
    assert verdict.fire is True


def test_decide_drain_ignores_caps_and_dark() -> None:
    """A drain cycle only honours low tank, never cap/limit/dark."""
    config = _config(max_cycles_per_day=1, skip_during_dark=True)
    verdict = _decide(config, event_type="drain", cycles_today=5, lights_dark=True)
    assert verdict.fire is True


def test_decide_drain_still_honours_low_tank() -> None:
    """Low tank blocks a drain cycle too, with a 'Drain skipped' message."""
    verdict = _decide(
        _config(),
        event_type="drain",
        tank_readings=[TankReading("Res", 5.0, 30.0)],
    )
    assert verdict.reason is SkipReason.LOW_TANK
    assert verdict.message == "Drain skipped — tank 'Res' is low (5.0% < 30.0%)"


def test_decide_cycle_limit_message() -> None:
    """Cycle limit produces CYCLE_LIMIT with the count in the message."""
    verdict = _decide(_config(max_cycles_per_day=2), cycles_today=2)
    assert verdict.reason is SkipReason.CYCLE_LIMIT
    assert verdict.message == "Irrigation skipped — Daily cycle limit reached (2/2)"


def test_decide_volume_cap_message() -> None:
    """Volume cap produces VOLUME_CAP with the volume math in the message."""
    verdict = _decide(
        _config(daily_volume_cap_liters=1.0), volume_today=0.0, cycle_volume_l=3.0
    )
    assert verdict.reason is SkipReason.VOLUME_CAP
    assert verdict.message == (
        "Irrigation skipped — Daily volume cap would be exceeded "
        "(0.000L + 3.000L > 1.0L cap)"
    )


def test_decide_dark_blocks_scheduled() -> None:
    """A scheduled cycle during the dark period is skipped."""
    verdict = _decide(_config(skip_during_dark=True), lights_dark=True, is_manual=False)
    assert verdict.reason is SkipReason.DARK
    assert (
        verdict.message == "Irrigation skipped — lights are currently off (dark period)"
    )


def test_decide_dark_bypassed_by_manual() -> None:
    """A manual run fires even during the dark period."""
    verdict = _decide(_config(skip_during_dark=True), lights_dark=True, is_manual=True)
    assert verdict.fire is True


def test_decide_dark_ignored_when_skip_disabled() -> None:
    """skip_during_dark False -> darkness does not block."""
    verdict = _decide(_config(skip_during_dark=False), lights_dark=True)
    assert verdict.fire is True
