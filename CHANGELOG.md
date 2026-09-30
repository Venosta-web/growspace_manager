# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Each irrigation zone now steers, schedules and records independently, sharing
  the pump queue, safety controls and undivided daily caps. Startup probe
  readiness holds only the affected zone.

- A memory-only Supply Queue decides due requests when the supply is free.
  Manual Runs wait at the front; a single-zone growspace no longer cancels a
  running shot when another scheduled, steering or manual request arrives.
  Delivery Attempts record `due_at`, and queued steering ticks report `queued`.

- Irrigation Zone actions and WebSocket commands for adding, editing, assigning
  cells, removing and reordering zones, guarded by the growspace layout revision.
  Each cell has one owner; grid growth inherits the adjacent boundary's zone.
  Multi-zone writes require `zone_id`, each zone needs an exclusive valve, and
  the supported envelope is six zones, eight valves per zone and four substrate
  probes per quantity. Zone payloads include order, probe roles, placement and
  health while the top-level default-zone mirrors remain available.
- Zone selection for irrigation settings, strategy, phase, schedules, recipes,
  programs and Steering Modes. Pump-only single-zone and Hand Watering
  behavior remains compatible.

- **Reopening a Finalized Grow Run**: an administrator can return a
  Finalized Run to Completed with `reopen_grow_run`, giving a reason. The
  Run's boundaries do not move and it does not resume; its harvest outcomes
  and Participant names follow the Plants again until it is finalized once
  more. The earlier snapshot is kept whole beside the new one
  (`superseded_snapshots` on `get_grow_run`) rather than overwritten.
- **Discarding an empty Active Run**: `discard_grow_run` removes an Active
  Run that has recorded nothing, as if it had never started. A Run with a
  Plant movement, a changed Participant or a harvest outcome is refused, with
  each kind named in the refusal's `reasons`. Its Run number is not reused,
  its audit trail is kept, and the growspace's Unattributed Activity coverage
  resumes from where the start ended it.
- Every Run Audit Entry, lifecycle event and logbook line now carries the
  command's reason, when it was given one.

- The **Tank–Pump Disagreement**: after each local midnight, a growspace
  whose tank has `volume_liters` compares the day's tank drop, less Hand
  Watering reported as drawn from that tank, with the water its pump cycles
  delivered. A day disagrees when the two are more than 25% and more than
  1 L apart. Two disagreeing days raise the signal and two agreeing ones clear
  it, each with a logbook line naming the likely causes: a wrong pump flow
  rate, a leak, or water drawn from the tank. Days with no pump cycle, or on
  which the tank level was unknown, count neither way. The growspace payload
  carries it as `calibration.tank_pump_disagreement` with its last six days.
  It never blocks irrigation. The comparison also starts again when the pump
  flow rate is changed.
- The **Calibration Proposal**, from the tank: while a Tank–Pump Disagreement
  is raised, a growspace with a pump flow rate gets a fixable Repairs issue
  showing the configured rate, a corrected one (the configured rate × the
  median tank drop ÷ pump figure over the disagreeing days), how many days
  that rests on, and the median ratio. It names a leak and water drawn from the
  tank as the other explanations. **Apply** writes the corrected rate and
  closes it; nothing is ever applied automatically. **Ignore** lasts until the
  tank and the pump agree again. A ratio within 5% of a gallons/litres or
  litres/m³/mL mix-up offers no Apply and names the tank sensor whose unit to
  check instead.

### Changed

- **Every growspace moves into an Irrigation Zone.** On first start the
  growspace store (`.storage/growspace_manager.config`) moves to version 2:
  each growspace's flow rate, schedule, soil trigger, minimum interval,
  steering strategy, phase, substrate history and substrate probes move into
  its implicit zone `default`, which owns every cell of the grid. Nothing
  about how an existing growspace waters, steers or reports changes, and every
  entity keeps its unique_id. The untouched version 1 document is kept once as
  `.storage/growspace_manager.config.v1`. **An older build now refuses setup
  with `UnsupportedStorageVersionError`** instead of loading the new store and
  saving over it; to roll back, stop Home Assistant, copy the `.v1` file over
  `growspace_manager.config`, install the older version and start. A
  growspace whose migrated zones fail their check has its irrigation held
  under `zone_migration_invalid`, with a Repairs issue naming it and the copy;
  everything else keeps running, and the hold clears itself once the stored
  zones are valid.

### Fixed

- Unloading the integration with a monitored tank no longer fails before its
  final save, and no longer leaves the tank monitor's timer running.

## [1.3.0] - 2026-09-29

1.3.0 is the safety and accounting release: irrigation and climate now fail
closed, the daily caps survive a restart, and every pump request leaves a
durable record. Every change applies to existing installs without opting in.
Read **Safety and limitations** in the README before letting irrigation run
unattended; `docs/COMMISSIONING.md` and `docs/HARDWARE.md` are new.

### Added

- Each growspace has an **Automation** switch, an **Irrigation armed** switch
  and an **Emergency stop** button, with the `emergency_stop` and
  `reset_safety` services. While Automation is off, Growspace Manager sends
  that growspace no automatic commands, and automatic pump cycles run only
  while irrigation is armed. An emergency stop latches across restarts,
  commands every configured pump, climate actuator, fan and grow light to its
  safe state and reads each one back; an administrator clears it with
  `reset_safety` once every output reads safe.
- An **Irrigation Controller** sensor per growspace reports what the
  controller is doing and why. A disagreement between a pump command and its
  readback latches a fault that survives a restart, is written to a Safety
  Ledger, and blocks every cycle until the outputs read OFF and an
  administrator calls `acknowledge_fault`.
- `set_override` and `clear_override` hand one subsystem to a person for up
  to 24 hours. A pump that turns on without Growspace Manager commanding it is
  an **Unexpected On**: under the default `unexpected_on_policy: alert` it
  notifies once and holds every cycle, manual ones included, until the pump
  reads OFF; under `enforce_off` it is switched off, read back and latched as
  a fault.
- The **Light Leak Guard** watches the dark period every minute, from the
  managed lights and an optional illuminance sensor, and alerts on a
  debounced leak. It can also switch the managed lights off
  (`light_leak_config`); that is off by default.
- Durable **reliability evidence** per growspace: lifetime and rolling 24 h
  and 30 day counts of cycles, skips, pump readback outcomes, faults,
  inhibits, sensor dropouts, restarts, pump runtime and estimated water, in
  diagnostics, a diagnostic sensor and the `export_reliability_evidence`
  service. None of it is sent anywhere.
- Grow Runs. `start_grow_run` starts an Active Grow Run for a growspace, and
  an Active Run sensor publishes it. A Plant moved from flower to dry records
  the active Run as its Harvest Source, so harvest outcomes are attributed to
  the Run that grew them, and an unknown dry weight stays distinct from zero.
- Plant entries, exits, moves, harvests, and removals now appear in each Grow
  Run's participation history. Pending movement facts survive restarts and retry
  safely after a failed projection.
- A Grow Run can be completed. `growspace_manager/preview_grow_run_completion`
  shows the completion moment, duration, the participation that will close,
  Plants still present, harvest outcomes still pending or incomplete, coverage,
  attribution gaps and the retrospective note; `growspace_manager/complete_grow_run`
  commits it once every warning is acknowledged. Completion is refused while
  Growspace Manager's own irrigation is delivering water, clears the Active Run
  Sensor, and emits a `complete` Grow Run Lifecycle Event. Run summaries now
  carry `status`, `completed_at` and `metrics_state` (`live` while Active,
  `pending` once Completed).
- A Grow Run can start on an earlier day. While a growspace has no active run it
  keeps its plant movement and a daily summary for 365 days (the new "Keep
  activity outside Grow Runs for" general option); `preview_grow_run_start`
  shows the participants, claimed activity, uncovered gaps and any conflicting
  boundary, and `start_grow_run` with `started_on` claims that activity for the
  new run in one write. Older history is refused and pointed at an imported run.
- A Completed Grow Run can be finalized. `preview_grow_run_finalization` shows
  the Run Finalization Snapshot it would freeze — identity, boundaries, Run
  Timezone, duration, Participant identities, counts, Strains, Harvest Window,
  Yield and Yield per Harvest Source Plant with their Metric Definition
  Versions, coverage, and every fact still missing — and `finalize_grow_run`
  freezes it. A snapshot with a missing fact finalizes only once acknowledged,
  and keeps the fact missing rather than counting it as zero. A Finalized Run
  stays readable through `get_grow_run` after its Plants, Strains or Growspace
  change or are deleted, and a Harvest Source Plant of a Finalized Run can be
  deleted without choosing an outcome first. `list_grow_runs` names every Run a
  growspace holds, and `update_grow_run_metadata` edits a Run's label, tags,
  goals and notes in any status, audited, without touching its snapshot.
  Harvest outcomes now record when their Plant entered dry (`entered_dry_at`),
  and Run details carry `tags`, `goals`, `audit` and `snapshot`.
- Onboarding creates the first growspace: the config flow asks for a setup
  preset, a grid size and optional temperature, humidity and VPD sensors, and
  suggests sensors from the chosen area. A Setup Preset stamps an editable set
  of Setup Modules on the growspace, which the card's setup checklist reads.
- `restart_visual_baseline` restarts one camera's visual baseline without
  discarding its evidence, and `get_vision_history_v2` reports each camera's
  framing epoch and baseline readiness.
- A new Capture Continuity Break raises one persistent notification and is sent
  to the growspace's notify target. Each channel is retried on failure and
  resumes after a restart, and the growspace's notification switch mutes both.
- Hand Watering reports (`water_plant`, `water_growspace`) now carry an ID and
  the Home Assistant user who made them, accept a `watered_at` up to seven days
  back, and take `from_monitored_tank`. In Tank-Derived Water Mode, water from
  a monitored tank is not counted a second time.
- Any label that has a raster can be printed past an advisory refusal:
  `preview_label_record` reports `override_available`, and
  `print_label_record` accepts `override`. A missing raster, an unpublished
  revision or a stale preview still refuses.
- A commissioning guide (`docs/COMMISSIONING.md`), hardware fail-safe guidance
  (`docs/HARDWARE.md`), and a feature matrix (`docs/FEATURE_MATRIX.md`) that
  records how each feature has been verified.

### Changed

- The daily cycle limit and volume cap now enforce **Dispensed Volume**: the
  pump starts and planned volume Growspace Manager itself charged since local
  midnight, summed from durable Delivery Attempts. A restart no longer resets
  them to zero. Aborted and manual pump starts count; Hand Watering, drains
  and unconfirmed cycles do not. Aggregate Water Use stays the figure that is
  displayed and is never enforced on, and the Pump-Cycle Water Estimate now
  uses measured ON time. (ADR-0054 to ADR-0056, #852)
- Adaptive Shot Control now learns only from a **Settled Observation**: it
  waits until the moisture probe's rise after a shot stops, instead of reading
  it 15 seconds after the pump stops. A timeout, a follow-up cycle, a sensor
  dropout, a composer reset, a Manual Run or a Hand Watering report abandons
  the pending feedback, so the adaptive factors can update less often on a
  slow or unreliable probe. Manual Runs leave the size and interval factors
  untouched. (#868, fixing #855)
- Configuring a flow meter or a drain volume sensor no longer switches
  **Tank-Derived Water Mode** off. A growspace with a monitored tank of known
  volume keeps counting its water from the tank. (#857)
- Every irrigation request that reaches the Pump Cycle Gate is now a Delivery
  Attempt, the refused ones included: a request the gate or an operator hold
  refuses is recorded as `suppressed` with its reason, and a run of refusals
  with one reason is one row with a count and its first and last times. Each
  attempt now records what triggered it (the schedule slot; the steering phase,
  triggering VWC, base seconds and VWC and EC factors; or the Home Assistant
  user of a manual run) and when it was requested. Dispensed Volume and the
  daily caps are unchanged.
- An irrigation shot's attempt is written to disk before the pump is switched
  on. If that write fails, the pump is no longer switched on at all: the
  growspace is held under `delivery_record_unreadable` straight away, where
  before the pump ran until the write at confirm-ON failed.
- Scheduled drains are now Delivery Attempts too, recorded with their schedule
  slot and never charged against the daily caps; a refused drain is recorded as
  `suppressed`. A drain is written to disk before its pump is switched on, so a
  failed write now holds the growspace under `delivery_record_unreadable`
  instead of draining. An Unconfirmed Pump Cycle's attempt records
  `not_delivered_window`, from the ON command to OFF read back, in which water
  may still have moved; it still charges nothing.
- A pump found ON at start while an irrigation attempt was still open is
  Growspace Manager's own interrupted shot, not someone watering by hand. This
  now includes a crash after the ON command but before the pump confirmed ON,
  which used to count as an Unexpected On and, under the default `alert`
  policy, was left running. The pump is switched off and read back whatever
  `unexpected_on_policy` says. Every attempt still open at start closes as
  `interrupted` and keeps whatever it was charged at confirm-ON. If its pump
  reads OFF, it ends at its planned end or the moment it was found, whichever
  is earlier. Nothing is replayed. (#858, #884)
- Every pump cycle has a runtime ceiling (configurable, never more than
  3600 s) and an independent watchdog that switches the pump OFF. New
  growspaces start with a daily cap of 24 cycles and 20 L; existing cap
  values are kept, and a Repairs issue asks you to review them.
- Every pump command is read back. A pump that does not read OFF within six
  seconds latches `fault_off_unconfirmed` and is sent OFF every minute until it
  does, across restarts. Three failed ON commands in a row on one output latch
  a fault. An Unconfirmed Pump Cycle books no water.
- New irrigation starts disarmed. A growspace that already had pumps is
  migrated armed, and a Repairs issue asks you to review it.
- A restart during the lit period resumes crop steering where the day left
  off instead of restarting the P1 ramp. Automatic cycles and drains are held
  behind a **Startup Inhibit** until `startup_grace_minutes` (default 5) have
  passed and every control sensor has reported; manual runs are not held.
- Crop steering fires no shot on a moisture reading that is unavailable,
  stale or implausible, and alerts once per episode. The staleness window is
  learned from the sensor's own reporting, capped by
  `sensor_stale_after_minutes`.
- With `pause_on_low_tank` on, a tank whose level is unknown (unavailable,
  not reported for its `stale_after_minutes`, default 120, or outside 0 to
  100 %) now holds every cycle, manual runs included, and raises a Tank
  Offline alert. Before, the unreadable tank was left out and the pump ran.
- The humidifier, dehumidifier and exhaust fail safe when their sensors are
  lost, the humidifier and dehumidifier are interlocked so they never run
  against each other, and each has a maximum runtime. The exhaust falls back
  to `exhaust_fallback_speed` when every regulation sensor is lost.
- `update_plant` refuses fields a grower cannot edit instead of saving them.
- A Plant record that cannot be read is kept unchanged in quarantine, with a
  Repairs issue, instead of being dropped on the next save.
- The Plant store moves to version 2 when first loaded. The untouched version 1
  document is retained as `growspace_manager.plants.v1`; older builds refuse the
  version 2 document rather than silently discarding pending movement facts.
- **Downgrading from 1.3.0.** An older build refuses the version 2 Plant
  store. To roll back, stop Home Assistant, copy
  `.storage/growspace_manager.plants.v1` over
  `.storage/growspace_manager.plants`, install the older version and start.
  Every Plant change made since the upgrade is lost. Do the copy before the
  older version starts, not after. The new stores (Grow Runs, Delivery
  Attempts, safety and reliability evidence) are ignored by an older build.

### Fixed

- A Plant whose Stage History holds an unreadable or non-record item can be
  repaired by editing a date, instead of failing with `list index out of
range`.
- Diagnostics report the live irrigation and climate state instead of `null`,
  include the latest Safety Ledger entries, and redact notification targets,
  camera URLs, tokens and coordinates.
- A tank's `stale_after_minutes` is sent to the card, so saving a tank there
  no longer resets it.
- `add_growspace` keeps the `notification_target` it is given.
- Capture Continuity Breaks are recovered from the evidence store after a
  restart, instead of being lost.

## [1.2.3] - 2026-09-22

### Added

- **Label Templates**: a full template system that replaces the old
  fixed-coordinate Niimbot design — create, publish and revise Named Label
  Templates through a direct-manipulation editor with draft protection
  against concurrent editing; printer calibration; batch preflight, printing
  and retry over WebSocket; library recovery and safe moves; a one-page
  evidence print that probes a profile's physical claims; the Niimbot B1
  50×30 profile promoted on that evidence; and an operator override to print
  past an unproven printer.
- **Growspace Vision**: a new AI camera evidence-checkup subsystem — a
  durable, authenticated evidence history store; comparison and continuity
  policies; versioned capture contracts; configurable snapshot cadence; and
  the Vision App client and discovery.
- **Irrigation Recipes & Programs**: save, list, edit and remove
  substrate-relative Irrigation Recipes; apply one to a growspace; plan a
  whole run with Irrigation Programs; carry a growspace's settings week to
  week, or hold and say why; let a completed P1 skip P2 straight to P3.
- `add_plant` now returns the created plant's identity.
- Numeric fan speed entities are now driven directly for climate control.

### Deprecated

- The `growspace_manager.print_label` service (the Classic label request,
  including `preview: true`) is deprecated and will be removed in **2.0.0**.
  It keeps working, with byte-identical output, through every 1.x release.
  The first call in a Home Assistant run logs a warning and raises a Repairs
  issue naming 2.0.0 and the migration guide; the issue clears by itself after
  a run in which nothing called the service. The timeline, the removal
  conditions and the migration path for cards, dashboards, automations,
  scripts and WebSocket clients are in
  [docs/deprecations/print-label.md](docs/deprecations/print-label.md).

### Fixed

- Cultivation Band and Current Stage are now resolved through the Plant
  Lifecycle module, instead of drifting from it.
- `update_growspace` now patches the given fields instead of replacing the
  growspace.
- EC ramp curves are now stored correctly and bound to the growspace that
  owns them, instead of matching the first curve for a stage in dictionary
  order.
- `flower_start` is now read as a Lifecycle Timestamp.
- An unconfirmed pump shot can no longer overrun its target.
- VPD actuation now drives AC-only setups correctly, and low-VPD circulation
  is increased.
- Growspace Vision declares `hassio` as an after-dependency.

## [0.3.4] - 2026-01-16

### Added

- Bayesian inference engine for environmental stress and mold risk detection
- AI-powered Grow Master assistant with configurable personalities
- Strain analytics tracking (yield, potency, quality metrics)
- Integrated Pest Management (IPM) system with treatment presets
- Smart irrigation strategies including crop steering
- Dehumidifier automation with stage-specific thresholds
- Nutrient inventory management and tracking
- Timeline event system for plant lifecycle documentation
- Task calendar for scheduled notifications
- WebSocket API for real-time frontend communication
- Comprehensive test suite (99% coverage, 1341 tests)

### Fixed

- Critical `NameError` in `evaluator_strategy.py` preventing test execution
- Import ordering in config handlers

### Changed

- Achieved Gold Quality Scale compliance
- Enhanced type hints across all modules (Python 3.13+)
- Improved error handling in config flows
- Optimized Bayesian probability calculations

### Security

- Input sanitization via Voluptuous schemas
- Safe parsing with `ast.literal_eval` only
- No eval() or exec() usage
- Pathlib for file operations

## [Unreleased]

### Planned

- Additional environment sensor integrations
- Enhanced AI model training capabilities
- Multi-user support
- Cloud backup integration
