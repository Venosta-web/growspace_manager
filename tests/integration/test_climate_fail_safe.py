"""The climate controllers fail safe when they cannot see, and never fight (#792).

Real Home Assistant state and real timers: a frozen sensor sends no events, so
only the controllers' own minute tick can notice it, and that tick is what
these tests drive.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.growspace_manager.climate_safety import ClimateSafety
from custom_components.growspace_manager.const import NotificationTier, PlantStage
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.exhaust_fan_coordinator import (
    ExhaustFanCoordinator,
)
from custom_components.growspace_manager.humidifier_coordinator import (
    HumidifierCoordinator,
)
from custom_components.growspace_manager.models import (
    ClimateFailSafeConfig,
    EnvironmentConfig,
    ExhaustFanConfig,
    Growspace,
)
from custom_components.growspace_manager.reliability_store import ReliabilityStore
from homeassistant.core import Event, HomeAssistant, ServiceCall
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util
from tests.common import async_mock_service

VPD = "sensor.vpd"
TEMPERATURE = "sensor.temperature"
HUMIDITY = "sensor.humidity"
HUMIDIFIER = "switch.humidifier"
DEHUMIDIFIER = "switch.dehumidifier"
EXHAUST = "fan.exhaust"

# Veg, day: the humidifier runs above 1.0 kPa, the dehumidifier below 0.6.
DRY = "1.2"
# Overlapping thresholds below put both demands on at this VPD.
BETWEEN = "1.05"


@dataclass
class Devices:
    """Switch and fan services that move the entity's state, like a device."""

    hass: HomeAssistant
    calls: list[tuple[str, str]] = field(default_factory=list)
    broken: set[str] = field(default_factory=set)
    both_on: list[str] = field(default_factory=list)

    def register(self) -> None:
        for service in ("turn_on", "turn_off"):
            self.hass.services.async_register("switch", service, self._switch)
        self.hass.services.async_register("fan", "set_percentage", self._fan)
        self.hass.states.async_set(HUMIDIFIER, "off")
        self.hass.states.async_set(DEHUMIDIFIER, "off")
        async_track_state_change_event(
            self.hass, [HUMIDIFIER, DEHUMIDIFIER], self._watch_interlock
        )

    async def _switch(self, call: ServiceCall) -> None:
        entity_id = call.data["entity_id"]
        self.calls.append((call.service, entity_id))
        if entity_id in self.broken:
            raise HomeAssistantError(f"{entity_id} did not answer")
        self.hass.states.async_set(entity_id, call.service.removeprefix("turn_"))

    async def _fan(self, call: ServiceCall) -> None:
        self.calls.append((f"set_percentage:{call.data['percentage']}", EXHAUST))

    def _watch_interlock(self, _event: Event) -> None:
        if self.is_on(HUMIDIFIER) and self.is_on(DEHUMIDIFIER):
            self.both_on.append(dt_util.utcnow().isoformat())

    def is_on(self, entity_id: str) -> bool:
        state = self.hass.states.get(entity_id)
        return state is not None and state.state == "on"

    def fan_speeds(self) -> list[int]:
        return [
            int(service.split(":")[1])
            for service, _ in self.calls
            if service.startswith("set_percentage")
        ]


@pytest.fixture
def devices(hass: HomeAssistant) -> Devices:
    devices = Devices(hass)
    devices.register()
    return devices


@pytest.fixture(autouse=True)
def notices(hass: HomeAssistant) -> dict[str, list[ServiceCall]]:
    return {
        service: async_mock_service(hass, "persistent_notification", service)
        for service in ("create", "dismiss")
    }


# Short-cycle timers off, so each test decides only what it is about.
NO_TIMERS = {"min_runtime": 0, "min_offtime": 0}


def _growspace(**fail_safe: Any) -> Growspace:
    return Growspace(
        id="tent",
        name="Tent",
        environment_config=EnvironmentConfig(
            vpd_sensor=VPD,
            humidifier_entities=[HUMIDIFIER],
            dehumidifier_entities=[DEHUMIDIFIER],
            control_humidifier=True,
            control_dehumidifier=True,
            climate_fail_safe_config=ClimateFailSafeConfig(**fail_safe),
        ),
        humidifier_config=dict(NO_TIMERS),
        dehumidifier_config=dict(NO_TIMERS),
    )


def _runtime(hass: HomeAssistant, growspace: Growspace) -> MagicMock:
    runtime = MagicMock()
    runtime.reliability = ReliabilityStore(hass, "climate-fail-safe")
    runtime.irrigation_safety.automation_enabled.return_value = True
    runtime.growspaces = {growspace.id: growspace}
    runtime.services.growspaces.get_growspace_plants.return_value = []
    runtime.services.notifications.manager.async_send_notification = AsyncMock()
    return runtime


@dataclass
class Tent:
    """One growspace's on/off controllers sharing one ClimateSafety."""

    runtime: MagicMock
    safety: ClimateSafety
    humidifier: HumidifierCoordinator
    dehumidifier: DehumidifierCoordinator

    @property
    def notify(self) -> AsyncMock:
        return self.runtime.services.notifications.manager.async_send_notification

    def counter(self, name: str) -> float:
        return self.runtime.reliability.snapshot("tent")["lifetime"].get(name, 0)

    def notes(self) -> list[list[str]]:
        return [call.args[1].reasons for call in self.runtime.add_event.call_args_list]


def _tent(hass: HomeAssistant, growspace: Growspace) -> Tent:
    runtime = _runtime(hass, growspace)
    safety = ClimateSafety(hass, growspace.id, runtime)
    return Tent(
        runtime,
        safety,
        HumidifierCoordinator(hass, MagicMock(), growspace.id, runtime, safety),
        DehumidifierCoordinator(hass, MagicMock(), growspace.id, runtime, safety),
    )


@pytest.fixture
async def tents() -> AsyncIterator[list[Tent]]:
    """Unload every controller a test started, so no tick outlives it."""
    started: list[Tent] = []
    yield started
    for tent in started:
        tent.humidifier.unload()
        tent.dehumidifier.unload()


async def _start(hass: HomeAssistant, tents: list[Tent], growspace: Growspace) -> Tent:
    tent = _tent(hass, growspace)
    tents.append(tent)
    await tent.humidifier.async_setup()
    await tent.dehumidifier.async_setup()
    await hass.async_block_till_done()
    return tent


async def _minutes(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, minutes: int
) -> None:
    """Let the controllers' minute tick run ``minutes`` times."""
    for _ in range(minutes):
        freezer.tick(timedelta(minutes=1))
        async_fire_time_changed(hass)
        await hass.async_block_till_done()


async def test_a_lost_vpd_sensor_switches_both_devices_off_and_alerts_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    notices: dict[str, list[ServiceCall]],
    tents: list[Tent],
) -> None:
    """Held through the timeout, off after it, one alert, and control resumes."""
    hass.states.async_set(VPD, DRY)
    tent = await _start(hass, tents, _growspace())
    assert devices.is_on(HUMIDIFIER)

    hass.states.async_set(VPD, "unavailable")
    await _minutes(hass, freezer, 9)
    assert devices.is_on(HUMIDIFIER)
    tent.notify.assert_not_awaited()

    await _minutes(hass, freezer, 2)
    assert not devices.is_on(HUMIDIFIER)
    assert not devices.is_on(DEHUMIDIFIER)
    tent.notify.assert_awaited_once()
    title, message = tent.notify.call_args.args[1:3]
    assert title == "⚠️ Climate Fail-Safe: Tent"
    assert "the dehumidifier is switched off; the humidifier is switched off" in (
        message
    )
    assert tent.notify.call_args.kwargs["tier"] is NotificationTier.SENSOR_INVALID
    assert notices["create"][-1].data["message"] == message
    assert [
        "Turned OFF",
        "Fail-safe: no usable reading from sensor.vpd",
    ] in tent.notes()
    assert tent.counter("climate.fail_safe.humidifier") == 1
    assert tent.counter("climate.fail_safe.dehumidifier") == 1
    assert tent.safety.is_failed(tent.humidifier._ROLE)
    assert tent.humidifier.diagnostics_snapshot()["fail_safe"] is True

    await _minutes(hass, freezer, 30)
    tent.notify.assert_awaited_once()

    hass.states.async_set(VPD, DRY)
    await hass.async_block_till_done()
    assert devices.is_on(HUMIDIFIER)
    assert tent.notify.await_count == 2
    assert tent.notify.call_args.args[1] == "✅ Climate Control Resumed: Tent"
    assert notices["dismiss"][-1].data == {
        "notification_id": "growspace_climate_fail_safe_tent"
    }


async def test_a_frozen_vpd_sensor_is_noticed_by_the_tick(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    notices: dict[str, list[ServiceCall]],
    tents: list[Tent],
) -> None:
    """No event ever arrives: stale at the 30-minute cap, safe 10 minutes later."""
    hass.states.async_set(VPD, DRY)
    tent = await _start(hass, tents, _growspace())
    assert devices.is_on(HUMIDIFIER)

    await _minutes(hass, freezer, 39)
    assert devices.is_on(HUMIDIFIER)

    await _minutes(hass, freezer, 1)
    assert not devices.is_on(HUMIDIFIER)
    tent.notify.assert_awaited_once()
    assert "since" in tent.notify.call_args.args[2]


async def test_a_sensor_that_keeps_reporting_is_never_failed(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    tents: list[Tent],
) -> None:
    """A steady value repeated is a fresh reading, not a frozen one."""
    hass.states.async_set(VPD, DRY)
    tent = await _start(hass, tents, _growspace())
    for _ in range(12):
        await _minutes(hass, freezer, 5)
        hass.states.async_set(VPD, DRY, force_update=True)
    assert devices.is_on(HUMIDIFIER)
    tent.notify.assert_not_awaited()


async def test_overlapping_thresholds_never_run_both_devices(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    tents: list[Tent],
) -> None:
    """The later demand takes over, the earlier one waits, and it is logged."""
    growspace = _growspace()
    overlap = {"day": {"on": 1.1, "off": 1.2}, "night": {"on": 1.1, "off": 1.2}}
    growspace.environment_config.dehumidifier_thresholds = {PlantStage.VEG: overlap}
    hass.states.async_set(VPD, BETWEEN)
    tent = _tent(hass, growspace)
    tents.append(tent)

    await tent.humidifier.async_setup()
    assert devices.is_on(HUMIDIFIER)

    freezer.tick(timedelta(minutes=1))
    await tent.dehumidifier.async_setup()
    assert devices.is_on(DEHUMIDIFIER)
    assert not devices.is_on(HUMIDIFIER)
    assert ["Turned OFF", "Interlock: the dehumidifier demanded later"] in (
        tent.notes()
    )

    await _minutes(hass, freezer, 10)
    assert devices.is_on(DEHUMIDIFIER)
    assert not devices.is_on(HUMIDIFIER)
    assert devices.both_on == []
    assert tent.counter("climate.interlock") == 1

    # The dehumidifier's demand ends; the humidifier's, still standing, runs
    # once its partner is off — at the latest on the next tick.
    hass.states.async_set(VPD, "1.25")
    await _minutes(hass, freezer, 1)
    assert devices.is_on(HUMIDIFIER)
    assert not devices.is_on(DEHUMIDIFIER)
    assert devices.both_on == []


async def test_a_running_device_without_demand_gives_way(
    hass: HomeAssistant, devices: Devices, tents: list[Tent]
) -> None:
    """A dehumidifier switched on by hand is switched off for a real demand."""
    hass.states.async_set(VPD, DRY)
    hass.states.async_set(DEHUMIDIFIER, "on")
    tent = await _start(hass, tents, _growspace())
    assert devices.is_on(HUMIDIFIER)
    assert not devices.is_on(DEHUMIDIFIER)
    assert ["Turned OFF", "Interlock: the humidifier demanded later"] in (tent.notes())


async def test_a_safe_state_on_takes_over_from_its_partner(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    tents: list[Tent],
) -> None:
    """A dehumidifier whose Safe State is on switches the humidifier off first."""
    hass.states.async_set(VPD, DRY)
    tent = await _start(hass, tents, _growspace(dehumidifier_safe_state="on"))
    assert devices.is_on(HUMIDIFIER)

    hass.states.async_set(VPD, "unavailable")
    await _minutes(hass, freezer, 11)
    assert devices.is_on(DEHUMIDIFIER)
    assert not devices.is_on(HUMIDIFIER)
    assert devices.both_on == []
    assert "the dehumidifier is switched on" in tent.notify.call_args.args[2]


async def test_a_safe_state_of_hold_leaves_the_device_alone(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    tents: list[Tent],
) -> None:
    """Hold is the pre-#792 behaviour, chosen explicitly; it still alerts."""
    hass.states.async_set(VPD, DRY)
    tent = await _start(hass, tents, _growspace(humidifier_safe_state="hold"))

    hass.states.async_set(VPD, "unavailable")
    await _minutes(hass, freezer, 11)
    assert devices.is_on(HUMIDIFIER)
    assert "the humidifier is left as it is" in tent.notify.call_args.args[2]


async def test_the_maximum_runtime_forces_a_break(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    tents: list[Tent],
) -> None:
    """Off at the cap, off for the minimum off time, then demand brings it back."""
    growspace = _growspace(
        humidifier_max_runtime_minutes=30, sensor_stale_after_minutes=0
    )
    growspace.humidifier_config = {"min_runtime": 0, "min_offtime": 300}
    hass.states.async_set(VPD, DRY)
    tent = await _start(hass, tents, growspace)
    assert devices.is_on(HUMIDIFIER)

    await _minutes(hass, freezer, 29)
    assert devices.is_on(HUMIDIFIER)
    await _minutes(hass, freezer, 1)
    assert not devices.is_on(HUMIDIFIER)
    assert tent.counter("climate.max_runtime_stop") == 1
    assert ["Turned OFF", "Maximum continuous runtime of 30 min reached"] in (
        tent.notes()
    )

    await _minutes(hass, freezer, 4)
    assert not devices.is_on(HUMIDIFIER)
    await _minutes(hass, freezer, 2)
    assert devices.is_on(HUMIDIFIER)


async def test_a_safe_state_overrides_the_short_cycle_timers(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    tents: list[Tent],
) -> None:
    """A device held on by its minimum runtime still goes safe on time."""
    growspace = _growspace()
    growspace.humidifier_config = {"min_runtime": 3600, "min_offtime": 0}
    hass.states.async_set(VPD, DRY)
    tent = await _start(hass, tents, growspace)
    # Below the humidifier's off threshold, above the dehumidifier's on one.
    hass.states.async_set(VPD, "0.7")
    await hass.async_block_till_done()
    assert devices.is_on(HUMIDIFIER)
    assert tent.humidifier._retry_cancel is not None

    hass.states.async_set(VPD, "unavailable")
    await _minutes(hass, freezer, 11)
    assert not devices.is_on(HUMIDIFIER)
    assert tent.humidifier._retry_cancel is None


async def test_the_runtime_cap_holds_through_a_short_dropout(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    tents: list[Tent],
) -> None:
    """An unreadable VPD does not exempt a device from its cap."""
    hass.states.async_set(VPD, DRY)
    await _start(hass, tents, _growspace(humidifier_max_runtime_minutes=5))
    hass.states.async_set(VPD, "unavailable")
    await _minutes(hass, freezer, 5)
    assert not devices.is_on(HUMIDIFIER)


async def test_a_failed_command_is_logged_and_counted(
    hass: HomeAssistant,
    devices: Devices,
    tents: list[Tent],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The device's refusal reaches the controller instead of vanishing."""
    devices.broken.add(HUMIDIFIER)
    hass.states.async_set(VPD, DRY)
    with caplog.at_level(logging.WARNING):
        tent = await _start(hass, tents, _growspace())
    assert tent.counter("climate.command_failure.humidifier") == 1
    assert "Failed to call switch.turn_on on switch.humidifier" in caplog.text


# ---------------------------------------------------------------------------
# Exhaust
# ---------------------------------------------------------------------------


def _exhaust_growspace(**fail_safe: Any) -> Growspace:
    growspace = _growspace(**fail_safe)
    env = growspace.environment_config
    env.temperature_sensors = [TEMPERATURE]
    env.humidity_sensors = [HUMIDITY]
    env.vpd_sensors = []
    env.exhaust_fan_entities = [EXHAUST]
    env.exhaust_fan_config = ExhaustFanConfig(enabled=True, min_speed=20)
    return growspace


def _exhaust(hass: HomeAssistant, growspace: Growspace) -> ExhaustFanCoordinator:
    runtime = _runtime(hass, growspace)
    runtime.options = {}
    return ExhaustFanCoordinator(hass, MagicMock(), growspace.id, runtime)


async def test_the_exhaust_falls_back_when_every_regulation_sensor_is_lost(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    notices: dict[str, list[ServiceCall]],
) -> None:
    """One reading sensor keeps it regulating; none past the timeout falls back."""
    hass.states.async_set(TEMPERATURE, "unavailable")
    hass.states.async_set(HUMIDITY, "80")
    exhaust = _exhaust(hass, _exhaust_growspace(exhaust_fallback_speed=10))

    await exhaust._async_regulate()
    assert devices.fan_speeds() == [100]

    hass.states.async_set(HUMIDITY, "unavailable")
    freezer.tick(timedelta(minutes=9))
    await exhaust._async_regulate()
    assert devices.fan_speeds() == [100]

    freezer.tick(timedelta(minutes=1))
    await exhaust._async_regulate()
    # Clamped into the fan's own range, as every exhaust speed is.
    assert devices.fan_speeds() == [100, 20]
    notify = exhaust.main_coordinator.services.notifications.manager
    message = notify.async_send_notification.call_args.args[2]
    assert "the sensors sensor.humidity, sensor.temperature" in message
    assert "the exhaust runs at 20%" in message
    assert exhaust.diagnostics_snapshot()["fail_safe"] is True

    hass.states.async_set(TEMPERATURE, "30")
    await exhaust._async_regulate()
    assert devices.fan_speeds() == [100, 20, 100]
    assert notices["dismiss"]


async def test_an_exhaust_without_regulation_sensors_never_fails(
    hass: HomeAssistant, freezer: FrozenDateTimeFactory, devices: Devices
) -> None:
    """Nothing to read is nothing to lose: no fallback, no alert."""
    growspace = _exhaust_growspace()
    growspace.environment_config.temperature_sensors = []
    growspace.environment_config.humidity_sensors = []
    exhaust = _exhaust(hass, growspace)
    freezer.tick(timedelta(hours=1))
    await exhaust._async_regulate()
    assert devices.fan_speeds() == []
    notify = exhaust.main_coordinator.services.notifications.manager
    notify.async_send_notification.assert_not_awaited()


async def test_the_exhaust_stops_commanding_once_automation_is_paused(
    hass: HomeAssistant, devices: Devices
) -> None:
    """A pause that lands mid-tick holds the rest of the fans."""
    hass.states.async_set(HUMIDITY, "80")
    exhaust = _exhaust(hass, _exhaust_growspace())
    exhaust.main_coordinator.irrigation_safety.automation_enabled.side_effect = [
        True,
        False,
    ]
    await exhaust._async_regulate()
    assert devices.fan_speeds() == []


def test_the_fallback_speed_without_a_growspace_is_the_configured_one(
    hass: HomeAssistant,
) -> None:
    """A growspace removed mid-episode has no fan range to clamp into."""
    runtime = MagicMock()
    runtime.growspaces = {}
    assert ClimateSafety(hass, "gone", runtime).exhaust_fallback_speed() == 50


async def test_a_failed_exhaust_command_is_counted(
    hass: HomeAssistant, devices: Devices
) -> None:
    """The fan's refusal is counted against the exhaust."""
    hass.states.async_set(HUMIDITY, "80")

    async def _refuse(_call: ServiceCall) -> None:
        raise HomeAssistantError("no answer")

    hass.services.async_register("fan", "set_percentage", _refuse)
    exhaust = _exhaust(hass, _exhaust_growspace())
    await exhaust._async_regulate()
    lifetime = exhaust.main_coordinator.reliability.snapshot("tent")["lifetime"]
    assert lifetime["climate.command_failure.exhaust"] == 1


async def test_an_unloaded_controller_leaves_the_episode(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    devices: Devices,
    notices: dict[str, list[ServiceCall]],
    tents: list[Tent],
) -> None:
    """Once nothing is in its Safe State, the next evaluation recovers."""
    hass.states.async_set(VPD, "unavailable")
    hass.states.async_set(HUMIDITY, "60")
    growspace = _exhaust_growspace()
    tent = await _start(hass, tents, growspace)
    exhaust = ExhaustFanCoordinator(
        hass, MagicMock(), "tent", tent.runtime, tent.safety
    )
    tent.runtime.options = {}
    await _minutes(hass, freezer, 11)
    tent.notify.assert_awaited_once()

    tent.humidifier.unload()
    tent.dehumidifier.unload()
    await exhaust._async_regulate()
    assert tent.notify.call_args.args[1] == "✅ Climate Control Resumed: Tent"
