# ADR 0021 — Pump Cycle Gate as a Pure Decision Module

**Status:** Accepted (sibling of [ADR-0015](./0015-ec-state-reconciliation-module.md) and [ADR-0017](./0017-aggregate-water-use-across-three-sources.md))

## Context

`BaseIrrigationCoordinator._run_pump_cycle` (in `irrigation_coordinator.py`) decides whether an irrigation/drain pump cycle may fire and, if not, why it is skipped. The skip rules are:

| Reason | Applies to | Gated on |
|---|---|---|
| Low tank | **all** cycles | `pause_on_low_tank` and any `irrigation_tanks` reading below its `warning_level` |
| Daily cycle limit | irrigation only | `max_cycles_per_day` vs `_cycles_today` |
| Daily volume cap | irrigation only | `daily_volume_cap_liters` vs `_volume_dispensed_today + cycle_volume` |
| Dark period | irrigation only, **scheduled only** | `skip_during_dark` and no light sensor reporting on (a manual run bypasses) |

Three guard *methods* already existed (`_find_low_tank`, `_check_safety_guards`, `_is_lights_dark`), but they read `self.growspace`, `self._get_sensor_value(...)`, and the in-memory counters — so exercising any rule required a coordinator wired to `hass`. Worse, the **decision and its effects were interwoven** inside `_run_pump_cycle`: the precedence ordering, the irrigation-vs-drain split, and the manual-bypasses-dark rule sat inline, mixed with `_LOGGER.warning`, the low-tank persistent notification, and logbook events. There was no way to ask "what would this decide?" without firing those effects, so every skip rule was reachable only through the ~1800-line `hass`-mocked integration test.

A second consumer already depends on one of these checks: the [[Adaptive Shot Control]] loop (`vwc_irrigation_coordinator.py`) calls `_check_safety_guards(scaled_duration)` on its own — not the whole skip decision — purely to set its `capped` diagnostic for [[Shot Size Composition]]. By the two-adapter rule that sub-check is already a real seam.

The codebase has an established precedent for exactly this shape: a pure, plain-data decision behind a small interface in `domain/` — `domain/ec_state.py` (ADR-0015) and `domain/water_aggregation.py` (ADR-0017), and the pure helpers in `domain/fan_control.py`.

## Decision

Extract the skip decision into a pure module `domain/pump_cycle.py` — the **Pump Cycle Gate** — following the `domain/fan_control.py` precedent: **plain data in, a verdict value out, no `hass`, no `self`, no sensor reads.**

```
TankReading(name, level, warning_level)
SkipReason = LOW_TANK | CYCLE_LIMIT | VOLUME_CAP | DARK   # enum
CycleVerdict(fire, reason, message="", low_tank=None)     # frozen, slots

cycle_volume_liters(config, duration) -> float
safety_cap_blocks(config, cycles_today, volume_today, cycle_volume_l) -> SkipReason | None
decide_cycle(*, event_type, is_manual, config, tank_readings,
             lights_dark, cycles_today, volume_today, cycle_volume_l) -> CycleVerdict
```

1. **Pure data in / [[Cycle Verdict]] out.** The coordinator resolves sensors first (tank levels → `list[TankReading]`, light state → a `lights_dark` bool) and computes the cycle volume once, then calls `decide_cycle`. The verdict carries `fire`, a `reason` enum the shell maps to effects, a **pure-formatted `message`** (the logbook text, with dynamic tank %, cycle counts, and volume math built behind the seam so the wording is unit-tested), and a `low_tank` `TankReading` for the persistent notification.

2. **The cap/limit sub-check is exported separately** as `safety_cap_blocks` and called *internally* by `decide_cycle`. The coordinator's `_check_safety_guards` becomes a thin delegator to `safety_cap_blocks`, so Adaptive Shot Control's existing `capped` probe and `decide_cycle` share one definition — two consumers, one seam.

3. **The effectful shell stays in the coordinator.** Sensor resolution (including the "fail toward dark when a light sensor is unavailable" rule, which remains in `any_light_sensor_on`), the reason→effect mapping (low-tank → persistent notification + logbook; cap/limit → logbook; dark → logbook only when `log_to_logbook`), the warning log, and the on→confirm→sleep→off→record-water→increment-counters body all remain in `_run_pump_cycle`.

## Consequences

- **One place owns *why a cycle is skipped*.** The precedence (low-tank ≻ cycle-limit ≻ volume-cap ≻ dark), the manual-bypasses-dark rule, and the drain-ignores-cap/dark rule become an exhaustive plain-data test matrix asserted without `hass`, replacing reliance on the integration test for these branches.
- **The decision interface is the test surface** — `decide_cycle`, `volume_cap_blocks`, and the message formatter are unit-tested directly.
- **`cycle_volume_liters` is computed once** by the shell and passed to both the cap check and the `finally`-block water accounting, removing the prior double-computation.
- **Honest scope:** this deepens the *decision*, not the whole method. The counter mutation, switch-confirm timing, water recording, and `CancelledError`/error handling stay in the effectful shell and remain integration-tested.

## Why Not

- **Injected-callable resolver** (a class built with `get_sensor_value` lambdas, like the EnvironmentState Assembler) — the readings here are few and cheap to resolve up front, so the seam stays purer as plain data; the assembler shape would leave the verdict "reaching out" to read.
- **Verdict carries only structured fields, shell formats every message** — keeps the dynamic skip-message wording (the part most likely to drift) out of unit tests; folding a pure formatter behind the seam tests it once.
- **Leave the guards as `self`-reading methods** — tidy but not testable; the real bugs hide in the precedence and the effect coupling, neither of which a `self`-method extraction relocates.
- **Name it around `halt`/`skip`** — `halt` collides with `halt_irrigation` (the EC-runoff safety cut on [[EC State]], ADR-0016) and `skip` names only the negative branch. The gate is the pre-cycle tank/limit/dark gate on the base pump, deliberately distinct from both the EC halt and the zero-plant steering-phase suspension (ADR-0011).
