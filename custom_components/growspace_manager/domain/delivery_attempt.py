"""Delivery Attempts and the Dispensed Volume the daily caps enforce.

A Delivery Attempt is one request for a pump cycle that reached the Pump Cycle
Gate, recorded under one stable identity from the request to its close
(ADR-0055). Today's charges across a growspace's attempts are its Dispensed
Volume: the pump starts and litres the daily cycle limit and daily volume cap
are enforced on (ADR-0054). Deriving the caps from durable attempts, rather
than from a counter in memory, is what stops a restart from handing out a fresh
daily allowance (#787).

An attempt moves **Requested → Actuated → Closed**. It is requested once the
gate passes, actuated (and charged) when its pump confirms ON, and closed as
``completed`` or ``aborted``. A request the gate or an operator hold refuses is
closed ``suppressed`` without ever reaching the pump, and a run of those with
one reason is one row. A request that was never confirmed ON closes
``not_delivered``, or ``aborted`` when something stopped it first, and charges
nothing. One a stopped process left open is closed ``interrupted`` by the next
start, keeping whatever confirm-ON charged.

This module holds the records and the arithmetic, and is free of Home
Assistant. Drain attempts, the ``not_delivered`` window and metered evidence
are the rest of ADR-0055 and are not recorded yet.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
import math
from typing import Any

#: How long raw attempts are kept (ADR-0055).
RETENTION = timedelta(days=7)

#: The fault a growspace is held under while its Delivery Attempts cannot be
#: read or written.
DELIVERY_RECORD_UNREADABLE = "delivery_record_unreadable"

#: The hard row limit. Only rows not charged today are evicted for it, because
#: the caps are derived from today's.
ROW_LIMIT = 2000


class AttemptTrigger(StrEnum):
    """What asked for the cycle."""

    SCHEDULE = "schedule"
    STEERING = "steering"
    MANUAL = "manual"


class AttemptState(StrEnum):
    """Where an attempt is in its lifecycle."""

    REQUESTED = "requested"
    ACTUATED = "actuated"
    CLOSED = "closed"


class AttemptOutcome(StrEnum):
    """How an attempt ended."""

    SUPPRESSED = "suppressed"
    NOT_DELIVERED = "not_delivered"
    COMPLETED = "completed"
    ABORTED = "aborted"
    INTERRUPTED = "interrupted"


@dataclass(frozen=True, slots=True)
class DispensedVolume:
    """What a growspace has been charged against its daily caps."""

    cycles: int = 0
    liters: float = 0.0


_EVIDENCE_TEXT = ("slot", "phase", "user_id")
_EVIDENCE_NUMBERS = ("vwc", "base_s", "vwc_factor", "ec_factor")


@dataclass(frozen=True, slots=True)
class TriggerEvidence:
    """Why the trigger asked, in the terms it decided on.

    A schedule names its ``slot``; a steering shot its ``phase``, the ``vwc``
    reading that triggered it, its ``base_s`` and the ``vwc_factor`` and
    ``ec_factor`` it was composed with; a manual run the HA ``user_id`` of the
    person who asked. Nothing else: a sensor series or a user name is left out
    on purpose (ADR-0055).
    """

    slot: str | None = None
    phase: str | None = None
    vwc: float | None = None
    base_s: float | None = None
    vwc_factor: float | None = None
    ec_factor: float | None = None
    user_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the fields the trigger supplied, and only those."""
        return {
            name: getattr(self, name)
            for name in (*_EVIDENCE_TEXT, *_EVIDENCE_NUMBERS)
            if getattr(self, name) is not None
        }

    @classmethod
    def from_dict(cls, value: Any) -> TriggerEvidence:
        """Refuse evidence that is not the shape it was written in."""
        if not isinstance(value, dict):
            raise TypeError("trigger evidence is not an object")
        if set(value) - {*_EVIDENCE_TEXT, *_EVIDENCE_NUMBERS}:
            raise ValueError("trigger evidence has an unknown field")
        if any(
            not isinstance(value[name], str) for name in _EVIDENCE_TEXT if name in value
        ):
            raise ValueError("trigger evidence has invalid text")
        if any(
            not _is_amount(value[name]) for name in _EVIDENCE_NUMBERS if name in value
        ):
            raise ValueError("trigger evidence has an invalid number")
        return cls(
            slot=value.get("slot"),
            phase=value.get("phase"),
            vwc=_optional_number(value.get("vwc")),
            base_s=_optional_number(value.get("base_s")),
            vwc_factor=_optional_number(value.get("vwc_factor")),
            ec_factor=_optional_number(value.get("ec_factor")),
            user_id=value.get("user_id"),
        )


def attempt_trigger(event_data: Mapping[str, Any]) -> AttemptTrigger:
    """Classify a pump request from the event data its caller passed."""
    if event_data.get("manual"):
        return AttemptTrigger.MANUAL
    if "phase" in event_data:
        return AttemptTrigger.STEERING
    return AttemptTrigger.SCHEDULE


def trigger_evidence(event_data: Mapping[str, Any]) -> TriggerEvidence:
    """Read the evidence its trigger kind records from a pump request."""
    trigger = attempt_trigger(event_data)
    if trigger is AttemptTrigger.MANUAL:
        return TriggerEvidence(user_id=_optional_text(event_data.get("user_id")))
    if trigger is AttemptTrigger.STEERING:
        return TriggerEvidence(
            phase=_optional_text(event_data.get("phase")),
            vwc=_optional_number(event_data.get("vwc")),
            base_s=_optional_number(event_data.get("base_seconds")),
            vwc_factor=_optional_number(event_data.get("vwc_factor")),
            ec_factor=_optional_number(event_data.get("ec_factor")),
        )
    return TriggerEvidence(slot=_optional_text(event_data.get("time")))


def _liters(seconds: float, flow_rate_ml_per_sec: float) -> float:
    return max(0.0, seconds) * flow_rate_ml_per_sec / 1000.0


@dataclass(frozen=True, slots=True)
class DeliveryAttempt:
    """One irrigation request, from reaching the gate to its close.

    ``charge_date`` is the local day the pump confirmed ON, and is set only
    then. The charge belongs to that day even when a top-up lands after
    midnight. A merged run of suppressions keeps its first request as
    ``requested_at`` and its last as ``last_requested_at``. ``ended_at`` is set
    only on an ``interrupted`` attempt: the end its evidence bounds it to.
    """

    attempt_id: str
    growspace_id: str
    output: str
    trigger: AttemptTrigger
    planned_s: float
    # Snapshotted so a later configuration edit cannot rewrite the charge.
    flow_rate_ml_per_sec: float
    requested_at: datetime
    trigger_evidence: TriggerEvidence = field(default_factory=TriggerEvidence)
    on_commanded_at: datetime | None = None
    on_confirmed_at: datetime | None = None
    charge_date: date | None = None
    charged_l: float = 0.0
    outcome: AttemptOutcome | None = None
    reason: str | None = None
    abort_cause: str | None = None
    off_commanded_at: datetime | None = None
    off_confirmed_at: datetime | None = None
    estimated_l: float | None = None
    suppressed_count: int = 0
    last_requested_at: datetime | None = None
    ended_at: datetime | None = None

    @classmethod
    def requested(
        cls,
        *,
        attempt_id: str,
        growspace_id: str,
        output: str,
        trigger: AttemptTrigger,
        trigger_evidence: TriggerEvidence | None = None,
        planned_s: float,
        flow_rate_ml_per_sec: float | None,
        requested_at: datetime,
    ) -> DeliveryAttempt:
        """Return an attempt the gate has passed, before its ON command."""
        return cls(
            attempt_id=attempt_id,
            growspace_id=growspace_id,
            output=output,
            trigger=trigger,
            trigger_evidence=trigger_evidence or TriggerEvidence(),
            planned_s=float(planned_s),
            flow_rate_ml_per_sec=float(flow_rate_ml_per_sec or 0.0),
            requested_at=requested_at,
        )

    @property
    def state(self) -> AttemptState:
        """Requested until the pump confirms ON, Actuated until it closes."""
        if self.outcome is not None:
            return AttemptState.CLOSED
        if self.on_confirmed_at is not None:
            return AttemptState.ACTUATED
        return AttemptState.REQUESTED

    @property
    def is_open(self) -> bool:
        """Whether the attempt has not closed yet."""
        return self.outcome is None

    @property
    def is_actuated(self) -> bool:
        """Whether its pump confirmed ON, which is what charges it."""
        return self.on_confirmed_at is not None

    @property
    def off_confirmed(self) -> bool:
        """Whether OFF was read back when the attempt closed."""
        return self.off_confirmed_at is not None

    @property
    def last_seen_at(self) -> datetime:
        """The latest moment this row describes, which retention ages it by."""
        moments = (
            self.requested_at,
            self.last_requested_at,
            self.on_confirmed_at,
            self.off_commanded_at,
            self.off_confirmed_at,
            self.ended_at,
        )
        return max(moment for moment in moments if moment is not None)

    def merges(self, suppressed: DeliveryAttempt) -> bool:
        """Whether ``suppressed`` continues this row's run of suppressions."""
        return (
            self.outcome is AttemptOutcome.SUPPRESSED
            and suppressed.outcome is AttemptOutcome.SUPPRESSED
            and self.output == suppressed.output
            and self.reason == suppressed.reason
            and self.trigger is suppressed.trigger
        )

    def merged(self, suppressed: DeliveryAttempt) -> DeliveryAttempt:
        """Count ``suppressed`` into this run, keeping the first request's identity."""
        if not self.merges(suppressed):
            raise ValueError("only a run of one output, trigger and reason merges")
        return replace(
            self,
            suppressed_count=self.suppressed_count + suppressed.suppressed_count,
            last_requested_at=suppressed.last_requested_at,
        )

    def refused(self, reason: str) -> DeliveryAttempt:
        """Close a request the gate or an operator hold refused, as ``suppressed``."""
        self._require(AttemptState.REQUESTED)
        if self.on_commanded_at is not None:
            raise ValueError("a request that reached the pump is not suppressed")
        return replace(
            self,
            outcome=AttemptOutcome.SUPPRESSED,
            reason=reason,
            suppressed_count=1,
            last_requested_at=self.requested_at,
        )

    def commanded(self, at: datetime) -> DeliveryAttempt:
        """Record the moment the ON command was sent."""
        self._require(AttemptState.REQUESTED)
        return replace(self, on_commanded_at=at)

    def confirmed_on(self, at: datetime, charge_date: date) -> DeliveryAttempt:
        """Return the attempt actuated, and charged its plan, at confirm-ON."""
        self._require(AttemptState.REQUESTED)
        return replace(
            self,
            on_confirmed_at=at,
            charge_date=charge_date,
            charged_l=_liters(self.planned_s, self.flow_rate_ml_per_sec),
        )

    def closed(
        self,
        *,
        off_commanded_at: datetime,
        abort_cause: str | None = None,
    ) -> DeliveryAttempt:
        """Close an actuated attempt on the pump's measured ON time.

        The estimate is the measured ON time. The charge keeps its plan and is
        only ever topped up, so an aborted shot costs the cap its whole plan and
        a late wake-up that overran it costs what really ran.
        """
        self._require(AttemptState.ACTUATED)
        confirmed = _required(self.on_confirmed_at)
        measured_s = (off_commanded_at - confirmed).total_seconds()
        estimated_l = _liters(measured_s, self.flow_rate_ml_per_sec)
        return replace(
            self,
            outcome=AttemptOutcome.ABORTED if abort_cause else AttemptOutcome.COMPLETED,
            abort_cause=abort_cause,
            off_commanded_at=off_commanded_at,
            estimated_l=estimated_l,
            charged_l=max(self.charged_l, estimated_l),
        )

    def unconfirmed(
        self,
        *,
        off_commanded_at: datetime | None,
        abort_cause: str | None = None,
        reason: str | None = None,
    ) -> DeliveryAttempt:
        """Close a requested attempt whose pump never confirmed ON.

        Stopped by something, it is ``aborted`` with that cause; otherwise the
        pump failed to open and it is ``not_delivered`` with the reason. Either
        way nothing is charged: only an actuated attempt charges.
        """
        self._require(AttemptState.REQUESTED)
        if abort_cause is None and reason is None:
            raise ValueError("an unconfirmed attempt closes with a cause or a reason")
        return replace(
            self,
            outcome=(
                AttemptOutcome.ABORTED if abort_cause else AttemptOutcome.NOT_DELIVERED
            ),
            abort_cause=abort_cause,
            reason=None if abort_cause else reason,
            off_commanded_at=off_commanded_at,
        )

    def interrupted(
        self,
        found_at: datetime,
        *,
        off_commanded_at: datetime | None = None,
        off_confirmed_at: datetime | None = None,
    ) -> DeliveryAttempt:
        """Close an attempt a stopped process left open, as ``interrupted``.

        Nothing watched the pump between the attempt's last record and
        ``found_at``, the start that found it, so its end is bounded by the
        evidence. An actuated shot ends at the earlier of its planned end and
        ``found_at``, and its estimate runs to there: it keeps the charge
        confirm-ON gave it and is never topped up. A request that never
        confirmed ON ends at its last recorded moment and charges nothing.

        ``off_commanded_at`` is set when its pump still read ON and was
        switched off; ``off_confirmed_at`` whenever its pump was read OFF.
        """
        if not self.is_open:
            raise ValueError("attempt is closed, not open")
        if self.on_confirmed_at is None:
            ended_at = self.on_commanded_at or self.requested_at
            estimated_l = None
        else:
            planned_end = self.on_confirmed_at + timedelta(seconds=self.planned_s)
            ended_at = max(self.on_confirmed_at, min(found_at, planned_end))
            estimated_l = _liters(
                (ended_at - self.on_confirmed_at).total_seconds(),
                self.flow_rate_ml_per_sec,
            )
        return replace(
            self,
            outcome=AttemptOutcome.INTERRUPTED,
            ended_at=ended_at,
            estimated_l=estimated_l,
            off_commanded_at=off_commanded_at,
            off_confirmed_at=off_confirmed_at,
        )

    def read_back_off(self, at: datetime) -> DeliveryAttempt:
        """Record that the closed attempt's pump was read back OFF."""
        return replace(self, off_confirmed_at=at)

    def _require(self, state: AttemptState) -> None:
        if self.state is not state:
            raise ValueError(f"attempt is {self.state.value}, not {state.value}")

    def as_dict(self) -> dict[str, Any]:
        """Return the durable wire form."""
        return {
            "attempt_id": self.attempt_id,
            "growspace_id": self.growspace_id,
            "output": self.output,
            "trigger": self.trigger.value,
            "trigger_evidence": self.trigger_evidence.as_dict(),
            "planned_s": self.planned_s,
            "flow_rate_ml_per_sec": self.flow_rate_ml_per_sec,
            "requested_at": self.requested_at.isoformat(),
            "on_commanded_at": _iso(self.on_commanded_at),
            "on_confirmed_at": _iso(self.on_confirmed_at),
            "off_commanded_at": _iso(self.off_commanded_at),
            "off_confirmed_at": _iso(self.off_confirmed_at),
            "charge_date": self.charge_date.isoformat() if self.charge_date else None,
            "state": self.state.value,
            "outcome": self.outcome.value if self.outcome else None,
            "reason": self.reason,
            "abort_cause": self.abort_cause,
            "charged_l": self.charged_l,
            "estimated_l": self.estimated_l,
            "evidence": "estimated" if self.estimated_l is not None else None,
            "suppressed_count": self.suppressed_count,
            "last_requested_at": _iso(self.last_requested_at),
            "ended_at": _iso(self.ended_at),
        }

    @classmethod
    def from_dict(cls, value: Any) -> DeliveryAttempt:
        """Refuse any record that is not whole; a malformed one fails closed.

        A row written before attempts were requested (#787) has neither
        ``requested_at`` nor ``trigger_evidence``: it was requested when its ON
        command was sent, and recorded no evidence.
        """
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
        for key in ("reason", "abort_cause"):
            if value.get(key) is not None and not isinstance(value[key], str):
                raise ValueError(f"delivery attempt has an invalid {key}")
        count = value.get("suppressed_count", 0)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise ValueError("delivery attempt has an invalid suppression count")
        on_commanded_at = _optional_aware(value.get("on_commanded_at"))
        requested_at = (
            _aware(value["requested_at"])
            if "requested_at" in value
            else _required(on_commanded_at)
        )
        outcome = value.get("outcome")
        charge_date = value.get("charge_date")
        attempt = cls(
            attempt_id=value["attempt_id"],
            growspace_id=value["growspace_id"],
            output=value["output"],
            trigger=AttemptTrigger(_text(value.get("trigger"))),
            trigger_evidence=TriggerEvidence.from_dict(
                value.get("trigger_evidence", {})
            ),
            planned_s=float(value["planned_s"]),
            flow_rate_ml_per_sec=float(value["flow_rate_ml_per_sec"]),
            requested_at=requested_at,
            on_commanded_at=on_commanded_at,
            on_confirmed_at=_optional_aware(value.get("on_confirmed_at")),
            charge_date=(
                None if charge_date is None else date.fromisoformat(_text(charge_date))
            ),
            charged_l=float(value["charged_l"]),
            outcome=AttemptOutcome(outcome) if outcome is not None else None,
            reason=value.get("reason"),
            abort_cause=value.get("abort_cause"),
            off_commanded_at=_optional_aware(value.get("off_commanded_at")),
            off_confirmed_at=_optional_aware(value.get("off_confirmed_at")),
            estimated_l=float(estimated) if estimated is not None else None,
            suppressed_count=count,
            last_requested_at=_optional_aware(value.get("last_requested_at")),
            ended_at=_optional_aware(value.get("ended_at")),
        )
        attempt._check_whole(value.get("state"))
        return attempt

    def _check_whole(self, state: Any) -> None:
        """Refuse a record whose fields disagree about what happened."""
        if state != self.state.value:
            raise ValueError("delivery attempt state disagrees with its outcome")
        if self.is_actuated != (self.charge_date is not None):
            raise ValueError("delivery attempt has a charge date out of place")
        if self.is_actuated:
            if self.charged_l < _liters(self.planned_s, self.flow_rate_ml_per_sec):
                raise ValueError("delivery attempt is charged less than its plan")
        elif self.charged_l:
            raise ValueError("delivery attempt is charged without confirming ON")
        suppressed = self.outcome is AttemptOutcome.SUPPRESSED
        if suppressed != (self.suppressed_count > 0) or suppressed != (
            self.last_requested_at is not None
        ):
            raise ValueError("delivery attempt has a suppression count out of place")
        if suppressed and (self.reason is None or self.on_commanded_at is not None):
            raise ValueError("a suppressed delivery attempt reached the pump")
        if (self.outcome is AttemptOutcome.INTERRUPTED) != (self.ended_at is not None):
            raise ValueError("delivery attempt has an end time out of place")


def dispensed_volume(attempts: Iterable[DeliveryAttempt], day: date) -> DispensedVolume:
    """Sum the charges dated ``day``: one cycle and its litres per attempt."""
    charged = [attempt.charged_l for attempt in attempts if attempt.charge_date == day]
    return DispensedVolume(cycles=len(charged), liters=sum(charged))


def with_suppression(
    attempts: Iterable[DeliveryAttempt], suppressed: DeliveryAttempt
) -> list[DeliveryAttempt]:
    """Add a suppressed request, merged into its output's run when it continues one.

    A run is consecutive for its output: any other attempt on that output in
    between, whatever its outcome, starts the next suppression on a row of its
    own.
    """
    rows = list(attempts)
    for index in range(len(rows) - 1, -1, -1):
        if rows[index].output != suppressed.output:
            continue
        if rows[index].merges(suppressed):
            rows[index] = rows[index].merged(suppressed)
            return rows
        break
    rows.append(suppressed)
    return rows


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
        if attempt.charge_date == today or attempt.last_seen_at >= horizon
    ]
    excess = len(kept) - ROW_LIMIT
    if excess <= 0:
        return kept
    evictable = sorted(
        (attempt for attempt in kept if attempt.charge_date != today),
        key=lambda attempt: attempt.last_seen_at,
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


def _optional_text(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _optional_number(value: Any) -> float | None:
    return float(value) if _is_amount(value) else None


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("delivery attempt has a missing field")
    return value


def _required(value: datetime | None) -> datetime:
    if value is None:
        raise TypeError("delivery attempt has a missing timestamp")
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
