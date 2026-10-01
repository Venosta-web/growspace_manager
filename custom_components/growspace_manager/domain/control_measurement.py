"""One elected substrate baseline and its response to confirmed shots (ADR-0059).

Pure values in; witnesses substitute on the elected baseline only. Reading validation
remains in sensor_validity; this layer adds provenance and response health.
"""

from __future__ import annotations

from bisect import bisect_right, insort
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from statistics import median
from typing import Any

from ..const import SUBSTRATE_INFILTRATION_DEADBAND_PP_PER_MIN
from .sensor_validity import Invalidity, SensorReading


@dataclass(frozen=True, slots=True)
class ControlMeasurement:
    """Validated % VWC on one probe's baseline, including an honest gap."""

    value: float | None
    observed_at: datetime | None
    cause: Invalidity | None
    invalid_since: datetime | None
    window: timedelta | None
    probe: dict[str, Any] | None
    substitute_for: str | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the wire provenance, including invalid measurements."""
        return {
            "value": self.value,
            "observed_at": self.observed_at.isoformat() if self.observed_at else None,
            "cause": self.cause.value if self.cause else None,
            "invalid_since": self.invalid_since.isoformat()
            if self.invalid_since
            else None,
            "validity_window_seconds": self.window.total_seconds()
            if self.window
            else None,
            "probe": self.probe,
            "substitute_for": self.substitute_for,
        }


def control_measurement(
    probes: list[dict[str, Any]],
    reading: SensorReading,
    *,
    observed_at: datetime | None,
    window: timedelta | None,
    unresponsive_since: datetime | None = None,
) -> ControlMeasurement:
    """Keep the elected moisture reading; never average or substitute witnesses."""
    probe = next(
        (p for p in probes if p["quantity"] == "moisture" and p["role"] == "control"),
        None,
    )
    cause = reading.invalidity
    since = reading.invalid_since
    if probe is None:
        cause = Invalidity.UNAVAILABLE
    elif cause is None and unresponsive_since is not None:
        cause, since = Invalidity.UNRESPONSIVE, unresponsive_since
    return ControlMeasurement(
        reading.value if cause is None else None,
        observed_at,
        cause,
        since,
        window,
        probe,
    )


@dataclass(slots=True)
class WitnessSubstitution:
    """Learn paired baselines over 24 hours and elect one healthy substitute.

    Re-reading the same report pair never weights the median again. History is
    memory-only and scoped to the elected control and current witness roster.
    The active witness stays elected while eligible; its offset uses only
    pairs still inside the rolling window, including during substitution.
    """

    history: dict[str, list[tuple[datetime, float]]] = field(default_factory=dict)
    pairs: dict[str, tuple[datetime, datetime]] = field(default_factory=dict)
    active: dict[str, Any] | None = None
    healthy_witnesses: bool | None = None

    def resolve(
        self,
        control: ControlMeasurement,
        witnesses: list[ControlMeasurement],
        now: datetime,
    ) -> ControlMeasurement:
        """Prefer control immediately; substitute only with fresh paired history."""
        roster = {w.probe["entity_id"] for w in witnesses if w.probe}
        self.history = {
            key: rows for key, rows in self.history.items() if key in roster
        }
        self.pairs = {key: pair for key, pair in self.pairs.items() if key in roster}
        healthy = [w for w in witnesses if w.value is not None and w.probe]
        self.healthy_witnesses = bool(healthy)
        cutoff = now - timedelta(hours=24)
        for witness in witnesses:
            if witness.probe is None:
                continue
            key = witness.probe["entity_id"]
            rows = self.history.setdefault(key, [])
            if rows and rows[0][0] <= cutoff:
                del rows[: bisect_right(rows, cutoff, key=lambda row: row[0])]
            if (
                control.value is not None
                and witness.value is not None
                and control.observed_at is not None
                and witness.observed_at is not None
            ):
                pair = (control.observed_at, witness.observed_at)
                if pair != self.pairs.get(key):
                    self.pairs[key] = pair
                    # History ages from the older report, never from a UI read.
                    at = min(pair)
                    if cutoff < at <= now:
                        sample = (at, control.value - witness.value)
                        if not rows or at >= rows[-1][0]:
                            rows.append(sample)
                        else:
                            insort(rows, sample)
        if control.value is not None or control.probe is None:
            self.active = None
            return control
        if self.active:
            active_entity = self.active["entity_id"]
            healthy.sort(
                key=lambda w: (w.probe or {}).get("entity_id") != active_entity
            )
        for witness in healthy:
            assert witness.probe is not None
            key = witness.probe["entity_id"]
            rows = self.history.get(key, [])
            if not rows:
                continue
            if self.active is None or self.active["entity_id"] != key:
                self.active = {
                    "entity_id": key,
                    "offset": median(delta for _, delta in rows),
                    "since": now.isoformat(),
                }
            self.active["offset"] = median(delta for _, delta in rows)
            assert witness.value is not None
            value = witness.value + self.active["offset"]
            if not 0 <= value <= 100:
                self.active = None
                continue
            return ControlMeasurement(
                value,
                witness.observed_at,
                None,
                None,
                witness.window,
                witness.probe,
                substitute_for=control.probe["entity_id"],
            )
        self.active = None
        return control


@dataclass(slots=True)
class ProbeResponseWatch:
    """Three eligible flat shots degrade; one measured rise restores control.

    A settled observation counts a shot once. Keep its baseline afterwards so
    a late rise from that same confirmed shot can still recover a held zone.
    Manual watering abandons that evidence, and peer values are never inputs.
    """

    failures: int = 0
    unresponsive_since: datetime | None = None
    before: float | None = None
    ended_at: datetime | None = None
    counted: bool = False

    def abandon(self) -> None:
        """Discard feedback contaminated by another watering or a probe edit."""
        self.before = None
        self.ended_at = None
        self.counted = False

    def confirmed_shot(
        self, before: float, ended_at: datetime, *, near_saturation: bool
    ) -> None:
        """Start response evidence only for a completed steering shot below target."""
        self.abandon()
        if near_saturation:
            return
        self.before, self.ended_at = before, ended_at

    def observe(self, value: float, observed_at: datetime, *, settled: bool) -> None:
        """Judge the rise against the infiltration deadband on fresh reports."""
        if self.before is None or self.ended_at is None or observed_at <= self.ended_at:
            return
        minutes = (observed_at - self.ended_at).total_seconds() / 60
        if (value - self.before) / minutes > SUBSTRATE_INFILTRATION_DEADBAND_PP_PER_MIN:
            self.failures = 0
            self.unresponsive_since = None
            self.abandon()
        elif settled and not self.counted:
            self.counted = True
            self.failures += 1
            if self.failures >= 3 and self.unresponsive_since is None:
                self.unresponsive_since = observed_at
