# ADR 0023 — `SteeringPhaseMachine` Owns the Crop-Steering Tick Decision

**Status:** Accepted

## Context

After ADR-0021 (ShotComposer) and ADR-0021/pump-cycle (Pump Cycle Gate), the
`VWCIrrigationCoordinator` still trapped the last large block of pure steering
logic inside its impure shell: the phase state machine. Phase boundary math
(`_phase_boundary_times`), time-period determination (`_determine_time_period`),
the daily target-reset date guard, the P1-ramp/P2-maintenance split with the
`soil_trigger_percent` override, the shot cooldown (interval × feedback factor),
the ADR-0011 Volume Mode sizing + zero-plant suspend, and the frontend's
`projected_shot_window` projection were interleaved with sensor reads,
SubstrateTracker feeding, and the pump effect across `_execute_phase_logic`,
`_handle_watering`, and `_set_phase`.

The cost was the usual pair: **no locality** (phase rules spread across five
methods plus three retained state fields) and **no test surface** — the
integration suite drove every phase edge case through a 136-mock coordinator
fixture (`tests/integration/test_vwc_irrigation_coordinator.py`, 1,744 lines),
versus the zero-mock `tests/domain/test_shot_composer.py`.

## Decisions

### 1. A stateful machine, not a pure resolver

The phase, the daily `target_reached` flag, its reset-date guard, and the
Volume Mode change-tracking pair persist across minute-loop ticks and have their
own reset rules (midnight `reset()`, date-guarded daily target reset, P1→P2
detection). Following the ADR-0021 reasoning verbatim, `SteeringPhaseMachine`
(`domain/steering_phase.py`) retains that state; a pure
`resolve(prev_state, inputs)` shape would leave the state record and reset
lifecycle in the coordinator, defeating the locality win.

### 2. The verdict covers the full tick, not just the phase

`tick(SteeringTickInputs) → SteeringTickVerdict` returns everything the shell
needs: the phase (display + canonical p1/p2/p3), `phase_changed`, a
pure-formatted `transition_message`, `reset_composer` (P1→P2), `fire`
(a `ShotRequest` with the phase pair and pre-composition **base** seconds), and
a pure-formatted `volume_change_note` (ADR-0011). The alternative — a
phase-only verdict with cooldown/sizing left in `_handle_watering` — would have
kept the hardest-to-test logic (cooldown × interval factor, Volume Mode
percent→ml→seconds, zero-plant suspend) behind the 136-mock fixture. This is the
[[Cycle Verdict]] shape: the verdict records the decision and performs no
effects; message wording is unit-tested behind the seam.

### 3. The machine owns every phase value; the shell owns every effect

All phase displays — including the non-canonical `"Disabled (No Sensor)"`
(via `mark_no_sensor()`) and `"Idle (no plants)"` — are produced by the machine,
so phase state has exactly one home. The coordinator keeps: sensor reads, the
runoff-EC halt, SubstrateTracker feeding, `composer.compose()` + the pump
background task, logbook events (gated on `log_to_logbook` in the shell),
`active_steering_phase`/`phase_changed_at` writes, and coordinator data pushes.
Inputs are plain values only (strategy, config fields, resolved day-hours, live
plant count, last confirmed shot time, composer interval factor).

### 4. The projection lives behind the same seam

`projected_shot_window` moved onto the machine (with `phase_boundary_times` /
`tomorrows_shot_window` as module functions), so the frontend's next-shot window
and the actual firing logic read the same boundaries and phase and can never
disagree. The coordinator property is a one-line adapter.

### 5. The transition tick uses the post-reset interval factor

One deliberate subtlety preserved from the old ordering: when a single tick
performs the P1→P2 transition, the composer reset used to run (inside
`_set_phase`) *before* the cooldown check read `interval_factor`. Since the
machine now receives the factor as a pre-tick input, it substitutes 1.0 for the
cooldown check on exactly that tick (`reset_pending`), matching the old
behaviour.

### 6. Rider: the EC modulation magnitude helper joined `ec_state.py`

`_ec_modulation_factor_for_reading` (a pure static) moved to
`domain/ec_state.py` as `ec_modulation_factor_for_reading`, completing
ADR-0015's "one place EC is reasoned about" — direction (`ECRecommendation`)
and magnitude now live in the same module.

### 7. Behaviour is unchanged

Structural move only. Phase windows, the auto-advance flags, trigger math,
cooldowns, ADR-0011 sizing/suspend/logbook wording, ADR-0014 factor handling,
and the projection semantics are identical; migrated tests assert the same
numbers.

## Consequences

- Phase, cooldown, sizing, and projection edge cases are unit-tested in
  `tests/domain/test_steering_phase.py` (48 cases, zero mocks); the integration
  suite keeps wiring tests (verdict → effects mapping, real plant lists flowing
  into inputs).
- `vwc_irrigation_coordinator.py` shrank from 898 to ~540 lines and holds no
  steering decision logic — it is now purely the effects shell its name
  suggests.
- The `domain/` precedent is reinforced: three stateful controllers
  (SubstrateTracker, ShotComposer, SteeringPhaseMachine) alongside the pure
  resolvers (EC State, Pump Cycle Gate) — state-across-ticks is the criterion
  for choosing the stateful shape.
