"""Every pump command is read back, and a disagreement fails closed (#785).

The pump here is a scripted fake switch on a clock only the test advances: it
reports ON and OFF a chosen number of seconds after each command, or never, or
refuses the command outright. The OFF readback is the real one, with its real
1 s / 0.5 s / 6 s window, so these tests measure the timing the issue specifies
rather than a stub's.
"""

import asyncio
from collections import deque
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager import actuator_driver
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.domain.irrigation_safety import (
    FaultRecord,
    SafetyReason,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    OFF_RETRY_INTERVAL,
    IrrigationCoordinator,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from custom_components.growspace_manager.reliability_store import ReliabilityStore
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"
PUMP = "switch.irrigation_pump"
FLOW_ML_PER_SEC = 100.0
START_TIME = "2026-01-12 12:00:00"
ON_WAIT = 10.0
_COORDINATOR = "custom_components.growspace_manager.irrigation_coordinator"


@dataclass
class FakeSwitch:
    """A pump that reports each commanded state after a scripted delay.

    ``on_after`` / ``off_after`` are the seconds between a command and the
    report; ``None`` means the report never comes. ``on_error`` / ``off_error``
    make that command raise instead of being accepted. ``state`` is what it reports
    before any command.
    """

    on_after: float | None = 0.0
    off_after: float | None = 0.0
    on_error: Exception | None = None
    off_error: Exception | None = None
    now: float = 0.0
    state: str = "off"
    pending: list[tuple[float, str]] = field(default_factory=list)
    commands: list[tuple[float, str]] = field(default_factory=list)

    def advance(self, seconds: float) -> None:
        """Move the clock, delivering every report that falls due."""
        self.now += seconds
        for due, state in sorted(self.pending):
            if due <= self.now:
                self.state = state
        self.pending = [(due, s) for due, s in self.pending if due > self.now]

    def command(self, service: str) -> None:
        """Receive turn_on / turn_off."""
        self.commands.append((self.now, service))
        error = self.on_error if service == "turn_on" else self.off_error
        if error is not None:
            raise error
        delay = self.on_after if service == "turn_on" else self.off_after
        target = "on" if service == "turn_on" else "off"
        # A new command supersedes a report still in flight for the old one.
        self.pending = []
        if delay is not None:
            self.pending.append((self.now + delay, target))
        self.advance(0)


@pytest.fixture
def coordinator() -> IrrigationCoordinator:
    """Build a coordinator over a growspace with a known pump flow rate."""
    hass = MagicMock(spec=HomeAssistant)
    type(hass).loop = property(lambda self: asyncio.get_running_loop())
    hass.services = AsyncMock()
    hass.bus = MagicMock()
    hass.states = MagicMock()
    hass.data = {DOMAIN: {}}

    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = ENTRY_ID
    entry.options = {}

    main = MagicMock()
    main.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Test Growspace",
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity=PUMP,
                pump_flow_rate_ml_per_sec=FLOW_ML_PER_SEC,
            ),
        )
    }
    main.async_commit = AsyncMock()
    safety = IrrigationSafetyStore.__new__(IrrigationSafetyStore)
    safety.faults = {}
    safety.emergency_stops = {}
    safety.controls = {GROWSPACE_ID: {"automation": True, "irrigation_armed": True}}
    safety.ledger = deque(maxlen=500)
    safety.unreadable = False
    safety._store = MagicMock()
    safety._store.async_save = AsyncMock()
    main.irrigation_safety = safety
    entry.runtime_data = main

    return IrrigationCoordinator(hass, entry, GROWSPACE_ID, main)


@dataclass
class CycleRun:
    """What one or more cycles did."""

    slept: list[float]
    record_water: AsyncMock
    retry_ticks: list[Any]
    services: list[tuple[str, str]]
    latched_at: list[float]


async def _run_cycles(
    coordinator: IrrigationCoordinator,
    switch: FakeSwitch,
    *,
    cycles: int = 1,
    duration: int = 30,
) -> CycleRun:
    """Run scheduled irrigation cycles against ``switch`` and a fake clock."""
    record_water = AsyncMock()
    slept: list[float] = []
    retry_ticks: list[Any] = []
    services: list[tuple[str, str]] = []
    latched_at: list[float] = []

    with freeze_time(START_TIME) as clock:

        def advance(seconds: float) -> None:
            clock.tick(seconds)
            switch.advance(seconds)

        async def fake_sleep(seconds: float) -> None:
            slept.append(seconds)
            advance(seconds)

        async def fake_on_wait(
            entity_id: str, target_state: str, timeout: float = ON_WAIT
        ) -> bool:
            # The event-driven ON wait: returns as soon as ON is reported.
            if switch.state == target_state:
                return True
            due = [d for d, s in switch.pending if s == target_state]
            if due and due[0] - switch.now <= timeout:
                advance(due[0] - switch.now)
                return True
            advance(timeout)
            return False

        async def fake_service_call(domain: str, service: str, *_a, **_k) -> None:
            services.append((domain, service))
            if domain == "switch":
                switch.command(service)

        coordinator.hass.services.async_call = AsyncMock(side_effect=fake_service_call)
        coordinator.hass.states.get.side_effect = lambda entity_id: (
            SimpleNamespace(state=switch.state) if entity_id == PUMP else None
        )
        real_latch = coordinator._latch_fault

        async def timed_latch(*args: Any) -> None:
            latched_at.append(switch.now)
            await real_latch(*args)

        with (
            patch("asyncio.sleep", new=fake_sleep),
            patch(
                f"{_COORDINATOR}.async_confirm_state",
                new=actuator_driver.async_confirm_state,
            ),
            patch(f"{_COORDINATOR}.async_call_later", return_value=lambda: None),
            patch(
                f"{_COORDINATOR}.async_track_time_interval",
                side_effect=lambda _h, action, interval: (
                    retry_ticks.append((action, interval)) or (lambda: None)
                ),
            ),
            patch.object(coordinator, "_async_wait_for_switch_state", new=fake_on_wait),
            patch.object(coordinator, "_async_record_pump_water", new=record_water),
            patch.object(coordinator, "_async_spawn_settling_report", MagicMock()),
            patch.object(coordinator, "_latch_fault", new=timed_latch),
            patch("homeassistant.helpers.issue_registry.async_create_issue"),
        ):
            for _ in range(cycles):
                await coordinator._run_pump_cycle(
                    "irrigation", PUMP, duration, {"time": "10:00:00"}
                )

    return CycleRun(slept, record_water, retry_ticks, services, latched_at)


def _liters(seconds: float) -> float:
    """Litres a pump at the fixture's flow rate delivers in ``seconds``."""
    return seconds * FLOW_ML_PER_SEC / 1000.0


def _not_delivered(coordinator: IrrigationCoordinator) -> list[dict[str, Any]]:
    store = coordinator._safety_store
    assert store is not None
    return [row for row in store.ledger if row["action"] == "cycle_not_delivered"]


def _turn_ons(run: CycleRun) -> int:
    return run.services.count(("switch", "turn_on"))


@pytest.mark.parametrize(
    ("switch", "expected"),
    [
        (
            FakeSwitch(),
            {
                "irrigation.fired": 1,
                "irrigation.completed_verified": 1,
                "runtime.estimated_water_l": 3,
                f"runtime.automated_seconds.{PUMP}": 30,
            },
        ),
        (
            FakeSwitch(on_error=HomeAssistantError("relay refused")),
            {"irrigation.command_failure.on": 1},
        ),
        (FakeSwitch(on_after=None), {"irrigation.readback.on_unconfirmed": 1}),
        (
            FakeSwitch(off_after=None),
            {
                "irrigation.readback.off_unconfirmed": 1,
                "irrigation.completed_unverified": 1,
            },
        ),
    ],
)
async def test_reliability_counts_pump_effect_paths(
    coordinator: IrrigationCoordinator, switch: FakeSwitch, expected: dict[str, int]
) -> None:
    """Each observed command and readback outcome has one durable counter."""
    reliability = ReliabilityStore.__new__(ReliabilityStore)
    reliability._data = {}
    reliability.unreadable = False
    reliability._lock = asyncio.Lock()
    reliability._store = MagicMock()
    reliability._store.async_save = AsyncMock()
    coordinator._main_coordinator.reliability = reliability
    await _run_cycles(coordinator, switch)
    counters = reliability.snapshot(GROWSPACE_ID)["lifetime"]
    assert counters["irrigation.requested"] == 1
    for key, value in expected.items():
        assert counters[key] == value


async def test_confirmed_cycle_is_delivered(
    coordinator: IrrigationCoordinator,
) -> None:
    """A pump that confirms both ways books the whole shot and nothing else."""
    run = await _run_cycles(coordinator, FakeSwitch(on_after=2.0, off_after=0.3))

    assert run.slept[0] == 30
    run.record_water.assert_awaited_once_with(pytest.approx(_liters(30)))
    assert coordinator.cycles_today == 1
    assert coordinator.last_cycle_timestamp is not None
    assert not coordinator.controller_snapshot().requires_ack
    assert _not_delivered(coordinator) == []


async def test_slow_pump_off_report_does_not_latch_false_fault(
    coordinator: IrrigationCoordinator,
) -> None:
    """A Zigbee plug that reports OFF 1.6 s late is read back, not faulted."""
    run = await _run_cycles(coordinator, FakeSwitch(off_after=1.6))

    assert not coordinator.controller_snapshot().requires_ack
    assert run.latched_at == []
    # Read at 1.0 and 1.5 (still ON), confirmed at 2.0.
    assert run.slept[1:] == [1.0, 0.5, 0.5]
    assert coordinator.cycles_today == 1


async def test_a_pump_that_never_reports_off_still_latches_and_within_seconds(
    coordinator: IrrigationCoordinator,
) -> None:
    """A switch that refuses OFF latches within 6 s, and no cycle starts after."""
    switch = FakeSwitch(off_after=None)
    run = await _run_cycles(coordinator, switch, cycles=2)

    off_commanded_at = next(t for t, s in switch.commands if s == "turn_off")
    assert run.latched_at == [pytest.approx(off_commanded_at + 6.0)]
    snapshot = coordinator.controller_snapshot()
    assert snapshot.requires_ack
    assert snapshot.reasons[0].code == f"fault_off_unconfirmed:{PUMP}"
    # The second scheduled cycle never commanded the pump.
    assert _turn_ons(run) == 1


async def test_unconfirmed_off_retries_notifies_and_keeps_retrying(
    coordinator: IrrigationCoordinator,
) -> None:
    """OFF is re-sent at once, a notification goes out, and a minute loop starts."""
    run = await _run_cycles(coordinator, FakeSwitch(off_after=None))

    # The cycle's own OFF, then the immediate retry.
    assert run.services.count(("switch", "turn_off")) == 2
    notification = next(
        call.args[2]
        for call in coordinator.hass.services.async_call.await_args_list
        if call.args[:2] == ("persistent_notification", "create")
    )
    assert PUMP in notification["message"]
    assert [interval for _, interval in run.retry_ticks] == [OFF_RETRY_INTERVAL]


async def test_minute_retry_resends_off_until_the_pump_reads_off(
    coordinator: IrrigationCoordinator,
) -> None:
    """Each tick re-sends OFF while the pump is ON and stops once it reads OFF."""
    switch = FakeSwitch(off_after=None)
    run = await _run_cycles(coordinator, switch)
    retry, _interval = run.retry_ticks[0]
    cancelled = MagicMock()
    coordinator._off_retries[PUMP] = cancelled
    services = coordinator.hass.services.async_call

    services.reset_mock()
    await retry(None)
    assert [call.args[1] for call in services.await_args_list] == ["turn_off"]
    cancelled.assert_not_called()

    switch.state = "off"
    services.reset_mock()
    await retry(None)
    services.assert_not_awaited()
    cancelled.assert_called_once()
    assert PUMP not in coordinator._off_retries
    # Reading OFF again re-arms nothing: the fault waits for an acknowledgement.
    assert coordinator.controller_snapshot().requires_ack


async def test_turn_on_raising_is_stopped_read_back_and_not_counted(
    coordinator: IrrigationCoordinator,
) -> None:
    """A refused ON commands OFF, reads it back and books nothing."""
    switch = FakeSwitch(on_error=HomeAssistantError("relay unavailable"))
    run = await _run_cycles(coordinator, switch)

    assert [s for _, s in switch.commands] == ["turn_on", "turn_off"]
    # The OFF readback ran: its first read waited a second.
    assert run.slept == [1.0]
    run.record_water.assert_not_awaited()
    assert coordinator.cycles_today == 0
    assert coordinator.volume_dispensed_today == 0
    assert coordinator.last_cycle_timestamp is None
    (row,) = _not_delivered(coordinator)
    assert row["reason_code"] == "on_command_failed"
    assert row["output"] == PUMP
    assert row["consecutive"] == 1
    assert row["off_confirmed"] is True
    assert "relay unavailable" in row["detail"]
    assert not coordinator.controller_snapshot().requires_ack


async def test_unconfirmed_on_is_stopped_and_not_delivered(
    coordinator: IrrigationCoordinator,
) -> None:
    """ON that never reports within the wait commands OFF and books nothing."""
    switch = FakeSwitch(on_after=None)
    run = await _run_cycles(coordinator, switch)

    assert [s for _, s in switch.commands] == ["turn_on", "turn_off"]
    assert switch.commands[1][0] == pytest.approx(ON_WAIT)
    assert 30 not in run.slept
    run.record_water.assert_not_awaited()
    assert coordinator.cycles_today == 0
    assert coordinator.last_cycle_timestamp is None
    (row,) = _not_delivered(coordinator)
    assert row["reason_code"] == "on_unconfirmed"
    assert not coordinator.controller_snapshot().requires_ack


async def test_third_consecutive_unconfirmed_on_latches_a_fault(
    coordinator: IrrigationCoordinator,
) -> None:
    """N consecutive on_unconfirmed cycles latch; the fault then holds the pump."""
    run = await _run_cycles(coordinator, FakeSwitch(on_after=None), cycles=4)

    assert [row["consecutive"] for row in _not_delivered(coordinator)] == [1, 2, 3]
    snapshot = coordinator.controller_snapshot()
    assert snapshot.requires_ack
    assert snapshot.reasons[0].code == f"fault_on_unconfirmed:{PUMP}"
    assert "3 consecutive cycles" in snapshot.reasons[0].detail
    assert _turn_ons(run) == 3


async def test_repeated_turn_on_refusals_latch_under_their_own_code(
    coordinator: IrrigationCoordinator,
) -> None:
    """The latched code names the last failure's kind."""
    await _run_cycles(
        coordinator, FakeSwitch(on_error=HomeAssistantError("gone")), cycles=3
    )
    assert coordinator.controller_snapshot().reasons[0].code == (
        f"fault_on_command_failed:{PUMP}"
    )


async def test_a_confirmed_cycle_between_resets_the_count(
    coordinator: IrrigationCoordinator,
) -> None:
    """Two failures, a delivered cycle, two failures: never three in a row."""
    await _run_cycles(coordinator, FakeSwitch(on_after=None), cycles=2)
    await _run_cycles(coordinator, FakeSwitch())
    await _run_cycles(coordinator, FakeSwitch(on_after=None), cycles=2)

    assert [row["consecutive"] for row in _not_delivered(coordinator)] == [1, 2, 1, 2]
    assert not coordinator.controller_snapshot().requires_ack
    assert coordinator.cycles_today == 1


async def test_unconfirmed_on_whose_off_also_fails_latches_the_off_fault(
    coordinator: IrrigationCoordinator,
) -> None:
    """An offline pump answers neither command and is held on the OFF one."""
    await _run_cycles(
        coordinator, FakeSwitch(state="unavailable", on_after=None, off_after=None)
    )

    assert coordinator.controller_snapshot().reasons[0].code == (
        f"fault_off_unconfirmed:{PUMP}"
    )
    (row,) = _not_delivered(coordinator)
    assert row["off_confirmed"] is False


async def test_refused_turn_off_latches_when_the_pump_stays_on(
    coordinator: IrrigationCoordinator,
) -> None:
    """A refused OFF is judged by the readback, and this pump is still ON."""
    switch = FakeSwitch(off_error=HomeAssistantError("switch unavailable"))
    await _run_cycles(coordinator, switch)

    assert coordinator.controller_snapshot().reasons[0].code == (
        f"fault_off_unconfirmed:{PUMP}"
    )


async def test_refused_turn_off_is_no_fault_when_the_pump_reads_off(
    coordinator: IrrigationCoordinator,
) -> None:
    """An OFF that errored but landed is what the readback says it is."""
    switch = FakeSwitch(off_error=HomeAssistantError("timed out"))
    original = switch.command

    def lands_then_raises(service: str) -> None:
        if service == "turn_off":
            switch.state = "off"
        original(service)

    switch.command = lands_then_raises  # type: ignore[method-assign]
    await _run_cycles(coordinator, switch)

    assert not coordinator.controller_snapshot().requires_ack


async def test_open_failures_are_counted_without_a_safety_store(
    coordinator: IrrigationCoordinator,
) -> None:
    """A legacy fixture without a store still fails closed and still counts."""
    coordinator._main_coordinator.irrigation_safety = None
    await _run_cycles(coordinator, FakeSwitch(on_after=None), cycles=3)
    assert coordinator._open_failures[PUMP] == 3


def _latched(
    coordinator: IrrigationCoordinator, code: str, outputs: tuple[str, ...]
) -> None:
    store = coordinator._safety_store
    assert store is not None
    store.faults[GROWSPACE_ID] = FaultRecord(
        "f1", SafetyReason(code, "stuck", "2026-01-12T12:00:00+00:00"), outputs
    )


@pytest.mark.parametrize(
    ("code", "pump_state", "resumes"),
    [
        (f"fault_off_unconfirmed:{PUMP}", "on", True),
        (f"fault_watchdog_off_unconfirmed:{PUMP}", "unavailable", True),
        (f"fault_off_unconfirmed:{PUMP}", "off", False),
        (f"fault_on_unconfirmed:{PUMP}", "on", False),
    ],
)
def test_restart_resumes_off_retry_only_for_a_pump_not_reading_off(
    coordinator: IrrigationCoordinator, code: str, pump_state: str, resumes: bool
) -> None:
    """A latched OFF disagreement keeps being stopped across a restart."""
    _latched(coordinator, code, (PUMP,))
    coordinator.hass.states.get.return_value = SimpleNamespace(state=pump_state)
    with patch(
        f"{_COORDINATOR}.async_track_time_interval", return_value=lambda: None
    ) as track:
        coordinator._resume_off_retries()
        coordinator._resume_off_retries()
    assert track.call_count == (1 if resumes else 0)


def test_restart_without_a_fault_starts_no_retry(
    coordinator: IrrigationCoordinator,
) -> None:
    """Nothing latched, nothing to keep stopping."""
    coordinator._resume_off_retries()
    assert coordinator._off_retries == {}


def test_teardown_cancels_off_retries(coordinator: IrrigationCoordinator) -> None:
    """Unloading the coordinator stops its retry loops; a schedule reload does not."""
    cancel = MagicMock()
    coordinator._off_retries[PUMP] = cancel
    coordinator.async_cancel_listeners(cancel_tasks=False)
    cancel.assert_not_called()
    coordinator.async_cancel_listeners(cancel_tasks=True)
    cancel.assert_called_once()
    assert coordinator._off_retries == {}


def test_controller_snapshot_tracks_idle_ready_inhibited_and_running(
    coordinator: IrrigationCoordinator,
) -> None:
    """Transient state and reason codes come from the same cycle gate."""
    assert coordinator.controller_snapshot().state.value == "idle"
    config = coordinator.growspace.irrigation_config
    config.irrigation_times = [{"time": "10:00:00"}]
    ready = coordinator.controller_snapshot()
    assert ready.state.value == "ready"
    assert ready.since is None
    config.max_cycles_per_day = 0
    inhibited = coordinator.controller_snapshot()
    assert inhibited.state.value == "inhibited"
    assert inhibited.reasons[0].code == "cap_cycles"
    assert (
        coordinator.controller_snapshot().reasons[0].since == inhibited.reasons[0].since
    )
    coordinator._active_events["irrigation"] = {"start": "now", "duration": 5}
    assert coordinator.controller_snapshot().state.value == "running"
