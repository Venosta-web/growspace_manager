"""SQLite schema for the Vision Evidence Store.

Home Assistant owns every artifact of a Vision Checkup because Growspace Vision is
stateless (ADR 0003).  This module holds the schema alone: the DDL, its version, and
the vocabulary its ``CHECK`` constraints enforce.  Connection handling, migrations and
queries live in ``vision_evidence_store.py``, which is deliberately deferred until the
Visual Comparison Result producer exists — see ADR 0041.

The schema is versioned through ``PRAGMA user_version`` and migrated by forward-only
numbered steps.  This is a deliberate departure from ``strain_library.py``, which
migrates by a stack of ``try: ALTER TABLE ... except OperationalError: pass`` and
therefore cannot report which shape a given file is in.
"""

from __future__ import annotations

from typing import Final

# Bumped by any forward migration step. Read from and written to PRAGMA user_version;
# a file whose user_version exceeds this value is a downgrade and must fail loudly
# rather than be migrated backwards.
VISION_EVIDENCE_SCHEMA_VERSION: Final = 1

# Bumped whenever the Home Assistant side changes how a Visual Comparison Result is
# produced — the distance metric, the rolling window size, the leave-one-out
# calibration, or the verdict cuts of ADR 0004.  An encoder change alone does not
# touch this; model identity is recorded separately.  A stored result whose policy
# version differs from the current one remains displayable history but is never
# reused as evidence.
VISION_SCORING_POLICY_VERSION: Final = 1

# The number of admitted members a Baseline Bucket needs before it may score.
# ADR 0004: a validity gate, not a confidence multiplier.
VISION_BASELINE_MEMBERS_REQUIRED: Final = 30

VISION_EVIDENCE_SCHEMA: Final = """
PRAGMA foreign_keys = ON;

-- A period in which one camera's physical framing is treated as materially
-- unchanged.  Its own table rather than a bare integer so that "why did this
-- camera's baseline reset" is answerable after the fact — camera-shaped change is
-- the dominant cause of high visual distance (hub#62), so the question gets asked.
CREATE TABLE IF NOT EXISTS vision_framing_epoch (
    epoch_id          TEXT PRIMARY KEY,
    growspace_id      TEXT NOT NULL,
    camera_id         TEXT NOT NULL,
    started_at        TEXT NOT NULL,
    reason            TEXT NOT NULL
                      CHECK (reason IN ('initial', 'camera_move_detected',
                                        'manual_restart', 'grow_run_boundary',
                                        'model_version_change')),
    detector_evidence TEXT
);
CREATE INDEX IF NOT EXISTS idx_vision_epoch_camera
    ON vision_framing_epoch (camera_id, started_at);

-- The Grow Run a capture belongs to.  Grow Runs are specified (ADR 0033-0035) but
-- not yet implemented, and a baseline that does not reset at harvest produces a
-- guaranteed false alarm at every harvest — the largest legitimate scene change in
-- the measured corpus (0.69 against a 0.13 noise ceiling).  So the integration mints
-- a surrogate run id per growspace now; when Grow Runs land, `source` flips to
-- 'grow_run' and this becomes a one-row-per-growspace backfill, not a migration.
CREATE TABLE IF NOT EXISTS vision_grow_run_ref (
    growspace_id TEXT PRIMARY KEY,
    grow_run_id  TEXT NOT NULL,
    started_at   TEXT NOT NULL,
    source       TEXT NOT NULL CHECK (source IN ('surrogate', 'grow_run'))
);

-- One Camera Snapshot taken for a Vision Checkup.  Written BEFORE the Growspace
-- Vision call, at the moment the bytes are persisted, so a failed or rejected
-- analysis still leaves the image tracked and prunable.  `growspace_name` is
-- denormalized so a labelled capture stays readable after its Growspace is deleted.
CREATE TABLE IF NOT EXISTS vision_capture (
    capture_id            TEXT PRIMARY KEY,
    growspace_id          TEXT NOT NULL,
    growspace_name        TEXT NOT NULL,
    camera_id             TEXT NOT NULL,
    grow_run_id           TEXT NOT NULL,
    framing_epoch_id      TEXT NOT NULL
                          REFERENCES vision_framing_epoch (epoch_id),
    captured_at           TEXT NOT NULL,
    light_window          TEXT NOT NULL
                          CHECK (light_window IN ('early', 'mid', 'late', 'manual')),
    light_state           TEXT NOT NULL
                          CHECK (light_state IN ('on', 'off', 'unknown')),
    trigger_source        TEXT NOT NULL
                          CHECK (trigger_source IN ('scheduled', 'manual')),
    content_sha256        TEXT,
    analysis_state        TEXT NOT NULL
                          CHECK (analysis_state IN ('pending', 'analyzed',
                                                    'rejected', 'failed')),
    analysis_error_code   TEXT,
    request_id            TEXT,
    vision_schema_version INTEGER,
    service_version       TEXT,
    quality_mean_luminance         REAL,
    quality_clipped_pixel_fraction REAL,
    quality_mean_absolute_gradient REAL,
    quality_reasons       TEXT,
    created_at            TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vision_capture_camera_time
    ON vision_capture (camera_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_vision_capture_run
    ON vision_capture (grow_run_id, captured_at);
CREATE INDEX IF NOT EXISTS idx_vision_capture_state
    ON vision_capture (analysis_state);

-- One image file per capture and variant.  `relative_path` is relative to the
-- resolved image root and never a public URL, so the serving mechanism can change
-- without a data migration.  The row survives its file: a pruned image is
-- distinguishable from an image that never existed.
CREATE TABLE IF NOT EXISTS vision_capture_file (
    capture_id     TEXT NOT NULL
                   REFERENCES vision_capture (capture_id) ON DELETE CASCADE,
    variant        TEXT NOT NULL CHECK (variant IN ('raw', 'processed')),
    relative_path  TEXT NOT NULL,
    byte_size      INTEGER NOT NULL,
    content_type   TEXT NOT NULL,
    deleted_at     TEXT,
    deletion_reason TEXT
                   CHECK (deletion_reason IS NULL
                          OR deletion_reason IN ('retention', 'growspace_deleted',
                                                 'user_requested')),
    PRIMARY KEY (capture_id, variant)
);

-- A Visual Embedding, keyed by the model that produced it so that re-embedding a
-- retained image under a new encoder is additive rather than destructive.  Values
-- are stored as returned by the service — float32, not unit-normalized — because
-- ADR 0004's normalization is a deterministic in-memory step and the stored artifact
-- should stay faithful to the wire.
CREATE TABLE IF NOT EXISTS vision_embedding (
    capture_id    TEXT NOT NULL
                  REFERENCES vision_capture (capture_id) ON DELETE CASCADE,
    model_id      TEXT NOT NULL,
    model_version TEXT NOT NULL,
    dimension     INTEGER NOT NULL,
    values_f32    BLOB NOT NULL,
    derived_at    TEXT NOT NULL,
    source        TEXT NOT NULL CHECK (source IN ('live', 're_embedded')),
    PRIMARY KEY (capture_id, model_id, model_version)
);

-- A Baseline Bucket: one camera, light window, Grow Run, model version and Framing
-- Epoch (ADR 0004).  The centroid and the leave-one-out calibration distances are
-- cached here and recomputed only on admission.
CREATE TABLE IF NOT EXISTS vision_baseline_bucket (
    bucket_id             TEXT PRIMARY KEY,
    growspace_id          TEXT NOT NULL,
    camera_id             TEXT NOT NULL,
    light_window          TEXT NOT NULL
                          CHECK (light_window IN ('early', 'mid', 'late')),
    grow_run_id           TEXT NOT NULL,
    model_id              TEXT NOT NULL,
    model_version         TEXT NOT NULL,
    framing_epoch_id      TEXT NOT NULL
                          REFERENCES vision_framing_epoch (epoch_id),
    state                 TEXT NOT NULL
                          CHECK (state IN ('monitoring', 'ready', 'stale')),
    member_count          INTEGER NOT NULL DEFAULT 0,
    members_required      INTEGER NOT NULL DEFAULT 30,
    centroid              BLOB,
    calibration_distances BLOB,
    last_admitted_at      TEXT,
    recomputed_at         TEXT,
    scoring_policy_version INTEGER NOT NULL,
    created_at            TEXT NOT NULL,
    UNIQUE (camera_id, light_window, grow_run_id, model_id, model_version,
            framing_epoch_id)
);

-- Membership is recorded, not derived.  Admission is history-dependent — during
-- bootstrap every eligible capture enters, after readiness only a `normal` one does
-- — so recomputing it later would silently re-decide it under today's policy.
-- Eviction is retained rather than deleted so a rolling window is auditable.
CREATE TABLE IF NOT EXISTS vision_baseline_member (
    bucket_id            TEXT NOT NULL
                         REFERENCES vision_baseline_bucket (bucket_id)
                         ON DELETE CASCADE,
    capture_id           TEXT NOT NULL
                         REFERENCES vision_capture (capture_id) ON DELETE CASCADE,
    admitted_at          TEXT NOT NULL,
    admission_phase      TEXT NOT NULL
                         CHECK (admission_phase IN ('bootstrap', 'normal')),
    evicted_at           TEXT,
    evicted_by_capture_id TEXT,
    PRIMARY KEY (bucket_id, capture_id)
);
CREATE INDEX IF NOT EXISTS idx_vision_member_active
    ON vision_baseline_member (bucket_id, evicted_at, admitted_at);

-- A Visual Comparison Result.  `admitted_to_baseline` is an explicit fact rather
-- than something inferred from the verdict: a manual capture may be scored `normal`
-- and still never enter a bucket.
CREATE TABLE IF NOT EXISTS vision_comparison_result (
    result_id             TEXT PRIMARY KEY,
    capture_id            TEXT NOT NULL
                          REFERENCES vision_capture (capture_id) ON DELETE CASCADE,
    bucket_id             TEXT REFERENCES vision_baseline_bucket (bucket_id),
    evaluated_at          TEXT NOT NULL,
    outcome               TEXT NOT NULL
                          CHECK (outcome IN ('scored', 'monitoring', 'unavailable')),
    baseline_state        TEXT
                          CHECK (baseline_state IS NULL
                                 OR baseline_state IN ('monitoring', 'ready',
                                                       'stale')),
    samples_collected     INTEGER,
    samples_required      INTEGER,
    raw_distance          REAL,
    anomaly_score         REAL
                          CHECK (anomaly_score IS NULL
                                 OR (anomaly_score >= 0.0 AND anomaly_score <= 1.0)),
    verdict               TEXT
                          CHECK (verdict IS NULL
                                 OR verdict IN ('normal', 'uncertain',
                                                'material_scene_change')),
    comparison_confidence REAL,
    admitted_to_baseline  INTEGER NOT NULL DEFAULT 0
                          CHECK (admitted_to_baseline IN (0, 1)),
    unavailable_reasons   TEXT,
    trigger_source        TEXT NOT NULL
                          CHECK (trigger_source IN ('scheduled', 'manual')),
    model_id              TEXT NOT NULL,
    model_version         TEXT NOT NULL,
    scoring_policy_version INTEGER NOT NULL,
    -- A scored outcome carries a score and a verdict; the others carry neither.
    CHECK ((outcome = 'scored')
           = (anomaly_score IS NOT NULL AND verdict IS NOT NULL)),
    UNIQUE (capture_id, model_id, model_version, scoring_policy_version)
);
CREATE INDEX IF NOT EXISTS idx_vision_result_capture
    ON vision_comparison_result (capture_id, evaluated_at);

-- The Vision Explainer's narrative for one capture (ADR 0042).  Separate from the
-- capture because the explainer is optional: the evidence rows are a complete
-- report without it, and a growspace with no AI task configured simply has no rows
-- here.  There is no severity column — severity is an Evidence Fusion output
-- (ADR 0040) and the explainer must not be able to overrule it — and no symptom
-- vocabulary, because V1 has no validated classifier to stand behind one (hub#68).
--
-- The fusion outcome is snapshotted rather than joined.  A narrative written
-- against `environmental_risk` is uninterpretable once the fusion transition table
-- moves underneath it, which is invisible to model version; the same reasoning that
-- put `scoring_policy_version` on a comparison result.  Text is free.
--
-- Not unique per capture: a manual re-run against a different AI task entity is a
-- second report, not a correction of the first.
CREATE TABLE IF NOT EXISTS vision_explainer_report (
    report_id          TEXT PRIMARY KEY,
    capture_id         TEXT NOT NULL
                       REFERENCES vision_capture (capture_id) ON DELETE CASCADE,
    created_at         TEXT NOT NULL,
    ai_task_entity_id  TEXT NOT NULL,
    -- `visual_comparison_only` records that no photograph was read, whether the
    -- Visual Observation Pass was switched off or failed.  A report can never
    -- imply an inspection that did not happen.
    observation_source TEXT NOT NULL
                       CHECK (observation_source IN ('image_pass',
                                                     'visual_comparison_only')),
    scoring_policy_version INTEGER NOT NULL,
    observation        TEXT NOT NULL,
    environmental_risk TEXT NOT NULL,
    hypothesis         TEXT NOT NULL,
    recommendations    TEXT NOT NULL,
    fusion_state       TEXT
                       CHECK (fusion_state IS NULL
                              OR fusion_state IN (
                                  'no_detected_change',
                                  'environmental_risk',
                                  'visual_anomaly',
                                  'concurrent_environmental_risk_and_visual_anomaly',
                                  'critical_scene_issue')),
    fusion_confidence  TEXT
                       CHECK (fusion_confidence IS NULL
                              OR fusion_confidence IN ('confirmed', 'monitor')),
    fusion_coverage    TEXT
                       CHECK (fusion_coverage IS NULL
                              OR fusion_coverage IN ('complete', 'partial')),
    fusion_unavailable_reasons TEXT,
    -- An available fusion outcome carries exactly one state with both qualifiers;
    -- an unavailable one carries none of the three.
    CHECK ((fusion_state IS NULL) = (fusion_confidence IS NULL)),
    CHECK ((fusion_state IS NULL) = (fusion_coverage IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_vision_explainer_report_capture
    ON vision_explainer_report (capture_id, created_at);

-- Grower feedback.  Two kinds, because V1 emits a scene claim and never a health
-- claim (hub#68): a `comparison_correction` corrects a verdict the model actually
-- made, an `observation` asserts something the model never claimed and therefore
-- has no model output to correct.  Append-only: a revision supersedes rather than
-- overwrites, so the annotation history stays auditable.
CREATE TABLE IF NOT EXISTS vision_label (
    label_id               TEXT PRIMARY KEY,
    capture_id             TEXT NOT NULL
                           REFERENCES vision_capture (capture_id) ON DELETE CASCADE,
    label_kind             TEXT NOT NULL
                           CHECK (label_kind IN ('comparison_correction',
                                                 'observation')),
    created_at             TEXT NOT NULL,
    author                 TEXT NOT NULL,
    model_verdict          TEXT,
    model_anomaly_score    REAL,
    model_id               TEXT,
    model_version          TEXT,
    scoring_policy_version INTEGER,
    corrected_verdict      TEXT
                           CHECK (corrected_verdict IS NULL
                                  OR corrected_verdict IN ('normal', 'uncertain',
                                                           'material_scene_change')),
    symptom_labels         TEXT,
    note                   TEXT,
    observed_from          TEXT,
    observed_to            TEXT,
    excluded               INTEGER NOT NULL DEFAULT 0
                           CHECK (excluded IN (0, 1)),
    exclusion_reason       TEXT,
    superseded_by          TEXT REFERENCES vision_label (label_id),
    -- A correction carries the model output it corrects and asserts no symptom.
    CHECK (label_kind <> 'comparison_correction'
           OR (model_verdict IS NOT NULL AND corrected_verdict IS NOT NULL
               AND symptom_labels IS NULL)),
    -- An observation is grower-asserted and corrects nothing.
    CHECK (label_kind <> 'observation'
           OR (model_verdict IS NULL AND corrected_verdict IS NULL))
);
CREATE INDEX IF NOT EXISTS idx_vision_label_capture
    ON vision_label (capture_id, created_at);
"""
