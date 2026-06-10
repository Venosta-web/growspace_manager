"""Coordinator for VWC-based crop steering irrigation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.dt import now, parse_datetime

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from .irrigation_coordinator import BaseIrrigationCoordinator
from .models import Growspace, IrrigationStrategy

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SteeringPhaseBoundaries:
    """Datetimes anchored on a reference date marking crop-steering phase transitions."""

    lights_on: datetime
    p0_end: datetime
    p2_stop: datetime
    lights_off: datetime


class VWCIrrigationCoordinator(BaseIrrigationCoordinator):
    """Manages VWC-based crop steering irrigation for a growspace."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the VWC irrigation coordinator."""
        super().__init__(hass, config_entry, growspace_id, main_coordinator)
        self._remove_update_listener: Callable[[], None] | None = None

        # State tracking
        self._current_phase = "P3"  # Start in safe state
        self._target_reached_today = False
        self._last_reset_date: str | None = None
        self._shot_scale_factor = 1.0

        # We track if we have logged a "sensor missing" warning recently to avoid spam
        self._sensor_warning_logged = False

    @override
    async def async_setup(self) -> None:
        """Set up the coordinator and start the update loop."""
        _LOGGER.info(
            "Setting up VWC Irrigation Coordinator for growspace %s", self._growspace_id
        )
        self._register_daily_reset_listener()
        # Check every minute for phase updates and actions
        self._remove_update_listener = async_track_time_interval(
            self.hass, self._update_loop, timedelta(minutes=1)
        )

    @override
    async def async_unload(self) -> None:
        """Unload the coordinator and stop listeners."""
        # Call base implementation to clean up any base listeners (if added in future)
        await super().async_unload()
        _LOGGER.info(
            "Unloaded VWC Irrigation Coordinator for growspace %s", self._growspace_id
        )

    @callback
    @override
    def async_cancel_listeners(self, cancel_tasks: bool = True) -> None:
        """Cancel all scheduled listeners."""
        super().async_cancel_listeners(cancel_tasks=cancel_tasks)
        if self._remove_update_listener:
            self._remove_update_listener()
            self._remove_update_listener = None

    @override
    def _reset_extra_daily_state(self) -> None:
        """Reset crop-steering target tracking at local midnight."""
        self._target_reached_today = False
        self._last_reset_date = None
        self._shot_scale_factor = 1.0

    async def _update_loop(self, _now: datetime) -> None:
        """Main update loop triggered every minute."""
        try:
            growspace = self.growspace
            strategy = growspace.irrigation_strategy

            if not strategy.enabled:
                # Should not happen if correctly loaded, but safe guard
                return

            sensor_entity = growspace.environment_config.soil_moisture_sensor
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

            if self._is_halted_by_runoff_ec(growspace):
                return

            phase_before = self._current_phase
            period = self._determine_time_period(strategy, growspace)
            self._execute_phase_logic(period, current_vwc, strategy)

            if self._current_phase != phase_before:
                self._main_coordinator.async_set_updated_data(
                    self._main_coordinator.data
                )

        except Exception:
            _LOGGER.exception(
                "Error in VWC Irrigation loop for growspace %s",
                self._growspace_id,
            )

    def _determine_time_period(
        self, strategy: IrrigationStrategy, growspace: Growspace
    ) -> str:
        """Determine the current steering phase based on time of day."""
        current_dt = now()
        boundaries = self._phase_boundary_times(strategy, growspace, current_dt.date())

        if current_dt < boundaries.lights_on:
            # Before lights on -> P3 (Dry Back) from yesterday
            return "P3"

        if current_dt < boundaries.p0_end:
            return "P0"

        if current_dt < boundaries.p2_stop:
            return "WINDOW"

        if current_dt < boundaries.lights_off:
            # Only enter early P3 when the flag is explicitly enabled.
            if growspace.irrigation_config.auto_advance_p2_to_p3:
                return "P3"
            return "WINDOW"

        return "P3"

    def _execute_phase_logic(
        self, period: str, current_vwc: float, strategy: IrrigationStrategy
    ) -> None:
        """Execute the logic for the current phase."""

        # Reset daily target flag at lights-on, regardless of whether P0 is observed.
        # Using a date guard prevents the flag from getting stuck if P0 is shorter than
        # the update interval or if the loop misses the P0 window entirely.
        today_str = now().date().isoformat()
        if today_str != self._last_reset_date and period in ("P0", "WINDOW"):
            self._target_reached_today = False
            self._last_reset_date = today_str

        if period == "P3":
            self._set_phase("P3 - Dry Back")
            return

        if period == "P0":
            self._set_phase("P0 - Activation")
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

            # Dynamic trigger: soil_trigger_percent overrides the calculated threshold
            # when set, enabling VWC-sensor-driven phase transitions.
            config = self.growspace.irrigation_config
            if config.soil_trigger_percent is not None:
                trigger = config.soil_trigger_percent
            else:
                trigger = target - strategy.maintenance_dryback_percent
            if current_vwc < trigger:
                _LOGGER.info(
                    "Growspace %s VWC (%.1f%%) dropped below maintenance trigger (%.1f%%). Pulse watering",
                    self._growspace_id,
                    current_vwc,
                    trigger,
                )
                self._handle_watering(strategy, "P2")

    def _last_shot_dt(self) -> datetime | None:
        """Return the last confirmed pump-cycle start time, or None.

        Reads `_last_cycle_timestamp` (set by `_run_pump_cycle` only after the
        switch is confirmed on) rather than stamping optimistically — a skipped
        cycle (e.g. dark-period guard) must not silently rate-limit future shots.
        """
        if not self._last_cycle_timestamp:
            return None
        return parse_datetime(self._last_cycle_timestamp)

    def _handle_watering(self, strategy: IrrigationStrategy, phase: str) -> None:
        """Handle execution of a shot if interval permits."""
        now_dt = now()

        last_shot = self._last_shot_dt()
        if last_shot:
            elapsed = (now_dt - last_shot).total_seconds() / 60.0
            if elapsed < strategy.shot_interval_minutes:
                return

        pump_entity = self._get_pump_entity()
        if not pump_entity:
            return

        duration = strategy.shot_duration_seconds
        scaled_duration = max(1, int(round(duration * self._shot_scale_factor)))

        _LOGGER.info(
            "Firing %s shot for growspace %s. Duration: %ss (scaled from %ss, factor: %.2f)",
            phase,
            self._growspace_id,
            scaled_duration,
            duration,
            self._shot_scale_factor,
        )

        existing_task = self._running_tasks.get("irrigation")
        if existing_task and not existing_task.done():
            _LOGGER.warning(
                "Cancelling lingering irrigation task for %s before firing new %s shot",
                self._growspace_id,
                phase,
            )
            existing_task.cancel()

        # Delegate to base _run_pump_cycle — inherits all safety guards:
        # pause_on_low_tank, max_cycles_per_day, daily_volume_cap_liters,
        # skip_during_dark, and log_to_logbook.
        task = self._config_entry.async_create_background_task(
            self.hass,
            self._run_pump_cycle("irrigation", pump_entity, scaled_duration, {"phase": phase}),
            f"irrigation_pump_{self._growspace_id}_irrigation",
        )
        self._running_tasks["irrigation"] = task

    def _is_halted_by_runoff_ec(self, growspace: Growspace) -> bool:
        """Return True and log a warning when the latest drain EC exceeds the configured threshold."""
        threshold = growspace.irrigation_config.halt_on_runoff_ec_threshold
        if threshold is None:
            return False
        readings = growspace.drain_config.readings
        if not readings:
            return False
        latest_ec = readings[-1].drain_ec
        if latest_ec > threshold:
            _LOGGER.warning(
                "Growspace %s: drain EC %.2f exceeds halt threshold %.2f. Suspending irrigation",
                self._growspace_id,
                latest_ec,
                threshold,
            )
            return True
        return False

    def _get_pump_entity(self) -> str | None:
        """Get configured irrigation pump entity."""
        growspace = self.growspace
        # Ensure we return a string or None, explicitly cast if needed or rely on typed access
        return growspace.irrigation_config.irrigation_pump_entity or None

    # Maps internal phase display strings to the canonical p1/p2/p3 values stored on
    # IrrigationConfig and read by the frontend.  Phases without an entry (e.g.
    # "Disabled (No Sensor)") leave active_steering_phase unchanged.
    _CANONICAL_PHASE: dict[str, str] = {
        "P0 - Activation": "p1",
        "P1 - Ramp Up": "p1",
        "P2 - Maintenance": "p2",
        "P3 - Dry Back": "p3",
        "P3": "p3",
    }

    def _phase_boundary_times(
        self, strategy: IrrigationStrategy, growspace: Growspace, reference_date: date
    ) -> SteeringPhaseBoundaries:
        """Return the crop-steering phase boundary datetimes anchored on reference_date."""
        lights_on_source = strategy.detected_lights_on_time or strategy.lights_on_time
        try:
            lights_on = datetime.strptime(lights_on_source, "%H:%M:%S").time()
        except ValueError:
            lights_on = datetime.strptime(lights_on_source, "%H:%M").time()

        # Default to 12 hours when the growspace has no day-length config.
        # Prefer flower hours, as crop steering is typically flower-focused.
        day_hours = 12
        if growspace.environment_config:
            day_hours = getattr(
                growspace.environment_config,
                "flower_day_hours",
                getattr(growspace.environment_config, "veg_day_hours", 12),
            )

        lights_on_dt = datetime.combine(reference_date, lights_on, tzinfo=now().tzinfo)
        p0_end_dt = lights_on_dt + timedelta(minutes=strategy.p0_duration_minutes)
        lights_off_dt = lights_on_dt + timedelta(hours=day_hours)
        p2_stop_dt = lights_off_dt - timedelta(
            minutes=strategy.p2_stop_before_lights_off_minutes
        )
        return SteeringPhaseBoundaries(
            lights_on=lights_on_dt,
            p0_end=p0_end_dt,
            p2_stop=p2_stop_dt,
            lights_off=lights_off_dt,
        )

    @property
    @override
    def projected_shot_window(self) -> dict[str, str] | None:
        """Return the {start, end} ISO range for the next projected crop-steering shot.

        Bounded by operational guardrails (shot cooldown, phase-window timing) rather
        than a statistical confidence interval, so it's meaningful from day one without
        any VWC sensor history. See ADR-0011 (lovelace-growspace-manager-card) for the
        reasoning behind a guardrail-bound range over a depletion-rate model.
        """
        growspace = self.growspace
        strategy = growspace.irrigation_strategy
        if not strategy or not strategy.enabled:
            return None
        if not strategy.lights_on_time or strategy.shot_interval_minutes is None:
            return None

        current_dt = now()
        today = current_dt.date()
        boundaries = self._phase_boundary_times(strategy, growspace, today)

        # Match on the display string directly — the canonical p1/p2/p3 mapping
        # collapses P0 into "p1" for the frontend's active_steering_phase, but P0
        # has its own time-bound window distinct from P1's threshold-driven one.
        if self._current_phase == "P0 - Activation":
            latest = boundaries.p0_end
        elif self._current_phase in ("P1 - Ramp Up", "P2 - Maintenance"):
            latest = boundaries.p2_stop
        else:
            # P3 (or unknown/disabled) — no shots fire today; roll forward to tomorrow
            return self._tomorrows_shot_window(strategy, growspace, today)

        earliest = current_dt
        last_shot = self._last_shot_dt()
        if last_shot:
            cooldown_end = last_shot + timedelta(minutes=strategy.shot_interval_minutes)
            if cooldown_end > current_dt:
                earliest = cooldown_end

        if earliest >= latest:
            # Today's active window has effectively closed — roll forward to tomorrow
            return self._tomorrows_shot_window(strategy, growspace, today)

        return {"start": earliest.isoformat(), "end": latest.isoformat()}

    def _tomorrows_shot_window(
        self, strategy: IrrigationStrategy, growspace: Growspace, today: date
    ) -> dict[str, str]:
        """Return tomorrow's {start, end} projected shot window (P1 start to P2 stop)."""
        tomorrow = today + timedelta(days=1)
        boundaries = self._phase_boundary_times(strategy, growspace, tomorrow)
        return {"start": boundaries.p0_end.isoformat(), "end": boundaries.p2_stop.isoformat()}

    def _set_phase(self, phase: str) -> bool:
        """Update phase state; log the transition to the HA logbook when enabled.

        Returns True when the phase actually changed so the caller can decide
        whether to push a coordinator update to subscribers.
        """
        if self._current_phase == phase:
            return False

        old_phase = self._current_phase
        _LOGGER.debug(
            "Growspace %s VWC Steering Phase changed: %s -> %s",
            self._growspace_id,
            old_phase,
            phase,
        )
        self._current_phase = phase

        canonical = self._CANONICAL_PHASE.get(phase)
        if canonical is not None:
            self.growspace.irrigation_config.active_steering_phase = canonical
            if canonical == "p3":
                self.growspace.irrigation_config.phase_changed_at = now().isoformat()

        if old_phase == "P1 - Ramp Up" and phase == "P2 - Maintenance":
            _LOGGER.info(
                "Growspace %s transitioned from P1 to P2. Resetting feedback scale factor",
                self._growspace_id,
            )
            self._shot_scale_factor = 1.0

        if self.growspace.irrigation_config.log_to_logbook:
            self._fire_logbook_event(
                f"VWC phase transition: {old_phase} → {phase}",
                category="irrigation",
            )
        return True

    @override
    async def _async_report_cycle_completion(
        self,
        *,
        event_type: str,
        start_dt: datetime,
        end_dt: datetime,
        duration_sec: float,
        moisture_before: float | None,
        volume_dispensed_today: float,
        wait_seconds: float,
    ) -> None:
        """Wait for the moisture sensor to settle, report cycle completion, and update dynamic shot scaling."""
        await super()._async_report_cycle_completion(
            event_type=event_type,
            start_dt=start_dt,
            end_dt=end_dt,
            duration_sec=duration_sec,
            moisture_before=moisture_before,
            volume_dispensed_today=volume_dispensed_today,
            wait_seconds=wait_seconds,
        )
        if event_type == "irrigation":
            sensor_entity = self.growspace.environment_config.soil_moisture_sensor
            if sensor_entity:
                moisture_after = self._get_sensor_value(sensor_entity)
                self._update_shot_feedback(moisture_before, moisture_after)

    def _update_shot_feedback(
        self, moisture_before: float | None, moisture_after: float | None
    ) -> None:
        """Evaluate the shot's effect on soil moisture and adjust the scale factor."""
        if moisture_before is None or moisture_after is None:
            return

        target = self.growspace.irrigation_strategy.target_vwc_percent
        d_target = target - moisture_before
        d_actual = moisture_after - moisture_before

        # Guard against division by very small numbers or non-positive actual delta
        if d_target <= 0.5 or d_actual <= 0:
            return

        ratio = d_actual / d_target
        if ratio > 1.0:
            # Overshot target: reduce scale factor
            aggressiveness = 1.0
            self._shot_scale_factor = max(
                0.5,
                min(1.0, self._shot_scale_factor - aggressiveness * (ratio - 1.0)),
            )
            _LOGGER.debug(
                "Growspace %s overshot VWC target. Expected delta: %.2f%%, actual: %.2f%%. "
                "New feedback scale factor: %.2f",
                self._growspace_id,
                d_target,
                d_actual,
                self._shot_scale_factor,
            )
        else:
            # Undershot or met target: recover scale factor
            beta = 0.1
            self._shot_scale_factor = max(
                0.5,
                min(1.0, self._shot_scale_factor + beta * (1.0 - ratio)),
            )
            _LOGGER.debug(
                "Growspace %s dynamic shot VWC feedback. Expected delta: %.2f%%, actual: %.2f%%. "
                "New feedback scale factor: %.2f",
                self._growspace_id,
                d_target,
                d_actual,
                self._shot_scale_factor,
            )
