"""The controller entity exposes the domain snapshot without changing it."""

from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.growspace_manager.domain.irrigation_safety import (
    ControllerState,
    FaultRecord,
    SafetyReason,
    controller_snapshot,
)
from custom_components.growspace_manager.sensor.irrigation_controller import (
    IrrigationControllerSensor,
)


def test_sensor_reports_fault_contract() -> None:
    """The entity reports the same code and acknowledgement status as its source."""
    coordinator = MagicMock()
    snapshot = controller_snapshot(
        configured=True,
        automation_enabled=True,
        running=False,
        fault=FaultRecord(
            "fault-1",
            SafetyReason("fault_off_unconfirmed:switch.pump", "still on", "now"),
            ("switch.pump",),
        ),
    )
    coordinator.services.growspaces.get_irrigation_coordinator.return_value.controller_snapshot.return_value = snapshot
    sensor = IrrigationControllerSensor(coordinator, "tent", "Demo Tent")
    assert sensor.native_value == ControllerState.FAULT.value
    assert sensor.extra_state_attributes == snapshot.attributes()
    assert sensor.options == [state.value for state in ControllerState]


def test_sensor_without_irrigation_is_idle() -> None:
    """A growspace without a coordinator still has a readable idle entity."""
    coordinator = MagicMock()
    coordinator.services.growspaces.get_irrigation_coordinator.return_value = None
    sensor = IrrigationControllerSensor(coordinator, "tent", "Demo Tent")
    assert sensor.native_value == "idle"
    assert sensor.extra_state_attributes["requires_ack"] is False
