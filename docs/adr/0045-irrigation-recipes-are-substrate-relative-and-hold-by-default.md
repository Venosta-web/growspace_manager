# ADR 0045 — Irrigation Recipes are substrate-relative, provenance is not authority, and the program holds by default

**Status:** Accepted (extends [ADR-0012](./0012-steering-mode-preset-stamp.md); builds on [ADR-0011](./0011-shot-volume-scales-with-live-plant-count.md) and [ADR-0029](./0029-irrigation-schedule-pure-time-rules.md); delivery governed by [ADR-0030](./0030-cross-repo-contract-fixture.md))

## Context

Growers want to save a growspace's irrigation settings and re-apply them — to another tent at the same point in its cycle, or to the same tent on the next run. Nutrient presets already do this for feed (`NutrientPreset`: a global library keyed by stage + week, matched through `get_applicable_presets`), and ADR-0012 established what applying irrigation settings means (a one-shot stamp into the editable fields, after which the coordinator reads only those fields). What does not exist is a **grower-authored** irrigation object; ADR-0012's presets are a table that ships with the product.

Four properties of the existing code shape the decisions below.

**A shot in seconds is not a portable quantity.** `IrrigationStrategy` stores `p1_shot_duration_seconds` / `p2_shot_duration_seconds`, and the pump converts them through `IrrigationConfig.pump_flow_rate_ml_per_sec`. Ten seconds delivers whatever that growspace's plumbing delivers. Copying seconds between growspaces is not portability — it silently over- or under-waters the target by the ratio of their flow rates, with no error and no visible symptom until the substrate responds. ADR-0011 already built the escape: Volume Mode expresses shots as a percent of substrate volume and converts percent → ml → pump seconds against the growspace's own [[Substrate Profile]] and flow rate.

**`ECRampCurve` shows what implicit binding costs.** It is the only existing week-keyed program, and it has no growspace binding at all. `sensor/environment.py:201` resolves it as `next(curve for curve in ec_ramp_curves.values() if curve.stage == stage)` — first match in dictionary insertion order. `config_facade.save_ec_ramp_curve` even accepts a `growspace_id` and discards it (the manager signature does not take one, and the facade logs a legacy warning). With two flower curves configured, which one drives a growspace's feed target is an accident.

**Stage and week are derived, never stored.** `resolve_feed_stage_week` (`domain/ec_state.py:157`) answers `(stage, week)` for a growspace as the furthest-along **live** stage and `days_to_week` of the greatest [[Current Stage Age]] within it. It was chosen for feed EC specifically to avoid under-feeding the most EC-demanding cohort in a mixed tent — a rationale that does not transfer to irrigation, where following the furthest-along cohort over-waters the younger one.

**A stamp is destructive by design.** ADR-0012 made re-selecting an already-declared Steering Mode re-stamp rather than no-op, deliberately discarding hand tweaks as a "reset to defaults". That is correct for an explicit grower gesture. It is a different proposition entirely when something other than the grower triggers it.

## Decision

Two objects, both grower-authored, in a global library: an **[[Irrigation Recipe]]** (one growspace's settings, one `kind` — `crop_steering` or `schedule`) and an **[[Irrigation Program]]** (recipes assigned to `(stage, week)` slots across a run, held **by reference**, bound to a growspace by an explicit `irrigation_program_id`). "Recipe" is reserved for grower-authored objects and "preset" for shipped tables, so ADR-0012's `media × mode` table and a grower's saved flower-week-3 settings can never be confused in prose or in code.

Three decisions are load-bearing and hard to reverse.

### 1. Shot sizes are stored substrate-relative, and media never converts

A recipe stores shot size as a percent of substrate volume, never as pump seconds. Applying recomputes the target's seconds through the existing ADR-0011 path against _its_ flow rate and _its_ `liters_per_pot`. A recipe authored while the growspace is in Seconds [[Shot Sizing Mode]] derives the percent from that growspace's captured flow rate and pot volume; the save is **refused** when either is unset, because seconds alone cannot be normalized honestly.

Pot size normalizes. **Media does not.** ADR-0012's own table is a set of discrete agronomic judgements — rockwool drybacks smaller and stacks EC higher than coco at the same declared intent — not a function that can be interpolated. A cross-media apply therefore **warns and proceeds unscaled**; it is never refused and never auto-converted.

`pump_flow_rate_ml_per_sec` gains no companion field. "Dripper L/h × emitter count" is an input representation of that one number, not a second one.

### 2. Provenance describes; the slot decides

A recipe carries its authoring context — media, `liters_per_pot`, flow rate, and the stage + week it was authored in — as **[[Recipe Provenance]]**. Provenance is descriptive only. It drives the media-mismatch warning and sorts the picker; it never gates an apply and never decides when a recipe runs. _When_ is decided by the [[Irrigation Program]] slot, or by the grower for a direct apply. Applying a flower-week-3 recipe to a week-5 tent is a supported deliberate act.

Applying records `applied_recipe_id` + `recipe_applied_at` on the strategy — nullable, `None` meaning "never applied" as a real third state, exactly parallel to `declared_steering_mode`. **No drift hash is stored**: recipes are held by reference, so "has the grower tweaked since applying?" is a live field comparison computed on read. Apply keeps ADR-0012's semantics unchanged, including that applying always writes.

### 3. The program holds whenever it has no unambiguous instruction

One rule, three causes: a week with no slot, a week past the end of the program, and — under auto-advance — a growspace whose fields have drifted from its stamp. In all three, nothing changes and the grower is told.

Auto-advance is opt-in (`program_auto_advance`, defaulting off), mirroring the existing opt-in `auto_advance_p1_to_p2` / `auto_advance_p2_to_p3` flags on `IrrigationConfig`. With it off, the card recommends and the grower confirms. Assigning a program **binds only** and applies nothing — except when auto-advance is already on, which is that consent expressed in advance.

`resolve_feed_stage_week` is reused **unchanged** to resolve the current slot.

## Rejected alternatives

- **Copying seconds verbatim with a mismatch warning.** The simplest thing that looks like it works, and the reason it was rejected is the failure mode: a warning the grower dismisses produces a tent watered at half or double the intended rate, with correct-looking numbers on screen. Substrate-relative storage makes the portable case _correct_ rather than _cautioned_.
- **Refusing an apply across differing media.** Agronomically honest, but ADR-0012 faced this exact choice on soil and chose gentle presets over refusal, for the same reasons: refusal adds a failure path and blocks a legitimate "I know what I'm doing" apply.
- **Auto-scaling shot sizes across media.** Requires a coco→rockwool coefficient that has no basis in anything; it would dress up a guess as a conversion.
- **Letting the recipe's own stage/week gate where it can be applied.** Makes provenance authoritative, which means a grower must edit a recipe to reuse it one week early — and creates two competing authorities the moment a program slot disagrees with the recipe's label.
- **Storing a drift hash at stamp time.** Cheap to write, but it is derived state that can go stale against a by-reference recipe; the comparison is computable on read from data already loaded.
- **Carrying the previous week's recipe forward into an undefined slot.** Produces actuation from the _absence_ of data. Under auto-advance it would also silently discard hand tweaks on a week where the grower deliberately defined nothing.
- **Auto-advance overwriting drift.** Makes hand-tuning worthless whenever auto-advance is on, and the damage is invisible until the plants show it — the worst available feedback loop on a subsystem that moves water.
- **An irrigation-specific week rule (least-advanced cohort, or refusing to progress a mixed tent).** Would mean two week calculators and a card that shows "flower wk3" beside the feed target and "veg wk2" beside the program in the same tent.
- **Per-stage programs, ECRampCurve-shaped.** A whole-run program that only defines flower slots already _is_ a per-stage program; per-stage would additionally need a veg→flower handoff rule.
- **Holding recipes by value inside programs.** Gives two places to fix a bad shot size and no way to notice they diverged. The growspace already holds the by-value snapshot — that is what the stamp is — which leaves the program free to be a plan.

## Consequence

Recipes port correctly across plumbing and pot size, and honestly refuse to pretend they port across media. The Seconds-Mode grower can author recipes, but only once a flow rate and pot volume are configured — a new precondition on a previously unconstrained mode, surfaced as a save-time refusal naming the missing field.

In a mixed-stage tent the furthest-along schedule **over-waters the younger cohort**. This is accepted, not solved: there is no per-plant escape on one pump and one substrate line, and the mitigation is that progression confirms by default. It inverts the risk `resolve_feed_stage_week` was originally chosen for, and that inversion is the price of one week calculator.

The program layer is inert by default in every ambiguous case, so its failure mode is a tent that keeps doing what it was doing — never a surprise irrigation change. The cost is that a grower who tweaks one field and forgets will find auto-advance has quietly stopped progressing them; the notification is what makes that recoverable.

Because programs hold recipes by reference, deleting a recipe leaves empty slots rather than being refused or cascading. Combined with the hold rule this degrades to "no instruction", so a deleted recipe can never actuate anything; the delete confirmation names the affected programs.

Per ADR-0030 this lands GSM-first and in two shipments — recipes, then programs — and both tiers enter the golden fixture: the global library alongside `nutrient_presets` in `models/contract.py`, and `applied_recipe_id`, `recipe_applied_at`, `irrigation_program_id`, `program_auto_advance` populated **non-null** on the fixture growspace, since every past cross-repo drop-bug involved an optional field that a sparse fixture would not have caught.
