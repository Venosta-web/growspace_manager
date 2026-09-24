"""Abstract base for VPD-based on/off device controllers (humidifier, dehumidifier)."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .actuator_driver import resolve_on_off_drivers
from .climate_safety import ClimateSafety
from .const import PlantStage
from .domain.climate_fail_safe import (
    ClimateRole,
    RoleFailure,
    SafeState,
    interlock_wins,
    runtime_exceeded,
)
from .domain.day_night import DayNightTracker
from .domain.sensor_validity import VPD_RANGE
from .domain.stage_calculator import determine_coordinator_stage
from .models import GrowspaceEvent
from .reliability_store import ReliabilityCounter, climate_command_failure

if TYPE_CHECKING:
    from .actuator_driver import ActuatorDriver
    from .coordinator import GrowspaceCoordinator
    from .models import ACInfinityDevice

_LOGGER = logging.getLogger(__name__)

# Re-evaluated on this tick as well as on sensor events, because a sensor that
# has frozen sends no events at all (#792).
_TICK_INTERVAL = timedelta(minutes=1)


class VpdOnOffController:
    """Controls a VPD-regulated on/off device (humidifier or dehumidifier).

    Subclasses set class variables to declare their identity:
    - _CONTROL_FLAG_ATTR: attribute on env_config that enables the controller
    - _THRESHOLDS_ATTR: attribute on env_config holding user threshold overrides
    - _DEVICE_CONFIG_ATTR: attribute on growspace holding min_runtime/min_offtime
    - _ON_TRIGGER_IS_HIGH_VPD: True → turns on at high VPD (humidifier);
                                False → turns on at low VPD (dehumidifier)
    - _DEFAULT_THRESHOLDS: per-stage {day/night: {on, off}} thresholds
    - _LOGBOOK_SENSOR_TYPE, _LOGBOOK_CATEGORY: logbook event labels
    - _DEFAULT_MIN_RUNTIME, _DEFAULT_MIN_OFFTIME: short-cycling prevention defaults
    - _ROLE: which device this is, for the Climate Fail-Safe and the interlock

    Every controller of a growspace shares one ``ClimateSafety`` (#792): after
    its VPD sensor has had no usable reading for the Fail-Safe Timeout the
    device goes to its Safe State, a device that has run past its maximum
    continuous runtime is switched off, and the Humidity Interlock keeps the
    humidifier and dehumidifier from running together — the later demand wins.
    """

    _CONTROL_FLAG_ATTR: ClassVar[str]
    _THRESHOLDS_ATTR: ClassVar[str]
    _DEVICE_CONFIG_ATTR: ClassVar[str]
    _ON_TRIGGER_IS_HIGH_VPD: ClassVar[bool]
    _DEFAULT_THRESHOLDS: ClassVar[dict[PlantStage, dict[str, dict[str, float]]]]
    _LOGBOOK_SENSOR_TYPE: ClassVar[str]
    _LOGBOOK_CATEGORY: ClassVar[str]
    _DEFAULT_MIN_RUNTIME: ClassVar[int] = 300
    _DEFAULT_MIN_OFFTIME: ClassVar[int] = 300
    _ROLE: ClassVar[ClimateRole]

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
        safety: ClimateSafety | None = None,
    ) -> None:
        """Initialize the VPD on/off controller for a growspace."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._safety = safety or ClimateSafety(hass, growspace_id, main_coordinator)
        self._safety.register(self._ROLE, self)
        # When this device's demand last began: VPD crossed its on threshold.
        # The Humidity Interlock compares it with the partner's.
        self.demand_since: datetime | None = None
        # When the device was first seen on in its current run, for the cap.
        self._on_since: datetime | None = None
        self._remove_listeners: list[Any] = []
        self._last_turn_on_time: float = 0.0
        self._last_turn_off_time: float = 0.0
        self._retry_cancel: CALLBACK_TYPE | None = None
        self._last_command: str | None = None
        self._last_command_at: str | None = None
        self._day_night = DayNightTracker(growspace_id)

        self.growspace = main_coordinator.growspaces.get(growspace_id)
        if not self.growspace:
            _LOGGER.error(
                "%s: growspace %s not found", type(self).__name__, growspace_id
            )
            return

        self.vpd_sensor: str | None = None
        self.light_sensors: list[str] = []
        self.control_enabled: bool = False
        self.user_thresholds: dict[str, Any] = {}
        self.device_config: dict[str, Any] = {}
        self._load_config()

    def _load_config(self) -> None:
        """(Re)read the fields this controller caches from the live environment config.

        Split out of ``__init__`` so ``async_restart`` can refresh them after a
        config-dialog edit — the controller instance is long-lived (constructed
        once at entry setup) and otherwise never notices later changes to its
        control flag, thresholds, or sensors.
        """
        if not self.growspace:
            return
        env = self.growspace.environment_config
        self.vpd_sensor = getattr(env, "vpd_sensor", None)
        self.light_sensors = getattr(env, "light_sensors", []) or []
        self.control_enabled = getattr(env, self._CONTROL_FLAG_ATTR, False)
        self.user_thresholds = getattr(env, self._THRESHOLDS_ATTR, {}) or {}
        self.device_config = getattr(self.growspace, self._DEVICE_CONFIG_ATTR, {}) or {}

    async def async_restart(self) -> None:
        """Restart after a config change: reload cached config and rebind listeners."""
        self.unload()
        self._load_config()
        await self.async_setup()

    def _get_all_controlled_entities(self) -> list[str]:
        """Return all entity IDs managed by this controller. Subclasses implement."""
        raise NotImplementedError

    def _get_ac_infinity_devices(self) -> list[ACInfinityDevice]:
        """Return AC Infinity bundles managed by this controller (none by default)."""
        return []

    def _resolve_drivers(self) -> list[ActuatorDriver]:
        """Resolve every controlled actuator — plain entities and AC Infinity."""
        return resolve_on_off_drivers(
            self.hass,
            self._get_all_controlled_entities(),
            self._get_ac_infinity_devices(),
        )

    async def async_setup(self) -> None:
        """Set up state-change listeners and run an initial check."""
        if self.growspace is None:
            return
        entities = self._get_all_controlled_entities()
        has_actuators = bool(entities or self._get_ac_infinity_devices())
        if self.vpd_sensor and has_actuators and self.control_enabled:
            self._setup_listeners()
            await self.async_check_and_control()
            _LOGGER.info(
                "%s started for %s (VPD: %s, Devices: %d)",
                type(self).__name__,
                self.growspace.name,
                self.vpd_sensor,
                len(entities) + len(self._get_ac_infinity_devices()),
            )
        elif not self.control_enabled:
            _LOGGER.info(
                "%s disabled for %s (%s is False)",
                type(self).__name__,
                self.growspace.name,
                self._CONTROL_FLAG_ATTR,
            )
        else:
            _LOGGER.warning(
                "%s skipped for %s: Missing VPD sensor or devices",
                type(self).__name__,
                self.growspace.name,
            )

    def _setup_listeners(self) -> None:
        entities_to_track: list[str] = [e for e in [self.vpd_sensor] if e]
        entities_to_track.extend(s for s in self.light_sensors if s)
        self._remove_listeners.append(
            async_track_state_change_event(
                self.hass, entities_to_track, self._on_sensor_change
            )
        )
        self._remove_listeners.append(
            async_track_time_interval(self.hass, self._on_tick, _TICK_INTERVAL)
        )

    async def _on_sensor_change(self, event: Any) -> None:
        await self.async_check_and_control()

    async def _on_tick(self, _now: Any) -> None:
        await self.async_check_and_control()

    async def async_check_and_control(self) -> None:
        """Evaluate VPD against stage thresholds and drive the device."""
        if not self.main_coordinator.irrigation_safety.automation_enabled(
            self.growspace_id
        ):
            return
        entities = self._get_all_controlled_entities()
        has_actuators = bool(entities or self._get_ac_infinity_devices())
        if not self.vpd_sensor or not has_actuators:
            return

        failure = await self._safety.async_failure(
            self._ROLE, {self.vpd_sensor: VPD_RANGE}
        )
        if failure is not None:
            await self._async_apply_safe_state(failure)
            return

        now = dt_util.utcnow()
        is_on = self._is_device_on()
        self._on_since = (self._on_since or now) if is_on else None
        # The runtime cap holds whether or not VPD can be read right now.
        max_runtime = self._safety.max_runtime(self._ROLE)
        if (
            is_on
            and max_runtime is not None
            and runtime_exceeded(self._on_since, now, max_runtime)
        ):
            await self._async_stop_for_max_runtime(max_runtime)
            return

        # A shorter dropout holds what was last commanded.
        current_vpd = self._get_current_vpd()
        if current_vpd is None:
            return

        stage = self._get_growth_stage()
        is_day = self._day_night.determine(self.hass, self.light_sensors)
        thresholds = self._get_current_thresholds(stage, is_day)
        on_threshold = thresholds["on"]
        off_threshold = thresholds["off"]
        demand = (
            current_vpd > on_threshold
            if self._ON_TRIGGER_IS_HIGH_VPD
            else current_vpd < on_threshold
        )
        self.demand_since = (self.demand_since or now) if demand else None

        if self._is_locked_by_timer(is_on):
            self._schedule_retry_if_needed(is_on)
            return

        if self._retry_cancel is not None:
            self._retry_cancel()
            self._retry_cancel = None

        if self._ON_TRIGGER_IS_HIGH_VPD:
            should_turn_on = current_vpd > on_threshold and not is_on
            should_turn_off = current_vpd < off_threshold and is_on
        else:
            should_turn_on = current_vpd < on_threshold and not is_on
            should_turn_off = current_vpd > off_threshold and is_on

        if should_turn_on and not await self._async_take_over(self.demand_since):
            return
        if should_turn_on:
            _LOGGER.info(
                "VPD Trigger: Current %.2f → Turning ON %s (%s, %s)",
                current_vpd,
                type(self).__name__,
                stage,
                "Day" if is_day else "Night",
            )
            await self._control_devices(True)
            self._fire_logbook_event(
                True, current_vpd, stage, is_day, on_threshold, off_threshold
            )
        elif should_turn_off:
            _LOGGER.info(
                "VPD Trigger: Current %.2f → Turning OFF %s (%s, %s)",
                current_vpd,
                type(self).__name__,
                stage,
                "Day" if is_day else "Night",
            )
            await self._control_devices(False)
            self._fire_logbook_event(
                False, current_vpd, stage, is_day, on_threshold, off_threshold
            )

    def _is_locked_by_timer(self, is_on: bool) -> bool:
        """Return True if a state change is blocked by minimum run/off timers."""
        now = time.monotonic()
        if is_on:
            elapsed = now - self._last_turn_on_time
            min_runtime = self.device_config.get(
                "min_runtime", self._DEFAULT_MIN_RUNTIME
            )
            if self._last_turn_on_time > 0 and elapsed < min_runtime:
                _LOGGER.debug(
                    "Locked by Min Runtime (remaining: %.0fs)", min_runtime - elapsed
                )
                return True
        else:
            elapsed = now - self._last_turn_off_time
            min_offtime = self.device_config.get(
                "min_offtime", self._DEFAULT_MIN_OFFTIME
            )
            if self._last_turn_off_time > 0 and elapsed < min_offtime:
                _LOGGER.debug(
                    "Locked by Min Offtime (remaining: %.0fs)", min_offtime - elapsed
                )
                return True
        return False

    def _schedule_retry_if_needed(self, is_on: bool) -> None:
        """Schedule a deferred check for when the active timer lock expires."""
        if self._retry_cancel is not None:
            return
        now = time.monotonic()
        if is_on:
            elapsed = now - self._last_turn_on_time
            min_duration = self.device_config.get(
                "min_runtime", self._DEFAULT_MIN_RUNTIME
            )
        else:
            elapsed = now - self._last_turn_off_time
            min_duration = self.device_config.get(
                "min_offtime", self._DEFAULT_MIN_OFFTIME
            )
        remaining = max(1.0, min_duration - elapsed)

        @callback
        def _retry(_now: Any) -> None:
            self._retry_cancel = None
            self.hass.async_create_task(self.async_check_and_control())

        self._retry_cancel = async_call_later(self.hass, remaining, _retry)
        _LOGGER.debug("Retry check scheduled in %.0fs", remaining)

    def _get_growth_stage(self) -> PlantStage:
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        return determine_coordinator_stage(plants)

    def _get_current_thresholds(
        self, stage: PlantStage, is_day: bool
    ) -> dict[str, float]:
        day_key = "day" if is_day else "night"
        if stage in self.user_thresholds and day_key in self.user_thresholds[stage]:
            return dict(self.user_thresholds[stage][day_key])
        return self._DEFAULT_THRESHOLDS.get(
            stage, self._DEFAULT_THRESHOLDS[PlantStage.VEG]
        )[day_key]

    async def _control_devices(self, turn_on: bool) -> None:
        """Turn on or off every controlled actuator through its driver."""
        main = getattr(self, "main_coordinator", None)
        safety = getattr(main, "irrigation_safety", None)
        if safety is not None and not safety.automation_enabled(self.growspace_id):
            return
        for driver in self._resolve_drivers():
            if safety is not None and not safety.automation_enabled(self.growspace_id):
                return
            done = await (driver.turn_on() if turn_on else driver.turn_off())
            if not done:
                self._safety.record(climate_command_failure(self._ROLE))
        if turn_on:
            self._last_turn_on_time = time.monotonic()
            self._on_since = self._on_since or dt_util.utcnow()
        else:
            self._last_turn_off_time = time.monotonic()
            self._on_since = None
        self._last_command = "on" if turn_on else "off"
        self._last_command_at = dt_util.now().isoformat()

    async def _async_take_over(self, demand_since: datetime | None) -> bool:
        """Apply the Humidity Interlock before this device switches on.

        Return False when the running partner's demand is the later one, so
        this device waits for it to finish. Otherwise the partner is switched
        off first. ``demand_since`` None is a Safe State, which always wins.
        """
        partner = self._safety.partner(self._ROLE)
        if partner is None or not partner.is_device_on():
            return True
        if not interlock_wins(demand_since, partner.demand_since):
            _LOGGER.debug(
                "%s for %s waits: its partner's demand is later",
                type(self).__name__,
                self.growspace_id,
            )
            return False
        await partner.async_interlock_off(self._ROLE)
        self._safety.record(ReliabilityCounter.CLIMATE_INTERLOCK)
        return True

    async def async_interlock_off(self, winner: ClimateRole) -> None:
        """Switch off because the partner's later demand takes over."""
        _LOGGER.info(
            "Interlock: %s for %s off, the %s demanded later",
            type(self).__name__,
            self.growspace_id,
            winner.value,
        )
        await self._control_devices(False)
        self._fire_note(False, [f"Interlock: the {winner.value} demanded later"])

    def is_device_on(self) -> bool:
        """Return whether any of this controller's devices is on."""
        return self._is_device_on()

    async def _async_apply_safe_state(self, failure: RoleFailure) -> None:
        """Drive the device to its Safe State, past the short-cycle timers.

        A controller that cannot see has no demand, so it never outranks its
        partner in the interlock while it is here. Commands go out only when
        the device is not already in its Safe State, so a failed command is
        retried on the next tick rather than repeated every minute.
        """
        self.demand_since = None
        safe_state = self._safety.safe_state(self._ROLE)
        if safe_state is SafeState.HOLD:
            return
        turn_on = safe_state is SafeState.ON
        if self._is_device_on() == turn_on:
            return
        if self._retry_cancel is not None:
            self._retry_cancel()
            self._retry_cancel = None
        if turn_on:
            await self._async_take_over(None)
        await self._control_devices(turn_on)
        self._fire_note(
            turn_on,
            [f"Fail-safe: no usable reading from {', '.join(failure.sensors)}"],
        )

    async def _async_stop_for_max_runtime(self, max_runtime: timedelta) -> None:
        """Switch off a device that has run for its maximum continuous runtime.

        The minimum off time then gives it its break before demand can bring
        it back.
        """
        minutes = int(max_runtime.total_seconds() // 60)
        _LOGGER.info(
            "%s for %s off: maximum continuous runtime of %d min reached",
            type(self).__name__,
            self.growspace_id,
            minutes,
        )
        await self._control_devices(False)
        self._safety.record(ReliabilityCounter.CLIMATE_MAX_RUNTIME_STOP)
        self._fire_note(False, [f"Maximum continuous runtime of {minutes} min reached"])

    def diagnostics_snapshot(self) -> dict[str, Any]:
        """Return the configured VPD controller state without changing an output."""
        stage = self._get_growth_stage()
        is_day = self._day_night.determine(self.hass, self.light_sensors)
        return {
            "control_enabled": self.control_enabled,
            "entities": self._get_all_controlled_entities(),
            "ac_infinity_ports": [
                {"mode_entity": device.mode_entity, "speed_entity": device.speed_entity}
                for device in self._get_ac_infinity_devices()
            ],
            "vpd_sensor": self.vpd_sensor,
            "stage": stage.value,
            "period": "day" if is_day else "night",
            "thresholds": self._get_current_thresholds(stage, is_day),
            "last_command": self._last_command,
            "last_command_at": self._last_command_at,
            "fail_safe": self._safety.is_failed(self._ROLE),
        }

    def _fire_logbook_event(
        self,
        turned_on: bool,
        vpd: float,
        stage: PlantStage,
        is_day: bool,
        on_threshold: float,
        off_threshold: float,
    ) -> None:
        period = "Day" if is_day else "Night"
        stage_label = str(stage).replace("_", " ").title()
        self._fire_note(
            turned_on,
            [
                f"VPD: {vpd:.2f} kPa",
                f"Stage: {stage_label}",
                f"Period: {period}",
                f"Thresholds: {on_threshold:.2f}/{off_threshold:.2f} kPa",
            ],
        )

    def _fire_note(self, turned_on: bool, details: list[str]) -> None:
        """Write one logbook entry for a command, with why it was given."""
        now = dt_util.now().isoformat()
        action = "Turned ON" if turned_on else "Turned OFF"
        event = GrowspaceEvent(
            sensor_type=self._LOGBOOK_SENSOR_TYPE,
            growspace_id=self.growspace_id,
            start_time=now,
            end_time=now,
            duration_sec=0,
            severity=0.3,
            category=self._LOGBOOK_CATEGORY,
            reasons=[action, *details],
        )
        self.main_coordinator.add_event(self.growspace_id, event)

    def _get_current_vpd(self) -> float | None:
        """Return the VPD, or None when it is unavailable, implausible or stale."""
        if not self.vpd_sensor:
            return None
        return self._safety.reading(self.vpd_sensor, VPD_RANGE).value

    def _is_device_on(self) -> bool:
        return any(driver.is_on() for driver in self._resolve_drivers())

    def unload(self) -> None:
        """Stop listeners and cancel any pending retry."""
        self._safety.withdraw(self._ROLE)
        if self._retry_cancel is not None:
            self._retry_cancel()
            self._retry_cancel = None
        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners.clear()
