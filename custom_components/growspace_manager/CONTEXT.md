# Growspace Manager — Domain Glossary

## Growspace

A physical grow area (tent, room, shelf). Has a name, dimensions, a plant grid (`rows × plants_per_row`), and an `EnvironmentConfig` that links sensor entity IDs to it.

## GrowspaceType

An enum (`flower`, `veg`, `mother`, `dry`, `cure`, `clone`) that describes the dominant lifecycle phase happening in a growspace.

**GrowspaceType is derived, not configured.** For regular growspaces it is computed from the most advanced `PlantStage` found across all plants in that growspace, following the priority ladder:

```
cure > dry > late_flower > mid_flower > early_flower > mother > veg > seedling == clone
```

Exception: the canonical special growspaces (`mother`, `veg`, `clone`, `dry`, `cure`) are created with an explicit type via the internal `upsert_growspace` manager method and exist before any plants are added.

## PlantStage

The lifecycle phase of an individual plant (`seedling`, `clone`, `veg`, `flower`, `dry`, `cure`, `mother`). Determined by which start-date fields are set on the plant record (e.g. `flower_start` being set moves the plant into flower stage).

## Dominant Stage

The single `PlantStage` that wins when a growspace contains plants at multiple stages. Computed by `determine_coordinator_stage()` using the priority ladder above. Maps to the growspace's effective `GrowspaceType`.

## EnvironmentConfig

The set of HA sensor entity IDs linked to a growspace. Covers: temperature, humidity, VPD, CO₂, substrate temperature, soil moisture, feed EC, bulk EC, pore EC, runoff EC, pH, drain volume, irrigation flow, power, energy, irrigation tanks, lights, fans, humidifier, dehumidifier. All sensor types can be linked to any growspace regardless of its `GrowspaceType`.

## Bulk EC

Electrical conductivity measured by a TDR or capacitance probe that reads the combined water-and-media mixture at the roots. Stored as `bulk_ec_sensors` on `EnvironmentConfig`. Replaces the former `substrate_ec_sensors` field (silent migration on load).

## Pore EC

Electrical conductivity of the water fraction only at the roots, measured by a suction cup or pore water extractor. Stored as `pore_ec_sensors` on `EnvironmentConfig`. A growspace may have both bulk and pore EC sensors configured simultaneously.

## Substrate EC Delta

The difference between **Pore EC** and **Bulk EC** (pore − bulk). Surfaced as a computed attribute on the growspace sensor entity; only present when both `bulk_ec_sensors` and `pore_ec_sensors` are configured. A growing delta indicates salt accumulation in the media — salts are bound in the substrate matrix, so bulk EC reads high while pore EC (what the roots actually see in solution) reads lower. Never a standalone HA sensor entity.

## IrrigationStrategy

Configuration for VWC-based crop steering. Lives on `Growspace` alongside `EnvironmentConfig`. Key fields: `enabled`, `lights_on_time` (user-configured), `detected_lights_on_time` (auto-tracked — see **Light Cycle Tracking**), `auto_light_tracking`.

## Light Cycle Tracking

An optional sub-feature of Crop Steering. When `IrrigationStrategy.auto_light_tracking = True` and the growspace has at least one entity in `EnvironmentConfig.light_sensors`, the backend listens for the light sensor's off→on transition each day and records the wall-clock time as `IrrigationStrategy.detected_lights_on_time`. The VWC coordinator resolves lights-on time as `detected_lights_on_time ?? lights_on_time` — the user's manual value is never overwritten and acts as the fallback.

**Precondition**: only active when `IrrigationStrategy.enabled = True`.

## Crop Steering History Chart

A chart of soil moisture, pore EC, and bulk EC readings bucketed into 5-minute averages, anchored to the most recently completed lighting cycle (resolved via **Light Cycle Tracking**: `detected_lights_on_time ?? lights_on_time`). The chart window always begins 2 hours before lights-on — the **pre-dawn baseline** — so the resting/dark-period state is visible alongside the active cycle for comparison. If the current time falls before today's lights-on (i.e. the dark period is still in progress), the chart anchors to *yesterday's* lights-on instead, so it always shows a complete, in-progress-or-recent cycle rather than an empty or inverted window.

## Photoperiod Flip

The event when any plant in a growspace transitions from veg to flower stage (i.e. `Plant.flower_start` becomes today). At this moment the daily light hours must drop from `EnvironmentConfig.veg_day_hours` (default 18h) to `EnvironmentConfig.flower_day_hours` (default 12h). The system fires a HA notification via the existing `NotificationManager` and surfaces a persistent **FlowerFlipChip** in the card.

If `auto_light_tracking` is enabled the system will auto-adapt its derived lights-off time from the sensor once the hardware schedule is changed, but the notification and chip still fire to prompt the user to verify their hardware.

## FlowerFlipChip

A pulsing growspace chip (same component as other header chips) that appears on the day `flower_start` is reached for any plant in the growspace. Persists until explicitly dismissed by the user; dismiss state is keyed to `growspaceId + flower_start` so it auto-resets if the transition date is changed. Clicking it opens the Irrigation Dialog on the Steering tab and scrolls `lights_on_time` into focus.

## Irrigation Failure Event

A logbook event (category `irrigation_error`) fired when an irrigation or drain cycle cannot complete. Three sub-cases:

- **Low tank skip** — `pause_on_low_tank` is enabled and a configured tank is below its warning level. Always logged, regardless of `log_to_logbook`.
- **Safety guard skip** — the daily cycle count or volume limit has been reached. Always logged, regardless of `log_to_logbook`.
- **Cycle abort** — the running cycle was cancelled mid-execution. Always logged.
- **Cycle error** — a service call or hardware exception occurred during the cycle. Always logged, message includes `str(exception)`.

Contrast with **dark period skip** (category `irrigation_error`, gated by `log_to_logbook`) — fires when a scheduled cycle is suppressed because lights are off. This is expected, working-as-intended behaviour.

Success events (irrigation started, irrigation completed) use `CATEGORY_ALERT` and are gated by `log_to_logbook`.

## IrrigationConfig.log_to_logbook

Boolean flag (default `True`) that gates verbose operational logbook entries: successful starts, successful completions, and dark-period skips. It does **not** gate failure events — low tank, safety guard, aborts, and exceptions always appear in the logbook regardless of this flag.

## Grow Master

The AI assistant persona surfaced in the **Grow Master Dialog**. Backed by whichever HA conversation agent the user configures (`CONF_ASSISTANT_ID`). The Grow Master has three modes: **Chat** (multi-turn conversation), **Briefing** (AI-generated facility summary), and **Inbox** (triage of Triage Alerts).

## Conversation Thread

A named, multi-turn dialogue between the user and the Grow Master, tied to a specific growspace. Each thread has a `conversation_id` issued by the backend on first turn; subsequent messages in the same thread pass that ID back so the underlying LLM agent maintains context. Threads are stored client-side in the AI slice; only `conversation_id` is persisted on the backend (via `homeassistant.components.conversation`).

## Suggested Action

A structured service call embedded in an AI response alongside the natural-language text. Encoded as a `[ACTION]` JSON block that the AI is prompted to emit when it has a specific, actionable recommendation. Shape: `{ service, target_entity_id, service_data, description, confidence }`. The frontend renders an **action card** with an Apply button; clicking it calls the HA service directly.

**Confidence** (`0.0–1.0`): self-reported by the AI in the same `[ACTION]` block. Displayed as a badge when present; omitted otherwise.

## Triage Alert

A persisted anomaly record created when a Bayesian binary sensor (`plants_under_stress`, `high_mold_risk`) transitions to `on`. Stored in `growspace_manager.ai_alerts`. Fields: `id`, `growspace_id`, `type` (`stress` | `mold`), `bayesian_reasons` (always present), `ai_reasoning` (added asynchronously if AI is enabled and available), `timestamp`, `resolved`.

**Graceful degradation**: if AI is disabled or rate-limited, the alert is logged with only `bayesian_reasons`; the Triage Inbox renders those directly. No alert is ever lost due to AI unavailability.

## AI Briefing

A structured AI-generated summary of all growspaces, covering KPIs, anomalies, and prioritised recommendations. Cached in storage; serves three triggers:
1. **Scheduled** — regenerated on a user-configurable interval (`briefing_interval_minutes`).
2. **Sensor event** — any entity in `briefing_trigger_entities` (e.g. a light sensor going `on`) fires an on-demand regeneration.
3. **Manual** — user hits "Refresh" in the Briefing mode of the Grow Master Dialog.

## Simulation Layer

HA `input_number` + `template sensor` entities used as stand-ins for real hardware sensors.

- **Demo simulation** (`growspace_demo.yaml`): dynamic sinusoidal variation for realistic Bayesian logic testing.
- **E2E simulation** (`growspace_e2e.yaml`): fully static pass-through sensors, prefixed `e2e_`, controllable from Playwright via `input_number.set_value` WebSocket calls.

## Strain Library

The user's personal collection of cannabis strains, stored in a SQLite database (`strain_library.db`). Each strain has metadata (breeder, generation), zero or more phenotypes, and a harvest history. The library is the source of truth for strain names used when assigning plants.

## Strain Lineage Tree

A recursive tree structure describing the parent strains of a given strain. Built entirely from in-memory `strains` data — no DB I/O during tree construction. Nodes carry `name`, `source` (`library` | `manual` | `seedfinder`), optional `phenotype`, and a `parents` list (capped at 2 parents, depth-limited to 15). Cycle detection prevents infinite loops via a `_seen` frozenset passed through recursion.

## Strain Analytics

An in-memory aggregation of harvest performance data across the Strain Library. Computes per-phenotype and per-strain averages (veg days, flower days, dry/wet yield) from the `harvests` list on each phenotype. Result is cached until the library changes. Contains no SQLite queries — all computation is over the in-memory `strains` dict.

## Service Facade Architecture

All coordinator sub-systems are exposed through `coordinator.services`, a `ServiceFacade` instance (`services/facade.py`). Direct access to coordinator internals (e.g. `coordinator.genetics_manager.*`, `coordinator.subsystem_manager.irrigation_coordinators`) is a bypass and should never appear in new code.

The five sub-facades are:

| Attribute | Class | Domain |
|---|---|---|
| `coordinator.services.growspaces` | `GrowspaceFacade` | Growspace CRUD, irrigation coordinator access (`get_irrigation_coordinator`, `get_dehumidifier_coordinator`), crop steering metrics |
| `coordinator.services.plants` | `PlantFacade` | Plant CRUD, watering, training, IPM, harvesting |
| `coordinator.services.config` | `ConfigFacade` | Nutrient presets, IPM presets, nutrient inventory (`get_inventory`, `update_stock`, `remove_stock`) |
| `coordinator.services.notifications` | `NotificationsFacade` | Alert creation/resolution, alert sensor registration (`get_alerts`, `resolve_alert`, `register_alert_sensor`) |
| `coordinator.services.genetics` | `GeneticsFacade` | Seed batches, lineage trees, pollination logs, phenotype scoring, plant sex assignment (`seed_batches`, `get_total_seed_count`, `get_lineage_tree`, etc.) |
