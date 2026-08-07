"""Coordinator for VWC-based crop steering irrigation.

The per-minute steering *decision* lives in the [[Steering Phase Machine]]
(``domain/steering_phase.py``, ADR-0023); this coordinator is the effects
shell: it reads sensors, feeds the SubstrateTracker, and executes whatever the
[[Steering Tick Verdict]] names — phase writes, logbook events, the composer
reset, and the pump cycle.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util.dt import now, parse_datetime

from .const import PlantStage
from .domain.ec_state import (
    ECRecommendation,
    ECState,
    ECStateResolver,
    RunoffInputs,
    ec_modulation_factor_for_reading,
    resolve_active_feed_ec,
    resolve_feed_stage_week,
    runoff_halt,
)
from .domain.infiltration import InfiltrationMonitor
from .domain.shot_composer import FeedbackTuning, ShotComposer
from .domain.steering_phase import (
    ShotRequest,
    SteeringPhaseMachine,
    SteeringTickInputs,
    SteeringTickVerdict,
    phase_boundary_times,
    resolve_day_hours,
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

        # Owns the phase state and the per-tick steering decision
        # (domain/steering_phase.py, ADR-0023). The machine owns the rules
        # (daily reset guard, P1→P2 detection); this shell owns the triggers
        # and executes every effect the verdict names.
        self._machine = SteeringPhaseMachine(growspace_id)
        # Owns the Adaptive Shot Control factors and the Shot Size Composition
        # (domain/shot_composer.py). The steering phase machine names its
        # reset() triggers (lights-on / P1→P2); it never reaches back into
        # the coordinator.
        self._composer = ShotComposer()
        # Measures whether the substrate is still absorbing the last shot
        # (domain/infiltration.py, ADR-0031). Measurement only for now: nothing
        # gates on it, and it samples on distinct *sensor* updates rather than
        # on loop ticks, so it needs the freshness-aware read below.
        self._infiltration = InfiltrationMonitor()

        # We track if we have logged a "sensor missing" warning recently to avoid spam
        self._sensor_warning_logged = False

        # Why the last applied verdict withheld a shot, surfaced in the
        # shot-composition payload (ADR-0031). Diagnostic only — nothing in the
        # irrigation path reads it.
        self._last_suppressed_by: str | None = None

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
        self._machine.reset()
        self._composer.reset()

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
                self._infiltration.reset()
                self._apply_verdict(self._machine.mark_no_sensor(), strategy)
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
                self._infiltration.reset()
                return

            # Feed the Infiltration Monitor before the EC halt check: the
            # substrate keeps absorbing whether or not steering is halted, and a
            # gap in the samples would be indistinguishable from a dropout.
            self._record_infiltration(sensor_entity, current_vwc)

            if self._is_halted_by_runoff_ec(growspace):
                return

            # Feed the SubstrateTracker before executing phase logic so the
            # reading reflects the substrate state going into this tick's
            # decision (and any shot it fires is recorded against this VWC).
            self._feed_substrate_reading(current_vwc, growspace)

            verdict = self._machine.tick(
                self._tick_inputs(current_vwc, strategy, growspace)
            )
            self._apply_verdict(verdict, strategy)

            if verdict.phase_changed:
                self._main_coordinator.async_set_updated_data(
                    self._main_coordinator.data
                )

        except Exception:
            _LOGGER.exception(
                "Error in VWC Irrigation loop for growspace %s",
                self._growspace_id,
            )

    def _tick_inputs(
        self, current_vwc: float, strategy: IrrigationStrategy, growspace: Growspace
    ) -> SteeringTickInputs:
        """Assemble the plain-value inputs for one steering tick."""
        config = growspace.irrigation_config
        return SteeringTickInputs(
            now=now(),
            vwc=current_vwc,
            strategy=strategy,
            auto_advance_p2_to_p3=config.auto_advance_p2_to_p3,
            soil_trigger_percent=config.soil_trigger_percent,
            pump_flow_rate_ml_per_sec=config.pump_flow_rate_ml_per_sec,
            pump_configured=bool(self._get_pump_entity()),
            day_hours=resolve_day_hours(growspace.environment_config),
            live_plant_count=self._live_plant_count(),
            last_shot=self._last_shot_dt(),
            interval_factor=self._composer.interval_factor,
        )

    def _apply_verdict(
        self, verdict: SteeringTickVerdict, strategy: IrrigationStrategy
    ) -> None:
        """Execute the effects a Steering Tick Verdict names.

        The verdict records the decision; every effect happens here: the
        canonical phase write, the P1→P2 composer reset (before any shot
        composes), logbook events, and the pump cycle.
        """
        config = self.growspace.irrigation_config
        self._last_suppressed_by = verdict.suppressed_by

        if verdict.phase_changed:
            if verdict.canonical is not None:
                config.active_steering_phase = verdict.canonical
                if verdict.canonical == "p3":
                    config.phase_changed_at = now().isoformat()

            if verdict.reset_composer:
                _LOGGER.info(
                    "Growspace %s transitioned from P1 to P2. Resetting feedback scale factors",
                    self._growspace_id,
                )
                self._composer.reset()

            if config.log_to_logbook and verdict.transition_message:
                self._fire_logbook_event(
                    verdict.transition_message, category="irrigation"
                )

        if verdict.volume_change_note and config.log_to_logbook:
            self._fire_logbook_event(verdict.volume_change_note, category="irrigation")

        if verdict.fire is not None:
            self._fire_shot(strategy, verdict.fire)

    def _fire_shot(self, strategy: IrrigationStrategy, request: ShotRequest) -> None:
        """Compose and fire a steering shot the tick verdict requested."""
        pump_entity = self._get_pump_entity()
        if not pump_entity:
            return
        growspace = self.growspace

        # Shot Size Composition: effective = base × VWC factor × EC factor.
        # The ShotComposer owns the multiply, the VWC feedback factor, and the
        # cap-aware ShotComposition record. EC modulation (P2 only) and the
        # safety-cap check are injected so the EC State seam and downstream
        # _run_pump_cycle enforcement stay where they are; caps are still applied
        # LAST, downstream, against this composed duration.
        composition = self._composer.compose(
            request.phase,
            request.base_seconds,
            lambda: self._compute_ec_modulation(strategy, growspace),
            lambda secs: self._check_safety_guards(secs) is not None,
            now().isoformat(),
        )
        scaled_duration = composition.composed_seconds

        _LOGGER.info(
            "Firing %s shot for growspace %s. Duration: %ss "
            "(base %ss × VWC %.2f × EC %.2f)",
            request.phase,
            self._growspace_id,
            scaled_duration,
            request.base_seconds,
            composition.vwc_factor,
            composition.ec_factor,
        )

        existing_task = self._running_tasks.get("irrigation")
        if existing_task and not existing_task.done():
            _LOGGER.warning(
                "Cancelling lingering irrigation task for %s before firing new %s shot",
                self._growspace_id,
                request.phase,
            )
            existing_task.cancel()

        # Delegate to base _run_pump_cycle — inherits all safety guards:
        # pause_on_low_tank, max_cycles_per_day, daily_volume_cap_liters,
        # skip_during_dark, and log_to_logbook.
        task = self._config_entry.async_create_background_task(
            self.hass,
            self._run_pump_cycle(
                "irrigation", pump_entity, scaled_duration, {"phase": request.phase}
            ),
            f"irrigation_pump_{self._growspace_id}_irrigation",
        )
        self._running_tasks["irrigation"] = task

        # Bound substrate dryback windows on the shot. The pre-shot VWC is the
        # trough for the just-closed in-cycle window; the tracker re-arms the
        # post-shot peak from the readings that follow.
        self._record_substrate_shot(request.phase)

    def _last_shot_dt(self) -> datetime | None:
        """Return the last confirmed pump-cycle start time, or None.

        Reads `_last_cycle_timestamp` (set by `_run_pump_cycle` only after the
        switch is confirmed on) rather than stamping optimistically — a skipped
        cycle (e.g. dark-period guard) must not silently rate-limit future shots.
        """
        if not self._last_cycle_timestamp:
            return None
        return parse_datetime(self._last_cycle_timestamp)

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

    def _record_infiltration(self, sensor_entity: str, current_vwc: float) -> None:
        """Offer the reading to the Infiltration Monitor with the sensor's own time.

        The existing reading path is freshness-blind — ``_get_sensor_value``
        discards ``last_updated`` and the substrate tracker stamps readings with
        the loop's ``now()``, timestamps that are load-bearing for dryback
        bounding. Rather than retrofit those readers, this reads the state again
        purely for its timestamp; the monitor dedupes the repeats itself. No
        ``await`` separates that read from the one that produced ``current_vwc``,
        so the two cannot straddle a state change. A state carrying no update
        time yields no distinct-update signal, so it is not a measurement and is
        skipped.
        """
        state = self.hass.states.get(sensor_entity)
        last_updated = state.last_updated if state else None
        if last_updated is None:
            return
        self._infiltration.record(current_vwc, last_updated)

    def _feed_substrate_reading(self, current_vwc: float, growspace: Growspace) -> None:
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
        boundaries = phase_boundary_times(
            growspace.irrigation_strategy,
            resolve_day_hours(growspace.environment_config),
            current_dt.date(),
            current_dt.tzinfo,
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

        ``suppressed_by`` names why the last steering tick withheld a shot (one
        of the ``SUPPRESSED_BY_*`` reasons), so a growspace that isn't watering
        is explainable without debug logging; None when the last tick fired or
        never reached the shot decision.
        """
        growspace = self.growspace
        strategy = growspace.irrigation_strategy
        _, ec_available = self._compute_ec_modulation(strategy, growspace)
        composition = self._composer.last_composition
        return {
            "ec_modulation_enabled": strategy.ec_modulation_enabled,
            "ec_modulation_available": ec_available,
            "pore_ec_target_min": strategy.pore_ec_target_min,
            "pore_ec_target_max": strategy.pore_ec_target_max,
            "current_vwc_factor": round(self._composer.size_factor, 3),
            "current_interval_factor": round(self._composer.interval_factor, 3),
            "dynamic_shot_enabled": strategy.dynamic_shot_enabled,
            "infiltration": self._infiltration.state.value,
            "last_shot": asdict(composition) if composition is not None else None,
            "suppressed_by": self._last_suppressed_by,
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
            lambda: self._runoff_inputs(growspace),
        ).resolve()

    @staticmethod
    def _runoff_inputs(growspace: Growspace) -> RunoffInputs:
        """Assemble the runoff inputs the EC State resolver needs."""
        drain_config = growspace.drain_config
        return RunoffInputs(
            readings=drain_config.readings,
            max_ec_delta=drain_config.max_ec_delta,
            target_runoff_percent=drain_config.target_runoff_percent,
            halt_threshold=growspace.irrigation_config.halt_on_runoff_ec_threshold,
        )

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
            "runoff_ec": state.runoff_ec,
            "feed_to_runoff_delta": state.feed_to_runoff_delta,
            "runoff_percent": state.runoff_percent,
            "runoff_pct_target": state.runoff_pct_target,
            "halt_irrigation": state.halt_irrigation,
        }

    def _compute_ec_modulation(
        self, strategy: IrrigationStrategy, growspace: Growspace
    ) -> tuple[float, bool]:
        """Return ``(factor, available)`` for EC modulation on a P2 shot.

        Reads the direction from the [[EC State]] seam: the resolver decides
        STACK/HOLD/FLUSH/UNAVAILABLE from pore-EC-vs-band, with a sustained
        over-target runoff delta escalating HOLD→FLUSH (ADR-0016). The resolver is
        built with pore + runoff inputs but **not** the feed target — feed EC is
        display-only and never affects modulation, and omitting it keeps this
        P2-shot hot path off the plant-reading path.

        ``available`` is the modulation *capability* flag — True only when opted
        in, a valid band is configured, and a measured pore EC exists
        (recommendation is not UNAVAILABLE). When unavailable the factor is exactly
        1.0 — distinct in the payload from a measured "within band → 1.0".
        """
        state = ECStateResolver(
            strategy,
            lambda: self._average_pore_ec(growspace),
            read_runoff=lambda: self._runoff_inputs(growspace),
        ).resolve()
        if state.recommendation is ECRecommendation.UNAVAILABLE:
            return 1.0, False

        band_min = strategy.pore_ec_target_min
        band_max = strategy.pore_ec_target_max
        # The flush magnitude reflects whichever EC is driving it, through the one
        # helper (one explainable factor, ADR-0016): a pore-driven flush/stack uses
        # pore EC; a runoff-driven flush (pore within band, escalated to FLUSH by
        # sustained runoff stacking) uses the runoff EC, which sits above the band
        # when stacking. pore_ec is guaranteed present here.
        driver_ec = state.pore_ec
        if (
            state.recommendation is ECRecommendation.FLUSH
            and state.pore_ec <= band_max
            and state.runoff_ec is not None
        ):
            driver_ec = state.runoff_ec
        factor = ec_modulation_factor_for_reading(driver_ec, band_min, band_max)
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
        """Return True and log a warning when the runoff-EC safety halt is active.

        Reads the single source of truth — ``runoff_halt`` over the same
        ``RunoffInputs`` that back ``ECState.halt_irrigation`` — so the loop and
        the payload always agree. The check is independent of EC Modulation
        (ADR-0016) and deliberately does not build the full EC State (no pore/feed
        reads) on this safety hot path.
        """
        runoff = self._runoff_inputs(growspace)
        if not runoff_halt(runoff):
            return False
        latest_ec = runoff.readings[-1].drain_ec
        _LOGGER.warning(
            "Growspace %s: drain EC %.2f exceeds halt threshold %.2f. Suspending irrigation",
            self._growspace_id,
            latest_ec,
            runoff.halt_threshold,
        )
        return True

    def _get_pump_entity(self) -> str | None:
        """Get configured irrigation pump entity."""
        growspace = self.growspace
        # Ensure we return a string or None, explicitly cast if needed or rely on typed access
        return growspace.irrigation_config.irrigation_pump_entity or None

    @property
    @override
    def projected_shot_window(self) -> dict[str, str] | None:
        """Return the {start, end} ISO range for the next projected crop-steering shot.

        Thin adapter: the projection lives on the Steering Phase Machine so it
        reads the same boundaries and phase the tick uses and the two can never
        disagree about windows.
        """
        growspace = self.growspace
        return self._machine.projected_shot_window(
            growspace.irrigation_strategy,
            resolve_day_hours(growspace.environment_config),
            self._last_shot_dt(),
            self._composer.interval_factor,
            now(),
        )

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
                self._composer.observe(
                    moisture_before,
                    moisture_after,
                    FeedbackTuning.from_strategy(self.growspace.irrigation_strategy),
                )
