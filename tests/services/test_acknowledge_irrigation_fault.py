"""Administrator re-arm requires every affected output to read OFF."""

from __future__ import annotations

from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.domain.irrigation_safety import (
    FaultRecord,
    SafetyReason,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.services.irrigation import (
    handle_acknowledge_fault,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def context() -> tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore]:
    """Build the narrow service boundary with a persisted latch."""
    hass = MagicMock()
    hass.auth.async_get_user = AsyncMock(
        return_value=MagicMock(is_admin=True, id="admin")
    )
    hass.states.get.return_value.state = "off"
    coordinator = MagicMock()
    irrigation = MagicMock()
    irrigation._configured_outputs.return_value = ("switch.pump",)
    coordinator.services.growspaces.get_irrigation_coordinator.return_value = irrigation
    store = IrrigationSafetyStore.__new__(IrrigationSafetyStore)
    store.faults = {
        "tent": FaultRecord(
            "fault-1",
            SafetyReason("fault_off_unconfirmed:switch.pump", "pump stayed on", "now"),
            ("switch.pump",),
        )
    }
    store.emergency_stops = {}
    store.controls = {}
    store.ledger = deque(maxlen=500)
    store.unreadable = False
    store._unreadable_since = None
    store._store = MagicMock()
    store._store.async_save = AsyncMock()
    coordinator.irrigation_safety = store
    call = MagicMock()
    call.context.user_id = "admin"
    call.data = {"growspace_id": "tent"}
    return hass, coordinator, call, store


@pytest.mark.parametrize("state", ["on", "unknown", "unavailable"])
async def test_ack_refuses_output_not_off(
    context: tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore],
    state: str,
) -> None:
    """A non-OFF readback names the entity and leaves its latch intact."""
    hass, coordinator, call, store = context
    hass.states.get.return_value.state = state
    with pytest.raises(ServiceValidationError, match="switch.pump"):
        await handle_acknowledge_fault(hass, coordinator, call)
    assert "tent" in store.faults
    store._store.async_save.assert_not_awaited()


async def test_ack_refuses_non_admin(
    context: tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore],
) -> None:
    """An ordinary HA user cannot re-arm a pump."""
    hass, coordinator, call, store = context
    hass.auth.async_get_user.return_value.is_admin = False
    with pytest.raises(ServiceValidationError, match="admin"):
        await handle_acknowledge_fault(hass, coordinator, call)
    assert "tent" in store.faults


async def test_ack_refuses_when_there_is_no_fault(
    context: tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore],
) -> None:
    """An admin cannot create a spurious acknowledgement audit row."""
    hass, coordinator, call, store = context
    store.faults.clear()
    with pytest.raises(ServiceValidationError, match="no latched fault"):
        await handle_acknowledge_fault(hass, coordinator, call)
    store._store.async_save.assert_not_awaited()


async def test_ack_names_second_affected_output(
    context: tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore],
) -> None:
    """An earlier OFF output cannot hide another output still ON."""
    hass, coordinator, call, store = context
    first = store.faults["tent"]
    store.faults["tent"] = FaultRecord(
        first.fault_id, first.reason, ("switch.pump", "switch.drain")
    )
    hass.states.get.side_effect = lambda entity: MagicMock(
        state="on" if entity == "switch.drain" else "off"
    )
    with pytest.raises(ServiceValidationError, match="switch.drain"):
        await handle_acknowledge_fault(hass, coordinator, call)
    assert "tent" in store.faults


async def test_ack_off_clears_and_audits_user(
    context: tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore],
) -> None:
    """A checked admin acknowledgement is durable and clears the repair."""
    hass, coordinator, call, store = context
    with patch(
        "custom_components.growspace_manager.services.irrigation.async_delete_issue"
    ) as delete:
        await handle_acknowledge_fault(hass, coordinator, call)
    assert store.fault_for("tent", ("switch.pump",)) is None
    assert store.ledger[-1]["user_id"] == "admin"
    store._store.async_save.assert_awaited_once()
    delete.assert_called_once()


async def test_unreadable_record_rearms_only_after_off_check(
    context: tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore],
) -> None:
    """Corrupt metadata stays held until the admin verifies the current outputs."""
    hass, coordinator, call, store = context
    store.unreadable = True
    store.faults.clear()
    coordinator.growspaces = {}
    hass.states.get.return_value.state = "on"
    with pytest.raises(ServiceValidationError, match="switch.pump"):
        await handle_acknowledge_fault(hass, coordinator, call)
    assert store.unreadable
    hass.states.get.return_value.state = "off"
    with patch(
        "custom_components.growspace_manager.services.irrigation.async_delete_issue"
    ):
        await handle_acknowledge_fault(hass, coordinator, call)
    assert not store.unreadable
    assert store.ledger[-1]["fault_id"] == "fault_record_unreadable"


async def test_unreadable_record_checks_other_growspaces_outputs(
    context: tuple[HomeAssistant, MagicMock, MagicMock, IrrigationSafetyStore],
) -> None:
    """Corrupt metadata cannot hide an ON output under another growspace."""
    hass, coordinator, call, store = context
    store.unreadable = True
    store.faults.clear()
    other = MagicMock()
    other.irrigation_config.irrigation_pump_entity = "switch.other"
    other.irrigation_config.drain_pump_entity = None
    coordinator.growspaces = {"other": other}
    hass.states.get.side_effect = lambda entity: MagicMock(
        state="on" if entity == "switch.other" else "off"
    )
    with pytest.raises(ServiceValidationError, match="switch.other"):
        await handle_acknowledge_fault(hass, coordinator, call)
    assert store.unreadable
