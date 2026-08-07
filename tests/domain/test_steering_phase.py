"""Tests for the Steering Phase Machine seam (domain/steering_phase.py).

The machine is a stateful controller (the ShotComposer mould), so these drive
it with deterministic ``tick``/``reset`` sequences and plain-value
``SteeringTickInputs`` — no coordinator, no Home Assistant, no mocks. The
phase/boundary/cooldown/Volume Mode cases were previously only reachable
through the full VWC-coordinator fixture in
``tests/integration/test_vwc_irrigation_coordinator.py`` and
``tests/integration/test_vwc_volume_mode.py``.
"""

from datetime import UTC, datetime

import pytest

from custom_components.growspace_manager.const import ShotSizingMode
from custom_components.growspace_manager.domain.infiltration import InfiltrationState
from custom_components.growspace_manager.domain.steering_phase import (
    PHASE_DISABLED,
    PHASE_IDLE,
    PHASE_P0,
    PHASE_P1,
    PHASE_P2,
    PHASE_P3,
    SUPPRESSED_BY_COOLDOWN,
    SUPPRESSED_BY_INFILTRATING,
    SUPPRESSED_BY_NO_PUMP,
    SUPPRESSED_BY_ZERO_VOLUME,
    SteeringPhaseMachine,
    SteeringTickInputs,
    determine_time_period,
    phase_boundary_times,
    resolve_day_hours,
    shot_params_for_phase,
    tomorrows_shot_window,
    volume_mode_active,
)
from custom_components.growspace_manager.models import IrrigationStrategy
from custom_components.growspace_manager.models.irrigation import SubstrateProfile


def _strategy(**overrides) -> IrrigationStrategy:
    """Build an enabled strategy with the model defaults, overridable per case.

    Defaults give lights-on 06:00, P0 until 07:00, a 12 h day (lights-off
    18:00) and a P2 stop at 16:00.
    """
    overrides.setdefault("enabled", True)
    return IrrigationStrategy(**overrides)


def _volume_strategy(**overrides) -> IrrigationStrategy:
    """Build a strategy in active Volume Mode (profile + percent sizes)."""
    overrides.setdefault("shot_sizing_mode", ShotSizingMode.VOLUME)
    overrides.setdefault("substrate_profile", SubstrateProfile(liters_per_pot=10.0))
    return _strategy(**overrides)


def _at(hour: int, minute: int = 0, day: int = 15) -> datetime:
    """A tz-aware datetime on a fixed reference day."""
    return datetime(2023, 6, day, hour, minute, tzinfo=UTC)


def _inputs(
    now: datetime,
    vwc: float,
    strategy: IrrigationStrategy | None = None,
    **overrides,
) -> SteeringTickInputs:
    """Build tick inputs with sensible test defaults, overridable per case."""
    defaults = {
        "strategy": strategy or _strategy(),
        "auto_advance_p2_to_p3": False,
        "soil_trigger_percent": None,
        "pump_flow_rate_ml_per_sec": 20.0,
        "pump_configured": True,
        "day_hours": 12,
        "live_plant_count": 3,
        "last_shot": None,
        "interval_factor": 1.0,
        "infiltration": InfiltrationState.UNKNOWN,
    }
    defaults.update(overrides)
    return SteeringTickInputs(now=now, vwc=vwc, **defaults)


# ── boundary math ─────────────────────────────────────────────────────────────


def test_boundaries_from_hms_time() -> None:
    boundaries = phase_boundary_times(_strategy(), 12, _at(12).date(), UTC)
    assert boundaries.lights_on == _at(6)
    assert boundaries.p0_end == _at(7)
    assert boundaries.lights_off == _at(18)
    assert boundaries.p2_stop == _at(16)


def test_boundaries_parse_hm_fallback() -> None:
    boundaries = phase_boundary_times(
        _strategy(lights_on_time="08:30"), 12, _at(12).date(), UTC
    )
    assert boundaries.lights_on == _at(8, 30)


def test_boundaries_prefer_detected_lights_on() -> None:
    strategy = _strategy(detected_lights_on_time="05:00:00")
    boundaries = phase_boundary_times(strategy, 12, _at(12).date(), UTC)
    assert boundaries.lights_on == _at(5)


def test_boundaries_day_hours_shift_lights_off_and_p2_stop() -> None:
    boundaries = phase_boundary_times(_strategy(), 18, _at(12).date(), UTC)
    assert boundaries.lights_off == _at(0, 0, day=16)
    assert boundaries.p2_stop == _at(22)


def test_resolve_day_hours_defaults_to_12_without_config() -> None:
    assert resolve_day_hours(None) == 12


def test_resolve_day_hours_prefers_flower_hours() -> None:
    class _Env:
        flower_day_hours = 11
        veg_day_hours = 18

    assert resolve_day_hours(_Env()) == 11


# ── time-period determination ─────────────────────────────────────────────────


def test_period_before_lights_on_is_p3() -> None:
    boundaries = phase_boundary_times(_strategy(), 12, _at(12).date(), UTC)
    assert determine_time_period(boundaries, False, _at(5, 59)) == "P3"


def test_period_p0_window() -> None:
    boundaries = phase_boundary_times(_strategy(), 12, _at(12).date(), UTC)
    assert determine_time_period(boundaries, False, _at(6, 30)) == "P0"


def test_period_window_between_p0_end_and_p2_stop() -> None:
    boundaries = phase_boundary_times(_strategy(), 12, _at(12).date(), UTC)
    assert determine_time_period(boundaries, False, _at(12)) == "WINDOW"


def test_period_after_p2_stop_stays_window_without_auto_advance() -> None:
    boundaries = phase_boundary_times(_strategy(), 12, _at(12).date(), UTC)
    assert determine_time_period(boundaries, False, _at(17)) == "WINDOW"


def test_period_after_p2_stop_is_p3_with_auto_advance() -> None:
    boundaries = phase_boundary_times(_strategy(), 12, _at(12).date(), UTC)
    assert determine_time_period(boundaries, True, _at(17)) == "P3"


def test_period_after_lights_off_is_p3() -> None:
    boundaries = phase_boundary_times(_strategy(), 12, _at(12).date(), UTC)
    assert determine_time_period(boundaries, False, _at(18, 1)) == "P3"


def test_shot_params_pick_the_phase_pair() -> None:
    strategy = _strategy(
        p1_shot_duration_seconds=30,
        p1_shot_interval_minutes=20,
        p2_shot_duration_seconds=8,
        p2_shot_interval_minutes=45,
    )
    assert shot_params_for_phase(strategy, "P1") == (30, 20)
    assert shot_params_for_phase(strategy, "P2") == (8, 45)


# ── Volume Mode gating ────────────────────────────────────────────────────────


def test_volume_mode_inactive_in_seconds_mode() -> None:
    assert volume_mode_active(_strategy(), 20.0) is False


def test_volume_mode_inactive_without_profile() -> None:
    strategy = _strategy(shot_sizing_mode=ShotSizingMode.VOLUME)
    assert volume_mode_active(strategy, 20.0) is False


def test_volume_mode_inactive_without_flow_rate() -> None:
    assert volume_mode_active(_volume_strategy(), 0.0) is False


def test_volume_mode_active_when_selected_and_capable() -> None:
    assert volume_mode_active(_volume_strategy(), 20.0) is True


# ── phase machine: transitions ────────────────────────────────────────────────


def test_machine_starts_in_safe_p3() -> None:
    machine = SteeringPhaseMachine("gs1")
    assert machine.current_phase == "P3"
    assert machine.canonical_phase == "p3"


def test_tick_p0_window_activates_p0() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(6, 30), vwc=40.0))
    assert verdict.phase == PHASE_P0
    assert verdict.canonical == "p1"
    assert verdict.phase_changed is True
    assert verdict.transition_message == f"VWC phase transition: P3 → {PHASE_P0}"
    assert verdict.fire is None


def test_tick_before_lights_on_is_dry_back() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(3), vwc=40.0))
    assert verdict.phase == PHASE_P3
    assert verdict.canonical == "p3"


def test_unchanged_phase_produces_no_transition() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(6, 30), vwc=40.0))
    verdict = machine.tick(_inputs(_at(6, 31), vwc=40.0))
    assert verdict.phase_changed is False
    assert verdict.transition_message is None


def test_p1_ramp_fires_shot_below_target() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=40.0))
    assert verdict.phase == PHASE_P1
    assert verdict.fire is not None
    assert verdict.fire.phase == "P1"
    assert verdict.fire.base_seconds == _strategy().p1_shot_duration_seconds


def test_p1_reaching_target_switches_state_without_firing() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=56.0))  # target 55.0
    assert verdict.phase == PHASE_P1
    assert verdict.fire is None
    follow_up = machine.tick(_inputs(_at(9, 1), vwc=56.0))
    assert follow_up.phase == PHASE_P2


def test_p1_to_p2_transition_requests_composer_reset() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))
    verdict = machine.tick(_inputs(_at(9, 1), vwc=56.0))
    assert verdict.reset_composer is True
    later = machine.tick(_inputs(_at(9, 2), vwc=56.0))
    assert later.reset_composer is False


def test_p2_fires_below_maintenance_trigger() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))
    # target 55 − dryback 2 = trigger 53
    verdict = machine.tick(_inputs(_at(9, 1), vwc=52.5))
    assert verdict.phase == PHASE_P2
    assert verdict.fire is not None
    assert verdict.fire.phase == "P2"


def test_p2_holds_above_maintenance_trigger() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))
    verdict = machine.tick(_inputs(_at(9, 1), vwc=54.0))
    assert verdict.fire is None


def test_p2_soil_trigger_percent_overrides_calculated_trigger() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))
    # 54.0 is above the calculated trigger (53) but below the explicit 54.5
    verdict = machine.tick(_inputs(_at(9, 1), vwc=54.0, soil_trigger_percent=54.5))
    assert verdict.fire is not None


# ── daily reset guard ─────────────────────────────────────────────────────────


def test_target_flag_resets_on_new_day() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9, 0, day=15), vwc=56.0))
    assert machine.tick(_inputs(_at(9, 1, day=15), vwc=50.0)).phase == PHASE_P2
    # Next day, first WINDOW tick: the date guard resets the flag → back to P1
    verdict = machine.tick(_inputs(_at(9, 0, day=16), vwc=50.0))
    assert verdict.phase == PHASE_P1


def test_reset_clears_daily_state() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))
    machine.reset()
    verdict = machine.tick(_inputs(_at(9, 1), vwc=50.0))
    assert verdict.phase == PHASE_P1


# ── cooldown ──────────────────────────────────────────────────────────────────


def test_cooldown_blocks_shot_within_interval() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=40.0, last_shot=_at(8, 50)))
    assert verdict.phase == PHASE_P1
    assert verdict.fire is None  # 10 min elapsed < 15 min interval


def test_cooldown_allows_shot_after_interval() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=40.0, last_shot=_at(8, 44)))
    assert verdict.fire is not None  # 16 min elapsed >= 15 min interval


def test_interval_factor_lengthens_cooldown() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(_at(9), vwc=40.0, last_shot=_at(8, 44), interval_factor=1.5)
    )
    assert verdict.fire is None  # 16 min < 15 × 1.5 = 22.5 min


def test_p1_to_p2_transition_tick_uses_post_reset_interval_factor() -> None:
    """The tick that performs P1→P2 resets the composer before the shot
    composes, so its cooldown must use factor 1.0, not the stale value."""
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))
    # 16 min elapsed: allowed at factor 1.0, blocked at the stale 1.5
    verdict = machine.tick(
        _inputs(_at(9, 16), vwc=50.0, last_shot=_at(9), interval_factor=1.5)
    )
    assert verdict.reset_composer is True
    assert verdict.fire is not None
    # Next P2 tick the (fresh) factor applies normally again
    blocked = machine.tick(
        _inputs(_at(9, 32), vwc=50.0, last_shot=_at(9, 16), interval_factor=1.5)
    )
    assert blocked.fire is None


def test_no_pump_means_no_fire() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=40.0, pump_configured=False))
    assert verdict.phase == PHASE_P1
    assert verdict.fire is None


# ── Volume Mode sizing + zero-plant suspend (ADR-0011) ────────────────────────


def test_volume_mode_base_seconds_from_percent() -> None:
    machine = SteeringPhaseMachine("gs1")
    # 4% of (10 L/pot × 3 plants) = 1200 ml; at 20 ml/s → 60 s
    verdict = machine.tick(_inputs(_at(9), vwc=40.0, strategy=_volume_strategy()))
    assert verdict.fire is not None
    assert verdict.fire.base_seconds == 60


def test_volume_mode_zero_plants_suspends_to_idle() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(_at(9), vwc=40.0, strategy=_volume_strategy(), live_plant_count=0)
    )
    assert verdict.phase == PHASE_IDLE
    assert verdict.canonical is None
    assert verdict.fire is None


def test_seconds_mode_zero_plants_still_fires() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=40.0, live_plant_count=0))
    assert verdict.phase == PHASE_P1
    assert verdict.fire is not None


def test_volume_mode_zero_volume_suspends_shot() -> None:
    machine = SteeringPhaseMachine("gs1")
    strategy = _volume_strategy(p1_shot_volume_percent=0.0)
    verdict = machine.tick(_inputs(_at(9), vwc=40.0, strategy=strategy))
    assert verdict.phase == PHASE_P1
    assert verdict.fire is None


def test_volume_change_note_on_plant_count_change() -> None:
    machine = SteeringPhaseMachine("gs1")
    strategy = _volume_strategy()
    first = machine.tick(_inputs(_at(9), vwc=40.0, strategy=strategy))
    assert first.volume_change_note is None  # no previous tick to compare
    second = machine.tick(
        _inputs(_at(9, 20), vwc=40.0, strategy=strategy, live_plant_count=2)
    )
    assert second.volume_change_note == "shot volume 1200→800 ml: plant count 3→2"


def test_no_volume_change_note_when_count_unchanged() -> None:
    machine = SteeringPhaseMachine("gs1")
    strategy = _volume_strategy()
    machine.tick(_inputs(_at(9), vwc=40.0, strategy=strategy))
    second = machine.tick(_inputs(_at(9, 20), vwc=40.0, strategy=strategy))
    assert second.volume_change_note is None


# ── suppression reasons (ADR-0031) ────────────────────────────────────────────


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        pytest.param({"last_shot": _at(8, 50)}, SUPPRESSED_BY_COOLDOWN, id="cooldown"),
        pytest.param({"pump_configured": False}, SUPPRESSED_BY_NO_PUMP, id="no_pump"),
        pytest.param(
            {"strategy": _volume_strategy(p1_shot_volume_percent=0.0)},
            SUPPRESSED_BY_ZERO_VOLUME,
            id="zero_volume",
        ),
    ],
)
def test_suppressed_shot_names_its_reason(overrides: dict, expected: str) -> None:
    """Each existing block cause reports its own distinct reason."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=40.0, **overrides))
    assert verdict.fire is None
    assert verdict.suppressed_by == expected


def test_fired_shot_carries_no_suppression_reason() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=40.0))
    assert verdict.fire is not None
    assert verdict.suppressed_by is None


def test_cooldown_takes_precedence_over_missing_pump() -> None:
    """The cooldown is checked first, so a cooling-down pumpless tick says cooldown."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(_at(9), vwc=40.0, last_shot=_at(8, 50), pump_configured=False)
    )
    assert verdict.suppressed_by == SUPPRESSED_BY_COOLDOWN


def test_p2_above_trigger_is_not_a_suppressed_shot() -> None:
    """A phase that never evaluates a shot reports no reason, not a stale one."""
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=40.0, pump_configured=False))
    machine.tick(_inputs(_at(9, 20), vwc=56.0))  # reaches target, enters P2
    verdict = machine.tick(_inputs(_at(9, 40), vwc=54.0))  # above the P2 trigger
    assert verdict.phase == PHASE_P2
    assert verdict.fire is None
    assert verdict.suppressed_by is None


def test_reaching_target_is_not_a_suppressed_shot() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(_inputs(_at(9), vwc=56.0))
    assert verdict.phase == PHASE_P1
    assert verdict.suppressed_by is None


def test_non_window_phases_carry_no_suppression_reason() -> None:
    machine = SteeringPhaseMachine("gs1")
    assert machine.tick(_inputs(_at(5), vwc=40.0)).suppressed_by is None  # P3
    assert machine.tick(_inputs(_at(6, 30), vwc=40.0)).suppressed_by is None  # P0
    idle = machine.tick(
        _inputs(_at(9), vwc=40.0, strategy=_volume_strategy(), live_plant_count=0)
    )
    assert idle.phase == PHASE_IDLE
    assert idle.suppressed_by is None
    assert machine.mark_no_sensor().suppressed_by is None


# ── the Infiltration Gate (ADR-0031) ──────────────────────────────────────────


def test_p1_shot_is_withheld_while_the_substrate_is_infiltrating() -> None:
    """P1 ramp-up is open-loop, so a still-climbing VWC must not trigger another shot."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(
            _at(9),
            vwc=40.0,
            last_shot=_at(8, 30),  # 30 min: past the 15 min cooldown
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert verdict.fire is None
    assert verdict.suppressed_by == SUPPRESSED_BY_INFILTRATING


def test_p2_shot_is_withheld_while_the_substrate_is_infiltrating() -> None:
    """The gate is a floor under both phase rules, not only P1's."""
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))  # reaches target, enters P2
    verdict = machine.tick(
        _inputs(
            _at(10),
            vwc=50.0,  # below the P2 trigger of 53%
            last_shot=_at(9, 30),
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert verdict.phase == PHASE_P2
    assert verdict.fire is None
    assert verdict.suppressed_by == SUPPRESSED_BY_INFILTRATING


@pytest.mark.parametrize(
    "state",
    [
        pytest.param(InfiltrationState.SETTLED, id="settled"),
        pytest.param(InfiltrationState.DRYING, id="drying"),
        pytest.param(InfiltrationState.UNKNOWN, id="unknown"),
    ],
)
def test_only_an_infiltrating_reading_withholds_a_shot(
    state: InfiltrationState,
) -> None:
    """UNKNOWN in particular must fail open: a dropout may not suspend irrigation."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(_at(9), vwc=40.0, last_shot=_at(8, 30), infiltration=state)
    )
    assert verdict.fire is not None
    assert verdict.suppressed_by is None


def test_the_gate_cannot_release_a_shot_the_cooldown_blocks() -> None:
    """Strictly additive: the cooldown is evaluated first and still wins."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(
            _at(9),
            vwc=40.0,
            last_shot=_at(8, 50),  # 10 min into the 15 min cooldown
            infiltration=InfiltrationState.SETTLED,
        )
    )
    assert verdict.fire is None
    assert verdict.suppressed_by == SUPPRESSED_BY_COOLDOWN


def test_a_cooling_down_infiltrating_tick_reports_the_cooldown() -> None:
    """The cooldown is the binding constraint, so it is the reason reported."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(
            _at(9),
            vwc=40.0,
            last_shot=_at(8, 50),
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert verdict.suppressed_by == SUPPRESSED_BY_COOLDOWN


def test_a_never_watered_growspace_is_not_gated() -> None:
    """Without a confirmed last shot the backstop has no anchor, so the gate opens."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(
            _at(9),
            vwc=40.0,
            last_shot=None,
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert verdict.fire is not None
    assert verdict.suppressed_by is None


@pytest.mark.parametrize(
    ("last_shot", "fires"),
    [
        pytest.param(_at(8, 15), False, id="at_the_backstop"),
        pytest.param(_at(8, 14), True, id="past_the_backstop"),
    ],
)
def test_the_backstop_releases_a_stuck_gate(last_shot: datetime, fires: bool) -> None:
    """A persistently-rising signal may not block P1 all day: 3 x 15 min = 45 min."""
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.tick(
        _inputs(
            _at(9),
            vwc=40.0,
            last_shot=last_shot,
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert (verdict.fire is not None) is fires


def test_the_backstop_scales_with_the_interval_feedback_factor() -> None:
    """A lengthened cooldown lengthens the backstop proportionally: 3 x 15 x 2 = 90."""
    machine = SteeringPhaseMachine("gs1")
    still_gated = machine.tick(
        _inputs(
            _at(9),
            vwc=40.0,
            last_shot=_at(7, 45),  # 75 min: past the doubled backstop of a factor of 1
            interval_factor=2.0,
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert still_gated.suppressed_by == SUPPRESSED_BY_INFILTRATING
    released = machine.tick(
        _inputs(
            _at(9),
            vwc=40.0,
            last_shot=_at(7, 29),  # 91 min
            interval_factor=2.0,
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert released.fire is not None


def test_the_p1_to_p2_transition_tick_backstops_on_the_post_reset_factor() -> None:
    """The tick that resets the composer uses 1.0, so its backstop is the unscaled one."""
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=56.0))  # reaches target; machine is still in P1
    verdict = machine.tick(
        _inputs(
            _at(10),
            vwc=50.0,
            last_shot=_at(9, 5),  # 55 min: past 3 x 15 x 1.0, inside 3 x 15 x 2.0
            interval_factor=2.0,
            infiltration=InfiltrationState.INFILTRATING,
        )
    )
    assert verdict.fire is not None


def test_volume_change_note_is_not_conflated_with_the_reason() -> None:
    """A firing tick can still carry a volume-change note; the two are separate."""
    machine = SteeringPhaseMachine("gs1")
    strategy = _volume_strategy()
    machine.tick(_inputs(_at(9), vwc=40.0, strategy=strategy))
    verdict = machine.tick(
        _inputs(_at(9, 20), vwc=40.0, strategy=strategy, live_plant_count=2)
    )
    assert verdict.fire is not None
    assert verdict.volume_change_note == "shot volume 1200→800 ml: plant count 3→2"
    assert verdict.suppressed_by is None


def test_zero_volume_suppression_keeps_its_volume_change_note() -> None:
    """A count change down to a zero-size shot reports both the note and the reason."""
    machine = SteeringPhaseMachine("gs1")
    strategy = _volume_strategy()
    machine.tick(_inputs(_at(9), vwc=40.0, strategy=strategy))
    strategy.p1_shot_volume_percent = 0.0
    verdict = machine.tick(
        _inputs(_at(9, 20), vwc=40.0, strategy=strategy, live_plant_count=2)
    )
    assert verdict.fire is None
    assert verdict.suppressed_by == SUPPRESSED_BY_ZERO_VOLUME
    assert verdict.volume_change_note == "shot volume 1200→0 ml: plant count 3→2"


# ── disabled / idle states ────────────────────────────────────────────────────


def test_mark_no_sensor_disables_with_no_canonical_phase() -> None:
    machine = SteeringPhaseMachine("gs1")
    verdict = machine.mark_no_sensor()
    assert verdict.phase == PHASE_DISABLED
    assert verdict.canonical is None
    assert verdict.phase_changed is True
    repeat = machine.mark_no_sensor()
    assert repeat.phase_changed is False


# ── projected shot window ─────────────────────────────────────────────────────


def test_projection_none_when_strategy_disabled() -> None:
    machine = SteeringPhaseMachine("gs1")
    strategy = IrrigationStrategy(enabled=False)
    assert machine.projected_shot_window(strategy, 12, None, 1.0, _at(9)) is None


def test_projection_rolls_to_tomorrow_from_p3() -> None:
    machine = SteeringPhaseMachine("gs1")  # starts in P3
    window = machine.projected_shot_window(_strategy(), 12, None, 1.0, _at(20))
    assert window == {
        "start": _at(7, 0, day=16).isoformat(),
        "end": _at(16, 0, day=16).isoformat(),
    }


def test_projection_in_p1_spans_now_to_p2_stop() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=40.0))
    window = machine.projected_shot_window(_strategy(), 12, None, 1.0, _at(9, 5))
    assert window == {
        "start": _at(9, 5).isoformat(),
        "end": _at(16).isoformat(),
    }


def test_projection_in_p0_ends_at_p0_end() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(6, 30), vwc=40.0))
    window = machine.projected_shot_window(_strategy(), 12, None, 1.0, _at(6, 35))
    assert window is not None
    assert window["end"] == _at(7).isoformat()


def test_projection_cooldown_pushes_start() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=40.0))
    window = machine.projected_shot_window(_strategy(), 12, _at(9), 1.0, _at(9, 5))
    assert window is not None
    assert window["start"] == _at(9, 15).isoformat()  # 15 min interval cooldown


def test_projection_closed_window_rolls_to_tomorrow() -> None:
    machine = SteeringPhaseMachine("gs1")
    machine.tick(_inputs(_at(9), vwc=40.0))
    # Cooldown would end after today's p2_stop → tomorrow's window
    window = machine.projected_shot_window(
        _strategy(p2_shot_interval_minutes=15, p1_shot_interval_minutes=15),
        12,
        _at(15, 55),
        1.0,
        _at(15, 56),
    )
    assert window == tomorrows_shot_window(_strategy(), 12, _at(15, 56).date(), UTC)


def test_tomorrows_window_spans_p0_end_to_p2_stop() -> None:
    window = tomorrows_shot_window(_strategy(), 12, _at(12).date(), UTC)
    assert window == {
        "start": _at(7, 0, day=16).isoformat(),
        "end": _at(16, 0, day=16).isoformat(),
    }
