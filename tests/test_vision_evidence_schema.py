"""Tests for the Vision Evidence Store schema.

The schema's ``CHECK`` constraints are the enforcement; the model enums are the
vocabulary.  These tests keep the two in step and prove the invariants ADR 0041
relies on, so that the deferred store implementation cannot quietly drift from them.
"""

from __future__ import annotations

import sqlite3

import pytest

from custom_components.growspace_manager.data_access.vision_evidence_schema import (
    VISION_BASELINE_MEMBERS_REQUIRED,
    VISION_EVIDENCE_SCHEMA,
    VISION_EVIDENCE_SCHEMA_VERSION,
    VISION_SCORING_POLICY_VERSION,
)
from custom_components.growspace_manager.domain.evidence_fusion import (
    ConfidenceQualifier,
    EvidenceCoverage,
    EvidenceFusionState,
)
from custom_components.growspace_manager.models.vision_evidence import (
    AdmissionPhase,
    AnalysisState,
    BaselineState,
    CaptureFileVariant,
    CaptureTrigger,
    ComparisonOutcome,
    ComparisonVerdict,
    EmbeddingSource,
    FileDeletionReason,
    FramingEpochReason,
    GrowRunRefSource,
    LabelKind,
    LightState,
    LightWindow,
    ObservationSource,
)

EXPECTED_TABLES = {
    "vision_baseline_bucket",
    "vision_baseline_member",
    "vision_capture",
    "vision_capture_file",
    "vision_comparison_result",
    "vision_embedding",
    "vision_explainer_report",
    "vision_framing_epoch",
    "vision_grow_run_ref",
    "vision_label",
}


@pytest.fixture(name="db")
def db_fixture():
    """Return an in-memory database with the evidence schema applied."""
    connection = sqlite3.connect(":memory:")
    connection.executescript(VISION_EVIDENCE_SCHEMA)
    connection.execute(f"PRAGMA user_version = {VISION_EVIDENCE_SCHEMA_VERSION}")
    yield connection
    connection.close()


def _table_sql(db: sqlite3.Connection, table: str) -> str:
    """Return the stored CREATE statement for a table."""
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    assert row is not None, f"table {table} is missing"
    return row[0]


def _insert_epoch(db: sqlite3.Connection, epoch_id: str = "epoch-1") -> str:
    """Insert a Framing Epoch and return its id."""
    db.execute(
        "INSERT INTO vision_framing_epoch"
        " (epoch_id, growspace_id, camera_id, started_at, reason)"
        " VALUES (?, 'gs-1', 'camera.growcam', '2026-08-31T06:00:00+00:00',"
        " 'initial')",
        (epoch_id,),
    )
    return epoch_id


def _insert_capture(
    db: sqlite3.Connection,
    capture_id: str = "capture-1",
    *,
    light_window: str = "early",
    analysis_state: str = "analyzed",
    trigger_source: str = "scheduled",
) -> str:
    """Insert a capture and return its id."""
    db.execute(
        "INSERT INTO vision_capture"
        " (capture_id, growspace_id, growspace_name, camera_id, grow_run_id,"
        "  framing_epoch_id, captured_at, light_window, light_state,"
        "  trigger_source, analysis_state, created_at)"
        " VALUES (?, 'gs-1', 'Flower Tent', 'camera.growcam', 'run-1', 'epoch-1',"
        " '2026-08-31T06:00:00+00:00', ?, 'on', ?, ?,"
        " '2026-08-31T06:00:00+00:00')",
        (capture_id, light_window, trigger_source, analysis_state),
    )
    return capture_id


def test_schema_creates_every_table(db):
    """The schema creates exactly the tables ADR 0041 specifies."""
    names = {
        row[0]
        for row in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    assert names == EXPECTED_TABLES


def test_schema_version_is_recorded_in_user_version(db):
    """The file carries its schema version, so a downgrade is detectable."""
    assert db.execute("PRAGMA user_version").fetchone()[0] == (
        VISION_EVIDENCE_SCHEMA_VERSION
    )


@pytest.mark.parametrize(
    ("table", "column", "enum"),
    [
        ("vision_framing_epoch", "reason", FramingEpochReason),
        ("vision_grow_run_ref", "source", GrowRunRefSource),
        ("vision_capture", "light_window", LightWindow),
        ("vision_capture", "light_state", LightState),
        ("vision_capture", "trigger_source", CaptureTrigger),
        ("vision_capture", "analysis_state", AnalysisState),
        ("vision_capture_file", "variant", CaptureFileVariant),
        ("vision_capture_file", "deletion_reason", FileDeletionReason),
        ("vision_embedding", "source", EmbeddingSource),
        ("vision_baseline_bucket", "state", BaselineState),
        ("vision_baseline_member", "admission_phase", AdmissionPhase),
        ("vision_comparison_result", "outcome", ComparisonOutcome),
        ("vision_comparison_result", "verdict", ComparisonVerdict),
        ("vision_label", "label_kind", LabelKind),
        ("vision_explainer_report", "observation_source", ObservationSource),
        ("vision_explainer_report", "fusion_state", EvidenceFusionState),
        ("vision_explainer_report", "fusion_confidence", ConfidenceQualifier),
        ("vision_explainer_report", "fusion_coverage", EvidenceCoverage),
    ],
)
def test_check_constraints_match_the_model_enums(db, table, column, enum):
    """Every enum member appears in the CHECK constraint that guards its column."""
    sql = _table_sql(db, table)
    for member in enum:
        assert f"'{member.value}'" in sql, (
            f"{enum.__name__}.{member.name} is missing from {table}.{column}"
        )


def test_baseline_bucket_has_no_manual_light_window(db):
    """A manual capture has no stable light window, so it gets no bucket."""
    sql = _table_sql(db, "vision_baseline_bucket")
    assert "'manual'" not in sql
    assert LightWindow.MANUAL.value == "manual"


def test_manual_capture_is_recordable(db):
    """A manual capture is still first-class evidence."""
    _insert_epoch(db)
    _insert_capture(db, light_window="manual", trigger_source="manual")
    assert db.execute("SELECT COUNT(*) FROM vision_capture").fetchone()[0] == 1


def test_capture_is_recordable_before_its_analysis(db):
    """A pending capture is valid, so a failed analysis leaves a tracked image."""
    _insert_epoch(db)
    _insert_capture(db, analysis_state="pending")
    db.execute(
        "INSERT INTO vision_capture_file"
        " (capture_id, variant, relative_path, byte_size, content_type)"
        " VALUES ('capture-1', 'raw', 'gs-1/camera.growcam/capture-1.raw.jpg',"
        " 250000, 'image/jpeg')"
    )
    assert db.execute("SELECT COUNT(*) FROM vision_capture_file").fetchone()[0] == 1


def test_one_capture_may_hold_several_model_versions(db):
    """Re-embedding under a new encoder is additive, never destructive."""
    _insert_epoch(db)
    _insert_capture(db)
    for version, source in (("1.0.0", "live"), ("2.0.0", "re_embedded")):
        db.execute(
            "INSERT INTO vision_embedding"
            " (capture_id, model_id, model_version, dimension, values_f32,"
            "  derived_at, source)"
            " VALUES ('capture-1', 'dinov2-vits14', ?, 384, X'00',"
            " '2026-08-31T06:00:00+00:00', ?)",
            (version, source),
        )
    assert db.execute("SELECT COUNT(*) FROM vision_embedding").fetchone()[0] == 2


def test_a_scored_result_must_carry_a_score_and_a_verdict(db):
    """A scored outcome without a score is not representable."""
    _insert_epoch(db)
    _insert_capture(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO vision_comparison_result"
            " (result_id, capture_id, evaluated_at, outcome, trigger_source,"
            "  model_id, model_version, scoring_policy_version)"
            " VALUES ('result-1', 'capture-1', '2026-08-31T06:00:10+00:00',"
            " 'scored', 'scheduled', 'dinov2-vits14', '1.0.0', ?)",
            (VISION_SCORING_POLICY_VERSION,),
        )


def test_a_monitoring_result_must_not_carry_a_score(db):
    """Monitoring means no score exists, not a score of zero."""
    _insert_epoch(db)
    _insert_capture(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO vision_comparison_result"
            " (result_id, capture_id, evaluated_at, outcome, trigger_source,"
            "  model_id, model_version, scoring_policy_version, anomaly_score,"
            "  verdict)"
            " VALUES ('result-1', 'capture-1', '2026-08-31T06:00:10+00:00',"
            " 'monitoring', 'scheduled', 'dinov2-vits14', '1.0.0', ?, 0.5,"
            " 'normal')",
            (VISION_SCORING_POLICY_VERSION,),
        )


def test_rescoring_under_a_new_policy_does_not_replace_the_old_result(db):
    """A policy change adds a result; it never rewrites the one already recorded."""
    _insert_epoch(db)
    _insert_capture(db)
    for index, policy in enumerate((1, 2)):
        db.execute(
            "INSERT INTO vision_comparison_result"
            " (result_id, capture_id, evaluated_at, outcome, trigger_source,"
            "  model_id, model_version, scoring_policy_version, anomaly_score,"
            "  verdict)"
            " VALUES (?, 'capture-1', '2026-08-31T06:00:10+00:00', 'scored',"
            " 'scheduled', 'dinov2-vits14', '1.0.0', ?, 0.5, 'normal')",
            (f"result-{index}", policy),
        )
    assert (
        db.execute("SELECT COUNT(*) FROM vision_comparison_result").fetchone()[0] == 2
    )


def test_an_observation_label_corrects_nothing(db):
    """V1 makes no health claim, so a symptom label has no model output to correct."""
    _insert_epoch(db)
    _insert_capture(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO vision_label"
            " (label_id, capture_id, label_kind, created_at, author, model_verdict,"
            "  symptom_labels)"
            " VALUES ('label-1', 'capture-1', 'observation',"
            " '2026-08-31T07:00:00+00:00', 'grower', 'normal', '[\"chlorosis\"]')"
        )


def test_a_correction_label_asserts_no_symptom(db):
    """Correcting a scene verdict is not an opportunity to assert a symptom."""
    _insert_epoch(db)
    _insert_capture(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO vision_label"
            " (label_id, capture_id, label_kind, created_at, author, model_verdict,"
            "  corrected_verdict, symptom_labels)"
            " VALUES ('label-1', 'capture-1', 'comparison_correction',"
            " '2026-08-31T07:00:00+00:00', 'grower', 'material_scene_change',"
            " 'normal', '[\"chlorosis\"]')"
        )


def test_labels_supersede_rather_than_overwrite(db):
    """A revised label leaves its predecessor readable."""
    _insert_epoch(db)
    _insert_capture(db)
    for label_id in ("label-1", "label-2"):
        db.execute(
            "INSERT INTO vision_label"
            " (label_id, capture_id, label_kind, created_at, author, symptom_labels)"
            " VALUES (?, 'capture-1', 'observation', '2026-08-31T07:00:00+00:00',"
            " 'grower', '[\"chlorosis\"]')",
            (label_id,),
        )
    db.execute(
        "UPDATE vision_label SET superseded_by = 'label-2' WHERE label_id = ?",
        ("label-1",),
    )
    assert db.execute("SELECT COUNT(*) FROM vision_label").fetchone()[0] == 2


def test_baseline_members_required_matches_the_bucket_default(db):
    """The 30-member validity gate of ADR 0004 is the schema's default."""
    row = db.execute(
        "SELECT sql FROM sqlite_master WHERE name = 'vision_baseline_bucket'"
    ).fetchone()
    assert f"DEFAULT {VISION_BASELINE_MEMBERS_REQUIRED}" in row[0]


def _insert_report(
    db: sqlite3.Connection,
    report_id: str = "report-1",
    *,
    capture_id: str = "capture-1",
    fusion_state: str | None = "no_detected_change",
    fusion_confidence: str | None = "confirmed",
    fusion_coverage: str | None = "complete",
) -> str:
    """Insert a Vision Explainer Report and return its id."""
    db.execute(
        "INSERT INTO vision_explainer_report"
        " (report_id, capture_id, created_at, ai_task_entity_id,"
        "  observation_source, scoring_policy_version, observation,"
        "  environmental_risk, hypothesis, recommendations,"
        "  fusion_state, fusion_confidence, fusion_coverage)"
        " VALUES (?, ?, '2026-08-31T06:05:00+00:00', 'ai_task.cloud',"
        " 'image_pass', 1, 'Canopy is even across all sectors.',"
        " 'No active evaluation.', '', '[]', ?, ?, ?)",
        (report_id, capture_id, fusion_state, fusion_confidence, fusion_coverage),
    )
    return report_id


def test_explainer_report_carries_no_severity(db):
    """Severity is a fusion output; the explainer has no column to overrule it."""
    sql = _table_sql(db, "vision_explainer_report")
    assert "severity" not in sql.lower()


def test_explainer_report_carries_no_symptom_vocabulary(db):
    """V1 emits no machine-readable symptom claim (hub#68)."""
    sql = _table_sql(db, "vision_explainer_report")
    assert "symptom" not in sql.lower()
    assert "issues_detected" not in sql.lower()


def test_explainer_report_is_recordable(db):
    """A complete report attaches to its capture."""
    _insert_epoch(db)
    _insert_capture(db)
    _insert_report(db)
    assert db.execute("SELECT COUNT(*) FROM vision_explainer_report").fetchone()[0] == 1


def test_an_unavailable_fusion_outcome_carries_no_qualifiers(db):
    """State, confidence and coverage are present together or not at all."""
    _insert_epoch(db)
    _insert_capture(db)
    _insert_report(
        db,
        "report-unavailable",
        fusion_state=None,
        fusion_confidence=None,
        fusion_coverage=None,
    )

    with pytest.raises(sqlite3.IntegrityError):
        _insert_report(db, "report-half", fusion_confidence=None)


def test_a_capture_may_carry_more_than_one_report(db):
    """A re-run against another AI task entity is a second report, not an edit."""
    _insert_epoch(db)
    _insert_capture(db)
    _insert_report(db, "report-1")
    _insert_report(db, "report-2")
    assert db.execute("SELECT COUNT(*) FROM vision_explainer_report").fetchone()[0] == 2


def test_deleting_a_capture_removes_its_report(db):
    """Evidence deletion is complete: no narrative outlives its capture."""
    _insert_epoch(db)
    _insert_capture(db)
    _insert_report(db)
    db.execute("DELETE FROM vision_capture WHERE capture_id = 'capture-1'")
    assert db.execute("SELECT COUNT(*) FROM vision_explainer_report").fetchone()[0] == 0
