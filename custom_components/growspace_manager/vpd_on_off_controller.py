"""Abstract base for VPD-based on/off device controllers (humidifier, dehumidifier)."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any, ClassVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_call_later, async_track_state_change_event
from homeassistant.util import dt as dt_util

from .actuator_driver import resolve_on_off_drivers
from .const import PlantStage
from .domain.day_night import DayNightTracker
from .domain.stage_calculator import determine_coordinator_stage
from .models import GrowspaceEvent

if TYPE_CHECKING:
    from .actuator_driver import ActuatorDriver
    from .coordinator import GrowspaceCoordinator
    from .models import ACInfinityDevice

_LOGGER = logging.getLogger(__name__)


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
    """

    _CONTROL_FLAG_ATTR: ClassVar[str]
    _THRESHOLDS_ATTR: ClassVar[str]
    _DEVICE_CONFIG_ATTR: ClassVar[str]
    _ON_TRIGGER_IS_HIGH_VPD: ClassVar[bool]
    _DEFAULT_THRESHOLDS: ClassVar[dict]
    _LOGBOOK_SENSOR_TYPE: ClassVar[str]
    _LOGBOOK_CATEGORY: ClassVar[str]
    _DEFAULT_MIN_RUNTIME: ClassVar[int] = 300
    _DEFAULT_MIN_OFFTIME: ClassVar[int] = 300

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the VPD on/off controller for a growspace."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_listeners: list[Any] = []
        self._last_turn_on_time: float = 0.0
        self._last_turn_off_time: float = 0.0
        self._retry_cancel: CALLBACK_TYPE | None = None
        self._day_night = DayNightTracker(growspace_id)

        self.growspace = main_coordinator.growspaces.get(growspace_id)
        if not self.growspace:
            _LOGGER.error(
                "%s: growspace %s not found", type(self).__name__, growspace_id
            )
            return

        env = self.growspace.environment_config or {}
        self.vpd_sensor: str | None = getattr(env, "vpd_sensor", None)
        self.light_sensors: list[str] = getattr(env, "light_sensors", []) or []
        self.control_enabled: bool = getattr(env, self._CONTROL_FLAG_ATTR, False)
        self.user_thresholds: dict[str, Any] = (
            getattr(env, self._THRESHOLDS_ATTR, {}) or {}
        )
        self.device_config: dict[str, Any] = (
            getattr(self.growspace, self._DEVICE_CONFIG_ATTR, {}) or {}
        )

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

    async def _on_sensor_change(self, event: Any) -> None:
        await self.async_check_and_control()

    async def async_check_and_control(self) -> None:
        """Evaluate VPD against stage thresholds and drive the device."""
        entities = self._get_all_controlled_entities()
        if not self.vpd_sensor or not entities:
            return

        current_vpd = self._get_current_vpd()
        if current_vpd is None:
            return

        stage = self._get_growth_stage()
        is_day = self._day_night.determine(self.hass, self.light_sensors)
        thresholds = self._get_current_thresholds(stage, is_day)
        on_threshold = thresholds["on"]
        off_threshold = thresholds["off"]
        is_on = self._is_device_on()

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
        for driver in self._resolve_drivers():
            if turn_on:
                await driver.turn_on()
            else:
                await driver.turn_off()
        if turn_on:
            self._last_turn_on_time = time.monotonic()
        else:
            self._last_turn_off_time = time.monotonic()

    def _fire_logbook_event(
        self,
        turned_on: bool,
        vpd: float,
        stage: PlantStage,
        is_day: bool,
        on_threshold: float,
        off_threshold: float,
    ) -> None:
        now = dt_util.now().isoformat()
        action = "Turned ON" if turned_on else "Turned OFF"
        period = "Day" if is_day else "Night"
        stage_label = str(stage).replace("_", " ").title()
        event = GrowspaceEvent(
            sensor_type=self._LOGBOOK_SENSOR_TYPE,
            growspace_id=self.growspace_id,
            start_time=now,
            end_time=now,
            duration_sec=0,
            severity=0.3,
            category=self._LOGBOOK_CATEGORY,
            reasons=[
                action,
                f"VPD: {vpd:.2f} kPa",
                f"Stage: {stage_label}",
                f"Period: {period}",
                f"Thresholds: {on_threshold:.2f}/{off_threshold:.2f} kPa",
            ],
        )
        self.main_coordinator.add_event(self.growspace_id, event)

    def _get_current_vpd(self) -> float | None:
        if not self.vpd_sensor:
            return None
        state = self.hass.states.get(self.vpd_sensor)
        if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _is_device_on(self) -> bool:
        return any(driver.is_on() for driver in self._resolve_drivers())

    def unload(self) -> None:
        """Stop listeners and cancel any pending retry."""
        if self._retry_cancel is not None:
            self._retry_cancel()
            self._retry_cancel = None
        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners.clear()
