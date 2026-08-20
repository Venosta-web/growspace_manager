"""Tests for the pure grow-light schedule helpers."""

from datetime import date, datetime
from types import SimpleNamespace

import pytest

from custom_components.growspace_manager.domain.light_schedule import (
    desired_grow_light_power,
    resolve_cycle_end_time,
    resolve_photoperiod_hours,
)

_TODAY = date(2026, 7, 3)


def _plant(flower_start: str | None) -> SimpleNamespace:
    """A minimal plant stub exposing only ``flower_start``."""
    return SimpleNamespace(flower_start=flower_start)


def test_power_is_full_inside_window_and_zero_outside() -> None:
    """Inside the photoperiod the light holds its power; outside it is off."""
    # lights on 06:00, 18h photoperiod -> window [06:00, 24:00)
    inside = datetime(2026, 7, 3, 12, 0, 0)
    outside = datetime(2026, 7, 3, 2, 0, 0)

    assert desired_grow_light_power(inside, "06:00:00", 18, 80) == 80
    assert desired_grow_light_power(outside, "06:00:00", 18, 80) == 0


def test_window_wrapping_past_midnight() -> None:
    """A photoperiod that crosses midnight stays on into the next morning."""
    # lights on 20:00, 18h -> window wraps to 14:00 next day
    after_start = datetime(2026, 7, 3, 22, 0, 0)
    after_midnight = datetime(2026, 7, 4, 2, 0, 0)
    in_dark_gap = datetime(2026, 7, 3, 16, 0, 0)

    assert desired_grow_light_power(after_start, "20:00:00", 18, 90) == 90
    assert desired_grow_light_power(after_midnight, "20:00:00", 18, 90) == 90
    assert desired_grow_light_power(in_dark_gap, "20:00:00", 18, 90) == 0


@pytest.mark.parametrize(
    ("plants", "expected"),
    [
        ([], 18),  # no plants -> veg
        ([_plant(None), _plant(None)], 18),  # all vegetative -> veg
        ([_plant(None), _plant("2026-07-01")], 12),  # one entered flower -> flower
        ([_plant("2026-07-03")], 12),  # entered flower today -> flower
        ([_plant("2026-07-10")], 18),  # flower start in the future -> still veg
    ],
)
def test_photoperiod_hours_follow_entered_flower(
    plants: list[SimpleNamespace], expected: int
) -> None:
    """Day length drops to flower hours once any plant has entered flower."""
    assert resolve_photoperiod_hours(plants, 18, 12, _TODAY) == expected


@pytest.mark.parametrize(
    ("lights_on", "hours", "expected_end"),
    [
        ("06:00:00", 12, "18:00:00"),
        ("06:00:00", 18, "00:00:00"),  # ends exactly at midnight
        ("20:00:00", 18, "14:00:00"),  # wraps past midnight
        ("06:30:00", 11.5, "18:00:00"),  # fractional hours
    ],
)
def test_resolve_cycle_end_time(lights_on: str, hours: float, expected_end: str) -> None:
    """Cycle end is lights-on plus the photoperiod, wrapping across midnight."""
    assert resolve_cycle_end_time(lights_on, hours) == expected_end


@pytest.mark.parametrize(
    ("on_time", "off_time", "now", "expected"),
    [
        ("06:00:00", "18:00:00", datetime(2026, 7, 3, 12, 0), True),  # midday lit
        ("06:00:00", "18:00:00", datetime(2026, 7, 3, 20, 0), False),  # post-cutoff
        ("06:00:00", "18:00:00", datetime(2026, 7, 3, 3, 0), False),  # pre-dawn
        ("20:00:00", "14:00:00", datetime(2026, 7, 3, 22, 0), True),  # wrap, after on
        ("20:00:00", "14:00:00", datetime(2026, 7, 4, 2, 0), True),  # wrap, after midnight
        ("20:00:00", "14:00:00", datetime(2026, 7, 3, 16, 0), False),  # wrap, in gap
    ],
)
def test_is_within_window(
    on_time: str, off_time: str, now: datetime, expected: bool
) -> None:
    """A held on/off schedule reports whether the light is lit at ``now``."""
    from custom_components.growspace_manager.domain.light_schedule import (
        is_within_window,
    )

    assert is_within_window(now, on_time, off_time) is expected
