"""One elected substrate baseline and its response to confirmed shots (ADR-0059).

Pure values in; witnesses never enter the control value. Reading validation
remains in sensor_validity; this layer adds provenance and response health.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
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
