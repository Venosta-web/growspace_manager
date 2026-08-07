"""Infiltration Monitor: measures whether the substrate is still absorbing water.

Turns a stream of VWC readings into an [[Infiltration]] state. Like
[[ShotComposer]] and the [[Steering Phase Machine]] — and unlike the
pure-per-call [[EC State]] resolver — this is a *stateful* controller: the
sample ring persists across ticks and owns its own ``reset()`` rule, so it is
retained here rather than threaded through by the caller. Plain values in, no
``hass``, no sensors, no coordinator (see ``tests/domain/test_infiltration.py``).
See ADR-0031.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from custom_components.growspace_manager.const import (
    SUBSTRATE_INFILTRATION_DEADBAND_PP_PER_MIN,
    SUBSTRATE_INFILTRATION_WINDOW_MINUTES,
)


class InfiltrationState(StrEnum):
    """The measured [[Infiltration]] state of a growspace."""

    INFILTRATING = "infiltrating"
    SETTLED = "settled"
    DRYING = "drying"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class _Sample:
    """One VWC reading, stamped with the sensor's own update time."""

    vwc: float
    at: datetime


class InfiltrationMonitor:
    """Stateful owner of the Infiltration measurement."""

    def __init__(self) -> None:
        """Start with an empty sample ring."""
        self._samples: list[_Sample] = []

    def record(self, vwc: float, sensor_last_updated: datetime) -> None:
        """Append a sample, but only when the sensor's own timestamp advances.

        The steering loop ticks every 60s while many VWC probes report every few
        minutes, so most calls re-present a reading already recorded. Sampling
        those repeats would compute a slope over loop ticks — exactly `0` mid-
        infiltration — so they are dropped here.
        """
        if self._samples and sensor_last_updated <= self._samples[-1].at:
            return
        self._samples.append(_Sample(vwc, sensor_last_updated))
        cutoff = sensor_last_updated - timedelta(
            minutes=SUBSTRATE_INFILTRATION_WINDOW_MINUTES
        )
        self._samples = [sample for sample in self._samples if sample.at >= cutoff]

    @property
    def state(self) -> InfiltrationState:
        """Return the current Infiltration state."""
        if len(self._samples) < 2:
            return InfiltrationState.UNKNOWN
        oldest, newest = self._samples[0], self._samples[-1]
        minutes = (newest.at - oldest.at).total_seconds() / 60.0
        slope = (newest.vwc - oldest.vwc) / minutes
        if slope > SUBSTRATE_INFILTRATION_DEADBAND_PP_PER_MIN:
            return InfiltrationState.INFILTRATING
        if slope < -SUBSTRATE_INFILTRATION_DEADBAND_PP_PER_MIN:
            return InfiltrationState.DRYING
        return InfiltrationState.SETTLED

    def reset(self) -> None:
        """Discard every sample."""
        self._samples.clear()
