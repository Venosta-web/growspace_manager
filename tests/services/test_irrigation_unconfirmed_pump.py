"""Hardware disagreements latch faults and stop future pump cycles."""

import asyncio
from collections import deque
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"
PUMP = "switch.irrigation_pump"
FLOW_ML_PER_SEC = 100.0
START_TIME = "2026-01-12 12:00:00"


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
    safety.ledger = deque(maxlen=500)
    safety.unreadable = False
    safety._store = MagicMock()
    safety._store.async_save = AsyncMock()
    main.irrigation_safety = safety
    entry.runtime_data = main

    return IrrigationCoordinator(hass, entry, GROWSPACE_ID, main)


async def _run_cycle(
    coordinator: IrrigationCoordinator,
    *,
    duration: int,
    confirmed: bool,
    wait_seconds: float,
    off_confirmed: bool = True,
    off_raises: bool = False,
) -> tuple[list[float], float, AsyncMock]:
    """Run one irrigation cycle against a clock only this test advances.

    Returns the seconds passed to every ``asyncio.sleep``, the pump's total ON
    time (turn_on call → turn_off call) and the water-recording spy.
    """
    record_water = AsyncMock()
    slept: list[float] = []

    with freeze_time(START_TIME) as clock:
        pump_on_at: list[float] = []
        elapsed = 0.0

        async def fake_wait(
            entity_id: str, target_state: str, **kwargs: object
        ) -> bool:
            nonlocal elapsed
            clock.tick(wait_seconds)
            elapsed += wait_seconds
            return confirmed if target_state == "on" else off_confirmed

        async def fake_sleep(seconds: float) -> None:
            nonlocal elapsed
            slept.append(seconds)
            clock.tick(seconds)
            elapsed += seconds

        async def fake_service_call(domain: str, service: str, *args, **kwargs) -> None:
            if service in ("turn_on", "turn_off"):
                pump_on_at.append(elapsed)
            if service == "turn_off" and off_raises:
                raise RuntimeError("switch unavailable")

        coordinator.hass.services.async_call = AsyncMock(side_effect=fake_service_call)

        with (
            patch("asyncio.sleep", new=fake_sleep),
            patch(
                "custom_components.growspace_manager.irrigation_coordinator.async_call_later",
                return_value=lambda: None,
            ),
            patch.object(coordinator, "_async_wait_for_switch_state", new=fake_wait),
            patch.object(coordinator, "_async_record_pump_water", new=record_water),
            patch.object(coordinator, "_async_spawn_settling_report", MagicMock()),
            patch("homeassistant.helpers.issue_registry.async_create_issue"),
        ):
            await coordinator._run_pump_cycle(
                "irrigation", PUMP, duration, {"time": "10:00:00"}
            )

    on_seconds = pump_on_at[-1] - pump_on_at[0]
    return slept, on_seconds, record_water


def _liters(seconds: float) -> float:
    """Litres a pump at the fixture's flow rate delivers in ``seconds``."""
    return seconds * FLOW_ML_PER_SEC / 1000.0


async def test_confirmed_switch_sleeps_the_full_duration(
    coordinator: IrrigationCoordinator,
) -> None:
    """A confirmed switch still starts the timer at the confirmation."""
    slept, on_seconds, record_water = await _run_cycle(
        coordinator, duration=30, confirmed=True, wait_seconds=2.0
    )

    assert slept == [30]
    # Timer starts at the confirmation, so the wait is on top — the device only
    # began moving water when it reported 'on'.
    assert on_seconds == pytest.approx(32.0)
    record_water.assert_awaited_once_with(pytest.approx(_liters(30)))
    assert coordinator._volume_dispensed_today == pytest.approx(_liters(30))


async def test_unconfirmed_switch_stops_without_sleeping(
    coordinator: IrrigationCoordinator,
) -> None:
    """An unconfirmed ON commands OFF immediately and latches a fault."""
    slept, on_seconds, record_water = await _run_cycle(
        coordinator, duration=30, confirmed=False, wait_seconds=10.0
    )

    assert slept == []
    assert on_seconds == pytest.approx(10.0)
    record_water.assert_not_awaited()
    assert coordinator._volume_dispensed_today == 0
    assert coordinator.controller_snapshot().requires_ack


async def test_unconfirmed_wait_longer_than_shot_still_latches(
    coordinator: IrrigationCoordinator,
) -> None:
    """A long confirmation wait never turns into a planned delivery."""
    slept, on_seconds, record_water = await _run_cycle(
        coordinator, duration=5, confirmed=False, wait_seconds=10.0
    )

    assert slept == []
    assert on_seconds == pytest.approx(10.0)
    record_water.assert_not_awaited()
    assert coordinator.controller_snapshot().fault_id is not None


async def test_unconfirmed_switch_still_turns_the_pump_off(
    coordinator: IrrigationCoordinator,
) -> None:
    """Non-confirmation always sends OFF and leaves the controller held."""
    await _run_cycle(coordinator, duration=5, confirmed=False, wait_seconds=10.0)

    services = coordinator.hass.services.async_call
    called = [(c.args[0], c.args[1]) for c in services.await_args_list]
    assert ("switch", "turn_on") in called
    assert ("switch", "turn_off") in called
    assert coordinator._cycles_today == 0
    assert coordinator.controller_snapshot().requires_ack


async def test_turn_off_command_failure_latches_fault(
    coordinator: IrrigationCoordinator,
) -> None:
    """A failed OFF service call leaves a durable hold on the controller."""
    await _run_cycle(
        coordinator, duration=5, confirmed=True, wait_seconds=0, off_raises=True
    )
    assert coordinator.controller_snapshot().requires_ack
    assert coordinator.controller_snapshot().reasons[0].code == (
        f"fault_off_unconfirmed:{PUMP}"
    )


async def test_latched_fault_blocks_later_cycle(
    coordinator: IrrigationCoordinator,
) -> None:
    """An ON mismatch blocks a later scheduled cycle before another command."""
    await _run_cycle(coordinator, duration=5, confirmed=False, wait_seconds=1.0)
    coordinator.hass.services.async_call.reset_mock()
    await coordinator._run_pump_cycle("irrigation", PUMP, 5, {})
    assert not any(
        call.args[:2] == ("switch", "turn_on")
        for call in coordinator.hass.services.async_call.await_args_list
    )


async def test_unconfirmed_off_latches_fault(
    coordinator: IrrigationCoordinator,
) -> None:
    """A completed shot still faults when OFF never confirms."""
    await _run_cycle(
        coordinator, duration=5, confirmed=True, wait_seconds=1.0, off_confirmed=False
    )
    snapshot = coordinator.controller_snapshot()
    assert snapshot.requires_ack
    assert snapshot.reasons[0].code == f"fault_off_unconfirmed:{PUMP}"


async def test_turn_on_command_failure_latches_fault(
    coordinator: IrrigationCoordinator,
) -> None:
    """A rejected ON command is a hardware fault, even if OFF then succeeds."""

    async def command(
        _domain: str, action: str, *_args: object, **_kwargs: object
    ) -> None:
        if action == "turn_on":
            raise ValueError("relay unavailable")

    coordinator.hass.services.async_call = AsyncMock(side_effect=command)
    with (
        patch.object(
            coordinator,
            "_async_wait_for_switch_state",
            new=AsyncMock(return_value=True),
        ),
        patch("homeassistant.helpers.issue_registry.async_create_issue"),
    ):
        await coordinator._run_pump_cycle("irrigation", PUMP, 5, {})
    assert (
        coordinator.controller_snapshot().reasons[0].code
        == f"fault_on_command_failed:{PUMP}"
    )


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
