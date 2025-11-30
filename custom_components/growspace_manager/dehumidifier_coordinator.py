"""Dehumidifier Coordinator for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_state_change_event

_LOGGER = logging.getLogger(__name__)

# Default Thresholds
# Format: {stage: {day_or_night: {on: float, off: float}}}
DEFAULT_THRESHOLDS = {
    "veg": {
        "day": {"on": 0.8, "off": 1.2},
        "night": {"on": 0.75, "off": 1.15},
    },
    "early_flower": {
        "day": {"on": 1.2, "off": 1.3},
        "night": {"on": 1.1, "off": 1.25},
    },
    "mid_flower": {
        "day": {"on": 1.4, "off": 1.5},
        "night": {"on": 1.3, "off": 1.45},
    },
    "late_flower": {
        "day": {"on": 1.4, "off": 1.55},
        "night": {"on": 1.35, "off": 1.5},
    },
}


class DehumidifierCoordinator:
    """Manages dehumidifier logic based on VPD and growth stage."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: Any,
        growspace_id: str,
        main_coordinator: Any,
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
        self._remove_listeners = []

        # Load configuration
        self.growspace = self.main_coordinator.growspaces.get(growspace_id)
        if not self.growspace:
            _LOGGER.error("Growspace %s not found for DehumidifierCoordinator", growspace_id)
            return

        self.env_config = self.growspace.environment_config or {}
        self.dehumidifier_config = self.growspace.dehumidifier_config or {} # Fallback if separate config used

        # Entity IDs
        self.vpd_sensor = self.env_config.get("vpd_sensor")
        self.light_sensor = self.env_config.get("light_sensor")
        self.dehumidifier_entity = self.env_config.get("dehumidifier_entity")
        self.control_dehumidifier = self.env_config.get("control_dehumidifier", False)

        # User Thresholds (optional override)
        self.user_thresholds = self.env_config.get("dehumidifier_thresholds", {})

        if self.vpd_sensor and self.dehumidifier_entity and self.control_dehumidifier:
            self._setup_listeners()
            _LOGGER.info(
                "DehumidifierCoordinator initialized for %s (VPD: %s, Dehum: %s)",
                self.growspace.name,
                self.vpd_sensor,
                self.dehumidifier_entity,
            )
        elif not self.control_dehumidifier:
             _LOGGER.info(
                "DehumidifierCoordinator disabled for %s (control_dehumidifier is False)",
                self.growspace.name,
            )
        else:
            _LOGGER.warning(
                "DehumidifierCoordinator skipped for %s: Missing VPD sensor or Dehumidifier entity",
                self.growspace.name,
            )

    def _setup_listeners(self) -> None:
        """Set up state change listeners."""
        entities_to_track = [self.vpd_sensor]
        if self.light_sensor:
            entities_to_track.append(self.light_sensor)

        self._remove_listeners.append(
            async_track_state_change_event(
                self.hass, entities_to_track, self._on_sensor_change
            )
        )

    @callback
    async def _on_sensor_change(self, event: Any) -> None:
        """Handle sensor state changes."""
        await self.async_check_and_control()

    async def async_check_and_control(self) -> None:
        """Evaluate conditions and control the dehumidifier."""
        if not self.vpd_sensor or not self.dehumidifier_entity:
            return

        # Get VPD value
        vpd_state = self.hass.states.get(self.vpd_sensor)
        if not vpd_state or vpd_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return
        try:
            current_vpd = float(vpd_state.state)
        except ValueError:
            return

        # Determine Growth Stage
        stage_name = self._get_growth_stage()
        
        # Determine Day/Night
        is_day = True # Default to day if no sensor
        if self.light_sensor:
            light_state = self.hass.states.get(self.light_sensor)
            if light_state and light_state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                try:
                    # Assuming light sensor reports lux or similar numeric value
                    # Or it could be a binary sensor. The prompt says "Light > 0" vs "Light < 1"
                    # which implies a numeric sensor.
                    light_val = float(light_state.state)
                    is_day = light_val > 0
                except ValueError:
                    # If it's not a number, maybe it's 'on'/'off'
                    is_day = light_state.state == STATE_ON

        # Get Thresholds
        thresholds = self._get_current_thresholds(stage_name, is_day)
        on_threshold = thresholds["on"]
        off_threshold = thresholds["off"]

        # Control Logic
        # Low VPD = High Humidity -> Needs Dehumidification (Turn ON)
        # High VPD = Low Humidity -> Stop Dehumidification (Turn OFF)
        
        dehum_state = self.hass.states.get(self.dehumidifier_entity)
        is_on = dehum_state and dehum_state.state == STATE_ON

        if current_vpd < on_threshold and not is_on:
            _LOGGER.info(
                "VPD %.2f < %.2f (%s, %s): Turning ON dehumidifier %s",
                current_vpd,
                on_threshold,
                stage_name,
                "Day" if is_day else "Night",
                self.dehumidifier_entity,
            )
            await self._control_dehumidifier(True)
        elif current_vpd > off_threshold and is_on:
            _LOGGER.info(
                "VPD %.2f > %.2f (%s, %s): Turning OFF dehumidifier %s",
                current_vpd,
                off_threshold,
                stage_name,
                "Day" if is_day else "Night",
                self.dehumidifier_entity,
            )
            await self._control_dehumidifier(False)

    def _get_growth_stage(self) -> str:
        """Determine the current growth stage for threshold selection."""
        plants = self.main_coordinator.get_growspace_plants(self.growspace_id)
        
        max_veg_days = 0
        max_flower_days = 0

        for plant in plants:
            v_days = self.main_coordinator.calculate_days_in_stage(plant, "veg")
            f_days = self.main_coordinator.calculate_days_in_stage(plant, "flower")
            
            if v_days > max_veg_days:
                max_veg_days = v_days
            if f_days > max_flower_days:
                max_flower_days = f_days

        # Logic from Prompt:
        # Veg: flower_days == 0 AND veg_days > 0
        # Early Flower: flower_days > 0 AND flower_days < 22
        # Mid Flower: flower_days >= 22 AND flower_days < 50
        # Late Flower: flower_days >= 50

        if max_flower_days >= 50:
            return "late_flower"
        if max_flower_days >= 22:
            return "mid_flower"
        if max_flower_days > 0:
            return "early_flower"
        if max_veg_days > 0:
            return "veg"
        
        return "veg" # Default

    def _get_current_thresholds(self, stage: str, is_day: bool) -> dict[str, float]:
        """Get the ON/OFF thresholds for the current state."""
        day_key = "day" if is_day else "night"
        
        # Check user overrides first
        if (
            stage in self.user_thresholds
            and day_key in self.user_thresholds[stage]
        ):
            return self.user_thresholds[stage][day_key]

        # Fallback to defaults
        return DEFAULT_THRESHOLDS.get(stage, DEFAULT_THRESHOLDS["veg"])[day_key]

    async def _control_dehumidifier(self, turn_on: bool) -> None:
        """Turn the dehumidifier on or off."""
        service = SERVICE_TURN_ON if turn_on else SERVICE_TURN_OFF
        domain = self.dehumidifier_entity.split(".")[0]
        
        # Support switch and humidifier domains
        if domain not in ("switch", "humidifier"):
            domain = "homeassistant"

        await self.hass.services.async_call(
            domain,
            service,
            {ATTR_ENTITY_ID: self.dehumidifier_entity},
        )

    def unload(self) -> None:
        """Unload the coordinator and remove listeners."""
        for remove_listener in self._remove_listeners:
            remove_listener()
        self._remove_listeners.clear()
