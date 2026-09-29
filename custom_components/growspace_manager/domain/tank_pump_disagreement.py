"""The Tank–Pump Disagreement: the calibration signal ADR-0054 asked for.

A growspace whose tank is measured (it has ``volume_liters``, so it qualifies
for Tank-Derived Water Mode) gets two independent answers to how much water left
the tank in a day: the tank's own drop, and the pump's Delivery Attempts. When
they part company, the usual cause is a wrong ``pump_flow_rate_ml_per_sec``, a
leak, or water drawn from the tank. A flow rate set too low leaves the daily cap
looser than the grower believes, so a lasting disagreement is surfaced, and is
never enforced (ADR-0064 item 9).

Each local day is judged once, after midnight. The tank side is the day's
consumption over every qualifying tank, less the Hand Watering reported as drawn
from a monitored tank. The pump side is the day's actuated attempts, metered
where they can be once metering exists and estimated from measured ON time
until then. A day **disagrees** when the gap is more than 25% of the larger
figure **and** more than 1 L. The signal is raised after 2 disagreeing days and
cleared after 2 agreeing ones. A day with no actuated attempt, or on which a
qualifying tank was at an Unknown Tank Level, counts neither way: it neither
advances a run nor breaks one.

The evidence is about one set of tanks and one configured flow rate. When
either changes, the comparison starts again from the next whole day: a tank
added at noon has only half a day's drop, and a day judged at the old rate says
nothing about the new one. That is also what lets an applied Calibration
Proposal close: the rate it wrote starts the comparison afresh.

Everything here is arithmetic over records the shell hands in. It reads no
sensor and touches no ``hass``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime, timedelta, tzinfo
from enum import StrEnum
import math
from typing import Any

from .delivery_attempt import DeliveryAttempt

#: A day disagrees when the gap is more than this share of the larger figure...
DISAGREEMENT_SHARE = 0.25
#: ...and more than this many litres, so a small tent's rounding never does.
DISAGREEMENT_FLOOR_L = 1.0
#: Disagreeing days in a row that raise the signal.
RAISE_AFTER_DAYS = 2
#: Agreeing days in a row that clear it.
CLEAR_AFTER_DAYS = 2
#: How many judged days are kept, and how far back a missed evaluation reaches.
#: A day older than this has lost attempts to their 7-day retention.
DAYS_KEPT = 6


class DayVerdict(StrEnum):
    """What one day said about the tank and the pump."""

    AGREES = "agrees"
    DISAGREES = "disagrees"
    NO_ATTEMPT = "no_attempt"
    TANK_UNKNOWN = "tank_unknown"


class DisagreementState(StrEnum):
    """Where the signal stands."""

    NO_TANK = "no_tank"
    CLEAR = "clear"
    RAISED = "raised"


class Transition(StrEnum):
    """A change the logbook records."""

    RAISED = "raised"
    CLEARED = "cleared"
    RESTARTED = "restarted"
    RATE_CHANGED = "rate_changed"


def disagrees(tank_l: float, pump_l: float) -> bool:
    """Whether the two figures are further apart than tank resolution explains."""
    gap = abs(tank_l - pump_l)
    return gap > DISAGREEMENT_SHARE * max(tank_l, pump_l) and gap > DISAGREEMENT_FLOOR_L


@dataclass(frozen=True, slots=True)
class DayComparison:
    """One local day's tank drop against the water its pump delivered."""

    day: date
    verdict: DayVerdict
    tank_drop_l: float
    hand_watering_l: float
    pump_l: float

    @property
    def tank_l(self) -> float:
        """The tank drop the pump has to answer for.

        Hand Watering reported as drawn from the tank left through a jug, not
        the pump. A report larger than the drop leaves nothing for the pump.
        """
        return max(0.0, self.tank_drop_l - self.hand_watering_l)

    @property
    def counts(self) -> bool:
        """Whether the day moves the signal at all."""
        return self.verdict in (DayVerdict.AGREES, DayVerdict.DISAGREES)

    def sentence(self, today: date) -> str:
        """Say what the day showed and what can cause it."""
        when = "yesterday" if self.day == today - timedelta(days=1) else self._on()
        tank = f"The tank dropped {self.tank_l:.1f} L {when}"
        if self.hand_watering_l:
            tank += f" beyond {self.hand_watering_l:.1f} L of Hand Watering from it"
        pump = f"the pump delivered {self.pump_l:.1f} L"
        if self.tank_l:
            share = round(abs(self.tank_l - self.pump_l) / self.tank_l * 100)
            pump += f" ({share}% {'less' if self.pump_l < self.tank_l else 'more'})"
        cause = (
            "A flow rate set too low, a leak, or water drawn from the tank"
            if self.pump_l < self.tank_l
            else "A flow rate set too high, a pump or line delivering less than it"
            " should, or water added to the tank"
        )
        return f"{tank}; {pump}. {cause} can cause this."

    def _on(self) -> str:
        return f"on {self.day.day} {self.day:%B}"

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and wire form."""
        return {
            "date": self.day.isoformat(),
            "verdict": self.verdict.value,
            "tank_drop_l": self.tank_drop_l,
            "hand_watering_l": self.hand_watering_l,
            "pump_l": self.pump_l,
        }

    @classmethod
    def from_dict(cls, value: Any) -> DayComparison:
        """Refuse a day that is not the shape it was written in."""
        if not isinstance(value, dict):
            raise TypeError("a judged day is not an object")
        figures = ("tank_drop_l", "hand_watering_l", "pump_l")
        if any(not _is_amount(value.get(name)) for name in figures):
            raise ValueError("a judged day has an invalid figure")
        return cls(
            day=_day(value.get("date")),
            verdict=DayVerdict(_text(value.get("verdict"))),
            tank_drop_l=float(value["tank_drop_l"]),
            hand_watering_l=float(value["hand_watering_l"]),
            pump_l=float(value["pump_l"]),
        )


def pump_delivered_l(
    attempts: Iterable[DeliveryAttempt], day: date
) -> tuple[float, bool]:
    """Return the litres the pump delivered on ``day``, and whether it ran at all.

    An attempt belongs to the day its pump confirmed ON, the day it is charged
    to. Its water is its estimate from measured ON time; a metered reading will
    replace that once flow meters exist (ADR-0064 item 8). A drain moves water
    out of the pots and is never counted, and an attempt still open has no
    estimate yet.
    """
    actuated = [
        attempt
        for attempt in attempts
        if attempt.charges and attempt.charge_date == day
    ]
    return sum(attempt.estimated_l or 0.0 for attempt in actuated), bool(actuated)


def tank_consumed_l(
    events: Iterable[Mapping[str, Any]], day: date, tz: tzinfo
) -> float:
    """Sum the tank consumption events stamped on ``day`` in ``tz``.

    ``events`` are the qualifying tanks' ``water_history.events``. An event
    without a readable timestamp is left out, as the tank charts leave it out,
    and one stamped without a zone was written in UTC.
    """
    total = 0.0
    for event in events:
        if event.get("event_type") != "consumption":
            continue
        try:
            stamped = datetime.fromisoformat(event["timestamp"])
        except KeyError, TypeError, ValueError:
            continue
        if stamped.tzinfo is None:
            stamped = stamped.replace(tzinfo=UTC)
        if stamped.astimezone(tz).date() == day:
            total += float(event.get("liters") or 0.0)
    return total


def hand_watered_from_tank_l(
    daily_readings: Iterable[Mapping[str, Any]], day: date
) -> float:
    """Sum the Hand Watering dated ``day`` that was drawn from a monitored tank."""
    return sum(
        float(reading.get("liters") or 0.0)
        for reading in daily_readings
        if reading.get("from_monitored_tank") and reading.get("date") == day.isoformat()
    )


def compare_day(
    day: date,
    *,
    tank_drop_l: float,
    hand_watering_l: float,
    pump_l: float,
    actuated: bool,
    tank_unknown: bool,
) -> DayComparison:
    """Judge one day, or say why it cannot be judged."""
    comparison = DayComparison(
        day=day,
        verdict=DayVerdict.AGREES,
        tank_drop_l=round(tank_drop_l, 2),
        hand_watering_l=round(hand_watering_l, 2),
        pump_l=round(pump_l, 2),
    )
    if not actuated:
        verdict = DayVerdict.NO_ATTEMPT
    elif tank_unknown:
        verdict = DayVerdict.TANK_UNKNOWN
    elif disagrees(max(0.0, tank_drop_l - hand_watering_l), pump_l):
        verdict = DayVerdict.DISAGREES
    else:
        return comparison
    return replace(comparison, verdict=verdict)


@dataclass(frozen=True, slots=True)
class TankPumpDisagreement:
    """The signal, and the evidence it stands on, for one growspace.

    ``tanks`` are the qualifying tanks the evidence is about; empty means there
    is nothing to compare. ``flow_rate_ml_per_sec`` is the configured rate the
    pump figures were estimated at. ``first_day`` is the first whole day watched
    for that set and rate. ``unknown_days`` are the days a qualifying tank was
    at an Unknown Tank Level. ``streak`` counts the counted days in a row pointing away from the
    current state: disagreeing ones while clear, agreeing ones while raised.
    """

    tanks: tuple[str, ...] = ()
    flow_rate_ml_per_sec: float | None = None
    first_day: date | None = None
    unknown_days: frozenset[date] = frozenset()
    evaluated_through: date | None = None
    raised_on: date | None = None
    streak: int = 0
    days: tuple[DayComparison, ...] = ()

    @property
    def state(self) -> DisagreementState:
        """No tank to compare, clear, or raised."""
        if not self.tanks:
            return DisagreementState.NO_TANK
        if self.raised_on is not None:
            return DisagreementState.RAISED
        return DisagreementState.CLEAR

    def watching(
        self, tanks: Iterable[str], today: date, *, flow_rate_ml_per_sec: float
    ) -> tuple[TankPumpDisagreement, Transition | None]:
        """Follow the qualifying tanks and the rate, starting afresh on a change.

        A new set or rate is compared from the next whole day. A raised signal
        about the old one is reported as restarted, not silently dropped. A
        record written before the rate was watched adopts the current one.
        """
        current = tuple(sorted(set(tanks)))
        if current == self.tanks:
            if self.flow_rate_ml_per_sec is None:
                return replace(self, flow_rate_ml_per_sec=flow_rate_ml_per_sec), None
            if self.flow_rate_ml_per_sec == flow_rate_ml_per_sec:
                return self, None
        fresh = TankPumpDisagreement(
            tanks=current,
            flow_rate_ml_per_sec=flow_rate_ml_per_sec,
            first_day=today + timedelta(days=1) if current else None,
        )
        if self.raised_on is None:
            return fresh, None
        if current != self.tanks:
            return fresh, Transition.RESTARTED
        return fresh, Transition.RATE_CHANGED

    def tank_unknown_on(self, day: date) -> TankPumpDisagreement:
        """Record that a qualifying tank was at an Unknown Tank Level on ``day``."""
        if not self.tanks or day in self.unknown_days:
            return self
        return replace(self, unknown_days=self.unknown_days | {day})

    def due_days(self, today: date) -> list[date]:
        """Return the whole days not yet judged, oldest first.

        Normally just yesterday. After a restart that slept through midnight,
        every missed day still inside the attempts' retention.
        """
        if self.first_day is None:
            return []
        start = max(self.first_day, today - timedelta(days=DAYS_KEPT))
        if self.evaluated_through is not None:
            start = max(start, self.evaluated_through + timedelta(days=1))
        return [
            start + timedelta(days=offset) for offset in range((today - start).days)
        ]

    def judged(
        self, comparison: DayComparison
    ) -> tuple[TankPumpDisagreement, Transition | None]:
        """Fold one judged day in, and say whether the signal moved."""
        state = replace(
            self,
            evaluated_through=comparison.day,
            days=(*self.days, comparison)[-DAYS_KEPT:],
            unknown_days=frozenset(
                day for day in self.unknown_days if day > comparison.day
            ),
        )
        if not comparison.counts:
            return state, None
        raised = self.raised_on is not None
        away = DayVerdict.AGREES if raised else DayVerdict.DISAGREES
        streak = self.streak + 1 if comparison.verdict is away else 0
        if raised and streak >= CLEAR_AFTER_DAYS:
            return replace(state, raised_on=None, streak=0), Transition.CLEARED
        if not raised and streak >= RAISE_AFTER_DAYS:
            return (
                replace(state, raised_on=comparison.day, streak=0),
                Transition.RAISED,
            )
        return replace(state, streak=streak), None

    def latest_disagreement(self) -> DayComparison | None:
        """Return the most recent disagreeing day kept, if any."""
        return next(
            (day for day in reversed(self.days) if day.verdict is DayVerdict.DISAGREES),
            None,
        )

    def message(self, transition: Transition, today: date) -> str:
        """Return the logbook line for a transition."""
        if transition is Transition.RESTARTED:
            return (
                "Tank–Pump Disagreement cleared: the growspace's measured tanks"
                " changed, so the comparison starts again."
            )
        if transition is Transition.RATE_CHANGED:
            return (
                "Tank–Pump Disagreement cleared: the pump flow rate changed, so the"
                " comparison starts again."
            )
        if transition is Transition.CLEARED:
            return (
                "Tank–Pump Disagreement cleared: the tank drop and the pump agreed"
                f" on {CLEAR_AFTER_DAYS} days in a row."
            )
        latest = self.latest_disagreement()
        detail = f" {latest.sentence(today)}" if latest is not None else ""
        return f"Tank–Pump Disagreement raised.{detail}"

    def view(self, today: date) -> dict[str, Any]:
        """Return the view model's ``calibration.tank_pump_disagreement``."""
        latest = self.latest_disagreement() if self.raised_on is not None else None
        return {
            "state": self.state.value,
            "raised_on": _iso(self.raised_on),
            "message": latest.sentence(today) if latest is not None else None,
            "days": [day.as_dict() for day in self.days],
        }

    def as_dict(self) -> dict[str, Any]:
        """Return the durable form."""
        return {
            "tanks": list(self.tanks),
            "flow_rate_ml_per_sec": self.flow_rate_ml_per_sec,
            "first_day": _iso(self.first_day),
            "unknown_days": sorted(day.isoformat() for day in self.unknown_days),
            "evaluated_through": _iso(self.evaluated_through),
            "raised_on": _iso(self.raised_on),
            "streak": self.streak,
            "days": [day.as_dict() for day in self.days],
        }

    @classmethod
    def from_dict(cls, value: Any) -> TankPumpDisagreement:
        """Refuse a record that is not whole."""
        if not isinstance(value, dict):
            raise TypeError("the Tank–Pump Disagreement is not an object")
        tanks = value.get("tanks")
        if not isinstance(tanks, list) or not all(
            isinstance(tank, str) and tank for tank in tanks
        ):
            raise ValueError("the Tank–Pump Disagreement has invalid tanks")
        rate = value.get("flow_rate_ml_per_sec")
        if rate is not None and not _is_amount(rate):
            raise ValueError("the Tank–Pump Disagreement has an invalid flow rate")
        streak = value.get("streak")
        if not isinstance(streak, int) or isinstance(streak, bool) or streak < 0:
            raise ValueError("the Tank–Pump Disagreement has an invalid streak")
        unknown = value.get("unknown_days")
        days = value.get("days")
        if not isinstance(unknown, list) or not isinstance(days, list):
            raise TypeError("the Tank–Pump Disagreement has invalid days")
        return cls(
            tanks=tuple(sorted(set(tanks))),
            flow_rate_ml_per_sec=float(rate) if rate is not None else None,
            first_day=_optional_day(value.get("first_day")),
            unknown_days=frozenset(_day(day) for day in unknown),
            evaluated_through=_optional_day(value.get("evaluated_through")),
            raised_on=_optional_day(value.get("raised_on")),
            streak=streak,
            days=tuple(DayComparison.from_dict(day) for day in days)[-DAYS_KEPT:],
        )


def qualifying_tanks(tanks: Sequence[Any]) -> list[Any]:
    """Return the tanks whose drop is in litres: those with ``volume_liters``."""
    return [tank for tank in tanks if tank.volume_liters is not None]


def _is_amount(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("a judged day has a missing field")
    return value


def _day(value: Any) -> date:
    return date.fromisoformat(_text(value))


def _optional_day(value: Any) -> date | None:
    return None if value is None else _day(value)


def _iso(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None
