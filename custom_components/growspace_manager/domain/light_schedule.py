"""Pure helpers for the schedule-driven grow-light controller.

These functions map a wall-clock time and a photoperiod onto the grow light's
desired demand. They are free of Home Assistant and coordinator dependencies so
they can be unit-tested in isolation and reused by any control path.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Protocol


class HasFlowerStart(Protocol):
    """Anything that carries a Lifecycle Timestamp for entering flower."""

    flower_start: str | None


def flower_start_date(flower_start: str | None) -> date | None:
    """Return the calendar day of a ``flower_start``, or ``None`` if unusable.

    ``flower_start`` is a Lifecycle Timestamp — stored as a full ISO datetime
    (ADR-0013) — but legacy date-only values are accepted too. The day is the
    one the timestamp was written in, i.e. its own offset's local date.
    """
    if not flower_start:
        return None
    try:
        return datetime.fromisoformat(flower_start).date()
    except ValueError:
        return None


def resolve_photoperiod_hours(
    plants: Iterable[HasFlowerStart],
    veg_hours: float,
    flower_hours: float,
    today: date,
) -> float:
    """Return the day length: ``flower_hours`` once any plant has entered flower.

    A plant has *entered* flower when its ``flower_start`` is set and on or
    before ``today`` — distinct from "flipped today". A missing or malformed
    ``flower_start`` counts as not-yet-flowering.
    """
    return flower_hours if has_entered_flower(plants, today) else veg_hours


def has_entered_flower(plants: Iterable[HasFlowerStart], today: date) -> bool:
    """Return whether any plant's ``flower_start`` is on or before ``today``."""
    for plant in plants:
        started = flower_start_date(plant.flower_start)
        if started is not None and started <= today:
            return True
    return False


def _minutes_since_midnight(value: str) -> int:
    """Parse an ``HH:MM[:SS]`` string into minutes since midnight."""
    hours, minutes, *_ = (int(part) for part in value.split(":"))
    return hours * 60 + minutes


def desired_grow_light_power(
    now: datetime,
    lights_on_time: str,
    photoperiod_hours: float,
    power: int,
) -> int:
    """Return ``power`` when ``now`` is inside the photoperiod, else ``0``."""
    start = _minutes_since_midnight(lights_on_time)
    window_minutes = round(photoperiod_hours * 60)
    now_min = now.hour * 60 + now.minute
    # Offset into the cycle from lights-on, wrapping across midnight.
    offset = (now_min - start) % (24 * 60)
    if offset < window_minutes:
        return power
    return 0


def is_dark_period(
    now: datetime, lights_on_time: str, photoperiod_hours: float
) -> bool:
    """Return whether ``now`` falls outside the photoperiod that starts at lights-on."""
    return desired_grow_light_power(now, lights_on_time, photoperiod_hours, 1) == 0


def resolve_cycle_end_time(lights_on_time: str, photoperiod_hours: float) -> str:
    """Return the lights-off wall-clock time as ``HH:MM:SS``, wrapping midnight."""
    start = _minutes_since_midnight(lights_on_time)
    end = (start + round(photoperiod_hours * 60)) % (24 * 60)
    return f"{end // 60:02d}:{end % 60:02d}:00"


def is_within_window(now: datetime, on_time: str, off_time: str) -> bool:
    """Return whether ``now`` falls inside the ``[on, off)`` window (wraps midnight)."""
    start = _minutes_since_midnight(on_time)
    end = _minutes_since_midnight(off_time)
    duration = (end - start) % (24 * 60) or (24 * 60)
    now_min = now.hour * 60 + now.minute
    return (now_min - start) % (24 * 60) < duration
