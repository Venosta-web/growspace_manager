"""Pure rules for a person operating Growspace Manager's equipment (#793).

Two ways a person takes an output over, and one rule for each:

- A **Manual Override** is declared. ``set_override`` names a growspace, a
  subsystem and a duration, and Growspace Manager issues no command to that
  subsystem until it expires or is cleared. It is persisted and audited by the
  safety store; this module owns its record and its validation.
- An **Unexpected On** is observed. A managed pump reads ON with no cycle of
  Growspace Manager's own in flight. By default that is treated as a person's
  action: alert, and hold automatic irrigation while it lasts. The opt-in
  ``enforce_off`` policy switches it off and latches a Fault instead.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from .irrigation_safety import SafetyReason

# Reason codes on the Irrigation Controller.
MANUAL_OVERRIDE = "manual_override"
OVERRIDE_DETECTED = "override_detected"
# The Fault an Unexpected On latches under ``enforce_off``.
FAULT_UNEXPECTED_ON = "fault_unexpected_on"

# A Manual Override always ends by itself; the longest is a day.
MAX_OVERRIDE_DURATION = timedelta(hours=24)
MAX_REASON_LENGTH = 200


class Subsystem(StrEnum):
    """A set of outputs a Manual Override hands to a person as one."""

    IRRIGATION = "irrigation"
    EXHAUST = "exhaust"
    CIRCULATION = "circulation"
    HUMIDIFIER = "humidifier"
    DEHUMIDIFIER = "dehumidifier"
    LIGHTS = "lights"


class UnexpectedOnPolicy(StrEnum):
    """What a pump reading ON outside any cycle of ours leads to."""

    ALERT = "alert"
    ENFORCE_OFF = "enforce_off"


class UnexpectedOnResponse(StrEnum):
    """The effect an observed ON calls for; the shell carries it out."""

    ALERT = "alert"
    ENFORCE_OFF = "enforce_off"


def respond_to_on(
    *,
    in_flight: bool,
    overridden: bool,
    commands_allowed: bool,
    policy: UnexpectedOnPolicy,
) -> UnexpectedOnResponse | None:
    """Decide what a pump reading ON calls for, or None when it was expected.

    It is expected while a cycle of ours has it — commanded ON and not yet read
    back OFF — and while a Manual Override has handed irrigation to a person.
    Otherwise it always alerts. It is switched off only under ``enforce_off``,
    and only while Growspace Manager may command the growspace at all: with
    automation off or an emergency stop latched it sends nothing, not even OFF.
    """
    if in_flight or overridden:
        return None
    if policy is UnexpectedOnPolicy.ENFORCE_OFF and commands_allowed:
        return UnexpectedOnResponse.ENFORCE_OFF
    return UnexpectedOnResponse.ALERT


def detected_override_reason(outputs: dict[str, str]) -> SafetyReason:
    """Return the inhibit for pumps a person is running, earliest first."""
    first = min(outputs, key=lambda output: outputs[output])
    names = ", ".join(sorted(outputs))
    return SafetyReason(
        OVERRIDE_DETECTED,
        f"{names} switched on outside Growspace Manager; "
        "automatic irrigation holds until it reads off",
        outputs[first],
    )


@dataclass(frozen=True, slots=True)
class ManualOverride:
    """One subsystem handed to a person until ``expires_at``."""

    subsystem: Subsystem
    started_at: datetime
    expires_at: datetime
    user_id: str | None = None
    reason: str | None = None

    def active(self, now: datetime) -> bool:
        """Whether it still holds at ``now``."""
        return now < self.expires_at

    def safety_reason(self) -> SafetyReason:
        """Return the Irrigation Controller's inhibit for this override."""
        detail = (
            f"manual override of {self.subsystem} until {self.expires_at.isoformat()}"
        )
        if self.reason:
            detail += f": {self.reason}"
        return SafetyReason(MANUAL_OVERRIDE, detail, self.started_at.isoformat())

    def as_dict(self) -> dict[str, Any]:
        """Return the durable and sensor wire form."""
        return {
            "subsystem": self.subsystem.value,
            "started_at": self.started_at.isoformat(),
            "expires_at": self.expires_at.isoformat(),
            "user_id": self.user_id,
            "reason": self.reason,
        }

    @classmethod
    def from_dict(cls, value: Any) -> ManualOverride:
        """Refuse any record that is not whole; a malformed one fails closed."""
        if not isinstance(value, dict):
            raise TypeError("override record is not an object")
        started, expires = value.get("started_at"), value.get("expires_at")
        user_id, reason = value.get("user_id"), value.get("reason")
        if (
            value.get("subsystem") not in {s.value for s in Subsystem}
            or not isinstance(started, str)
            or not isinstance(expires, str)
            or not (user_id is None or isinstance(user_id, str))
            or not (reason is None or isinstance(reason, str))
        ):
            raise ValueError("override record is incomplete")
        started_at = datetime.fromisoformat(started)
        expires_at = datetime.fromisoformat(expires)
        if started_at.tzinfo is None or expires_at.tzinfo is None:
            raise ValueError("override record has a naive timestamp")
        if not started_at < expires_at <= started_at + MAX_OVERRIDE_DURATION:
            raise ValueError("override record has an impossible window")
        return cls(
            Subsystem(value["subsystem"]), started_at, expires_at, user_id, reason
        )
