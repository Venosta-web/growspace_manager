"""What the climate controllers do when they cannot see (#792).

A control input that has had no usable reading (``domain/sensor_validity.py``)
for longer than the **Fail-Safe Timeout** puts every controller that depends on
it into its **Safe State**: the humidifier and dehumidifier to a configured
state (off by default), the exhaust to a fallback speed once *every* one of its
regulation sensors has failed. Circulation has no safe state; it holds.

Short dropouts are not failures: until the timeout the controllers simply hold
what they last commanded, as they always have. One **Fail-Safe Episode** spans
the time any controller in the growspace is in its safe state, so a dead VPD
sensor that takes the humidifier and the dehumidifier down together raises one
alert, not two, and one recovery message when control resumes.

The **Humidity Interlock** keeps the humidifier and the dehumidifier from
running together: the later demand wins.

Pure: the shell hands in readings, times and configuration.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import StrEnum

from .sensor_validity import REALERT_AFTER, SensorReading


class ClimateRole(StrEnum):
    """A climate controller of one growspace."""

    HUMIDIFIER = "humidifier"
    DEHUMIDIFIER = "dehumidifier"
    EXHAUST = "exhaust"
    CIRCULATION = "circulation"


class SafeState(StrEnum):
    """What an on/off device does while its controller is in fail-safe."""

    OFF = "off"
    ON = "on"
    HOLD = "hold"


def failed_since(
    readings: Mapping[str, SensorReading], invalid_since: Mapping[str, datetime]
) -> datetime | None:
    """Return when the last of a controller's inputs stopped being usable.

    A controller fails only when none of its inputs can be used, so its failure
    starts when the last usable one was lost. None while any input reads, and
    for a controller with no inputs at all, which has nothing to lose.
    """
    if not readings or any(reading.valid for reading in readings.values()):
        return None
    return max(invalid_since[entity_id] for entity_id in readings)


def fail_safe_due(since: datetime | None, now: datetime, timeout: timedelta) -> bool:
    """Return whether an input lost at ``since`` has now been lost too long."""
    return since is not None and now - since >= timeout


def interlock_wins(mine: datetime | None, partner: datetime | None) -> bool:
    """Return whether this device's demand displaces its running partner.

    The later demand wins. A partner running without any demand of its own —
    switched on by hand, or held — never outranks one. ``mine`` is None only
    for a safe state, which outranks every demand.
    """
    if mine is None or partner is None:
        return True
    return mine >= partner


def runtime_exceeded(
    on_since: datetime | None, now: datetime, max_runtime: timedelta
) -> bool:
    """Return whether a device on since ``on_since`` has run past its cap."""
    return on_since is not None and now - on_since >= max_runtime


class EpisodeAlert(StrEnum):
    """What a Fail-Safe Episode should announce after one evaluation."""

    NONE = "none"
    FAILED = "failed"
    UPDATED = "updated"
    RECOVERED = "recovered"


@dataclass(frozen=True, slots=True)
class RoleFailure:
    """One controller in its safe state: which inputs, and since when."""

    sensors: tuple[str, ...]
    since: datetime


@dataclass(slots=True)
class FailSafeEpisode:
    """The growspace's controllers in fail-safe, and whether they were announced.

    ``failed`` is the roles currently in their safe state. The episode alerts
    once, when the first role fails, and at most once per ``REALERT_AFTER``
    for a sensor that keeps dropping out; a role joining an alerted episode
    only updates it. It recovers when the last role does.
    """

    failed: dict[ClimateRole, RoleFailure] = field(default_factory=dict)
    alerted: bool = False
    last_alert_at: datetime | None = None

    def update(
        self, failed: Mapping[ClimateRole, RoleFailure], now: datetime
    ) -> EpisodeAlert:
        """Fold one evaluation in and return what, if anything, to announce."""
        changed = dict(failed) != self.failed
        self.failed = dict(failed)
        if not self.failed:
            if self.alerted:
                self.alerted = False
                return EpisodeAlert.RECOVERED
            return EpisodeAlert.NONE
        if self.alerted:
            return EpisodeAlert.UPDATED if changed else EpisodeAlert.NONE
        if self.last_alert_at is not None and now - self.last_alert_at < REALERT_AFTER:
            return EpisodeAlert.NONE
        self.alerted = True
        self.last_alert_at = now
        return EpisodeAlert.FAILED


_ACTION_TEXT = {
    SafeState.OFF: "is switched off",
    SafeState.ON: "is switched on",
    SafeState.HOLD: "is left as it is",
}


def safe_action(role: ClimateRole, safe_state: SafeState | None, speed: int) -> str:
    """Describe what one controller does in its safe state."""
    if role is ClimateRole.EXHAUST:
        return f"the exhaust runs at {speed}%"
    return f"the {role.value} {_ACTION_TEXT[safe_state or SafeState.OFF]}"


def failed_alert_message(
    growspace_name: str,
    failed: Mapping[ClimateRole, RoleFailure],
    actions: Mapping[ClimateRole, str],
    *,
    since_local: str,
) -> str:
    """Return the text of a Fail-Safe Episode's alert."""
    sensors = sorted(
        {sensor for failure in failed.values() for sensor in failure.sensors}
    )
    doing = "; ".join(actions[role] for role in sorted(failed))
    noun, verb = ("sensor", "reports") if len(sensors) == 1 else ("sensors", "report")
    return (
        f"Climate control in {growspace_name} has had no usable reading from "
        f"the {noun} {', '.join(sensors)} since {since_local}, so it has gone "
        f"to its fail-safe: {doing}. Normal control resumes when the "
        f"{noun} {verb} again."
    )


def recovered_alert_message(growspace_name: str) -> str:
    """Return the text announcing that climate control is back."""
    return (
        f"Climate control in {growspace_name} has usable readings again and "
        "has resumed normal control."
    )
