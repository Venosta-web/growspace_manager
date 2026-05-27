# Growspace Manager — Domain Glossary

## Core Concepts

**Strain Image Gallery**
The collection of images associated with a single phenotype. Stored as a JSON array on the phenotype record. Each entry has a path and optional crop metadata. One entry is designated as the Strain Thumbnail. A phenotype may have zero or more images.

**Strain Thumbnail**
The single designated image from a phenotype's Strain Image Gallery that is used everywhere a strain image is displayed (plant cards, library list, recommendations). If a phenotype has no images, the thumbnail is resolved from a sibling phenotype of the same strain: the `"default"` phenotype takes priority as the fallback source, then any other sibling in alphabetical order. This fallback is display-only — the phenotype's own gallery remains empty.

**Plant**
An individual cannabis plant tracked from seedling through cure. The atomic unit of all lifecycle, drying, and curing tracking. A "harvest batch" is not a separate concept — each plant is weighed and tracked individually.

**PlantStage**
The lifecycle phase of a Plant. Ordered stages: `seedling → clone → mother → veg → flower → dry → cure`. The `dry` and `cure` stages are fully-fledged lifecycle stages, not post-harvest metadata.

**Photoperiod Flip**
The calendar day on which a Plant transitions from vegetative to flower stage — specifically, the day `flower_start == today`. The grower must change the light schedule to 12 hours on this day. When `IrrigationStrategy.auto_light_tracking` is enabled on the growspace, the integration will auto-adapt the light schedule from sensor data; otherwise the grower must update it manually. A notification is sent once per day per growspace when any plant's Photoperiod Flip day arrives.

**HarvestMetrics**
Final-outcome snapshot values recorded at the point of harvest: `wet_weight`, `dry_weight`, `trim_weight`, `thc_percentage`, `cbd_percentage`, `terpene_profile`. These are single snapshots, not time-series. Do not add in-progress drying observations here.

**DryingData**
In-progress observations recorded while a Plant is in the `dry` stage. Contains:
- `weight_log`: time-series of `WeightEntry(date, weight_grams)` readings
- `moisture_log`: time-series of `MoistureEntry(date, moisture_percent)` readings
- `visual_tag`: free-text identifier (e.g. "Red Velcro") persisted across all stages

Distinct from `HarvestMetrics`. `HarvestMetrics` records what happened; `DryingData` records what is happening.

**WeightEntry**
A single daily weight observation during drying: `{date: str (ISO), weight_grams: float}`.

**MoistureEntry**
A single daily moisture meter reading during drying: `{date: str (ISO), moisture_percent: float}`.

**Visual Tag**
Free-text label assigned to a Plant for physical identification in the drying room (e.g. colored velcro tie color). Stored on `DryingData`. Persists across all lifecycle stages.

**Target Dry Weight**
25% of the plant's initial wet weight (`HarvestMetrics.wet_weight`). Computed constant — not user-configurable.

**Cure-Ready Threshold**
A moisture reading ≤ 12.0% indicates the plant is ready to move from `dry` to `cure`. Computed constant — not user-configurable.

**Estimated Days to Target Weight**
Projected number of days until the plant's current weight reaches the Target Dry Weight. Computed from the rolling average daily weight loss across all `weight_log` entries.

**Active Growspace**
A growspace with `total_plants > 0`, regardless of `PlantStage`. A growspace in `dry` or `cure` mode still counts as active if plants are present. An empty growspace (no plants at all) is inactive.

## Drying Thresholds (Constants)

| Threshold | Value | Source |
|-----------|-------|--------|
| Target dry weight ratio | 25% of wet weight | Standard cannabis drying science |
| Cure-ready moisture | ≤ 12.0% | Branch-snap test equivalent |

## Service API

Data entry for drying observations is done via **service calls**, not HA helper entities (`input_number`). This is consistent with all other data-entry patterns in this integration. Services: `log_drying_weight`, `log_moisture_reading`.

## Service Facade Architecture

All external callers (sensors, websocket handlers, config flow handlers, service handlers) must access the coordinator exclusively through `coordinator.services.*`. Direct access to `coordinator.strain_library`, `coordinator.nutrient_manager`, `coordinator.notification_manager` from outside the coordinator is forbidden.

`coordinator.services` is a **ServiceFacade** container that exposes four domain sub-facades:

- `coordinator.services.growspaces` — growspace CRUD, subareas, irrigation, drain/water tracking, tank trackers
- `coordinator.services.plants` — plant lifecycle (clone, harvest, stage transitions), watering, IPM, training, drying
- `coordinator.services.config` — nutrient presets, IPM presets, EC ramp curves, strain library
- `coordinator.services.notifications` — notification settings and timed notifications

Infrastructure methods (`save`, `request_refresh`, `fire_event`, `add_timeline_note`) live on the container itself.

## Sensor Entities

Each computed drying metric is a distinct HA sensor entity:
- `DryingWeightSensor` — state: current weight; attributes: `weight_lost_pct`, `days_to_target`
- `DryingMoistureSensor` — state: current moisture percent
- `DryingReadyForCureSensor` — `BinarySensorEntity`; `on` when latest moisture ≤ 12.0%

## GrowMaster

**GrowMaster**
The AI advisor growers interact with to monitor and manage their cultivation. Accessible via the GrowMaster dialog, which has three panels: Chat (real-time conversation with the AI agent), Briefing (latest scheduled health summary), and Inbox (unresolved triage alerts). GrowMaster is backed by any HA conversation agent the grower configures; it is not a specific AI model.

**AI Briefing**
A scheduled health summary of one or more growspaces generated by GrowMaster. Triggered on a configurable interval or when nominated trigger entities change state. When GrowMaster is unavailable or disabled, falls back to a Bayesian-only summary. There is at most one current briefing per coordinator instance; new briefings replace the previous one.

## Alert Monitor

**Alert Monitor** (`alert_monitor.py`)
Listens for off→on transitions on Bayesian binary sensors (`stress`, `mold`) and creates persistent [[Triage Alert]] records. Stores records internally using a private storage dict; emits a public wire format via `_serialize_alert()` for all WebSocket responses. These two formats must never be conflated.

**Alert Monitor — internal storage format**
Private dict stored in `growspace_manager.ai_alerts`. Fields: `alert_id` (UUID), `alert_type` (`"stress"` | `"mold"`), `timestamp` (ISO-8601 string), `resolution_notes` (string | null), plus `growspace_id`, `bayesian_reasons`, `bayesian_probability`, `ai_reasoning`, `resolved`.

**Alert Monitor — wire format**
Public contract emitted by `_serialize_alert()` and consumed by the card's `TriageAlertSchema`. Fields differ from storage: `id` (renamed from `alert_id`), `type` (renamed from `alert_type`), `timestamp` (Unix epoch int, converted from ISO string), `resolution_note` (singular, renamed from `resolution_notes`), plus a computed `severity` field absent from storage.

**Triage Alert Severity**
Computed field added at serialization time. Maps `alert_type` to `severity`:
- `"stress"` → `"danger"` — plant stress is happening now, requires immediate action
- `"mold"` → `"warning"` — mold conditions are favorable (probabilistic), warrants watching
