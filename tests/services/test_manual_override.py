"""A person operating the equipment is noticed and respected (#793).

Real Home Assistant state, services and timers. The pump is a switch whose
state follows its commands, as a device's would — or, when ``stuck``, does not;
a person is someone setting its state directly. Readback is the real one with
its waits taken out, so what is asserted is what was read back.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from functools import partial
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed
import voluptuous as vol

from custom_components.growspace_manager import actuator_driver
from custom_components.growspace_manager.circulation_fan_coordinator import (
    CirculationFanCoordinator,
)
from custom_components.growspace_manager.const import (
    EVENT_GROWSPACE_LOG_ENTRY,
    FanRegulationMode,
    NotificationTier,
)
from custom_components.growspace_manager.domain.irrigation_safety import ControllerState
from custom_components.growspace_manager.domain.manual_override import (
    MAX_REASON_LENGTH,
    ManualOverride,
    Subsystem,
    UnexpectedOnPolicy,
)
from custom_components.growspace_manager.exhaust_fan_coordinator import (
    ExhaustFanCoordinator,
)
from custom_components.growspace_manager.irrigation_coordinator import (
    IrrigationCoordinator,
)
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import (
    CirculationFanConfig,
    EnvironmentConfig,
    ExhaustFanConfig,
    Growspace,
    IrrigationConfig,
)
from custom_components.growspace_manager.reliability_store import ReliabilityStore
from custom_components.growspace_manager.services.safety import (
    CLEAR_OVERRIDE_SCHEMA,
    SET_OVERRIDE_SCHEMA,
    handle_clear_override,
    handle_set_override,
)
from homeassistant.core import Context, HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.storage import Store
from tests.common import async_mock_service

PUMP = "switch.pump"
DRAIN = "switch.drain"
EXHAUST = "fan.exhaust"
CIRCULATION = "fan.circulation"
HUMIDITY = "sensor.humidity"
_COORDINATOR = "custom_components.growspace_manager.irrigation_coordinator"
_TARGETS = "custom_components.growspace_manager.services.safety._targets"


@pytest.fixture(autouse=True)
def instant_readback() -> Iterator[None]:
    """Read back once, at once: the fake pump answers inside its command."""
    with patch(
        f"{_COORDINATOR}.async_confirm_state",
        new=partial(actuator_driver.async_confirm_state, first_read=0, poll=0),
    ):
        yield


@pytest.fixture(autouse=True)
def notices(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    return {
        service: async_mock_service(hass, "persistent_notification", service)
        for service in ("create", "dismiss")
    }


@dataclass
class Pump:
    """A switch that follows its commands, unless ``stuck``."""

    hass: HomeAssistant
    stuck: bool = False
    commands: list[str] = field(default_factory=list)

    def register(self) -> None:
        for service in ("turn_on", "turn_off"):
            self.hass.services.async_register("switch", service, self._command)
        self.hass.states.async_set(PUMP, "off")

    async def _command(self, call: ServiceCall) -> None:
        self.commands.append(call.service)
        if not self.stuck:
            self.hass.states.async_set(
                call.data["entity_id"], call.service.removeprefix("turn_")
            )

    async def person(self, state: str) -> None:
        """Someone at the relay, not Growspace Manager."""
        self.hass.states.async_set(PUMP, state)
        await self.hass.async_block_till_done()

    @property
    def state(self) -> str:
        state = self.hass.states.get(PUMP)
        assert state is not None
        return state.state


@dataclass
class Tent:
    """One growspace with a pump, its safety store and irrigation coordinator."""

    hass: HomeAssistant
    growspace: Growspace
    runtime: MagicMock
    irrigation: IrrigationCoordinator
    pump: Pump

    @property
    def store(self) -> IrrigationSafetyStore:
        store: IrrigationSafetyStore = self.runtime.irrigation_safety
        return store

    @property
    def notify(self) -> AsyncMock:
        manager = self.runtime.services.notifications.manager
        return manager.async_send_notification  # type: ignore[no-any-return]

    def ledger(self, action: str) -> list[dict[str, Any]]:
        return [row for row in self.store.ledger if row["action"] == action]

    def counter(self, name: str) -> float:
        lifetime = self.runtime.reliability.snapshot("tent")["lifetime"]
        return float(lifetime.get(name, 0))

    def state(self) -> tuple[ControllerState, str | None]:
        snapshot = self.irrigation.controller_snapshot()
        return snapshot.state, snapshot.reasons[0].code if snapshot.reasons else None

    async def start(self) -> None:
        await self.irrigation._async_begin_startup_inhibit()
        await self.hass.async_block_till_done()

    async def restart(self, key: str) -> None:
        """Stop, load the store from disk, and start a new coordinator on it."""
        self.irrigation.async_cancel_listeners()
        self.store.async_stop_overrides()
        restarted = IrrigationSafetyStore(self.hass, key)
        await restarted.async_load()
        await restarted.async_start_overrides()
        self.runtime.irrigation_safety = restarted
        self.irrigation = _coordinator(self.hass, self.runtime)
        await self.start()


def _coordinator(hass: HomeAssistant, runtime: MagicMock) -> IrrigationCoordinator:
    entry = MagicMock(runtime_data=runtime)
    entry.async_create_background_task = lambda hass, coro, name: (
        hass.async_create_task(coro, name)
    )
    return IrrigationCoordinator(hass, entry, "tent", runtime)


async def _tent(
    hass: HomeAssistant,
    key: str,
    policy: UnexpectedOnPolicy = UnexpectedOnPolicy.ALERT,
) -> Tent:
    growspace = Growspace(
        id="tent",
        name="Tent",
        irrigation_config=IrrigationConfig(
            irrigation_pump_entity=PUMP,
            startup_grace_minutes=0,
            unexpected_on_policy=policy.value,
        ),
    )
    growspace.irrigation_config.irrigation_times = [{"time": "10:00:00", "duration": 5}]
    store = IrrigationSafetyStore(hass, key)
    await store.async_load()
    await store.async_initialize_controls({"tent": growspace})
    await store.async_set_control("tent", "irrigation_armed", True, "operator")
    runtime = MagicMock()
    runtime.irrigation_safety = store
    runtime.reliability = ReliabilityStore(hass, key)
    runtime.growspaces = {"tent": growspace}
    runtime.services.notifications.manager.async_send_notification = AsyncMock()
    pump = Pump(hass)
    pump.register()
    return Tent(hass, growspace, runtime, _coordinator(hass, runtime), pump)


@pytest.fixture
async def tent(hass: HomeAssistant) -> AsyncIterator[Tent]:
    tent = await _tent(hass, "override")
    await tent.start()
    yield tent
    tent.irrigation.async_cancel_listeners()
    tent.store.async_stop_overrides()
    await hass.async_block_till_done()


async def _set(tent: Tent, **data: Any) -> None:
    call = MagicMock(
        data=SET_OVERRIDE_SCHEMA({"growspace_id": "tent", **data}),
        context=Context(user_id="user-1"),
    )
    with patch(_TARGETS, return_value=[(tent.runtime, "tent")]):
        await handle_set_override(tent.hass, call)
    await tent.hass.async_block_till_done()


async def _clear(tent: Tent, subsystem: str) -> None:
    call = MagicMock(
        data=CLEAR_OVERRIDE_SCHEMA({"growspace_id": "tent", "subsystem": subsystem}),
        context=Context(user_id="user-2"),
    )
    with patch(_TARGETS, return_value=[(tent.runtime, "tent")]):
        await handle_clear_override(tent.hass, call)
    await tent.hass.async_block_till_done()


# --- Unexpected On, under the default alert policy ------------------------------


async def test_a_pump_switched_on_by_hand_alerts_and_holds_automatic_irrigation(
    tent: Tent, notices: dict[str, list[ServiceCall]]
) -> None:
    assert tent.state() == (ControllerState.READY, None)

    await tent.pump.person("on")

    assert tent.state() == (ControllerState.INHIBITED, "override_detected")
    assert tent.pump.state == "on", "the alert policy never switches it off"
    assert tent.pump.commands == []
    [row] = tent.ledger("unexpected_on")
    assert (row["output"], row["policy"], row["response"]) == (PUMP, "alert", "alert")
    assert tent.ledger("transition")[-1]["reason_code"] == "override_detected"
    assert tent.counter("irrigation.readback.unexpected_on") == 1
    assert tent.counter("controller.inhibit.override_detected") == 1
    assert tent.notify.await_args.kwargs["tier"] is NotificationTier.UNEXPECTED_ON
    assert len(notices["create"]) == 1

    # A scheduled cycle is held, and leaves the pump alone.
    await tent.irrigation._run_pump_cycle("irrigation", PUMP, 5, {})
    assert tent.pump.commands == []
    assert tent.counter("irrigation.skipped.override_detected") == 1

    # So is a manual run through Growspace Manager: the pump is already running.
    with pytest.raises(ServiceValidationError, match="outside Growspace Manager"):
        await tent.irrigation.async_manual_run(5)

    # A pump that drops off the network and comes back ON is not a second person.
    await tent.pump.person("unavailable")
    await tent.pump.person("on")
    assert len(tent.ledger("unexpected_on")) == 1

    await tent.pump.person("off")

    assert tent.state() == (ControllerState.READY, None)
    assert tent.ledger("override_detected_cleared")[0]["output"] == PUMP
    assert len(notices["dismiss"]) == 1


async def test_a_cycle_of_our_own_is_not_unexpected(tent: Tent) -> None:
    with patch(f"{_COORDINATOR}.asyncio.sleep", new=AsyncMock()):
        await tent.irrigation._run_pump_cycle("irrigation", PUMP, 30, {"manual": True})
    await tent.hass.async_block_till_done()

    assert tent.pump.commands == ["turn_on", "turn_off"]
    assert tent.ledger("unexpected_on") == []
    assert tent.counter("irrigation.readback.unexpected_on") == 0
    assert tent.state() == (ControllerState.READY, None)


async def test_a_pump_already_on_is_never_confirmed_as_ours(
    hass: HomeAssistant,
) -> None:
    """Before #793 the ON wait returned at once, then the cycle switched it off."""
    tent = await _tent(hass, "already-on")
    await tent.pump.person("on")  # nothing is watching yet

    await tent.irrigation._run_pump_cycle("irrigation", PUMP, 5, {})

    assert tent.pump.commands == []
    assert tent.pump.state == "on"
    assert tent.counter("irrigation.skipped.override_detected") == 1
    assert tent.state() == (ControllerState.INHIBITED, "override_detected")


async def test_a_pump_on_at_startup_is_an_unexpected_on(hass: HomeAssistant) -> None:
    tent = await _tent(hass, "on-at-start")
    await tent.pump.person("on")
    await tent.start()
    try:
        assert tent.state() == (ControllerState.INHIBITED, "override_detected")
        assert tent.counter("irrigation.readback.unexpected_on") == 1
    finally:
        tent.irrigation.async_cancel_listeners()


# --- Unexpected On, under enforce_off ------------------------------------------


async def test_enforce_off_switches_it_off_reads_it_back_and_latches(
    hass: HomeAssistant,
) -> None:
    tent = await _tent(hass, "enforce", UnexpectedOnPolicy.ENFORCE_OFF)
    await tent.start()
    try:
        await tent.pump.person("on")

        assert tent.pump.commands == ["turn_off"]
        assert tent.pump.state == "off"
        assert tent.state() == (ControllerState.FAULT, f"fault_unexpected_on:{PUMP}")
        [row] = tent.ledger("unexpected_on")
        assert (row["response"], row["off_confirmed"]) == ("enforce_off", True)
        assert ir.async_get(hass).async_get_issue(
            "growspace_manager", "irrigation_fault_tent"
        )
        assert tent.notify.await_count == 1
        with pytest.raises(ServiceValidationError, match="fault"):
            await tent.irrigation.async_manual_run(5)
    finally:
        tent.irrigation.async_cancel_listeners()


async def test_enforce_off_that_will_not_read_off_keeps_stopping_it(
    hass: HomeAssistant,
) -> None:
    tent = await _tent(hass, "enforce-stuck", UnexpectedOnPolicy.ENFORCE_OFF)
    await tent.start()
    tent.pump.stuck = True
    try:
        await tent.pump.person("on")

        assert tent.pump.commands == ["turn_off", "turn_off"]
        assert tent.state() == (ControllerState.FAULT, f"fault_off_unconfirmed:{PUMP}")
        assert tent.ledger("unexpected_on")[0]["off_confirmed"] is False
        assert PUMP in tent.irrigation._off_retries
        # Being stopped, it is ours: reading ON again raises nothing new.
        await tent.pump.person("off")
        await tent.pump.person("on")
        assert len(tent.ledger("unexpected_on")) == 1
    finally:
        tent.irrigation.async_cancel_listeners()


async def test_enforce_off_sends_nothing_while_automation_is_off(
    hass: HomeAssistant,
) -> None:
    tent = await _tent(hass, "enforce-paused", UnexpectedOnPolicy.ENFORCE_OFF)
    await tent.store.async_set_control("tent", "automation", False, "operator")
    await tent.start()
    try:
        await tent.pump.person("on")

        assert tent.pump.commands == []
        assert tent.state() == (ControllerState.INHIBITED, "override_detected")
        assert tent.ledger("unexpected_on")[0]["response"] == "alert"
    finally:
        tent.irrigation.async_cancel_listeners()


# --- Manual Override ------------------------------------------------------------


async def test_a_30_minute_override_holds_survives_a_restart_and_expires(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    notices: dict[str, list[ServiceCall]],
) -> None:
    logbook: list[dict[str, Any]] = []
    hass.bus.async_listen(
        EVENT_GROWSPACE_LOG_ENTRY, lambda event: logbook.append(event.data)
    )
    tent = await _tent(hass, "lifecycle")
    await tent.start()
    try:
        await _set(
            tent, subsystem="irrigation", duration="00:30:00", reason="hand watering"
        )

        state, code = tent.state()
        assert (state, code) == (ControllerState.INHIBITED, "manual_override")
        assert (
            "hand watering" in tent.irrigation.controller_snapshot().reasons[0].detail
        )
        [row] = tent.ledger("override_set")
        assert (row["subsystem"], row["user_id"]) == ("irrigation", "user-1")
        assert any("HA user user-1" in entry["message"] for entry in logbook)
        attributes = tent.irrigation.controller_snapshot().attributes()
        assert attributes["overrides"][0]["reason"] == "hand watering"
        assert not tent.store.commands_allowed("tent", Subsystem.IRRIGATION)
        assert tent.store.commands_allowed("tent", Subsystem.EXHAUST)

        # Growspace Manager commands nothing, scheduled or manual.
        await tent.irrigation._run_pump_cycle("irrigation", PUMP, 5, {})
        with pytest.raises(ServiceValidationError, match="manual override"):
            await tent.irrigation.async_manual_run(5)
        # And a person running the pump now is expected, not reported.
        await tent.pump.person("on")
        assert tent.pump.commands == []
        assert tent.ledger("unexpected_on") == []
        assert tent.counter("irrigation.skipped.manual_override") == 1

        await tent.restart("lifecycle")

        assert tent.state() == (ControllerState.INHIBITED, "manual_override")
        assert tent.ledger("unexpected_on") == []

        freezer.tick(timedelta(minutes=30))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()

        assert tent.store.override_for("tent", Subsystem.IRRIGATION) is None
        assert tent.ledger("override_expired")[0]["user_id"] is None
        # The pump the person left running is now an Unexpected On.
        assert tent.state() == (ControllerState.INHIBITED, "override_detected")
        assert len(notices["create"]) == 1
        await tent.pump.person("off")
        assert tent.state() == (ControllerState.READY, None)
        assert tent.pump.commands == []
    finally:
        tent.irrigation.async_cancel_listeners()
        tent.store.async_stop_overrides()


async def test_an_override_can_be_cleared_early_and_only_once(tent: Tent) -> None:
    await _set(tent, subsystem="exhaust", duration={"minutes": 30})
    await _set(tent, subsystem="irrigation", duration={"minutes": 30})

    await _clear(tent, "irrigation")

    row = tent.ledger("override_cleared")[0]
    assert (row["subsystem"], row["user_id"]) == ("irrigation", "user-2")
    assert tent.state() == (ControllerState.READY, None)
    assert not tent.store.commands_allowed("tent", Subsystem.EXHAUST)
    with pytest.raises(ServiceValidationError, match="No manual override"):
        await _clear(tent, "irrigation")
    tent.store.unreadable = True
    with pytest.raises(ServiceValidationError, match="unreadable"):
        await _set(tent, subsystem="irrigation", duration={"minutes": 30})


async def test_setting_an_override_again_replaces_it(
    tent: Tent, freezer: FrozenDateTimeFactory
) -> None:
    await _set(tent, subsystem="lights", duration={"minutes": 10})
    await _set(tent, subsystem="lights", duration={"minutes": 60})

    freezer.tick(timedelta(minutes=11))
    async_fire_time_changed(tent.hass)
    await tent.hass.async_block_till_done()

    assert tent.store.override_for("tent", Subsystem.LIGHTS) is not None
    assert tent.ledger("override_expired") == []


async def test_an_override_that_ran_out_while_stopped_expires_at_start(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    store = IrrigationSafetyStore(hass, "ran-out")
    await store.async_load()
    await store.async_set_override(
        "tent", Subsystem.HUMIDIFIER, timedelta(minutes=5), "user-1"
    )
    store.async_stop_overrides()
    freezer.tick(timedelta(minutes=6))

    restarted = IrrigationSafetyStore(hass, "ran-out")
    await restarted.async_load()
    assert restarted.override_for("tent", Subsystem.HUMIDIFIER) is None
    await restarted.async_start_overrides()

    assert restarted.overrides == {}
    assert restarted.ledger[-1]["action"] == "override_expired"


async def test_an_irrigation_override_closes_the_cycle_in_flight(tent: Tent) -> None:
    task = tent.hass.async_create_task(
        tent.irrigation._run_pump_cycle("irrigation", PUMP, 60, {"manual": True})
    )
    tent.irrigation._running_tasks["irrigation"] = task
    for _ in range(100):
        if tent.pump.state == "on":
            break
        await asyncio.sleep(0)

    await tent.store.async_set_override(
        "tent", Subsystem.IRRIGATION, timedelta(minutes=30), "user-1"
    )
    await task
    await tent.hass.async_block_till_done()

    assert tent.pump.commands == ["turn_on", "turn_off"]
    assert tent.counter("irrigation.aborted.override") == 1
    assert tent.ledger("unexpected_on") == []
    assert tent.state() == (ControllerState.INHIBITED, "manual_override")


# --- Fans do not reassert -------------------------------------------------------


async def test_exhaust_and_circulation_stop_reasserting_during_an_override(
    hass: HomeAssistant,
) -> None:
    commanded: list[str] = []

    async def fan(call: ServiceCall) -> None:
        commanded.append(call.data["entity_id"])

    for service in ("set_percentage", "turn_on", "turn_off"):
        hass.services.async_register("fan", service, fan)
    hass.states.async_set(HUMIDITY, "80")
    for entity_id in (EXHAUST, CIRCULATION):
        hass.states.async_set(entity_id, "on", {"percentage": 50})
    growspace = Growspace(
        id="tent",
        name="Tent",
        environment_config=EnvironmentConfig(
            humidity_sensors=[HUMIDITY],
            exhaust_fan_entities=[EXHAUST],
            exhaust_fan_config=ExhaustFanConfig(enabled=True, min_speed=20),
            circulation_fan_entities=[CIRCULATION],
            circulation_fan_config=CirculationFanConfig(
                enabled=True, regulation_mode=FanRegulationMode.HUMIDITY
            ),
        ),
    )
    store = IrrigationSafetyStore(hass, "fans")
    await store.async_load()
    runtime = MagicMock()
    runtime.irrigation_safety = store
    runtime.reliability = ReliabilityStore(hass, "fans")
    runtime.growspaces = {"tent": growspace}
    runtime.options = {}
    runtime.services.growspaces.get_growspace_plants.return_value = []
    exhaust = ExhaustFanCoordinator(hass, MagicMock(), "tent", runtime)
    circulation = CirculationFanCoordinator(hass, MagicMock(), "tent", runtime)

    async def tick() -> list[str]:
        commanded.clear()
        await exhaust._async_regulate()
        await circulation._async_regulate()
        return sorted(set(commanded))

    try:
        assert await tick() == [CIRCULATION, EXHAUST]

        await store.async_set_override(
            "tent", Subsystem.EXHAUST, timedelta(minutes=30), "user-1"
        )
        assert await tick() == [CIRCULATION]

        await store.async_set_override(
            "tent", Subsystem.CIRCULATION, timedelta(minutes=30), "user-1"
        )
        assert await tick() == []

        await store.async_clear_override("tent", Subsystem.EXHAUST, "user-1")
        await store.async_clear_override("tent", Subsystem.CIRCULATION, "user-1")
        assert await tick() == [CIRCULATION, EXHAUST]
    finally:
        store.async_stop_overrides()


# --- The service schema ---------------------------------------------------------


@pytest.mark.parametrize(
    "data",
    [
        {"subsystem": "irrigation", "duration": "24:00:01"},
        {"subsystem": "irrigation", "duration": "00:00:00"},
        {"subsystem": "pumps", "duration": "00:30:00"},
        {"subsystem": "irrigation"},
        {
            "subsystem": "irrigation",
            "duration": "00:30:00",
            "reason": "x" * (MAX_REASON_LENGTH + 1),
        },
    ],
)
def test_set_override_refuses_what_it_cannot_honour(data: dict[str, Any]) -> None:
    with pytest.raises(vol.Invalid):
        SET_OVERRIDE_SCHEMA({"growspace_id": "tent", **data})


def test_set_override_takes_a_day_at_most() -> None:
    data = SET_OVERRIDE_SCHEMA(
        {"growspace_id": "tent", "subsystem": "lights", "duration": "24:00:00"}
    )
    assert data["duration"] == timedelta(hours=24)
    assert data["subsystem"] is Subsystem.LIGHTS


# --- The store refuses rather than lapses ---------------------------------------


_IRRIGATION_OVERRIDE = ManualOverride(
    Subsystem.IRRIGATION,
    datetime(2026, 9, 24, tzinfo=UTC),
    datetime(2026, 9, 24, 0, 5, tzinfo=UTC),
)


@pytest.mark.parametrize(
    "overrides",
    [
        [],
        {"tent": []},
        {"tent": {"irrigation": {"subsystem": "irrigation"}}},
        # Filed under another subsystem than its own.
        {"tent": {"exhaust": _IRRIGATION_OVERRIDE.as_dict()}},
    ],
)
async def test_a_malformed_stored_override_holds_everything(
    hass: HomeAssistant, overrides: object
) -> None:
    await Store(hass, 1, "growspace_manager.irrigation_safety_corrupt").async_save(
        {"faults": {}, "controls": {}, "overrides": overrides}
    )
    store = IrrigationSafetyStore(hass, "corrupt")
    await store.async_load()

    assert store.unreadable
    assert store.overrides == {}
    assert not store.commands_allowed("tent", Subsystem.EXHAUST)


async def test_an_unreadable_store_refuses_overrides(hass: HomeAssistant) -> None:
    store = IrrigationSafetyStore(hass, "refuses")
    await store.async_load()
    store.unreadable = True
    with pytest.raises(RuntimeError):
        await store.async_set_override(
            "tent", Subsystem.LIGHTS, timedelta(minutes=5), None
        )
    with pytest.raises(RuntimeError):
        await store.async_clear_override("tent", Subsystem.LIGHTS, None)
    with pytest.raises(RuntimeError):
        await store.async_record_event("tent", "unexpected_on")


@pytest.mark.parametrize("duration", [timedelta(0), timedelta(hours=24, seconds=1)])
async def test_the_store_refuses_an_impossible_duration(
    hass: HomeAssistant, duration: timedelta
) -> None:
    store = IrrigationSafetyStore(hass, "duration")
    await store.async_load()
    with pytest.raises(ValueError, match="24 hours"):
        await store.async_set_override("tent", Subsystem.LIGHTS, duration, None)


async def test_an_override_that_cannot_be_saved_fails_closed(
    hass: HomeAssistant,
) -> None:
    store = IrrigationSafetyStore(hass, "disk-full")
    await store.async_load()
    store._store.async_save = AsyncMock(side_effect=OSError("disk full"))  # type: ignore[method-assign]
    with pytest.raises(OSError, match="disk full"):
        await store.async_set_override(
            "tent", Subsystem.LIGHTS, timedelta(minutes=5), None
        )
    assert store.unreadable
    assert not store.commands_allowed("tent", Subsystem.EXHAUST)


async def test_an_expiry_that_cannot_be_recorded_still_stops_holding(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = IrrigationSafetyStore(hass, "expiry-refused")
    await store.async_load()
    override = await store.async_set_override(
        "tent", Subsystem.LIGHTS, timedelta(minutes=5), None
    )
    store.unreadable = True
    freezer.tick(timedelta(minutes=5))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()

    assert "Could not record the expiry" in caplog.text
    assert store.override_for("tent", Subsystem.LIGHTS) is None
    # A replaced override is not expired by the old one's timer.
    store.unreadable = False
    replacement = await store.async_set_override(
        "tent", Subsystem.LIGHTS, timedelta(minutes=5), None
    )
    await store._async_expire("tent", override)
    assert store.overrides["tent"][Subsystem.LIGHTS] == replacement
    store.async_stop_overrides()


async def test_an_override_listener_can_be_removed(hass: HomeAssistant) -> None:
    store = IrrigationSafetyStore(hass, "listener")
    await store.async_load()
    heard: list[tuple[str, Subsystem]] = []
    remove = store.add_override_listener(lambda *args: heard.append(args))
    await store.async_set_override("tent", Subsystem.LIGHTS, timedelta(minutes=5), None)
    remove()
    remove()
    await store.async_clear_override("tent", Subsystem.LIGHTS, None)
    assert heard == [("tent", Subsystem.LIGHTS)]


async def test_stopping_the_timers_leaves_the_override_persisted(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory
) -> None:
    store = IrrigationSafetyStore(hass, "stopped")
    await store.async_load()
    await store.async_set_override("tent", Subsystem.LIGHTS, timedelta(minutes=5), None)
    store.async_stop_overrides()
    freezer.tick(timedelta(minutes=6))
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert Subsystem.LIGHTS in store.overrides["tent"]
    assert [row["action"] for row in store.ledger] == ["override_set"]


# --- Edges of the pump watch ----------------------------------------------------


async def test_the_watch_follows_a_changed_pump(tent: Tent) -> None:
    await tent.pump.person("on")
    assert tent.state()[1] == "override_detected"

    tent.growspace.irrigation_config.irrigation_pump_entity = DRAIN
    hass = tent.hass
    hass.states.async_set(DRAIN, "off")
    await tent.irrigation._async_sensor_tick()

    assert tent.irrigation._watched_outputs == (DRAIN,)
    assert tent.irrigation._detected_overrides == {}
    hass.states.async_set(DRAIN, "on")
    await hass.async_block_till_done()
    assert tent.ledger("unexpected_on")[-1]["output"] == DRAIN
    hass.states.async_remove(DRAIN)
    await hass.async_block_till_done()


async def test_an_unreadable_policy_alerts_rather_than_actuates(tent: Tent) -> None:
    tent.growspace.irrigation_config.unexpected_on_policy = "switch_it_off"
    await tent.pump.person("on")
    assert tent.pump.commands == []
    assert tent.ledger("unexpected_on")[0]["policy"] == "alert"


async def test_a_ledger_that_cannot_be_written_never_blocks_the_alert(
    tent: Tent, caplog: pytest.LogCaptureFixture
) -> None:
    tent.store.async_record_event = AsyncMock(side_effect=OSError("disk full"))  # type: ignore[method-assign]
    await tent.pump.person("on")
    assert tent.notify.await_count == 1
    await tent.pump.person("off")
    assert "Could not record an unexpected ON" in caplog.text
    assert f"Could not record {PUMP} reading OFF" in caplog.text
    assert tent.state() == (ControllerState.READY, None)


async def test_an_unreadable_store_still_announces_a_person(tent: Tent) -> None:
    tent.store.unreadable = True
    await tent.pump.person("on")
    await tent.pump.person("off")
    assert tent.notify.await_count == 1
    assert tent.ledger("unexpected_on") == []


async def test_other_growspaces_and_subsystems_are_not_this_ones(tent: Tent) -> None:
    tent.irrigation._on_override_change("veg", Subsystem.IRRIGATION)
    tent.irrigation._on_override_change("tent", Subsystem.EXHAUST)
    await tent.hass.async_block_till_done()
    await tent.irrigation._async_person_finished(PUMP)
    assert tent.ledger("override_detected_cleared") == []


async def test_without_a_safety_store_a_person_is_still_noticed(
    hass: HomeAssistant,
) -> None:
    """Legacy isolated fixtures have no store; the rule does not depend on one."""
    tent = await _tent(hass, "no-store")
    tent.runtime.irrigation_safety = MagicMock()
    await tent.pump.person("on")

    await tent.irrigation._run_pump_cycle("irrigation", PUMP, 5, {})
    await tent.irrigation._async_person_finished(PUMP)

    assert tent.pump.commands == []
    assert tent.counter("irrigation.readback.unexpected_on") == 1
