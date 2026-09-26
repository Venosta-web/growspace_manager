"""The daily caps survive a restart and reset at local midnight (#787, ADR-0054).

Each case runs real pump cycles on a real Home Assistant with frozen time, the
pump a switch that follows its commands. A restart is a new
``DeliveryAttemptStore`` reading what the last one wrote, and a new coordinator
set up on it: nothing in memory crosses over.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.delivery_attempt_store import (
    CLOSE_SAVE_DELAY_SECONDS,
    DeliveryAttemptStore,
    DeliveryRecordUnreadable,
    GrowspaceDeliveries,
)
from custom_components.growspace_manager.domain.delivery_attempt import (
    DELIVERY_RECORD_UNREADABLE,
    AttemptOutcome,
    AttemptTrigger,
)
from custom_components.growspace_manager.domain.irrigation_safety import ControllerState
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from tests.delivery_helpers import charged_attempt

GROWSPACE_ID = "gs1"
ENTRY_ID = "entry1"
PUMP = "switch.pump"
KEY = f"growspace_manager.deliveries_{ENTRY_ID}_{GROWSPACE_ID}"
# 30 s at 10 ml/s: 0.3 L a shot.
SHOT_S = 30

_REAL_SLEEP = asyncio.sleep


def _at(clock: str, day: str = "2026-09-25") -> datetime:
    return datetime.fromisoformat(f"{day}T{clock}:00+00:00")


@pytest.fixture(autouse=True)
async def pump(hass: HomeAssistant) -> list[str]:
    """A switch that reads back whatever it was last told."""
    commands: list[str] = []
    hass.states.async_set(PUMP, "off")

    async def command(call: ServiceCall) -> None:
        commands.append(call.service)
        hass.states.async_set(PUMP, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("switch", "turn_on", command)
    hass.services.async_register("switch", "turn_off", command)
    return commands


@pytest.fixture
def clock(freezer: FrozenDateTimeFactory) -> Any:
    """Make a shot's sleep take its seconds on the frozen clock, instantly."""

    async def sleep(seconds: float, *_: Any) -> None:
        freezer.tick(seconds)
        await _REAL_SLEEP(0)

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.asyncio.sleep",
        new=sleep,
    ):
        yield freezer


def _growspace(**config: Any) -> Growspace:
    return Growspace(
        id=GROWSPACE_ID,
        name="Tent",
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity=PUMP,
            irrigation_duration=SHOT_S,
            pump_flow_rate_ml_per_sec=10.0,
            **config,
        ),
    )


async def _start(
    hass: HomeAssistant, growspace: Growspace | None = None
) -> IrrigationCoordinator:
    """Start Home Assistant's side of one growspace the way setup does."""
    main = MagicMock()
    main.growspaces = {GROWSPACE_ID: growspace or _growspace(max_cycles_per_day=3)}
    main.async_commit = AsyncMock()
    main.deliveries = DeliveryAttemptStore(hass, ENTRY_ID)
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.runtime_data = main
    coordinator = IrrigationCoordinator(hass, entry, GROWSPACE_ID, main)
    await coordinator._async_load_deliveries()
    return coordinator


async def _shot(
    hass: HomeAssistant, coordinator: IrrigationCoordinator, **event_data: Any
) -> None:
    await coordinator._run_pump_cycle("irrigation", PUMP, SHOT_S, event_data)
    await hass.async_block_till_done()


async def test_cycles_charged_before_a_restart_still_hold_the_limit(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """After 3 of 3 cycles and a restart, cycles_today is 3 and the 4th is refused."""
    clock.move_to(_at("08:00"))
    before = await _start(hass)
    for _ in range(3):
        await _shot(hass, before)
    assert before.cycles_today == 3

    clock.move_to(_at("12:00"))
    after = await _start(hass)

    assert after.cycles_today == 3
    assert after.volume_dispensed_today == pytest.approx(0.9)
    pump.clear()
    await _shot(hass, after)
    assert pump == []
    assert after.cycles_today == 3


async def test_the_volume_cap_after_a_restart_is_the_persisted_dispensed_volume(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """0.6 L of a 0.8 L cap survives, so a third 0.3 L shot is refused."""
    growspace = _growspace(daily_volume_cap_liters=0.8)
    clock.move_to(_at("08:00"))
    before = await _start(hass, growspace)
    await _shot(hass, before)
    await _shot(hass, before)

    after = await _start(hass, growspace)
    pump.clear()
    await _shot(hass, after)

    assert after.volume_dispensed_today == pytest.approx(0.6)
    assert pump == []


async def test_a_day_that_ended_while_home_assistant_was_down_starts_at_zero(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """Charged up to the limit at 23:00, down over midnight, back at 06:00."""
    clock.move_to(_at("23:00"))
    before = await _start(hass)
    for _ in range(3):
        await _shot(hass, before)

    clock.move_to(_at("06:00", day="2026-09-26"))
    after = await _start(hass)

    assert after.cycles_today == 0
    assert after.volume_dispensed_today == 0.0
    pump.clear()
    await _shot(hass, after)
    assert pump == ["turn_on", "turn_off"]
    assert after.cycles_today == 1


async def test_a_restart_mid_shot_keeps_the_shot_counted(
    hass: HomeAssistant, clock: FrozenDateTimeFactory
) -> None:
    """The charge is on disk from confirm-ON; a shot that never closed still counts."""
    clock.move_to(_at("08:00"))
    before = await _start(hass)
    mid_shot = asyncio.Event()
    stopped = asyncio.Event()

    async def shot_in_progress(seconds: float, *_: Any) -> None:
        if seconds == SHOT_S:
            mid_shot.set()
            await stopped.wait()

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.asyncio.sleep",
        new=shot_in_progress,
    ):
        task = hass.async_create_task(
            before._run_pump_cycle("irrigation", PUMP, SHOT_S, {})
        )
        await mid_shot.wait()
        assert before._deliveries.attempts[0].is_open

        after = await _start(hass)

        assert after.cycles_today == 1
        assert after.volume_dispensed_today == pytest.approx(0.3)
        assert after._deliveries.attempts[0].is_open
        stopped.set()
        await task


async def test_an_aborted_shot_costs_the_cap_its_plan_and_books_what_ran(
    hass: HomeAssistant, clock: FrozenDateTimeFactory
) -> None:
    """Cancelled 5 s into 30 s: the cap keeps 0.3 L, the water shows 0.05 L."""
    growspace = _growspace()
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass, growspace)

    cut = False

    async def cut_short(seconds: float, *_: Any) -> None:
        # The shot is cancelled 5 s in; the OFF readback then sleeps as usual.
        nonlocal cut
        if not cut:
            cut = True
            clock.tick(5)
            raise asyncio.CancelledError
        clock.tick(seconds)

    with patch(
        "custom_components.growspace_manager.irrigation_coordinator.asyncio.sleep",
        new=cut_short,
    ):
        await _shot(hass, coordinator)

    (attempt,) = coordinator._deliveries.attempts
    assert attempt.outcome is AttemptOutcome.ABORTED
    assert attempt.abort_cause == "cancel"
    assert attempt.off_confirmed
    assert coordinator.volume_dispensed_today == pytest.approx(0.3)
    assert growspace.water_usage.daily_readings[0]["liters"] == pytest.approx(0.05)


async def test_a_close_is_batched_and_a_charge_is_not(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """The charge is written through; the close follows in the next batch."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)
    await _shot(hass, coordinator, manual=True)

    (stored,) = hass_storage[KEY]["data"]["attempts"]
    assert stored["state"] == "actuated"
    assert stored["trigger"] == AttemptTrigger.MANUAL

    async_fire_time_changed(
        hass, dt_util.utcnow() + timedelta(seconds=CLOSE_SAVE_DELAY_SECONDS + 1)
    )
    await hass.async_block_till_done()

    (stored,) = hass_storage[KEY]["data"]["attempts"]
    assert stored["state"] == "closed"
    assert stored["outcome"] == "completed"
    assert stored["off_confirmed_at"] is not None


async def test_an_unreadable_record_holds_every_cycle_as_a_fault(
    hass: HomeAssistant,
    clock: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    pump: list[str],
) -> None:
    """A cap whose history is unknown is spent: nothing fires, and it says why."""
    clock.move_to(_at("08:00"))
    hass_storage[KEY] = {
        "version": 1,
        "key": KEY,
        "data": {"growspace_id": GROWSPACE_ID, "attempts": [{"attempt_id": 3}]},
    }
    coordinator = await _start(hass)

    snapshot = coordinator.controller_snapshot()
    assert snapshot.state is ControllerState.FAULT
    assert snapshot.fault_id == DELIVERY_RECORD_UNREADABLE
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, f"irrigation_fault_{GROWSPACE_ID}"
    )
    await _shot(hass, coordinator)
    assert pump == []
    # Never written over: the evidence stays for whoever repairs it.
    assert hass_storage[KEY]["data"]["attempts"] == [{"attempt_id": 3}]


async def test_a_charge_that_cannot_be_written_stops_the_shot_and_holds(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """The write reaches disk before the cycle proceeds, or the cycle does not."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)

    with patch.object(
        coordinator._deliveries._store, "async_save", side_effect=OSError("disk full")
    ):
        await _shot(hass, coordinator)

    assert pump == ["turn_on", "turn_off"]
    # The pump did confirm ON, so the shot is charged in memory all the same.
    assert coordinator.cycles_today == 1
    assert coordinator.controller_snapshot().fault_id == DELIVERY_RECORD_UNREADABLE
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, f"irrigation_fault_{GROWSPACE_ID}"
    )
    pump.clear()
    await _shot(hass, coordinator)
    assert pump == []


async def test_a_file_that_exists_but_loads_nothing_fails_closed(
    hass: HomeAssistant, clock: FrozenDateTimeFactory
) -> None:
    """Storage reporting no data for a file that is there is not an empty day."""
    deliveries = GrowspaceDeliveries(GROWSPACE_ID, hass=hass, entry_id=ENTRY_ID)
    with patch(
        "custom_components.growspace_manager.delivery_attempt_store.exists",
        return_value=True,
    ):
        await deliveries.async_load()

    assert deliveries.unreadable
    with pytest.raises(DeliveryRecordUnreadable):
        await deliveries.async_charge(charged_attempt(GROWSPACE_ID, liters=0.3))
    assert deliveries.dispensed().cycles == 1


@pytest.mark.parametrize(
    "data",
    [
        {"growspace_id": "someone-else", "attempts": []},
        {"growspace_id": GROWSPACE_ID, "attempts": "none"},
        {
            "growspace_id": GROWSPACE_ID,
            "attempts": [charged_attempt("someone-else", attempt_id="x").as_dict()],
        },
        {
            "growspace_id": GROWSPACE_ID,
            "attempts": [
                charged_attempt(GROWSPACE_ID, attempt_id="x").as_dict(),
                charged_attempt(GROWSPACE_ID, attempt_id="x").as_dict(),
            ],
        },
    ],
    ids=["other-growspace", "no-list", "misfiled-attempt", "duplicate-id"],
)
async def test_a_document_that_is_not_this_growspaces_is_unreadable(
    hass: HomeAssistant, hass_storage: dict[str, Any], data: dict[str, Any]
) -> None:
    """The whole document is validated before any attempt in it counts."""
    hass_storage[KEY] = {"version": 1, "key": KEY, "data": data}
    deliveries = GrowspaceDeliveries(GROWSPACE_ID, hass=hass, entry_id=ENTRY_ID)

    await deliveries.async_load()

    assert deliveries.unreadable
    assert deliveries.attempts == []


async def test_a_charge_prunes_rows_past_retention(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A week-old row is gone from the next write; today's stay."""
    clock.move_to(_at("08:00"))
    old = charged_attempt(
        GROWSPACE_ID,
        at=_at("08:00", day="2026-09-10"),
        day=datetime(2026, 9, 10).date(),
        attempt_id="old",
    )
    hass_storage[KEY] = {
        "version": 1,
        "key": KEY,
        "data": {"growspace_id": GROWSPACE_ID, "attempts": [old.as_dict()]},
    }
    deliveries = GrowspaceDeliveries(GROWSPACE_ID, hass=hass, entry_id=ENTRY_ID)
    await deliveries.async_load()

    await deliveries.async_charge(charged_attempt(GROWSPACE_ID, attempt_id="new"))

    stored = hass_storage[KEY]["data"]["attempts"]
    assert [row["attempt_id"] for row in stored] == ["new"]


async def test_a_rebuilt_coordinator_shares_the_growspaces_attempts(
    hass: HomeAssistant,
) -> None:
    """The entry loads a growspace once, so a pending close is never lost."""
    store = DeliveryAttemptStore(hass, ENTRY_ID)

    first = await store.async_load(GROWSPACE_ID)
    second = await store.async_load(GROWSPACE_ID)

    assert first is second


async def test_removing_a_growspace_deletes_its_attempts(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """A removed growspace's file does not linger unread."""
    clock.move_to(_at("08:00"))
    store = DeliveryAttemptStore(hass, ENTRY_ID)
    deliveries = await store.async_load(GROWSPACE_ID)
    await deliveries.async_charge(charged_attempt(GROWSPACE_ID))
    assert KEY in hass_storage

    await store.async_remove(GROWSPACE_ID)
    assert KEY not in hass_storage

    # One this entry never loaded goes too.
    hass_storage[KEY] = {"version": 1, "key": KEY, "data": {}}
    await store.async_remove(GROWSPACE_ID)
    assert KEY not in hass_storage


async def test_memory_only_attempts_charge_and_close_without_a_file() -> None:
    """Legacy isolated fixtures keep their caps in memory and write nothing."""
    deliveries = GrowspaceDeliveries(GROWSPACE_ID)
    attempt = charged_attempt(GROWSPACE_ID, liters=0.3)

    await deliveries.async_load()
    await deliveries.async_charge(attempt)
    deliveries.close(
        attempt.closed(off_commanded_at=attempt.on_confirmed_at + timedelta(seconds=1))
    )
    await deliveries.async_remove()

    assert deliveries.loaded
    assert deliveries.attempts == []


async def test_an_admin_acknowledgement_starts_the_record_again(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Acknowledged, the unreadable file is rewritten and the ledger names who."""
    clock.move_to(_at("08:00"))
    hass_storage[KEY] = {"version": 1, "key": KEY, "data": "garbage"}
    coordinator = await _start(hass)
    safety = IrrigationSafetyStore(hass, ENTRY_ID)
    await safety.async_load()
    coordinator._main_coordinator.irrigation_safety = safety
    assert coordinator.controller_snapshot().fault_id == DELIVERY_RECORD_UNREADABLE

    await coordinator._async_acknowledge_deliveries("admin")

    assert coordinator.controller_snapshot().fault_id is None
    assert hass_storage[KEY]["data"] == {"growspace_id": GROWSPACE_ID, "attempts": []}
    assert safety.ledger[-1]["action"] == "acknowledge"
    assert safety.ledger[-1]["fault_id"] == DELIVERY_RECORD_UNREADABLE
    assert safety.ledger[-1]["user_id"] == "admin"


async def test_an_acknowledgement_that_cannot_be_written_stays_held(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """The fault clears only once the fresh record is on disk."""
    clock.move_to(_at("08:00"))
    hass_storage[KEY] = {"version": 1, "key": KEY, "data": "garbage"}
    coordinator = await _start(hass)

    with (
        patch.object(
            coordinator._deliveries._store, "async_save", side_effect=OSError("disk")
        ),
        pytest.raises(DeliveryRecordUnreadable),
    ):
        await coordinator._async_acknowledge_deliveries("admin")

    assert coordinator.controller_snapshot().fault_id == DELIVERY_RECORD_UNREADABLE
    assert hass_storage[KEY]["data"] == "garbage"
