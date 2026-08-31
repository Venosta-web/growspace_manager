# Growspace Manager — Domain Glossary

## Core Concepts

**Growspace**
An enduring cultivation venue that exists independently of any one crop or operating episode. Its Grow Runs partition its historical activity without replacing its identity.
_Avoid_: run, crop, batch

**Grow Run**
A bounded, growspace-local operating episode whose records belong to one enduring Growspace. A Growspace has at most one active Grow Run; runs never overlap, their boundaries are explicitly started and completed, and a Plant may participate in different runs as it moves between growspaces.
_Avoid_: Grow Cycle, reporting window, harvest batch

**Run Participation**
One half-open interval during which a Plant occupied the Growspace of an active Grow Run. Participation opens and closes from actual Plant movement or Run boundaries; re-entry creates another interval rather than rewriting the earlier one.
_Avoid_: run membership, current growspace

**Run Participant**
A Plant with at least one Run Participation in a Grow Run. Each Plant counts once in the Run's participant total even if it has multiple participation intervals.
_Avoid_: starting plant, current plant

**Harvest Source Run**
The active Grow Run in the source Growspace when a Plant transitions into dry. That Run owns the Plant's later harvest outcome updates; without an active source Run, the outcome is unattributed.
_Avoid_: dry run, current run

**Harvest Window**
The local-date interval from the first through the last Harvest Source Plant entering dry. It is absent for a Grow Run with no harvest outcomes and displays as one date when both boundaries fall on the same day.
_Avoid_: harvest date, run completion date

**Yield** _(Grow Run)_
The sum of final dry weights from a Grow Run's Harvest Source Plants. It remains incomplete until every contributing Plant has a dry weight or is explicitly recorded as producing no usable yield; wet and trim weights are secondary outcomes.
_Avoid_: wet yield, projected yield

**Yield per Harvest Source Plant**
A Grow Run's Yield divided by the number of its Harvest Source Plants. It excludes Run Participants that never became harvest sources so replacements and non-harvested Plants do not distort the result.
_Avoid_: yield per participant, yield per starting plant

**No Usable Yield**
An explicit Harvest Source Plant outcome recording zero usable dry Yield together with a grower-supplied reason. It remains in the Harvest Source Plant denominator and loss counts; an absent dry weight remains unknown rather than zero.
_Avoid_: missing yield, zero-filled weight

**Average VPD Deviation**
The time-weighted mean absolute distance between observed VPD and the midpoint of the applicable target band, with that target resolved from the observation's Plant stage, transition blend, and day/night state. Time in the target band is a separate metric.
_Avoid_: average VPD, signed VPD error

**Water Applied**
Irrigation delivered to Plants in a Grow Run's Growspace through automated or recorded manual watering. Tank refills, evaporation, leaks, and unrelated reservoir loss are excluded, and each application has one measurement source so inferred and direct readings cannot double-count it.
_Avoid_: tank depletion, water loss, reservoir use

**Water Productivity**
A Grow Run's dry Yield in grams divided by its Water Applied in litres. Total Water Applied is neutral context; Water Productivity is the comparable efficiency outcome.
_Avoid_: water efficiency percentage, lower water use

**Run Energy**
Electricity consumed during a Grow Run's half-open operating interval by equipment attributed to its Growspace. It prefers positive deltas from cumulative energy sensors, may explicitly fall back to integrated power, detects meter resets, and is incomplete below 80 percent Metric Coverage.
_Avoid_: current power, energy baseline

**Energy Accounting Boundary**
The non-overlapping meter set whose consumption constitutes one Growspace's Run Energy. It is either one whole-Growspace meter or an explicit sum of non-overlapping device meters; a shared multi-Growspace meter requires an explicit allocation rule.
_Avoid_: all energy sensors, shared meter guess

**Energy Productivity**
A Harvest Source Run's dry Yield in grams divided by its Growspace-local Run Energy in kilowatt-hours. Energy used by downstream drying or curing Growspaces belongs to their own Runs rather than this metric.
_Avoid_: whole-crop energy efficiency, power efficiency

**Derived Run Metric**
A comparison metric calculated from other Run metrics. It exists only when every input is complete and its denominator is positive; otherwise it reports the missing prerequisite rather than a provisional value.
_Avoid_: estimated final metric, partial efficiency

**Comparison Direction**
The increase, decrease, or equality of one Run metric relative to another. Direction is neutral for totals and receives an improvement judgment only for metrics with an agreed monotonic goal.
_Avoid_: improvement arrow, score

**Mold-Risk Episode**
One inactive-to-active transition of the Growspace's mold-risk condition during a Grow Run. It counts once regardless of later resolution or notification delivery; a condition already active at Run start counts only if it clears and begins again.
_Avoid_: unresolved mold alert, mold notification

**Metric Coverage**
The proportion of a metric's required observation interval supported by valid data. Missing observations are never zero; time-series metrics below their required coverage are incomplete and receive no comparison direction.
_Avoid_: data availability flag, zero fill

**Metric Definition Version**
The identity of the calculation rules used to freeze one comparison metric. Values with different definition versions are not directly comparable and historical values are never silently rewritten.
_Avoid_: schema version, app version

**Metric Source Segment**
A contiguous portion of a Grow Run metric produced from one compatible sensor source and unit. Compatible segments may be combined, while uncovered gaps reduce Metric Coverage and overlapping or incompatible sources require explicit resolution.
_Avoid_: sensor history, merged source

**Observation Validity Window**
The maximum interval for which one time-series observation may represent a continuing value, defaulting to three times the sensor's expected update interval subject to a configurable cap. Time after that window is uncovered rather than filled from a stale value.
_Avoid_: sample interval, forward fill

**Completed Grow Run**
A Grow Run whose operating interval has ended but which may still receive linked post-harvest outcomes.
_Avoid_: closed run, finalized run

**Finalized Grow Run**
A completed Grow Run whose comparison facts are frozen and remain readable even if its Growspace or participating Plants are later removed.
_Avoid_: completed run, archived growspace

**Run Reopening**
The audited return of a Finalized Grow Run to Completed status so a grower can correct its facts before finalizing it again. It requires a grower-supplied reason.
_Avoid_: edit finalized run, silent correction

**Voided Grow Run**
A retained Grow Run declared invalid and excluded from comparisons. Only an empty Run with no attributed activity may instead be discarded entirely.
_Avoid_: deleted run, cancelled run

**Imported Run**
A historical Grow Run created directly as Finalized from a confirmed, otherwise unsaved import draft containing manually supplied summary facts. It is visibly marked as imported and participates in comparisons only for complete, definition-compatible metrics; unverifiable metrics remain incomplete.
_Avoid_: reconstructed run, inferred run

**Run Comparison**
A two-column comparison of exactly two Finalized Grow Runs belonging to the same Growspace. It defaults to the newest Run and its predecessor; cross-growspace and multi-Run comparison are outside the initial model.
_Avoid_: growspace comparison, live comparison

**Active Run Sensor**
The single lightweight Home Assistant entity that exposes one Growspace's current Grow Run for dashboards and automations. Its state is the active Run Sequence Number or `none`, with compact identity, label, start, duration, participant-count, and Run Revision attributes; detailed history remains behind the integration API.
_Avoid_: run entity collection, historical run sensor

**Grow Run State Graph**
The allowed lifecycle transitions `Active → Completed → Finalized`, `Finalized → Completed` through Run Reopening, and `Active | Completed → Voided`. Reopening never resumes the operating interval, Voided is terminal except Purge Run History, and only an activity-free Active Run may be discarded.
_Avoid_: planned run, resumed run

**Grow Run View**
The dedicated product surface for a selected Grow Run's overview, participants, performance, history, and comparison. It replaces the unversioned aggregate Grow Report as the canonical reporting surface.
_Avoid_: grow report, logbook report

**Harvest Attribution Correction**
An audited assignment of a Plant's harvest outcome to a Completed Harvest Source Run after the Plant entered dry without the intended Run active. Correcting a Finalized Grow Run requires Run Reopening first.
_Avoid_: manual yield edit, silent run assignment

**Run Boundary Correction**
An audited transactional change to one or more adjacent Grow Run boundaries that previews and transfers every affected fact and participation interval without creating overlap. Every affected Finalized Grow Run must be reopened first.
_Avoid_: date edit, independent boundary update

**Activity Fact**
An immutable, uniquely identified record emitted durably by a successful cultivation mutation and projected idempotently into Run history and summaries. Projection may retry, but the source mutation does not report success until its fact is durable.
_Avoid_: log message, Run projection

**Run Opening Baseline**
The relevant condition and equipment states captured at Grow Run start. Conditions already active are carried-in context rather than new episodes; only a later clear-to-active transition increments the Run's episode count.
_Avoid_: opening alert, initial event

**Grow Run Lifecycle Event**
An auditable event emitted when a Grow Run starts, completes, finalizes, reopens, or is voided, or when harvest attribution is corrected. Reopen, void, and correction events carry the grower-supplied reason required by their corresponding authenticated command.
_Avoid_: UI action log, card event

**Run Configuration Timeline**
The Growspace's cultivation-affecting configuration at Run start plus each later change to environmental targets, lighting, irrigation, sensor assignment, equipment control, or dimensions. Cosmetic dashboard and card settings are excluded.
_Avoid_: final configuration, card history

**Run Activity Timeline**
The durable sequence of Growspace Manager cultivation events attributed to a Grow Run, including Plant movement and lifecycle changes, watering, IPM, alerts, configuration changes, notes, harvest actions, corrections, and Run lifecycle events. Arbitrary Home Assistant state changes and raw telemetry are excluded.
_Avoid_: HA history, logbook query

**Run Media**
An image explicitly attached to a Grow Run as cover, progress, problem, or harvest context. It follows Run retention and purge rules; ordinary camera history and incidental event media are not copied into the Run.
_Avoid_: camera history, automatic snapshot archive

**Participant Identity Snapshot**
The Plant name, Strain identity and name, and Phenotype identity and name retained with a Run Participant. Corrections before finalization update it; later source renames do not rewrite a Finalized Grow Run.
_Avoid_: current plant name, live strain lookup

**Run Metadata**
The editable descriptive label, tags, goals, and retrospective notes of a Grow Run. Audited metadata edits do not require Run Reopening because they do not change identity, boundaries, attribution, or comparison facts.
_Avoid_: run facts, metric annotations

**Run Lifecycle Suggestion**
A dismissible prompt to start, complete, or finalize a Grow Run based on observed cultivation activity and outcome readiness. It never changes Run state without an explicit authorized command.
_Avoid_: automatic run transition, lifecycle automation

**Live Run Metrics**
The provisional metrics of an Active Grow Run, recalculated as facts arrive and excluded from historical comparison judgments.
_Avoid_: finalized metrics, projected yield

**Pending Run Metrics**
The provisional metrics of a Completed Grow Run while linked post-harvest outcomes may still arrive. They remain excluded from Run Comparison until finalization freezes them.
_Avoid_: final metrics, live metrics

**Run Completion Preview**
The confirmation view of a proposed completion boundary, duration, participation intervals that will close, Plants still present, missing harvest outcomes, coverage, attribution gaps, and retrospective note. Warnings do not block completion but require explicit acknowledgement when Plants or outcomes remain at risk.
_Avoid_: completion summary, automatic close

**Run Finalization Snapshot**
The exact values, canonical units, coverage, Metric Definition Versions, missing prerequisites, Participant Identity Snapshots, and configuration boundary frozen when a Grow Run is finalized. Incomplete finalization requires explicit acknowledgement and later factual changes require Run Reopening.
_Avoid_: current report, cached metrics

**Run Export**
A JSON or PDF representation of one selected Grow Run containing its identity, status, metadata, boundaries, timezone, participants, harvest outcomes, versioned metrics, configuration and activity timelines, audit history, and retained media references or thumbnails. A Finalized Grow Run exports its frozen snapshot.
_Avoid_: grow report export, live dashboard dump

**Run Lifecycle Authorization**
The permission rule that Growspace controllers may start, complete, finalize, and edit descriptive metadata, while only Home Assistant administrators may reopen, void, correct harvest attribution, or purge Run history.
_Avoid_: card-only permission, unaudited automation

**Run Audit Entry**
The immutable record of a lifecycle, correction, metadata, or purge command containing its timestamp, stable Home Assistant actor or automation/system origin, command identity, prior and resulting Run Revision, and any required reason.
_Avoid_: display-name history, logbook entry

**Run Timezone**
The IANA timezone frozen when a Grow Run starts and used for local dates, duration, daily summaries, and day/night interpretation. Canonical measurements remain grams, litres, kilowatt-hours, and kilopascals and convert only for display or export.
_Avoid_: current HA timezone, display timezone

**Unattributed Activity**
Valid cultivation activity that occurred in a Growspace while it had no active Grow Run. It does not belong to a Grow Run and is excluded from comparisons.
_Avoid_: default run, implicit run

**Unattributed Activity Ledger**
The Growspace-level facts and daily summaries retained while no Grow Run is active so a backdated Run can claim eligible activity transactionally. Its retention is configurable and defaults to 365 days; older history can only become an incomplete Imported Run.
_Avoid_: implicit run, Recorder history

**Run Sequence Number**
A monotonic display number allocated within one Growspace. Allocated numbers are never reused after a Run is voided or discarded, while the Run's opaque identity remains its stable reference.
_Avoid_: run ID, calendar run number

**Run Revision**
The monotonic version of one Growspace's Run collection used to reject stale lifecycle commands and atomically preserve the zero-or-one-active-Run rule.
_Avoid_: updated timestamp, run sequence

**Purge Run History**
The explicit administrator-authorized irreversible removal of a Finalized or Voided Grow Run. Plant or Growspace deletion never performs this purge implicitly.
_Avoid_: delete growspace, cascade delete, void run

**Strain Image Gallery**
The collection of images associated with a single phenotype. Stored as a JSON array on the phenotype record. Each entry has a path and optional crop metadata. One entry is designated as the Strain Thumbnail. A phenotype may have zero or more images.

**Strain Thumbnail**
The single designated image from a phenotype's Strain Image Gallery that is used everywhere a strain image is displayed (plant cards, library list, recommendations). If a phenotype has no images, the thumbnail is resolved from a sibling phenotype of the same strain: the `"default"` phenotype takes priority as the fallback source, then any other sibling in alphabetical order. This fallback is display-only — the phenotype's own gallery remains empty.

**Plant**
An individual cannabis plant tracked from seedling through cure. The atomic unit of all lifecycle, drying, and curing tracking. A "harvest batch" is not a separate concept — each plant is weighed and tracked individually.

**Plant Updated Date**
The calendar day on which a Plant was most recently mutated. Stored and emitted
through `updated_at` as an ISO 8601 date-only string (`YYYY-MM-DD`), never as a
datetime. Every write site routes through `plant_updated_date()` in
`domain/date_logic.py`, the single owner of this representation. Distinct from
the [[Lifecycle Timestamp]], which records the full timezone-aware moment a Plant
entered a lifecycle stage.

**Plant Layout**
The complete mapping of every Plant in one growspace to a unique grid cell within that growspace's current dimensions. A layout and any dimension change that affects its valid bounds are committed as one unit rather than as independently observable plant moves.

**Layout Revision**
A monotonically increasing identifier for a growspace's Plant Layout. Adding, removing, moving, swapping, or transplanting a Plant changes the affected layout's revision, allowing a stale complete-layout update to be rejected rather than overwriting newer positions. A repair that relocates Plants between growspaces advances the revision of every growspace it touches, and one that recreates a growspace resumes past the revision it discarded, so a repair can never be silently overwritten by a draft captured before it.
_Avoid_: plant version, layout timestamp

**Plant Layout Changed**
The single growspace-level event emitted after an atomic Plant Layout commit. It identifies the growspace and its new Layout Revision; it is not decomposed into independent plant-move or plant-swap events.
_Avoid_: plants moved, arrangement saved

**PlantStage**
The lifecycle phase of a Plant. The branching transition graph is `seedling → veg`, `clone → veg`, `veg → mother | flower`, `mother → veg | flower`, `flower → dry | veg` (Reveg), and `dry → cure`; `cure` is terminal. The `dry` and `cure` stages are fully-fledged lifecycle stages, not post-harvest metadata.

**Lifecycle Timestamp**
The recorded moment a Plant entered a stage: the `seedling_start`, `mother_start`, `clone_start`, `veg_start`, `flower_start`, `dry_start`, `cure_start` fields on `Plant`. Represented end-to-end as a timezone-aware **ISO 8601 datetime string** (date _and_ time), never date-only — see [[ADR-0013]]. The model fields are typed `str | None` and store the ISO string; readers normalise via `parse_date_field` (which promotes any legacy date-only value to midnight-local on read). All write sites — create, stage transitions, cloning, WebSocket update — route through the `to_lifecycle_timestamp()` writer in `domain/date_logic.py`, the single owner of the representation: it preserves a supplied time or defaults to `dt_util.now()` and always returns an ISO string. Distinct from `WeightEntry`/`MoistureEntry` `date` fields (drying observations), which remain date-only.

**Plant Lifecycle**
The pure, in-process owner of what stage one Plant is in and how it got there, implemented in `domain/plant_lifecycle.py`. It parses and validates [[Stage History]], reconstructs absent history once from legacy lifecycle dates, derives one [[Lifecycle Facts]] snapshot, and proposes [[Lifecycle Transition]] or [[Lifecycle Correction]] values without persistence, events, growspace moves, Home Assistant, or an implicit clock.

**Effective Date**
The explicit calendar date on which a proposed lifecycle change takes effect. It may be backdated to the current open interval's start, but never before it. Distinct from the [[Observed Date]], when the request is evaluated, and from the full [[Lifecycle Timestamp]] representation used by persistence writers.

**Observed Date**
The explicit calendar date on which lifecycle data or a transition request is evaluated. A transition whose Effective Date is after its Observed Date is rejected. Supplying this value, rather than reading a clock, keeps Plant Lifecycle deterministic.

**Stage History**
The ordered sequence of immutable half-open stage intervals (`[start, end)`), with exactly one current open interval at the end. Starts are chronological, intervals do not overlap, and adjacent stage identities must follow the PlantStage transition graph. Present malformed data is never silently replaced with legacy fields: the lifecycle reports [[Unknown Stage]] and [[Lifecycle Repair Warning]] values. Only absent history activates one-time reconstruction from legacy lifecycle dates.

**Unknown Stage**
The fail-closed Current Stage reported when Stage History cannot be trusted. It is not a persistable PlantStage and never participates in the transition graph; the grower must apply a Lifecycle Correction before another normal transition.

**Lifecycle Facts**
One internally consistent snapshot returned by `facts(on=...)`: [[Current Stage]], [[Current Stage Age]], [[Lifetime Stage Days]], and [[Cultivation Band]], all evaluated on the same explicit date.

**Current Stage**
The stage interval containing the Lifecycle Facts date. For a current snapshot this is the final open Stage History interval; invalid or uncovered history reports Unknown Stage.

**Current Stage Age**
Whole calendar days between the Current Stage interval's start and the Lifecycle Facts date. Day zero is the stage's Effective Date.

**Lifetime Stage Days**
The cumulative days a Plant has spent in each canonical stage, including repeated intervals such as veg before and after Reveg, up to the Lifecycle Facts date.

**Cultivation Band**
The stable age classification within the Current Stage: Seedling and Clone are Acclimating on days 0–6 and Established on day 7 onward; Flower is Early on days 0–20, Mid on days 21–41, and Late on day 42 onward. A separate adjacent-band interpolation hint is available in the three days before a boundary, but never changes the reported band identity early.

**Band Identity**
The [[Cultivation Band]] a Plant or growspace is currently in. It changes only at the band's actual age boundary; an adjacent-band interpolation hint blends numeric environmental targets without changing this identity early.

**Transition Blend**
A numeric ramp from one [[Current Stage]] into the next, distinct from interpolation between [[Cultivation Band]]s within one stage. Its reported stage changes to the destination at the ramp's midpoint; the seedling-to-veg ramp is the current example.

**Lifecycle Transition**
An immutable `Applied`, `NoChange`, or `Rejected` proposal. It carries before/after lifecycle values and facts, [[Compatibility Data]], and any Lifecycle Repair Event draft; applying persistence, moves, or events belongs to a separate effect shell.

**Lifecycle Correction**
An explicit repair proposal that replaces the ambiguous current interval, preserves the maximal trustworthy and graph-compatible earlier prefix, rebuilds Compatibility Data, and drafts a Lifecycle Repair Event. It requires the corrected stage, its start date, the correction date, and a non-empty grower reason.

**Lifecycle Repair Warning**
A machine-readable diagnosis produced for malformed, overlapping, nonchronological, future-dated, unknown-stage, or graph-invalid lifecycle data. Warnings fail lifecycle facts closed to Unknown Stage rather than activating a legacy fallback.

**Lifecycle Repair Event**
The immutable event draft produced by Lifecycle Correction, recording the prior/corrected stage, correction and stage-start dates, grower reason, discarded interval count, and warning codes. The domain module drafts it; an outer shell decides whether and where to publish it.

**Compatibility Data**
The lifecycle-owned projection for legacy Plant consumers: the shadow `stage`, latest per-stage `*_start` values, and Stage History. It is rebuilt from trusted intervals after every Applied transition or Lifecycle Correction so legacy fields cannot disagree with the domain result.

**Current Stage Resolution**
The read path's single rule for reporting [[Current Stage]], implemented in `domain/current_stage.py` and shared by the plant view model the card renders, the plant sensor's state and `stage` attribute, nutrient-preset stage matching, environmental stage-day assembly, and feed-EC week selection. Stored [[Stage History]] wins whenever it parses; older Plants without history are reconstructed by the [[Plant Lifecycle]] module from legacy lifecycle dates, while malformed present history fails closed to [[Unknown Stage]]. There is no separate growspace/date heuristic. Consequences: after a Reveg the stale `flower_start` no longer outranks the newer veg interval, and a promoted clone still sitting in the clone growspace reads as veg rather than taking a special-growspace shortcut.
_Avoid_: displayed stage, computed stage

**Cultivation Band Resolution**
The read path's single rule for reporting a Plant's [[Cultivation Band]] and [[Current Stage Age]], implemented in `domain/cultivation_band.py` on top of [[Current Stage Resolution]] and shared by every environmental consumer: the dehumidifier and humidifier (`determine_coordinator_stage`), the circulation and exhaust fans (`resolve_stage_vpd_target`), and the Bayesian VPD and humidity evaluation (`classify_stages`, `_determine_stage_key`). All of them classify flower through `cultivation_band_for`, so day 21 is Mid Flower and day 42 is Late Flower everywhere at once; the strict `> 21` / `> 42` comparisons that left the actuators a band behind the Bayesian evaluation are gone, and the boundary constants that let them drift no longer exist outside the lifecycle module. A growspace takes the most demanding band across its Plants, and an empty growspace still reports veg. Seedling and Clone acclimation is deliberately not routed here: `classify_stages` keeps its own four-day blend between `ACCLIMATION_START_DAYS` and `ACCLIMATION_END_DAYS`, which is tuned against the acclimation humidity and VPD targets.
_Avoid_: growth stage, granular stage, flower band

**Current Stage Age Gating**
The rule that a "day N of a stage" question is answered by [[Current Stage Age]], never by [[Lifetime Stage Days]]. Nutrient-preset `min_days_in_stage` eligibility and timed-notification day-of-stage triggers both read the current open interval, so a Plant on its second veg stint after a Reveg is evaluated on days since that Reveg. A day-of-stage trigger has no answer at all while the Plant is in a different stage, and stays silent rather than firing off a stint the Plant has already left.
_Avoid_: days in stage, stage days

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

**Aggregate Water Use**
The single canonical figure for how much water a growspace has consumed, the one number every consumer (`WaterUsageSensor`, briefing KPI, AI context, the frontend [[Tank-Derived Water Chip]]) reports. Composed from three [[Water Source]]s under one rule: **manual watering plus exactly one measurement source** — [[Tank-Derived Water Mode]] when it qualifies, otherwise the [[Pump-Cycle Water Estimate]]. The two measurement sources are never summed (they describe the same physical water when a pump draws from a monitored tank); manual is always added on top, because hand-watering may come from a source the measurement never sees. See [[ADR-0017]].

**Water Source**
One of the three independent ways water reaching a growspace is accounted for: **manual** (explicit watering events, liters supplied by the caller), **tank-derived** ([[Tank-Derived Water Mode]] inference from reservoir-level change), and **pump-cycle** ([[Pump-Cycle Water Estimate]]). "Flow-based water use" is _not_ a source — no `irrigation_flow_sensor` reading is ever converted to liters; that config only gates whether [[Tank-Derived Water Mode]] is active.

**Pump-Cycle Water Estimate**
The liters a fired irrigation pump cycle delivered, estimated as pump runtime × `pump_flow_rate_ml_per_sec` (the same figure the daily-volume cap already uses). **Pump runtime** is the planned shot duration, except when the measured ON time exceeds it — which only happens on an [[Unconfirmed Pump Cycle]] whose confirmation wait outlasts the shot — so neither the estimate nor the cap can under-count water that physically flowed. It is persisted write-through into `WaterUsageData` — bumping `total_liters` and appending a `daily_readings` entry tagged `source: "pump_estimate"` (manual events are tagged `"manual"`) — so it survives restarts. The write is **skipped when the growspace is in [[Tank-Derived Water Mode]]**, since the tank already measures that water. The fallback measurement source whenever there is no qualifying tank. See [[ADR-0017]].

**Tank-Derived Water Mode**
The reservoir-measurement mode for water consumption tracking. Active when a growspace has at least one tank with `volume_liters` configured and no `irrigation_flow_sensors` or `drain_volume_sensors` are set. In this mode the tank-derived measurement comes from summing events across all qualifying `TankWaterTracker` instances since `cycle_start_date` (read-through — `WaterUsageData`'s pump estimates are _not_ written in this mode). It is one input to [[Aggregate Water Use]], which adds manual watering on top (per [[ADR-0017]] this can double-count hand-watering drawn from the monitored tank — a deliberate trade-off). The `reset_water_tracking` service advances `cycle_start_date` in both modes; `TankWaterHistory` is never cleared on reset.

The growspace view model payload includes `water_usage.liters_today` (sum of `TankWaterTracker.get_total_liters_today()` across all qualifying tanks) so the frontend chip can display today's consumption without reading from the HA sensor entity. The `growspace_manager/get_tank_water_history` WebSocket command returns pre-bucketed consumption data (aggregated across all qualifying tanks) for the frontend [[Tank Water Chart]].

**Crop Steering Phases**
The four phases of the crop-steering loop, derived each minute from the current time and soil VWC reading by the [[Steering Phase Machine]]: `P0` (Activation, immediately after lights-on), `P1` (Ramp Up, watering until `target_vwc_percent` is reached), `P2` (Maintenance, pulse watering when VWC drops below the maintenance trigger), and `P3` (Dry Back, no watering — spans the dark period and any post-`p2_stop` window). The active phase is exposed to the frontend via `IrrigationConfig.active_steering_phase` using a collapsed `p1`/`p2`/`p3` mapping (P0 collapses into `p1`).

**Crop Steering Phase Boundaries**
The four datetimes (`lights_on`, `p0_end`, `p2_stop`, `lights_off`) for a given calendar day that delimit the Crop Steering Phase windows. Computed by `phase_boundary_times()` (`domain/steering_phase.py`) from `IrrigationStrategy.lights_on_time`/`detected_lights_on_time`, `p0_duration_minutes`, `p2_stop_before_lights_off_minutes`, and the growspace's day-length config (`flower_day_hours`/`veg_day_hours`, defaulting to 12). Returned as a `SteeringPhaseBoundaries` dataclass and used both to determine the current phase (`determine_time_period`) and to project the next shot window (`projected_shot_window`) — both behind the [[Steering Phase Machine]] seam, so the two can never disagree.

**Steering Phase Machine**
The stateful module in `domain/steering_phase.py` that owns the per-minute crop-steering tick decision (ADR-0023). A [[ShotComposer]]-style stateful controller: it retains the phase, the daily ramp-up target flag with its date guard, and the Volume Mode change-tracking pair, and owns their reset rules. Its small interface is `tick(SteeringTickInputs)` → [[Steering Tick Verdict]] (the whole decision: phase, shot request, composer reset, logbook notes), `mark_no_sensor()` (the disabled state), `reset()` (midnight), read-only `current_phase`/`canonical_phase`, and `projected_shot_window(...)`. It owns **every** value the phase display can take — including `"Disabled (No Sensor)"` and `"Idle (no plants)"` — so phase state has exactly one home. Inputs are plain values only (strategy, config fields, resolved day-hours, live plant count, last confirmed shot, composer interval factor): no `hass`, no sensors, no coordinator (`tests/domain/test_steering_phase.py` is zero-mock). The [[VWCIrrigationCoordinator]] is the effects shell — it reads sensors, feeds the [[SubstrateTracker]], runs the runoff halt, and executes whatever the verdict names.

**Steering Tick Verdict**
The value one steering tick returns, in the [[Cycle Verdict]] mould: it records the decision and performs none of the effects. Fields: `phase` (display string), `canonical` (`p1`/`p2`/`p3`, `None` for non-canonical states), `phase_changed`, a pure-formatted `transition_message`, `reset_composer` (the P1→P2 event — applied by the shell _before_ any shot composes), `fire` (a `ShotRequest` naming the phase pair and the pre-composition **base** seconds; the [[ShotComposer]] and safety caps still apply downstream), `volume_change_note` (the pure-formatted ADR-0011 logbook text), and `suppressed_by` (why a shot the WINDOW phases would otherwise have fired did not — `cooldown`, `infiltrating`, `no_pump`, or `zero_volume`, evaluated in that order; `None` whenever a shot fires or the tick never reaches the shot decision, and never a phase state: `Idle (no plants)` is a phase, not a suppressed shot). `suppressed_by` is a diagnostic only — the shell publishes it in the shot-composition payload and nothing branches on it (ADR-0031). The shell maps fields to effects: `active_steering_phase`/`phase_changed_at` writes, the composer reset, logbook events (gated on `log_to_logbook` in the shell), and the pump cycle.

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
The grower's declared steering intent for a growspace: `vegetative`, `generative`, or `balanced`, plus a third "undeclared" state (`declared_steering_mode` is `None` until the first stamp — distinct from an explicit `balanced`). Selecting a mode is a **preset stamp**: it applies the mode's recommended setpoints into the ordinary editable strategy fields, one time — the grower may tweak any field afterwards and the coordinator only ever reads the explicit fields, never the mode. The stamp writes `maintenance_dryback_percent`, `p2_stop_before_lights_off_minutes`, the P1/P2 shot size + interval pair for the **active** [[Shot Sizing Mode]] only (seconds _or_ percent, never both), and the [[Pore EC Target Band]]. It deliberately does **not** write `target_vwc_percent` (a substrate/strain saturation property, not a steering-direction lever). Preset values vary by media × mode for the percent/dryback/p2-stop/EC fields; the raw seconds defaults vary by mode only (they are pump-dependent crude fallbacks). `soil` gets deliberately gentle, near mode-independent presets. The stamp is **not** idempotent-by-mode: re-selecting the already-declared mode re-stamps (a deliberate "reset to this mode's defaults", discarding hand tweaks). Each stamp writes one logbook entry naming the mode and media. Exposed via the `apply_steering_mode` service and a matching WS command; the server owns the preset table, the client only names the mode. The mode is also stored as the **declared intent**, so the measured steering score can be reported against it ("intended generative, substrate reads vegetative"). Distinct from the **Measured Classification** below, which is a measurement, not a setting.

In the wire contract the declared intent has a **single source of truth**: the `declared_steering_mode` field on the irrigation strategy, which the growspace view-model payload carries at `irrigation.irrigation_strategy.declared_steering_mode` (and the `apply_steering_mode` WS command echoes back under the same key). It is deliberately **not** mirrored onto the crop-steering sensor — the sensor carries only the derived readout. The crop-steering sensor attribute previously named `steering_mode` (the score-derived classification) is renamed to `measured_classification`, and the deviation readout is the sensor attribute `intent_deviation`; nothing in the payload uses the bare term `steering_mode` for two different things.

**Measured Classification**
The `vegetative` / `balanced` / `generative` bucket derived from the live steering score by fixed thresholds (`score > 0.3` → generative, `score < −0.3` → vegetative, else balanced). A read-only _measurement_ of how the substrate is actually behaving — never a setting and never written back to the strategy. Exposed as the `measured_classification` sensor attribute. [[Intent Deviation]] is exactly the comparison of this against the declared [[Steering Mode]].

**Intent Deviation**
A directional readout comparing the [[Measured Classification]] against the declared [[Steering Mode]] along the ordered axis `vegetative (−1) → balanced (0) → generative (+1)`. Exposed as the crop-steering sensor attribute `intent_deviation`, one of: `on_target` (buckets match), `more_generative` (substrate reads more generative than declared), `more_vegetative` (substrate reads more vegetative than declared), or `null` when no intent has been declared (`declared_steering_mode` is null — nothing to deviate from) or there is no current VWC reading (no measurement to compare). It is a comparison of a measurement against a setting; it never bends the score toward the declared mode, and the score itself stays an absolute −1…+1 measurement. The card composes any human-readable sentence by joining `intent_deviation` and `measured_classification` (sensor attributes) with `declared_steering_mode` (strategy payload).

**Substrate Profile**
Per-growspace description of the growing medium: media type (`coco`, `rockwool`, `soil`) and **liters per pot**. Total substrate volume is _liters per pot × live plant count_ — shot sizing is therefore constant **per-plant dosing**: when plants are removed mid-grow, total shot volume scales down automatically while each remaining plant's dose stays constant. Any live-count change that alters computed shot volume is recorded in the logbook. At zero plants the growspace has no irrigation demand: crop steering suspends shots (loop stays alive, phase reports idle).

**Shot Sizing Mode**
An explicit per-growspace choice between two ways of expressing steering shot size: **Seconds Mode** (the default, today's behavior — raw pump seconds, works with any pump and no extra config) and **Volume Mode** ([[Volume-Based Shot Sizing]], opt-in). Volume Mode is never auto-activated by the mere presence of its prerequisites; the grower switches modes deliberately. Seconds Mode is a permanently supported first-class mode, not a legacy fallback.

**Volume-Based Shot Sizing**
The professional convention for expressing irrigation shot size as a **percentage of substrate volume** (e.g. "P2 shots of 4%") rather than raw pump seconds. An opt-in [[Shot Sizing Mode]], selectable only when both a [[Substrate Profile]] and a pump flow rate are configured; the backend converts percent → ml → pump seconds. [[Steering Mode]] presets carry both percent values and seconds defaults, stamping whichever matches the active mode. P1 and P2 each have their own shot size and interval — the pair is a steering lever in its own right (fewer/larger = generative).

**Sensor-Gated Capability**
The principle governing every crop-steering feature: each capability gates on **its own minimal prerequisites** and nothing else. A VWC sensor alone enables the full phase loop, dryback tracking, and the steering score; pore-EC sensors additionally enable [[EC Trend]] and [[EC Modulation]]; flow rate + [[Substrate Profile]] additionally enable Volume Mode; drain readings enable the runoff-EC halt. A grower with partial sensors gets every feature their sensors support — no feature bundle requires the full sensor suite, and adding a capability never degrades a growspace that lacks its prerequisites.

**EC Modulation**
Opt-in, bounded adjustment of P2 shot volume driven by measured pore EC versus the [[Pore EC Target Band]]: pore EC above the band scales shots up (inducing runoff to flush), below the band scales them down (stacking EC). This is the only EC actuation in the system — there is no dosing hardware; feed EC remains hand-mixed. The modulation factor is bounded (roughly ±25%) and never overrides safety caps. Reads its direction from the [[EC Recommendation]] on [[EC State]] (ADR-0015), not from five scattered fields — so a runoff-driven flush and a pore-driven flush share this one actuator.

**Pore EC Target Band**
An explicit min/max pore-EC range on the irrigation strategy that [[EC Modulation]] steers toward. Stamped by [[Steering Mode]] presets (generative modes stack higher) and freely editable afterwards. Deliberately distinct from the per-stage **feed** EC target ranges (`ECTargetRange`) — pore EC legitimately runs above feed EC when stacking, so the two must never be conflated.

**Shot Size Composition**
The effective steering shot volume is `base × VWC feedback factor × EC modulation factor`, then subject to safety caps. The two factors are computed independently, may pull in opposite directions (partially cancelling — physically sensible), and are both exposed in diagnostics so any fired shot is explainable. Owned by the [[ShotComposer]] module (`domain/shot_composer.py`): the [[VWCIrrigationCoordinator]] hands it the base seconds plus injected `get_ec_factor`/`check_cap` callables and gets back a finished `ShotComposition` record — the one place the multiply, the [[Adaptive Shot Control]] factors, and the cap-aware `effective_seconds`/`capped` fields live.

**ShotComposer**
The stateful module in `domain/shot_composer.py` that owns the [[Shot Size Composition]] and the [[Adaptive Shot Control]] feedback factors. It is a `SubstrateTracker`-style stateful controller (retains the size/interval factors across ticks, owns their `reset()` rule), **not** a pure-per-call resolver like [[EC State]] — chosen because the factors persist and reset on phase events. Its small interface is `observe(moisture_before, moisture_after, tuning)` (run the feedback update), `reset()` (both factors → 1.0), `compose(phase, base_seconds, get_ec_factor, check_cap)` → `ShotComposition` (the full multiply + cap-aware record), and read-only `size_factor` / `interval_factor` / `last_composition`. The EC factor and the safety-cap check are **injected callables** so the [[EC State]] seam and downstream `_run_pump_cycle` cap enforcement stay where they are. The [[Steering Phase Machine]] decides _when_ the P1→P2 reset happens (its verdict carries a `reset_composer` flag the shell executes before composing); the midnight reset stays with the coordinator's daily-reset listener — the module owns the rule, the machine/shell own the triggers. Unit-testable with plain values, no coordinator or HA (`tests/domain/test_shot_composer.py`). See ADR-0021.

**EC State**
The single reconciled view of a growspace's electrical conductivity, produced by the `domain/ec_state.py` module (the [[StageEnvironmentalTargets]] precedent: a pure, lambda-testable class behind a small interface) — the **one place EC is reasoned about**. It carries the [[Active Feed EC Target]], the measured pore EC (via the existing averaging semantics), the measured runoff EC (latest drain reading), the [[Feed-to-Runoff EC Delta]], the [[Runoff Percentage]], one [[EC Recommendation]], and a separate `halt_irrigation` boolean. It is the input that [[EC Modulation]] and the [[Crop Steering Score]] read, replacing the prior pore-only path. Feed EC and pore EC live in separate fields and are never conflated — the recommendation is decided from pore-vs-band only (see ADR-0015). The `halt_irrigation` flag is a **separate field**, not an enum member: it is computed unconditionally from `drain_ec > halt_on_runoff_ec_threshold` regardless of `ec_modulation_enabled`, so the runoff safety halt can never be masked by a grower opting out of EC Modulation (ADR-0016). Reads only already-persisted config/readings; stores nothing of its own.
_Avoid_: EC reading, EC status (too vague — "EC State" is the reconciled record, not a single sensor value).

**Active Feed EC Target**
The feed-EC min/max resolved for a growspace _right now_ from its weekly `ECRampCurve` or, failing that, its per-stage `ECTargetRange` — keyed by the **furthest-along stage** present in the growspace (a growspace has no single canonical stage, so feed-target resolution deliberately chooses the most advanced stage with live plants, never under-feeding the most EC-demanding cohort). Week is `days_to_week(max_current_stage_age)` for Plants currently in that selected stage, read from [[Plant Lifecycle]]. Resolving to the furthest-along stage can over-state EC for younger plants in a mixed tent, but the readout is advisory (reconciliation display + a bounded score nudge, not actuation) so the risk is cosmetic; mixing stages on one feed line is itself unusual. `None` (source `"none"`) when neither a curve nor a matching range is configured — a graceful [[Sensor-Gated Capability]] absence, not an error. This is **feed** EC (what the grower hand-mixes into the tank), deliberately distinct from the [[Pore EC Target Band]]; the [[Steering Mode]] stamp never writes it (ADR-0012). Carried by [[EC State]] for display and runoff reconciliation, never to move the pore band.
_Avoid_: target EC, EC setpoint (ambiguous between feed and pore).

**EC Recommendation**
The single enum [[EC State]] exposes — `stack` / `hold` / `flush` / `unavailable` — that names the system's one EC _modulation_ decision. It is deliberately **modulation-direction only**: the runoff safety halt is **not** a member of this enum but a separate `halt_irrigation` boolean on [[EC State]] (see its entry), so a safety cut-off and an opt-in advisory adjustment never share a field or a gate. Maps 1:1 onto the [[EC Modulation]] tri-state: `stack` ⇔ pore below band (shrink shot, build EC), `hold` ⇔ within band (factor 1.0), `flush` ⇔ pore above band **or** runoff stacking (enlarge shot, induce runoff), `unavailable` ⇔ no pore reading / opt-out. The recommendation chooses _direction_; the `ec_modulation_factor_for_reading` helper (also in `domain/ec_state.py`, ADR-0023 rider) computes the bounded _magnitude_ — direction and magnitude live in the one EC module. There is exactly one EC actuator — every flush, whatever its cause, flows through this enum so any fired shot stays explainable ([[Shot Size Composition]]).
_Avoid_: EC action, EC mode (overloaded with [[Steering Mode]]).

**Runoff Reconciliation**
Turning runoff from a binary safety cut-off into a graduated steering input, on top of the [[EC State]] seam (ADR-0016). Makes the previously dead `target_runoff_percent` and the warning-only `max_ec_delta` live: [[Runoff Percentage]] and [[Feed-to-Runoff EC Delta]] are compared to their targets, bias the [[EC Recommendation]] (e.g. salts stacking faster than the pen shows → `hold` escalates to `flush`), and feed a bounded component into the [[Crop Steering Score]]. "Sustained" is read from the tail (last 2–3 entries) of the already-persisted `DrainConfig.readings` window — **not** from new state and never from the [[SubstrateTracker]] (which stays recorder-free measurement-only per ADR-0010). The existing runoff-EC halt is the `halt_irrigation` flag on [[EC State]], computed independently of EC Modulation rather than as a modulation-enum member. Degrades along [[Sensor-Gated Capability]]: EC-only growers still get delta reconciliation and the halt; volume sensors add [[Runoff Percentage]].
_Avoid_: drain monitoring (the storage/CRUD concern), runoff control (implies a closed setpoint loop, explicitly deferred).

**Runoff Percentage**
The measured fraction of feed that drains out: `drain_volume_ml / feed_volume_ml × 100` of the latest drain reading, compared against `DrainConfig.target_runoff_percent`. `None` when either volume is absent (a lower [[Sensor-Gated Capability]] tier). A noisy, low-confidence signal (channeling, uneven emitters) — it earns a [[Crop Steering Score]] nudge and a flush bias, never a hard irrigation gate (ADR-0016). Derived per-call, never persisted.

**Feed-to-Runoff EC Delta**
`drain_ec − feed_ec` of the latest [[DrainReading]] — how much the substrate concentrates the feed before it drains, compared against `DrainConfig.max_ec_delta`. A _sustained_ delta (agreement across the last 2–3 `DrainConfig.readings`, not a single reading) above target means salts are accumulating faster than the pore pen shows, biasing the [[EC Recommendation]] toward `flush` and the [[Crop Steering Score]] generative. Available from EC values **alone** (no volume sensors needed), so it is the runoff signal every drain-equipped grower gets. Distinct from runoff EC crossing `halt_on_runoff_ec_threshold`, which sets the separate `halt_irrigation` flag. Derived per-call from the persisted readings tail, never separately stored.

**Crop Steering Score**
The absolute −1…+1 measurement of how generatively the substrate is behaving, computed by `calculate_crop_steering_score` from three axes: [[Dryback]] (the ±0.4 primary), a **shared EC axis** (±0.3), and shot frequency (±0.3), summed then clamped. The **shared EC axis** carries the [[EC Trend]] _or_ the runoff signal, never both added: when a pore-EC Trend is measured (`rising`/`falling`) it sets the axis (±0.3); only when the Trend is `None` or `stable` does the sustained [[Feed-to-Runoff EC Delta]] fill it (ADR-0016). Pore EC is the closed-loop primary (ADR-0012 stamps its band); runoff's role is to _extend_ the EC signal to growers without pore-EC sensors, never to override or stack on a measured Trend — so the EC axis stays ±0.3 and dryback remains primary. The runoff fill is `None`-safe (no drain data → 0.0, score unchanged) and bucketed symmetrically off the grower's `max_ec_delta` (Δmax): a _sustained_ delta (unanimous across the last 2–3 readings, scored on the weakest) of ≥2·Δmax → +0.3, ≥Δmax → +0.2, ≤−Δmax → −0.2, ≤−2·Δmax → −0.3, else 0.0. [[Runoff Percentage]] does **not** contribute to the score (display-only). Stays a _measurement_ — it never bends toward the declared [[Steering Mode]]; the [[Measured Classification]] and [[Intent Deviation]] are derived from it. The runoff fill reads a config-thresholded physical signal (salts past the grower's `max_ec_delta`), the same measurement-relative-to-a-setting shape as [[Intent Deviation]] — not the score bending toward an intent.

**Dynamic VWC Steering Shot**
An irrigation shot in the VWC crop-steering loop whose duration is dynamically adjusted (clamped between the configured size floor and 100% of standard duration) based on the [[VWC Feedback Scale Factor]] calculated from the substrate's response to the previous shot. Part of [[Adaptive Shot Control]].

**VWC Feedback Scale Factor**
The scalar multiplier applied to the next steering shot's duration, calculated by comparing the actual volumetric water content (VWC) increase from the last settled shot against the expected target increase. Clamped `[dynamic_shot_size_floor, 1.0]` — it only ever shrinks a shot below nominal or recovers toward nominal, never enlarges. Resets to 1.0 at lights-on and during the P1-to-P2 phase transition.

**Interval Feedback Scale Factor**
The interval-domain sibling of the [[VWC Feedback Scale Factor]]: a scalar multiplier applied to the steering shot's minimum-cooldown floor (`p1/p2_shot_interval_minutes`), driven by the same overshoot ratio. Clamped `[1.0, dynamic_interval_ceiling]` — it only ever **lengthens** the cooldown or recovers toward nominal, never shortens below the configured interval. On overshoot the loop both shrinks the shot (size factor down) and lengthens the cooldown (this factor up); on undershoot both recover toward 1.0. Because P2 shots are already dryback-triggered, this factor only raises the floor — it never makes P2 fire faster than the substrate dries. Resets to 1.0 alongside the size factor. See ADR-0014.

**Adaptive Shot Control**
The full VWC feedback controller over both shot size ([[VWC Feedback Scale Factor]]) and shot spacing ([[Interval Feedback Scale Factor]]), gated by the single `dynamic_shot_enabled` master toggle. Its response is tunable via four shared/paired strategy fields: `dynamic_aggressiveness` (overshoot correction strength), `dynamic_recovery` (undershoot recovery rate), `dynamic_shot_size_floor` (lower clamp on the size factor), and `dynamic_interval_ceiling` (upper clamp on the interval factor). Size and interval share the aggressiveness/recovery pair so the loop has one consistent feel; only the bounds differ. Defaults on, preserving the previously always-on size feedback while making it disableable and adding interval adaptation. See ADR-0014. Lives in the [[ShotComposer]] module: the two factors are the composer's retained state and the feedback update is its `observe()` method; the [[VWCIrrigationCoordinator]] holds a composer instance and triggers `observe()` on each [[Settled Observation]] and `reset()` at lights-on and on the [[Steering Tick Verdict]]'s P1→P2 flag. Because an observation is conditional on a settled reading arriving in time, **`observe()` no longer runs once per cycle**: on a growspace whose substrate never settles between shots, or whose probe is slow or flaky, the factors simply stay where they are. Adaptation is therefore less frequent than it was, and directionally correct rather than biased toward more water. A **manual** run still trains the controller as it always has, even though the composer did not choose its volume — a pre-existing wart left standing deliberately (ADR-0014 amendment).

**Infiltration**
The interval after an irrigation shot during which delivered water is still redistributing through the substrate and measured VWC is still climbing toward its settled peak. A _physical_ state of the growspace, not a sensor artifact: its duration is a property of the medium and pot size (fast in rockwool, slow in coco and large pots), so it is measured per growspace rather than configured. The three states are `infiltrating` (VWC climbing), `settled` (VWC flat within the noise floor), and `drying` (VWC falling — the beginning of a [[Dryback]]), plus `unknown` when no reliable measurement exists. Deliberately **not** called a "VWC trend": [[EC Trend]] already binds `rising`/`stable`/`falling` to a _daily_ baseline-vs-latest comparison, and VWC's daily direction is Dryback, a different concept at a different timescale. The state has two consumers reading it at different strictnesses: the [[Infiltration Gate]] reads the bare state (a wrong `settled` only costs it a suppression it would not have made), while the [[Settled Observation]] additionally requires the measurement to rest on samples taken _after_ the cycle it describes.

**Infiltration Gate**
The steering-tick rule that withholds a shot while the growspace is [[Infiltration|infiltrating]], so a shot is never composed against a VWC reading that has not finished responding to the previous shot. It is **strictly additive to the configured shot cooldown**, never a replacement: the `p1/p2_shot_interval_minutes` floor (as scaled by the [[Interval Feedback Scale Factor]]) still applies underneath, so the gate can only ever _delay_ a shot, never permit one the existing rules would block. It therefore has no regression path — a missing or unreliable signal falls back to exactly today's behaviour. Applies to **both** P1 ramp-up and P2 maintenance: P1's stepped shots are otherwise open-loop, stepping VWC upward while blind to where the previous step actually landed. Distinct from [[Adaptive Shot Control]], which corrects overshoot _after_ the fact by shrinking the next shot and lengthening the next cooldown; the Infiltration Gate prevents the measurement error that causes the overshoot in the first place. Also distinct from the [[Pump Cycle Gate]] (tank/limit/dark, on the base pump) and from `halt_irrigation` (the EC-runoff safety cut) — this is a steering-timing concern only. A **stall backstop** keeps a stuck signal from withholding irrigation all day: once more than three configured intervals (as scaled by the [[Interval Feedback Scale Factor]]) have elapsed since the last _confirmed_ shot, the shot fires despite an `infiltrating` reading. The backstop anchors on `last_shot` rather than on a new timestamp — nothing observes the moment the gate became the binding constraint, since the cooldown returns first — so it adds no state and no configuration field. See ADR-0031.
_Avoid_: VWC trend gate (collides with [[EC Trend]]'s timescale), settling gate ("Sensor Settling Delay" is ADR-0008's 15s post-cycle wait), rising gate (names only the blocking branch).

**Settled Observation**
The [[Adaptive Shot Control]] feedback measurement of one irrigation cycle, taken when the [[Infiltration]] measurement says the substrate has stopped absorbing that cycle's water — not on a timer. Distinct from the **Sensor Settling Delay** (ADR-0008), which is a fixed `min(cycle_duration, 15s)` wait serving the _logbook_ line: the two describe the same cycle, run on different clocks, and will often report different after-readings, because 15s is mid-[[Infiltration]] by construction. Its readiness rule is stricter than the [[Infiltration Gate]]'s: at least two distinct sensor updates stamped _after_ the cycle ended, and a slope **across those post-cycle samples alone** that is no longer positive — never the monitor's ring-wide state, which keeps reading as climbing long after motion stops. Both `settled` and `drying` qualify: falling VWC is unambiguous evidence infiltration finished. The reading handed to the controller is one of those post-cycle samples, never a separate sensor read. An observation is **abandoned, never approximated** — on timeout, on a fast-following cycle (any confirmed irrigation start after this cycle ended, manual runs included), on a sensor dropout that outlasts the bound, or when the [[ShotComposer]] resets underneath it. Note that "fail open" means the _opposite_ mechanics here and in the Infiltration Gate: the gate's safe direction is to let the shot through, this one's is to do nothing at all. See the ADR-0014 amendment for the bound, the abandonment rules and the rejected alternatives.
_Avoid_: settling delay / settling observation (ADR-0008 owns "Sensor Settling Delay", a different wait on a different clock), infiltration-gated observation ("gate" names the shot-suppression rule, which this is not).

**Pump Cycle Gate**
The pure decision (in `domain/`, following the [[EC State]] / `domain/fan_control.py` precedent) of whether a base irrigation/drain pump cycle may fire _before_ it starts, and why it is skipped if not. Reasons, in precedence order: low tank (any [[Tank-Derived Water Mode]]-irrelevant `irrigation_tanks` reading below its `warning_level`, applies to **all** cycles when `pause_on_low_tank`), daily cycle limit, daily volume cap, and dark period (the last three irrigation-only; a **manual** run bypasses the dark check). Takes plain data in — config, the resolved `TankReading` list, a resolved `lights_dark` bool, the in-memory `cycles_today`/`volume_dispensed_today` counters, the precomputed cycle volume — and returns a [[Cycle Verdict]]; it reads no sensors and touches no `hass`. The volume/cycle-cap sub-check is exported separately (`safety_cap_blocks`) because the [[Adaptive Shot Control]] loop consults it alone (via the coordinator's thin `_check_safety_guards`) to set its `capped` diagnostic ([[Shot Size Composition]]). **Deliberately distinct from `halt_irrigation`** (the EC-runoff safety cut on [[EC State]], ADR-0016) and from the zero-plant steering-phase suspension (ADR-0011): the Pump Cycle Gate is the pre-cycle tank/limit/dark gate on the base pump, not an EC or steering concern. The decision is pure; the on→confirm→sleep→off→record-water→increment-counters shell and the reason→effect mapping (low-tank → persistent notification + logbook; cap/limit → logbook; dark → logbook only when `log_to_logbook`) stay in the coordinator.
_Avoid_: irrigation halt, skip (too vague — "halt" collides with the EC cut, "skip" names only the negative branch).

**Cycle Verdict**
The value a [[Pump Cycle Gate]] returns: `fire` (bool), a `reason` enum (`LOW_TANK` / `CYCLE_LIMIT` / `VOLUME_CAP` / `DARK` / `None`) the shell maps to effects, a pure-formatted `message` (the logbook text — dynamic tank %, cycle counts, and volume math built behind the seam so the wording is unit-tested), and the `low_tank` `TankReading` (name/level/warning) the persistent notification needs. A `fire=True` verdict carries `reason=None`. It records the decision only; it performs none of the effects.

**Unconfirmed Pump Cycle**
A cycle whose pump switch never reported `on` within the confirmation wait (10s) that exists for high-latency devices such as Matter smart plugs. It is **not** a skip and has nothing to do with the [[Pump Cycle Gate]]: `switch.turn_on` already returned, so the pump may have been running the whole time. The coordinator therefore dates the cycle from the `turn_on` call rather than from a confirmation that never came, and shortens the sleep by the wait — otherwise the pump delivers the shot _plus_ the entire timeout while the books record the shot. When the wait alone outlasts the shot the sleep clamps to zero and the measured ON time drives the [[Pump-Cycle Water Estimate]]. A genuinely offline pump is still treated as a completed cycle (water is booked that never flowed); turning non-confirmation into a hard failure is a separate, unmade decision.

**Irrigation Schedule**
The one owner of what a schedule time _is_ and how `irrigation_times`/`drain_times` change (`domain/irrigation_schedule.py`, ADR-0029; the [[Pump Cycle Gate]] / [[EC State]] mould — pure, no `hass`). Two parsing strictnesses on purpose: `normalize_schedule_time` (strict, for writes; raises so a bad service call fails loudly) is shared by add **and** remove, so they can never again disagree about time identity — the raw-string remove comparison it replaces made `remove_irrigation_time("08:00")` silently miss the stored `"08:00:00"`. `parse_stored_time` (lenient, for reads) returns `None` on malformed stored entries. `upsert_item`/`remove_items` return a `ScheduleChange` (new list + what happened); `schedulable_events` dedups by _parsed_ time and splits out malformed entries for the shell to warn about; `next_occurrence` projects the soonest future run. The coordinator keeps the effects: `async_track_time_change` registration, save/reload, task management. Deliberately _not_ here: `_run_pump_cycle` and the listener wiring are effect shells (ADR-0021/0023 precedent), not extraction candidates.

**Environment Patch**
The value a writer submits to change a growspace's `EnvironmentConfig`: the grower's edit, applied under **patch semantics** — an absent field means _keep the existing value_; an explicitly present field (including an empty list/dict) is a deliberate set or clear. Built and applied by `domain/environment_patch.py` (the [[Pump Cycle Gate]] / [[EC State]] precedent: pure, no `hass`), the one place EnvironmentConfig merge rules live (ADR-0026). **Build validates, apply is total**: writer-specific builders (`patch_from_service_call`, `patch_from_flow_options`, and per-sub-config builders for the narrow fan/grow-light writers) front-load all validation — singular→plural alias normalisation (the shadow singular is re-derived _after_ merge, so a stale singular can never resurrect a deliberately cleared plural), per-item key filtering for tanks/sensor groups (invalid items dropped as warnings, preserving today's lenient behaviour), and the stage/optimal VPD validators — so `apply_environment_patch(current, patch)` never raises on a built patch. `current=None` applies onto dataclass defaults; this pure path is also the one-time options-blob migration. Merge behaviour derives entirely from the [[Environment Field Ownership]] table; apply returns an [[Environment Patch Verdict]], and runtime writers commit it through one shared effect shell (`async_commit_environment_patch`) that owns the assign → save → refresh → targeted controller restarts → exhaust-repair re-evaluation ordering — a writer can no more forget an effect than a field. Hand-built `EnvironmentConfig(...)` rebuilds outside the module are forbidden. Supersedes the previous full-replace contract of `configure_environment`.
_Avoid_: full replace (the retired contract), config merge (names the mechanism, not the meaning).

**Environment Field Ownership**
The per-field classification row, declared once beside `EnvironmentConfig` in `models/growspace.py`, from which all [[Environment Patch]] merge behaviour derives: `grower-config` (patchable), `runtime-accumulated` (never patchable — always carried over from the existing config), or `sub-config` (owned by a dedicated narrow writer, patchable only as a whole). A row also declares the field's legacy singular alias and, for list-of-dataclass fields, the per-item identity key and nested runtime fields — `irrigation_tanks` items match by `sensor_entity` and carry over `water_history`/`last_recorded_level`/`peak_level`. The classification is **total**, enforced at import time by symmetric difference against the dataclass fields: adding an `EnvironmentConfig` field without a row fails every import instead of silently resetting on the next edit — the bug class behind the exhaust-config reset (ADR-0019), the Stage Hysteresis Threshold wipe, and the tank-history clobber.

**Environment Patch Verdict**
The value `apply_environment_patch` returns, in the [[Cycle Verdict]] mould: a fresh `EnvironmentConfig` (inputs never mutated), `changed_fields` (by value comparison — a patch restating current values changes nothing and restarts nothing), `controllers_to_restart` (derived behind the seam from a field→controller relevance table), `exhaust_repair_relevant`, a pure-formatted `summary` for the logbook, and the builder's drop-warnings. The verdict records the decision; the commit shell performs the effects.

**Environment Action Metadata**
The curated Home Assistant presentation of canonical `configure_environment` fields. Compatibility aliases remain accepted by the action adapter but are not part of this preferred interface, and omission never acquires a metadata default.

The growspace store is the **single source of truth** for `environment_config`. Per-growspace environment blobs in `config_entry.options` are legacy — no current writer produces them; on load one is adopted only when the store has no environment config for that growspace (one-time migration), then deleted. `storage_manager` no longer re-applies options over the store on every restart (the mechanism that silently reverted service-made environment edits).

## Drying Thresholds (Constants)

| Threshold               | Value             | Source                           |
| ----------------------- | ----------------- | -------------------------------- |
| Target dry weight ratio | 25% of wet weight | Standard cannabis drying science |
| Cure-ready moisture     | ≤ 12.0%           | Branch-snap test equivalent      |

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

## WebSocket API

**WS Command Lifecycle**
The one owner of everything between a WebSocket message arriving and a result or error leaving: coordinator resolution → handler execution → `send_result` → error mapping, implemented by the registration wrapper in `websocket/_common.py` (ADR-0027). A handler is a payload-returning function `(hass, coordinator, msg) → payload | None` — it never sees the connection, so its return value is its test surface (no mock connections). Each module declares its commands as [[WSCommand]] rows; the registrar loop in `websocket/__init__.py` wraps every row identically. Inline `connection.send_error` calls are forbidden in handlers — an error is a raised typed exception, mapped once by the shared error table.

**WSCommand**
The declarative row a websocket module contributes: `(type, handler, schema, resolve, sync)`. `resolve="targeted"` resolves the coordinator from ids in the message via `get_for_service_call`; `resolve="any"` uses `get_any` (global commands: strain library, genetics, nutrients, lineage). `sync=True` registers a `@callback` wrapper for cheap reads. Adding a WS command = one handler + one row; the lifecycle is inherited. (The WS command count is asserted in `test_core_init`.)

**Typed Error Codes**
The five-code wire vocabulary shared with the card (ADR-0005, completed backend-side by ADR-0027): `coordinator_not_ready`, `entity_not_found`, `validation_failed`, `internal_error`, `rate_limited`. Produced by the [[WS Command Lifecycle]] error table from typed exceptions — `EntityNotFoundError`, `CoordinatorNotReadyError`, `RateLimitedError` (subclasses of the existing hierarchy, so service-call paths behave as before) plus the validation family → `validation_failed` and everything else → `internal_error` (with traceback). The card's `errors.ts` types exactly this set and coerces anything else to `internal_error` — so ad-hoc codes are self-defeating and deliberately retired.

## Serialization

**Plant View Model**
The one shared representation of a Plant exposed to both the card and Home Assistant sensor attributes. Every `{stage}_days` entry means [[Lifetime Stage Days]], including the currently open stage after a Reveg; questions about only the current open interval use [[Current Stage Age]] instead.

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
Consumes `EvaluationSnapshot` records for Bayesian stress and mold evaluations and creates persistent [[Triage Alert]] records on inactive-to-active transitions. Repeated active snapshots are deduplicated in memory; a resolved snapshot re-arms the next rising edge. The first active snapshot after startup is treated as a rising edge, matching the former Home Assistant state-listener behavior. Stores records internally using a private storage dict; emits a public wire format via `_serialize_alert()` for all WebSocket responses. These two formats must never be conflated.

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

**Stage Hysteresis Thresholds**
The per-stage, day/night, **on/off** VPD band that drives a humidifier or dehumidifier: a nested `{stage: {cycle: {on, off}}}` table stored on `EnvironmentConfig` as `humidifier_thresholds` / `dehumidifier_thresholds`, ranged 0.1–3.0 kPa. The on/off pair is a hysteresis band (turn the appliance on at one VPD, off at another, to avoid short-cycling); the _direction_ differs by appliance — a humidifier's `on > off` (run when the air is too dry), a dehumidifier's `on < off` — but that lives entirely in the per-appliance default table, not in the structure. Its config-flow round-trip (the flat `{stage}_{cycle}_on`/`_off` form fields ↔ the nested table, plus the form schema) is owned by one module, `config_handlers/stage_thresholds.py` (`parse_stage_thresholds` + `build_stage_threshold_schema`), so the schema a step renders and the parse a step reads share **one field-name encoding** and cannot drift — which matters because `configure_humidifier`/`configure_dehumidifier` have **more than one router**: `EnvironmentConfigHandler` and `EnvironmentSensorsHandler` both reach these steps, and depending on the path either `EnvironmentConfigHandler` or the dedicated humidifier/dehumidifier handler can be the one that renders, while submissions always route (via the OptionsFlow step methods) to the dedicated handler. Every render path and every parse path now go through this one module, so the encoding is defined once no matter which handler renders or parses. Parameterised only by the appliance defaults table; the calling handler picks which config key the parsed table lands under. Distinct in _shape_ from [[Stage VPD Overrides]] and `vpd_optimal_overrides` (sparse `{day,night}` / `{low,high}` override dicts keyed by stage): Stage Hysteresis Thresholds are a **full** stage×cycle table of on/off pairs, not a sparse override.

## Exhaust Fan Controller

**ExhaustFanController**
An optional per-growspace subsystem that evacuates air by driving all `exhaust_fan_entities` on the same fixed 10 s tick as the [[Circulation Fan Controller]], registered in the `SubsystemManager` as an `EnvironmentController` with a `get_exhaust_fan_controller` accessor. Unlike the circulation fan there is **no single regulation mode and no dynamic wind layer**: exhaust output is always the combined **Exhaust Demand**. The controller is a no-op when `enabled=False` or no `exhaust_fan_entities` are configured, and it restarts cleanly when `configure_exhaust_fan` rewrites the config. See [ADR-0018](./docs/adr/0018-exhaust-fan-combined-demand.md).

**Exhaust Ownership**
The `ExhaustFanController` is the **sole owner** of `exhaust_fan_entities`; the [[Dehumidifier Controller]] controls only `dehumidifier_entities` and never touches exhaust fans. Historically the dehumidifier coordinator's controlled set was `dehumidifier_entities + exhaust_fan_entities`, so a grower with `control_dehumidifier` on and exhaust fans configured got crude on/off cycling of those fans for free. That ownership has been transferred to the exhaust controller. Because `ExhaustFanConfig` defaults to `enabled=False`, the transfer is **not auto-migrated** — old on/off humidity thresholds carry no speed-band information to infer from. Instead, affected installs raise the **Exhaust Migration Repair** so the opt-in to the new controller is explicit. See [ADR-0019](./docs/adr/0019-exhaust-fan-sole-ownership.md).

**Exhaust Migration Repair**
A per-growspace HA repair issue (`issue_id = exhaust_fan_migration_{growspace_id}`, `is_fixable=False`, `IssueSeverity.WARNING`) raised when a growspace's `EnvironmentConfig` has `control_dehumidifier` **on**, has `exhaust_fan_entities` **configured**, and has the new exhaust controller **disabled** (`exhaust_fan_config.enabled` is False) — the exact condition under which the [[Exhaust Ownership]] transfer would silently stop cycling a grower's exhaust fans. The `NOT enabled` guard is a deliberate refinement over the literal acceptance criteria: a grower who already enabled the new controller is being served by it and is not nagged. The repair text directs the grower to the Exhaust panel to opt in. It is **create-or-clear**: evaluated by a shared helper called from `async_setup_entry` and from every service handler that can change a trigger input without a full reload — `configure_exhaust_fan`, `set_dehumidifier_control`, and `configure_environment` (which mutate config via `async_restart`, not a reload) — so it self-heals the moment the condition no longer holds. `configure_environment` also preserves the existing `exhaust_fan_config` when it rebuilds `EnvironmentConfig`, so an environment edit no longer silently resets the exhaust controller to `enabled=False`. Accepted edge case: a `switch`/`input_boolean` exhaust fan the dehumidifier last commanded **on** can be left stuck on after the transfer (nothing drives it off until the grower enables the new controller) — out of scope, the issue's framed risk is fans _not cycling_, not fans stuck on.

**Exhaust Demand**
Each tick computes three demand terms from the shared `domain/fan_control.py` helpers and drives the fan to the highest: a **temperature term** (`compute_fan_speed` — hotter tent → more exhaust), a **humidity term** (`compute_fan_speed` — more humid → more exhaust), and an **inverted VPD term** (`compute_inverted_fan_speed` — more exhaust when VPD is _below_ target, i.e. the air is too saturated). The result is `final = clamp(max(temperature, humidity, vpd_inverted), min_speed, max_speed)`. A sensor that is missing or unavailable drops its term from the maximum; if none of the three read, the tick is a no-op. When `stage_vpd_enabled` is set, the VPD target is resolved per stage and day/night via the shared `resolve_stage_vpd_target` (and `stage_vpd_overrides`), exactly like the circulation fan. The **Source-Air Gate** may drop individual terms before the maximum, and the **Exhaust Critical-Temp Override** is then composed on top of the gated result (see below).

**Source-Air Gate**
A symmetric filter applied to **Exhaust Demand** that suppresses a term when the air the fan would draw in cannot improve conditions (ADR-0018). The **temperature** term is dropped when the lung-room/source air is **not cooler than the tent**, or is **below `minimum_source_air_temperature`**. The **humidity and inverted-VPD** terms are dropped when the source air is **not drier than the tent** — reusing the same closeness-to-target comparison the `EnvironmentAnalyzer` performs for air-exchange recommendations (`abs(lung_room_vpd − target) ≥ abs(current_vpd − target)`). Each suppressed term simply leaves the `max()`, so the remaining terms still drive the fan; if every term is gated while readings exist, demand floors at `min_speed` (switch off / fan idle) — a true no-op is reserved for when no sensor reads at all. The gate reads the install-wide lung-room sensors from `global_settings` (`lung_room_temp_sensor`, `lung_room_humidity_sensor`) — the same source the air-exchange recommendations use — and is **inert when no lung-room sensor is configured** (current ungated behavior). The **Exhaust Critical-Temp Override** bypasses this gate on a high-temp breach.

**Exhaust Critical-Temp Override**
A safety layer composed on top of the gated **Exhaust Demand** via the shared `evaluate_temp_override` helper (the same one the circulation fan uses). A breach of `critical_temp_high` forces `max_speed`, **bypassing the Source-Air Gate** — a heat emergency vents regardless of whether incoming air is ideal — while a breach of `critical_temp_low` forces `min_speed` to avoid over-chilling the tent. The override **latches** until temperature returns within bounds plus `critical_temp_hysteresis` (latch state is held on the controller and cleared on `async_restart`). It applies only when at least one critical threshold is configured and the temperature sensor reads; otherwise the gated demand passes through unchanged. Accepted edge case: a `critical_temp_low` breach forcing `min_speed` overrides a simultaneous high humidity demand (venting stops while humid) — cold air holds little moisture and chill protection takes precedence.

**Exhaust Speed Dispatch**
The final demand is dispatched per entity domain: a `fan` entity receives it as a percentage (`fan.set_percentage`); a `switch` or `input_boolean` exhaust device is turned **on** when the demand exceeds `min_speed` and **off** otherwise.

**ExhaustFanConfig**
The dataclass stored on `EnvironmentConfig` that holds the exhaust controller settings: `enabled`, `min_speed`, `max_speed`, per-term `temperature_target`/`temperature_tolerance`, `humidity_target`/`humidity_tolerance`, `vpd_target`/`vpd_tolerance`, `stage_vpd_enabled`, `stage_vpd_overrides`, and (driving the **Exhaust Critical-Temp Override**) `critical_temp_low`, `critical_temp_high`, `critical_temp_hysteresis`. There is no `regulation_mode` and no wind field. Absent or `enabled=False` means no exhaust control. Source-air gating reuses the existing `minimum_source_air_temperature` and lung-room sensors on `EnvironmentConfig` rather than adding fields here.

**VPD Optimal Overrides**
A per-growspace sparse dict stored on `EnvironmentConfig` as `vpd_optimal_overrides`. Keyed by user-facing stage name (`"seedling"`, `"clone"`, `"mother"`, `"veg"`, `"flower_early"`, `"flower_mid"`, `"flower_late"`, `"dry"`, `"cure"`); each entry is `{"day": {"low": float, "high": float}, "night": {"low": float, "high": float}}`. Only stages the user has explicitly edited are present — absent stages fall back to `VPD_OPTIMAL_THRESHOLDS`. Applies to the **standard sub-stage only**: the acclimation phases for `seedling` and `clone` (`BayesianStage.SEEDLING`, `BayesianStage.CLONE`) always use hardcoded defaults regardless of any override. Drives the "not optimal" chip and the optimal conditions binary sensor. Distinct from `stage_vpd_overrides` on `CirculationFanConfig`, which controls the fan regulation target, not Bayesian evaluation. Validation rules: `0.1 ≤ low < high ≤ 3.0` kPa; unknown stage keys are rejected; each entry must contain both `"day"` and `"night"` with both `"low"` and `"high"` — a partial entry is invalid. Configurable per-growspace via the **VPD Targets** tab in the config dialog.

**StageEnvironmentalTargets**
A class in `domain/environmental_targets.py` that encapsulates all stage-interpolated environmental threshold lookups behind a typed interface. Constructed from a `(stage_a, stage_b, factor)` triple taken from `StageClassification`. Provides five methods: `vpd_stress_band(time_of_day, env_config)` → `VpdStressBand` (evaluator path — direct subscript, raises on missing stage); `vpd_optimal_band(time_of_day, overrides)` → list of `(low, high, prob)` bands with per-growspace `vpd_optimal_overrides`; `humidity_band(env_config)` → `HumidityBand`; `co2_optimal_band()` → list of `(low, high, prob)` bands; `vpd_display_targets()` → `VpdDisplayTargets` (display path — `.get` with veg fallback, distinct from the evaluator path). The two VPD paths must not be unified: `vpd_stress_band` raises on a missing key (Bayesian evaluator contract), while `vpd_display_targets` silently falls back to veg thresholds (frontend display contract). Private helpers `_hum_limits`, `_get_optimal_limits`, `_ACCLIMATION_STAGES`, `_OVERRIDE_BAYESIAN_TO_KEY` live in the same module.

**Evaluation Snapshot**
An immutable record published by each Bayesian binary sensor (stress/mold/optimal) after every probability update, via `coordinator.services.notifications.report_evaluation()`. Fields: `growspace_id`, `sensor_type`, sensor name, `probability`, `threshold`, `is_on`, `reasons`, `sensor_states` (observation dict), `lights_on`, and the notification title/message precomputed for the triggered state. The snapshot is the **only** interface between Bayesian sensors and the notification subsystem: the facade sends it to both the Notification Manager and Alert Monitor. Neither consumer holds live sensor entity references, and there is no entity-registration or global state-change-listener path. The Notification Manager stores the latest snapshot per `(growspace_id, sensor_type)`. Light-flip cooldown is derived by the manager from consecutive snapshots' `lights_on` transitions, deduplicated per growspace — sensors do not call `trigger_cooldown`. The title/message text is frozen at snapshot time, which may be a few seconds older than the debounced batch-fire time; this is accepted. Notification message formatting (sorted reasons appended up to `MAX_NOTIFICATION_LENGTH`) is a pure function in `notifications/`, not a Notification Manager method. GrowAssistant AI enrichment of alert _records_ lives in `AlertMonitor._async_enrich_with_ai` (gated by `CONF_AI_AUTO_ALERTS`); the sensor never had a live AI path — its old `_send_notification` GrowAssistant copy was already unreachable and was removed.

**Evidence Fusion**
The Home Assistant-owned interpretation of current Bayesian environmental evidence and a Visual Comparison Result. It reports environmental risk, departure from recent scene history, or their coexistence; it never diagnoses plant health or treats coexistence as causation. See [ADR-0040](./docs/adr/0040-evidence-fusion-reports-observations-not-plant-health.md).
_Avoid_: Plant-health fusion, diagnosis engine, correlated stress

**Evidence Fusion Outcome**
Either an unavailable result with explicit missing-evidence reasons, or exactly one of `no_detected_change`, `environmental_risk`, `visual_anomaly`, `concurrent_environmental_risk_and_visual_anomaly`, and `critical_scene_issue`, qualified by confidence and evidence coverage. `no_detected_change` means only that complete available evidence found neither environmental risk nor material departure from recent scene history.
_Avoid_: Healthy, unhealthy, visual plant stress

**EnvironmentState Assembler**
A class in `domain/` (following the [[StageEnvironmentalTargets]] precedent) that builds an `EnvironmentState` from raw HA entity states. Constructed with injected callables (`get_state`, `get_growspace`, `get_plants`) plus the growspace's `EnvironmentConfig`; each Bayesian sensor owns its own assembler (`assemble()` is uncached, so a shared per-growspace instance would dedupe no reads). A single `assemble()` call returns an `AssembledEnvironment` holding both the `EnvironmentState` and the flat observation dict, derived from one read pass so the two can never diverge. Owns: multi-sensor aggregation (average) for temp/humidity/VPD, VPD fallback calculation with LST offset (zeroed for dry/cure growspaces), CO2/soil-moisture/substrate-temp reads, device-state derivation (fans-off AND logic, dehumidifier/humidifier-on OR logic, exhaust/humidifier max value), lights-on OR logic, and per-stage maxima of [[Current Stage Age]] from [[Plant Lifecycle]] (only a Plant's current stage contributes, so stale closed-stage dates cannot grow uncapped). Pure — no side effects: light-flip transition detection lives in the Notification Manager (see [[Evaluation Snapshot]]), not here. Unit-testable with plain lambdas (see `tests/domain/test_environment_state_assembler.py`).

**Notification Settings**
A dict of six timing/cooldown parameters stored in `config_entry.options["notification_settings"]`. Keys: `critical_cooldown_minutes`, `warning_cooldown_minutes`, `recovery_cooldown_minutes`, `escalation_delay_minutes`, `min_stress_duration_seconds`, `warning_persistence_minutes`. Each value falls back to the corresponding hardcoded constant in `const.py` when absent, so the dict may be partially populated or omitted entirely without breaking behaviour. Exposed as a top-level key in the global coordinator data payload and written atomically via the `save_notification_settings` WebSocket command.

**Timed Notification**
A user-configured reminder that fires on a specific day of a plant's lifecycle stage. Stored as a list in `config_entry.options["timed_notifications"]`. Each entry has `id` (UUID), `message`, `trigger_type`, `day`, and `growspace_ids`. Managed by `NotificationSettingsManager`. Exposed as a top-level key in the global coordinator data payload alongside Notification Settings.

**Camera Snapshot**
A point-in-time image captured from a growspace camera. Can be triggered manually by the grower via the camera snapshots dialog or automatically as part of a scheduled [[Vision Checkup]]. Saved to the public directory `www/growspace_manager/snapshots/{growspace_id}/` as a JPEG file named with a local timestamp prefix for display in the frontend.

**Vision Checkup**
An AI-powered diagnostic task performed on one or more [[Camera Snapshot]]s from a growspace, scheduled at three key times in the light cycle (early, mid, late) or triggered manually. The snapshots are processed with a 4x4 grid overlay and canopy green-pixel coverage analysis before being sent to the AI model. The analysis results (severity, detected issues, recommendations) are stored as a `VisionCheckupResult` in the growspace's vision history.

**Vision Evidence Store**
The Home Assistant-owned SQLite database `growspace_vision.db` holding every artifact of a [[Vision Checkup]]: [[Vision Capture]]s, their image files, Visual Embeddings, Visual Comparison Results, Baseline Buckets and [[Vision Label]]s. Growspace Vision is stateless, so this is the only durable record that the analysis happened. Versioned by `PRAGMA user_version` and migrated by forward-only numbered steps — deliberately not the `try: ALTER TABLE / except` pattern of `strain_library.py`, which records no version. See [ADR-0041](./docs/adr/0041-home-assistant-owns-vision-evidence-in-a-dedicated-store.md).
_Avoid_: Vision history, embedding cache, anomaly database

**Vision Capture**
One [[Camera Snapshot]] taken for a [[Vision Checkup]], identified by a `capture_id` (UUIDv7) minted in Home Assistant **before** the Growspace Vision call. The id is the filename stem of every image variant, so a file and its record are linked without the database. The capture record is written when the bytes are persisted, so a rejected or failed analysis still leaves a tracked, prunable image; `analysis_state` carries how far it got (`pending`, `analyzed`, `rejected`, `failed`).
_Avoid_: Frame, snapshot record, image row

**Capture Variant**
Which rendering of a [[Vision Capture]] an image file holds: `raw` (the camera's original bytes) or `processed` (the grid-overlaid JPEG the cloud path produces). Stored as a path relative to the resolved image root, never as a public URL, so the serving mechanism can change without a data migration. The record outlives the file — a pruned image is distinguishable from an image that never existed.

**Pinned Capture**
A [[Vision Capture]] exempt from image retention because its image is evidence: it is a current Baseline Bucket member, it carries a [[Vision Label]], or its Visual Comparison Result was `uncertain` or `material_scene_change`. Unpinned images are deleted after `image_retention_days` (default 90); pinned ones are kept indefinitely and survive deletion of their Growspace as orphans, with the growspace name denormalized onto the capture. This is the set a future training run needs, so an unrelated tidy-up must not destroy it.
_Avoid_: Archived capture, saved snapshot

**Scoring Policy Version**
An integer recorded on every Visual Comparison Result and Baseline Bucket, bumped whenever the Home Assistant side changes _how_ a comparison is produced — the distance metric, the rolling window size, the leave-one-out calibration, or the verdict cuts of ADR 0004. Distinct from model identity: an encoder change and a policy change both make results incomparable, and only the first is captured by model version. A result whose policy version differs from the current one stays displayable as history but is never reused as evidence.
_Avoid_: Schema version, algorithm hash

**Grow Run Reference**
The run identity a [[Vision Capture]] is attributed to. Grow Runs are specified but not yet implemented, so the integration mints a persisted surrogate id per growspace and marks it `surrogate`; when Grow Runs land, the source flips to `grow_run` and the mapping is a one-row-per-growspace backfill rather than a schema migration. A run boundary starts fresh Baseline Buckets — without one, the harvest (the largest legitimate scene change in the measured corpus) would alarm every time.

**Vision Label**
Grower feedback anchored on a `capture_id`, in exactly two kinds. A `comparison_correction` corrects a scene verdict the model actually made and carries that verdict alongside the corrected one. An `observation` asserts a symptom or condition the model never claimed, and therefore has no model output to correct — V1 emits no health claim, so conflating the two would imply one. Append-only: a revision supersedes its predecessor rather than overwriting it. Training eligibility is derived at export time, never stored; only an explicit human exclusion is persisted.
_Avoid_: Correction, ground truth, annotation record

**Legacy Vision Checkup History**
The pre-local-vision `vision_checkup_history` list on each `Growspace`, holding up to ten cloud-LLM results with `analysis`, `issues_detected`, `severity` and `recommendations`. Frozen in place at the cutover: never appended to again, and never read by baselines, trends, [[Evidence Fusion]] or a training set. It is not migrated into the [[Vision Evidence Store]] — those records assert exactly the symptom claims V1 may not make, and giving them equal standing with measured evidence would re-import the false authority the local vision work exists to remove.
_Avoid_: Vision history (unqualified)

**Contract Fixture**
The golden `get_data` growspace payload committed at `tests/fixtures/contract/growspace_payload.json`, serialized from one **maximally populated** growspace (every optional sub-config set). A snapshot test fails when the payload shape changes without the fixture being deliberately regenerated; the lovelace card strict-parses the same file in its CI. Maximal population is the load-bearing property — a field absent from the fixture builder is invisible to the contract.

**GSM-First Landing Order**
The rule that for any cross-repo feature, the integration side merges to `prerelease` and ships in a GSM release **before** the card PR merges to the card's `dev`. The only sanctioned exception is a [[Backward-Safe Card Change]].

**Backward-Safe Card Change**
A card change proven safe against the _released_ GSM backend, not just `prerelease` — the proof being the card's strict parse of the release-ref [[Contract Fixture]] passing. Named after the env-clear fix pattern (card #439), which had to behave correctly under both the old full-replace and the new patch semantics of `configure_environment`.
