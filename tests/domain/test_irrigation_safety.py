"""Pure controller state precedence and durable fault-record contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import json
from pathlib import Path

import pytest

from custom_components.growspace_manager.domain.irrigation_safety import (
    STARTUP_INHIBIT,
    ControllerState,
    FaultRecord,
    SafetyReason,
    controller_snapshot,
    startup_inhibit,
)
from custom_components.growspace_manager.domain.manual_override import (
    ManualOverride,
    Subsystem,
)

REASON = SafetyReason("cap_volume", "daily volume cap", "2026-09-23T10:00:00Z")
FAULT = FaultRecord("fault-1", REASON, ("switch.pump",))


@pytest.mark.parametrize(
    ("configured", "enabled", "running", "inhibits", "fault", "e_stop", "expected"),
    [
        (False, False, False, (), None, None, ControllerState.IDLE),
        (True, False, False, (), None, None, ControllerState.IDLE),
        (True, True, False, (), None, None, ControllerState.READY),
        (True, True, True, (), None, None, ControllerState.RUNNING),
        (True, True, False, (REASON,), None, None, ControllerState.INHIBITED),
        (True, True, True, (), FAULT, None, ControllerState.FAULT),
        (True, True, True, (), FAULT, REASON, ControllerState.EMERGENCY_STOP),
    ],
)
def test_controller_state_precedence(
    configured: bool,
    enabled: bool,
    running: bool,
    inhibits: tuple[SafetyReason, ...],
    fault: FaultRecord | None,
    e_stop: SafetyReason | None,
    expected: ControllerState,
) -> None:
    """Every state is reachable and durable stops dominate live conditions."""
    snapshot = controller_snapshot(
        configured=configured,
        automation_enabled=enabled,
        running=running,
        inhibits=inhibits,
        fault=fault,
        emergency_stop=e_stop,
    )
    assert snapshot.state is expected
    assert snapshot.requires_ack is (
        expected in (ControllerState.FAULT, ControllerState.EMERGENCY_STOP)
    )
    assert set(snapshot.attributes()) == {
        "reasons",
        "fault_id",
        "requires_ack",
        "since",
        "overrides",
    }


def test_fault_wire_round_trip() -> None:
    """Sensor reasons and stored fault metadata keep their named fields."""
    assert FaultRecord.from_dict(FAULT.as_dict()) == FAULT
    assert controller_snapshot(
        configured=True, automation_enabled=True, running=False, fault=FAULT
    ).attributes() == {
        "reasons": [REASON.as_dict()],
        "fault_id": "fault-1",
        "requires_ack": True,
        "since": REASON.since,
        "overrides": [],
    }


def test_emergency_stop_wire_allows_no_outputs() -> None:
    """An operator stop can hold an unwired growspace across restart."""
    stop = FaultRecord("stop-1", REASON, ())
    assert FaultRecord.from_dict(stop.as_dict(), allow_empty_outputs=True) == stop


def test_sensor_contract_fixture() -> None:
    """The enum and attributes have a stable consumer-facing wire shape."""
    fault = FaultRecord(
        "fault-1",
        SafetyReason(
            "fault_off_unconfirmed:switch.pump",
            "Pump remained on",
            "2026-09-23T10:00:00Z",
        ),
        ("switch.pump",),
    )
    started = datetime(2026, 9, 23, 9, 30, tzinfo=UTC)
    snapshot = controller_snapshot(
        configured=True,
        automation_enabled=True,
        running=False,
        fault=fault,
        manual_overrides=(
            ManualOverride(
                Subsystem.EXHAUST,
                started,
                started + timedelta(hours=1),
                "user-1",
                "Changing the carbon filter",
            ),
        ),
    )
    wire = {"state": snapshot.state.value, "attributes": snapshot.attributes()}
    fixture = (
        Path(__file__).parents[1] / "fixtures/contract/irrigation_controller_v1.json"
    )
    assert wire == json.loads(fixture.read_text())


@pytest.mark.parametrize(
    "record",
    [None, {}, {"fault_id": "x", "reason": REASON.as_dict(), "outputs": []}],
)
def test_incomplete_fault_record_refused(record: object) -> None:
    """An incomplete stored latch cannot become a clear controller."""
    with pytest.raises((TypeError, ValueError)):
        FaultRecord.from_dict(record)


STARTED = datetime(2026, 9, 23, 10, 0, tzinfo=UTC)
GRACE = timedelta(minutes=5)


def test_startup_inhibit_holds_through_the_grace_period() -> None:
    reason = startup_inhibit(
        started_at=STARTED, now=STARTED + timedelta(minutes=4), grace=GRACE, awaiting=()
    )
    assert reason == SafetyReason(
        STARTUP_INHIBIT,
        "starting up: grace period until 2026-09-23T10:05:00+00:00",
        STARTED.isoformat(),
    )


def test_startup_inhibit_outlasts_the_grace_period_until_every_sensor_reports() -> None:
    reason = startup_inhibit(
        started_at=STARTED,
        now=STARTED + timedelta(minutes=9),
        grace=GRACE,
        awaiting=("sensor.vwc", "sensor.tank"),
    )
    assert reason is not None
    assert reason.detail == (
        "starting up: waiting for a first report from sensor.vwc, sensor.tank"
    )
    assert reason.since == STARTED.isoformat()


def test_startup_inhibit_names_both_conditions_while_both_are_outstanding() -> None:
    reason = startup_inhibit(
        started_at=STARTED, now=STARTED, grace=GRACE, awaiting=("sensor.vwc",)
    )
    assert reason is not None
    assert reason.detail == (
        "starting up: grace period until 2026-09-23T10:05:00+00:00; "
        "waiting for a first report from sensor.vwc"
    )


@pytest.mark.parametrize(
    ("elapsed", "grace"),
    [(timedelta(minutes=5), GRACE), (timedelta(0), timedelta(0))],
)
def test_startup_inhibit_clears_once_both_conditions_are_met(
    elapsed: timedelta, grace: timedelta
) -> None:
    assert (
        startup_inhibit(
            started_at=STARTED, now=STARTED + elapsed, grace=grace, awaiting=()
        )
        is None
    )
