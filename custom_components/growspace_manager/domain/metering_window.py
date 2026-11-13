"""Pure integration of flow readings over a Delivery Attempt (ADR-0064)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
import math
from typing import Literal

type MeterKind = Literal["cumulative_total", "rate"]

METERING_TAIL = timedelta(seconds=60)


class MeterAbsence(StrEnum):
    """Why a configured meter could not establish a volume."""

    STALE = "meter_stale"
    UNAVAILABLE = "meter_unavailable"


@dataclass(frozen=True, slots=True)
class MeterReading:
    """A report in litres or litres per second, or an unusable state."""

    at: datetime
    value: float | None


@dataclass(frozen=True, slots=True)
class MeteringWindow:
    """The supply readbacks and the optional next command that ends the tail."""

    on_confirmed_at: datetime
    off_confirmed_at: datetime | None
    next_on_commanded_at: datetime | None = None
    observed_at: datetime | None = None


def integrate_meter(
    kind: MeterKind, window: MeteringWindow, readings: Sequence[MeterReading]
) -> float | MeterAbsence:
    """Integrate chronological reports without inventing a missing reading."""
    start, off, cutoff = (
        window.on_confirmed_at,
        window.off_confirmed_at,
        window.next_on_commanded_at,
    )
    bounds = (
        off + METERING_TAIL if off is not None else None,
        cutoff,
        window.observed_at,
    )
    end = min((bound for bound in bounds if bound is not None), default=None)
    before = None
    inside = []
    for reading in readings:
        if reading.at < start:
            before = reading.value
        elif (end is None or reading.at <= end) and (
            cutoff is None or reading.at < cutoff
        ):
            if reading.value is None:
                return MeterAbsence.UNAVAILABLE
            inside.append((reading.at, reading.value))

    if off is None or end is None:
        return MeterAbsence.STALE
    if kind == "cumulative_total":
        if not inside or inside[-1][0] <= off or before is None:
            return MeterAbsence.STALE
        volume = 0.0
        for _, value in inside:
            volume += value - before if value >= before else value
            before = value
    else:
        if not inside or (before is None and inside[0][0] > start):
            return MeterAbsence.STALE
        cursor = start
        volume = 0.0
        rate = before if before is not None else inside[0][1]
        for at, value in inside:
            volume += rate * (at - cursor).total_seconds()
            cursor, rate = at, value
        volume += rate * (end - cursor).total_seconds()
    return volume if math.isfinite(volume) else MeterAbsence.UNAVAILABLE
