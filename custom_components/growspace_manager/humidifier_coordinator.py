"""Humidifier Coordinator for Growspace Manager."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CATEGORY_HUMIDIFIER,
    DEFAULT_HUMIDIFIER_MIN_OFFTIME,
    DEFAULT_HUMIDIFIER_MIN_RUNTIME,
)
from .domain import calculate_days_in_stage
from .models import GrowspaceEvent

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

# Default thresholds — humidifier turns ON when VPD exceeds `on`, OFF when it drops below `off`.
# High VPD = low humidity = needs humidification.
# Format: {stage: {day_or_night: {on: float, off: float}}}
DEFAULT_THRESHOLDS = {
    "seedling": {
        "day": {"on": 0.7, "off": 0.5},
        "night": {"on": 0.75, "off": 0.55},
    },
    "mother": {
        "day": {"on": 0.9, "off": 0.7},
        "night": {"on": 0.85, "off": 0.65},
    },
    "veg": {
        "day": {"on": 1.0, "off": 0.8},
        "night": {"on": 0.85, "off": 0.65},
    },
    "early_flower": {
        "day": {"on": 1.4, "off": 1.2},
        "night": {"on": 1.0, "off": 0.8},
    },
    "mid_flower": {
        "day": {"on": 1.6, "off": 1.4},
        "night": {"on": 1.2, "off": 1.0},
    },
    "late_flower": {
        "day": {"on": 1.7, "off": 1.5},
        "night": {"on": 1.3, "off": 1.1},
    },
    "dry": {
        "day": {"on": 1.2, "off": 1.0},
        "night": {"on": 1.2, "off": 1.0},
    },
    "cure": {
        "day": {"on": 1.2, "off": 1.0},
        "night": {"on": 1.2, "off": 1.0},
    },
}


class HumidifierCoordinator:
    """Manages humidifier logic based on VPD and growth stage."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the Humidifier Coordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_listeners: list[Any] = []

        self._last_turn_on_time: float = 0.0
        self._last_turn_off_time: float = 0.0

        self.growspace = self.main_coordinator.growspaces.get(growspace_id)
        if not self.growspace:
            _LOGGER.error(
                "Growspace %s not found for HumidifierCoordinator", growspace_id
            )
            return

        self.env_config: Any = self.growspace.environment_config or {}
        self.humidifier_config = getattr(self.growspace, "humidifier_config", {})

        self.vpd_sensor = getattr(self.env_config, "vpd_sensor", None)
        self.light_sensors = getattr(self.env_config, "light_sensors", [])
        self.humidifier_entities = getattr(self.env_config, "humidifier_entities", [])
        self.control_humidifier = getattr(self.env_config, "control_humidifier", False)
        self.user_thresholds: dict[str, Any] = getattr(
            self.env_config, "humidifier_thresholds", {}
        )

        if self.vpd_sensor and self.humidifier_entities and self.control_humidifier:
            _LOGGER.debug(
                "HumidifierCoordinator initialized for %s. Call async_setup() to start monitoring",
                self.growspace.name,
            )

    async def async_setup(self) -> None:
        """Set up the coordinator and start monitoring."""
        if self.vpd_sensor and self.humidifier_entities and self.control_humidifier:
            self._setup_listeners()
            # Start initial check after reload/startup
            await self.async_check_and_control()
            _LOGGER.info(
                "HumidifierCoordinator started for %s (VPD: %s, Devices: %d)",
                self.growspace.name,
                self.vpd_sensor,
                len(self.humidifier_entities),
            )
        elif not self.control_humidifier:
            _LOGGER.info(
                "HumidifierCoordinator disabled for %s (control_humidifier is False)",
                self.growspace.name,
            )
        else:
            _LOGGER.warning(
                "HumidifierCoordinator skipped for %s: Missing VPD sensor or humidifier entities",
                self.growspace.name,
            )

    def _setup_listeners(self) -> None:
        """Set up state change listeners."""
        entities_to_track: list[str] = [e for e in [self.vpd_sensor] if e]
        if self.light_sensors:
            entities_to_track.extend([e for e in self.light_sensors if e])

        self._remove_listeners.append(
            async_track_state_change_event(
                self.hass, entities_to_track, self._on_sensor_change
            )
        )

    async def _on_sensor_change(self, event: Any) -> None:
        """Handle sensor state changes."""
        await self.async_check_and_control()

    async def async_check_and_control(self) -> None:
        """Evaluate conditions and control the humidifier."""
        if not self.vpd_sensor or not self.humidifier_entities:
            return

        current_vpd = self._get_current_vpd()
        if current_vpd is None:
            return

        stage_name = self._get_growth_stage()
        is_day = self._determine_is_day()
        thresholds = self._get_current_thresholds(stage_name, is_day)
        on_threshold = thresholds["on"]
        off_threshold = thresholds["off"]

        is_on = self._determine_is_device_on()

        if self._is_locked_by_timer(is_on):
            return

        # High VPD = low humidity → turn humidifier ON
        # Low VPD = sufficient humidity → turn humidifier OFF
        if current_vpd > on_threshold and not is_on:
            _LOGGER.info(
                "VPD Trigger: Current %.2f > Target %.2f (%s, %s) -> Turning ON Humidifier",
                current_vpd,
                on_threshold,
                stage_name,
                "Day" if is_day else "Night",
            )
            await self._control_humidifier(True)
            self._fire_logbook_event(True, current_vpd, stage_name, is_day, on_threshold, off_threshold)
        elif current_vpd < off_threshold and is_on:
            _LOGGER.info(
                "VPD Trigger: Current %.2f < Threshold %.2f (%s, %s) -> Turning OFF Humidifier",
                current_vpd,
                off_threshold,
                stage_name,
                "Day" if is_day else "Night",
            )
            await self._control_humidifier(False)
            self._fire_logbook_event(False, current_vpd, stage_name, is_day, on_threshold, off_threshold)

    def _is_locked_by_timer(self, is_on: bool) -> bool:
        """Check if state change is blocked by minimum run/off timers."""
        now = time.monotonic()

        if is_on:
            elapsed_on = now - self._last_turn_on_time
            min_runtime = self.humidifier_config.get(
                "min_runtime", DEFAULT_HUMIDIFIER_MIN_RUNTIME
            )
            if self._last_turn_on_time > 0 and elapsed_on < min_runtime:
                _LOGGER.debug(
                    "Locked by Min Runtime (remaining: %.0fs)",
                    min_runtime - elapsed_on,
                )
                return True
        else:
            elapsed_off = now - self._last_turn_off_time
            min_offtime = self.humidifier_config.get(
                "min_offtime", DEFAULT_HUMIDIFIER_MIN_OFFTIME
            )
            if self._last_turn_off_time > 0 and elapsed_off < min_offtime:
                _LOGGER.debug(
                    "Locked by Min Offtime (remaining: %.0fs)",
                    min_offtime - elapsed_off,
                )
                return True

        return False

    def _get_growth_stage(self) -> str:
        """Determine the current growth stage for threshold selection."""
        plants = self.main_coordinator.get_growspace_plants(self.growspace_id)

        max_seedling_days = 0
        max_veg_days = 0
        max_flower_days = 0
        max_dry_days = 0
        max_cure_days = 0
        max_mother_days = 0

        for plant in plants:
            max_seedling_days = max(max_seedling_days, calculate_days_in_stage(plant, "seedling"))
            max_veg_days = max(max_veg_days, calculate_days_in_stage(plant, "veg"))
            max_flower_days = max(max_flower_days, calculate_days_in_stage(plant, "flower"))
            max_dry_days = max(max_dry_days, calculate_days_in_stage(plant, "dry"))
            max_cure_days = max(max_cure_days, calculate_days_in_stage(plant, "cure"))
            max_mother_days = max(max_mother_days, calculate_days_in_stage(plant, "mother"))

        if max_cure_days > 0:
            return "cure"
        if max_dry_days > 0:
            return "dry"
        if max_flower_days >= 50:
            return "late_flower"
        if max_flower_days >= 22:
            return "mid_flower"
        if max_flower_days > 0:
            return "early_flower"
        if max_mother_days > 0:
            return "mother"
        if max_veg_days > 0:
            return "veg"
        if max_seedling_days > 0:
            return "seedling"

        return "veg"

    def _get_current_thresholds(self, stage: str, is_day: bool) -> dict[str, float]:
        """Get the ON/OFF thresholds for the current state."""
        day_key = "day" if is_day else "night"

        if stage in self.user_thresholds and day_key in self.user_thresholds[stage]:
            return dict(self.user_thresholds[stage][day_key])

        return DEFAULT_THRESHOLDS.get(stage, DEFAULT_THRESHOLDS["veg"])[day_key]

    async def _control_humidifier(self, turn_on: bool) -> None:
        """Turn the humidifier(s) on or off."""
        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF

        for entity_id in self.humidifier_entities:
            domain = entity_id.split(".")[0]

            if domain not in ("switch", "humidifier", "fan", "input_boolean"):
                domain = "homeassistant"

            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=False,
                )
            except Exception:  # noqa: BLE001
                _LOGGER.warning("Failed to control device %s", entity_id, exc_info=True)

        if turn_on:
            self._last_turn_on_time = time.monotonic()
        else:
            self._last_turn_off_time = time.monotonic()

    def _fire_logbook_event(
        self,
        turned_on: bool,
        vpd: float,
        stage: str,
        is_day: bool,
        on_threshold: float,
        off_threshold: float,
    ) -> None:
        """Fire a logbook event for a humidifier control action."""
        now = dt_util.now().isoformat()
        action = "Turned ON" if turned_on else "Turned OFF"
        period = "Day" if is_day else "Night"
        stage_label = stage.replace("_", " ").title()
        event = GrowspaceEvent(
            sensor_type="humidifier_control",
            growspace_id=self.growspace_id,
            start_time=now,
            end_time=now,
            duration_sec=0,
            severity=0.3,
            category=CATEGORY_HUMIDIFIER,
            reasons=[
                action,
                f"VPD: {vpd:.2f} kPa",
                f"Stage: {stage_label}",
                f"Period: {period}",
                f"Thresholds: {on_threshold:.2f}/{off_threshold:.2f} kPa",
            ],
        )
        self.main_coordinator.add_event(self.growspace_id, event)

    def unload(self) -> None:
        """Unload the coordinator and remove listeners."""
        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners.clear()

    def _get_current_vpd(self) -> float | None:
        """Get the current VPD value."""
        if not self.vpd_sensor:
            return None
        vpd_state = self.hass.states.get(self.vpd_sensor)
        if not vpd_state or vpd_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return None
        try:
            return float(vpd_state.state)
        except ValueError:
            return None

    def _determine_is_day(self) -> bool:
        """Determine Day/Night state (OR logic)."""
        is_day = True
        if self.light_sensors:
            any_valid = False
            any_on = False
            for sensor in self.light_sensors:
                light_state = self.hass.states.get(sensor)
                if light_state and light_state.state not in (
                    STATE_UNKNOWN,
                    STATE_UNAVAILABLE,
                ):
                    any_valid = True
                    try:
                        light_val = float(light_state.state)
                        if light_val > 0:
                            any_on = True
                    except ValueError:
                        if light_state.state == STATE_ON:
                            any_on = True

            if any_valid:
                is_day = any_on
        return is_day

    def _determine_is_device_on(self) -> bool:
        """Determine if any controlled humidifier device is on."""
        for entity in self.humidifier_entities:
            state = self.hass.states.get(entity)
            if state and state.state == STATE_ON:
                return True
        return False
