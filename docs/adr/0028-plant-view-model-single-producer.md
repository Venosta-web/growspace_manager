# 0028. Plant View Model is the single producer of serialized Plant data

Date: 2026-07-06

## Status

Accepted

## Context

Serialized Plant data had two hand-synced producers: the plant sensor's
`extra_state_attributes` (sensor/plant.py) and `PlantViewModelBuilder.build()`
(presentation/plant_view_model.py). The view model even carried a confessing
comment — "these mirror the top-level attributes exposed by the plant
sensor" — which is exactly the "field silently missing on the card" bug class
that caused the visual_tag/drying-fields incident: a field added to one
producer doesn't exist in the other, and nothing fails.

The same class of defect hid in hand-copied sub-dataclass blocks: the wire's
`phenotype_score` dropped `notes`/`updated_at`, and the growspace payload's
`irrigation_config` dropped `pump_flow_rate_ml_per_sec` and
`phase_changed_at`; `drain_config`/`water_usage`/`energy_tracking` each
dropped a field too.

The two surfaces cannot simply share one dict: the sensor attribute contract
exposes raw stored date strings (automations parse them) while the wire
formats dates for display, and their day-count helpers differ semantically
(model methods are stage_history-aware and return `None` for never-watered;
the domain functions use start-field windows and return `0`).

## Decision

- `presentation/plant_view_model.py` is the one home for serialized Plant
  data. It owns two projections that share every computed block
  (drying observations, PHI readout, sub-dataclass dicts, position):
  - `PlantViewModelBuilder.build()` — the wire payload (formatted dates).
  - `PlantViewModelBuilder.build_attributes()` — the plant sensor's HA
    attribute dict (raw stored dates). The sensor delegates to it.
- Sub-dataclass blocks (`phenotype_score`, `harvest_metrics` on Plant;
  `irrigation_config`, `drain_config`, `water_usage`, `energy_tracking` on
  the growspace payload) serialize via the model's own `to_dict()` so a new
  model field ships automatically. Computed properties (e.g.
  `total_score`) are appended explicitly.
- The wire payload's `{stage}_days` loop now iterates `PLANT_STAGES` like the
  sensor always did, adding the sub-stage keys (`veg_early_days`,
  `flower_mid_days`, …) to the wire.

All changes are wire-additive; the card's zod schemas strip unknown fields.

## Consequences

- Adding a field to a Plant/growspace sub-model propagates to the sensor
  attributes and the card payload with no serializer edit.
- The two day-count semantics (`Plant.get_days_in_stage` vs
  `domain.calculate_days_in_stage`, and the days-since-watering pair) still
  disagree; both predate this ADR and are kept per projection on purpose.
  Reconciling them is a semantic decision tracked separately — do not "fix"
  one side to match the other inside a serialization change.
- Snapshot tests pin both projections; a field appearing in only one of them
  now fails `test_build_attributes_matches_wire_payload_on_shared_blocks`.
