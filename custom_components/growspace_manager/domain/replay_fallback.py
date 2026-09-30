"""Pure Reference Day selection and conservative replay layout (ADR-0062)."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from .delivery_attempt import AttemptTrigger, DeliveryAttempt
from .steering_phase import SteeringPhaseBoundaries


def reference_shots(
    attempts: Iterable[DeliveryAttempt], zone_id: str, day: date
) -> list[DeliveryAttempt]:
    """Only confirmed steering water belongs to a reference recipe."""
    return sorted(
        (
            a
            for a in attempts
            if a.zone_id == zone_id
            and a.charge_date == day
            and a.trigger is AttemptTrigger.STEERING
            and a.on_confirmed_at is not None
        ),
        key=lambda a: a.on_confirmed_at or a.requested_at,
    )


def choose_reference_day(
    days: Iterable[dict[str, Any]],
    attempts: Iterable[DeliveryAttempt],
    *,
    zone_id: str,
    today: date,
    day_hours: float,
) -> dict[str, Any] | None:
    """Choose the latest compatible past day with its recipe still retained."""
    rows = list(attempts)
    candidates = [
        d
        for d in days
        if 0 < (today - date.fromisoformat(d["day"])).days < 7
        and d["day_hours"] == day_hours
        and reference_shots(rows, zone_id, date.fromisoformat(d["day"]))
        and set(d.get("attempt_ids", [])) <= {a.attempt_id for a in rows}
    ]
    return max(candidates, key=lambda d: d["day"], default=None)


@dataclass(frozen=True)
class ReplayShot:
    """One reference attempt translated onto today's lights-on."""

    at: datetime
    planned_s: float
    reference_day: str
    reference_attempt_id: str

    def as_dict(self) -> dict[str, Any]:
        """Return the timeline and attempt linkage."""
        return {
            "at": self.at.isoformat(),
            "planned_s": self.planned_s,
            "reference_day": self.reference_day,
            "reference_attempt_id": self.reference_attempt_id,
        }


def layout_replay(
    reference: dict[str, Any],
    shots: Iterable[DeliveryAttempt],
    *,
    boundaries: SteeringPhaseBoundaries,
    started_at: datetime,
    max_cycle_seconds: float,
) -> list[ReplayShot]:
    """Keep future offsets, reduce each dose, and never enter P0 or P3."""
    origin = datetime.fromisoformat(reference["lights_on"])
    result = []
    for shot in shots:
        if shot.on_confirmed_at is None:
            continue
        # Local wall-clock offsets survive daylight-saving transitions.
        local = shot.on_confirmed_at.astimezone(origin.tzinfo)
        offset = local.replace(tzinfo=None) - origin.replace(tzinfo=None)
        at = boundaries.lights_on + offset
        if at > started_at and boundaries.p0_end <= at < boundaries.p2_stop:
            result.append(
                ReplayShot(
                    at,
                    min(shot.planned_s * 0.8, max_cycle_seconds),
                    reference["day"],
                    shot.attempt_id,
                )
            )
    return result


def watch_reference_window(
    window: dict[str, Any],
    *,
    at: datetime,
    boundaries: SteeringPhaseBoundaries,
    own_control_valid: bool,
    enabled: bool,
    delay: timedelta,
) -> tuple[dict[str, Any], bool]:
    """Persist coverage, refusing any invalid sample or unwatched lit stretch."""
    window = dict(window)
    key = boundaries.lights_on.isoformat()
    if window.get("lights_on") != key:
        window = {
            "lights_on": key,
            "clean": True,
            "last_seen": boundaries.lights_on.isoformat(),
        }
    last = datetime.fromisoformat(window["last_seen"])
    if at >= boundaries.lights_on:
        observed_end = min(at, boundaries.lights_off)
        # The regular minute loop is watched time, even with instant alerts.
        if observed_end - last > max(delay, timedelta(minutes=1)) or (
            at < boundaries.lights_off and (not enabled or not own_control_valid)
        ):
            window["clean"] = False
        window["last_seen"] = observed_end.isoformat()
    closed = at >= boundaries.lights_off and not window.get("closed", False)
    if closed:
        window["closed"] = True
    return window, closed and window["clean"]
