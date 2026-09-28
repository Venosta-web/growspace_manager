# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.2.3] - Unreleased

### Added

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

### Changed

- Manual irrigation runs leave Adaptive Shot Control's size and interval
  factors untouched while still abandoning feedback pending from an earlier
  steering shot.
- The Plant store moves to version 2 when first loaded. The untouched version 1
  document is retained as `growspace_manager.plants.v1`; older builds refuse the
  version 2 document rather than silently discarding pending movement facts.
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
  is earlier. Nothing is replayed.

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
