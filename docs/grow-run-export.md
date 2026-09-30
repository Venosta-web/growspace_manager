# Finalized Grow Run JSON export (version 1)

Send `growspace_manager/export_grow_run` with `growspace_id` and `run_id` over
Home Assistant's authenticated WebSocket API. This is a read; it changes no
Run Revision and needs no control permission. The Grow Run view's Overview
provides **Export JSON** for the selected Finalized Run. The legacy Grow Report
remains available; PDF and provisional exports are outside this contract.

Success is `{ "outcome": "exported", "document": { ... } }`. Download only
`document`, UTF-8 JSON, as `grow-run-<run_id>.json`. Its envelope is:

```json
{
  "format": "growspace_manager.grow_run",
  "version": 1,
  "status": "finalized",
  "snapshot": {}
}
```

`snapshot` is the frozen Run Finalization Snapshot, not a reconstruction from
live Plants, the Growspace or today's editable Run Metadata. It includes:

- `format` (snapshot format, independent of document version), `run_id`,
  `growspace_id`, `growspace_name`, `sequence_number` and IANA `timezone`.
- ISO timestamps `started_at`, `completed_at`, `finalized_at`, `duration_days`
  counted in the Run Timezone, and local-date `harvest_window` (`first`, `last`).
- `metadata` (`label`, `tags`, `goals`, `notes`) as it stood at finalization.
- `participants`: Participant Identity Snapshots with Plant, Strain and
  Phenotype IDs and names; `counts` and per-strain `strains` totals.
- `harvest_outcomes`: each source Plant's state, reason, recorded harvest
  metrics, quality score and `entered_dry_at`. No Usable Yield's explicit zero
  remains zero; unknown dry weight remains null.
- Every `metrics` row: metric name, unit, `definition_version`, nullable
  `value`, `complete`, and `missing` facts. `coverage` carries recorded metric
  coverage percentages; no coverage is inferred for metrics without a row.
- `water_applications`, `uncovered_gaps`, overall `missing` and `complete`.
- `reliability`, when captured: frozen safety event counts, coverage start,
  latest fault and acknowledgement, state and definition version.

Missing facts retain their snapshot representation: nullable facts stay null,
unrecorded optional harvest metrics stay absent, and unidentified participant
names retain their empty strings plus the snapshot's `participant_identity`
missing fact. Nothing fills an unknown with zero. A known absence is an empty
array. Snapshots finalized before metadata and harvest outcomes were frozen
have those two fields **null**, distinct from an empty outcome list. Export
never backfills them from the editable Run. These additive optional snapshot
fields retain snapshot format 1; existing durable snapshots still load.

Active, Completed and Voided Runs return `outcome: refused` with code
`grow_run.not_finalized`. Missing Run IDs use `grow_run.not_found`; unreadable
history uses `grow_run.store_unreadable`. All use the existing structured Run
refusal (`message`, `current_revision`, `active_run`, `reasons`). A reopened Run
refuses until finalized again; export then uses its current snapshot. Export
survives source deletion and persistence reload. Metric names are open-ended; consumers should retain every metric row,
including names they do not display, when saving the document.

The complete golden schema example is
[`grow_run_exported_v1.json`](../tests/fixtures/contract/grow_run_exported_v1.json).
