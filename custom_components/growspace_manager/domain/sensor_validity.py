"""Whether a control input's reading can be trusted right now (#789).

A reading is usable only while it is **available** (a number), **plausible**
(inside the quantity's physical range) and **fresh** (reported within its
validity window). An invalid reading is ``None`` with the reason and the moment
it stopped being trustworthy — it never becomes 0, which would look like an
empty tank or a bone-dry substrate and drive an actuator.

Freshness reads ``last_reported``, which Home Assistant moves on every report,
including one that repeats the previous value, so a steady sensor that is still
speaking is never stale; only one that has stopped is.

Pure: the shell hands in the raw state string and its timestamps. Only the tank
slice exists so far (#790); the moisture, pore-EC and climate inputs extend this
module rather than growing a second one.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import math


class Invalidity(StrEnum):
    """Why a reading cannot be trusted."""

    UNAVAILABLE = "unavailable"
    STALE = "stale"
    IMPLAUSIBLE = "implausible"


@dataclass(frozen=True, slots=True)
class PlausibleRange:
    """The inclusive physical range of one quantity."""

    low: float
    high: float

    def contains(self, value: float) -> bool:
        """Return whether ``value`` is a finite number inside the range."""
        return math.isfinite(value) and self.low <= value <= self.high


TANK_LEVEL_RANGE = PlausibleRange(0.0, 100.0)


@dataclass(frozen=True, slots=True)
class SensorReading:
    """A validated reading: a value, or why there is none and since when.

    ``invalid_since`` is None for a valid reading, and for an entity that does
    not exist, whose invalidity has no date of its own.
    """

    value: float | None
    invalidity: Invalidity | None
    invalid_since: datetime | None

    @property
    def valid(self) -> bool:
        """Return whether the reading can be acted on."""
        return self.invalidity is None


def parse_numeric_state(raw: str | None) -> float | None:
    """Parse a state string into a number, or None when it is not one.

    Accepts a trailing ``%`` and a decimal comma, as tank sensors have been seen
    to report. ``nan`` and ``inf`` parse, so the plausibility check can name
    them rather than calling them unavailable.
    """
    if not raw:
        return None
    try:
        return float(raw.replace("%", "").strip().replace(",", "."))
    except ValueError:
        return None


def validate_reading(
    raw: str | None,
    *,
    changed_at: datetime | None,
    reported_at: datetime | None,
    now: datetime,
    max_age: timedelta,
    plausible: PlausibleRange,
) -> SensorReading:
    """Validate one raw state against availability, plausibility and age.

    ``raw`` is ``None`` when the entity does not exist. An unavailable or
    implausible reading is invalid from ``changed_at``, when the state took that
    value — undated for an entity that does not exist, which the caller dates;
    a stale one from the moment its window ran out. Implausible outranks stale,
    since it says more about what is wrong.
    """
    value = parse_numeric_state(raw)
    if value is None:
        return SensorReading(None, Invalidity.UNAVAILABLE, changed_at)
    if not plausible.contains(value):
        return SensorReading(None, Invalidity.IMPLAUSIBLE, changed_at)
    if reported_at is not None and now - reported_at > max_age:
        return SensorReading(None, Invalidity.STALE, reported_at + max_age)
    return SensorReading(value, None, None)
