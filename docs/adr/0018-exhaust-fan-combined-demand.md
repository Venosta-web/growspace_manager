# ADR 0018 — Exhaust Fan Controller: Combined-Demand Regulation

**Status:** Accepted

## Context

The integration already drives in-tent air movement through the
**CirculationFanController** ([[Circulation Fan Controller]]), which picks
*exactly one* regulation mode (`humidity`, `temperature`, or `vpd`) and layers a
dynamic wind oscillation on top. That single-mode model fits a fan whose job is
to keep air stirring inside the canopy.

Exhaust is a different job. An exhaust fan (or damper) evacuates hot, humid air
*out* of the tent, and the grower wants it to respond to **whichever stress is
worst right now** — not to a single pre-chosen variable:

- the tent is **too hot** → pull more air,
- the tent is **too humid** → pull more air,
- the **VPD is too low** (air is saturated relative to the leaf) → pull more air.

A mode selector would force the grower to guess which of these dominates, and the
answer changes across the day and the grow stage. So exhaust needs a *combined*
signal, and the VPD term has to be **inverted** relative to circulation: for
circulation VPD mode, a high VPD reading raises fan speed; for exhaust, a **low**
VPD (humid) is the condition that demands evacuation.

The three terms reuse the same linear band math the circulation controller
already uses. Before this work that math (`compute_fan_speed`,
`evaluate_temp_override`, the stage-aware VPD target resolution, and
`FAN_VPD_STAGE_DEFAULTS`) lived *inside* `circulation_fan_coordinator.py`, so an
exhaust controller could only get at it by importing from a sibling coordinator
or by duplicating it.

## Decision

1. **Extract the fan-control math into a shared `domain/fan_control.py` module**
   (the enabling refactor, [#473]). `compute_fan_speed`,
   `evaluate_temp_override`, `compute_wind_offset`, `resolve_stage_vpd_target`,
   and `FAN_VPD_STAGE_DEFAULTS` become coordinator-free pure functions. The
   circulation coordinator re-exports them, so its behavior and tests are
   unchanged.

2. **Add an `ExhaustFanController`** as a per-growspace `EnvironmentController`,
   registered in the `SubsystemManager` alongside the dehumidifier, humidifier,
   and circulation controllers, with a `get_exhaust_fan_controller` accessor. It
   runs on the same fixed 10 s tick.

3. **Demand is the maximum of three terms**, clamped to the configured band:

   ```
   temp_demand     = compute_fan_speed(temp,     temp_target, temp_tol, min, max)
   humidity_demand = compute_fan_speed(humidity, hum_target,  hum_tol,  min, max)
   vpd_demand      = compute_inverted_fan_speed(vpd, vpd_target, vpd_tol, min, max)

   final = clamp(max(temp_demand, humidity_demand, vpd_demand), min_speed, max_speed)
   ```

   `compute_inverted_fan_speed` is the only *new* term: it delegates to
   `compute_fan_speed` with the speed bounds swapped, so a VPD at/below
   `target − tolerance` yields `max_speed` and a VPD at/above `target + tolerance`
   yields `min_speed`. A sensor that is missing or unavailable drops its term from
   the maximum; if none of the three sensors read, the tick is a no-op.

4. **Stage-aware VPD targets are honored** via the shared
   `resolve_stage_vpd_target` when `stage_vpd_enabled` is set, exactly like
   circulation — including day/night resolution and per-stage overrides.

5. **Speed dispatch is per entity domain.** A `fan` entity receives the final
   speed as a percentage (`fan.set_percentage`). A `switch` or `input_boolean`
   exhaust device is turned **on** when the final speed exceeds `min_speed` and
   **off** otherwise. The controller is a no-op when `enabled=False` or no
   exhaust entities are configured, and it restarts cleanly when the
   `configure_exhaust_fan` service rewrites the config.

## Scope

This slice deliberately implements **only** the combined-demand regulation and
the per-domain dispatch. Two adjacent concerns are handled by separate slices and
are **out of scope here**, even though `ExhaustFanConfig` already carries fields
for them:

- the **source-air gate** (skip/limit exhaust when the lung-room / source air is
  colder than `minimum_source_air_temperature`), and
- the **critical-temperature override** (`critical_temp_low` /
  `critical_temp_high` / `critical_temp_hysteresis`).

## Consequences

- One implementation of the fan band math, shared by circulation and exhaust;
  fixing or extending it happens in one place.
- Exhaust responds to the worst of heat, humidity, and saturation without the
  grower choosing a mode, which matches how an evacuation fan is actually used.
- The inverted VPD term is a thin, separately unit-tested helper, so the
  "more exhaust when it's humid" rule is pinned by its own tests rather than
  buried in the controller.

## Why Not

- **Reuse the circulation single-mode model** — forces the grower to pick one
  stress variable for a fan whose purpose is to react to all of them.
- **Sum the three terms instead of taking the max** — would push the fan past the
  level any single condition justifies and make the band bounds meaningless.
- **A second copy of `compute_fan_speed` for inversion** — duplicates the band
  math; swapping the speed bounds on the existing helper expresses the inversion
  with no new arithmetic.
- **Implement the source-air gate and critical-temp override here too** — larger,
  separately testable safety behaviors; bundling them would blur this slice's
  combined-demand contract.

[#473]: https://github.com/Venosta-web/growspace_manager/issues/473
