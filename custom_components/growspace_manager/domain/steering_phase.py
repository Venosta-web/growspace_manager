"""Steering Phase Machine: the one place the crop-steering tick is decided.

Owns the [[Crop Steering Phases]] state machine — the per-minute decision of
which phase the growspace is in (P0/P1/P2/P3, plus the non-canonical
"Disabled"/"Idle" states) and whether a steering shot may fire, returned as a
[[Steering Tick Verdict]] in the [[Cycle Verdict]] mould: it records the
decision and performs none of the effects.

Like [[ShotComposer]] — and unlike the pure-per-call [[EC State]] resolver —
this is a *stateful* controller: the phase, the daily ramp-up target flag, and
the Volume Mode change-tracking pair persist across ticks and have their own
reset rules (the midnight ``reset()``, the date-guarded daily target reset, the
P1→P2 detection), so they are retained here rather than threaded through by the
caller. The module owns those rules; the [[VWCIrrigationCoordinator]] owns the
triggers (the minute loop calls ``tick()``, the daily-reset listener calls
``reset()``) and executes every effect the verdict names — logbook events,
``active_steering_phase`` writes, the composer reset, and the pump cycle
itself. Everything here is computable from plain values: no ``hass``, no
sensors, no coordinator (see ``tests/domain/test_steering_phase.py``).
See ADR-0023.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
import logging
from typing import Any

from custom_components.growspace_manager.const import ShotSizingMode
from custom_components.growspace_manager.domain.infiltration import InfiltrationState
from custom_components.growspace_manager.models import IrrigationStrategy

_LOGGER = logging.getLogger(__name__)

PHASE_P0 = "P0 - Activation"
PHASE_P1 = "P1 - Ramp Up"
PHASE_P2 = "P2 - Maintenance"
PHASE_P3 = "P3 - Dry Back"
PHASE_DISABLED = "Disabled (No Sensor)"
PHASE_IDLE = "Idle (no plants)"

# Maps phase display strings to the canonical p1/p2/p3 values stored on
# IrrigationConfig and read by the frontend. Phases without an entry (e.g.
# "Disabled (No Sensor)") leave active_steering_phase unchanged. The bare "P3"
# entry covers the machine's initial safe state.
# Reasons a WINDOW tick decided against firing a shot, carried on the verdict as
# ``suppressed_by`` and surfaced in the shot-composition payload so a growspace
# that isn't watering is explainable without enabling debug logging (ADR-0031).
# Evaluated in this order, so the first that applies is the one reported: the
# configured cooldown, then the [[Infiltration Gate]], then the missing pump,
# then a zero-size Volume Mode shot.
SUPPRESSED_BY_COOLDOWN = "cooldown"
SUPPRESSED_BY_INFILTRATING = "infiltrating"
SUPPRESSED_BY_NO_PUMP = "no_pump"
SUPPRESSED_BY_ZERO_VOLUME = "zero_volume"

# The Infiltration Gate's stall backstop: a shot fires despite an INFILTRATING
# reading once this many configured (factor-scaled) intervals have passed since
# the last confirmed one, so a persistently-rising signal — a leaking valve, a
# drifting probe — cannot withhold irrigation all day (ADR-0031).
INFILTRATION_BACKSTOP_INTERVALS = 3

# Logbook texts for the [[Infiltration Gate]] edges (ADR-0031 decision 6). The
# held side may name the cause — only a still-climbing reading holds — but the
# release side deliberately may not: a hold ends when infiltration settles, when
# the stall backstop gives up, or when the shot window closes, so the wording
# claims only that shots are no longer withheld.
INFILTRATION_HELD_MESSAGE = (
    "Irrigation held: substrate still infiltrating the last shot"
)
INFILTRATION_RELEASED_MESSAGE = "Irrigation hold released: shots are no longer withheld"

CANONICAL_PHASE: dict[str, str] = {
    PHASE_P0: "p1",
    PHASE_P1: "p1",
    PHASE_P2: "p2",
    PHASE_P3: "p3",
    "P3": "p3",
}


@dataclass(frozen=True, slots=True)
class SteeringPhaseBoundaries:
    """Datetimes anchored on a reference date marking crop-steering phase transitions."""

    lights_on: datetime
    p0_end: datetime
    p2_stop: datetime
    lights_off: datetime


@dataclass(frozen=True, slots=True)
class ShotRequest:
    """A steering shot the tick decided may fire: which parameter pair and the BASE seconds.

    The base is pre-composition — the [[ShotComposer]] still applies the VWC and
    EC factors and the safety caps downstream.
    """

    phase: str
    base_seconds: int


@dataclass(frozen=True, slots=True)
class SteeringTickInputs:
    """Plain-value inputs for one steering tick. No hass, no live objects.

    ``infiltration`` is the [[Infiltration]] state measured by the
    ``InfiltrationMonitor``, threaded in as a plain value; the machine takes no
    dependency on the monitor itself.

    ``interval_factor`` is the [[Interval Feedback Scale Factor]] read from the
    composer *before* the tick; when the tick itself triggers the P1→P2 composer
    reset, the machine uses 1.0 (the post-reset value) for the cooldown check,
    matching the pre-extraction ordering where the reset ran before the check.
    """

    now: datetime
    vwc: float
    strategy: IrrigationStrategy
    auto_advance_p2_to_p3: bool
    soil_trigger_percent: float | None
    pump_flow_rate_ml_per_sec: float
    pump_configured: bool
    day_hours: int
    live_plant_count: int
    last_shot: datetime | None
    interval_factor: float
    infiltration: InfiltrationState


@dataclass(frozen=True, slots=True)
class SteeringTickVerdict:
    """The value one steering tick returns; records the decision, performs no effects.

    ``transition_message`` and ``volume_change_note`` are pure-formatted logbook
    texts (the [[Cycle Verdict]] message precedent) so the wording is
    unit-tested; the shell decides whether ``log_to_logbook`` lets them fire.

    ``suppressed_by`` names why a shot the WINDOW phases would otherwise have
    fired did not (one of the ``SUPPRESSED_BY_*`` reasons); it is None whenever
    a shot fires and on ticks that never reach the shot decision at all. It is
    a diagnostic only — nothing branches on it.

    ``infiltration_note`` carries the [[Infiltration Gate]] logbook text on the
    tick the gate starts or stops holding, and None on every tick in between —
    the machine owns the latch, so a hold sustained across many ticks yields one
    entry, not one per tick (ADR-0031).
    """

    phase: str
    canonical: str | None
    phase_changed: bool
    transition_message: str | None
    reset_composer: bool
    fire: ShotRequest | None
    volume_change_note: str | None
    suppressed_by: str | None = None
    infiltration_note: str | None = None


def resolve_day_hours(environment_config: Any) -> int:
    """Resolve the growspace's lit-period length in hours for boundary math.

    Prefers flower hours, as crop steering is typically flower-focused;
    defaults to 12 when the growspace has no day-length config.
    """
    if not environment_config:
        return 12
    return getattr(
        environment_config,
        "flower_day_hours",
        getattr(environment_config, "veg_day_hours", 12),
    )


def phase_boundary_times(
    strategy: IrrigationStrategy,
    day_hours: int,
    reference_date: date,
    tz: tzinfo | None,
) -> SteeringPhaseBoundaries:
    """Return the crop-steering phase boundary datetimes anchored on reference_date."""
    lights_on_source = strategy.detected_lights_on_time or strategy.lights_on_time
    try:
        lights_on = datetime.strptime(lights_on_source, "%H:%M:%S").time()
    except ValueError:
        lights_on = datetime.strptime(lights_on_source, "%H:%M").time()

    lights_on_dt = datetime.combine(reference_date, lights_on, tzinfo=tz)
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


def determine_time_period(
    boundaries: SteeringPhaseBoundaries,
    auto_advance_p2_to_p3: bool,
    now_dt: datetime,
) -> str:
    """Determine the current steering time period: "P3", "P0" or "WINDOW"."""
    if now_dt < boundaries.lights_on:
        # Before lights on -> P3 (Dry Back) from yesterday
        return "P3"

    if now_dt < boundaries.p0_end:
        return "P0"

    if now_dt < boundaries.p2_stop:
        return "WINDOW"

    if now_dt < boundaries.lights_off:
        # Only enter early P3 when the flag is explicitly enabled.
        if auto_advance_p2_to_p3:
            return "P3"
        return "WINDOW"

    return "P3"


def infiltration_gate_note(was_held: bool, now_held: bool) -> str | None:
    """Return the logbook text for an [[Infiltration Gate]] edge, or None.

    The pure half of the latch: a text only on the transitions, so the caller
    can call it on every observed tick and get one entry per hold rather than
    one per minute.
    """
    if now_held == was_held:
        return None
    return INFILTRATION_HELD_MESSAGE if now_held else INFILTRATION_RELEASED_MESSAGE


def shot_params_for_phase(strategy: IrrigationStrategy, phase: str) -> tuple[int, int]:
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


def volume_mode_active(
    strategy: IrrigationStrategy, pump_flow_rate_ml_per_sec: float
) -> bool:
    """Return True when Volume Mode is selected AND its prerequisites hold.

    Volume Mode never auto-activates on prerequisites alone — the mode must
    be explicitly selected. If it is selected but prerequisites have lapsed,
    this returns False (fail safe): the growspace is treated as not-capable
    and no Volume Mode shots fire (callers suspend rather than guess seconds).
    """
    return (
        strategy.shot_sizing_mode == ShotSizingMode.VOLUME
        and strategy.substrate_profile.is_configured
        and pump_flow_rate_ml_per_sec > 0.0
    )


class SteeringPhaseMachine:
    """Stateful controller for the crop-steering phase and shot decision."""

    def __init__(self, name: str = "") -> None:
        """Initialize in the safe P3 state. ``name`` is log context only."""
        self._name = name
        self._phase = "P3"  # Start in safe state
        self._target_reached_today = False
        self._last_reset_date: str | None = None
        # Last computed Volume Mode shot volume (ml) and the live plant count it
        # was derived from, so a count-driven volume change can be detected
        # across ticks and surfaced as a verdict note (ADR-0011).
        self._last_shot_volume_ml: float | None = None
        self._last_live_plant_count: int | None = None
        # [[Infiltration Gate]] latch: True while the gate is withholding shots,
        # so the logbook texts fire on the edges only (ADR-0031). Deliberately
        # absent from reset(): infiltration is a physical process spanning
        # minutes, not daily state (ADR-0031 decision 2), and clearing the latch
        # at midnight would swallow the release entry for a live hold.
        self._infiltration_held = False

    @property
    def current_phase(self) -> str:
        """Return the current phase display string."""
        return self._phase

    @property
    def canonical_phase(self) -> str | None:
        """Return the canonical p1/p2/p3 value for the current phase, if any."""
        return CANONICAL_PHASE.get(self._phase)

    def reset(self) -> None:
        """Reset the daily steering state (called at local midnight)."""
        self._target_reached_today = False
        self._last_reset_date = None
        self._last_shot_volume_ml = None
        self._last_live_plant_count = None

    def mark_no_sensor(self) -> SteeringTickVerdict:
        """Transition to the disabled state when no VWC sensor is configured."""
        return self._finish(PHASE_DISABLED, gate_held=False)

    def mark_sensor_unavailable(self) -> SteeringTickVerdict:
        """Release the [[Infiltration Gate]] hold on a VWC sensor dropout.

        Deliberately keeps the current phase: unlike a *missing* sensor, a
        momentarily unavailable one is not a configuration state and never
        disabled steering. It still ends any hold — the measurement it rested on
        is gone, and the gate fails open on ``UNKNOWN`` — so the logbook may not
        leave the growspace reading as held across the dropout (ADR-0031).
        """
        return self._finish(self._phase, gate_held=False)

    def tick(self, inputs: SteeringTickInputs) -> SteeringTickVerdict:
        """Advance the machine one tick and return the full decision."""
        boundaries = phase_boundary_times(
            inputs.strategy, inputs.day_hours, inputs.now.date(), inputs.now.tzinfo
        )
        period = determine_time_period(
            boundaries, inputs.auto_advance_p2_to_p3, inputs.now
        )

        # Reset daily target flag at lights-on, regardless of whether P0 is observed.
        # Using a date guard prevents the flag from getting stuck if P0 is shorter than
        # the update interval or if the loop misses the P0 window entirely.
        today_str = inputs.now.date().isoformat()
        if today_str != self._last_reset_date and period in ("P0", "WINDOW"):
            self._target_reached_today = False
            self._last_reset_date = today_str

        # Zero-plant suspend (ADR-0011): in active Volume Mode a growspace with no
        # live plants has no irrigation demand. Keep the loop alive but report an
        # idle phase and fire no shots — never a 0 ml no-op or a seconds fallback.
        if (
            period in ("P0", "WINDOW")
            and volume_mode_active(inputs.strategy, inputs.pump_flow_rate_ml_per_sec)
            and inputs.live_plant_count == 0
        ):
            return self._finish(PHASE_IDLE, gate_held=False)

        if period == "P3":
            return self._finish(PHASE_P3, gate_held=False)

        if period == "P0":
            return self._finish(PHASE_P0, gate_held=False)

        # P1 / P2 WINDOW
        target = inputs.strategy.target_vwc_percent

        fire: ShotRequest | None = None
        note: str | None = None
        suppressed: str | None = None
        # None until the shot decision actually consults the [[Infiltration
        # Gate]]. A tick that skips the decision because demand vanished (VWC at
        # or above the P1 target / the P2 trigger) leaves the latch untouched: a
        # satisfied growspace is not the gate releasing, and treating it as one
        # would split a single hold into several logbook pairs.
        gate_held: bool | None = None

        if not self._target_reached_today:
            # We are in P1: Ramp Up
            if inputs.vwc >= target:
                _LOGGER.info(
                    "Growspace %s reached target VWC %.1f%%. Switching to P2",
                    self._name,
                    target,
                )
                self._target_reached_today = True
                # No watering this tick, just switch state
                return self._finish(PHASE_P1)
            fire, note, suppressed = self._evaluate_shot(
                inputs, "P1", reset_pending=False
            )
            return self._finish(
                PHASE_P1,
                fire=fire,
                volume_change_note=note,
                suppressed_by=suppressed,
                gate_held=suppressed == SUPPRESSED_BY_INFILTRATING,
            )

        # We are in P2: Maintenance
        # Dynamic trigger: soil_trigger_percent overrides the calculated threshold
        # when set, enabling VWC-sensor-driven phase transitions.
        if inputs.soil_trigger_percent is not None:
            trigger = inputs.soil_trigger_percent
        else:
            trigger = target - inputs.strategy.maintenance_dryback_percent

        if inputs.vwc < trigger:
            _LOGGER.info(
                "Growspace %s VWC (%.1f%%) dropped below maintenance trigger (%.1f%%). Pulse watering",
                self._name,
                inputs.vwc,
                trigger,
            )
            # When this very tick performs the P1→P2 transition the composer is
            # reset before the shot composes, so the cooldown must use the
            # post-reset interval factor (1.0), not the stale pre-tick value.
            fire, note, suppressed = self._evaluate_shot(
                inputs, "P2", reset_pending=self._phase == PHASE_P1
            )
            gate_held = suppressed == SUPPRESSED_BY_INFILTRATING
        return self._finish(
            PHASE_P2,
            fire=fire,
            volume_change_note=note,
            suppressed_by=suppressed,
            gate_held=gate_held,
        )

    def projected_shot_window(
        self,
        strategy: IrrigationStrategy,
        day_hours: int,
        last_shot: datetime | None,
        interval_factor: float,
        now_dt: datetime,
    ) -> dict[str, str] | None:
        """Return the {start, end} ISO range for the next projected crop-steering shot.

        Bounded by operational guardrails (shot cooldown, phase-window timing) rather
        than a statistical confidence interval, so it's meaningful from day one without
        any VWC sensor history. See ADR-0011 (lovelace-growspace-manager-card) for the
        reasoning behind a guardrail-bound range over a depletion-rate model.
        """
        if not strategy or not strategy.enabled:
            return None

        # Cooldown anchors on the active phase's interval: P2 maintenance uses
        # the P2 pair, everything else the P1 pair.
        active_phase = "P2" if self._phase == PHASE_P2 else "P1"
        _, interval_minutes = shot_params_for_phase(strategy, active_phase)
        if not strategy.lights_on_time or interval_minutes is None:
            return None

        today = now_dt.date()
        boundaries = phase_boundary_times(strategy, day_hours, today, now_dt.tzinfo)

        # Match on the display string directly — the canonical p1/p2/p3 mapping
        # collapses P0 into "p1" for the frontend's active_steering_phase, but P0
        # has its own time-bound window distinct from P1's threshold-driven one.
        if self._phase == PHASE_P0:
            latest = boundaries.p0_end
        elif self._phase in (PHASE_P1, PHASE_P2):
            latest = boundaries.p2_stop
        else:
            # P3 (or unknown/disabled) — no shots fire today; roll forward to tomorrow
            return tomorrows_shot_window(strategy, day_hours, today, now_dt.tzinfo)

        earliest = now_dt
        if last_shot:
            effective_interval = interval_minutes * interval_factor
            cooldown_end = last_shot + timedelta(minutes=effective_interval)
            if cooldown_end > now_dt:
                earliest = cooldown_end

        if earliest >= latest:
            # Today's active window has effectively closed — roll forward to tomorrow
            return tomorrows_shot_window(strategy, day_hours, today, now_dt.tzinfo)

        return {"start": earliest.isoformat(), "end": latest.isoformat()}

    def _evaluate_shot(
        self, inputs: SteeringTickInputs, phase: str, *, reset_pending: bool
    ) -> tuple[ShotRequest | None, str | None, str | None]:
        """Decide whether a shot may fire this tick and its base duration.

        Returns ``(request, volume_change_note, suppressed_by)``; ``request`` is
        None when the cooldown blocks, the [[Infiltration Gate]] holds, no pump
        is configured, or Volume Mode suspends (zero live plants / zero volume —
        ADR-0011), and ``suppressed_by`` names which of those it was. The note
        and the reason stay separate: a volume change can be worth logging on a
        tick that fires.

        The gate sits behind the cooldown and is therefore strictly additive: it
        can only delay a shot the cooldown already permits, never release one it
        blocks. It fails open — only ``INFILTRATING`` suppresses — and gives up
        after ``INFILTRATION_BACKSTOP_INTERVALS`` intervals so a stuck signal
        cannot withhold irrigation all day (ADR-0031).
        """
        seconds_duration, interval_minutes = shot_params_for_phase(
            inputs.strategy, phase
        )

        if inputs.last_shot is not None:
            effective_factor = 1.0 if reset_pending else inputs.interval_factor
            elapsed = (inputs.now - inputs.last_shot).total_seconds() / 60.0
            if elapsed < interval_minutes * effective_factor:
                return None, None, SUPPRESSED_BY_COOLDOWN
            backstop_minutes = (
                INFILTRATION_BACKSTOP_INTERVALS * interval_minutes * effective_factor
            )
            if (
                inputs.infiltration is InfiltrationState.INFILTRATING
                and elapsed <= backstop_minutes
            ):
                return None, None, SUPPRESSED_BY_INFILTRATING

        if not inputs.pump_configured:
            return None, None, SUPPRESSED_BY_NO_PUMP

        # Derive the BASE per-shot duration. Volume Mode converts the per-phase
        # percent-of-substrate-volume size to pump seconds via the live plant
        # count and flow rate; Seconds Mode keeps the configured seconds exactly.
        # The base is computed BEFORE the VWC feedback and EC modulation factors
        # (and any downstream safety caps).
        if volume_mode_active(inputs.strategy, inputs.pump_flow_rate_ml_per_sec):
            base_seconds, note = self._volume_mode_base_duration(inputs, phase)
            if base_seconds is None:
                # Zero live plants: suspend rather than firing a floored shot.
                return None, note, SUPPRESSED_BY_ZERO_VOLUME
            return ShotRequest(phase=phase, base_seconds=base_seconds), note, None

        return ShotRequest(phase=phase, base_seconds=seconds_duration), None, None

    def _volume_mode_base_duration(
        self, inputs: SteeringTickInputs, phase: str
    ) -> tuple[int | None, str | None]:
        """Return the base pump-seconds for a Volume Mode shot, or None to suspend.

        Converts the per-phase percent-of-substrate-volume size to milliliters
        (``percent/100 × liters_per_pot × live_count × 1000``) and then to pump
        seconds via the flow rate (``ml / flow_rate_ml_per_sec``). Returns None
        when the live plant count is zero so the caller suspends the shot rather
        than firing a 1 s floor. Also formats a volume-change note when a
        live-count change alters the computed shot volume (ADR-0011).
        """
        live_count = inputs.live_plant_count
        strategy = inputs.strategy
        percent = (
            strategy.p2_shot_volume_percent
            if phase == "P2"
            else strategy.p1_shot_volume_percent
        )
        profile = strategy.substrate_profile

        shot_volume_ml = (
            (percent / 100.0) * profile.liters_per_pot * live_count * 1000.0
        )
        note = self._volume_change_note(shot_volume_ml, live_count)

        if live_count == 0 or shot_volume_ml <= 0.0:
            return None, note
        return (
            max(1, round(shot_volume_ml / inputs.pump_flow_rate_ml_per_sec)),
            note,
        )

    def _volume_change_note(self, shot_volume_ml: float, live_count: int) -> str | None:
        """Format the logbook note when a live-count change alters the shot volume.

        Only produced in active Volume Mode when the computed volume actually
        changed versus the previous tick, so Seconds Mode and unchanged ticks
        never spam the logbook (ADR-0011). The shell still gates the actual
        logbook write on ``log_to_logbook``.
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
            return None

        return (
            f"shot volume {round(prev_volume)}→{round(shot_volume_ml)} ml: "
            f"plant count {prev_count}→{live_count}"
        )

    def _finish(
        self,
        new_phase: str,
        *,
        fire: ShotRequest | None = None,
        volume_change_note: str | None = None,
        suppressed_by: str | None = None,
        gate_held: bool | None = None,
    ) -> SteeringTickVerdict:
        """Apply the phase transition and assemble the verdict.

        ``gate_held`` is this tick's [[Infiltration Gate]] observation — True
        while it withholds a shot, False on any tick that leaves the gate not
        holding (including the P3/P0/idle/disabled ticks that carry no shot
        decision at all, so a hold at window close still releases), and None
        when the tick made no observation and the latch must stand.
        """
        old_phase = self._phase
        changed = new_phase != old_phase
        transition_message: str | None = None
        if changed:
            _LOGGER.debug(
                "Growspace %s VWC Steering Phase changed: %s -> %s",
                self._name,
                old_phase,
                new_phase,
            )
            transition_message = f"VWC phase transition: {old_phase} → {new_phase}"
        self._phase = new_phase

        infiltration_note: str | None = None
        if gate_held is not None:
            infiltration_note = infiltration_gate_note(
                self._infiltration_held, gate_held
            )
            self._infiltration_held = gate_held

        return SteeringTickVerdict(
            phase=new_phase,
            canonical=CANONICAL_PHASE.get(new_phase),
            phase_changed=changed,
            transition_message=transition_message,
            reset_composer=changed and old_phase == PHASE_P1 and new_phase == PHASE_P2,
            fire=fire,
            volume_change_note=volume_change_note,
            suppressed_by=suppressed_by,
            infiltration_note=infiltration_note,
        )


def tomorrows_shot_window(
    strategy: IrrigationStrategy,
    day_hours: int,
    today: date,
    tz: tzinfo | None,
) -> dict[str, str]:
    """Return tomorrow's {start, end} projected shot window (P1 start to P2 stop)."""
    tomorrow = today + timedelta(days=1)
    boundaries = phase_boundary_times(strategy, day_hours, tomorrow, tz)
    return {
        "start": boundaries.p0_end.isoformat(),
        "end": boundaries.p2_stop.isoformat(),
    }
