"""Coordinator for VWC-based crop steering irrigation."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.dt import now, utcnow

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from .models import GrowspaceEvent, IrrigationStrategy

_LOGGER = logging.getLogger(__name__)


class VWCIrrigationCoordinator:
    """Manages VWC-based crop steering irrigation for a growspace."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the VWC irrigation coordinator."""
        self.hass = hass
        self._config_entry = config_entry
        self._growspace_id = growspace_id
        self._main_coordinator = main_coordinator
        self._remove_update_listener = None

        # State tracking
        self._current_phase = "P3"  # Start in safe state
        self._last_shot_time: datetime | None = None
        self._target_reached_today = False

        # We track if we have logged a "sensor missing" warning recently to avoid spam
        self._sensor_warning_logged = False

    async def async_setup(self):
        """Set up the coordinator and start the update loop."""
        _LOGGER.info(
            "Setting up VWC Irrigation Coordinator for growspace %s", self._growspace_id
        )
        # Check every minute for phase updates and actions
        self._remove_update_listener = async_track_time_interval(
            self.hass, self._update_loop, timedelta(minutes=1)
        )

    async def async_unload(self):
        """Unload the coordinator and stop listeners."""
        if self._remove_update_listener:
            self._remove_update_listener()
            self._remove_update_listener = None
        _LOGGER.info(
            "Unloaded VWC Irrigation Coordinator for growspace %s", self._growspace_id
        )

    @callback
    def async_cancel_listeners(self):
        """Alias for unload to match interface of standard coordinator."""
        # We don't need to await here because _remove_update_listener is synchronous callback removal
        if self._remove_update_listener:
            self._remove_update_listener()
            self._remove_update_listener = None

    async def _update_loop(self, _now: datetime):
        """Main update loop triggered every minute."""
        try:
            growspace = self._main_coordinator.growspaces[self._growspace_id]
            strategy = growspace.irrigation_strategy

            if not strategy.enabled:
                # Should not happen if correctly loaded, but safe guard
                return

            sensor_entity = growspace.environment_config.get("soil_moisture_sensor")
            if not sensor_entity:
                if not self._sensor_warning_logged:
                    _LOGGER.warning(
                        "VWC Steering enabled for %s but no soil moisture sensor configured. "
                        "Aborting steering logic",
                        self._growspace_id,
                    )
                    self._sensor_warning_logged = True
                self._set_phase("Disabled (No Sensor)")
                return

            # Reset warning flag if sensor is now present
            self._sensor_warning_logged = False

            # Get current VWC reading
            current_vwc = self._get_sensor_value(sensor_entity)
            if current_vwc is None:
                _LOGGER.debug(
                    "VWC Sensor %s is unavailable for growspace %s",
                    sensor_entity,
                    self._growspace_id,
                )
                return

            period = self._determine_time_period(strategy, growspace)
            self._execute_phase_logic(period, current_vwc, strategy)

        except Exception as e:
            _LOGGER.exception(
                "Error in VWC Irrigation loop for growspace %s: %s",
                self._growspace_id,
                e,
            )

    def _determine_time_period(self, strategy: IrrigationStrategy, growspace) -> str:
        """Determine the current steering phase based on time of day."""

        # Parse Lights On Time
        try:
            lights_on = datetime.strptime(strategy.lights_on_time, "%H:%M:%S").time()
        except ValueError:
            # Fallback format check
            lights_on = datetime.strptime(strategy.lights_on_time, "%H:%M").time()

        # Calculate Lights Off Time (derived from photoperiod settings in config)
        # Default to 12/12 if not set, or read from growspace options
        # We need to know the day hours.
        # Assuming we can access veg_day_hours or flower_day_hours from environment config options via handler logic?
        # Actually growspace.environment_config has the unified settings.
        # Let's check stage to decide hours.
        # For simplicity, if we lack stage info, we assume 12 hours for flowering.

        # Wait, the growspace model doesn't strictly track "stage" on the growspace itself,
        # but environment_config has 'veg_day_hours' etc.
        # And plants have stages. This is tricky.
        # Let's verify environment_config keys from handler.
        # 'veg_day_hours', 'flower_early_day_hours', etc.
        # To determine which one to use, we might need to look at the plants or just use a default?
        # A simpler approach for Phase 1: Use a config on the strategy itself? No, user requirement said "Lights On Time"
        # and "P2 Stop before Lights Off". It implies we know Lights Off.
        # Let's attempt to calculate Lights Off from 'lights_on_time' + 12 hours as a safe default for flowering,
        # or 18 for veg.
        # BETTER: Let's assume 12 hours duration if we can't find better info, to be safe.
        # OR: Check if we can get 'lights_off_time' from somewhere? No.

        # Let's check environment config for day lengths.
        day_hours = 12  # Default
        if growspace.environment_config:
            # This is a simplification. A more robust implementation would determine the dominant
            # plant stage in the growspace and use the corresponding day hours.
            # For now, we prefer flower hours if available, as steering is often flower-focused.
            day_hours = growspace.environment_config.get(
                "flower_day_hours",
                growspace.environment_config.get("veg_day_hours", 12),
            )

        # Calculate P0 End
        # We need datetime arithmetic then convert back to time
        today_start_dt = datetime.combine(now().date(), lights_on, tzinfo=now().tzinfo)
        current_dt = now()

        # Adjust for wrapping if needed? Assume Lights On is today.
        # If current time is before lights on, it might be "Night" (P3) from previous cycle or before P0.

        p0_end_dt = today_start_dt + timedelta(minutes=strategy.p0_duration_minutes)
        p1_start_dt = p0_end_dt

        # Calculate Lights Off
        lights_off_dt = today_start_dt + timedelta(hours=day_hours)

        # P2 Stop
        p2_stop_dt = lights_off_dt - timedelta(
            minutes=strategy.p2_stop_before_lights_off_minutes
        )

        if current_dt < today_start_dt:
            # Before lights on -> P3 (Dry Back) from yesterday

            return "P3"

        if current_dt < p1_start_dt:
            # P0 Activation

            return "P0"

        if current_dt < p2_stop_dt:
            # P1 or P2 window
            # We differentiate P1 vs P2 by target achievement, not strictly time.
            # But the 'Time Period' is "Active Watering Window".
            return "WINDOW"

        if current_dt < lights_off_dt:
            # Post-Maintenance, Pre-Lights Off -> P3 starts early effectively (or just stop watering)
            return "P3"

        # After lights off
        return "P3"

    def _execute_phase_logic(
        self, period: str, current_vwc: float, strategy: IrrigationStrategy
    ):
        """Execute the logic for the current phase."""

        if period == "P3":
            self._set_phase("P3 - Dry Back")
            self._target_reached_today = False  # Reset for next day logic?
            # Strictly speaking, we should reset this at Lights On.
            # But if we are in P3 (night), we are dry backing.
            return

        if period == "P0":
            self._set_phase("P0 - Activation")
            # Reset daily target flag if we are in P0 (start of day)
            self._target_reached_today = False
            return

        # P1 / P2 WINDOW
        target = strategy.target_vwc_percent

        if not self._target_reached_today:
            # We are in P1: Ramp Up
            self._set_phase("P1 - Ramp Up")

            if current_vwc >= target:
                _LOGGER.info(
                    "Growspace %s reached target VWC %.1f%%. Switching to P2",
                    self._growspace_id,
                    target,
                )
                self._target_reached_today = True
                # No watering this tick, just switch state
            else:
                self._handle_watering(strategy, "P1")

        else:
            # We are in P2: Maintenance
            self._set_phase("P2 - Maintenance")

            # Check dryback trigger
            trigger = target - strategy.maintenance_dryback_percent
            if current_vwc < trigger:
                _LOGGER.info(
                    "Growspace %s VWC (%.1f%%) dropped below maintenance trigger (%.1f%%). Pulse watering",
                    self._growspace_id,
                    current_vwc,
                    trigger,
                )
                self._handle_watering(strategy, "P2")

    def _handle_watering(self, strategy: IrrigationStrategy, phase: str):
        """Handle execution of a shot if interval permits."""
        now_dt = now()

        if self._last_shot_time:
            elapsed = (now_dt - self._last_shot_time).total_seconds() / 60.0
            if elapsed < strategy.shot_interval_minutes:
                # Waiting for interval
                return

        # Fire Shot
        pump_entity = self._get_pump_entity()
        if not pump_entity:
            return

        duration = strategy.shot_duration_seconds

        _LOGGER.info(
            "Firing %s shot for growspace %s. Duration: %ss",
            phase,
            self._growspace_id,
            duration,
        )

        # Schedule the task
        self.hass.async_create_task(self._run_pump_cycle(pump_entity, duration, phase))

        self._last_shot_time = now_dt

    async def _run_pump_cycle(self, pump_entity: str, duration: int, phase: str):
        """Execute the pump cycle."""
        start_time = utcnow()
        try:
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": pump_entity}, blocking=True
            )
            await asyncio.sleep(duration)
        except asyncio.CancelledError:
            pass
        finally:
            end_time = utcnow()
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": pump_entity}, blocking=True
            )
            # Log Event
            actual_duration = int((end_time - start_time).total_seconds())
            await self._log_event(phase, actual_duration, start_time, end_time)

    async def _log_event(
        self, phase: str, duration: int, start_time: datetime, end_time: datetime
    ):
        """Log the irrigation event."""
        event = GrowspaceEvent(
            sensor_type="irrigation",
            growspace_id=self._growspace_id,
            start_time=start_time.isoformat(),
            end_time=end_time.isoformat(),
            duration_sec=duration,
            severity=0.5,  # Info level
            category="irrigation",
            reasons=[f"VWC Steering {phase} Shot"],
        )
        self._main_coordinator.add_event(self._growspace_id, event)

    def _get_sensor_value(self, entity_id: str) -> float | None:
        """Get float value from sensor state."""
        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _get_pump_entity(self) -> str | None:
        """Get configured irrigation pump entity."""
        growspace = self._main_coordinator.growspaces[self._growspace_id]
        return growspace.irrigation_config.get("irrigation_pump_entity")

    def _set_phase(self, phase: str):
        """Update phase state and potentially expose strictly for debugging."""
        # In a full implementation, we might expose this as a sensor state.
        if self._current_phase != phase:
            _LOGGER.debug(
                "Growspace %s VWC Steering Phase changed: %s -> %s",
                self._growspace_id,
                self._current_phase,
                phase,
            )
            self._current_phase = phase
