"""Coordinator for VWC-based crop steering irrigation."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.dt import now, parse_datetime

from .const import (
    EC_MODULATION_FULL_SCALE_DELTA,
    EC_MODULATION_MAX_FACTOR,
    EC_MODULATION_MIN_FACTOR,
    PlantStage,
    ShotSizingMode,
)
from .domain.ec_state import (
    ECRecommendation,
    ECState,
    ECStateResolver,
    resolve_active_feed_ec,
    resolve_feed_stage_week,
)
from .irrigation_coordinator import BaseIrrigationCoordinator
from .models import Growspace, IrrigationStrategy

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

# Plant stages whose plants no longer sit on the irrigation line; excluded from
# the live plant count that backs per-plant Volume Mode dosing (see ADR-0011).
_NON_LIVE_STAGES: frozenset[str] = frozenset(
    {PlantStage.DRY.value, PlantStage.CURE.value}
)


@dataclass(frozen=True, slots=True)
class SteeringPhaseBoundaries:
    """Datetimes anchored on a reference date marking crop-steering phase transitions."""

    lights_on: datetime
    p0_end: datetime
    p2_stop: datetime
    lights_off: datetime


@dataclass(frozen=True, slots=True)
class ShotComposition:
    """Fully-explained composition of the most recent fired steering shot.

    Surfaced in diagnostics/payload so any shot is explainable end to end:
    ``effective = base × vwc_factor × ec_factor``, then safety caps clamp the
    delivered duration (``capped`` is True when a cap actually reduced it).
    ``ec_modulation_available`` distinguishes "modulation off / no pore-EC
    sensor / no reading → factor 1.0" from "within band → factor 1.0".
    """

    phase: str
    base_seconds: int
    vwc_factor: float
    ec_factor: float
    ec_modulation_available: bool
    composed_seconds: int
    effective_seconds: int
    capped: bool
    timestamp: str


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
        # Interval-domain sibling of the size factor (ADR-0014): scales the
        # minimum-cooldown floor. Clamped [1.0, dynamic_interval_ceiling] — only
        # ever lengthens spacing or recovers to nominal, never shortens.
        self._interval_scale_factor = 1.0
        # Last fired shot's full composition, exposed for diagnostics so any
        # shot is explainable (base × VWC × EC, then caps). None until a shot
        # has fired this session.
        self._last_shot_composition: ShotComposition | None = None

        # Last computed Volume Mode shot volume (ml) and the live plant count it
        # was derived from, so a count-driven volume change can be detected
        # across loop ticks and written to the logbook (ADR-0011).
        self._last_shot_volume_ml: float | None = None
        self._last_live_plant_count: int | None = None

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
        self._interval_scale_factor = 1.0
        self._last_shot_volume_ml = None
        self._last_live_plant_count = None

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

            # Feed the SubstrateTracker before executing phase logic so the
            # reading reflects the substrate state going into this tick's
            # decision (and any shot it fires is recorded against this VWC).
            self._feed_substrate_reading(current_vwc, period, growspace)

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

        # Zero-plant suspend (ADR-0011): in active Volume Mode a growspace with no
        # live plants has no irrigation demand. Keep the loop alive but report an
        # idle phase and fire no shots — never a 0 ml no-op or a seconds fallback.
        if (
            period in ("P0", "WINDOW")
            and self._volume_mode_active(strategy)
            and self._live_plant_count() == 0
        ):
            self._set_phase("Idle (no plants)")
            return

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

    @staticmethod
    def _shot_params_for_phase(
        strategy: IrrigationStrategy, phase: str
    ) -> tuple[int, int]:
        """Return the (duration_seconds, interval_minutes) pair for a steering phase.

        P2 maintenance shots use the P2 pair; everything else (P1 ramp-up, and
        P0 which collapses into P1) uses the P1 pair.
        """
        if phase == "P2":
            return (
                strategy.p2_shot_duration_seconds,
                strategy.p2_shot_interval_minutes,
            )
        return (
            strategy.p1_shot_duration_seconds,
            strategy.p1_shot_interval_minutes,
        )

    def _live_plant_count(self) -> int:
        """Return the number of live plants on the growspace's irrigation line.

        "Live" excludes plants in the dry/cure stages, which no longer draw
        irrigation. This is the per-plant dosing basis for Volume Mode (ADR-0011).
        """
        plants = self._main_coordinator.services.growspaces.get_growspace_plants(
            self._growspace_id
        )
        return sum(
            1 for p in plants if str(getattr(p, "stage", "")) not in _NON_LIVE_STAGES
        )

    @staticmethod
    def _volume_prerequisites_met(
        strategy: IrrigationStrategy, growspace: Growspace
    ) -> bool:
        """Return True when Volume Mode's prerequisites (profile + flow rate) are present."""
        return (
            strategy.substrate_profile.is_configured
            and growspace.irrigation_config.pump_flow_rate_ml_per_sec > 0.0
        )

    def _volume_mode_active(self, strategy: IrrigationStrategy) -> bool:
        """Return True when Volume Mode is selected AND its prerequisites hold.

        Volume Mode never auto-activates on prerequisites alone — the mode must
        be explicitly selected. If it is selected but prerequisites have lapsed,
        this returns False (fail safe): the growspace is treated as not-capable
        and no Volume Mode shots fire (callers suspend rather than guess seconds).
        """
        return (
            strategy.shot_sizing_mode == ShotSizingMode.VOLUME
            and self._volume_prerequisites_met(strategy, self.growspace)
        )

    def _volume_mode_base_duration(
        self, strategy: IrrigationStrategy, phase: str
    ) -> int | None:
        """Return the base pump-seconds for a Volume Mode shot, or None to suspend.

        Converts the per-phase percent-of-substrate-volume size to milliliters
        (``percent/100 × liters_per_pot × live_count × 1000``) and then to pump
        seconds via the flow rate (``ml / flow_rate_ml_per_sec``). Returns None
        when the live plant count is zero so the caller suspends the shot rather
        than firing a 1 s floor. Also writes a logbook entry when a live-count
        change alters the computed shot volume (ADR-0011).
        """
        live_count = self._live_plant_count()
        percent = (
            strategy.p2_shot_volume_percent
            if phase == "P2"
            else strategy.p1_shot_volume_percent
        )
        profile = strategy.substrate_profile
        flow_rate = self.growspace.irrigation_config.pump_flow_rate_ml_per_sec

        shot_volume_ml = (
            (percent / 100.0) * profile.liters_per_pot * live_count * 1000.0
        )
        self._maybe_log_volume_change(shot_volume_ml, live_count)

        if live_count == 0 or shot_volume_ml <= 0.0:
            return None
        return max(1, int(round(shot_volume_ml / flow_rate)))

    def _maybe_log_volume_change(self, shot_volume_ml: float, live_count: int) -> None:
        """Write a logbook entry when a live-count change alters the shot volume.

        Only fires in active Volume Mode when the computed volume actually
        changed versus the previous tick, so Seconds Mode and unchanged ticks
        never spam the logbook (ADR-0011).
        """
        prev_volume = self._last_shot_volume_ml
        prev_count = self._last_live_plant_count
        self._last_shot_volume_ml = shot_volume_ml
        self._last_live_plant_count = live_count

        if (
            prev_volume is None
            or prev_count is None
            or round(prev_volume) == round(shot_volume_ml)
            or prev_count == live_count
        ):
            return

        if not self.growspace.irrigation_config.log_to_logbook:
            return

        self._fire_logbook_event(
            f"shot volume {round(prev_volume)}→{round(shot_volume_ml)} ml: "
            f"plant count {prev_count}→{live_count}",
            category="irrigation",
        )

    def _handle_watering(self, strategy: IrrigationStrategy, phase: str) -> None:
        """Handle execution of a shot if the phase's interval permits."""
        now_dt = now()
        growspace = self.growspace
        seconds_duration, interval_minutes = self._shot_params_for_phase(
            strategy, phase
        )

        last_shot = self._last_shot_dt()
        if last_shot:
            elapsed = (now_dt - last_shot).total_seconds() / 60.0
            if elapsed < interval_minutes * self._interval_scale_factor:
                return

        pump_entity = self._get_pump_entity()
        if not pump_entity:
            return

        # Derive the BASE per-shot duration. Volume Mode converts the per-phase
        # percent-of-substrate-volume size to pump seconds via the live plant
        # count and flow rate; Seconds Mode keeps the configured seconds exactly.
        # The base is computed BEFORE the VWC feedback and EC modulation factors
        # (and any downstream safety caps).
        if self._volume_mode_active(strategy):
            duration = self._volume_mode_base_duration(strategy, phase)
            if duration is None:
                # Zero live plants: suspend rather than firing a floored shot.
                return
        else:
            duration = seconds_duration

        # Shot Size Composition: effective = base × VWC factor × EC factor.
        # The two factors are computed independently (they may pull opposite
        # ways and partially cancel — physically sensible). EC modulation
        # applies to P2 maintenance shots only (the issue's actuation point);
        # P1 ramp-up keeps a neutral EC factor of 1.0. Safety caps are applied
        # LAST, downstream in _run_pump_cycle, against this composed duration.
        if phase == "P2":
            ec_factor, ec_available = self._compute_ec_modulation(strategy, growspace)
        else:
            ec_factor, ec_available = 1.0, False
        composed_factor = self._shot_scale_factor * ec_factor
        scaled_duration = max(1, int(round(duration * composed_factor)))

        # Caps are evaluated last and never exceeded: record whether they would
        # block this composed shot so a fired (or skipped) shot is explainable.
        capped = self._check_safety_guards(scaled_duration) is not None
        self._last_shot_composition = ShotComposition(
            phase=phase,
            base_seconds=duration,
            vwc_factor=round(self._shot_scale_factor, 3),
            ec_factor=round(ec_factor, 3),
            ec_modulation_available=ec_available,
            composed_seconds=scaled_duration,
            effective_seconds=0 if capped else scaled_duration,
            capped=capped,
            timestamp=now_dt.isoformat(),
        )

        _LOGGER.info(
            "Firing %s shot for growspace %s. Duration: %ss "
            "(base %ss × VWC %.2f × EC %.2f)",
            phase,
            self._growspace_id,
            scaled_duration,
            duration,
            self._shot_scale_factor,
            ec_factor,
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
            self._run_pump_cycle(
                "irrigation", pump_entity, scaled_duration, {"phase": phase}
            ),
            f"irrigation_pump_{self._growspace_id}_irrigation",
        )
        self._running_tasks["irrigation"] = task

        # Bound substrate dryback windows on the shot. The pre-shot VWC is the
        # trough for the just-closed in-cycle window; the tracker re-arms the
        # post-shot peak from the readings that follow.
        self._record_substrate_shot(phase)

    def _feed_substrate_reading(
        self, current_vwc: float, period: str, growspace: Growspace
    ) -> None:
        """Feed the current VWC reading to the growspace's SubstrateTracker.

        ``lit`` marks whether the lit period is active (lights-on to lights-off),
        which the tracker uses for the zero-shot-day overnight-peak fallback.
        """
        tracker = self._main_coordinator.services.growspaces.get_substrate_tracker(
            self._growspace_id
        )
        if tracker is None:
            return
        current_dt = now()
        boundaries = self._phase_boundary_times(
            growspace.irrigation_strategy, growspace, current_dt.date()
        )
        lit = boundaries.lights_on <= current_dt < boundaries.lights_off
        tracker.record_reading(current_vwc, current_dt.isoformat(), lit=lit)

        # Feed the averaged pore-EC reading for the daily EC trend. Absent
        # pore-EC sensors, the trend stays unavailable (never "stable").
        pore_ec = self._average_pore_ec(growspace)
        if pore_ec is not None:
            tracker.record_pore_ec(pore_ec, current_dt.isoformat())

    def _average_pore_ec(self, growspace: Growspace) -> float | None:
        """Average the configured pore-EC sensors, or None if none are usable.

        Skips ``unknown``/``unavailable``/non-numeric states exactly like the
        VWC reading path, so a partial sensor dropout still yields a value from
        the remaining sensors and a full dropout yields None (unavailable).
        """
        sensors = growspace.environment_config.pore_ec_sensors
        if not sensors:
            return None
        values = [
            value
            for sensor in sensors
            if (value := self._get_sensor_value(sensor)) is not None
        ]
        if not values:
            return None
        return sum(values) / len(values)

    def shot_composition_payload(self) -> dict[str, Any]:
        """Return the frontend/diagnostics view of the last shot composition.

        Always carries the current modulation *capability* (whether opt-in,
        band, and a pore-EC reading are all present) plus the configured band,
        so the card can explain modulation even before the first shot fires.
        ``last_shot`` is None until a P2/P1 shot has fired this session.
        """
        growspace = self.growspace
        strategy = growspace.irrigation_strategy
        _, ec_available = self._compute_ec_modulation(strategy, growspace)
        composition = self._last_shot_composition
        return {
            "ec_modulation_enabled": strategy.ec_modulation_enabled,
            "ec_modulation_available": ec_available,
            "pore_ec_target_min": strategy.pore_ec_target_min,
            "pore_ec_target_max": strategy.pore_ec_target_max,
            "current_vwc_factor": round(self._shot_scale_factor, 3),
            "current_interval_factor": round(self._interval_scale_factor, 3),
            "dynamic_shot_enabled": strategy.dynamic_shot_enabled,
            "last_shot": asdict(composition) if composition is not None else None,
        }

    def _resolve_feed_target(
        self, growspace: Growspace
    ) -> tuple[tuple[float, float] | None, str]:
        """Resolve the growspace's Active Feed EC Target as ``(band, source)``.

        Reads the growspace's plants (for the furthest-along live stage and its
        week), the configured EC ramp curves, and the per-stage feed-EC ranges.
        """
        plants = self._main_coordinator.services.growspaces.get_growspace_plants(
            self._growspace_id
        )
        stage, week = resolve_feed_stage_week(plants)
        ramp_curves = self._main_coordinator.services.config.ec_ramp_curves
        return resolve_active_feed_ec(
            stage, week, ramp_curves, growspace.irrigation_config.ec_target_ranges
        )

    def ec_state(self) -> ECState:
        """Build the reconciled :class:`ECState` for this growspace.

        The one place EC is reasoned about (ADR-0015): the modulation direction
        (pore-vs-band) and the Active Feed EC Target, behind a single seam.
        """
        growspace = self.growspace
        return ECStateResolver(
            growspace.irrigation_strategy,
            lambda: self._average_pore_ec(growspace),
            lambda: self._resolve_feed_target(growspace),
        ).resolve()

    def ec_state_payload(self) -> dict[str, Any]:
        """Return the frontend/diagnostics view of the current EC State."""
        state = self.ec_state()
        return {
            "pore_ec": state.pore_ec,
            "recommendation": state.recommendation.value,
            "active_feed_ec": (
                list(state.active_feed_ec) if state.active_feed_ec is not None else None
            ),
            "feed_ec_source": state.feed_ec_source,
        }

    @staticmethod
    def _ec_modulation_factor_for_reading(
        measured_ec: float, band_min: float, band_max: float
    ) -> float:
        """Map a measured pore EC against the band to a bounded shot factor.

        Pure helper: above the band → factor > 1.0 (flush), below → < 1.0
        (stack), within → exactly 1.0. The response is proportional to the
        excursion past the nearest band edge, normalised so an excursion of
        ``EC_MODULATION_FULL_SCALE_DELTA`` saturates at the bound, then clamped
        to ``[EC_MODULATION_MIN_FACTOR, EC_MODULATION_MAX_FACTOR]``.
        """
        if measured_ec > band_max:
            excursion = measured_ec - band_max
            span = EC_MODULATION_MAX_FACTOR - 1.0
            factor = 1.0 + span * (excursion / EC_MODULATION_FULL_SCALE_DELTA)
            return min(EC_MODULATION_MAX_FACTOR, factor)
        if measured_ec < band_min:
            excursion = band_min - measured_ec
            span = 1.0 - EC_MODULATION_MIN_FACTOR
            factor = 1.0 - span * (excursion / EC_MODULATION_FULL_SCALE_DELTA)
            return max(EC_MODULATION_MIN_FACTOR, factor)
        return 1.0

    def _compute_ec_modulation(
        self, strategy: IrrigationStrategy, growspace: Growspace
    ) -> tuple[float, bool]:
        """Return ``(factor, available)`` for EC modulation on a P2 shot.

        Reads the direction from the [[EC State]] seam (ADR-0015): the resolver
        decides STACK/HOLD/FLUSH/UNAVAILABLE from pore-EC-vs-band, and this method
        turns that into the existing ``(factor, available)`` contract. ``available``
        is the modulation *capability* flag — True only when opted in, a valid band
        is configured, and a measured pore EC exists (recommendation is not
        UNAVAILABLE). When unavailable the factor is exactly 1.0 — distinct in the
        payload from a measured "within band → 1.0" (available True, factor 1.0).
        """
        state = ECStateResolver(
            strategy, lambda: self._average_pore_ec(growspace)
        ).resolve()
        if state.recommendation is ECRecommendation.UNAVAILABLE:
            return 1.0, False
        # Recommendation chooses direction; the pure helper computes the bounded
        # magnitude. pore_ec and the band are guaranteed present/valid here.
        factor = self._ec_modulation_factor_for_reading(
            state.pore_ec,
            strategy.pore_ec_target_min,
            strategy.pore_ec_target_max,
        )
        return factor, True

    def _record_substrate_shot(self, phase: str) -> None:
        """Signal a fired shot to the SubstrateTracker for dryback bounding."""
        tracker = self._main_coordinator.services.growspaces.get_substrate_tracker(
            self._growspace_id
        )
        if tracker is None:
            return
        sensor_entity = self.growspace.environment_config.soil_moisture_sensor
        vwc = self._get_sensor_value(sensor_entity) if sensor_entity else None
        if vwc is None:
            return
        tracker.record_shot(phase, now().isoformat(), vwc)

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

        # Cooldown anchors on the active phase's interval: P2 maintenance uses
        # the P2 pair, everything else the P1 pair.
        active_phase = "P2" if self._current_phase == "P2 - Maintenance" else "P1"
        _, interval_minutes = self._shot_params_for_phase(strategy, active_phase)
        if not strategy.lights_on_time or interval_minutes is None:
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
            effective_interval = interval_minutes * self._interval_scale_factor
            cooldown_end = last_shot + timedelta(minutes=effective_interval)
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
        return {
            "start": boundaries.p0_end.isoformat(),
            "end": boundaries.p2_stop.isoformat(),
        }

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
                "Growspace %s transitioned from P1 to P2. Resetting feedback scale factors",
                self._growspace_id,
            )
            self._shot_scale_factor = 1.0
            self._interval_scale_factor = 1.0

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
        """Evaluate the shot's effect on soil moisture and adjust the feedback factors.

        Drives both the size factor (shot volume/duration) and the interval
        factor (minimum-cooldown spacing) from the same overshoot ratio: on
        overshoot the shot shrinks and the interval lengthens; on undershoot
        both recover toward nominal (1.0). Inert when Adaptive Shot Control is
        disabled (ADR-0014).
        """
        strategy = self.growspace.irrigation_strategy
        if not strategy.dynamic_shot_enabled:
            return
        if moisture_before is None or moisture_after is None:
            return

        target = strategy.target_vwc_percent
        d_target = target - moisture_before
        d_actual = moisture_after - moisture_before

        # Guard against division by very small numbers or non-positive actual delta
        if d_target <= 0.5 or d_actual <= 0:
            return

        aggressiveness = strategy.dynamic_aggressiveness
        recovery = strategy.dynamic_recovery
        size_floor = strategy.dynamic_shot_size_floor
        interval_ceiling = strategy.dynamic_interval_ceiling

        ratio = d_actual / d_target
        if ratio > 1.0:
            # Overshot target: shrink the shot and lengthen the interval.
            error = ratio - 1.0
            self._shot_scale_factor = max(
                size_floor,
                min(1.0, self._shot_scale_factor - aggressiveness * error),
            )
            self._interval_scale_factor = min(
                interval_ceiling,
                max(1.0, self._interval_scale_factor + aggressiveness * error),
            )
            direction = "overshot VWC target"
        else:
            # Undershot or met target: recover both factors toward nominal.
            error = 1.0 - ratio
            self._shot_scale_factor = max(
                size_floor,
                min(1.0, self._shot_scale_factor + recovery * error),
            )
            self._interval_scale_factor = min(
                interval_ceiling,
                max(1.0, self._interval_scale_factor - recovery * error),
            )
            direction = "dynamic shot VWC feedback"

        _LOGGER.debug(
            "Growspace %s %s. Expected delta: %.2f%%, actual: %.2f%%. "
            "Size factor: %.2f, interval factor: %.2f",
            self._growspace_id,
            direction,
            d_target,
            d_actual,
            self._shot_scale_factor,
            self._interval_scale_factor,
        )
