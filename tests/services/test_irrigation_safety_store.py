"""Irrigation safety persistence does not depend on Recorder."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.domain.irrigation_safety import ControllerState
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


async def test_fault_survives_restart_and_ack_is_audited(hass: HomeAssistant) -> None:
    """A fresh manager sees the latch, and acknowledgement records its HA user."""
    store = IrrigationSafetyStore(hass, "entry")
    fault = await store.async_latch(
        "tent",
        "fault_off_unconfirmed:switch.pump",
        "Pump remained on",
        ("switch.pump",),
    )
    restarted = IrrigationSafetyStore(hass, "entry")
    await restarted.async_load()
    assert restarted.fault_for("tent", ("switch.pump",)) == fault
    await restarted.async_acknowledge("tent", "admin-user")
    assert restarted.fault_for("tent", ("switch.pump",)) is None
    assert restarted.ledger[-1]["user_id"] == "admin-user"

    third = IrrigationSafetyStore(hass, "entry")
    await third.async_load()
    assert third.fault_for("tent", ("switch.pump",)) is None
    assert [row["action"] for row in third.ledger] == ["fault", "acknowledge"]


async def test_restarted_fault_blocks_scheduled_and_manual_cycles(
    hass: HomeAssistant,
) -> None:
    """The loaded latch gates both routes before a switch command."""
    original = IrrigationSafetyStore(hass, "blocked")
    await original.async_latch(
        "tent",
        "fault_off_unconfirmed:switch.pump",
        "Pump remained on",
        ("switch.pump",),
    )
    restarted = IrrigationSafetyStore(hass, "blocked")
    await restarted.async_load()
    runtime = MagicMock()
    runtime.irrigation_safety = restarted
    runtime.growspaces = {
        "tent": Growspace(
            id="tent",
            name="Tent",
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity="switch.pump", irrigation_duration=5
            ),
        )
    }
    fake_hass = MagicMock()
    fake_hass.services.async_call = AsyncMock()
    entry = MagicMock(runtime_data=runtime)
    coordinator = IrrigationCoordinator(fake_hass, entry, "tent", runtime)
    await coordinator._run_pump_cycle("irrigation", "switch.pump", 5, {})
    fake_hass.services.async_call.assert_not_awaited()
    with pytest.raises(ServiceValidationError, match="fault"):
        await coordinator.async_manual_run(5)


async def test_emergency_stop_survives_restart_and_precedes_fault(
    hass: HomeAssistant,
) -> None:
    """The later operator control can latch this state without losing a fault."""
    store = IrrigationSafetyStore(hass, "emergency-stop")
    await store.async_latch(
        "tent", "fault_off_unconfirmed:switch.pump", "pump stayed on", ("switch.pump",)
    )
    stop = await store.async_latch_emergency_stop(
        "tent", "Operator stopped irrigation", ("switch.pump",)
    )
    assert (
        await store.async_latch_emergency_stop(
            "tent", "Operator stopped irrigation", ("switch.pump",)
        )
        == stop
    )
    restarted = IrrigationSafetyStore(hass, "emergency-stop")
    await restarted.async_load()
    assert restarted.emergency_stop_for("tent") == stop
    assert restarted.fault_for("tent", ("switch.pump",)) is not None
    runtime = MagicMock()
    runtime.irrigation_safety = restarted
    runtime.growspaces = {
        "tent": Growspace(
            id="tent",
            name="Tent",
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity="switch.pump", irrigation_duration=5
            ),
        )
    }
    fake_hass = MagicMock()
    fake_hass.services.async_call = AsyncMock()
    coordinator = IrrigationCoordinator(
        fake_hass, MagicMock(runtime_data=runtime), "tent", runtime
    )
    assert coordinator.controller_snapshot().state is ControllerState.EMERGENCY_STOP
    await coordinator._run_pump_cycle("irrigation", "switch.pump", 5, {})
    fake_hass.services.async_call.assert_not_awaited()
    assert restarted.ledger[-1]["action"] == "emergency_stop"


async def test_emergency_stop_can_hold_a_growspace_without_outputs(
    hass: HomeAssistant,
) -> None:
    """The future global stop can latch an empty growspace before it is wired."""
    store = IrrigationSafetyStore(hass, "empty-stop")
    stop = await store.async_latch_emergency_stop("tent", "Operator stop", ())
    restarted = IrrigationSafetyStore(hass, "empty-stop")
    await restarted.async_load()
    assert restarted.emergency_stop_for("tent") == stop


async def test_concurrent_faults_keep_every_affected_output(
    hass: HomeAssistant,
) -> None:
    """A second failing output extends the latch that acknowledgement checks."""
    store = IrrigationSafetyStore(hass, "two-outputs")
    first = await store.async_latch(
        "tent", "fault_on_unconfirmed:switch.feed", "feed", ("switch.feed",)
    )
    second = await store.async_latch(
        "tent", "fault_off_unconfirmed:switch.drain", "drain", ("switch.drain",)
    )
    assert (
        await store.async_latch(
            "tent", "fault_off_unconfirmed:switch.drain", "drain", ("switch.drain",)
        )
        == second
    )
    assert second.fault_id == first.fault_id
    assert second.outputs == ("switch.feed", "switch.drain")
    restarted = IrrigationSafetyStore(hass, "two-outputs")
    await restarted.async_load()
    assert restarted.fault_for("tent", ()) == second


async def test_corrupt_record_fails_closed(hass: HomeAssistant) -> None:
    """A malformed persisted fault never silently re-arms a pump."""
    store = IrrigationSafetyStore(hass, "broken")
    await store._store.async_save({"faults": {"tent": {"fault_id": "x"}}, "ledger": []})
    restarted = IrrigationSafetyStore(hass, "broken")
    await restarted.async_load()
    assert restarted.unreadable
    assert (
        restarted.fault_for("tent", ("switch.pump",)).reason.code
        == "fault_record_unreadable"
    )


@pytest.mark.parametrize(
    "document",
    [
        {},
        {"faults": {}, "ledger": ["invalid"]},
        {"faults": {}, "emergency_stops": []},
        {"faults": {}, "emergency_stops": {"tent": {"fault_id": "x"}}},
        {
            "faults": {},
            "controls": {"tent": {"automation": "on", "irrigation_armed": True}},
        },
    ],
)
async def test_malformed_safety_documents_fail_closed(
    hass: HomeAssistant, document: dict[str, object]
) -> None:
    """Missing maps, bad ledgers, and invalid keys never discard a safety hold."""
    store = IrrigationSafetyStore(hass, "malformed")
    await store._store.async_save(document)
    restarted = IrrigationSafetyStore(hass, "malformed")
    await restarted.async_load()
    assert restarted.unreadable
    assert restarted.fault_for("tent", ("switch.pump",)) is not None


def test_decode_refuses_non_string_growspace_key() -> None:
    """The decoder refuses an invalid in-memory document before accepting faults."""
    with pytest.raises(ValueError, match="invalid growspace ID"):
        IrrigationSafetyStore._decode({"faults": {7: {}}, "ledger": []})


async def test_unreadable_file_fails_closed(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """HA Store returning None for an existing broken file still blocks actuation."""
    store = IrrigationSafetyStore(hass, "unreadable")
    path = tmp_path / store._key
    path.write_text("not-json")
    with (
        patch.object(hass.config, "path", return_value=str(path)),
        patch.object(store._store, "async_load", new=AsyncMock(return_value=None)),
    ):
        await store.async_load()
    assert store.unreadable
    assert (
        store.fault_for("tent", ("switch.pump",)).reason.code
        == "fault_record_unreadable"
    )


async def test_unreadable_record_cannot_be_rewritten_by_normal_events(
    hass: HomeAssistant,
) -> None:
    """An e-stop or transition cannot erase corrupt fault metadata on disk."""
    store = IrrigationSafetyStore(hass, "unreadable-write")
    store.unreadable = True
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_latch_emergency_stop("tent", "Operator stop", ())
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_record_transition("tent", "running")
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_record_not_delivered(
            "tent",
            "switch.pump",
            "on_unconfirmed",
            "no ON",
            consecutive=1,
            off_confirmed=True,
        )
    assert not store.ledger


async def test_not_delivered_cycle_survives_restart(hass: HomeAssistant) -> None:
    """A failed-closed cycle is a durable ledger row, not a Recorder event."""
    store = IrrigationSafetyStore(hass, "not-delivered")
    await store.async_record_not_delivered(
        "tent",
        "switch.pump",
        "on_command_failed",
        "switch.pump refused turn_on: gone",
        consecutive=2,
        off_confirmed=False,
    )
    restarted = IrrigationSafetyStore(hass, "not-delivered")
    await restarted.async_load()
    (row,) = restarted.ledger
    assert row == {
        "at": row["at"],
        "growspace_id": "tent",
        "action": "cycle_not_delivered",
        "output": "switch.pump",
        "reason_code": "on_command_failed",
        "detail": "switch.pump refused turn_on: gone",
        "consecutive": 2,
        "off_confirmed": False,
    }


async def test_transitions_are_deduplicated_and_bounded(hass: HomeAssistant) -> None:
    """A stable state writes once and the ring retains only the newest 500 rows."""
    store = IrrigationSafetyStore(hass, "transitions")
    assert await store.async_record_transition("tent", "ready")
    assert not await store.async_record_transition("tent", "ready")
    assert len(store.ledger) == 1
    for index in range(510):
        await store.async_record_transition("tent", "running" if index % 2 else "ready")
    assert len(store.ledger) == 500
    restarted = IrrigationSafetyStore(hass, "transitions")
    await restarted.async_load()
    assert len(restarted.ledger) == 500


async def test_failed_acknowledgement_write_keeps_latch(hass: HomeAssistant) -> None:
    """A storage failure cannot report success or leave a phantom ack row."""
    store = IrrigationSafetyStore(hass, "ack-failure")
    fault = await store.async_latch(
        "tent", "fault_on_unconfirmed:switch.pump", "failed", ("switch.pump",)
    )
    prior_ledger = list(store.ledger)
    with (
        patch.object(
            store._store, "async_save", new=AsyncMock(side_effect=OSError("disk full"))
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await store.async_acknowledge("tent", "admin")
    assert store.fault_for("tent", ()) == fault
    assert list(store.ledger) == prior_ledger


@pytest.mark.parametrize(
    "operation",
    ["first_fault", "second_output", "emergency_stop", "transition", "not_delivered"],
)
async def test_failed_safety_writes_fail_closed(
    hass: HomeAssistant, operation: str
) -> None:
    """A failed write leaves a closed gate even when its audit row was not saved."""
    store = IrrigationSafetyStore(hass, f"write-failure-{operation}")
    if operation == "second_output":
        await store.async_latch(
            "tent", "fault_on_unconfirmed", "feed", ("switch.feed",)
        )
    failing_write = {
        "first_fault": lambda: store.async_latch(
            "tent", "fault_on_unconfirmed", "feed", ("switch.feed",)
        ),
        "second_output": lambda: store.async_latch(
            "tent", "fault_off_unconfirmed", "drain", ("switch.drain",)
        ),
        "emergency_stop": lambda: store.async_latch_emergency_stop(
            "tent", "Operator stop", ()
        ),
        "transition": lambda: store.async_record_transition("tent", "running"),
        "not_delivered": lambda: store.async_record_not_delivered(
            "tent",
            "switch.feed",
            "on_unconfirmed",
            "no ON",
            consecutive=1,
            off_confirmed=True,
        ),
    }[operation]
    with (
        patch.object(
            store._store, "async_save", new=AsyncMock(side_effect=OSError("disk full"))
        ),
        pytest.raises(OSError, match="disk full"),
    ):
        await failing_write()
    assert store.unreadable
    assert store.fault_for("tent", ("switch.feed",)) is not None
