"""Pure irrigation controller state and fault-record validation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ControllerState(StrEnum):
    """The grower's view of one growspace's irrigation controller."""

    IDLE = "idle"
    READY = "ready"
    RUNNING = "running"
    INHIBITED = "inhibited"
    FAULT = "fault"
    EMERGENCY_STOP = "emergency_stop"


@dataclass(frozen=True, slots=True)
class SafetyReason:
    """A stable machine code with human context and its first observation."""

    code: str
    detail: str
    since: str

    def as_dict(self) -> dict[str, str]:
        """Return the sensor and storage wire form."""
        return {"code": self.code, "detail": self.detail, "since": self.since}


@dataclass(frozen=True, slots=True)
class FaultRecord:
    """A latched hardware disagreement, including every affected output."""

    fault_id: str
    reason: SafetyReason
    outputs: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the durable wire form."""
        return {
            "fault_id": self.fault_id,
            "reason": self.reason.as_dict(),
            "outputs": list(self.outputs),
        }

    @classmethod
    def from_dict(cls, value: Any, *, allow_empty_outputs: bool = False) -> FaultRecord:
        """Reject incomplete records; a malformed latch must fail closed."""
        if not isinstance(value, dict):
            raise TypeError("fault record is not an object")
        reason = value.get("reason")
        outputs = value.get("outputs")
        if (
            not isinstance(value.get("fault_id"), str)
            or not value["fault_id"]
            or not isinstance(reason, dict)
            or any(
                not isinstance(reason.get(k), str) or not reason[k]
                for k in ("code", "detail", "since")
            )
            or not isinstance(outputs, list)
            or (not outputs and not allow_empty_outputs)
            or any(not isinstance(entity, str) or not entity for entity in outputs)
        ):
            raise ValueError("fault record is incomplete")
        return cls(
            fault_id=value["fault_id"],
            reason=SafetyReason(reason["code"], reason["detail"], reason["since"]),
            outputs=tuple(outputs),
        )


@dataclass(frozen=True, slots=True)
class ControllerSnapshot:
    """One computed state; a latch always wins over transient gates."""

    state: ControllerState
    reasons: tuple[SafetyReason, ...] = ()
    fault_id: str | None = None
    since: str | None = None

    @property
    def requires_ack(self) -> bool:
        """Whether an operator must explicitly re-arm the controller."""
        return self.state in (ControllerState.FAULT, ControllerState.EMERGENCY_STOP)

    def attributes(self) -> dict[str, Any]:
        """Return stable sensor attributes."""
        return {
            "reasons": [reason.as_dict() for reason in self.reasons],
            "fault_id": self.fault_id,
            "requires_ack": self.requires_ack,
            "since": self.since,
        }


def controller_snapshot(
    *,
    configured: bool,
    automation_enabled: bool,
    running: bool,
    inhibits: tuple[SafetyReason, ...] = (),
    fault: FaultRecord | None = None,
    emergency_stop: SafetyReason | None = None,
) -> ControllerSnapshot:
    """Evaluate controller state in safety precedence order."""
    if emergency_stop is not None:
        return ControllerSnapshot(
            ControllerState.EMERGENCY_STOP,
            (emergency_stop,),
            since=emergency_stop.since,
        )
    if fault is not None:
        return ControllerSnapshot(
            ControllerState.FAULT,
            (fault.reason,),
            fault_id=fault.fault_id,
            since=fault.reason.since,
        )
    if running:
        return ControllerSnapshot(ControllerState.RUNNING)
    if not configured or not automation_enabled:
        return ControllerSnapshot(ControllerState.IDLE)
    if inhibits:
        return ControllerSnapshot(
            ControllerState.INHIBITED, inhibits, since=inhibits[0].since
        )
    return ControllerSnapshot(ControllerState.READY)
