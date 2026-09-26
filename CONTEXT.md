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
The maximum interval for which one time-series observation may represent a continuing value, defaulting to three times the sensor's expected update interval subject to a configurable cap. Time after that window is uncovered rather than filled from a stale value. For a [[Control Input]] the expected interval is learned — the median of the last eight intervals between its `last_reported` stamps, trusted once three are seen — and the window is never under 5 minutes; until an interval is learned, the cap alone applies. `validity_window` in `domain/sensor_validity.py`.
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
The single lightweight Home Assistant entity that exposes one Growspace's current Grow Run for dashboards and automations. Its state is the active Run Sequence Number or `none`, with compact identity, label, start, duration, participant-count, and Run Revision attributes; detailed history remains behind the integration API. It is `sensor.<growspace>_active_run` (`translation_key` `active_run`); its attribute keys are fixed whatever the state — `run_id`, `label`, `started_at`, `duration_days` (whole local days in the Run Timezone), `participant_count`, `run_revision` — and all but `run_revision` are null without an Active Run, because the Run Revision is what a Start must name. It reads unavailable while the Run history is unreadable. `domain/grow_run.py` owns the shape; `sensor/grow_run.py` publishes it (#668).
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
The permission rule that Growspace controllers may start, complete, finalize, and edit descriptive metadata, while only Home Assistant administrators may reopen, void, correct harvest attribution, or purge Run history. A **Growspace controller** is a Home Assistant user with entity _control_ permission on the Growspace's Active Run Sensor: every ordinary user and administrator, never a read-only user. It is asked on every command (`services/grow_runs.require_controller`), never remembered.
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
The monotonic version of one Growspace's Run collection used to reject stale lifecycle commands and atomically preserve the zero-or-one-active-Run rule. Each lifecycle command names the revision it was decided on (`expected_run_revision` on `growspace_manager/start_grow_run`); the Run Ledger checks, mutates, persists and only then publishes under one lock. Every refusal is a result rather than a WebSocket error — `grow_run.revision_conflict`, `grow_run.already_active`, `grow_run.not_authorized`, `grow_run.store_unreadable` — and carries the current revision and Active Run, so a stale command is answered with where the ledger really is.
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

**Lifecycle Reschedule**
The repair proposal for an edit that moves more than one boundary at once: it rebuilds [[Stage History]] from a set of stage starts, retaining every interval the edit does not name. A supplied date retargets that stage's latest interval, a stage the Plant has never been in is inserted where its date places it, and boundaries are re-derived so the result is gapless by construction. Retained stages are never reordered — a set that would require it, one that predates its successor, one dated after the correction date, or an insertion that breaks the transition graph is refused naming the stages that conflict. The Plant ends up in the stage owning the last interval, so correcting existing dates cannot change [[Current Stage]] while entering a later stage's start advances it. `update_plant` selects it structurally: no explicit `stage` and two or more populated `*_start` fields. One save is one [[Lifecycle Repair Event]] listing every boundary it moved. See ADR-0047.
_Avoid_: bulk date edit, multi-stage transition

**Lifecycle Repair Warning**
A machine-readable diagnosis produced for malformed, overlapping, nonchronological, future-dated, unknown-stage, or graph-invalid lifecycle data. Warnings fail lifecycle facts closed to Unknown Stage rather than activating a legacy fallback.

**Lifecycle Repair Event**
The immutable event draft produced by [[Lifecycle Correction]] or [[Lifecycle Reschedule]], recording the prior/corrected stage, correction and stage-start dates, every corrected boundary, grower reason, discarded interval count, and warning codes. The domain module drafts it; an outer shell decides whether and where to publish it.

**Compatibility Data**
The lifecycle-owned projection for legacy Plant consumers: the shadow `stage`, latest per-stage `*_start` values, and Stage History. It is rebuilt from trusted intervals after every Applied transition, Lifecycle Correction, or [[Lifecycle Reschedule]] so legacy fields cannot disagree with the domain result.

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
The single canonical figure for how much water a growspace has consumed, the one number every consumer (`WaterUsageSensor`, briefing KPI, AI context, the frontend [[Tank-Derived Water Chip]]) reports. Composed from three [[Water Source]]s under one rule: **manual watering plus exactly one measurement source** — [[Tank-Derived Water Mode]] when it qualifies, otherwise the [[Pump-Cycle Water Estimate]]. The two measurement sources are never summed (they describe the same physical water when a pump draws from a monitored tank); manual is always added on top, because hand-watering may come from a source the measurement never sees. It is the answer to "how much water today" and is **never** what the daily caps enforce — that is [[Dispensed Volume]], and the two may differ (ADR-0054). See [[ADR-0017]].

**Water Source**
One of the three independent ways water reaching a growspace is accounted for: **manual** ([[Hand Watering]], liters supplied by the person reporting it), **tank-derived** ([[Tank-Derived Water Mode]] inference from reservoir-level change), and **pump-cycle** ([[Pump-Cycle Water Estimate]]). "Flow-based water use" is _not_ a source — no `irrigation_flow_sensor` reading is ever converted to liters, and the config has no effect on water accounting (#853).

**Pump-Cycle Water Estimate**
The liters a fired irrigation pump cycle delivered, estimated as the **measured** ON time × `pump_flow_rate_ml_per_sec` — the best estimate of the water that flowed, so a shot aborted 5s into a 60s plan shows 5s of water. The daily caps charge the same shot differently: see [[Dispensed Volume]] (ADR-0054). An [[Unconfirmed Pump Cycle]] books none. It is persisted write-through into `WaterUsageData` — bumping `total_liters` and appending a `daily_readings` entry tagged `source: "pump_estimate"` (manual events are tagged `"manual"`) — so it survives restarts. The write is **skipped when the growspace is in [[Tank-Derived Water Mode]]**, since the tank already measures that water. The fallback measurement source whenever there is no qualifying tank. See [[ADR-0017]].

**Dispensed Volume**
The pump volume, and with it the count of pump starts (**Dispensed Cycles**), that the [[Irrigation Controller]] has charged against a growspace's daily cycle limit and daily volume cap since local midnight. It answers "how much has the controller been allowed to push today", not "how much water did the plants get" — that is [[Aggregate Water Use]], and in [[Tank-Derived Water Mode]] the two legitimately differ. Every irrigation cycle whose pump confirmed ON is charged, manual pump runs included, aborted ones included; hand-watering, drains and an [[Unconfirmed Pump Cycle]] never are. A shot is charged its planned volume the moment the pump confirms ON and topped up if it runs longer, so an aborted shot costs the cap its whole plan while its [[Pump-Cycle Water Estimate]] shows only what ran. It is the sum of today's charges across the growspace's [[Delivery Attempt]]s, so it is durable, outside any user reset, and survives a restart only on the day it was charged. See ADR-0054 and ADR-0055.
_Avoid_: water used today, liters today (those name [[Aggregate Water Use]]).

**Delivery Attempt**
One request for a pump cycle that reached the [[Pump Cycle Gate]] — scheduled, steering, manual or drain — recorded from the request to its close under one stable identity. Its lifecycle is **Requested → Actuated → Closed**: actuated when its zone's valves read open and the [[Irrigation Supply]] confirms ON, closed with an outcome of `suppressed` (and why — including `foreign_valve_open`), `not_delivered` (an [[Unconfirmed Pump Cycle]], or a valve that never read open), `completed`, `aborted` (and by what) or `interrupted` (open when Home Assistant stopped), plus whether OFF was read back. Its delivered volume is either **estimated** (measured ON time × flow rate) or **metered**, and only a metered attempt can be short or over. Today's charges across a growspace's attempts are its [[Dispensed Volume]]; each attempt names the [[Irrigation Zone]] it watered. A steering tick that withholds a shot never asks, so it makes no attempt. See ADR-0055.
_Avoid_: shot (a steering request, and only one kind of attempt), cycle alone (names the pump's run, not the record), verified (already means OFF read back — `completed_verified`).

**Irrigation Zone**
One steered cohort within a growspace: the grid cells, and so the plants, that the same valve outputs water together and one control loop steers. It owns its cells, valves, substrate probes, emitter flow rate, schedule and steering strategy with its own phase and substrate history; the growspace keeps what is shared — the pump, drain, tanks and feed, the lights and the steering day, the safety policies and controls, the daily caps and the water figures. Every existing growspace has one **implicit zone** (id `default`) owning every cell and watered by the pump directly; it stays invisible and undeletable while it is the only zone. With two or more zones every zone must own a valve, and a call that names only the growspace is refused rather than guessed. See ADR-0057.
It owns one or more valves, always opened together, and a valve belongs to exactly one zone (ADR-0058).
_Avoid_: subarea (that is air — climate sensors for a region, with no plants and no actuation), valve (a zone may open several), delivery group (ruled out: the valves a zone opens together are the zone), section.

**Irrigation Supply**
The one output per growspace that moves water into its [[Irrigation Zone]]s — a pump, or a master valve on pressurised mains. Only one zone is ever open on it at a time, so a flow meter on the supply line always measures exactly the one open zone. A grower with two feeds has two growspaces. See ADR-0058.
_Avoid_: pump group (ruled out), master pump.

**Manual Run**
A pump cycle Growspace Manager runs because a person asked for it (`run_irrigation_cycle`), through every gate but the dark check and the [[Startup Inhibit]]. It is a [[Delivery Attempt]] with a `manual` trigger, charges [[Dispensed Volume]] like any other cycle, and never trains [[Adaptive Shot Control]]. See ADR-0056.
_Avoid_: manual delivery, manual watering, manual cycle.

**Hand Watering**
A person's report of water they gave the plants themselves (`water_plant`, `water_growspace`). Growspace Manager moved nothing, so it is never gated, never actuates an output, never charges [[Dispensed Volume]] and is not a [[Delivery Attempt]]; it is a record, attributed by plant, that feeds [[Aggregate Water Use]] as its manual source. It may be reported up to 7 days late and is dated to when the water was given; one marked `from_monitored_tank` is left out of the figure in [[Tank-Derived Water Mode]], which already counted it. See ADR-0056.
_Avoid_: manual delivery, manual watering, manual run (that one Growspace Manager performs).

**Tank-Derived Water Mode**
The reservoir-measurement mode for water consumption tracking. Active when a growspace has at least one tank with `volume_liters` configured. `irrigation_flow_sensors` and `drain_volume_sensors` do not switch it off: neither is ever read as litres, and when they did, adding a flow meter quietly traded the tank figure for the less accurate [[Pump-Cycle Water Estimate]] (#853). In this mode the tank-derived measurement comes from summing events across all qualifying `TankWaterTracker` instances since `cycle_start_date` (read-through — `WaterUsageData`'s pump estimates are _not_ written in this mode). It is one input to [[Aggregate Water Use]], which adds manual watering on top (per [[ADR-0017]] this can double-count hand-watering drawn from the monitored tank — a deliberate trade-off, which a [[Hand Watering]] marked `from_monitored_tank` avoids, ADR-0056). The `reset_water_tracking` service advances `cycle_start_date` in both modes; `TankWaterHistory` is never cleared on reset.

The growspace view model payload includes `water_usage.liters_today` (sum of `TankWaterTracker.get_total_liters_today()` across all qualifying tanks) so the frontend chip can display today's consumption without reading from the HA sensor entity. The `growspace_manager/get_tank_water_history` WebSocket command returns pre-bucketed consumption data (aggregated across all qualifying tanks) for the frontend [[Tank Water Chart]].

**Crop Steering Phases**
The four phases of the crop-steering loop, derived each minute from the current time and soil VWC reading by the [[Steering Phase Machine]]: `P0` (Activation, immediately after lights-on), `P1` (Ramp Up, watering until `target_vwc_percent` is reached), `P2` (Maintenance, pulse watering when VWC drops below the maintenance trigger), and `P3` (Dry Back, no watering — spans the dark period and any post-`p2_stop` window). The active phase is exposed to the frontend via `IrrigationConfig.active_steering_phase` using a collapsed `p1`/`p2`/`p3` mapping (P0 collapses into `p1`). Under [[Skip P2]] the P1 → P2 step does not happen at all and a completed P1 goes straight to P3.

**Skip P2**
The `IrrigationStrategy.skip_p2_after_p1` opt-in (default off) that sends a completed P1 straight to P3, so P2 never runs. A phase-transition rule and nothing more: the [[Steering Phase Machine]] reads it only where it would otherwise answer P2 — on the tick VWC reaches `target_vwc_percent`, and on every post-completion tick after it — and the P2 setpoints (`p2_shot_duration_seconds`, `p2_shot_interval_minutes`, `maintenance_dryback_percent`, `p2_stop_before_lights_off_minutes`, `IrrigationConfig.soil_trigger_percent`) are left exactly as the grower configured them. Clearing the flag therefore restores the ordinary P1 → P2 → P3 day mid-run, from those same values, with nothing to re-enter. Deliberately **not** a phase lock: once in P3 the day behaves as any other P3, and the daily reset returns the growspace to P1 at the next lights-on. Distinct from `IrrigationConfig.auto_advance_p2_to_p3`, which is clock-driven — it ends a P2 that ran; this one means P2 never begins.

**Crop Steering Phase Boundaries**
The four datetimes (`lights_on`, `p0_end`, `p2_stop`, `lights_off`) for a given calendar day that delimit the Crop Steering Phase windows. Computed by `phase_boundary_times()` (`domain/steering_phase.py`) from `IrrigationStrategy.lights_on_time`/`detected_lights_on_time`, `p0_duration_minutes`, `p2_stop_before_lights_off_minutes`, and the growspace's day-length config (`flower_day_hours`/`veg_day_hours`, defaulting to 12). Returned as a `SteeringPhaseBoundaries` dataclass and used both to determine the current phase (`determine_time_period`) and to project the next shot window (`projected_shot_window`) — both behind the [[Steering Phase Machine]] seam, so the two can never disagree.

**Steering Phase Machine**
The stateful module in `domain/steering_phase.py` that owns the per-minute crop-steering tick decision (ADR-0023). A [[ShotComposer]]-style stateful controller: it retains the phase, the daily ramp-up target flag with its date guard, and the Volume Mode change-tracking pair, and owns their reset rules. Its small interface is `tick(SteeringTickInputs)` → [[Steering Tick Verdict]] (the whole decision: phase, shot request, composer reset, logbook notes), `mark_no_sensor()` (the disabled state), `reset()` (midnight), `restore(p1_completed_on, today)` (setup: resume a day whose P1 already completed, ADR-0049), read-only `current_phase`/`canonical_phase`, and `projected_shot_window(...)`. It owns **every** value the phase display can take — including `"Disabled (No Sensor)"` and `"Idle (no plants)"` — so phase state has exactly one home. Inputs are plain values only (strategy, config fields, resolved day-hours, live plant count, last confirmed shot, composer interval factor, whether the [[Startup Inhibit]] holds): no `hass`, no sensors, no coordinator (`tests/domain/test_steering_phase.py` is zero-mock). The [[VWCIrrigationCoordinator]] is the effects shell — it reads sensors, feeds the [[SubstrateTracker]], runs the runoff halt, and executes whatever the verdict names.

**Steering Tick Verdict**
The value one steering tick returns, in the [[Cycle Verdict]] mould: it records the decision and performs none of the effects. Fields: `phase` (display string), `canonical` (`p1`/`p2`/`p3`, `None` for non-canonical states), `phase_changed`, a pure-formatted `transition_message`, `reset_composer` (the P1→P2 event — applied by the shell _before_ any shot composes), `fire` (a `ShotRequest` naming the phase pair and the pre-composition **base** seconds; the [[ShotComposer]] and safety caps still apply downstream), `volume_change_note` (the pure-formatted ADR-0011 logbook text), `p1_completed_on` (the local date, on the one tick that completes P1 — the shell persists it so a restart can `restore()` it), and `suppressed_by` (why a shot the WINDOW phases would otherwise have fired did not — `startup`, `cooldown`, `infiltrating`, `no_pump`, or `zero_volume`, evaluated in that order; `None` whenever a shot fires or the tick never reaches the shot decision, and never a phase state: `Idle (no plants)` is a phase, not a suppressed shot). `suppressed_by` is a diagnostic only — the shell publishes it in the shot-composition payload and nothing branches on it (ADR-0031). The shell maps fields to effects: `active_steering_phase`/`phase_changed_at` writes, the composer reset, logbook events (gated on `log_to_logbook` in the shell), and the pump cycle.

**Dryback**
The decrease in substrate volumetric water content from a local peak to the following trough, always expressed in **absolute VWC percentage points** (peak − trough; a drop from 55% to 45% is a 10% dryback) — never as a ratio relative to the peak. This is the single canonical convention across backend logic, dialogs, and charts; it matches how `maintenance_dryback_percent` already behaves (P2 trigger = target − dryback) and the convention growers quote. Any formula computing dryback relative to peak is wrong.

**SubstrateTracker**
The per-growspace component that turns raw soil-moisture and pore-EC readings into measured substrate events, following the [[Tank-Derived Water Mode]] tracker precedent: fed live by the crop-steering minute loop, persisting a rolling event history on the growspace model so derived metrics survive restarts. The recorder remains chart-only — automation and analytics never query it. v1 produces three measured metrics: [[Overnight Dryback]], [[In-Cycle Dryback]]s, and the [[EC Trend]]. Field-capacity detection is explicitly deferred. The same persisted history also carries the two steering facts a restart must not forget — the last confirmed shot and the date P1 completed (ADR-0049) — but the tracker neither writes nor reads them: its own shot timestamps are request times and settling peaks, not confirmed pump starts.

**Overnight Dryback**
The headline daily [[Dryback]]: from the settled VWC peak after the day's **last** irrigation shot to the minimum VWC before the **next** day's first shot (shot-to-shot, not clock-bounded). Lights-off/lights-on times do not bound the window — when Auto-Advance ends shots early, the dryback window starts at the last shot, hours before lights-off. On a day with zero shots, the peak falls back to the lit-period maximum.

**In-Cycle Dryback**
A micro [[Dryback]] between two consecutive P2 shots: the settled peak after one shot to the trough immediately before the next. The set of a day's In-Cycle Drybacks yields shots/day context and the average P2 dryback, and validates that the configured maintenance trigger behaves as intended.

**EC Trend**
The direction of pore EC over the current day — `rising`, `stable`, or `falling` — computed from actual pore-EC sensor readings by the [[SubstrateTracker]]. Replaces the previously hardcoded `"stable"` placeholder in the steering score.

**Steering Mode**
The grower's declared steering intent for a growspace: `vegetative`, `generative`, or `balanced`, plus a third "undeclared" state (`declared_steering_mode` is `None` until the first stamp — distinct from an explicit `balanced`). Selecting a mode is a **preset stamp**: it applies the mode's recommended setpoints into the ordinary editable strategy fields, one time — the grower may tweak any field afterwards and the coordinator only ever reads the explicit fields, never the mode. The stamp writes `maintenance_dryback_percent`, `p2_stop_before_lights_off_minutes`, the P1/P2 shot size + interval pair for the **active** [[Shot Sizing Mode]] only (seconds _or_ percent, never both), and the [[Pore EC Target Band]]. It deliberately does **not** write `target_vwc_percent` (a substrate/strain saturation property, not a steering-direction lever). Preset values vary by media × mode for the percent/dryback/p2-stop/EC fields; the raw seconds defaults vary by mode only (they are pump-dependent crude fallbacks). `soil` gets deliberately gentle, near mode-independent presets. The stamp is **not** idempotent-by-mode: re-selecting the already-declared mode re-stamps (a deliberate "reset to this mode's defaults", discarding hand tweaks). Each stamp writes one logbook entry naming the mode and media. Exposed via the `apply_steering_mode` service and a matching WS command; the server owns the preset table, the client only names the mode. The mode is also stored as the **declared intent**, so the measured steering score can be reported against it ("intended generative, substrate reads vegetative"). Distinct from the **Measured Classification** below, which is a measurement, not a setting.

In the wire contract the declared intent has a **single source of truth**: the `declared_steering_mode` field on the irrigation strategy, which the growspace view-model payload carries at `irrigation.irrigation_strategy.declared_steering_mode` (and the `apply_steering_mode` WS command echoes back under the same key). It is deliberately **not** mirrored onto the crop-steering sensor — the sensor carries only the derived readout. The crop-steering sensor attribute previously named `steering_mode` (the score-derived classification) is renamed to `measured_classification`, and the deviation readout is the sensor attribute `intent_deviation`; nothing in the payload uses the bare term `steering_mode` for two different things.

**Irrigation Change**
A validated change to a growspace's irrigation configuration, and the **one** module that writes irrigation setpoints: `services/irrigation_change.py`. Every [[Recipe Stamp]] goes through it, whether a grower asked for it or automatic [[Program Progression]] did, as does every [[Steering Mode]] stamp and every ordinary settings/strategy patch — there is no second stamp writer and no caller-managed provenance write (ADR-0046). A refused candidate changes nothing. A raised commit restores the prior in-memory config, strategy and recipe provenance and produces neither a success logbook entry nor a refresh; success narrates only after the commit that earned it. The guarantee is exactly that in-memory restoration: it is **not** durable atomicity across the configuration, plant and genetics stores, so a failure in a later store can still leave persisted state a restart would reveal, and recovering from that is separate work.

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

**Shot Size Conversion**
The two-way conversion in `domain/shot_sizing.py` between a [[Volume-Based Shot Sizing]] percent and pump seconds, and the only place that arithmetic lives. Pure functions over plain numbers with the live plant count passed in explicitly: `shot_volume_ml(percent, …)`, `percent_to_seconds(…)` (the sizing direction the [[Steering Phase Machine]] fires shots with) and `seconds_to_percent(…)` (recovering the per-pot dose a growspace's configured seconds actually deliver, so a shot size can travel between growspaces). Both are anchored on `percent/100 × liters_per_pot × live_plant_count × 1000 = ml` and `ml / flow rate = seconds`. Because the forward direction multiplies the live plant count in, the inverse **divides it back out** — that division is exactly what makes a recovered percent plant-count-independent, since two growspaces dosing the same per-pot percent need different seconds at different plant counts. Omitting it would scale the percent by the count and silently mis-water every growspace the value is later applied to. A missing prerequisite (no live plants, no pot volume, no flow rate) returns `None` — a suspend or a refusal, never a fallback duration or a guessed percent. The module also owns `dripper_flow_rate_ml_per_sec` ([[Dripper Throughput]]), because litres/hour × emitter count is an input representation of the very flow rate these conversions consume rather than a quantity of its own.

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
The feed-EC min/max resolved for a growspace _right now_ from its own weekly [[EC Ramp Curve]] or, failing that, its per-stage `ECTargetRange` — keyed by the **furthest-along stage** present in the growspace (a growspace has no single canonical stage, so feed-target resolution deliberately chooses the most advanced stage with live plants, never under-feeding the most EC-demanding cohort). Week is `days_to_week(max_current_stage_age)` for Plants currently in that selected stage, read from [[Plant Lifecycle]]. Resolving to the furthest-along stage can over-state EC for younger plants in a mixed tent, but the readout is advisory (reconciliation display + a bounded score nudge, not actuation) so the risk is cosmetic; mixing stages on one feed line is itself unusual. `None` (source `"none"`) when neither a curve nor a matching range is configured — a graceful [[Sensor-Gated Capability]] absence, not an error. This is **feed** EC (what the grower hand-mixes into the tank), deliberately distinct from the [[Pore EC Target Band]]; the [[Steering Mode]] stamp never writes it (ADR-0012). Carried by [[EC State]] for display and runoff reconciliation, never to move the pore band.
_Avoid_: target EC, EC setpoint (ambiguous between feed and pore).

**EC Ramp Curve**
A grower-authored table of weekly feed-EC bands for **one stage of one growspace** — `ECRampCurve` in `models/irrigation.py`, holding `growspace_id`, `stage`, and week-keyed `ECRampPoint`s. It is the preferred source of the [[Active Feed EC Target]], outranking the growspace's per-stage `ECTargetRange` (which has no week dimension) whenever a band resolves for the current week; `band_for_week` holds the final point past the last defined week and answers `None` before the first. The growspace binding is **explicit ownership**, and a growspace has at most one curve per stage: a second curve for a stage it already covers is refused at save time rather than stored as one of two whose precedence would be an accident of dictionary order. `active_curve_for` in `domain/ec_state.py` is the single owner of that lookup, shared by the feed-target seam and the `ECTargetSensor`. Ownership rather than a by-reference `ec_ramp_curve_id` on the growspace (the [[Irrigation Program]] shape) because a curve covers one stage, so an id on the growspace would go stale at every stage transition and fall silently back to `ECTargetRange`; a growspace's own flower curve applies the moment it flowers. A curve with an empty `growspace_id` was written by the version that discarded the binding entirely (workspace#108): it is inert and raises a repair asking the grower to re-save it, because the stage it was saved with was never stored and cannot be recovered. See ADR-0046.
_Avoid_: EC schedule, feed chart (the curve is the stored table; what it resolves to _now_ is the [[Active Feed EC Target]]).

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
The full VWC feedback controller over both shot size ([[VWC Feedback Scale Factor]]) and shot spacing ([[Interval Feedback Scale Factor]]), gated by the single `dynamic_shot_enabled` master toggle. Its response is tunable via four shared/paired strategy fields: `dynamic_aggressiveness` (overshoot correction strength), `dynamic_recovery` (undershoot recovery rate), `dynamic_shot_size_floor` (lower clamp on the size factor), and `dynamic_interval_ceiling` (upper clamp on the interval factor). Size and interval share the aggressiveness/recovery pair so the loop has one consistent feel; only the bounds differ. Defaults on, preserving the previously always-on size feedback while making it disableable and adding interval adaptation. See ADR-0014. Lives in the [[ShotComposer]] module: the two factors are the composer's retained state and the feedback update is its `observe()` method; the [[VWCIrrigationCoordinator]] holds a composer instance and triggers `observe()` on each [[Settled Observation]] and `reset()` at lights-on and on the [[Steering Tick Verdict]]'s P1→P2 flag. Because an observation is conditional on a settled reading arriving in time, **`observe()` no longer runs once per cycle**: on a growspace whose substrate never settles between shots, or whose probe is slow or flaky, the factors simply stay where they are. Adaptation is therefore less frequent than it was, and directionally correct rather than biased toward more water. A [[Manual Run]] never trains the controller, because a person chose its volume, not the composer; it and a [[Hand Watering]] reported while an observation is pending still abandon that observation (ADR-0056, reversing the ADR-0014 amendment's standing wart).

**Infiltration**
The interval after an irrigation shot during which delivered water is still redistributing through the substrate and measured VWC is still climbing toward its settled peak. A _physical_ state of the growspace, not a sensor artifact: its duration is a property of the medium and pot size (fast in rockwool, slow in coco and large pots), so it is measured per growspace rather than configured. The three states are `infiltrating` (VWC climbing), `settled` (VWC flat within the noise floor), and `drying` (VWC falling — the beginning of a [[Dryback]]), plus `unknown` when no reliable measurement exists. Deliberately **not** called a "VWC trend": [[EC Trend]] already binds `rising`/`stable`/`falling` to a _daily_ baseline-vs-latest comparison, and VWC's daily direction is Dryback, a different concept at a different timescale. The state has two consumers reading it at different strictnesses: the [[Infiltration Gate]] reads the bare state (a wrong `settled` only costs it a suppression it would not have made), while the [[Settled Observation]] additionally requires the measurement to rest on samples taken _after_ the cycle it describes.

**Infiltration Gate**
The steering-tick rule that withholds a shot while the growspace is [[Infiltration|infiltrating]], so a shot is never composed against a VWC reading that has not finished responding to the previous shot. It is **strictly additive to the configured shot cooldown**, never a replacement: the `p1/p2_shot_interval_minutes` floor (as scaled by the [[Interval Feedback Scale Factor]]) still applies underneath, so the gate can only ever _delay_ a shot, never permit one the existing rules would block. It therefore has no regression path — a missing or unreliable signal falls back to exactly today's behaviour. Applies to **both** P1 ramp-up and P2 maintenance: P1's stepped shots are otherwise open-loop, stepping VWC upward while blind to where the previous step actually landed. Distinct from [[Adaptive Shot Control]], which corrects overshoot _after_ the fact by shrinking the next shot and lengthening the next cooldown; the Infiltration Gate prevents the measurement error that causes the overshoot in the first place. Also distinct from the [[Pump Cycle Gate]] (tank/limit/dark, on the base pump) and from `halt_irrigation` (the EC-runoff safety cut) — this is a steering-timing concern only. A **stall backstop** keeps a stuck signal from withholding irrigation all day: once more than three configured intervals (as scaled by the [[Interval Feedback Scale Factor]]) have elapsed since the last _confirmed_ shot, the shot fires despite an `infiltrating` reading. The backstop anchors on `last_shot` rather than on a new timestamp — nothing observes the moment the gate became the binding constraint, since the cooldown returns first — so it adds no state and no configuration field. See ADR-0031.
_Avoid_: VWC trend gate (collides with [[EC Trend]]'s timescale), settling gate ("Sensor Settling Delay" is ADR-0008's 15s post-cycle wait), rising gate (names only the blocking branch).

**Settled Observation**
The [[Adaptive Shot Control]] feedback measurement of one irrigation cycle, taken when the [[Infiltration]] measurement says the substrate has stopped absorbing that cycle's water — not on a timer. Distinct from the **Sensor Settling Delay** (ADR-0008), which is a fixed `min(cycle_duration, 15s)` wait serving the _logbook_ line: the two describe the same cycle, run on different clocks, and will often report different after-readings, because 15s is mid-[[Infiltration]] by construction. Its readiness rule is stricter than the [[Infiltration Gate]]'s: at least two distinct sensor updates stamped _after_ the cycle ended, and a slope **across those post-cycle samples alone** that is no longer positive — never the monitor's ring-wide state, which keeps reading as climbing long after motion stops. Both `settled` and `drying` qualify: falling VWC is unambiguous evidence infiltration finished. The reading handed to the controller is one of those post-cycle samples, never a separate sensor read. An observation is **abandoned, never approximated** — on timeout, on a fast-following cycle (any confirmed irrigation start after this cycle ended, manual runs included), on a sensor dropout that outlasts the bound, or when the [[ShotComposer]] resets underneath it. Note that "fail open" means the _opposite_ mechanics here and in the Infiltration Gate: the gate's safe direction is to let the shot through, this one's is to do nothing at all. See the ADR-0014 amendment for the bound, the abandonment rules and the rejected alternatives.
_Avoid_: settling delay / settling observation (ADR-0008 owns "Sensor Settling Delay", a different wait on a different clock), infiltration-gated observation ("gate" names the shot-suppression rule, which this is not).

**Pump Cycle Gate**
The pure decision (in `domain/`, following the [[EC State]] / `domain/fan_control.py` precedent) of whether a base irrigation/drain pump cycle may fire _before_ it starts, and why it is skipped if not. Reasons, in precedence order: emergency stop, latched fault, low tank (any [[Tank-Derived Water Mode]]-irrelevant `irrigation_tanks` reading below its `warning_level`, applies to **all** cycles when `pause_on_low_tank`), [[Unknown Tank Level]] (the same scope and the same switch — a tank whose level cannot be trusted is refused, never skipped), daily cycle limit, daily volume cap, and dark period (the last three irrigation-only; a **manual** run bypasses the dark check). Takes plain data in — config, the resolved `TankReading` list and the tanks at an [[Unknown Tank Level]], a resolved `lights_dark` bool, the growspace's [[Dispensed Volume]] and Dispensed Cycles, the precomputed cycle volume — and returns a [[Cycle Verdict]]; it reads no sensors and touches no `hass`. The volume/cycle-cap sub-check is exported separately (`safety_cap_blocks`) because the [[Adaptive Shot Control]] loop consults it alone (via the coordinator's thin `_check_safety_guards`) to set its `capped` diagnostic ([[Shot Size Composition]]). **Deliberately distinct from `halt_irrigation`** (the EC-runoff safety cut on [[EC State]], ADR-0016) and from the zero-plant steering-phase suspension (ADR-0011): the Pump Cycle Gate is the pre-cycle safety/tank/limit/dark gate on the base pump, not an EC or steering concern. The decision is pure; the on→confirm→sleep→book-water→off→confirm-off shell and the reason→effect mapping (low-tank and unknown-tank → persistent notification + logbook; cap/limit → logbook; dark → logbook only when `log_to_logbook`) stay in the coordinator.
_Avoid_: irrigation halt, skip (too vague — "halt" collides with the EC cut, "skip" names only the negative branch).

**Cycle Verdict**
The value a [[Pump Cycle Gate]] returns: `fire` (bool), a `reason` enum (`FAULT` / `EMERGENCY_STOP` / `STARTUP` / `LOW_TANK` / `TANK_UNKNOWN` / `CYCLE_LIMIT` / `VOLUME_CAP` / `DARK` / `None`) the shell maps to effects, a pure-formatted `message` (the logbook text — dynamic tank %, cycle counts, and volume math built behind the seam so the wording is unit-tested), and the `low_tank` `TankReading` (name/level/warning) or the `unknown_tank` the persistent notification needs. A `fire=True` verdict carries `reason=None`. It records the decision only; it performs none of the effects.

**Unconfirmed Pump Cycle**
A cycle that could not be opened: `switch.turn_on` raised (`on_command_failed`), or the pump never reported `on` within the confirmation wait (10s) that exists for high-latency devices such as Matter smart plugs (`on_unconfirmed`). The command may still have reached the relay, so the coordinator fails closed: it commands OFF, reads it back, and books the cycle as **not delivered** — a `cycle_not_delivered` row in the [[Safety Ledger]], no daily cycle or volume, no pump water, no `last_cycle_timestamp`. One is a slow or flaky device; three in a row on the same output latch a [[Fault]] (`fault_on_unconfirmed:<entity>` or `fault_on_command_failed:<entity>`, after the last one's kind), and a confirmed ON on that output resets the run. It charges no water, but its [[Delivery Attempt]] records the window in which water may have moved, from the ON command until OFF read back (ADR-0055).
_Avoid_: failed cycle (a skipped cycle also "fails"; this one was commanded).

**Pump Readback**
Reading a pump's own reported state after commanding it, rather than trusting the command's return (`actuator_driver.async_confirm_state`, ADR-0022's driver layer). OFF is read back after every cycle, the watchdog's OFF and every OFF sent after a failed open: first at 1s — so an optimistic state written as the command returns is never taken as the answer — then every 0.5s up to 6s. The window is patient on purpose: a Zigbee plug has reported OFF 1.6s late, and a readback that gives up at the first disagreement latches a false [[Fault]] on it. A pump that does not read OFF by 6s latches `fault_off_unconfirmed:<entity>`; OFF is re-sent at once, a persistent notification goes out, and OFF is re-sent every minute until the pump reads OFF — across a restart too. Reading OFF again stops the retries and nothing else: the fault stays latched until it is acknowledged. A refused OFF command is judged by the readback, not by the refusal.
_Avoid_: confirmation (names the 10s ON wait, which is event-driven and has no first-read delay).

**Irrigation Controller**
The growspace-level safety interlock around automatic and manual pump cycles. Its sensor state is `idle`, `ready`, `running`, `inhibited`, `fault`, or `emergency_stop`. A transient inhibit clears with its gate and never starts a cycle by itself; the [[Startup Inhibit]] is one, and an invalid moisture [[Control Input]] another. A person holding the pumps — a [[Manual Override]] of irrigation (`manual_override`) or an [[Unexpected On]] under the `alert` policy (`override_detected`) — is an inhibit that holds manual runs too, so it reads `inhibited` even on a controller with nothing automated. Its `overrides` attribute lists every Manual Override of the growspace, whatever subsystem it holds. A latched [[Fault]] blocks every later cycle on that growspace across restarts. The emergency-stop latch is durable and takes precedence over a simultaneous fault; the operator controls for it belong to #791. `domain/irrigation_safety.py` owns state precedence and structured reason wire forms; `irrigation_safety_store.py` owns durability.

**Startup Inhibit**
The transient hold every growspace starts under after a start or reload (ADR-0049): the [[Irrigation Controller]] reads `inhibited` with reason `startup_inhibit` until `startup_grace_minutes` (default 5) have passed **and** every control sensor — the substrate moisture sensor while crop steering drives the pump, and each configured irrigation tank — has reported a usable value since the start. It holds automatic cycles of every kind and never a manual run, which still passes every other gate. It latches clear for the life of the coordinator, and a shot it withheld is never replayed. Once a growspace has [[Irrigation Zone]]s, the grace time and the tanks stay growspace-wide but the probes are each zone's own: a zone clears when its probes have reported, so a dead probe holds only its zone (ADR-0057).
_Avoid_: warm-up, boot delay (it waits on sensors, not only on a clock).

**Fault**
A hardware disagreement with a pump command, recorded with a stable reason code and affected outputs: a [[Pump Readback]] that never read OFF, or a run of [[Unconfirmed Pump Cycle]]s. It is latched before another cycle can begin and clears only when an administrator calls `acknowledge_fault` while every affected output reads OFF. Corrupt stored safety metadata fails closed as `fault_record_unreadable`.

**Manual Override**
A person declaring that they have one subsystem of a growspace — `irrigation` (both pumps), `exhaust`, `circulation`, `humidifier`, `dehumidifier` or `lights` — for a stated time of at most 24 hours (`set_override`, `clear_override`; #793, ADR-0053). Until it expires or is cleared, Growspace Manager sends that subsystem no command of any kind: no cycle, no regulation tick, no fail-safe, no OFF. A cycle already running when irrigation is taken over is closed first, so its own OFF is the last command the pump gets. It is written through to the safety store with the caller's HA user, survives a restart, and expires by its own timer — or, if it ran out while Home Assistant was stopped, at the next start. A stored one that cannot be read fails closed like every other safety record. The emergency stop is not an output command in this sense and still reaches every output. `domain/manual_override.py` owns the record; `IrrigationSafetyStore.commands_allowed` is the one gate the controllers ask.
_Avoid_: pause (that is the automation switch, which holds everything), manual run (a manual run is Growspace Manager watering on a person's request, through every gate).

**Unexpected On**
A managed pump reading ON when no cycle of Growspace Manager's own is in flight — none commanded ON and not yet read back OFF — and no [[Manual Override]] holds irrigation (#793, ADR-0053). A pump found ON at a start while a cycle of Growspace Manager's own was still in flight when the previous process stopped is not one: it is switched off and read back, whatever the policy, the controls or an override say. Until ADR-0055's restart handling lands, "still in flight" is its [[In-flight Marker]] (#854); after it, an open [[Delivery Attempt]], which then closes as `interrupted`. It is seen by a state watch on every pump, at a start, and before any cycle is let through, so the ON-confirmation wait can never take a person's run for its own. `unexpected_on_policy` on `IrrigationConfig` decides what follows: `alert` (default) treats it as a person's, notifies once and holds every cycle with `override_detected` until the pump reads OFF; `enforce_off` switches it off, reads it back and latches `fault_unexpected_on:<entity>`, or `fault_off_unconfirmed:<entity>` with its retries when it will not read OFF. With automation off or an emergency stop latched, `enforce_off` only alerts: Growspace Manager is sending nothing then, not even OFF.
_Avoid_: rogue pump, manual override (that one is declared, this one is observed).

**Safety Ledger**
The bounded, write-through record of controller transitions, faults, acknowledgements, cycles booked as not delivered, [[Manual Override]]s set, cleared and expired, and each [[Unexpected On]] with what was done about it. It survives Recorder purges and is included in diagnostics; entries also produce logbook events.

**Reliability Evidence**
Durable per-growspace counts of how the controller operated: cycles requested, fired and completed (verified or not), skips by reason, aborts by cause, pump command and [[Pump Readback]] failures, control-sensor dropouts, inhibits, [[Fault]]s, emergency stops and Home Assistant starts — each a lifetime total plus rolling 24 h and 30 d windows (`reliability_store.py`, `docs/reliability-evidence.md`). Every counter is incremented from one place in an effect shell, and recording never waits on the disk, so evidence cannot delay a fail-safe. Unlike the [[Safety Ledger]] it holds counts, not events, and it never gates control. It is returned to the grower on request by `export_reliability_evidence` and is never sent anywhere.
_Avoid_: telemetry (nothing leaves the instance), evidence alone (the Vision terms own it — [[Vision Evidence Store]], Evidence Fusion).

**In-flight Marker**
The durable note in [[Reliability Evidence]] that a pump is running a cycle, written the moment it reads ON and cleared, without a save delay, when the cycle closes. A marker still present at a start means the previous process stopped mid-cycle, and is counted as `runtime.ha_start_inflight`. It is kept until its pump reads OFF. A pump reading ON while it holds is that cycle's, not an [[Unexpected On]]: it is switched off and read back, whatever the policy, and an `interrupted_cycle` row is written to the [[Safety Ledger]] (#854). A marker is written only once the pump confirms ON, so a crash between the ON command and its confirmation leaves none. That gap, and the question whose run this is, move to an open [[Delivery Attempt]] with ADR-0055's restart handling.

**Automation Uptime**
The share of observed minutes in which automatic irrigation was armed and no [[Fault]] was latched, per window of [[Reliability Evidence]]. It measures whether the controller could act, not whether any cycle was due.

**Control Input**
A sensor an automatic controller acts on, read only through `domain/sensor_validity.py`: **unavailable** (unknown, unavailable, missing or not a number), **implausible** (NaN, infinite, or outside its quantity's range — substrate moisture 0–100 %, and 0 itself with `moisture_zero_is_implausible`; pore EC 0–20 mS/cm, a µS/cm probe converted first; relative humidity 0–100 %; VPD 0–10 kPa; temperature −10–60 °C or 14–140 °F by the sensor's unit, both when it names none) or **stale** (no report within its [[Observation Validity Window]], capped by `sensor_stale_after_minutes`, default 30, `0` off). An invalid reading is `None` with its cause and never becomes 0. The substrate moisture sensor under crop steering withholds automatic shots from the first invalid minute — the [[Irrigation Controller]] reads `inhibited` with `sensor_unavailable`, `sensor_stale` or `sensor_implausible` — and after `sensor_alert_delay_minutes` (default 15) raises one alert per episode, cleared with a recovery message, at most once an hour for a flapping probe; manual runs are not held. Pore EC sensors are validated the same way and an invalid one is left out of the average, which turns EC modulation off rather than holding irrigation. The humidifier, dehumidifier and exhaust controllers read their control inputs for freshness too, capped by the [[Climate Fail-Safe]]'s own `sensor_stale_after_minutes`, and hold their last command while one is invalid. A tank is a control input with its own window and grace: [[Unknown Tank Level]]. See ADR-0051.
_Avoid_: bad sensor, sensor offline (names one of three causes).

**Unknown Tank Level**
A configured irrigation tank whose level cannot be trusted right now, for one of three reasons from `domain/sensor_validity.py`: **unavailable** (unknown, unavailable or not a number), **stale** (no report — read from `last_reported`, which moves on a report that repeats the value — for longer than the tank's `stale_after_minutes`, default 120; `0` switches staleness off for a sensor that reports only when its value changes) or **implausible** (outside 0–100 %; 0 % is a real, empty tank and reads as low). With `pause_on_low_tank` on, the [[Pump Cycle Gate]] refuses every cycle, manual included, with `TANK_UNKNOWN`, and the [[Irrigation Controller]] reads `inhibited` with reason `tank_unknown`. The refusal waits out `tank_unknown_grace_minutes` (default 10) from the moment the level stopped being trustworthy — for a stale tank, the moment it went stale — holding the last valid reading meanwhile; a tank that has not read validly since the start has nothing to hold and is refused at once. Independently of `pause_on_low_tank`, and whether or not a cycle is due, the tank's **Tank Offline Alert** goes out once the grace period has passed: one push per episode on its own notification tier, a persistent notification that is dismissed when the tank reads again — together with the notice a refused cycle raised, once no tank in the growspace is still offline — and a "back online" push only for an episode that alerted. A new episode's alert waits out 60 minutes from the previous one, so a flapping probe cannot page every hour; one still unknown after that wait alerts then. `domain/unknown_tank_level.py` owns the grace and the episode; `TankLevelMonitor` owns the watch and its effects. See ADR-0050.
_Avoid_: tank offline (names one of the three causes), unreadable tank (a stale tank reads fine; it just stopped reporting).

**Irrigation Schedule**
The one owner of what a schedule time _is_ and how `irrigation_times`/`drain_times` change (`domain/irrigation_schedule.py`, ADR-0029; the [[Pump Cycle Gate]] / [[EC State]] mould — pure, no `hass`). Two parsing strictnesses on purpose: `normalize_schedule_time` (strict, for writes; raises so a bad service call fails loudly) is shared by add **and** remove, so they can never again disagree about time identity — the raw-string remove comparison it replaces made `remove_irrigation_time("08:00")` silently miss the stored `"08:00:00"`. `parse_stored_time` (lenient, for reads) returns `None` on malformed stored entries. `upsert_item`/`remove_items` return a `ScheduleChange` (new list + what happened); `schedulable_events` dedups by _parsed_ time and splits out malformed entries for the shell to warn about; `next_occurrence` projects the soonest future run. The coordinator keeps the effects: `async_track_time_change` registration, save/reload, task management. Deliberately _not_ here: `_run_pump_cycle` and the listener wiring are effect shells (ADR-0021/0023 precedent), not extraction candidates.

**Irrigation Recipe**
A grower-authored, reusable snapshot of one growspace's irrigation settings, saved into a global library and applicable to any other growspace. `models/irrigation_recipe.py` is the shape, `domain/irrigation_recipe.py` the capture rules (pure, the [[Pump Cycle Gate]] mould), `managers/irrigation_recipe.py` the library — global exactly as nutrient presets are, stored beside them in the same config document and riding every growspace payload at `irrigation.recipes` so the card's irrigation dialog seeds from the device payload it already has. Carries exactly one `kind` — `crop_steering` (the `IrrigationStrategy` setpoints) or `schedule` (`irrigation_times`, durations, daily cap, max cycles, skip-during-dark) — because a grower runs one or the other, and a recipe holding both halves would always carry one half of noise. Applying a recipe of the wrong kind is refused, never half-applied. Deliberately excludes pump/tank entity IDs, `active_steering_phase`, `phase_changed_at` and `detected_lights_on_time`: those are the target growspace's own hardware and live state, and copying them across is not portability but corruption. Also excludes `ec_target_ranges` — that is feed EC, which must never be conflated with the [[Pore EC Target Band]] (see [[Active Feed EC Target]]) — and two fields that are settings but not _setpoints_: `enabled`, because applying a recipe must never switch a subsystem on (ADR-0012's stamp does not write it either), and `declared_steering_mode`, because that is provenance naming a different source, and a recipe writing it would leave two competing provenances on one strategy.
The word **recipe** is reserved for grower-authored objects; **preset** is reserved for tables that ship with the product (the [[Steering Mode]] stamp). Nutrient presets predate the distinction and keep their name.
_Avoid_: irrigation preset (collides with the shipped [[Steering Mode]] table), irrigation profile (collides with [[Substrate Profile]]).

**Recipe Provenance**
The authoring context stamped onto an [[Irrigation Recipe]] at save time: media type, liters per pot, pump flow rate, and the [[Current Stage]] + week it was authored in. Purely **descriptive** — it records where the recipe came from and lets the card warn on a media mismatch at apply time. It never gates an apply and never decides _when_ a recipe runs; that authority belongs to the [[Irrigation Program]] slot, or to the grower for a direct apply. The recipe's own stage/week only sorts and preselects in the picker, so applying a flower-week-3 recipe to a week-5 tent is a supported deliberate act, not a validation failure.

**Substrate-Relative Shot Storage**
The mechanism that makes an [[Irrigation Recipe]] portable: shot sizes are stored as a percent of substrate volume, never as pump seconds. Ten seconds at one dripper throughput is a completely different shot at another, so a verbatim copy silently over- or under-waters the target growspace. On apply, the target recomputes its own seconds from _its_ flow rate and _its_ `liters_per_pot` through the existing [[Volume-Based Shot Sizing]] path (percent → ml → pump seconds). A recipe authored while the growspace is in Seconds [[Shot Sizing Mode]] derives the percent through [[Shot Size Conversion]]'s inverse direction, and the save is **refused, naming the missing input**, when the flow rate, the per-pot volume or a live plant count to divide back out is absent — seconds alone cannot be normalized honestly, and the capture runs to completion before anything is stored so a refusal leaves no partial recipe. Pot size normalizes; **media does not** — drybacks and EC stacking differ agronomically between coco, rockwool and soil (ADR-0012's table is discrete judgements, not an interpolable function), so a cross-media apply warns and proceeds unscaled rather than inventing a conversion.

**Dripper Throughput**
A grower-facing _input representation_ of `pump_flow_rate_ml_per_sec`, entered as per-emitter litres/hour times emitter count. One physical quantity, one stored value: there is no second field, because two numbers that must agree is a reconciliation rule waiting to be written. `dripper_flow_rate_ml_per_sec` in `domain/shot_sizing.py` is the conversion; the [[Irrigation Change]] seam accepts `dripper_liters_per_hour` + `emitter_count` as a compatibility spelling and collapses them into `pump_flow_rate_ml_per_sec` during normalization, so neither input reaches storage. Submitting one half alone is refused. Displayed back in the same form.

**Irrigation Program**
An ordered plan that assigns [[Irrigation Recipe]]s to `(stage, week)` slots across a whole run, bound to a growspace by an explicit `irrigation_program_id`. `models/irrigation_program.py` is the shape, `domain/irrigation_program.py` the rules (pure, the [[Pump Cycle Gate]] mould), `managers/irrigation_program.py` the library — global exactly as the recipe library is, stored beside it in the same config document and riding every growspace payload at `irrigation.programs`. Whole-run rather than per-stage because a program defining only flower slots _is_ a per-stage program, while the veg→flower handoff is exactly what a per-stage shape would need a separate rule for. The binding is explicit on purpose: the [[EC Ramp Curve]] used to bind implicitly by first stage match in dictionary order, so which curve drove a growspace was an accident of insertion — a footgun this deliberately did not repeat, and one ADR-0046 has since closed on the curve's own side (by ownership rather than by reference, because a curve covers a single stage). Assigning through `assign_irrigation_program` (and its matching WS command) writes that one id and **no setpoint**, so picking a program from a dropdown cannot change what a pump does that same minute; putting a slot's values into a growspace stays the separate, deliberate [[Recipe Stamp]]. Recipes are held **by reference** — a slot stores a `recipe_id` and nothing else — so a fixed shot size propagates to every program using it; the growspace already holds a by-value snapshot from the moment of the stamp, which is what makes the program a _plan_ rather than a record. Slots are keyed by the live stages [[Recipe Week Resolution]] can answer with and by 1-indexed weeks, and a slot naming anything else is refused at save time rather than stored as a plan the system would silently never reach. Removing a program leaves a bound growspace's id dangling exactly as a deleted recipe leaves `applied_recipe_id` dangling; the read path reports it as no current slot.
_Avoid_: irrigation schedule (means [[Irrigation Schedule]] — the times a pump fires), feed chart.

**Program Slot Resolution**
Which slot a bound growspace is currently in, and what the payload says about it. `domain/irrigation_program.resolve_program_slot` matches `(stage, week)` — from [[Recipe Week Resolution]], unchanged — **exactly**, and answers `None` for every other case: no live plants, a week the plan does not define, and a week past its end. One answer for all three because they are one thing, [[Program Hold]]: no unambiguous instruction, so nothing changes. Surfaced on the growspace payload at `irrigation.program`, which carries the resolved `stage`/`week` even when nothing matched (so a card can say _which_ week found no slot), the `slot`, that slot's `recipe` resolved through the library, the growspace's `auto_advance`, and the [[Program Progression]] block. `null` when nothing is bound or the bound id names no program; `slot` and `recipe` are independently `null`, the latter when a slot names a recipe since deleted.

**Recipe Stamp**
Applying an [[Irrigation Recipe]] writes its values into the ordinary editable strategy fields once and records `applied_recipe_id` + `recipe_applied_at`; the coordinator only ever reads the explicit fields, never the recipe. `domain/irrigation_recipe.resolve_recipe_application` answers what a stamp would write — the same module as the capture, so the two directions cannot disagree about what a stored percent means — and [[Irrigation Change]] owns the explicit write, validation, provenance and commit effects, reached through the `apply_irrigation_recipe` action and its matching WS command. [[Substrate-Relative Shot Storage]] is re-expressed in the target's own units on the way in: a Volume Mode growspace takes the percent and the composer converts it live, a Seconds Mode one is given the pump seconds that percent delivers through _its_ flow rate, pot volume and live plant count (refused, naming the missing input, when it cannot be). Identical semantics to the [[Steering Mode]] stamp (ADR-0012), including that applying **always writes** — re-applying the recipe already applied re-stamps, which doubles as "reset to this recipe" after hand-tuning. Applying a recipe whose `kind` is not the half the growspace is running (`irrigation_strategy.enabled` decides which) is refused before anything is resolved, so a refusal changes nothing. `applied_recipe_id` is nullable and `None` means "never applied", a real third state. No drift hash is stored: because recipes are held by reference, "has the grower tweaked since applying?" is `recipe_has_drifted` — the resolution re-run and compared against the live fields — surfaced on the growspace payload at `irrigation.applied_recipe_drifted`, `null` when no recipe was ever applied or the applied one has since been deleted. Each successful explicit stamp writes one logbook entry naming the recipe and both media when logbook recording is enabled. Automatic [[Program Progression]] performs the _same_ operation on the same module — it supplies only the program and stage/week its entry names — so both paths share one resolution, one validation, one provenance derivation and one commit tail (ADR-0046).

**Recipe Edit**
Correcting a stored [[Irrigation Recipe]] in place — its name, and the values of the one half its `kind` holds — through `domain/irrigation_recipe.edit_recipe`, the library's `async_update_recipe` and the `update_irrigation_recipe` action and WS command. The counterpart to capture, and in the same module for the same reason [[Recipe Stamp]] is: all three answer one question about what a stored percent means, and an edit sets a percent of substrate volume rather than pump seconds, so unlike capture it has no plumbing to recover and no refusal path of that kind. The edit is **sparse** — an unnamed field keeps what it stores, which is what lets a card built against an older contract correct one setpoint without resetting one it never knew about — and validated in full before anything is written, so a refusal leaves the library untouched. `id`, `kind`, `created_at` and every [[Recipe Provenance]] field are absent from the signature rather than merely ignored: provenance describes where the recipe came from, and rewriting it would turn a record of something that happened into a claim about something that did not; switching `kind` would be a capture, since the other half does not exist to be filled in. Editing changes **no growspace** — apply is by value, so a tent holds the numbers and not a live link, which is exactly what makes a recipe safe to edit; what a grower sees afterwards is `applied_recipe_drifted` turning true on the tents carrying it, because they no longer hold what the recipe now says. The library mutates its own stored instance rather than replacing it, matching `get_recipe`'s promise that an edit is visible to everything pointing at the recipe.

**Program Hold**
The single safe default of the [[Irrigation Program]] layer: when the program has no unambiguous instruction, nothing changes. It covers three causes with one rule — a week with no slot, a week past the end of the program, and (under auto-advance) a growspace whose fields have drifted from its [[Recipe Stamp]]. Carrying the previous week's recipe forward into an undefined week was rejected as producing actuation from the _absence_ of data; overwriting drift under auto-advance was rejected because it makes hand-tuning worthless and the damage stays invisible until the plants show it. Auto-advance is opt-in (`program_auto_advance` on `IrrigationConfig`, defaulting off, written through the [[Irrigation Change]] settings seam exactly as the `auto_advance_p1_to_p2` / `auto_advance_p2_to_p3` flags beside it are); with it off the card recommends and the grower confirms. Assigning a program **binds only** and does not apply — except when auto-advance is already on, which is the same consent expressed in advance, so `assign_irrigation_program` runs [[Program Progression]] once rather than making the grower wait a refresh interval to see it honoured.

Holding is **reported, not silent**. `domain/irrigation_program.ProgramHold` names the cause — `no_position`, `no_slot`, `program_complete`, `recipe_missing`, `drifted`, `not_applicable` — because the behaviour being identical is precisely why a finished run would otherwise read as a broken plan. Two more causes join the ADR's three once the rule has to act rather than only report: a slot naming a recipe since deleted (a gap, which can never actuate), and a recipe that cannot be stamped into _this_ growspace at all — the half it is not running, or a Seconds Mode target lacking the plumbing its percents need. Those two and `drifted` are the holds that block a stamp the grower opted into, so they notify as well as report, once per `(stage, week, cause)` rather than on every refresh; the quiet holds are payload-only, since a plan that skips weeks would otherwise notify on every one of them.
_Avoid_: skip (implies the week was passed over rather than deliberately left alone), fail.

**Program Progression**
What the [[Irrigation Program]] layer will _do_ about a growspace's current [[Program Slot Resolution]], and the thing that does it. `domain/irrigation_program.resolve_program_progression` is the rule — pure, judging only facts handed to it — and answers one of four states: `up_to_date` (the growspace already holds the slot's recipe), `available` (a new week's recipe is ready and auto-advance is off, so the grower applies it), `due` (auto-advance owes a stamp), and `held` with a [[Program Hold]] cause. `irrigation_program_progression.py` gathers the facts and acts: `resolve_program_position` is the **one** resolution both the payload and the coordinator's refresh read, so a card can never say a week is held while the tick stamps it, and `IrrigationProgramProgression` runs it for every growspace before the payload is built. A `due` stamp is the same [[Irrigation Change]] recipe operation an explicit [[Recipe Stamp]] submits, carrying one extra value — a `ProgramAdvance` naming the program and the week — so progression keeps slot selection, consent and the [[Program Hold]] while recipe resolution, validation, provenance and commit effects stay with the write module. It records the same `applied_recipe_id` + `recipe_applied_at`, which is exactly what makes it happen **once**: the next evaluation reads that provenance, finds the slot's recipe already applied, and answers `up_to_date`. Drift discovered _after_ that stamp is therefore never written back over; only drift from a **different** recipe than the week now calls for holds the advance. Each automatic stamp writes one logbook entry naming the program, the week and the recipe, after the commit that earned it — a raised commit restores the prior setpoints, schedules and provenance, says nothing, and leaves the week still owed, so the next eligible evaluation retries. Surfaced at `irrigation.program.progression` as `{state, hold, detail}`, where `detail` is the one grower-facing sentence the payload, the log line and the notification all share.
_Avoid_: auto-apply (names the happy path only, and the holds are the point), advance (ambiguous with the [[Steering Phase Machine]]'s P1→P2 advance).

**Recipe Week Resolution**
Which `(stage, week)` slot a growspace is in, answered by `resolve_feed_stage_week` — the same seam as [[Active Feed EC Target]], unchanged: furthest-along live stage, `days_to_week` of the greatest [[Current Stage Age]] within it. Reused rather than given an irrigation-specific rule so one card never shows two different weeks for one tent. Accepted consequence: in a mixed-stage tent the furthest-along schedule **over-waters the younger cohort**, which inverts the risk the rule was originally chosen for (never under-feeding). There is no per-plant escape — one pump, one substrate line — so the mitigation is that progression confirms by default rather than a second week calculator.

**Environment Patch**
The value a writer submits to change a growspace's `EnvironmentConfig`: the grower's edit, applied under **patch semantics** — an absent field means _keep the existing value_; an explicitly present field (including an empty list/dict) is a deliberate set or clear. Built and applied by `domain/environment_patch.py` (the [[Pump Cycle Gate]] / [[EC State]] precedent: pure, no `hass`), the one place EnvironmentConfig merge rules live (ADR-0026). **Build validates, apply is total**: writer-specific builders (`patch_from_service_call`, `patch_from_flow_options`, and per-sub-config builders for the narrow fan/grow-light writers) front-load all validation — singular→plural alias normalisation (the shadow singular is re-derived _after_ merge, so a stale singular can never resurrect a deliberately cleared plural), per-item key filtering for tanks/sensor groups (invalid items dropped as warnings, preserving today's lenient behaviour), and the stage/optimal VPD validators — so `apply_environment_patch(current, patch)` never raises on a built patch. `current=None` applies onto dataclass defaults; this pure path is also the one-time options-blob migration. Merge behaviour derives entirely from the [[Environment Field Ownership]] table; apply returns an [[Environment Patch Verdict]], and runtime writers commit it through one shared effect shell (`async_commit_environment_patch`) that owns the assign → save → [[Camera Assignment]] continuity reconciliation → refresh → targeted controller restarts → exhaust-repair re-evaluation ordering — a writer can no more forget an effect than a field. Hand-built `EnvironmentConfig(...)` rebuilds outside the module are forbidden. Supersedes the previous full-replace contract of `configure_environment`.
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

## Label Rendering

**Label Rendering Seam**
The fixed order every printed label passes through, implemented in `labels/`: a content snapshot, a layout and a [[Capability Profile]] are compiled by `canonical.compile_layout` into a [[Label Render Plan]], and a printer adapter realises the plan. Templates, calibration sheets and Classic requests from released cards — strain, plant and batch, preview and print alike — all take that one compiler, which is what stops a preview and its print from disagreeing. Nothing upstream of the compiler knows what a printer is; nothing downstream of it decides what a label says or where anything sits. Adding a second printer brand is a change behind this seam rather than to it.

**Label Content**
The retired fixed renderer's input: title, body lines, logo, QR payload, printed-on stamp, already filtered. No entry point builds one any more; it survives only with `renderer.render`, as the reference the [[Compatibility Layout]] goldens are proven byte-identical against. The Classic Path's content is now a compatibility content snapshot.

**Label Render Plan**
One composed label — every element placed on a known [[Canvas]] in device pixels, plus a _symbolic_ density. A printer adapter's only input. Density stays a word here because the same word means different heat on different hardware; mapping it onto a device scale is the adapter's job.

**Canvas**
The printable extent of one label in device pixels. Five Label Size identities (`50x30`, `40x30`, `50x50`, `50x80`, `50x15`) resolve to canvases; an absent or unrecognised size resolves to the 400×240 reference, which Classic callers have always been allowed to rely on. Composition is written against that reference and scaled per axis, so a stock with a different aspect ratio stretches.

**Compatibility Adapter**
`labels/classic.py`, the only module that understands the pre-template `print_label` request: subject as `plant_id` or bare strain, breeder/lineage overrides over strain-library meta, `fields` visibility flags, `base_url`, `qr_target`. It resolves the request once into a compatibility content snapshot, picks the [[Compatibility Layout]] for its legacy size and visible fields, and compiles both against a compatibility profile through the same compiler Templates use. Caller-supplied URLs stay confined to it. It refuses, by name and before sending, a raster or density the selected printer's driver cannot take — except the 16-pixel overhang every 50 mm Classic label has always run past a 384-dot B1/B21 head, which is a known, accepted legacy deviation. The response is the printer integration's, untouched; the canonical identities are logged. See the cross-repository specification in the workspace hub, `docs/design/label-compatibility-rollout-and-acceptance.md`.

**Compatibility Layout**
The transient canonical [[Label Layout]] one Classic request compiles from, one per legacy Label Size and combination of visible fields, versioned as `growspace.classic-layout.v1/<size>/<fields>`. It binds only the private `classic.*` namespace and carries Classic styles the schema cannot express, so document validation refuses it: it can never be saved, published, exported, made a default or satisfy Template print eligibility. Its profile is provisional and names no printer. Every one of the 160 is pinned by a reviewed golden raster and proven byte-identical to the retired fixed renderer — see `tests/labels/classic_golden.py`.

**Classic Path**
The composition every released card prints: one 400×240 design stretched per axis onto the requested stock. Since hub #240 it is expressed as [[Compatibility Layout]]s and compiled by the same compiler as the [[Label Template Path]]; the fixed-coordinate `renderer.render` is reachable from no entry point and may be deleted once the adapter has shipped enabled in two stable releases (hub #232).

**Label Template Path**
The canonical composition in `labels/canonical/`: a validated [[Label Layout]] compiled against a [[Capability Profile]] into a [[Label Render Plan]], then rastered by the same printer adapter. Preview and print are the same call with one argument different — which is the only arrangement in which a preview can honestly stand in for a print. See the workspace hub's `docs/design/label-layout-and-rendering-seam.md`.

**Label Layout**
One complete printable design, as saved: a versioned [[Label Size]] reference and an ordered list of stable [[Label Element]]s with absolute millimetre frames, in the closed `growspace.label-layout` v1 schema. It holds no CSS, no browser pixels, no `imagespec`, no DPI, no density, no device and no resolved plant data; every one of those is chosen at render time, which is what lets one saved design print on different hardware without being rewritten. The `elements` array is back-to-front paint order and there is no separate z-index. Unknown fields are rejected rather than dropped, because dropping them is how a future document quietly becomes a lossy v1 one.

**Label Size**
A physical stock identity in millimetres, versioned (`growspace.stock.50x30.v1`) so a size is never inferred from a display name or from the Classic `50x30` spelling beside it. A [[Label Layout]] references one and never repeats its dimensions; a template's size cannot change, because converting a design between stocks is a transform, not an edit.

**Label Element**
One placed thing on a [[Label Layout]]: an opaque layout-unique `id`, an [[Element Frame]], a clockwise rotation from 0/90/180/270, a single content source, and one closed style object. Four variants only — `text`, `logo`, `qr`, `divider`. The ID is stable across moves, resizing, styling, reordering, publication and historical restore, which is what lets a diagnostic name an element and an editor select it.

**Element Frame**
An element's axis-aligned rectangle in physical millimetres on the unrotated stock, quantized to 0.01 mm. It is the post-rotation occupied and clipped rectangle, so rotating never moves an element. Geometry finer than the quantum is rejected rather than rounded, and geometry outside the stock cannot publish; neither is ever repaired.

**Content Binding**
A symbolic request for content — a catalogue ID plus a closed parameter object — never a resolved string, a generated URL, a format string or an expression. The v1 catalogue is `growspace.label-bindings.v1`; each entry fixes which element kinds and print contexts it serves, what its parameters mean, and whether absence blocks, warns and omits, or cannot happen. Every publishable [[Label Layout]] carries at least one text element bound to `strain.name`; a literal does not satisfy it. Version 1 has exactly ten: strain name, phenotype, breeder, lineage, breeder logo and print date in every context, and stage start date, stage-and-age, plant ID and plant link only where a plant exists. Captions come from `presentation`, date shape from `date_style`, and the QR form from `target` — all closed sets, none of them a string the document supplies.

**Label Content Snapshot**
What one subject says, resolved once and frozen: the normalized value behind every binding, the captured breeder logo _by value_, both QR URIs, why each absent binding is absent, the record-level diagnostics resolution produced, and the locale, time zone and instant it was all read against. Taken before rendering and never re-resolved, so a preview, its print and every retry read the same content — which is the only arrangement in which a replacement label matches the one it replaces after the plant, the library row, the breeder's logo, the URL configuration or the clock has moved. Its digest is the content identity a [[Render Context]] records. A batch captures one per record against one shared instant, so an age cannot tick over between items.

**Source Adapter**
The only thing that reads integration state for a label, in `labels/canonical/subjects.py`. A caller names a saved strain or a live plant; the adapter reads the strain-library row, the plant, the current stage's [[Lifecycle Timestamp]], the breeder's logo bytes and the configured plant route, and hands raw facts to one normalizer. A plant's own strain and phenotype names are its identity and never come from the library; breeder, lineage and the dynamic logo come only from its captured library relationship and never from a dialog, an entity attribute or a caller override. No public label operation accepts a field value, a caption, a base URL or asset bytes.

**Content Absence**
Why one binding has nothing to say. The catalogue's missing policy decides what absence _does_ — block, warn and omit, or cannot happen; this records what happened, so a strain with no breeder, a plant whose strain is not in the library at all, a logo that would not decode, a stage whose start date is empty and a QR route that could not be built do not all arrive as the same warning. An unsupported binding for the context is a fifth thing again: a plant line on a strain label warns, keeps its frame and reflows nothing.

**Representative Subject**
A versioned fixture subject an editor previews a layout against, in `labels/canonical/fixtures.py`. Three families — typical, long content, missing optional — in each of the three print contexts, every value fixed so that an editor comparing two layouts and a test comparing two rasters both have the content as the constant. They are raw facts like any record's and normalize through the same resolver, so a preview cannot acquire behaviour a printed record lacks. The batch-item fixtures are the plant ones in the batch context rather than a second set to keep in agreement.

**Style Token**
An opaque, versioned backend-owned printable resource or policy — a font face, a leading, a monochrome conversion rule. A token resolves to a deterministic file or rule, never to browser CSS, and a changed definition gets a new version rather than a new meaning. A missing token is a named incompatibility, never a substitution.

**Capability Profile**
One immutable printer-class, stock, orientation, resolution, printhead, Printable Area, Safe Area, element-rotation, density and [[Calibrated Limits]] contract, selected per render. It is why "203 dpi" is not a global property: the same [[Label Layout]] compiles to different pixels on different profiles without changing a millimetre. It declares three nested regions in the stock's own unrotated millimetres — the physical stock, the calibrated [[Printable Area]] inside it and the recommended [[Safe Area]] inside that — and which clockwise element rotations this combination really realises, so an unsupported angle is refused by name rather than mapped to a neighbour. It also declares its [[Feed Axis]], because "feed alignment" is a measurement in one direction and no stock's dimensions imply which. A **provisional** profile has enough known geometry to render and cannot authorize a production print; promotion to product-verified is a physical-evidence decision. The profile's evidence state is a _claim_: product-verified is honoured only with a complete, current [[Release Evidence Record]] attached, and a claim without one is advertised, judged and refused as provisional, with the missing parts named in `evidence_invalidated_by`. The first one is `growspace.profile.niimbot-b1.50x30.v1`, whose Printable Area is 48 mm rather than the stock's 50 — 384 printhead pixels at 203 dpi — because a 400-pixel raster for a 384-pixel head is a failure the transport does not reject and no preview would show. It is product-verified on a Release Evidence Record taken on 2026-09-22, and that record covers only the device model it was printed on — `B1`, as the printer integration registers it — so a production print to a B21 or a B1 Pro — or to a B1 Home Assistant registered before the printer had answered, whose model is still empty — is refused with `printer_model_not_covered` however alike their datasheets are. Like every refusal about a raster that exists, an operator may print past it. Promotion raised its text floor from the declared 1.6 mm to the 2.2 mm the paper proved readable.

**Printable Area**
The region of one stock a profile can place ink in without known mechanical clipping. Compiled ink outside it is an error. It is not the stock: on the shipped B1 profile it is 2 mm narrower, and geometry the layout put in that strip is diagnosed rather than moved.

**Safe Area**
The more conservative inset inside the [[Printable Area]]. Ink inside the Printable Area but outside the Safe Area warns — it prints, close to an edge. A frame may cross it as long as its resolved ink does not, because the diagnostic describes the compiled outcome rather than a bounding box.

**Calibrated Limits**
The thresholds below which one profile's output stops being readable: the text readable floor and the comfort threshold above it, the QR module floor, quiet-zone requirement, verified target length and permitted correction levels, the minimum effective image resolution and the thinnest reproducible divider. Every one of them is an output of the physical evidence matrix, which is why a profile carries its own instead of deriving one from DPI — and why they are marked unmeasured while the profile carrying them is provisional, so no unverified constant is ever the last thing between a layout and paper.

**Element Ink**
What one element really paints, as opposed to what its frame reserves: a one-bit mask on the raster's grid plus the measurements behind it — resolved font size, the lines that survived fitting, missing glyphs, QR version, module scale and quiet zone, an image's effective resolution, a divider's thickness. Every geometry is reproduced from the pinned renderer's own — the same fitting search, the same integer module scale anchored at the frame's top-left, the same centred contain — so overlap, occlusion and Safe Area excursions are judged from pixels rather than rectangles. Where the backend cannot reproduce it (a font this installation does not hold, an image behind an HTTP URL validation must not fetch) the basis is `frame` and every check that needed a measurement says it was not taken.

**Protected QR Area**
The square a QR really pastes — its matrix and complete quiet zone. Any other element's ink inside it is an error whatever the paint order, because a scanner does not care which mark was drawn first.

**Render Context**
The complete identity of one render: layout digest, content-snapshot identity, profile and its evidence state, local-calibration identity, density and its device value, locale, time zone, captured instant, the digest of every font file that was really measured, and the compiler, renderer, adapter, text-toolchain, QR-model, safety-policy and catalogue versions, each recorded separately. Its digest is the **cache identity** — two requests sharing it share a raster, and anything else, however similar, does not. A font, profile or compiler update therefore invalidates a cached raster without pretending the saved layout changed. The same context without the two fields that decide what a raster may _do_ rather than what it _is_ — the operation and the local-calibration identity — is its [[Raster Identity]].

**Render Result**
What the canonical operation returns: the authoritative monochrome PNG as the renderer produced it, the [[Render Context]], the [[Capability Profile]] with its regions and [[Calibrated Limits]], one outcome and one [[Element Ink]] record per stable element ID, every graded overlap pair, every diagnostic of every layer with the [[Recovery Route]] that clears it, and one [[Print Eligibility]] answer per operation. Eligibility is decided here and read by the card; it is never inferred from a warning count on the other side of the wire. A provisional profile yields an exact raster and no production eligibility, because an exact bitmap is a claim about the driver and not about the paper.

**Print Eligibility**
What one exact Render Result is allowed to do, answered per operation rather than as one boolean: draft autosave and candidate validation always, preview with a raster, publish without blocking diagnostics, administrator test print additionally without them, and production single print and batch preflight additionally on a product-verified profile with current local calibration. Each refusal names every independent reason rather than the first, because fixing one of three and finding the button still disabled is how a recovery path loses people. Local calibration is an input here and belongs to the calibration route; its absence is a named refusal and its staleness a different one, never both at once. What a _result_ authorizes is only half the answer: [[Print Provenance]] is the other half, and it is asked of the request rather than of the raster. A refusal is advice, not a wall, wherever a raster exists: an operator may print past blocking diagnostics, an unproven profile or printer model, and missing or stale calibration, because they have the preview in front of them and the label in their hand. What no consent waives is anything that would put something other than the approved preview on paper — no raster, a draft, fixture content, or a result that is no longer current.

**Recovery Route**
The kind of correction one diagnostic leads to — the element, the record, profile selection, calibration, the template itself, or simply asking again. It names a destination, never a repair: nothing is applied for the user, and there is no "fix all". A device error routes to profile selection or calibration rather than sending someone searching through element controls.

**Factory Template**
A layout the integration ships, at a shipped revision, identified by a stable namespaced ID. An upgrade may append a new revision and advance the head; it never edits a revision in place and never changes a template someone copied. Factory and named templates cross the same renderer interface — factory status creates no second rendering implementation. It is also the designated fallback for its [[Label Size]] and cannot be renamed, published to or deleted, which is what makes it safe to be the thing every other failure resolves to.

**Release Evidence Record**
The physical proof behind one product-verified [[Capability Profile]]: the exact printer model, firmware, driver, stock and procedure, the operator and the reviewer, and one measured, passed, artifact-backed result for every row of the matrix — edges, rotation, text, QR, logos, density, repeatability and batch — covering every rotation and density the profile permits. It names the profile definition it measured and the compiler, renderer, adapter, text toolchain, style tokens, QR model and safety policy it depended on, so a change to any of them returns the profile to provisional by itself. CI cannot produce one; it can only refuse a claim that lacks one.

**Golden Raster**
The pinned [[Raster Inputs]] of one cell of a matrix derived from the catalogues — every [[Factory Template]] and an element-kind coverage layout on every profile, in every representative family, print context, permitted rotation and distinct date order — with the PNG the pinned renderer really draws from them beside it as reviewed evidence. Output may not change without a named compiler, renderer, font, asset, policy, profile or layout identity changing with it, and every recording carries a reviewer and a reason. Regenerating to make a red test green is exactly what the recorder refuses. See `tests/labels/golden_matrix.py`.

**Diagnostic Catalogue**
Every diagnostic code the label pipeline can produce, with the layer it appears at, the severities it may carry and the only parameters copy may interpolate. The card localizes by code, so a code missing here is a sentence nobody wrote; it is published beside the refusal codes and eligibility blockers as the `label_localization_catalogue_v1` contract fixture, and every diagnostic the product emits under test is held to it.

## Label Template Library

**Template Library**
One Home Assistant config entry's authoritative templates, defaults, revision history and drafts, in `labels/library/`. The config entry ID is in the `.storage` key, so the isolation is the store rather than a rule applied over a shared one: an identity minted under one entry is simply absent from another, and two entries may hold the same names without sharing anything. The card is an authenticated editor and consumer of this model, never a second source of truth — browser storage may cache it for responsiveness and cannot establish a template, default, revision or draft. See the workspace hub's `docs/design/label-template-lifecycle.md`.

**Named Template**
An administrator-created [[Label Layout]] under an opaque UUID, belonging permanently to one [[Label Size]]. The UUID survives rename, revision and restore; the name is the current [[Template Revision]]'s, trimmed and case-insensitively unique within that size and free at any other. The size never changes, because converting a design between stocks is a transform rather than an edit.

**Template Revision**
One immutable published state beneath a [[Named Template]]'s UUID, numbered from 1. Immutable after commit means the head moves only by appending: nothing edits a revision, which is what lets a print reference one and stay truthful about what it printed. Each records its instant, the acting user, the operation kind, its parent, and the structural provenance of where its content came from — the [[Factory Template]] revision, the source template revision, or the blank it started as.

**Template Draft**
One administrator's unpublished, durable editing state, based on one [[Template Revision]] or on a [[Label Size]] alone. Exactly one per administrator and template, and one untitled one per administrator and size. Its payload is opaque and may be invalid: autosave keeps whatever the editor last had, because an autosave that dropped invalid work would make every diagnostic a threat to the work. It is private to its owner, survives a restart, and becomes a `LabelLayout` at exactly one moment — publication.

**Publication Gate**
What a [[Template Draft]] must pass to become a [[Template Revision]]: the document layer in full — the closed schema, the 0.01 mm quantum, identity and paint order, supported rotation, and the required `strain.name` text element inside a frame that really fits the stock. Deliberately not the profile-relative layers. A [[Capability Profile]] is chosen per render, so judging ink coverage or safe areas at publication would pin a saved design to today's one profile and refuse a perfectly good 50×50 layout for the sole reason that no 50×50 profile has shipped. Those judgements are [[Print Eligibility]]'s, where a profile exists.

**Effective Default**
What one [[Label Size]] resolves to: the administrator's optional override where there is a usable one, and that size's [[Factory Template]] where there is not. Resolution produces one concrete revision at the start of an operation, so a later save or default change cannot reach back into a render or print that already has one. An override naming a template that has gone, or a revision the catalogues have moved past, exposes the fallback rather than failing — losing an override must not cost a stock its printing — and an override is never silently re-pointed to make that true.

**Library Generation**
A monotonic integer identifying one [[Template Library]]'s committed state, advanced once per committed mutation of templates or defaults. Draft autosave does not advance it: the generation identifies the library other clients can see, and announcing every keystroke as a library change would make everybody refresh for something none of them can read. A [[Template Draft]]'s own version number is the same idea one scope down, and is what an autosave compares against.

**Stale Draft**
A [[Template Draft]] whose base [[Template Revision]] is no longer its template's head, because somebody else published while it was open. It is refused publication and nothing else: it keeps its payload, stays previewable, and its owner discards it, reloads it from the new head, reapplies the parts worth keeping by hand, replaces it from the factory, or takes it out from under the collision with [[Save As]]. **Layouts are never merged.** Two independently edited designs are structurally mergeable and physically unsafe to merge — composed moves, resizes and typography produce overlap, clipping and unreadable text neither editor asked for — so the choice stays with a person. An untitled draft is based on nothing and is never stale; a draft whose template has gone is an orphan, which is a different condition with a different remedy.

**Revision Operation**
Which act appended a [[Template Revision]]: a publication of a [[Template Draft]], a [[Rename]], a [[Duplicate]], a [[Save As]] or a [[Historical Restore]]. Recorded on the revision rather than inferred, because a history that called them all "publish" could not tell a restore from the edit it reached back past — and reading a template's history is how an administrator decides what to restore.

**Rename**
Giving a [[Named Template]] a new name by appending a [[Template Revision]] that carries the previous one's document unchanged. The UUID does not move, so no default override, print reference or draft follows the name. It is an append rather than an edit of the head because a name is part of what a revision says about itself: rewriting it in place would silently change what an old print claims. It advances the head, so an open [[Template Draft]] becomes a [[Stale Draft]] exactly as it would after any other publication — the documented rule rather than an exception carved out for names.

**Duplicate**
Copying a saved head — a [[Named Template]]'s or a [[Factory Template]]'s — into a second [[Named Template]] at revision 1, under a fresh UUID and a free name. The _saved_ head, never a [[Template Draft]]: an administrator with unpublished work open who duplicates is asking for a copy of what the library holds, and quietly copying the draft would publish work they had not chosen to publish. Duplicating a [[Factory Template]] is how a shipped design becomes one that stops following the installed version.

**Save As**
Publishing the active [[Template Draft]] under a fresh UUID instead of as its template's next revision, clearing the draft in the same commit. The remedy a [[Stale Draft]] has left once merging is off the table, and the way an edit becomes a second label rather than a new version of the first. Staleness is deliberately not a refusal here: it is the condition this exists for. The source template is not touched.

**Historical Restore**
Bringing an older [[Template Revision]]'s layout back by appending it as a _new_ head with provenance naming what it was copied from. Never by rewinding: the revisions in between stay where they are, so the design a template was taken back _from_ is still in a history that claims to be complete. The name does not travel with the layout — content and identity are separate axes, and restoring a design is not a request to be renamed. A revision the catalogues have moved past is preserved and readable but cannot be made the head, because that would put a layout nothing can render in front of every print resolving this template.

**Factory Replacement**
Starting a [[Named Template]]'s [[Template Draft]] again from a shipped [[Factory Template]] while the template keeps its UUID, its name and every revision it has. A draft operation and only that: it advances no [[Library Generation]] and fires no [[Library Change Event]], and the saved layout changes when that draft is published and at no other moment. The payload it replaced goes to the draft's [[Recovery Payload]] slot. A stock the integration ships nothing for says so rather than being handed another size's design.

**Recovery Payload**
Editing work the server declined to make current, kept in one slot beside the [[Template Draft]] it was meant for: the payload of an autosave refused by the version compare, the payload a reload replaced, or the one a [[Factory Replacement]] replaced. It exists because refusing a write must not be the same act as deleting it — the refused client may be the one that has been edited for an hour. It is never merged into the document and never published from; an ordinary autosave leaves it alone, and only an explicit discard, or the draft itself going, clears it.

**Commit Record**
One committed mutation, remembered by the idempotency key that made it, so a retry of a call whose answer was lost finds the first attempt instead of publishing a second revision or advancing the [[Library Generation]] again. It holds a _locator_ — which draft slot, which template and revision, which [[Label Size]] — and never a result, so the ledger cannot describe a state the library is not in and carries no second copy of anybody's document. A key belongs to the actor that spent it, and presenting a spent key with different input is refused rather than performed. The ledger is persisted and capped: the window a key protects is seconds, and an unbounded one would grow with every autosave.

**Library Change Event**
The one Home Assistant bus event a committed library mutation fires, naming the new [[Library Generation]], the one it replaced, the operation kind and the identities it touched — never the document. Only an authenticated Home Assistant client can subscribe to the bus, which is the whole of its authentication. `previous_generation` is what makes a gap detectable: a client holding generation N applies an event whose previous is N and refreshes its whole snapshot when it is anything else. Taking that snapshot is a read, so recovering from a gap cannot cost an editor its unsaved work.

**Template Tombstone**
One soft-deleted [[Named Template]], kept whole for 30 days: the record _is_ the template, so restoring returns the same UUID and the same revision history rather than something resembling them. Deletion, clearing any [[Effective Default]] override that named it, and orphaning its drafts are one commit. A [[Factory Template]] cannot be deleted. The expiry instant is stored rather than computed, so shortening the window later cannot retroactively expire somebody's deletion, and an expired tombstone is refused restoration rather than quietly honoured.

**Restore Deletion**
Bringing a [[Template Tombstone]]'s template back under the identity it always had. It never reclaims the default — whatever was selected while it was gone has been printing ever since — and it never takes a name another template of that stock has used in the meantime: a conflict is refused, and the new name an administrator supplies arrives as a [[Rename]] revision, because a name lives on a revision. [[Orphaned Draft]]s reconnect by doing nothing, since a draft names the template it is for.

**Orphaned Draft**
A [[Template Draft]] whose template has been deleted. Kept rather than removed with it, because deleting a template is not a decision about somebody else's unpublished work. It is read-only recovery work: its owner may read it, preview it, export it, discard it, or publish it under a fresh identity with [[Save As]], but not carry on editing towards a revision that can never be appended. Distinct from a [[Stale Draft]], which has a newer head to reload from where an orphan has none. It expires with the [[Template Tombstone]] it belongs to.

**Tombstone Collection**
The one operation in the library that destroys anything: removing the [[Template Tombstone]]s whose window has closed, together with the [[Orphaned Draft]]s still waiting on them. Explicit and administrator-only rather than something a load does on the way past — opening a library must not write, and "your templates were collected" must not be a thing that happened while nobody was looking. A run that finds nothing expired writes nothing and advances no [[Library Generation]].

**Quarantined Template**
A [[Named Template]] whose head [[Template Revision]] no longer passes the [[Publication Gate]], because a catalogue it references has moved on beneath it. It is kept exactly as saved — never clamped, re-pointed, stripped or migrated — and stays listed with its diagnostics, exportable, openable as a draft for repair, and available for a [[Historical Restore]] of a revision that still validates. It is refused only where using it would mean printing it: resolution and default selection. Quarantine is computed from today's catalogues rather than stored, so it clears itself when the upgrade that fixes it arrives.

**Portable Bundle**
A document sharing published [[Named Template]]s with another installation: current revisions with their identities, [[Label Size]], structural provenance and dependency lists, under a format version and a checksum. It carries no history, drafts, defaults, tombstones, [[Factory Template]] definitions or Home Assistant user IDs — a share that carried those would be a restore wearing a share's name. Importing is additive, administrator-only, and all-or-nothing: everything is staged and validated before anything is written. An identity nobody holds arrives as itself; the same identity with the same content is a no-op; the same identity with different content, or an identity deleted here, is refused until the administrator asks for a copy under a fresh UUID. Unknown dependencies and layouts that no longer compile are refused by name, never dropped or substituted.

**Library Backup**
The complete document one [[Template Library]] is: every [[Named Template]] with its full history, the default overrides, every administrator's [[Template Draft]]s, the [[Template Tombstone]]s with their windows still running, the idempotency ledger and the [[Library Generation]]. Restoring one _replaces_ rather than merges, because two libraries cannot be reconciled without silently choosing for every UUID they both hold. Everything is validated before the single write, so a failure leaves the current library untouched, and the generation comes back exactly as the backup held it — which can be lower than the current one, which is why the [[Library Change Event]] matters most here.

**Store Containment**
What happens when a [[Template Library]]'s `.storage` document was written at a newer store version: it is left byte-for-byte, nothing is read out of it — reads included, since half a library answered confidently is how a newer store becomes a lossy older one — the library reports itself read-only, and a Home Assistant repair issue names the found and supported versions. Every other Growspace Manager feature carries on; the way out is the newer integration or a [[Library Backup]] this version can read. There is deliberately no downgrade and no reset.

## Label Calibration and Printing

**Local Calibration**
Where one installed printer really puts ink, measured on that printer with that roll on it. It is the second of the two independent proofs a production print needs: [[Capability Profile]] evidence proves a printer _class_, stock, orientation, toolchain and density mapping, and no amount of it can know that the roll in this machine is loaded 0.8 mm off. The reverse holds just as hard — one alignment label cannot establish that a font is readable, that a QR scans or that density maps correctly, so measuring a printer never promotes its class. A record is immutable: re-calibrating appends beside it, because "what was this printer measured at when that label printed?" has to keep having an answer for as long as the label is in the grow room.

**Calibration Label**
The standardized sheet every printer is measured on, constructed from a [[Capability Profile]] rather than drawn for one stock. Four edge scales of staggered ticks stepping 0.5 mm inward from the declared [[Printable Area]], a signed ruler along the [[Feed Axis]] centred on the printable midpoint, and an identity block naming the profile, resolution, stock, mounting, feed axis and density it came out of. Every mark sits _inside_ the declared Printable Area — ink outside it is an error, so a sheet drawn to the stock's edges would be the one print the safety policy refuses, and that print is the one that diagnoses the printer. Ticks are staggered along the edge rather than stacked because 0.5 mm at 203 dpi is four dots and a stacked column would merge into a smear. It is the one thing a **provisional** profile can print, which is how a provisional profile stops being one.

**Evidence Label**
The one-page print a [[Release Evidence Record]] is mostly read off, constructed from a [[Capability Profile]] so every probe is that profile's own claim rather than a number chosen for the sheet. It carries the [[Calibration Label]]'s edge scales in the same positions — so the four edge offsets read off either sheet are the same numbers, and feed alignment is the offset along the [[Feed Axis]] — and inside them three QR targets (the shortest real plant route, a typical dashboard URL, and exactly the claimed maximum encoded bytes, ending with its own length) each at the claimed minimum dots per module, quiet zone and weakest claimed error correction; text at the readable floor and the comfort threshold in both faces, including accented and wrapped long text; the thinnest claimed rule and twice it; and the profile and density; when a copy printed is the run record's to say. A profile whose readable floor is its comfort threshold gets that size probed once rather than twice. One print per semantic density covers most of the matrix. It prints through the test-print gate like the Calibration Label, so a provisional profile can print it, and records nothing: what it proves is read off paper and a phone by a person. A logo is not on it, because the integration ships no asset to print. A missing glyph is not either, because the safety policy refuses to print one.

**Feed Axis**
Which of a stock's own axes the media travels along, declared by the [[Capability Profile]] and never derived from its dimensions: a 50×30 label can be slit either way round. On the shipped B1 profile it is the 30 mm axis, because the 384-dot printhead spans the other one and a head cannot also be the direction paper moves in. It is part of a [[Local Calibration]]'s identity, so a printer re-loaded with the roll turned is not the printer that was measured.

**Placement Measurement**
What an operator reads off a [[Calibration Label]]: four edge offsets and one signed feed displacement. Each edge value is how many millimetres of the declared [[Printable Area]] that edge does not reach, so it is never negative — a printer that reaches _further_ than declared is a profile understating itself, which is a profile correction rather than a local measurement. Feed is signed because media runs both early and long. Values are quantized to the document model's own 0.01 mm and bounded by the printable extent of the axis they are on, judged against the geometry the sheet was printed with rather than whichever profile is selected when the form is submitted. A large offset is accepted: a badly loaded roll really does lose four millimetres, and refusing that would refuse the measurement most worth having.

**Calibration Dependencies**
Everything one [[Placement Measurement]] was silently true of — the resolution, printhead, declared regions, density mapping, [[Calibrated Limits]], compiler, renderer, adapter, text toolchain, QR and safety policy, catalogues, the [[Calibration Label]]'s own version, the installation's shipped font digests and, where it can be read, the printer's firmware. Captured from the [[Render Context]] of the sheet that was actually printed, so four numbers can never be recorded against a render that did not happen. Two absences are decisions: the _selected_ density is not in it, because density is heat rather than placement and a record that went stale every time somebody printed darker would be asking for a re-measurement of something that did not move; and the profile's evidence state is not in it, because promotion to product-verified is exactly the transition a calibration is taken in anticipation of.

**Calibration Scope**
Which records are candidates for one print at all: the installed device, its printer class, the [[Label Size]] and the orientation. A record outside it is not a stale calibration of this print, it is a calibration of something else — so another printer reads as _unmeasured_ rather than as _stale_. Scope selects; [[Calibration Dependencies]] judge.

**Calibration Staleness**
Why a [[Local Calibration]] stops authorizing production. A changed dependency does it, and the refusal **names the field that moved** — "recalibrate" with no reason is indistinguishable from the product having forgotten. Elapsed time does not: a printer measured a year ago and untouched since still puts ink where it put ink, so age produces a warning recommending a check and never a refusal. A stale record contributes no identity and stays on file, because its audit value is intact even when its authority is not. Stale and missing are never reported together: they are mutually exclusive accounts of the same printer, and the wrong one of the two is the discouraging one.

**Raster Identity**
The [[Render Context]] digest with the operation and the local-calibration identity taken out — the two fields that decide what a raster may _do_ rather than what it _is_. It is what makes "the operator is printing what they approved" a comparison rather than an assurance: a preview, the test print taken of it, the production print that follows and every retry share it while their cache identities differ. An operator who previews, is told the printer needs calibrating, calibrates it and prints is therefore printing the raster they looked at — and the print is still judged afresh, because [[Print Eligibility]] is a separate question asked at the moment of the print.

**Raster Inputs**
The exact payload handed to the printer adapter — canvas, rotation, density and the compiled element list — with `preview` and `device_id` left out, because those decide where a bitmap goes and never what it is. Built once and digested before it is sent, so the identity recorded describes what really reached the printer integration rather than something reconstructed beside it. Two results sharing a [[Raster Identity]] hand over byte-identical raster inputs, and every print route asserts it rather than assuming it.

**Print Provenance**
The three facts a print route holds and a render cannot: whether the layout is a published [[Template Revision]] or a [[Factory Template]] rather than somebody's [[Template Draft]], whether the [[Label Content Snapshot]] is one real record's rather than a representative fixture's or a [[Calibration Label]]'s, and whether the [[Raster Identity]] the caller approved is still the one this render produces. Asked only of a production single print and a batch preflight. A test print asserts none of the three, which is exactly what makes it the operation a draft and a provisional profile can both reach.

**Print Route**
The three ways a label reaches paper, each asserting something different: the [[Calibration Label]], an administrator's test print, and a production print of one real record. All three **judge before they commit** — a render sends to the printer integration and only then reports its diagnostics, so each route renders a preview, decides on it, and commits only if that decision allows. The committing render is the judged one's bitmap because [[Raster Inputs]] are a pure function of the layout, the immutable content snapshot, the profile and the density, and the routes compare the digests rather than assume it. Calibration and test printing are administrators' operations; printing a label for a plant is any authenticated user's.

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

**Triage Alert**
A durable grower-attention record whose tagged type owns its evidence: `stress` and
`mold` carry Bayesian evidence, while `capture_continuity_break` carries camera-streak
evidence and no plant probability or AI reasoning. An equipment condition clearing and
the grower resolving its alert are separate facts.
_Avoid_: AI alert, diagnosis, notification

**Alert Monitor** (`alert_monitor.py`)
Consumes Bayesian stress and mold Evaluation Snapshot transitions plus [[Capture Continuity Break]] condition transitions and creates persistent [[Triage Alert]] records. Repeated active conditions are deduplicated per condition streak; a cleared condition re-arms alert creation, while grower resolution remains a separate acknowledgement. Its Inbox is bounded, but eviction never takes a Capture Continuity Break whose condition is still active, and the Inbox is never the authority for streak state: on recovery it is reconciled to the evidence, correcting an active alert's derived evidence in place and never manufacturing an alert for a condition that already cleared. An equipment condition is looked up by its [[Camera Assignment]] — the growspace and camera pair, never the camera alone — so two growspaces holding one camera keep two conditions and neither answers for the other. Stores records internally using a private storage dict and emits a public tagged-union wire format; these two formats must never be conflated.

**Alert Monitor — internal storage format**
Private tagged record stored in `growspace_manager.ai_alerts`. Every branch carries identity, growspace, timestamps, condition status and grower resolution; stress and mold branches carry Bayesian evidence and optional AI reasoning, while the Capture Continuity Break branch carries camera and streak evidence and forbids both.

**Alert Monitor — wire format**
Public tagged union emitted by `_serialize_alert()` and consumed by the card's `TriageAlertSchema`. Common fields carry identity, type, severity, presentation, condition status and resolution; branch evidence is mutually exclusive, so an equipment alert can never acquire a Bayesian probability or AI explanation.

**Triage Alert Severity**
Computed field added at serialization time. Maps `alert_type` to `severity`:

- `"stress"` → `"danger"` — plant stress is happening now, requires immediate action
- `"mold"` → `"warning"` — mold conditions are favorable (probabilistic), warrants watching
- `"capture_continuity_break"` → `"warning"` — scheduled camera evidence has stopped
  matching recent history and requires inspection

## Climate Fail-Safe

**Climate Fail-Safe**
What the humidifier, dehumidifier and exhaust controllers do once they cannot see (#792, ADR-0052). When every [[Control Input]] of a controller has been invalid for `sensor_timeout_minutes` (default 10), it goes to its [[Safe State]]. A shorter loss holds the last command. The controllers of a growspace share one `ClimateSafety` (`climate_safety.py`), which reads their inputs through one `SensorWatch` per sensor. Each controller re-evaluates once a minute as well as on sensor events, since a frozen sensor sends no events. Configured on `EnvironmentConfig.climate_fail_safe_config`. The rules are `domain/climate_fail_safe.py`'s.

**Safe State**
Where a controller in the [[Climate Fail-Safe]] drives its devices. For the humidifier and dehumidifier it is `humidifier_safe_state` / `dehumidifier_safe_state`: `off` (default), `on` or `hold` (leave the device as it is), never both `on`. For the exhaust it is `exhaust_fallback_speed` (default 50 %, clamped into the fan's `[min_speed, max_speed]`), reached only when _every_ regulation sensor has failed. Circulation has none and holds. A Safe State is applied past the short-cycle timers, and control resumes by itself once an input reads again.
_Avoid_: fallback mode, emergency state

**Fail-Safe Episode**
The time any controller of a growspace spends in its [[Safe State]]. It raises one push on the `SENSOR_INVALID` tier and one persistent notification naming every controller in it and what each is doing; a controller joining later only rewrites the notification. It ends with one recovery push when the last controller can see again, and a flapping sensor alerts at most once an hour.

**Humidity Interlock**
The rule that a growspace's humidifier and dehumidifier never run together: the **later demand wins**. A controller's demand begins when VPD crosses its on threshold. The device whose demand is later switches the running partner off before it starts, and the partner waits for it to finish rather than taking over again. A partner running without a demand of its own — switched on by hand, or in its [[Safe State]] — always gives way. Each takeover writes a logbook note on the device switched off.

**Maximum Continuous Runtime**
`humidifier_max_runtime_minutes` / `dehumidifier_max_runtime_minutes` on `climate_fail_safe_config` (default 0, off): a device seen on that long without a break is switched off, whether or not VPD reads, and its minimum off time is its rest. Nothing latches.

## Circulation Fan Controller

**CirculationFanController**
An optional per-growspace subsystem that drives all configured circulation actuators from an environmental demand signal on a fixed tick. Variable-speed devices receive a percentage clamped to the grower-defined `[min_speed, max_speed]` range; binary devices interpret demand above `min_speed` as on. In VPD mode the controller promises protective canopy circulation when VPD is low, not that internal circulation alone will regulate ambient VPD to the target.

**Regulation Layer**
Exactly one regulation mode is active at a time: `humidity`, `temperature`, or `vpd`. Humidity and temperature use direct linear mapping: below `(target − tolerance)` → `min_speed`; above `(target + tolerance)` → `max_speed`. VPD uses inverted linear mapping because low VPD calls for stronger canopy circulation: below `(target − tolerance)` → `max_speed`; above `(target + tolerance)` → `min_speed`. Every mode interpolates linearly inside its band, and `max_speed` always means the grower-configured ceiling rather than an unconditional 100%.

**Circulation VPD Observation**
The lowest valid reading among the growspace's configured VPD sensors, representing the most humid measured canopy zone. Unavailable or invalid readings are ignored; when none remain, regulation retains the last commanded speed because sensor failure does not establish environmental demand.
_Avoid_: first VPD sensor, average canopy VPD

**VPD Mode Temperature Safety Override**
When regulation mode is `vpd`, two additional thresholds apply: `critical_temp_low` and `critical_temp_high`. If the temperature sensor reading breaches either threshold, the override activates: high-temp breach drives fans to `max_speed`; low-temp breach drives fans to `min_speed`. The override remains active until the temperature returns within bounds plus `critical_temp_hysteresis`. While active, the override replaces VPD regulation and suspends dynamic-wind modulation, making the safety speed absolute.

**Dynamic Wind Layer**
Normally adds a sinusoidal ±offset to the regulation speed. At or below VPD's lower boundary, negative modulation is suppressed so an urgent low-VPD demand remains at the configured `max_speed`; during a temperature safety override, modulation is suspended entirely. The final speed is always clamped to `[min_speed, max_speed]`.

**CirculationFanConfig**
The growspace-local circulation policy: whether automatic control is enabled, which environmental demand signal it follows, its configured speed range and target band, its critical-temperature bounds, optional dynamic-wind behavior, and optional stage-aware VPD targets. A zero minimum remains valid and may turn circulation off when demand reaches the minimum; continuous airflow requires the grower to configure a nonzero minimum.

**Stage-Aware VPD Mode**
An optional sub-mode of VPD regulation (`stage_vpd_enabled = True`) that resolves the effective VPD target from the active plant stage and time of day (day/night) rather than the static `vpd_target`. Defaults for all nine stages (`seedling`, `clone`, `mother`, `veg`, `flower_early`, `flower_mid`, `flower_late`, `dry`, `cure`) are defined in `FAN_VPD_STAGE_DEFAULTS`. Falls back to `vpd_target` when the growspace has no plants or the current stage is not in the lookup table.

**Stage VPD Overrides**
A sparse dict stored on `CirculationFanConfig` as `stage_vpd_overrides`. Keyed by stage name (the string value of `PlantStage`, e.g. `"veg"`, `"flower_early"`); each entry is `{"day": float, "night": float}`. Only stages the user has explicitly edited are present — absent stages resolve to `FAN_VPD_STAGE_DEFAULTS`. Deleting all entries (or an individual entry) restores the default for that stage. Validation rules: values must be in the range 0.1–3.0 kPa; unknown stage keys are rejected (not silently dropped); each entry must contain both `"day"` and `"night"` keys — a half-specified entry is invalid.

**Fan Speed Composition**
`final_speed = clamp(regulation_speed + effective_wind_offset, min_speed, max_speed)` where `regulation_speed` is the output of the active regulation mode (or the temperature safety override when active). `effective_wind_offset` is zero when dynamic wind is disabled and cannot be negative while low VPD demands maximum circulation. The low-temperature safety override still takes precedence over low-VPD demand; Bayesian mold-risk output is not fed back into circulation demand.

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
Each tick computes three demand terms from the shared `domain/fan_control.py` helpers and drives the fan to the highest: a **temperature term** (`compute_fan_speed` — hotter tent → more exhaust), a **humidity term** (`compute_fan_speed` — more humid → more exhaust), and an **inverted VPD term** (`compute_inverted_fan_speed` — more exhaust when VPD is _below_ target, i.e. the air is too saturated). The result is `final = clamp(max(temperature, humidity, vpd_inverted), min_speed, max_speed)`. A sensor that is missing, unavailable, implausible or stale drops its term from the maximum; if none of the three read, the tick holds the last speed until the [[Climate Fail-Safe]] timeout, and then the exhaust runs at its fallback speed. When `stage_vpd_enabled` is set, the VPD target is resolved per stage and day/night via the shared `resolve_stage_vpd_target` (and `stage_vpd_overrides`), exactly like the circulation fan. The **Source-Air Gate** may drop individual terms before the maximum, and the **Exhaust Critical-Temp Override** is then composed on top of the gated result (see below).

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
An immutable record published by each Bayesian binary sensor (stress/mold/optimal) after every probability update, via `coordinator.services.notifications.report_evaluation()`. It records when the evaluation occurred and whether it contained valid observations, so capture-relative consumers can distinguish measured inactivity from an empty zero-probability result. The snapshot is the **only** interface between Bayesian sensors and the notification and Vision evidence subsystems; neither consumer holds live sensor entity references.

**Vision Analysis**
One Growspace Vision operation that either produces a Visual Embedding or rejects the Camera Snapshot as unusable.
_Avoid_: Vision Checkup, scoring, diagnosis

**Visual Embedding**
The model-versioned vector representation of one Camera Snapshot returned by a successful Vision Analysis.
_Avoid_: Anomaly score, health score, feature score

**Frame Quality Result**
The non-plant image measurements and any unusable-frame reasons returned by a Vision Analysis.
_Avoid_: Plant evidence, health evidence

**Frame Quality Gate**
The two-layer decision that admits or rejects a Camera Snapshot: an absolute floor applied by Growspace Vision to one image, and history-relative rails applied by Home Assistant to the returned Frame Quality Result.
_Avoid_: Image quality score, blur detector

**Quality History**
The trailing 30 accepted captures' Frame Quality Result signals for one camera, across light windows, against which the relative rails are evaluated. Rejected captures never enter it.
_Avoid_: Quality baseline, exposure baseline

**Baseline Bucket**
The Home Assistant-owned rolling recent history for one camera, light window, Grow Run, model version, and Framing Epoch against which Visual Embeddings may be compared.
_Avoid_: Vision-service baseline, global baseline

**Framing Epoch**
A period in which one camera's physical framing is treated as materially unchanged. A manual visual-baseline restart begins another epoch. V1 has no automatic camera-move detection because the structural signature cannot separate a move from a lens occlusion.
_Avoid_: Camera position, framing bucket

**Baseline State**
The comparison readiness of a Baseline Bucket: `monitoring`, `ready`, or `stale`.
_Avoid_: Validity flag, baseline confidence

**Visual Comparison Result**
The Home Assistant-owned result of interpreting a Vision Analysis against temporal context, including an Anomaly Score and any material-scene-change verdict.
_Avoid_: Evaluation Snapshot, analysis response, model result

**Camera Assignment**
One camera assigned to one Growspace — the unit a [[Capture Continuity Streak]] belongs to. A camera held by two Growspaces is two assignments whose evidence never pools, and un-assigning a camera ends its assignment rather than pausing it. An assignment begins after the newest capture already on record for that camera in that Growspace, so a returning camera — or a recreated Growspace with the same id — never inherits evidence from an earlier assignment.
_Avoid_: Camera, camera link, camera binding

**Capture Continuity Streak**
The run of consecutive non-comparable automatically scheduled captures accumulated for one [[Camera Assignment]], carrying its start, the capture that began it, count, per-reason counts, latest capture and whether the condition is active. Its authority is the Vision Evidence Store: after a restart or upgrade it is rebuilt by replaying every retained capture of its assignment through the same classification live evaluation uses — never from a window of recent rows, never from image files, and never from the [[Triage Alert]] Inbox. Retiring the assignment drops the streak, so re-adding the camera — or adding it to another Growspace — starts from nothing.
_Avoid_: Recent capture window, rolling streak, camera history

**Capture Continuity Break**
The equipment condition raised when a [[Capture Continuity Streak]] reaches three: three consecutive automatically scheduled captures for one [[Camera Assignment]] that are non-comparable, meaning quality-rejected or `material_scene_change`. It names no cause or plant condition. Manual captures neither advance nor reset the streak, and neither a transport failure nor an accepted capture whose comparison is unavailable advances or clears it. Later qualifying captures update the same [[Triage Alert]]'s evidence rather than raising another. Clearing the condition — by comparable scheduled evidence or by retiring the assignment — leaves the durable alert and any grower resolution untouched.
_Avoid_: Camera fault, equipment alarm, camera moved

**Continuity Activation**
The one moment a [[Capture Continuity Streak]] crosses the threshold, identified by the capture that began the streak so a live evaluation and a recovery name it identically. An activation is **new** when live evaluation raised it, or when its evidence was persisted by a checkup that never finished processing; it is **historical** when a restart or upgrade merely rediscovered it. Notification delivery announces only new activations; neither restart, upgrade nor Inbox trimming can make one new again.
_Avoid_: Alert, notification, alarm event

**Capture Continuity Monitor** (`capture_continuity_monitor.py`)
The runtime owner of every [[Capture Continuity Streak]]. It normalizes one finished [[Vision Capture]] into the evidence ADR-0044 recognises — a transport failure is not a quality rejection — asks the pure `domain/capture_continuity.py` state machine for the next state, and reports condition transitions to the [[Alert Monitor]]. It hands each new [[Continuity Activation]] to [[Continuity Delivery]] after the alert and before the capture counts as processed. On start, before any checkup is scheduled, it recovers each current [[Camera Assignment]]'s streak from the Vision Evidence Store, reconciles the Inbox to it, and only then starts delivery. It persists only what evidence cannot say, in `growspace_manager.capture_continuity`: where each assignment began and how far live intake has processed. The [[Vision Checkup]] scheduler invokes it and holds no continuity policy of its own; the [[Environment Patch]] commit shell and growspace creation and removal tell it, after a change has been persisted, which cameras a Growspace holds.
_Avoid_: Continuity evaluator, streak cache

**Continuity Delivery** (`continuity_notifier.py`)
The durable record of announcing one new [[Continuity Activation]] to the grower. Each delivery channel keeps its own outcome: `pending`, `delivered`, `suppressed` (the growspace notification switch was off) or `failed` (the bounded retries ran out). Only a new activation gets a record. It is written before the activating capture counts as processed, so every new activation is either recorded here or still new to recovery. Records live in `growspace_manager.continuity_notifications`, apart from both streak state and the Triage Alert Inbox, so neither recovery nor Inbox trimming can make an activation announce itself twice. Each streak sends under one stable notification id. A crash between sending and recording success may send it again under that id, so delivery is at-least-once, never exactly-once. The first channel is a warning-level Home Assistant persistent notification. It carries the canonical ADR-0044 message unrewritten, plus the camera and Growspace, and needs no device target. It ignores the generic sender's cooldowns, no-Plants gate and AI rewrite. Muting suppresses every unfinished channel and cancels its retries; un-muting sends no backlog. The [[Triage Alert]] is recorded either way.
_Avoid_: Notification log, alert history

**Evidence Fusion**
The Home Assistant-owned interpretation of current Bayesian environmental evidence and a Visual Comparison Result. It reports environmental risk, departure from recent scene history, or their coexistence; it never diagnoses plant health or treats coexistence as causation. See [ADR-0040](./docs/adr/0040-evidence-fusion-reports-observations-not-plant-health.md).
_Avoid_: Plant-health fusion, diagnosis engine, correlated stress

**Evidence Fusion Outcome**
Either an unavailable result with explicit missing-evidence reasons, or exactly one of `no_detected_change`, `environmental_risk`, `visual_anomaly`, `concurrent_environmental_risk_and_visual_anomaly`, and `persistent_visual_anomaly`, qualified by confidence and evidence coverage. Every state is observe-only; `no_detected_change` means only that complete available evidence found neither environmental risk nor material departure from recent scene history.
_Avoid_: Healthy, unhealthy, visual plant stress

**Plant-Health Calibration**
Symptom-specific evidence that a fixed alert policy detects independently labelled real episodes while meeting its prospective false-alert budget. Baseline readiness and a single observed event are not Plant-Health Calibration, and V1 has none.
_Avoid_: Baseline validity, camera calibrated, synthetic validation

**EnvironmentState Assembler**
A class in `domain/` (following the [[StageEnvironmentalTargets]] precedent) that builds an `EnvironmentState` from raw HA entity states. Constructed with injected callables (`get_state`, `get_growspace`, `get_plants`) plus the growspace's `EnvironmentConfig`; each Bayesian sensor owns its own assembler (`assemble()` is uncached, so a shared per-growspace instance would dedupe no reads). A single `assemble()` call returns an `AssembledEnvironment` holding both the `EnvironmentState` and the flat observation dict, derived from one read pass so the two can never diverge. Owns: multi-sensor aggregation (average) for temp/humidity/VPD, VPD fallback calculation with LST offset (zeroed for dry/cure growspaces), CO2/soil-moisture/substrate-temp reads, device-state derivation (fans-off AND logic, dehumidifier/humidifier-on OR logic, exhaust/humidifier max value), lights-on OR logic, and per-stage maxima of [[Current Stage Age]] from [[Plant Lifecycle]] (only a Plant's current stage contributes, so stale closed-stage dates cannot grow uncapped). Pure — no side effects: light-flip transition detection lives in the Notification Manager (see [[Evaluation Snapshot]]), not here. Unit-testable with plain lambdas (see `tests/domain/test_environment_state_assembler.py`).

**Notification Settings**
A dict of six timing/cooldown parameters stored in `config_entry.options["notification_settings"]`. Keys: `critical_cooldown_minutes`, `warning_cooldown_minutes`, `recovery_cooldown_minutes`, `escalation_delay_minutes`, `min_stress_duration_seconds`, `warning_persistence_minutes`. Each value falls back to the corresponding hardcoded constant in `const.py` when absent, so the dict may be partially populated or omitted entirely without breaking behaviour. Exposed as a top-level key in the global coordinator data payload and written atomically via the `save_notification_settings` WebSocket command.

**Timed Notification**
A user-configured reminder that fires on a specific day of a plant's lifecycle stage. Stored as a list in `config_entry.options["timed_notifications"]`. Each entry has `id` (UUID), `message`, `trigger_type`, `day`, and `growspace_ids`. Managed by `NotificationSettingsManager`. Exposed as a top-level key in the global coordinator data payload alongside Notification Settings.

**Camera Snapshot**
A point-in-time image captured from a growspace camera. A [[Vision Checkup]] stores the original camera bytes and any derived grid overlay as private, capture-addressed variants owned by the [[Vision Evidence Store]]; manual snapshots outside a checkup remain a separate public camera-gallery concern.

**Vision Checkup**
One Home Assistant-owned observation task for a growspace, scheduled in a light window or triggered manually and identified by `checkup_id`. It groups one [[Vision Capture]] per camera and has only an operational outcome (`completed`, `partial`, `failed`); visual comparison and [[Evidence Fusion Outcome]] remain capture-specific and are never aggregated across cameras. See [ADR-0043](./docs/adr/0043-vision-checkups-migrate-through-versioned-capture-contracts.md).
_Avoid_: Vision diagnosis, AI verdict, plant health check

**Vision Explainer**
The optional cloud LLM stage of a [[Vision Checkup]]. It receives the [[Evidence Fusion Outcome]], the visual evidence, the environmental evidence and the temporal trend, each labelled with its origin, and produces prose. It emits no verdict, no severity and no machine-readable symptom claim; severity is a fusion output and the explainer has no field to overrule it. A growspace with no AI task configured has no explainer and a complete report without one. See [ADR-0042](./docs/adr/0042-the-vision-explainer-explains-evidence-it-does-not-inspect.md).
_Avoid_: Vision AI, diagnostician, the vision model

**Visual Observation Pass**
The first of the [[Vision Explainer]]'s two calls. It receives the photographs and the light window and nothing else — there is no parameter through which environmental evidence, a fusion state or a trend could reach it — and returns a description of what is visible. Optional, behind `ai_settings.vision_explainer_sees_image`; when it is off or it fails, the observation is derived from the Visual Comparison Result and recorded as `visual_comparison_only`.
_Avoid_: Image analysis, visual diagnosis

**Evidence Explanation Pass**
The second of the [[Vision Explainer]]'s two calls. It receives the [[Visual Observation Pass]]'s text, the evidence and the trend, and **no image** — which is what makes its binding rule ("You have not seen an image") true rather than aspirational. It never returns the observation, so it cannot revise what was seen.
_Avoid_: Interpretation call, the second prompt

**Vision Explainer Report**
The four fields a [[Vision Explainer]] produces for one capture — `observation`, `environmental_risk`, `hypothesis`, `recommendations` — stored in the `vision_explainer_report` table with the [[Evidence Fusion Outcome]] snapshotted alongside them. No severity, no symptom vocabulary. Empty values are legal: an empty hypothesis is the honest output when the evidence supports none.
_Avoid_: Vision analysis, AI diagnosis, checkup result

**Vision Analysis**
One stateless `POST /analyze` against Growspace Vision: exactly one image plus a closed metadata object in, and either a [[Visual Embedding]] or a [[Frame Quality Result]] rejection out. `analyzed` says only that the App produced an embedding — never that the scene is normal, anomalous, healthy or unhealthy. Every temporal claim is Home Assistant's, so an anomaly score, change score, trend or symptom in a response is a contract violation and is refused at the boundary. See [ADR-0043](./docs/adr/0043-vision-checkups-migrate-through-versioned-capture-contracts.md).
_Avoid_: Vision checkup, plant health scan, AI analysis

**Frame Quality Result**
The App's three single-frame measurements — mean luminance, clipped pixel fraction, mean absolute gradient — plus every absolute-floor reason that held (`too_dark`, `overexposed`, `low_detail`, `light_state_mismatch`). Returned on accepted and rejected frames alike, because the numbers describe the frame while the history-relative rails stay in Home Assistant. A rejection is a first-class HTTP 200 result stored as unusable, never an error that erases the attempt.
_Avoid_: Blur score, image validation error, quality gate failure

**Visual Embedding**
The model-versioned vector one accepted frame produced. It is comparable only with embeddings from the same `model_id` and `model_version`: a changed model version starts a new Baseline Bucket rather than continuing the old one, which is why negotiation refuses to substitute a different model for a pinned one.
_Avoid_: Feature vector, fingerprint, image hash

**Vision Evidence Store**
The Home Assistant-owned SQLite database `growspace_vision.db` holding every artifact of a [[Vision Checkup]]: the checkup itself, [[Vision Capture]]s, their image files, Visual Embeddings, Visual Comparison Results, Baseline Buckets, [[Evidence Fusion Outcome]]s and [[Vision Label]]s. Growspace Vision is stateless, so this is the only durable record that the analysis happened. Versioned by `PRAGMA user_version` and migrated by forward-only numbered steps — deliberately not the `try: ALTER TABLE / except` pattern of `strain_library.py`, which records no version. See [ADR-0041](./docs/adr/0041-home-assistant-owns-vision-evidence-in-a-dedicated-store.md).
_Avoid_: Vision history, embedding cache, anomaly database

**Vision Capture**
One [[Camera Snapshot]] taken for a [[Vision Checkup]], identified by a `capture_id` (UUIDv7) and linked to its parent `checkup_id`. The id is minted in Home Assistant before the Growspace Vision call and names every image variant; the record is written when the bytes are persisted, so rejection or failure still leaves a tracked, prunable image.
_Avoid_: Frame, snapshot record, image row

**Vision Capture Result**
The card-facing projection of one [[Vision Capture]]: image availability, quality outcome, visual comparison, normalized environmental evidence, [[Evidence Fusion Outcome]], measurement-only trend, provenance and optional [[Vision Explainer Report]]. It is not an embedding or database-row dump and has no severity or symptom claim.
_Avoid_: Checkup result, AI verdict, capture diagnosis

**Vision Service Status**
The integration-owned statement of whether Growspace Vision is `ready`, `unavailable` or `incompatible`, with a typed reason and the service, schema and active-model versions when known. The card displays it but never probes or configures the service itself.
_Avoid_: Connected boolean, App health check, model setting

**Vision Connection**
The integration-wide route to Growspace Vision: either automatic Supervisor discovery or an explicit manual endpoint and bearer token. It never belongs to a growspace, never reaches the card with its token, and never silently falls back between modes.
_Avoid_: VisionCheckupConfig endpoint, camera connection

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

**Legacy Vision Checkup Result**
One cloud-era entry preserved verbatim inside [[Legacy Vision Checkup History]] and discriminated as `legacy_cloud_v1` when projected to the card. Its severity and detected issues are attributed historical cloud output, never V1 evidence.
_Avoid_: Migrated result, V1 result

**Vision History**
The newest-first card projection of V1 [[Vision Checkup]] envelopes and clearly marked [[Legacy Vision Checkup Result]]s. Pagination counts checkups rather than captures, and legacy entries never participate in V1 trends or evidence.
_Avoid_: Legacy history, capture list

**Contract Fixture**
The golden `get_data` growspace payload committed at `tests/fixtures/contract/growspace_payload.json`, serialized from one **maximally populated** growspace (every optional sub-config set). A snapshot test fails when the payload shape changes without the fixture being deliberately regenerated; the lovelace card strict-parses the same file in its CI. Maximal population is the load-bearing property — a field absent from the fixture builder is invisible to the contract.

**GSM-First Landing Order**
The rule that for any cross-repo feature, the integration side merges to `prerelease` and ships in a GSM release **before** the card PR merges to the card's `dev`. The only sanctioned exception is a [[Backward-Safe Card Change]].

**Backward-Safe Card Change**
A card change proven safe against the _released_ GSM backend, not just `prerelease` — the proof being the card's strict parse of the release-ref [[Contract Fixture]] passing. Named after the env-clear fix pattern (card #439), which had to behave correctly under both the old full-replace and the new patch semantics of `configure_environment`.
