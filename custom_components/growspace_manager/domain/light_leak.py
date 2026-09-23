"""Pure decisions for the Light Leak Guard (#794).

Light during the dark period is one of the most damaging failures in a
flowering room. The guard watches the *computed* dark period — the same
photoperiod the grow light controller drives, so the two can never disagree
about when it is dark — for two kinds of evidence: a managed grow light that
reports on, and an optional illuminance sensor reading above a threshold.

Evidence becomes an alert only once it has held for the debounce, and a
confirmed episode alerts once: the shell sends on ``CONFIRMED`` and stays quiet
until the evidence clears, which is also what ends the episode when the lit
period begins.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .light_schedule import HasFlowerStart, has_entered_flower, is_dark_period


class LeakCause(StrEnum):
    """One piece of evidence that light is reaching the canopy in the dark."""

    MANAGED_LIGHT_ON = "managed_light_on"
    ILLUMINANCE = "illuminance"


class EpisodeTransition(StrEnum):
    """What one observation did to the current light-leak episode."""

    NONE = "none"
    CONFIRMED = "confirmed"
    CLEARED = "cleared"


def in_watched_dark_period(
    now: datetime,
    plants: Iterable[HasFlowerStart],
    *,
    lights_on_time: str,
    veg_hours: float,
    flower_hours: float,
    all_stages: bool,
) -> bool:
    """Return whether ``now`` is a dark period the guard is watching.

    The photoperiod is resolved exactly as the grow light controller resolves
    it — flower hours from the day any plant enters flower — so on the flip day
    the hours the shortened day gives up are dark here too. Only a flowering
    growspace is watched unless ``all_stages`` is set.
    """
    flowering = has_entered_flower(plants, now.date())
    if not flowering and not all_stages:
        return False
    hours = flower_hours if flowering else veg_hours
    return is_dark_period(now, lights_on_time, hours)


def leak_causes(
    *,
    managed_light_on: bool,
    illuminance: float | None,
    threshold_lux: float,
) -> frozenset[LeakCause]:
    """Return the evidence of light, given readings taken in the dark period.

    An unreadable illuminance sensor (``None``) is no evidence either way.
    """
    causes: set[LeakCause] = set()
    if managed_light_on:
        causes.add(LeakCause.MANAGED_LIGHT_ON)
    if illuminance is not None and illuminance > threshold_lux:
        causes.add(LeakCause.ILLUMINANCE)
    return frozenset(causes)


@dataclass(slots=True)
class LightLeakEpisode:
    """Debounces leak evidence into episodes that alert once each.

    ``started_at`` is when the current run of evidence was first seen;
    ``confirmed`` is set once that run outlasted the debounce.
    """

    started_at: datetime | None = None
    confirmed: bool = False

    def observe(
        self, now: datetime, leaking: bool, debounce: timedelta
    ) -> EpisodeTransition:
        """Fold one observation into the episode and report the transition."""
        if not leaking:
            was_confirmed = self.confirmed
            self.started_at = None
            self.confirmed = False
            return (
                EpisodeTransition.CLEARED if was_confirmed else EpisodeTransition.NONE
            )

        if self.started_at is None:
            self.started_at = now
        if self.confirmed or now - self.started_at < debounce:
            return EpisodeTransition.NONE
        self.confirmed = True
        return EpisodeTransition.CONFIRMED

    def duration(self, now: datetime) -> timedelta:
        """Return how long the current run of evidence has lasted."""
        return now - self.started_at if self.started_at is not None else timedelta(0)
