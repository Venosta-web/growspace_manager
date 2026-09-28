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
    AttemptState,
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


async def _flush_batch(hass: HomeAssistant, clock: FrozenDateTimeFactory) -> None:
    """Let the batched save write, however many saves it has coalesced.

    Its timer is the first delay scheduled, and a later save only moves the
    write time on; the timer checks the loop's clock against that, so the
    clock has to have moved past it, not merely the timer fired.
    """
    clock.tick(CLOSE_SAVE_DELAY_SECONDS + 1)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


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


async def test_a_request_that_cannot_be_written_commands_nothing_and_holds(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """The first write reaches disk before the ON command, or there is no command."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)

    with patch.object(
        coordinator._deliveries._store, "async_save", side_effect=OSError("disk full")
    ):
        await _shot(hass, coordinator)

    assert pump == []
    assert coordinator.cycles_today == 0
    assert coordinator.controller_snapshot().fault_id == DELIVERY_RECORD_UNREADABLE
    assert ir.async_get(hass).async_get_issue(
        DOMAIN, f"irrigation_fault_{GROWSPACE_ID}"
    )
    (attempt,) = coordinator._deliveries.attempts
    assert attempt.outcome is AttemptOutcome.ABORTED
    assert attempt.abort_cause == "error"
    assert attempt.on_commanded_at is None
    assert not attempt.off_confirmed


async def test_a_charge_that_cannot_be_written_stops_the_shot_and_holds(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """The charge reaches disk before the cycle proceeds, or the cycle does not."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)

    # The request is written; the charge at confirm-ON is not.
    with patch.object(
        coordinator._deliveries._store,
        "async_save",
        side_effect=[None, OSError("disk full")],
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


async def test_the_request_is_on_disk_before_the_on_command(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """At the moment turn_on is called, the open attempt is already stored."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)
    seen: list[dict[str, Any]] = []

    async def command(call: ServiceCall) -> None:
        if call.service == "turn_on":
            seen.extend(hass_storage[KEY]["data"]["attempts"])
        hass.states.async_set(PUMP, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("switch", "turn_on", command)
    hass.services.async_register("switch", "turn_off", command)
    await _shot(hass, coordinator)

    (stored,) = seen
    assert stored["state"] == "requested"
    assert stored["requested_at"] == _at("08:00").isoformat()
    assert stored["on_commanded_at"] is None
    assert stored["charged_l"] == 0.0
    assert stored["planned_s"] == SHOT_S
    assert stored["flow_rate_ml_per_sec"] == 10.0
    (after,) = hass_storage[KEY]["data"]["attempts"]
    assert after["attempt_id"] == stored["attempt_id"]
    assert after["state"] == "actuated"
    assert after["charged_l"] == pytest.approx(0.3)


async def test_a_crash_before_confirm_on_leaves_an_open_attempt(
    hass: HomeAssistant, clock: FrozenDateTimeFactory
) -> None:
    """Commanded, then Home Assistant stopped: the next start finds it open."""
    clock.move_to(_at("08:00"))
    before = await _start(hass)
    commanded = asyncio.Event()
    stopped = asyncio.Event()

    async def never_confirms(*_: Any, **__: Any) -> bool:
        commanded.set()
        await stopped.wait()
        return False

    with patch.object(before, "_async_wait_for_switch_state", new=never_confirms):
        task = hass.async_create_task(
            before._run_pump_cycle("irrigation", PUMP, SHOT_S, {})
        )
        await commanded.wait()

        after = await _start(hass)

        (attempt,) = after._deliveries.attempts
        assert attempt.state is AttemptState.REQUESTED
        assert attempt.is_open
        assert after.cycles_today == 0
        stopped.set()
        await task


async def test_a_pump_that_never_reads_on_is_not_delivered_and_uncharged(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """No ON readback: stopped, read back OFF, closed with the reason."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)

    with patch.object(
        coordinator, "_async_wait_for_switch_state", new=AsyncMock(return_value=False)
    ):
        await _shot(hass, coordinator)

    (attempt,) = coordinator._deliveries.attempts
    assert attempt.outcome is AttemptOutcome.NOT_DELIVERED
    assert attempt.reason == "on_unconfirmed"
    assert attempt.on_commanded_at == _at("08:00")
    assert attempt.off_commanded_at is not None
    assert attempt.off_confirmed
    assert attempt.not_delivered_window == (_at("08:00"), attempt.off_confirmed_at)
    assert coordinator.cycles_today == 0
    assert coordinator.volume_dispensed_today == 0.0

    await _flush_batch(hass, clock)
    (stored,) = hass_storage[KEY]["data"]["attempts"]
    assert stored["not_delivered_window"] == {
        "start": _at("08:00").isoformat(),
        "end": stored["off_confirmed_at"],
    }


async def test_every_moment_of_a_shot_is_recorded(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, hass_storage: dict[str, Any]
) -> None:
    """Requested, ON commanded and read, OFF commanded and read: all five."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)
    await _shot(hass, coordinator)
    await _flush_batch(hass, clock)

    (stored,) = hass_storage[KEY]["data"]["attempts"]
    assert stored["state"] == "closed"
    assert stored["outcome"] == "completed"
    for moment in (
        "requested_at",
        "on_commanded_at",
        "on_confirmed_at",
        "off_commanded_at",
        "off_confirmed_at",
    ):
        assert stored[moment] is not None, moment
    assert datetime.fromisoformat(stored["off_commanded_at"]) == _at("08:00") + (
        timedelta(seconds=SHOT_S)
    )
    assert stored["charged_l"] == pytest.approx(0.3)
    assert stored["estimated_l"] == pytest.approx(0.3)
    assert stored["evidence"] == "estimated"


async def test_a_run_of_refusals_is_one_suppressed_row(
    hass: HomeAssistant,
    clock: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    pump: list[str],
) -> None:
    """Three shots over the limit are one row: the reason, a count, first and last."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)
    for _ in range(3):
        await _shot(hass, coordinator)
    pump.clear()

    for clock_time in ("09:00", "10:00", "11:00"):
        clock.move_to(_at(clock_time))
        await _shot(hass, coordinator)

    assert pump == []
    assert coordinator.cycles_today == 3
    *_, refused = coordinator._deliveries.attempts
    assert len(coordinator._deliveries.attempts) == 4
    assert refused.outcome is AttemptOutcome.SUPPRESSED
    assert refused.reason == "cycle_limit"
    assert refused.suppressed_count == 3
    assert refused.requested_at == _at("09:00")
    assert refused.last_requested_at == _at("11:00")
    assert refused.charged_l == 0.0

    # Batched, like a close: on disk after the next save, not before.
    assert all(
        row["outcome"] != "suppressed" for row in hass_storage[KEY]["data"]["attempts"]
    )
    await _flush_batch(hass, clock)
    stored = hass_storage[KEY]["data"]["attempts"][-1]
    assert stored["outcome"] == "suppressed"
    assert stored["suppressed_count"] == 3

    # And it survives a restart as the same row.
    after = await _start(hass)
    assert after._deliveries.attempts[-1] == refused
    assert after.cycles_today == 3


async def test_an_operator_hold_is_a_suppressed_attempt(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """Irrigation disarmed refuses a scheduled shot, and the refusal is recorded."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)
    safety = IrrigationSafetyStore(hass, ENTRY_ID)
    await safety.async_load()
    coordinator._main_coordinator.irrigation_safety = safety

    await _shot(hass, coordinator, time="08:00:00")

    assert pump == []
    (attempt,) = coordinator._deliveries.attempts
    assert attempt.outcome is AttemptOutcome.SUPPRESSED
    assert attempt.reason == "irrigation_disarmed"
    assert attempt.trigger is AttemptTrigger.SCHEDULE
    assert attempt.trigger_evidence.slot == "08:00:00"


async def _drain(hass: HomeAssistant, coordinator: IrrigationCoordinator) -> None:
    await coordinator._run_pump_cycle("drain", PUMP, SHOT_S, {"time": "22:00:00"})
    await hass.async_block_till_done()


async def test_a_refused_drain_is_a_suppressed_drain_attempt(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """Irrigation disarmed holds a scheduled drain, and the refusal is recorded."""
    clock.move_to(_at("22:00"))
    coordinator = await _start(hass)
    safety = IrrigationSafetyStore(hass, ENTRY_ID)
    await safety.async_load()
    coordinator._main_coordinator.irrigation_safety = safety

    await _drain(hass, coordinator)

    assert pump == []
    (attempt,) = coordinator._deliveries.attempts
    assert attempt.outcome is AttemptOutcome.SUPPRESSED
    assert attempt.reason == "irrigation_disarmed"
    assert attempt.trigger is AttemptTrigger.DRAIN
    assert attempt.trigger_evidence.slot == "22:00:00"


async def test_a_drain_is_an_attempt_that_never_charges(
    hass: HomeAssistant,
    clock: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    pump: list[str],
) -> None:
    """Written before ON, actuated, closed: and no cycle, no litres, no estimate."""
    clock.move_to(_at("22:00"))
    coordinator = await _start(hass)
    seen: list[dict[str, Any]] = []

    async def command(call: ServiceCall) -> None:
        if call.service == "turn_on":
            seen.extend(hass_storage[KEY]["data"]["attempts"])
        hass.states.async_set(PUMP, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("switch", "turn_on", command)
    hass.services.async_register("switch", "turn_off", command)
    await _drain(hass, coordinator)

    (requested,) = seen
    assert requested["state"] == "requested"
    assert requested["trigger"] == "drain"
    assert coordinator.cycles_today == 0
    assert coordinator.volume_dispensed_today == 0.0
    assert coordinator.last_cycle_timestamp is None

    await _flush_batch(hass, clock)
    (stored,) = hass_storage[KEY]["data"]["attempts"]
    assert stored["attempt_id"] == requested["attempt_id"]
    assert stored["trigger_evidence"] == {"slot": "22:00:00"}
    assert stored["outcome"] == "completed"
    assert stored["on_confirmed_at"] is not None
    assert stored["off_confirmed_at"] is not None
    assert stored["charge_date"] is None
    assert stored["charged_l"] == 0.0
    assert stored["estimated_l"] is None
    assert stored["flow_rate_ml_per_sec"] == 0.0

    # And a restart reads it back without charging it.
    after = await _start(hass)
    assert after.cycles_today == 0


async def test_a_drain_at_the_daily_limit_still_runs_and_moves_no_cap(
    hass: HomeAssistant, clock: FrozenDateTimeFactory, pump: list[str]
) -> None:
    """The caps neither hold a drain nor count it: the limit stays where it was."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)
    for _ in range(3):
        await _shot(hass, coordinator)
    volume = coordinator.volume_dispensed_today
    pump.clear()

    clock.move_to(_at("22:00"))
    await _drain(hass, coordinator)

    assert pump == ["turn_on", "turn_off"]
    assert coordinator.cycles_today == 3
    assert coordinator.volume_dispensed_today == pytest.approx(volume)
    drain = coordinator._deliveries.attempts[-1]
    assert drain.trigger is AttemptTrigger.DRAIN
    assert drain.outcome is AttemptOutcome.COMPLETED


@pytest.mark.parametrize(
    ("event_data", "trigger", "evidence"),
    [
        ({"time": "08:00:00"}, "schedule", {"slot": "08:00:00"}),
        (
            {
                "phase": "p2",
                "vwc": 42.5,
                "base_seconds": 25,
                "vwc_factor": 1.2,
                "ec_factor": 0.8,
            },
            "steering",
            {
                "phase": "p2",
                "vwc": 42.5,
                "base_s": 25.0,
                "vwc_factor": 1.2,
                "ec_factor": 0.8,
            },
        ),
        ({"manual": True, "user_id": "user-1"}, "manual", {"user_id": "user-1"}),
    ],
    ids=["schedule", "steering", "manual"],
)
async def test_each_trigger_leaves_its_evidence_on_the_stored_attempt(
    hass: HomeAssistant,
    clock: FrozenDateTimeFactory,
    hass_storage: dict[str, Any],
    event_data: dict[str, Any],
    trigger: str,
    evidence: dict[str, Any],
) -> None:
    """The slot, the steering decision, or the person, as written to disk."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)

    await _shot(hass, coordinator, **event_data)

    (stored,) = hass_storage[KEY]["data"]["attempts"]
    assert stored["trigger"] == trigger
    assert stored["trigger_evidence"] == evidence


async def test_a_manual_run_records_who_asked(
    hass: HomeAssistant, clock: FrozenDateTimeFactory
) -> None:
    """run_irrigation_cycle's caller reaches the attempt through async_manual_run."""
    clock.move_to(_at("08:00"))
    coordinator = await _start(hass)
    coordinator._config_entry.async_create_background_task = lambda hass, target, name: (
        hass.async_create_task(target)
    )

    await coordinator.async_manual_run(SHOT_S, user_id="user-1")
    await hass.async_block_till_done()

    (attempt,) = coordinator._deliveries.attempts
    assert attempt.trigger is AttemptTrigger.MANUAL
    assert attempt.trigger_evidence.user_id == "user-1"


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
