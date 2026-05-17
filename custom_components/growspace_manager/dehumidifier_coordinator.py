"""Dehumidifier Coordinator for Growspace Manager."""

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
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import (
    CATEGORY_DEHUMIDIFIER,
    DEFAULT_DEHUMIDIFIER_MIN_OFFTIME,
    DEFAULT_DEHUMIDIFIER_MIN_RUNTIME,
    PlantStage,
)
from .domain.stage_calculator import determine_coordinator_stage
from .models import GrowspaceEvent

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

# Default Thresholds
# Format: {stage: {day_or_night: {on: float, off: float}}}
DEFAULT_THRESHOLDS = {
    PlantStage.SEEDLING: {
        "day": {"on": 0.5, "off": 0.6},
        "night": {"on": 0.55, "off": 0.65},
    },
    PlantStage.MOTHER: {
        "day": {"on": 0.6, "off": 0.7},
        "night": {"on": 0.65, "off": 0.75},
    },
    PlantStage.VEG: {
        "day": {"on": 0.6, "off": 0.7},
        "night": {"on": 0.65, "off": 0.75},
    },
    PlantStage.FLOWER_EARLY: {
        "day": {"on": 1.1, "off": 1.2},
        "night": {"on": 0.7, "off": 0.9},
    },
    PlantStage.FLOWER_MID: {
        "day": {"on": 1.25, "off": 1.35},
        "night": {"on": 0.9, "off": 1},
    },
    PlantStage.FLOWER_LATE: {
        "day": {"on": 1.35, "off": 1.4},
        "night": {"on": 0.95, "off": 1.05},
    },
    PlantStage.DRY: {
        "day": {"on": 0.8, "off": 1.0},
        "night": {"on": 0.85, "off": 1.05},
    },
    PlantStage.CURE: {
        "day": {"on": 0.9, "off": 1.1},
        "night": {"on": 0.95, "off": 1.15},
    },
}


class DehumidifierCoordinator:
    """Manages dehumidifier logic based on VPD and growth stage."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the Dehumidifier Coordinator.

        Args:
            hass: The Home Assistant instance.
            config_entry: The configuration entry.
            growspace_id: The ID of the growspace to manage.
            main_coordinator: The main GrowspaceCoordinator instance.
        """
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_listeners: list[Any] = []

        # Timing state for short-cycling prevention
        self._last_turn_on_time: float = 0.0
        self._last_turn_off_time: float = 0.0

        # Light-sensor fallback state
        self._last_known_is_day: bool | None = None
        self._sensors_unavailable_since: float | None = None

        # Load configuration
        self.growspace = self.main_coordinator.growspaces.get(growspace_id)
        if not self.growspace:
            _LOGGER.error(
                "Growspace %s not found for DehumidifierCoordinator", growspace_id
            )
            return

        self.env_config: Any = self.growspace.environment_config or {}
        self.dehumidifier_config = getattr(self.growspace, "dehumidifier_config", {})

        # Entity IDs - env_config is an EnvironmentConfig object, use attribute access
        # Entity IDs - multi-device support
        # Use lists from env_config (populated by models.py migration or new config)
        self.vpd_sensor = getattr(self.env_config, "vpd_sensor", None)
        self.light_sensors = getattr(self.env_config, "light_sensors", [])

        # Dehumidifiers
        self.dehumidifier_entities = getattr(
            self.env_config, "dehumidifier_entities", []
        )
        # Exhaust fans (also controlled if configured?)
        self.exhaust_fan_entities = getattr(self.env_config, "exhaust_fan_entities", [])

        self.control_dehumidifier = getattr(
            self.env_config, "control_dehumidifier", False
        )

        # Thresholds
        self.user_thresholds: dict[str, Any] = getattr(
            self.env_config, "dehumidifier_thresholds", {}
        )

        # Valid if we have VPD sensor and at least one device to control
        self.has_devices = bool(self.dehumidifier_entities or self.exhaust_fan_entities)

        if self.vpd_sensor and self.has_devices and self.control_dehumidifier:
            _LOGGER.debug(
                "DehumidifierCoordinator initialized for %s. Call async_setup() to start monitoring",
                self.growspace.name,
            )

    async def async_setup(self) -> None:
        """Set up the coordinator and start monitoring."""
        if self.vpd_sensor and self.has_devices and self.control_dehumidifier:
            self._setup_listeners()
            # Start initial check after reload/startup
            await self.async_check_and_control()
            _LOGGER.info(
                "DehumidifierCoordinator started for %s (VPD: %s, Devices: %d)",
                self.growspace.name,
                self.vpd_sensor,
                len(self.dehumidifier_entities) + len(self.exhaust_fan_entities),
            )
        elif not self.control_dehumidifier:
            _LOGGER.info(
                "DehumidifierCoordinator disabled for %s (control_dehumidifier is False)",
                self.growspace.name,
            )
        else:
            _LOGGER.warning(
                "DehumidifierCoordinator skipped for %s: Missing VPD sensor or Devices",
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
        """Evaluate conditions and control the dehumidifier."""
        if not self.vpd_sensor or (
            not self.dehumidifier_entities and not self.exhaust_fan_entities
        ):
            return

        # Get VPD value
        current_vpd = self._get_current_vpd()
        if current_vpd is None:
            return

        # Determine Growth Stage
        stage_name = self._get_growth_stage()

        # Determine Day/Night (OR logic)
        is_day = self._determine_is_day()

        # Get Thresholds
        thresholds = self._get_current_thresholds(stage_name, is_day)
        on_threshold = thresholds["on"]
        off_threshold = thresholds["off"]

        # Control Logic
        # Low VPD = High Humidity -> Needs Dehumidification (Turn ON)
        # High VPD = Low Humidity -> Stop Dehumidification (Turn OFF)

        # Check state of devices
        # We consider "is_on" true if ANY controlled device is on
        is_on = self._determine_is_device_on()

        # Check timing guards to prevent short-cycling
        if self._is_locked_by_timer(is_on):
            return

        # Evaluate VPD thresholds with hysteresis
        if current_vpd < on_threshold and not is_on:
            _LOGGER.info(
                "VPD Trigger: Current %.2f < Target %.2f (%s, %s) -> Turning ON Devices",
                current_vpd,
                on_threshold,
                stage_name,
                "Day" if is_day else "Night",
            )
            await self._control_dehumidifier(True)
            self._fire_logbook_event(
                True, current_vpd, stage_name, is_day, on_threshold, off_threshold
            )
        elif current_vpd > off_threshold and is_on:
            _LOGGER.info(
                "VPD Trigger: Current %.2f > Threshold %.2f (%s, %s) -> Turning OFF Devices",
                current_vpd,
                off_threshold,
                stage_name,
                "Day" if is_day else "Night",
            )
            await self._control_dehumidifier(False)
            self._fire_logbook_event(
                False, current_vpd, stage_name, is_day, on_threshold, off_threshold
            )

    def _is_locked_by_timer(self, is_on: bool) -> bool:
        """Check if state change is blocked by minimum run/off timers.

        Args:
            is_on: Whether the dehumidifier is currently on.

        Returns:
            True if a state change should be blocked, False otherwise.
        """
        now = time.monotonic()

        if is_on:
            # Guard: Minimum Runtime (must stay ON for min duration)
            elapsed_on = now - self._last_turn_on_time
            min_runtime = self.dehumidifier_config.get(
                "min_runtime", DEFAULT_DEHUMIDIFIER_MIN_RUNTIME
            )
            if self._last_turn_on_time > 0 and elapsed_on < min_runtime:
                remaining = min_runtime - elapsed_on
                _LOGGER.debug(
                    "Locked by Min Runtime (remaining: %.0fs)",
                    remaining,
                )
                return True
        else:
            # Guard: Minimum Offtime (must stay OFF for min duration)
            elapsed_off = now - self._last_turn_off_time
            min_offtime = self.dehumidifier_config.get(
                "min_offtime", DEFAULT_DEHUMIDIFIER_MIN_OFFTIME
            )
            if self._last_turn_off_time > 0 and elapsed_off < min_offtime:
                remaining = min_offtime - elapsed_off
                _LOGGER.debug(
                    "Locked by Min Offtime (remaining: %.0fs)",
                    remaining,
                )
                return True

        return False

    def _get_growth_stage(self) -> PlantStage:
        """Determine the current growth stage for threshold selection."""
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(self.growspace_id)
        return determine_coordinator_stage(plants)

    def _get_current_thresholds(self, stage: str, is_day: bool) -> dict[str, float]:
        """Get the ON/OFF thresholds for the current state."""
        day_key = "day" if is_day else "night"

        # Check user overrides first
        if stage in self.user_thresholds and day_key in self.user_thresholds[stage]:
            # Expecting dict[str, float] structure
            return dict(self.user_thresholds[stage][day_key])

        # Fallback to defaults
        return DEFAULT_THRESHOLDS.get(stage, DEFAULT_THRESHOLDS["veg"])[day_key]

    async def _control_dehumidifier(self, turn_on: bool) -> None:
        """Turn the dehumidifier(s) and exhaust fan(s) on or off."""
        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF

        # Combine all entities
        all_entities = self.dehumidifier_entities + self.exhaust_fan_entities

        for entity_id in all_entities:
            domain = entity_id.split(".")[0]

            # Support switch, humidifier, fan, input_boolean domains
            # Default to homeassistant.turn_on/off if domain unknown or generic
            if domain not in ("switch", "humidifier", "fan", "input_boolean"):
                domain = "homeassistant"

            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {ATTR_ENTITY_ID: entity_id},
                    blocking=False,  # Use non-blocking to speed up
                )
            except (HomeAssistantError, TimeoutError):
                _LOGGER.warning("Failed to control device %s", entity_id, exc_info=True)

        # Update timestamps for short-cycling prevention
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
        """Fire a logbook event for a dehumidifier control action."""
        now = dt_util.now().isoformat()
        action = "Turned ON" if turned_on else "Turned OFF"
        period = "Day" if is_day else "Night"
        stage_label = stage.replace("_", " ").title()
        event = GrowspaceEvent(
            sensor_type="dehumidifier_control",
            growspace_id=self.growspace_id,
            start_time=now,
            end_time=now,
            duration_sec=0,
            severity=0.3,
            category=CATEGORY_DEHUMIDIFIER,
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

    _SENSOR_UNAVAILABLE_WARN_SECONDS = 300

    def _determine_is_day(self) -> bool:
        """Determine Day/Night state (OR logic)."""
        if not self.light_sensors:
            return True

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
            self._last_known_is_day = any_on
            self._sensors_unavailable_since = None
            return any_on

        # All sensors unavailable — use cached state
        now = time.monotonic()
        if self._sensors_unavailable_since is None:
            self._sensors_unavailable_since = now
        elif (
            now - self._sensors_unavailable_since
            >= self._SENSOR_UNAVAILABLE_WARN_SECONDS
        ):
            _LOGGER.warning(
                "All light sensors for growspace %s have been unavailable for over %d seconds; "
                "using last known day/night state",
                self.growspace_id,
                int(now - self._sensors_unavailable_since),
            )

        if self._last_known_is_day is not None:
            return self._last_known_is_day

        return True  # No prior observation — assume daytime

    def _determine_is_device_on(self) -> bool:
        """Determine if any controlled device is on."""
        is_on = False

        # Check Dehumidifiers
        for entity in self.dehumidifier_entities:
            state = self.hass.states.get(entity)
            if state and state.state == STATE_ON:
                is_on = True
                break

        # Check Exhaust Fans (if not found in dehum loop)
        if not is_on:
            for entity in self.exhaust_fan_entities:
                state = self.hass.states.get(entity)
                if state and state.state == STATE_ON:
                    is_on = True
                    break
        return is_on
