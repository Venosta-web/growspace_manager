# Home Assistant owns vision evidence in a dedicated store

**Status:** Accepted; amended by
[ADR 0043](./0043-vision-checkups-migrate-through-versioned-capture-contracts.md)

Decided on 2026-08-31 in
[hub#70](https://github.com/Venosta-web/growspace_manager_workspace/issues/70), under
the stateless-service boundary of ADR 0003 and the baseline semantics of ADR 0004.

Every artifact of a Vision Checkup — the checkup envelope, each capture, its image
files, its Visual Embedding, the Baseline Bucket it was scored against, the Visual
Comparison Result, its Evidence Fusion Outcome, and any grower label — is persisted
by Home Assistant in a dedicated SQLite database, `growspace_vision.db`. Evidence
rows are kept unpruned for the life of the growspace; images are kept on a bounded
rolling window with an explicit pin rule. The existing cloud-era
`vision_checkup_history` is frozen in place rather than migrated, and no
`STORAGE_VERSION` bump is required.

## Medium

A dedicated `aiosqlite` database, alongside `strain_library.db` and not inside it.

Disk does not decide this; write amplification and query shape do. A Visual Embedding
is 384 float32 values, three times a day, per camera. As JSON in the existing config
`Store` that is ~5 KB per capture in a file rewritten _whole_ on every debounced save
— and saves are triggered by unrelated plant and configuration edits, so one Grow Run
of one camera would add ~1.8 MB to every one of them. That store is already 302 KB in
production use. It also cannot answer "the thirty newest admitted embeddings for this
bucket" without loading everything.

Sharing `strain_library.db` was rejected on lifecycle rather than shape: the strain
library is a curated catalogue a grower wants in every backup and never auto-pruned,
while vision evidence is machine-generated, per-Grow-Run and retention-managed. One
file cannot hold two contradictory retention policies without one of them being a lie.

The schema versions itself through `PRAGMA user_version` and migrates by forward-only
numbered steps, refusing to start when the file's version exceeds the code's. This is
a deliberate departure from `strain_library.py`, which migrates by a stack of
`try: ALTER TABLE ... except OperationalError: pass` and therefore cannot report which
shape a given file is in.

## Growth

Per capture, rows total roughly 2.8 KB — a 1,536-byte embedding blob plus capture,
result, file and membership rows. At the settled three captures per day:

|                               | per capture | per month, one camera | per year, one camera |
| ----------------------------- | ----------- | --------------------- | -------------------- |
| evidence rows                 | ~2.8 KB     | **~0.26 MB**          | ~3.1 MB              |
| with SQLite pages and indices | —           | ~0.4 MB               | ~5 MB                |
| raw + processed images        | ~370 KB     | **~33 MB**            | ~400 MB              |

Images are roughly 130x the evidence. The database is therefore too small to justify
any retention policy of its own, and the images are the only part a backup notices.

## Durability and retention

Evidence rows are durable and unpruned. Pruning them would destroy the temporal series
the quality gate ([hub#74]) and the alerting decision ([hub#75]) depend on, and at
0.26 MB per camera-month there is nothing to gain.

Images get a rolling window, `image_retention_days`, defaulting to 90 and disabled by
`0`, with a pin rule. A **Pinned Capture** — a current Baseline Bucket member, a
capture carrying a label, or one whose result was `uncertain` or
`material_scene_change` — is never deleted by retention. That is precisely the set a
future training run needs, and it is a small fraction of captures; the unpinned
remainder is what would otherwise put ~400 MB per camera-year into every backup,
unattended, for a feature that may ship observe-only.

A model-version change does **not** delete images: that is exactly when retained
images are wanted for re-embedding. The workflow for re-embedding stays unspecified;
the schema only refuses to foreclose it.

The retention job runs at setup and daily thereafter, deleting files before their rows
so a crash leaves a recoverable orphan row rather than an untracked file. **It only
deletes files it has a row for.** The existing unpruned `www/growspace_manager/snapshots/`
backlog is out of its scope — removing files a grower may have linked or
archived, on the strength of a glob, is not a storage migration's decision.

Images live under the media root, as
`growspace_vision/{growspace_id}/{camera_id}/{capture_id}.{variant}.jpg`. On HAOS and
Supervised installs `media` is a separately selectable backup folder, so a grower can
exclude the corpus without excluding their configuration; on Container and Core
installs `media_dirs` defaults to `<config>/media` and that separability does not
exist. `www/` was rejected outright: `/local/` is world-readable to anyone with the
URL and the path is guessable from a timestamp. The database stores a
**storage-relative path and a variant**, never a public URL, so the serving mechanism
can change without a data migration.

## Capture identity

A `checkup_id` is a UUIDv7 string minted when one scheduled or manual Vision
Checkup begins. The `vision_checkup` row is the durable multi-camera task and every
capture references it; close timestamps are never used as an implicit group (ADR
0043).

A `capture_id` is a UUIDv7 string minted in Home Assistant at capture time, **before**
the Growspace Vision call, and is the filename stem of every image variant. It exists
even when the call fails or the frame is rejected.

A content hash was rejected as the identity: a static scene under a static light can
produce byte-identical frames, and two captures an hour apart are two events even when
the pixels agree — collapsing them would corrupt both the baseline and the trend. The
hash is kept as a separate nullable column, for integrity checks and for detecting a
frozen camera.

## Provenance

An embedding records `model_id`, `model_version` and `dimension`; its capture records
the negotiated `vision_schema_version`, the `service_version` and the `request_id`.

Encoder identity is not sufficient. A change to Home Assistant's _own_ scoring policy —
the distance metric, the rolling window size, the leave-one-out calibration, the
verdict cuts of ADR 0004 — makes stored results equally incomparable and is invisible
to model version. Results and buckets therefore also carry a `scoring_policy_version`.
A result whose policy version differs from the current one remains displayable history
and is never reused as evidence. Re-scoring under a new policy inserts a second
result rather than overwriting the first.

Embeddings are stored as returned by the service: float32, **not** unit-normalized.
ADR 0004's normalization is a deterministic in-memory step, and the stored artifact
should stay faithful to what the service actually emitted.

## Baselines are recorded, not derived

Bucket membership is written when it is decided, in `vision_baseline_member`, and
eviction is retained rather than deleted.

Deriving membership by query — "the thirty most recent captures here whose verdict was
normal" — cannot reproduce ADR 0004, because admission is history-dependent: during
bootstrap every eligible capture enters, and only after readiness is admission limited
to `normal`. Recomputing it later re-decides it under today's policy and silently
rewrites what the baseline was. The bucket row caches `centroid` and the thirty
leave-one-out `calibration_distances`, recomputed only on admission.

`admitted_to_baseline` is an explicit fact on the result, not inferred from the
verdict. A **manual** capture has no stable light window, so it may be scored against
the window it falls within but is never admitted — admitting it would mix illumination
conditions into the bucket whose purpose is to hold them fixed, and manual captures
cluster around the moment a grower already suspects something, which is the worst
available admission bias for a baseline of "normal".

## Framing Epochs and the Grow Run dimension

A Framing Epoch is its own table, with `started_at`, a `reason`
(`camera_move_detected`, `manual_restart`, `grow_run_boundary`,
`model_version_change`, `initial`) and a nullable `detector_evidence` for [hub#74]'s
structural-correlation value. An integer column would answer _which_ epoch but not
_why this camera's baseline reset_, and camera-shaped change is the dominant cause of
high visual distance, so that question gets asked constantly.

Grow Runs are specified (ADR 0033-0035) but not implemented; `grep` finds `GrowRun` in
three ADRs and zero Python files. Leaving `grow_run_id` null until they land was
rejected: the harvest is the largest legitimate scene change in the measured corpus
(0.69 against a 0.13 noise ceiling), so a baseline that never resets at harvest
produces a guaranteed false alarm at every harvest. The integration therefore mints a
persisted surrogate run id per growspace now, in `vision_grow_run_ref` with
`source = 'surrogate'`. When Grow Runs land, the source flips and the mapping is a
one-row-per-growspace backfill, not a schema migration.

## Labels

One table, two kinds. A `comparison_correction` corrects a scene verdict the model
actually made and carries that verdict, its score and its policy version alongside the
correction. An `observation` asserts a symptom or condition the model never claimed,
and so has no model output to correct.

Merging them was rejected because V1 emits a _scene_ claim and never a health claim
([hub#68]): a single record carrying both "the model said chlorosis" and "the grower
says chlorosis" implies a model output that does not exist, and re-imports exactly the
false authority the local vision work exists to remove. Check constraints enforce the
split in both directions.

Labels are append-only; a revision sets `superseded_by` rather than overwriting.
**Training eligibility is derived at export time, not stored** — a computed flag goes
stale the moment an image is pruned or a model version changes. What is stored is an
explicit human `excluded` flag with a reason.

## Deletion

Deleting a Growspace cascades into its vision evidence and images, **except** pinned
and labelled captures, which survive as orphans with `growspace_name` denormalized
onto them. ADR 0033's rule that source deletion never cascades into Run history does
not apply here: vision evidence is not Run history, and ADR 0037 explicitly keeps
ordinary camera history out of Run media.

## Write ordering

The checkup row is written when the task begins. Each capture row is written when its
bytes are persisted, before the analysis call, and its result is written after. A
capture with no result is a first-class state and is always visible to retention —
which makes the database the index for the image
files and closes the untracked-file hole `www/snapshots` has today, where the
filesystem _is_ the index and a glob parses the timestamp out of the filename.

If the capture row cannot be written, the checkup aborts loudly: spending an inference
on a capture we cannot record, or leaving an untracked file behind, is worse than a
missed checkup. A result-write failure after a successful analysis is logged and the
checkup reports unavailable — the light-cycle scheduler must never be taken down by
the evidence store. Connections use `journal_mode=WAL` and `synchronous=NORMAL`; a
torn evidence database must not take the integration with it.

## Migration

The existing `vision_checkup_history` is **frozen in place**: never appended to after
the cutover, never read by baselines, trends, Evidence Fusion or a training set, and
rendered as a clearly-marked legacy tail (sequenced by [hub#73]).

Migrating it into the evidence store was rejected. Those records have no capture id,
no embedding and no framing epoch, their snapshot paths point at overlaid JPEGs, and
they assert the `severity` and `issues_detected` claims [hub#68] settled that V1 may
not make; copying them in would give them equal standing with measured evidence.

Because all new evidence lives in SQLite and the legacy list merely stops growing,
**the config `Store`'s schema does not change, so `STORAGE_VERSION` is not bumped** —
which matters, since that constant is shared by four stores and bumping it would force
a migration of all of them. Removing the frozen field becomes a separate, later
decision once real installs have rolled over.

## Named home

- `custom_components/growspace_manager/data_access/vision_evidence_schema.py` — the
  DDL, its version, and the scoring-policy and baseline-size constants.
- `custom_components/growspace_manager/models/vision_evidence.py` — frozen records and
  the enums the `CHECK` constraints enforce.
- `custom_components/growspace_manager/data_access/vision_evidence_store.py` — the
  repository: connection lifecycle, migrations, evidence queries, atomic image writes,
  retention and deletion.

`domain/` gets nothing. There is no pure logic here; ADR 0004's baseline mathematics
belongs with the scoring work, not with the store.

`tests/test_vision_evidence_schema.py` holds the executable half: it proves every model
enum appears in the constraint that guards its column, that a scored result cannot
exist without a score and a verdict, that a monitoring result cannot carry one, that
re-scoring under a new policy adds rather than replaces, that one capture may hold
several model versions, that a Baseline Bucket has no `manual` light window, and that
neither label kind can be filled in as the other.

## Interim raw-capture bridge

[Hub issue #72](https://github.com/Venosta-web/growspace_manager_workspace/issues/72)
starts preserving the source corpus before the dedicated evidence repository and
local comparison producer exist. The cloud-era scheduler writes each camera response
unchanged under the resolved private media root:

`growspace_vision/raw/{growspace_id}/{timestamp}_{camera}_raw.{source-extension}`

The paired overlaid image remains in the existing public snapshot directory with the
same stem and `_processed.jpg`; manual captures retain the bare `.jpg` convention.
Unknown camera content types use `.bin` rather than claiming the bytes are JPEG. Raw
artifacts are retained for 90 days and pruning matches only `_raw` files. They are not
returned by `get_snapshots` because that API only reads the separate `www/` tree; no
filename filter is needed. A failed overlay still leaves the already-fetched raw
artifact available. This file-only bridge remains until the Vision Checkup producer
is cut over to the repository; that cutover replaces it with the capture and file rows
specified above.

[hub#68]: https://github.com/Venosta-web/growspace_manager_workspace/issues/68
[hub#69]: https://github.com/Venosta-web/growspace_manager_workspace/issues/69
[hub#73]: https://github.com/Venosta-web/growspace_manager_workspace/issues/73
[hub#74]: https://github.com/Venosta-web/growspace_manager_workspace/issues/74
[hub#75]: https://github.com/Venosta-web/growspace_manager_workspace/issues/75
