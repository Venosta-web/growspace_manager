"""A person operating the equipment: the pure rules (#793). No mocks."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from custom_components.growspace_manager.domain.irrigation_safety import (
    ControllerState,
    FaultRecord,
    SafetyReason,
    controller_snapshot,
)
from custom_components.growspace_manager.domain.manual_override import (
    MANUAL_OVERRIDE,
    OVERRIDE_DETECTED,
    ManualOverride,
    Subsystem,
    UnexpectedOnPolicy,
    UnexpectedOnResponse,
    detected_override_reason,
    respond_to_on,
)

STARTED = datetime(2026, 9, 24, 10, 0, tzinfo=UTC)
HALF_HOUR = timedelta(minutes=30)
OVERRIDE = ManualOverride(
    Subsystem.IRRIGATION, STARTED, STARTED + HALF_HOUR, "user-1", "hand watering"
)

ALERT, ENFORCE = UnexpectedOnPolicy.ALERT, UnexpectedOnPolicy.ENFORCE_OFF


@pytest.mark.parametrize(
    ("in_flight", "overridden", "allowed", "policy", "expected"),
    [
        # Ours: commanded ON and not yet read back OFF.
        (True, False, True, ENFORCE, None),
        # A Manual Override handed irrigation to a person.
        (False, True, True, ENFORCE, None),
        (False, False, True, ALERT, UnexpectedOnResponse.ALERT),
        (False, False, True, ENFORCE, UnexpectedOnResponse.ENFORCE_OFF),
        # Automation off or an emergency stop: no command, not even OFF.
        (False, False, False, ENFORCE, UnexpectedOnResponse.ALERT),
        (False, False, False, ALERT, UnexpectedOnResponse.ALERT),
    ],
)
def test_an_on_is_ours_a_persons_or_to_be_stopped(
    in_flight: bool,
    overridden: bool,
    allowed: bool,
    policy: UnexpectedOnPolicy,
    expected: UnexpectedOnResponse | None,
) -> None:
    assert (
        respond_to_on(
            in_flight=in_flight,
            overridden=overridden,
            commands_allowed=allowed,
            policy=policy,
        )
        is expected
    )


def test_a_detected_override_names_every_pump_and_dates_from_the_first() -> None:
    reason = detected_override_reason(
        {
            "switch.pump": "2026-09-24T10:05:00+00:00",
            "switch.drain": STARTED.isoformat(),
        }
    )
    assert reason == SafetyReason(
        OVERRIDE_DETECTED,
        "switch.drain, switch.pump switched on outside Growspace Manager; "
        "automatic irrigation holds until it reads off",
        STARTED.isoformat(),
    )


def test_an_override_holds_until_it_expires() -> None:
    assert OVERRIDE.active(STARTED)
    assert OVERRIDE.active(STARTED + HALF_HOUR - timedelta(seconds=1))
    assert not OVERRIDE.active(STARTED + HALF_HOUR)


def test_an_override_reads_as_its_own_inhibit() -> None:
    assert OVERRIDE.safety_reason() == SafetyReason(
        MANUAL_OVERRIDE,
        "manual override of irrigation until 2026-09-24T10:30:00+00:00: hand watering",
        STARTED.isoformat(),
    )
    bare = ManualOverride(Subsystem.EXHAUST, STARTED, STARTED + HALF_HOUR)
    assert bare.safety_reason().detail == (
        "manual override of exhaust until 2026-09-24T10:30:00+00:00"
    )


def test_an_override_round_trips_its_wire_form() -> None:
    assert OVERRIDE.as_dict() == {
        "subsystem": "irrigation",
        "started_at": "2026-09-24T10:00:00+00:00",
        "expires_at": "2026-09-24T10:30:00+00:00",
        "user_id": "user-1",
        "reason": "hand watering",
    }
    assert ManualOverride.from_dict(OVERRIDE.as_dict()) == OVERRIDE


def _wire(**changes: Any) -> dict[str, Any]:
    return {**OVERRIDE.as_dict(), **changes}


@pytest.mark.parametrize(
    "record",
    [
        None,
        [],
        _wire(subsystem="pumps"),
        _wire(started_at=None),
        _wire(expires_at=12),
        _wire(user_id=7),
        _wire(reason=["x"]),
        _wire(started_at="yesterday"),
        _wire(started_at="2026-09-24T10:00:00"),
        _wire(expires_at="2026-09-24T09:00:00+00:00"),
        _wire(expires_at="2026-09-26T10:00:00+00:00"),
    ],
)
def test_a_malformed_override_is_refused(record: object) -> None:
    """A person's hold must never be read as something shorter, or as nothing."""
    with pytest.raises((TypeError, ValueError)):
        ManualOverride.from_dict(record)


FAULT = FaultRecord("fault-1", SafetyReason("fault_x", "x", "then"), ("switch.pump",))
HOLD = OVERRIDE.safety_reason()
CAP = SafetyReason("cap_volume", "daily volume cap", "earlier")


@pytest.mark.parametrize(
    ("configured", "automated", "running", "fault", "expected", "reasons"),
    [
        # A person holds manual runs too, so a manual-only controller shows it.
        (True, False, False, None, ControllerState.INHIBITED, (HOLD,)),
        # Automated: the hold comes first, the other inhibits after it.
        (True, True, False, None, ControllerState.INHIBITED, (HOLD, CAP)),
        (False, True, False, None, ControllerState.IDLE, ()),
        (True, True, True, None, ControllerState.RUNNING, ()),
        (True, True, False, FAULT, ControllerState.FAULT, (FAULT.reason,)),
    ],
)
def test_a_persons_hold_in_the_controller_precedence(
    configured: bool,
    automated: bool,
    running: bool,
    fault: FaultRecord | None,
    expected: ControllerState,
    reasons: tuple[SafetyReason, ...],
) -> None:
    snapshot = controller_snapshot(
        configured=configured,
        automation_enabled=automated,
        running=running,
        inhibits=(CAP,),
        fault=fault,
        holds=(HOLD,),
    )
    assert snapshot.state is expected
    assert snapshot.reasons == reasons


def test_every_override_is_reported_whatever_the_state() -> None:
    exhaust = ManualOverride(Subsystem.EXHAUST, STARTED, STARTED + HALF_HOUR)
    snapshot = controller_snapshot(
        configured=True,
        automation_enabled=True,
        running=False,
        manual_overrides=(exhaust,),
    )
    assert snapshot.state is ControllerState.READY
    assert snapshot.attributes()["overrides"] == [exhaust.as_dict()]
