# 26. Environment Patch — one write seam for EnvironmentConfig

Date: 2026-07-05

## Status

Accepted

## Context

`EnvironmentConfig` (~50 fields) had five writers, each with private merge rules:

- `services/environment.py:handle_configure_environment` rebuilt the dataclass from
  ~40 explicit kwargs, silently resetting every field it didn't name
  (`vision_checkup_config`, `bayesian_options`, DLI targets,
  `snapshot_interval_hours`; the hysteresis threshold tables reset to `{}`;
  stress/mold thresholds to hardcoded defaults; `electricity_cost_per_kwh` became
  `None` — a type violation). Preservation was patched in ad hoc, incident by
  incident: `exhaust_fan_config` (ADR-0019), the growlight trio, AC-Infinity
  bundles, tank runtime state.
- Both config-flow environment handlers did `from_dict` full replaces with their own
  `preserve_ac_infinity_devices` hooks.
- The narrow fan writers replaced their sub-config with defaults for omitted keys.
- `storage_manager._apply_options_to_growspaces` re-applied per-growspace
  `config_entry.options` blobs over the store on **every restart** — but nothing has
  written those blobs since the config handlers moved to writing the growspace store
  directly. The path was a zombie reader: any install carrying a stale blob had its
  environment config reverted to that snapshot on every restart, silently undoing
  all service-made edits.

The interface of "write an EnvironmentConfig" included knowing which fields to
hand-preserve and which writer you were standing in — a shallow seam whose bug class
(field silently wiped, effect silently forgotten) recurred with every new field.

## Decision

1. **Patch semantics.** `configure_environment` — and every EnvironmentConfig write —
   moves from full replace to patch: an absent field keeps its existing value; an
   explicitly present field (including an empty list/dict) is a deliberate set or
   clear.
2. **One pure merge module.** `domain/environment_patch.py` owns all merge law.
   Build/apply split: writer-specific builders (`patch_from_service_call`,
   `patch_from_flow_options`, per-sub-config builders) front-load validation and
   normalisation (singular/plural aliases with post-merge shadow re-derivation,
   per-item key filtering with drop-and-warn for tank/sensor-group lists, the
   stage/optimal VPD validators); `apply_environment_patch(current, patch)` is total
   on a built patch and returns a verdict record (fresh config, `changed_fields` by
   value comparison, `controllers_to_restart`, `exhaust_repair_relevant`, logbook
   `summary`, warnings). `current=None` applies onto dataclass defaults.
3. **Total field ownership classification.** Merge behaviour derives from a
   per-field table declared beside the model (`grower-config` /
   `runtime-accumulated` / `sub-config`), with rows carrying the singular alias and
   nested per-item runtime specs (tank runtime fields matched by `sensor_entity`).
   An import-time symmetric-difference check makes the table total: a new field
   without a row fails every import.
4. **One shared effect shell.** `async_commit_environment_patch` owns the
   assign → save → refresh → targeted controller restarts → exhaust-repair
   re-evaluation ordering for all runtime writers. Config-flow saves gain the
   controller restarts they previously lacked; the ADR-0019 repair re-evaluation
   fires from the verdict, not from a call site remembering to.
5. **Single source of truth.** The growspace store owns `environment_config`.
   On load, a per-growspace options blob is adopted only when the store has no
   environment config for that growspace (one-time migration, pure path, no
   effects), then deleted. The every-restart options-apply and
   `_preserve_tank_runtime_state` are removed.

## Considered options

- **Minimal single-function design** (one `apply(existing, raw_dict)` entry point):
  rejected because it left the duplicated effect choreography at all five call
  sites — the second half of the recurring bug class.
- **Maximal flexible design** (leaf-path partial patches, patch union algebra,
  validation policy knobs, `diff_configs`): rejected as speculative surface with no
  current caller; all of it is additive later without breaking the chosen interface.
- Chosen hybrid: the caller-optimised skeleton (named builders + commit shell) with
  the declarative classification table, trimmed of speculative surface.

## Consequences

- Adding an EnvironmentConfig field = model field + one classification row (forced
  at import); every writer preserves it automatically, and no writer changes.
- Behavioural change: automations that relied on *omission* to clear a field must
  now send an explicit empty value. `services.yaml` needs updating and the Lovelace
  card needs a coordinated audit for omit-to-clear assumptions (the card sends full
  payloads, so the expected impact is nil — but it must be verified, cross-repo).
- The stage-key vocabulary (`FAN_VPD_STAGE_DEFAULTS`' keys) moves to `const.py` so
  the pure module never imports a coordinator.
- The merge law is unit-testable with two `EnvironmentConfig` literals and a dict;
  the known regressions (exhaust reset, threshold wipe, tank-history clobber,
  electricity-cost type violation, singular-resurrects-cleared-plural) become a
  table-driven test.
