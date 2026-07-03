"""Pure helpers for the schedule-driven grow-light controller.

These functions map a wall-clock time and a photoperiod onto the grow light's
desired demand. They are free of Home Assistant and coordinator dependencies so
they can be unit-tested in isolation and reused by any control path.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import date, datetime
from typing import Protocol


class _HasFlowerStart(Protocol):
    flower_start: str | None


def resolve_photoperiod_hours(
    plants: Iterable[_HasFlowerStart],
    veg_hours: float,
    flower_hours: float,
    today: date,
) -> float:
    """Return the day length: ``flower_hours`` once any plant has entered flower.

    A plant has *entered* flower when its ``flower_start`` is set and on or
    before ``today`` — distinct from "flipped today". A missing or malformed
    ``flower_start`` counts as not-yet-flowering.
    """
    for plant in plants:
        if not plant.flower_start:
            continue
        try:
            if date.fromisoformat(plant.flower_start) <= today:
                return flower_hours
        except ValueError:
            continue
    return veg_hours


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
