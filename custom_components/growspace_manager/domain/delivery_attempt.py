"""Delivery Attempts and the Dispensed Volume the daily caps enforce.

A Delivery Attempt is one request for a pump cycle recorded under one stable
identity (ADR-0055). Today's charges across a growspace's attempts are its
Dispensed Volume: the pump starts and litres the daily cycle limit and daily
volume cap are enforced on (ADR-0054). Deriving the caps from durable attempts,
rather than from a counter in memory, is what stops a restart from handing out
a fresh daily allowance (#787).

This module holds the records and the arithmetic, and is free of Home
Assistant. What it covers is the slice the caps need: an attempt is recorded
once its pump confirms ON, which is the moment it is charged, and closed as
``completed`` or ``aborted``. Suppressed requests, the write before the ON
command, closing an attempt a restart left open as ``interrupted``, and metered
evidence are the rest of ADR-0055 and are not recorded yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
import math
from typing import Any

#: How long raw attempts are kept (ADR-0055).
RETENTION = timedelta(days=7)

#: The fault a growspace is held under while its Delivery Attempts cannot be
#: read or written.
DELIVERY_RECORD_UNREADABLE = "delivery_record_unreadable"

#: The hard row limit. Only rows charged on another day are evicted for it,
#: because the caps are derived from today's.
ROW_LIMIT = 2000


class AttemptTrigger(StrEnum):
    """What asked for the cycle."""

    SCHEDULE = "schedule"
    STEERING = "steering"
    MANUAL = "manual"


class AttemptOutcome(StrEnum):
    """How an actuated attempt ended."""

    COMPLETED = "completed"
    ABORTED = "aborted"


@dataclass(frozen=True, slots=True)
class DispensedVolume:
    """What a growspace has been charged against its daily caps."""

    cycles: int = 0
    liters: float = 0.0


def attempt_trigger(event_data: Mapping[str, Any]) -> AttemptTrigger:
    """Classify a pump request from the event data its caller passed."""
    if event_data.get("manual"):
        return AttemptTrigger.MANUAL
    if "phase" in event_data:
        return AttemptTrigger.STEERING
    return AttemptTrigger.SCHEDULE


def _liters(seconds: float, flow_rate_ml_per_sec: float) -> float:
    return max(0.0, seconds) * flow_rate_ml_per_sec / 1000.0


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """One irrigation request, from the pump confirming ON to its close.

    ``charge_date`` is the local day the pump confirmed ON. The charge belongs
    to that day even when a top-up lands after midnight.
    """

    attempt_id: str
    growspace_id: str
    output: str
    trigger: AttemptTrigger
    planned_s: float
    # Snapshotted so a later configuration edit cannot rewrite the charge.
    flow_rate_ml_per_sec: float
    on_commanded_at: datetime
    on_confirmed_at: datetime
    charge_date: date
    charged_l: float
    outcome: AttemptOutcome | None = None
    abort_cause: str | None = None
    off_commanded_at: datetime | None = None
    off_confirmed_at: datetime | None = None
    estimated_l: float | None = None

    @classmethod
    def actuated(
        cls,
        *,
        attempt_id: str,
        growspace_id: str,
        output: str,
        trigger: AttemptTrigger,
        planned_s: float,
        flow_rate_ml_per_sec: float | None,
        on_commanded_at: datetime,
        on_confirmed_at: datetime,
        charge_date: date,
    ) -> DeliveryAttempt:
        """Return an attempt whose pump has confirmed ON, charged its plan."""
        flow = float(flow_rate_ml_per_sec or 0.0)
        return cls(
            attempt_id=attempt_id,
            growspace_id=growspace_id,
            output=output,
            trigger=trigger,
            planned_s=float(planned_s),
            flow_rate_ml_per_sec=flow,
            on_commanded_at=on_commanded_at,
            on_confirmed_at=on_confirmed_at,
            charge_date=charge_date,
            charged_l=_liters(planned_s, flow),
        )

    @property
    def is_open(self) -> bool:
        """Whether the attempt is still Actuated rather than Closed."""
        return self.outcome is None

    @property
    def off_confirmed(self) -> bool:
        """Whether OFF was read back when the attempt closed."""
        return self.off_confirmed_at is not None

    def closed(
        self,
        *,
        off_commanded_at: datetime,
        abort_cause: str | None = None,
    ) -> DeliveryAttempt:
        """Close the attempt on the pump's measured ON time.

        The estimate is the measured ON time. The charge keeps its plan and is
        only ever topped up, so an aborted shot costs the cap its whole plan and
        a late wake-up that overran it costs what really ran.
        """
        measured_s = (off_commanded_at - self.on_confirmed_at).total_seconds()
        estimated_l = _liters(measured_s, self.flow_rate_ml_per_sec)
        return replace(
            self,
            outcome=AttemptOutcome.ABORTED if abort_cause else AttemptOutcome.COMPLETED,
            abort_cause=abort_cause,
            off_commanded_at=off_commanded_at,
            estimated_l=estimated_l,
            charged_l=max(self.charged_l, estimated_l),
        )

    def read_back_off(self, at: datetime) -> DeliveryAttempt:
        """Record that the closed attempt's pump was read back OFF."""
        return replace(self, off_confirmed_at=at)

    def as_dict(self) -> dict[str, Any]:
        """Return the durable wire form."""
        return {
            "attempt_id": self.attempt_id,
            "growspace_id": self.growspace_id,
            "output": self.output,
            "trigger": self.trigger.value,
            "planned_s": self.planned_s,
            "flow_rate_ml_per_sec": self.flow_rate_ml_per_sec,
            "on_commanded_at": self.on_commanded_at.isoformat(),
            "on_confirmed_at": self.on_confirmed_at.isoformat(),
            "charge_date": self.charge_date.isoformat(),
            "charged_l": self.charged_l,
            "state": "actuated" if self.is_open else "closed",
            "outcome": self.outcome.value if self.outcome else None,
            "abort_cause": self.abort_cause,
            "off_commanded_at": _iso(self.off_commanded_at),
            "off_confirmed_at": _iso(self.off_confirmed_at),
            "estimated_l": self.estimated_l,
            "evidence": "estimated",
        }

    @classmethod
    def from_dict(cls, value: Any) -> DeliveryAttempt:
        """Refuse any record that is not whole; a malformed one fails closed."""
        if not isinstance(value, dict):
            raise TypeError("delivery attempt is not an object")
        for key in ("attempt_id", "growspace_id", "output"):
            if not isinstance(value.get(key), str) or not value[key]:
                raise ValueError(f"delivery attempt has no {key}")
        numbers = ("planned_s", "flow_rate_ml_per_sec", "charged_l")
        if any(not _is_amount(value.get(key)) for key in numbers):
            raise ValueError("delivery attempt has an invalid amount")
        estimated = value.get("estimated_l")
        if estimated is not None and not _is_amount(estimated):
            raise ValueError("delivery attempt has an invalid estimate")
        abort_cause = value.get("abort_cause")
        if abort_cause is not None and not isinstance(abort_cause, str):
            raise ValueError("delivery attempt has an invalid abort cause")
        outcome = value.get("outcome")
        attempt = cls(
            attempt_id=value["attempt_id"],
            growspace_id=value["growspace_id"],
            output=value["output"],
            trigger=AttemptTrigger(_text(value.get("trigger"))),
            planned_s=float(value["planned_s"]),
            flow_rate_ml_per_sec=float(value["flow_rate_ml_per_sec"]),
            on_commanded_at=_aware(value.get("on_commanded_at")),
            on_confirmed_at=_aware(value.get("on_confirmed_at")),
            charge_date=date.fromisoformat(_text(value.get("charge_date"))),
            charged_l=float(value["charged_l"]),
            outcome=AttemptOutcome(outcome) if outcome is not None else None,
            abort_cause=abort_cause,
            off_commanded_at=_optional_aware(value.get("off_commanded_at")),
            off_confirmed_at=_optional_aware(value.get("off_confirmed_at")),
            estimated_l=float(estimated) if estimated is not None else None,
        )
        if attempt.is_open != (value.get("state") == "actuated"):
            raise ValueError("delivery attempt state disagrees with its outcome")
        if attempt.charged_l < _liters(attempt.planned_s, attempt.flow_rate_ml_per_sec):
            raise ValueError("delivery attempt is charged less than its plan")
        return attempt


def dispensed_volume(attempts: Iterable[DeliveryAttempt], day: date) -> DispensedVolume:
    """Sum the charges dated ``day``: one cycle and its litres per attempt."""
    charged = [attempt.charged_l for attempt in attempts if attempt.charge_date == day]
    return DispensedVolume(cycles=len(charged), liters=sum(charged))


def retained(
    attempts: Iterable[DeliveryAttempt], *, now: datetime, today: date
) -> list[DeliveryAttempt]:
    """Drop attempts past retention, then the oldest over the row limit.

    Neither rule removes an attempt charged today: the caps are derived from
    them, so evicting one would hand the allowance back.
    """
    horizon = now - RETENTION
    kept = [
        attempt
        for attempt in attempts
        if attempt.charge_date == today or attempt.on_confirmed_at >= horizon
    ]
    excess = len(kept) - ROW_LIMIT
    if excess <= 0:
        return kept
    evictable = sorted(
        (attempt for attempt in kept if attempt.charge_date != today),
        key=lambda attempt: attempt.on_confirmed_at,
    )
    evicted = {attempt.attempt_id for attempt in evictable[:excess]}
    return [attempt for attempt in kept if attempt.attempt_id not in evicted]


def _is_amount(value: Any) -> bool:
    return (
        isinstance(value, int | float)
        and not isinstance(value, bool)
        and math.isfinite(value)
        and value >= 0
    )


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("delivery attempt has a missing field")
    return value


def _aware(value: Any) -> datetime:
    parsed = datetime.fromisoformat(_text(value))
    if parsed.tzinfo is None:
        raise ValueError("delivery attempt has a naive timestamp")
    return parsed


def _optional_aware(value: Any) -> datetime | None:
    return None if value is None else _aware(value)


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
