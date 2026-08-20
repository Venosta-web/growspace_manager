# ADR 0021 — `ShotComposer` Owns the Shot Size Composition and Adaptive Shot Control

**Status:** Accepted

## Context

The crop-steering shot-sizing logic lived inside `VWCIrrigationCoordinator`: two
mutable feedback factors (`_shot_scale_factor`, `_interval_scale_factor`), the
feedback update (`_update_shot_feedback`), the reset-to-1.0 lifecycle (scattered
across `_reset_extra_daily_state` and `_set_phase`), and the
`base × VWC × EC` composition multiply (`_handle_watering`).

This was the one part of the irrigation cluster that had not received the
deep-module treatment the rest already has (`domain/ec_state.py`,
`substrate_tracker.py`, `domain/environmental_targets.py`). It had **no
locality** (the factors, their math, and their lifecycle were spread across four
methods) and **no test surface**: the suite already carried ~20 assertions that
set `_shot_scale_factor` directly and called `_update_shot_feedback` through a
full coordinator fixture — unit tests forced to wear an integration-test costume
because there was no seam to test against.

## Decisions

### 1. A stateful controller, not a pure-per-call resolver

The feedback factors persist across minute-loop ticks and reset on phase events,
so `ShotComposer` retains them as state and is tested with deterministic
sequences — the `SubstrateTracker` precedent. It is deliberately **not** shaped
like `ECStateResolver` (pure, rebuilt per call): a pure function would leave the
factors and the reset lifecycle in the coordinator, defeating the locality win.

### 2. The seam cuts at the whole Shot Size Composition

`ShotComposer.compose(...)` takes the base seconds and returns the finished
`ShotComposition` record (the multiply, the cap-aware `effective_seconds` /
`capped`, and the diagnostic factors). The alternative — extracting only the
feedback factors and leaving the multiply in `_handle_watering` — would split the
`ShotComposition` record across two modules.

### 3. EC factor and cap-check are injected callables

`compose` receives `get_ec_factor()` and `check_cap(seconds)` from the
coordinator. The [[EC State]] seam (`ec_state.py`, ADR-0015/0016) and the
downstream `_run_pump_cycle` cap enforcement stay exactly where they are; the
composer never reaches into the coordinator or Home Assistant. This keeps it
unit-testable with plain values and preserves the "one EC actuator" rule —
EC modulation is still computed once, by the existing code, and only for P2.

### 4. The module owns the reset *rule*; the coordinator owns the *trigger*

`reset()` (both factors → 1.0) lives on the composer, so the lifecycle rule is in
one place. *When* to reset stays with the coordinator's phase machine
(lights-on daily reset, P1→P2 transition) — detecting those events is
inherently coordination, not composition.

### 5. Behaviour is unchanged

This is a structural move only. The overshoot/recovery math, the clamps, the
`dynamic_shot_enabled` gate, the tuning fields, the reset moments, and the safety
caps are identical to the prior in-coordinator implementation. ADR-0014 governs
that behaviour and is untouched; the migrated tests assert the same numbers.

## Consequences

- The Adaptive Shot Control feedback math is unit-tested in
  `tests/domain/test_shot_composer.py` with no coordinator and no Home Assistant;
  the integration suite keeps only thin wiring tests (reset on phase events,
  `observe` on cycle completion, the `compose`→pump path).
- `VWCIrrigationCoordinator` shrank by ~125 net lines and no longer holds shot
  factor state directly.
- A second domain precedent now exists alongside the pure `ec_state` one: a
  stateful controller is the right shape when state persists across ticks.
