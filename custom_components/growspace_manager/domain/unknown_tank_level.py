"""The Unknown Tank Level watch — one per configured irrigation tank (#790).

A tank whose level cannot be trusted (``domain/sensor_validity.py``) is not
treated as unknown at once: for ``tank_unknown_grace_minutes`` its last valid
reading stands in, so a short probe dropout neither stops a tent nor hides a
low tank. Past that, the Pump Cycle Gate refuses (with ``pause_on_low_tank``)
and the Tank Offline Alert goes out. A tank with no valid reading since the
watch began has nothing to hold and is unknown at once — to the gate. The alert
still waits out the grace from the start, so a slow start raises no alarm.

``TankWatch`` follows ``LightLeakEpisode``: the shell folds readings in with
``observe`` and asks ``status`` (the gate's view) and ``alert`` (the alert's
view, which advances the episode). It reads no sensors and sends nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from .sensor_validity import REALERT_AFTER, Invalidity, SensorReading

DEFAULT_TANK_UNKNOWN_GRACE_MINUTES = 10
DEFAULT_STALE_AFTER_MINUTES = 120


@dataclass(frozen=True, slots=True)
class UnknownTankLevel:
    """A configured tank whose level cannot be trusted, why, and since when."""

    name: str
    entity_id: str
    cause: Invalidity
    since: datetime


@dataclass(frozen=True, slots=True)
class TankStatus:
    """The gate's view of one tank: a level to act on, or an unknown one."""

    level: float | None
    unknown: UnknownTankLevel | None


class TankAlert(StrEnum):
    """What the Tank Offline Alert should say after one watch tick."""

    NONE = "none"
    OFFLINE = "offline"
    RECOVERED = "recovered"


@dataclass(slots=True)
class TankWatch:
    """Grace and episode state for one tank.

    ``unknown_since`` is set while the tank is invalid, and never earlier than
    ``watching_since``; ``alerted`` is set once the current episode alerted.
    """

    watching_since: datetime
    last_valid_level: float | None = None
    unknown_since: datetime | None = None
    cause: Invalidity = Invalidity.UNAVAILABLE
    alerted: bool = False
    last_alert_at: datetime | None = None

    def observe(self, reading: SensorReading) -> None:
        """Fold one validated reading into the watch."""
        if reading.invalidity is None:
            self.last_valid_level = reading.value
            self.unknown_since = None
            return
        self.cause = reading.invalidity
        if self.unknown_since is None:
            since = reading.invalid_since or self.watching_since
            self.unknown_since = max(since, self.watching_since)

    def _unknown_for(self, now: datetime) -> timedelta | None:
        if self.last_valid_level is None and self.unknown_since is None:
            return now - self.watching_since
        if self.unknown_since is None:
            return None
        return now - self.unknown_since

    def status(
        self, name: str, entity_id: str, now: datetime, grace: timedelta
    ) -> TankStatus:
        """Return the level the gate may act on, or the Unknown Tank Level."""
        unknown_for = self._unknown_for(now)
        if unknown_for is None:
            return TankStatus(self.last_valid_level, None)
        if self.last_valid_level is not None and unknown_for < grace:
            return TankStatus(self.last_valid_level, None)
        since = self.unknown_since or self.watching_since
        return TankStatus(None, UnknownTankLevel(name, entity_id, self.cause, since))

    def alert(self, now: datetime, grace: timedelta) -> TankAlert:
        """Advance the episode and return what, if anything, to announce."""
        unknown_for = self._unknown_for(now)
        if unknown_for is None:
            if self.alerted:
                self.alerted = False
                return TankAlert.RECOVERED
            return TankAlert.NONE
        if self.alerted or unknown_for < grace:
            return TankAlert.NONE
        if self.last_alert_at is not None and now - self.last_alert_at < REALERT_AFTER:
            return TankAlert.NONE
        self.alerted = True
        self.last_alert_at = now
        return TankAlert.OFFLINE


_CAUSE_TEXT = {
    Invalidity.UNAVAILABLE: "the sensor is unavailable",
    Invalidity.IMPLAUSIBLE: "its reading is outside 0–100 %",
}


def offline_alert_message(
    unknown: UnknownTankLevel,
    *,
    growspace_name: str,
    since_local: str,
    stale_after_minutes: int,
    irrigation_paused: bool,
) -> str:
    """Return the Tank Offline Alert's text."""
    cause = _CAUSE_TEXT.get(
        unknown.cause, f"no report for over {stale_after_minutes} minutes"
    )
    consequence = (
        "Irrigation is paused until it reports again."
        if irrigation_paused
        else "Irrigation is not paused, because Pause When Tank Is Low is off."
    )
    return (
        f"{unknown.name} in {growspace_name} has had no usable level since "
        f"{since_local}: {cause}. {consequence}"
    )


def recovered_alert_message(tank_name: str, growspace_name: str, level: float) -> str:
    """Return the text announcing that an alerted tank reads again."""
    return f"{tank_name} in {growspace_name} is reporting again ({level:.0f}%)."


def unknown_tank_skip_text(unknown: UnknownTankLevel) -> str:
    """Return the gate's reason text for a cycle refused on an unknown tank."""
    return f"tank '{unknown.name}' level is unknown ({unknown.cause.value})"
