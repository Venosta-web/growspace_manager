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

**Lifecycle Timestamp**
The recorded moment a Plant entered a stage: the `seedling_start`, `mother_start`, `clone_start`, `veg_start`, `flower_start`, `dry_start`, `cure_start` fields on `Plant`. Represented end-to-end as a timezone-aware **ISO 8601 datetime string** (date *and* time), never date-only — see [[ADR-0013]]. The model fields are typed `str | None` and store the ISO string; readers normalise via `parse_date_field` (which promotes any legacy date-only value to midnight-local on read). All write sites — create, stage transitions, cloning, WebSocket update — route through the `to_lifecycle_timestamp()` writer in `domain/date_logic.py`, the single owner of the representation: it preserves a supplied time or defaults to `dt_util.now()` and always returns an ISO string. Distinct from `WeightEntry`/`MoistureEntry` `date` fields (drying observations), which remain date-only.

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

**Water Usage Cycle**
The period over which cumulative water consumption is tracked for a growspace. Begins on `cycle_start_date` (set when the grower calls `reset_water_tracking`) and accumulates until the next reset. `WaterUsageSensor` reports total liters since `cycle_start_date` as its primary value.

**Tank-Derived Water Mode**
The implicit fallback mode for water consumption tracking. Active when a growspace has at least one tank with `volume_liters` configured and no `irrigation_flow_sensors` or `drain_volume_sensors` are set. In this mode, `WaterUsageSensor` derives cumulative consumption by summing events from all qualifying `TankWaterTracker` instances since `cycle_start_date`, rather than reading from `WaterUsageData`. The `reset_water_tracking` service advances `cycle_start_date` in both modes; `TankWaterHistory` is never cleared on reset.

The growspace view model payload includes `water_usage.liters_today` (sum of `TankWaterTracker.get_total_liters_today()` across all qualifying tanks) so the frontend chip can display today's consumption without reading from the HA sensor entity. The `growspace_manager/get_tank_water_history` WebSocket command returns pre-bucketed consumption data (aggregated across all qualifying tanks) for the frontend [[Tank Water Chart]].

**Crop Steering Phases**
The four phases of `VWCIrrigationCoordinator`'s crop-steering loop, derived each minute from the current time and soil VWC reading: `P0` (Activation, immediately after lights-on), `P1` (Ramp Up, watering until `target_vwc_percent` is reached), `P2` (Maintenance, pulse watering when VWC drops below the maintenance trigger), and `P3` (Dry Back, no watering — spans the dark period and any post-`p2_stop` window). The active phase is exposed to the frontend via `IrrigationConfig.active_steering_phase` using a collapsed `p1`/`p2`/`p3` mapping (P0 collapses into `p1`).

**Crop Steering Phase Boundaries**
The four datetimes (`lights_on`, `p0_end`, `p2_stop`, `lights_off`) for a given calendar day that delimit the Crop Steering Phase windows. Computed by `_phase_boundary_times()` from `IrrigationStrategy.lights_on_time`/`detected_lights_on_time`, `p0_duration_minutes`, `p2_stop_before_lights_off_minutes`, and the growspace's day-length config (`flower_day_hours`/`veg_day_hours`, defaulting to 12). Returned as a `SteeringPhaseBoundaries` dataclass and used both to determine the current phase (`_determine_time_period`) and to project the next shot window (`projected_shot_window`).

**Dryback**
The decrease in substrate volumetric water content from a local peak to the following trough, always expressed in **absolute VWC percentage points** (peak − trough; a drop from 55% to 45% is a 10% dryback) — never as a ratio relative to the peak. This is the single canonical convention across backend logic, dialogs, and charts; it matches how `maintenance_dryback_percent` already behaves (P2 trigger = target − dryback) and the convention growers quote. Any formula computing dryback relative to peak is wrong.

**SubstrateTracker**
The per-growspace component that turns raw soil-moisture and pore-EC readings into measured substrate events, following the [[Tank-Derived Water Mode]] tracker precedent: fed live by the crop-steering minute loop, persisting a rolling event history on the growspace model so derived metrics survive restarts. The recorder remains chart-only — automation and analytics never query it. v1 produces three measured metrics: [[Overnight Dryback]], [[In-Cycle Dryback]]s, and the [[EC Trend]]. Field-capacity detection is explicitly deferred.

**Overnight Dryback**
The headline daily [[Dryback]]: from the settled VWC peak after the day's **last** irrigation shot to the minimum VWC before the **next** day's first shot (shot-to-shot, not clock-bounded). Lights-off/lights-on times do not bound the window — when Auto-Advance ends shots early, the dryback window starts at the last shot, hours before lights-off. On a day with zero shots, the peak falls back to the lit-period maximum.

**In-Cycle Dryback**
A micro [[Dryback]] between two consecutive P2 shots: the settled peak after one shot to the trough immediately before the next. The set of a day's In-Cycle Drybacks yields shots/day context and the average P2 dryback, and validates that the configured maintenance trigger behaves as intended.

**EC Trend**
The direction of pore EC over the current day — `rising`, `stable`, or `falling` — computed from actual pore-EC sensor readings by the [[SubstrateTracker]]. Replaces the previously hardcoded `"stable"` placeholder in the steering score.

**Steering Mode**
The grower's declared steering intent for a growspace: `vegetative`, `generative`, or `balanced`, plus a third "undeclared" state (`declared_steering_mode` is `None` until the first stamp — distinct from an explicit `balanced`). Selecting a mode is a **preset stamp**: it applies the mode's recommended setpoints into the ordinary editable strategy fields, one time — the grower may tweak any field afterwards and the coordinator only ever reads the explicit fields, never the mode. The stamp writes `maintenance_dryback_percent`, `p2_stop_before_lights_off_minutes`, the P1/P2 shot size + interval pair for the **active** [[Shot Sizing Mode]] only (seconds *or* percent, never both), and the [[Pore EC Target Band]]. It deliberately does **not** write `target_vwc_percent` (a substrate/strain saturation property, not a steering-direction lever). Preset values vary by media × mode for the percent/dryback/p2-stop/EC fields; the raw seconds defaults vary by mode only (they are pump-dependent crude fallbacks). `soil` gets deliberately gentle, near mode-independent presets. The stamp is **not** idempotent-by-mode: re-selecting the already-declared mode re-stamps (a deliberate "reset to this mode's defaults", discarding hand tweaks). Each stamp writes one logbook entry naming the mode and media. Exposed via the `apply_steering_mode` service and a matching WS command; the server owns the preset table, the client only names the mode. The mode is also stored as the **declared intent**, so the measured steering score can be reported against it ("intended generative, substrate reads vegetative"). Distinct from the **Measured Classification** below, which is a measurement, not a setting.

In the wire contract the declared intent has a **single source of truth**: the `declared_steering_mode` field on the irrigation strategy, which the growspace view-model payload carries at `irrigation.irrigation_strategy.declared_steering_mode` (and the `apply_steering_mode` WS command echoes back under the same key). It is deliberately **not** mirrored onto the crop-steering sensor — the sensor carries only the derived readout. The crop-steering sensor attribute previously named `steering_mode` (the score-derived classification) is renamed to `measured_classification`, and the deviation readout is the sensor attribute `intent_deviation`; nothing in the payload uses the bare term `steering_mode` for two different things.

**Measured Classification**
The `vegetative` / `balanced` / `generative` bucket derived from the live steering score by fixed thresholds (`score > 0.3` → generative, `score < −0.3` → vegetative, else balanced). A read-only *measurement* of how the substrate is actually behaving — never a setting and never written back to the strategy. Exposed as the `measured_classification` sensor attribute. [[Intent Deviation]] is exactly the comparison of this against the declared [[Steering Mode]].

**Intent Deviation**
A directional readout comparing the [[Measured Classification]] against the declared [[Steering Mode]] along the ordered axis `vegetative (−1) → balanced (0) → generative (+1)`. Exposed as the crop-steering sensor attribute `intent_deviation`, one of: `on_target` (buckets match), `more_generative` (substrate reads more generative than declared), `more_vegetative` (substrate reads more vegetative than declared), or `null` when no intent has been declared (`declared_steering_mode` is null — nothing to deviate from) or there is no current VWC reading (no measurement to compare). It is a comparison of a measurement against a setting; it never bends the score toward the declared mode, and the score itself stays an absolute −1…+1 measurement. The card composes any human-readable sentence by joining `intent_deviation` and `measured_classification` (sensor attributes) with `declared_steering_mode` (strategy payload).

**Substrate Profile**
Per-growspace description of the growing medium: media type (`coco`, `rockwool`, `soil`) and **liters per pot**. Total substrate volume is *liters per pot × live plant count* — shot sizing is therefore constant **per-plant dosing**: when plants are removed mid-grow, total shot volume scales down automatically while each remaining plant's dose stays constant. Any live-count change that alters computed shot volume is recorded in the logbook. At zero plants the growspace has no irrigation demand: crop steering suspends shots (loop stays alive, phase reports idle).

**Shot Sizing Mode**
An explicit per-growspace choice between two ways of expressing steering shot size: **Seconds Mode** (the default, today's behavior — raw pump seconds, works with any pump and no extra config) and **Volume Mode** ([[Volume-Based Shot Sizing]], opt-in). Volume Mode is never auto-activated by the mere presence of its prerequisites; the grower switches modes deliberately. Seconds Mode is a permanently supported first-class mode, not a legacy fallback.

**Volume-Based Shot Sizing**
The professional convention for expressing irrigation shot size as a **percentage of substrate volume** (e.g. "P2 shots of 4%") rather than raw pump seconds. An opt-in [[Shot Sizing Mode]], selectable only when both a [[Substrate Profile]] and a pump flow rate are configured; the backend converts percent → ml → pump seconds. [[Steering Mode]] presets carry both percent values and seconds defaults, stamping whichever matches the active mode. P1 and P2 each have their own shot size and interval — the pair is a steering lever in its own right (fewer/larger = generative).

**Sensor-Gated Capability**
The principle governing every crop-steering feature: each capability gates on **its own minimal prerequisites** and nothing else. A VWC sensor alone enables the full phase loop, dryback tracking, and the steering score; pore-EC sensors additionally enable [[EC Trend]] and [[EC Modulation]]; flow rate + [[Substrate Profile]] additionally enable Volume Mode; drain readings enable the runoff-EC halt. A grower with partial sensors gets every feature their sensors support — no feature bundle requires the full sensor suite, and adding a capability never degrades a growspace that lacks its prerequisites.

**EC Modulation**
Opt-in, bounded adjustment of P2 shot volume driven by measured pore EC versus the [[Pore EC Target Band]]: pore EC above the band scales shots up (inducing runoff to flush), below the band scales them down (stacking EC). This is the only EC actuation in the system — there is no dosing hardware; feed EC remains hand-mixed. The modulation factor is bounded (roughly ±25%) and never overrides safety caps.

**Pore EC Target Band**
An explicit min/max pore-EC range on the irrigation strategy that [[EC Modulation]] steers toward. Stamped by [[Steering Mode]] presets (generative modes stack higher) and freely editable afterwards. Deliberately distinct from the per-stage **feed** EC target ranges (`ECTargetRange`) — pore EC legitimately runs above feed EC when stacking, so the two must never be conflated.

**Shot Size Composition**
The effective steering shot volume is `base × VWC feedback factor × EC modulation factor`, then subject to safety caps. The two factors are computed independently, may pull in opposite directions (partially cancelling — physically sensible), and are both exposed in diagnostics so any fired shot is explainable.

**Dynamic VWC Steering Shot**
An irrigation shot in the VWC crop-steering loop whose duration is dynamically adjusted (clamped between 50% and 100% of standard duration) based on the VWC feedback scale factor calculated from the substrate's response to the previous shot.

**VWC Feedback Scale Factor**
The scalar multiplier applied to the next steering shot's duration, calculated by comparing the actual volumetric water content (VWC) increase from the last settled shot against the expected target increase. Resets to 1.0 at lights-on and during the P1-to-P2 phase transition.

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

## Circulation Fan Controller

**CirculationFanController**
An optional per-growspace subsystem that drives all `circulation_fan_entities` to a computed speed percentage on a fixed tick (default 10 s). Speed is always clamped to the user-defined `[min_speed, max_speed]` range. The controller has two independent layers that are always composed: a **Regulation Layer** and a **Dynamic Wind Layer**.

**Regulation Layer**
Exactly one regulation mode is active at a time: `humidity`, `temperature`, or `vpd`. Each mode uses linear mapping: below `(target − tolerance)` → `min_speed`; above `(target + tolerance)` → `max_speed`; inside the band → linearly interpolated. The grower configures `target` and `tolerance` per mode.

**VPD Mode Temperature Safety Override**
When regulation mode is `vpd`, two additional thresholds apply: `critical_temp_low` and `critical_temp_high`. If the temperature sensor reading breaches either threshold, the override activates: high-temp breach drives fans to `max_speed`; low-temp breach drives fans to `min_speed`. The override remains active until the temperature returns within bounds plus `critical_temp_hysteresis`. While active, the override replaces the VPD regulation output entirely.

**Dynamic Wind Layer**
Runs in parallel with the Regulation Layer regardless of mode. Adds a sinusoidal ±offset to the regulation speed: `offset = wind_amplitude_pct × sin(2π × elapsed_seconds / wind_period_seconds)`. The final speed after adding the offset is clamped to `[min_speed, max_speed]`. The grower configures `wind_period_seconds` (default 60) and `wind_amplitude_pct` (default 10).

**CirculationFanConfig**
The dataclass stored on `EnvironmentConfig` that holds all fan controller settings: `enabled`, `regulation_mode`, `min_speed`, `max_speed`, per-mode `target` and `tolerance`, `critical_temp_low`, `critical_temp_high`, `critical_temp_hysteresis`, `wind_enabled`, `wind_period_seconds`, `wind_amplitude_pct`, `stage_vpd_enabled`, `stage_vpd_overrides`. Absent or `enabled=False` means no fan control.

**Stage-Aware VPD Mode**
An optional sub-mode of VPD regulation (`stage_vpd_enabled = True`) that resolves the effective VPD target from the active plant stage and time of day (day/night) rather than the static `vpd_target`. Defaults for all nine stages (`seedling`, `clone`, `mother`, `veg`, `flower_early`, `flower_mid`, `flower_late`, `dry`, `cure`) are defined in `FAN_VPD_STAGE_DEFAULTS`. Falls back to `vpd_target` when the growspace has no plants or the current stage is not in the lookup table.

**Stage VPD Overrides**
A sparse dict stored on `CirculationFanConfig` as `stage_vpd_overrides`. Keyed by stage name (the string value of `PlantStage`, e.g. `"veg"`, `"flower_early"`); each entry is `{"day": float, "night": float}`. Only stages the user has explicitly edited are present — absent stages resolve to `FAN_VPD_STAGE_DEFAULTS`. Deleting all entries (or an individual entry) restores the default for that stage. Validation rules: values must be in the range 0.1–3.0 kPa; unknown stage keys are rejected (not silently dropped); each entry must contain both `"day"` and `"night"` keys — a half-specified entry is invalid.

**Fan Speed Composition**
`final_speed = clamp(regulation_speed + wind_offset, min_speed, max_speed)` where `regulation_speed` is the output of the active regulation mode (or the safety override when active), and `wind_offset` is the sine term (zero when `wind_enabled=False`).

**VPD Optimal Overrides**
A per-growspace sparse dict stored on `EnvironmentConfig` as `vpd_optimal_overrides`. Keyed by user-facing stage name (`"seedling"`, `"clone"`, `"mother"`, `"veg"`, `"flower_early"`, `"flower_mid"`, `"flower_late"`, `"dry"`, `"cure"`); each entry is `{"day": {"low": float, "high": float}, "night": {"low": float, "high": float}}`. Only stages the user has explicitly edited are present — absent stages fall back to `VPD_OPTIMAL_THRESHOLDS`. Applies to the **standard sub-stage only**: the acclimation phases for `seedling` and `clone` (`BayesianStage.SEEDLING`, `BayesianStage.CLONE`) always use hardcoded defaults regardless of any override. Drives the "not optimal" chip and the optimal conditions binary sensor. Distinct from `stage_vpd_overrides` on `CirculationFanConfig`, which controls the fan regulation target, not Bayesian evaluation. Validation rules: `0.1 ≤ low < high ≤ 3.0` kPa; unknown stage keys are rejected; each entry must contain both `"day"` and `"night"` with both `"low"` and `"high"` — a partial entry is invalid. Configurable per-growspace via the **VPD Targets** tab in the config dialog.

**StageEnvironmentalTargets**
A class in `domain/environmental_targets.py` that encapsulates all stage-interpolated environmental threshold lookups behind a typed interface. Constructed from a `(stage_a, stage_b, factor)` triple taken from `StageClassification`. Provides five methods: `vpd_stress_band(time_of_day, env_config)` → `VpdStressBand` (evaluator path — direct subscript, raises on missing stage); `vpd_optimal_band(time_of_day, overrides)` → list of `(low, high, prob)` bands with per-growspace `vpd_optimal_overrides`; `humidity_band(env_config)` → `HumidityBand`; `co2_optimal_band()` → list of `(low, high, prob)` bands; `vpd_display_targets()` → `VpdDisplayTargets` (display path — `.get` with veg fallback, distinct from the evaluator path). The two VPD paths must not be unified: `vpd_stress_band` raises on a missing key (Bayesian evaluator contract), while `vpd_display_targets` silently falls back to veg thresholds (frontend display contract). Private helpers `_hum_limits`, `_get_optimal_limits`, `_ACCLIMATION_STAGES`, `_OVERRIDE_BAYESIAN_TO_KEY` live in the same module.

**Evaluation Snapshot**
An immutable record published by each Bayesian binary sensor (stress/mold/optimal) after every probability update, via `coordinator.services.notifications.report_evaluation()`. Fields: `growspace_id`, `sensor_type`, sensor name, `probability`, `threshold`, `is_on`, `reasons`, `sensor_states` (observation dict), `lights_on`, and the notification title/message precomputed for the triggered state. The snapshot is the **only** interface between Bayesian sensors and the notification subsystem: the Notification Manager stores the latest snapshot per `(growspace_id, sensor_type)` and never holds live sensor entity references (no attach/detach handshake). Light-flip cooldown is derived by the manager from consecutive snapshots' `lights_on` transitions, deduplicated per growspace — sensors do not call `trigger_cooldown`. The title/message text is frozen at snapshot time, which may be a few seconds older than the debounced batch-fire time; this is accepted. Notification message formatting (sorted reasons appended up to `MAX_NOTIFICATION_LENGTH`) is a pure function in `notifications/`, not a Notification Manager method. GrowAssistant AI enrichment of alert *records* lives in `AlertMonitor._async_enrich_with_ai` (gated by `CONF_AI_AUTO_ALERTS`); the sensor never had a live AI path — its old `_send_notification` GrowAssistant copy was already unreachable and was removed.

**EnvironmentState Assembler**
A class in `domain/` (following the [[StageEnvironmentalTargets]] precedent) that builds an `EnvironmentState` from raw HA entity states. Constructed with injected callables (`get_state`, `get_growspace`, `get_plants`) plus the growspace's `EnvironmentConfig`; each Bayesian sensor owns its own assembler (`assemble()` is uncached, so a shared per-growspace instance would dedupe no reads). A single `assemble()` call returns an `AssembledEnvironment` holding both the `EnvironmentState` and the flat observation dict, derived from one read pass so the two can never diverge. Owns: multi-sensor aggregation (average) for temp/humidity/VPD, VPD fallback calculation with LST offset (zeroed for dry/cure growspaces), CO2/soil-moisture/substrate-temp reads, device-state derivation (fans-off AND logic, dehumidifier/humidifier-on OR logic, exhaust/humidifier max value), lights-on OR logic, and growth-stage day counts. Pure — no side effects: light-flip transition detection lives in the Notification Manager (see [[Evaluation Snapshot]]), not here. Unit-testable with plain lambdas (see `tests/domain/test_environment_state_assembler.py`).

**Notification Settings**
A dict of six timing/cooldown parameters stored in `config_entry.options["notification_settings"]`. Keys: `critical_cooldown_minutes`, `warning_cooldown_minutes`, `recovery_cooldown_minutes`, `escalation_delay_minutes`, `min_stress_duration_seconds`, `warning_persistence_minutes`. Each value falls back to the corresponding hardcoded constant in `const.py` when absent, so the dict may be partially populated or omitted entirely without breaking behaviour. Exposed as a top-level key in the global coordinator data payload and written atomically via the `save_notification_settings` WebSocket command.

**Timed Notification**
A user-configured reminder that fires on a specific day of a plant's lifecycle stage. Stored as a list in `config_entry.options["timed_notifications"]`. Each entry has `id` (UUID), `message`, `trigger_type`, `day`, and `growspace_ids`. Managed by `NotificationSettingsManager`. Exposed as a top-level key in the global coordinator data payload alongside Notification Settings.
