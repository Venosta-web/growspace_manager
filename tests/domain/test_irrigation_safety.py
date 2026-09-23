"""Pure controller state precedence and durable fault-record contract."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.growspace_manager.domain.irrigation_safety import (
    ControllerState,
    FaultRecord,
    SafetyReason,
    controller_snapshot,
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
    snapshot = controller_snapshot(
        configured=True, automation_enabled=True, running=False, fault=fault
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
