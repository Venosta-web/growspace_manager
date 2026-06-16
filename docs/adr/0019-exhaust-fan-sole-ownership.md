# ADR 0019 — Exhaust Fan Sole Ownership + Repair-Based Migration

**Status:** Accepted (completes the ownership transfer left implicit by [ADR-0018](./0018-exhaust-fan-combined-demand.md))

## Context

Before the [[ExhaustFanController]] existed, the only thing that ever moved an
exhaust fan was the **DehumidifierCoordinator**. Its controlled set was
`dehumidifier_entities + exhaust_fan_entities` (`_get_all_controlled_entities`
returned `dehum + exhaust`), so a grower who turned `control_dehumidifier` on and
listed exhaust fans got crude on/off cycling of those fans for free, driven by the
dehumidifier's VPD/humidity thresholds.

ADR-0018 added a dedicated `ExhaustFanController` with combined-demand regulation
and per-domain speed dispatch, but its Scope section only carved out the
source-air gate and critical-temp override as follow-ups — it never said the
dehumidifier coordinator should **stop** controlling exhaust fans. As a result two
subsystems could command the same `exhaust_fan_entities`, and the ownership
boundary was undocumented. (The originating issue cited "ADR 0017" for the
transfer, but 0017 is about water aggregation — the reference was dangling, which
is what prompted this ADR.)

The migration is not free. `ExhaustFanConfig` defaults to `enabled=False`, so
the moment the dehumidifier coordinator relinquishes exhaust, an install that
relied on the old behavior would **silently stop cycling its exhaust fans** until
the grower enables the new controller. We cannot auto-migrate: the old behavior is
on/off humidity thresholds, which carry no speed-band information from which to
synthesize an `ExhaustFanConfig`.

## Decision

1. **The `ExhaustFanController` becomes the sole owner of `exhaust_fan_entities`.**
   `DehumidifierCoordinator._get_all_controlled_entities` returns only
   `dehumidifier_entities`; exhaust fans are dropped from its controlled set and
   its docstring no longer claims exhaust control.

2. **No auto-migration.** We do not infer an `ExhaustFanConfig` from the old
   dehumidifier thresholds. The opt-in to the new controller is explicit.

3. **Affected installs raise a repair issue** (the **Exhaust Migration Repair**)
   directing the grower to the Exhaust panel. The trigger is evaluated **per
   growspace**: `control_dehumidifier` on **AND** `exhaust_fan_entities`
   configured **AND** `exhaust_fan_config.enabled` is False.

   The `AND NOT enabled` clause is a deliberate deviation from the literal
   acceptance criteria ("`control_dehumidifier` on and `exhaust_fan_entities`
   configured"). A grower who has already enabled the new controller is being
   served by it and must not be nagged.

4. **Create-or-clear lifecycle.** A shared helper evaluates the condition and
   either raises (`async_create_issue`) or clears (`async_delete_issue`) the
   per-growspace issue. It is called from `async_setup_entry` **and** from every
   service handler that can mutate a trigger input without a full entry reload:
   `configure_exhaust_fan` (toggles `exhaust_fan_config.enabled`),
   `set_dehumidifier_control` (toggles `control_dehumidifier`), and
   `configure_environment` (rebuilds `exhaust_fan_entities` and
   `control_dehumidifier`). Those services persist via `async_restart`, not a
   reload, so a setup-only check would not self-heal until the next restart. The
   repair therefore clears the moment the grower enables the new controller,
   removes the exhaust entities, or turns off `control_dehumidifier`.

   `configure_environment` rebuilds the whole `EnvironmentConfig` and previously
   did **not** carry `exhaust_fan_config`, so an environment edit silently reset
   the exhaust controller to `enabled=False` — disabling a grower's controller
   *and* re-arming this repair. That handler now preserves the existing
   `exhaust_fan_config` (mirroring how `circulation_fan_config` already falls back
   to the stored config), so the two concerns no longer collide.

5. **Presentation:** `issue_id = exhaust_fan_migration_{growspace_id}`,
   `is_fixable=False`, `IssueSeverity.WARNING`. A fix flow can't open a panel and
   auto-migration is disallowed, so a guided repair adds nothing; WARNING (not
   ERROR) matches an opt-in behavior change rather than a failure.

## Scope

Out of scope: actively driving **off** an exhaust fan the dehumidifier last
commanded on. A `switch`/`input_boolean` exhaust device can be left stuck on
after the transfer until the grower enables the new controller. The risk this
issue addresses is fans that **stop cycling**, not fans stuck on; teardown of
orphaned fans would require the dehumidifier coordinator to track which exhaust
entities it last commanded and could turn off a fan a grower wanted running.
Accepted edge case.

## Consequences

- Exactly one subsystem commands each exhaust fan; no more two-owner contention.
- Installs relying on the old "exhaust rides along with the dehumidifier" behavior
  get a visible, self-healing prompt instead of silent loss of function.
- The repair condition is the same predicate inverted for create vs. clear, so the
  raise and the heal can't drift apart.

## Why Not

- **Auto-migrate by synthesizing an `ExhaustFanConfig`** — old on/off humidity
  thresholds carry no speed-band, target, or tolerance information; any synthesized
  config would be a guess that silently changes how the grower's tent is vented.
- **Trigger on the literal AC (no `enabled` guard)** — would raise the repair for
  growers already migrated to the new controller, training them to ignore it.
- **Setup-only check** — the dedicated configure services don't reload the entry,
  so the issue would linger after a grower fixed the condition until the next
  restart.
- **`is_fixable=True` repair flow** — the only real fix is opening the Exhaust
  panel; a confirm-style flow can't do that and auto-enable is disallowed.
- **Drive orphaned exhaust fans off on transfer** — larger state-tracking concern,
  and risks switching off a fan the grower intended to run; the framed risk is
  under-venting, not over-venting.
