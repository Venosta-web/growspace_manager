# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
