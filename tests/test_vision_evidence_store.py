"""Behavior tests for the durable Vision Evidence Store."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock
import uuid

import aiosqlite
import pytest

from custom_components.growspace_manager.data_access.vision_evidence_schema import (
    VISION_EVIDENCE_SCHEMA_VERSION,
)
from custom_components.growspace_manager.data_access.vision_evidence_store import (
    VisionEvidenceSchemaTooNewError,
    VisionEvidenceStore,
)
from custom_components.growspace_manager.models.vision_evidence import (
    AdmissionPhase,
    AnalysisState,
    BaselineBucket,
    BaselineMember,
    BaselineState,
    CaptureFileVariant,
    CaptureTrigger,
    CheckupStatus,
    ComparisonOutcome,
    ComparisonVerdict,
    EmbeddingSource,
    FileDeletionReason,
    LabelKind,
    LightState,
    LightWindow,
    ObservationSource,
    VisionEmbedding,
    VisionExplainerReport,
    VisionFusionOutcome,
    VisionLabel,
    VisualComparisonResult,
)


async def _start_capture(
    store: VisionEvidenceStore,
    *,
    captured_at: datetime = datetime(2026, 9, 1, 6, tzinfo=UTC),
    checkup_id: str | None = None,
):
    """Create the common pending capture used by repository behavior tests."""
    if checkup_id is None:
        checkup_id = store.mint_checkup_id()
        await store.async_start_checkup(
            checkup_id=checkup_id,
            growspace_id="gs-1",
            growspace_name="Flower Tent",
            trigger_source=CaptureTrigger.SCHEDULED,
            light_window=LightWindow.EARLY,
            started_at=captured_at,
        )
    capture_id = store.mint_capture_id()
    return await store.async_start_capture(
        capture_id=capture_id,
        checkup_id=checkup_id,
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        camera_id="camera.canopy",
        captured_at=captured_at,
        light_window=LightWindow.EARLY,
        light_state=LightState.ON,
        trigger_source=CaptureTrigger.SCHEDULED,
        image=b"jpeg-capture-bytes",
        content_type="image/jpeg",
    )


@pytest.mark.asyncio
async def test_setup_migrates_once_and_survives_restart(tmp_path: Path) -> None:
    """A reopened store keeps evidence and its forward-only schema version."""
    database = tmp_path / "growspace_vision.db"
    images = tmp_path / "media" / "growspace_vision"

    store = VisionEvidenceStore(database, images)
    await store.async_setup()
    await store.async_close()

    reopened = VisionEvidenceStore(database, images)
    await reopened.async_setup()
    await reopened.async_close()

    async with aiosqlite.connect(database) as connection:
        version = await (await connection.execute("PRAGMA user_version")).fetchone()
        mode = await (await connection.execute("PRAGMA journal_mode")).fetchone()

    assert version == (VISION_EVIDENCE_SCHEMA_VERSION,)
    assert mode == ("wal",)
    assert images.is_dir()


@pytest.mark.asyncio
async def test_setup_refuses_a_database_from_newer_code(tmp_path: Path) -> None:
    """Opening a future schema never attempts an implicit downgrade."""
    database = tmp_path / "growspace_vision.db"
    async with aiosqlite.connect(database) as connection:
        await connection.execute(
            f"PRAGMA user_version = {VISION_EVIDENCE_SCHEMA_VERSION + 1}"
        )
        await connection.commit()

    with pytest.raises(VisionEvidenceSchemaTooNewError):
        await VisionEvidenceStore(database, tmp_path / "images").async_setup()


@pytest.mark.asyncio
async def test_failed_migration_does_not_publish_a_partial_schema(
    tmp_path: Path,
) -> None:
    """A migration error leaves its version and newly-created tables uncommitted."""
    database = tmp_path / "growspace_vision.db"
    async with aiosqlite.connect(database) as connection:
        await connection.execute("CREATE TABLE vision_capture (capture_id TEXT)")
        await connection.commit()

    with pytest.raises(aiosqlite.OperationalError):
        await VisionEvidenceStore(database, tmp_path / "images").async_setup()

    async with aiosqlite.connect(database) as connection:
        version = await (await connection.execute("PRAGMA user_version")).fetchone()
        tables = await (
            await connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        ).fetchall()
    assert version == (0,)
    assert tables == [("vision_capture",)]


@pytest.mark.asyncio
async def test_capture_identity_and_image_survive_restart(tmp_path: Path) -> None:
    """A UUIDv7 capture is durable before any Vision Analysis exists."""
    database = tmp_path / "growspace_vision.db"
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(database, image_root)
    await store.async_setup()
    capture_id = store.mint_capture_id()
    checkup_id = store.mint_checkup_id()
    await store.async_start_checkup(
        checkup_id=checkup_id,
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
    )

    created = await store.async_start_capture(
        capture_id=capture_id,
        checkup_id=checkup_id,
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        camera_id="camera.canopy",
        captured_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
        light_window=LightWindow.EARLY,
        light_state=LightState.ON,
        trigger_source=CaptureTrigger.SCHEDULED,
        image=b"jpeg-capture-bytes",
        content_type="image/jpeg",
    )

    assert uuid.UUID(capture_id).version == 7
    assert created.analysis_state is AnalysisState.PENDING
    assert created.grow_run_id
    assert created.framing_epoch_id
    await store.async_close()

    reopened = VisionEvidenceStore(database, image_root)
    await reopened.async_setup()
    persisted = await reopened.async_get_capture(capture_id)
    files = await reopened.async_get_capture_files(capture_id)
    await reopened.async_close()

    assert persisted == created
    assert files[0].variant is CaptureFileVariant.RAW
    assert files[0].relative_path == f"gs-1/camera.canopy/{capture_id}.raw.jpg"
    assert (image_root / files[0].relative_path).read_bytes() == b"jpeg-capture-bytes"


@pytest.mark.asyncio
async def test_failed_capture_write_does_not_replace_the_tracked_image(
    tmp_path: Path,
) -> None:
    """A rejected database write leaves neither a new nor overwritten file."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    capture_id = store.mint_capture_id()
    arguments = {
        "capture_id": capture_id,
        "checkup_id": store.mint_checkup_id(),
        "growspace_id": "gs-1",
        "growspace_name": "Flower Tent",
        "camera_id": "camera.canopy",
        "captured_at": datetime(2026, 9, 1, 6, tzinfo=UTC),
        "light_window": LightWindow.EARLY,
        "light_state": LightState.ON,
        "trigger_source": CaptureTrigger.SCHEDULED,
        "content_type": "image/jpeg",
    }
    await store.async_start_checkup(
        checkup_id=arguments["checkup_id"],
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at=arguments["captured_at"],
    )
    await store.async_start_capture(image=b"original", **arguments)

    with pytest.raises(aiosqlite.IntegrityError):
        await store.async_start_capture(image=b"replacement", **arguments)

    files = await store.async_get_capture_files(capture_id)
    assert (tmp_path / "images" / files[0].relative_path).read_bytes() == b"original"
    await store.async_close()


@pytest.mark.asyncio
async def test_checkup_groups_captures_and_records_operational_outcome(
    tmp_path: Path,
) -> None:
    """Multi-camera identity is durable and never reconstructed from timestamps."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    checkup_id = store.mint_checkup_id()
    checkup = await store.async_start_checkup(
        checkup_id=checkup_id,
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at=datetime(2026, 9, 1, 6, tzinfo=UTC),
    )
    first = await _start_capture(store, checkup_id=checkup_id)
    second = await store.async_start_capture(
        capture_id=store.mint_capture_id(),
        checkup_id=checkup_id,
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        camera_id="camera.side",
        captured_at=datetime(2026, 9, 1, 6, 0, 2, tzinfo=UTC),
        light_window=LightWindow.EARLY,
        light_state=LightState.ON,
        trigger_source=CaptureTrigger.SCHEDULED,
        image=b"second-camera",
        content_type="image/jpeg",
    )
    finished = await store.async_finish_checkup(
        checkup_id,
        status=CheckupStatus.COMPLETED,
        completed_at=datetime(2026, 9, 1, 6, 0, 4, tzinfo=UTC),
    )

    assert uuid.UUID(checkup.checkup_id).version == 7
    assert checkup.status is None
    assert finished.status is CheckupStatus.COMPLETED
    assert await store.async_get_checkup_captures(checkup_id) == [first, second]
    await store.async_close()


@pytest.mark.asyncio
async def test_quality_history_reconstructs_accepted_tail_and_rejection_streak(
    tmp_path: Path,
) -> None:
    """Camera-relative rails survive restart without learning from rejections."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    accepted = await _start_capture(store)
    first_rejection = await _start_capture(
        store, captured_at=datetime(2026, 9, 1, 7, tzinfo=UTC)
    )
    second_rejection = await _start_capture(
        store, captured_at=datetime(2026, 9, 1, 8, tzinfo=UTC)
    )
    await store.async_record_analysis(
        replace(
            accepted,
            analysis_state=AnalysisState.ANALYZED,
            quality_mean_luminance=100.0,
            quality_clipped_pixel_fraction=0.1,
            quality_mean_absolute_gradient=10.0,
        )
    )
    await store.async_record_analysis(
        replace(
            first_rejection,
            analysis_state=AnalysisState.REJECTED,
            quality_mean_luminance=40.0,
            quality_clipped_pixel_fraction=0.1,
            quality_mean_absolute_gradient=10.0,
            quality_reasons=("exposure_excursion",),
        )
    )
    await store.async_record_analysis(
        replace(
            second_rejection,
            analysis_state=AnalysisState.REJECTED,
            quality_mean_luminance=100.0,
            quality_clipped_pixel_fraction=0.1,
            quality_mean_absolute_gradient=4.0,
            quality_reasons=("detail_collapse",),
        )
    )

    history = await store.async_get_quality_history("camera.canopy")

    assert len(history.accepted) == 1
    assert history.accepted[0].mean_luminance == 100.0
    assert history.relative_rejection_streak == 2

    reanchored = await _start_capture(
        store, captured_at=datetime(2026, 9, 1, 9, tzinfo=UTC)
    )
    await store.async_record_analysis(
        replace(
            reanchored,
            analysis_state=AnalysisState.ANALYZED,
            quality_mean_luminance=40.0,
            quality_clipped_pixel_fraction=0.1,
            quality_mean_absolute_gradient=10.0,
            quality_history_reanchored=True,
        )
    )

    restarted_history = await store.async_get_quality_history("camera.canopy")

    assert [entry.mean_luminance for entry in restarted_history.accepted] == [40.0]
    assert restarted_history.relative_rejection_streak == 0
    await store.async_close()


@pytest.mark.asyncio
async def test_processed_capture_variant_is_tracked_by_the_same_identity(
    tmp_path: Path,
) -> None:
    """A processed rendering shares the capture stem and becomes retention-visible."""
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", image_root)
    await store.async_setup()
    capture = await _start_capture(store)

    processed = await store.async_add_capture_file(
        capture.capture_id,
        variant=CaptureFileVariant.PROCESSED,
        image=b"processed-jpeg",
        content_type="image/jpeg",
    )

    assert processed.relative_path.endswith(f"{capture.capture_id}.processed.jpg")
    assert (image_root / processed.relative_path).read_bytes() == b"processed-jpeg"
    assert {
        item.variant for item in await store.async_get_capture_files(capture.capture_id)
    } == {
        CaptureFileVariant.RAW,
        CaptureFileVariant.PROCESSED,
    }
    await store.async_close()


def _analysis_records(capture):
    """Build one complete comparison write rooted in a pending capture."""
    completed = replace(
        capture,
        analysis_state=AnalysisState.ANALYZED,
        request_id="request-1",
        vision_schema_version=1,
        service_version="1.0.0",
        quality_mean_luminance=0.52,
        quality_clipped_pixel_fraction=0.01,
        quality_mean_absolute_gradient=0.12,
    )
    embedding = VisionEmbedding(
        capture_id=capture.capture_id,
        model_id="dinov2-vits14",
        model_version="1.0.0",
        dimension=2,
        values_f32=b"\x00\x00\x80?\x00\x00\x00@",
        derived_at="2026-09-01T06:00:01+00:00",
        source=EmbeddingSource.LIVE,
    )
    bucket = BaselineBucket(
        bucket_id="bucket-1",
        growspace_id=capture.growspace_id,
        camera_id=capture.camera_id,
        light_window=LightWindow.EARLY,
        grow_run_id=capture.grow_run_id,
        model_id=embedding.model_id,
        model_version=embedding.model_version,
        framing_epoch_id=capture.framing_epoch_id,
        state=BaselineState.MONITORING,
        scoring_policy_version=1,
        created_at="2026-09-01T06:00:01+00:00",
        member_count=1,
    )
    member = BaselineMember(
        bucket_id=bucket.bucket_id,
        capture_id=capture.capture_id,
        admitted_at="2026-09-01T06:00:01+00:00",
        admission_phase=AdmissionPhase.BOOTSTRAP,
    )
    result = VisualComparisonResult(
        result_id="result-1",
        capture_id=capture.capture_id,
        bucket_id=bucket.bucket_id,
        evaluated_at="2026-09-01T06:00:01+00:00",
        outcome=ComparisonOutcome.MONITORING,
        baseline_state=BaselineState.MONITORING,
        samples_collected=0,
        samples_required=30,
        trigger_source=CaptureTrigger.SCHEDULED,
        model_id=embedding.model_id,
        model_version=embedding.model_version,
        scoring_policy_version=1,
        admitted_to_baseline=True,
    )
    return completed, embedding, bucket, member, result


@pytest.mark.asyncio
async def test_analysis_evidence_is_one_durable_write(tmp_path: Path) -> None:
    """Provenance, embedding, result and recorded membership commit together."""
    database = tmp_path / "growspace_vision.db"
    store = VisionEvidenceStore(database, tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    completed, embedding, bucket, member, result = _analysis_records(capture)

    await store.async_record_analysis(
        completed,
        embedding=embedding,
        comparison=result,
        bucket=bucket,
        member=member,
    )
    await store.async_close()

    reopened = VisionEvidenceStore(database, tmp_path / "images")
    await reopened.async_setup()
    assert await reopened.async_get_capture(capture.capture_id) == completed
    assert (
        await reopened.async_get_embedding(
            capture.capture_id, embedding.model_id, embedding.model_version
        )
        == embedding
    )
    assert await reopened.async_get_comparison_results(capture.capture_id) == [result]
    assert await reopened.async_get_baseline_bucket(bucket.bucket_id) == bucket
    assert await reopened.async_get_active_baseline_members(bucket.bucket_id) == [
        member
    ]
    assert (
        await reopened.async_find_baseline_bucket(
            camera_id=bucket.camera_id,
            light_window=bucket.light_window,
            grow_run_id=bucket.grow_run_id,
            model_id=bucket.model_id,
            model_version=bucket.model_version,
            framing_epoch_id=bucket.framing_epoch_id,
            scoring_policy_version=bucket.scoring_policy_version,
        )
        == bucket
    )
    assert await reopened.async_get_active_baseline_embeddings(bucket.bucket_id) == [
        embedding
    ]
    await reopened.async_close()


@pytest.mark.asyncio
async def test_baseline_eviction_remains_auditable(tmp_path: Path) -> None:
    """Rolling-window eviction changes active membership without deleting history."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    completed, embedding, bucket, member, result = _analysis_records(capture)
    await store.async_record_analysis(
        completed,
        embedding=embedding,
        comparison=result,
        bucket=bucket,
        member=member,
    )

    await store.async_evict_baseline_member(
        bucket.bucket_id,
        capture.capture_id,
        evicted_at="2026-09-02T06:00:00+00:00",
        evicted_by_capture_id="newer-capture",
    )

    assert await store.async_get_active_baseline_members(bucket.bucket_id) == []
    assert await store.async_get_baseline_members(bucket.bucket_id) == [
        replace(
            member,
            evicted_at="2026-09-02T06:00:00+00:00",
            evicted_by_capture_id="newer-capture",
        )
    ]
    await store.async_close()


@pytest.mark.asyncio
async def test_rolling_admission_evicts_oldest_member_in_analysis_transaction(
    tmp_path: Path,
) -> None:
    """A normal result cannot commit its 31st member without its paired eviction."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    first = await _start_capture(store)
    first_records = _analysis_records(first)
    await store.async_record_analysis(
        first_records[0],
        embedding=first_records[1],
        comparison=first_records[4],
        bucket=first_records[2],
        member=first_records[3],
    )
    second = await _start_capture(
        store, captured_at=datetime(2026, 9, 2, 6, tzinfo=UTC)
    )
    completed, embedding, bucket, member, result = _analysis_records(second)
    member = replace(
        member,
        admitted_at="2026-09-02T06:00:01+00:00",
        admission_phase=AdmissionPhase.NORMAL,
    )
    result = replace(result, result_id="result-2")

    await store.async_record_analysis(
        completed,
        embedding=embedding,
        comparison=result,
        bucket=bucket,
        member=member,
        evict_capture_id=first.capture_id,
    )

    assert await store.async_get_active_baseline_members(bucket.bucket_id) == [member]
    assert await store.async_get_baseline_members(bucket.bucket_id) == [
        replace(
            first_records[3],
            evicted_at=member.admitted_at,
            evicted_by_capture_id=second.capture_id,
        ),
        member,
    ]
    await store.async_close()


@pytest.mark.asyncio
async def test_failed_analysis_write_rolls_back_every_artifact(tmp_path: Path) -> None:
    """A bad result cannot leave provenance or an embedding half-committed."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    completed, embedding, bucket, member, result = _analysis_records(capture)
    invalid_result = replace(
        result,
        outcome=ComparisonOutcome.SCORED,
        anomaly_score=None,
        verdict=None,
    )

    with pytest.raises(aiosqlite.IntegrityError):
        await store.async_record_analysis(
            completed,
            embedding=embedding,
            comparison=invalid_result,
            bucket=bucket,
            member=member,
        )

    assert await store.async_get_capture(capture.capture_id) == capture
    assert (
        await store.async_get_embedding(
            capture.capture_id, embedding.model_id, embedding.model_version
        )
        is None
    )
    assert await store.async_get_comparison_results(capture.capture_id) == []
    assert await store.async_get_baseline_bucket(bucket.bucket_id) is None
    await store.async_close()


@pytest.mark.asyncio
async def test_fusion_outcome_is_durable_without_an_explainer_report(
    tmp_path: Path,
) -> None:
    """Local-only checkups retain environment and fusion evidence independently."""
    database = tmp_path / "growspace_vision.db"
    store = VisionEvidenceStore(database, tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    outcome = VisionFusionOutcome(
        outcome_id="fusion-1",
        capture_id=capture.capture_id,
        evaluated_at="2026-09-01T06:00:02+00:00",
        scoring_policy_version=1,
        environmental_verdict="risk",
        environmental_evaluated_at="2026-09-01T05:55:00+00:00",
        stress_reasons=("high_vpd",),
        fusion_state="environmental_risk",
        fusion_confidence="confirmed",
        fusion_coverage="complete",
    )

    await store.async_record_fusion_outcome(outcome)
    await store.async_close()

    reopened = VisionEvidenceStore(database, tmp_path / "images")
    await reopened.async_setup()
    assert await reopened.async_get_fusion_outcomes(capture.capture_id) == [outcome]
    await reopened.async_close()


@pytest.mark.asyncio
async def test_explainer_report_preserves_its_fusion_snapshot(tmp_path: Path) -> None:
    """Optional prose stays bound to the fusion outcome it was written against."""
    database = tmp_path / "growspace_vision.db"
    store = VisionEvidenceStore(database, tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    report = VisionExplainerReport(
        report_id="report-1",
        capture_id=capture.capture_id,
        created_at="2026-09-01T06:00:03+00:00",
        ai_task_entity_id="ai_task.cloud",
        observation_source=ObservationSource.IMAGE_PASS,
        scoring_policy_version=1,
        observation="The canopy is even across the frame.",
        environmental_risk="High VPD evaluation is active.",
        hypothesis="",
        recommendations=("Check humidification.",),
        fusion_state="environmental_risk",
        fusion_confidence="confirmed",
        fusion_coverage="complete",
    )

    await store.async_add_explainer_report(report)
    await store.async_close()

    reopened = VisionEvidenceStore(database, tmp_path / "images")
    await reopened.async_setup()
    assert await reopened.async_get_explainer_reports(capture.capture_id) == [report]
    await reopened.async_close()


@pytest.mark.asyncio
async def test_label_revisions_are_append_only_and_pin_the_capture(
    tmp_path: Path,
) -> None:
    """A revision preserves its predecessor and records supersession explicitly."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    original = VisionLabel(
        label_id="label-1",
        capture_id=capture.capture_id,
        label_kind=LabelKind.OBSERVATION,
        created_at="2026-09-01T07:00:00+00:00",
        author="grower",
        symptom_labels=("chlorosis",),
        note="Possible yellowing",
    )
    revision = replace(
        original,
        label_id="label-2",
        created_at="2026-09-01T07:05:00+00:00",
        symptom_labels=("senescence",),
        note="Expected late-run colour change",
    )

    await store.async_add_label(original)
    await store.async_add_label(revision, supersedes_label_id=original.label_id)

    assert await store.async_get_labels(capture.capture_id) == [
        replace(original, superseded_by=revision.label_id),
        revision,
    ]
    assert await store.async_is_capture_pinned(capture.capture_id)
    await store.async_close()


@pytest.mark.asyncio
async def test_failed_label_revision_leaves_no_partial_label(tmp_path: Path) -> None:
    """Superseding a nonexistent predecessor rolls the new label back."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    label = VisionLabel(
        label_id="label-1",
        capture_id=capture.capture_id,
        label_kind=LabelKind.OBSERVATION,
        created_at="2026-09-01T07:00:00+00:00",
        author="grower",
        symptom_labels=("chlorosis",),
    )

    with pytest.raises(KeyError):
        await store.async_add_label(label, supersedes_label_id="missing")

    assert await store.async_get_labels(capture.capture_id) == []
    await store.async_close()


@pytest.mark.asyncio
async def test_retention_deletes_only_old_unpinned_tracked_images(
    tmp_path: Path,
) -> None:
    """Baseline, label and anomalous evidence stays; ordinary old images do not."""
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", image_root)
    await store.async_setup()
    old = datetime(2026, 5, 1, 6, tzinfo=UTC)
    unpinned = await _start_capture(store, captured_at=old)
    baseline_pinned = await _start_capture(store, captured_at=old)
    labelled = await _start_capture(store, captured_at=old)
    anomalous = await _start_capture(store, captured_at=old)
    recent = await _start_capture(store)

    completed, embedding, bucket, member, result = _analysis_records(baseline_pinned)
    await store.async_record_analysis(
        completed,
        embedding=embedding,
        comparison=result,
        bucket=bucket,
        member=member,
    )
    await store.async_add_label(
        VisionLabel(
            label_id="retention-label",
            capture_id=labelled.capture_id,
            label_kind=LabelKind.OBSERVATION,
            created_at="2026-05-01T07:00:00+00:00",
            author="grower",
            symptom_labels=("chlorosis",),
        )
    )
    anomalous_result = replace(
        result,
        result_id="anomalous-result",
        capture_id=anomalous.capture_id,
        bucket_id=None,
        outcome=ComparisonOutcome.SCORED,
        baseline_state=BaselineState.READY,
        anomaly_score=0.72,
        verdict=ComparisonVerdict.UNCERTAIN,
        admitted_to_baseline=False,
    )
    await store.async_record_analysis(
        replace(anomalous, analysis_state=AnalysisState.ANALYZED),
        comparison=anomalous_result,
    )
    untracked = image_root / "untracked.jpg"
    untracked.write_bytes(b"not indexed by the store")

    deleted = await store.async_prune_images(
        image_retention_days=90,
        now=datetime(2026, 9, 1, 12, tzinfo=UTC),
    )

    assert deleted == 1
    unpinned_file = (await store.async_get_capture_files(unpinned.capture_id))[0]
    assert not (image_root / unpinned_file.relative_path).exists()
    assert unpinned_file.deletion_reason is FileDeletionReason.RETENTION
    for capture in (baseline_pinned, labelled, anomalous, recent):
        capture_file = (await store.async_get_capture_files(capture.capture_id))[0]
        assert (image_root / capture_file.relative_path).exists()
    assert untracked.exists()
    assert await store.async_get_capture(unpinned.capture_id) == unpinned
    await store.async_close()


@pytest.mark.asyncio
async def test_zero_days_disables_image_retention(tmp_path: Path) -> None:
    """The explicit zero setting preserves even old unpinned images."""
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", image_root)
    await store.async_setup()
    capture = await _start_capture(store, captured_at=datetime(2020, 1, 1, tzinfo=UTC))

    assert (
        await store.async_prune_images(
            image_retention_days=0,
            now=datetime(2026, 9, 1, tzinfo=UTC),
        )
        == 0
    )
    capture_file = (await store.async_get_capture_files(capture.capture_id))[0]
    assert (image_root / capture_file.relative_path).exists()
    await store.async_close()


@pytest.mark.asyncio
async def test_growspace_deletion_keeps_pinned_captures_as_named_orphans(
    tmp_path: Path,
) -> None:
    """Deleting a growspace removes ordinary evidence but preserves labelled evidence."""
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", image_root)
    await store.async_setup()
    ordinary = await _start_capture(store)
    pinned = await _start_capture(store)
    await store.async_add_label(
        VisionLabel(
            label_id="orphan-label",
            capture_id=pinned.capture_id,
            label_kind=LabelKind.OBSERVATION,
            created_at="2026-09-01T07:00:00+00:00",
            author="grower",
            symptom_labels=("chlorosis",),
        )
    )
    ordinary_file = (await store.async_get_capture_files(ordinary.capture_id))[0]
    pinned_file = (await store.async_get_capture_files(pinned.capture_id))[0]

    deleted = await store.async_delete_growspace("gs-1")

    assert deleted == 1
    assert await store.async_get_capture(ordinary.capture_id) is None
    orphan = await store.async_get_capture(pinned.capture_id)
    assert orphan is not None
    assert orphan.growspace_id == "gs-1"
    assert orphan.growspace_name == "Flower Tent"
    assert not (image_root / ordinary_file.relative_path).exists()
    assert (image_root / pinned_file.relative_path).exists()
    assert await store.async_get_labels(pinned.capture_id)
    await store.async_close()


@pytest.mark.asyncio
async def test_public_boundaries_reject_invalid_identity_time_and_media(
    tmp_path: Path,
) -> None:
    """Invalid caller data is rejected before it can become durable evidence."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    now = datetime(2026, 9, 1, 6, tzinfo=UTC)

    assert await store.async_run_retention(now) == 0
    with pytest.raises(ValueError, match="checkup_id"):
        await store.async_start_checkup(
            checkup_id=str(uuid.uuid4()),
            growspace_id="gs-1",
            growspace_name="Flower Tent",
            trigger_source=CaptureTrigger.SCHEDULED,
            light_window=LightWindow.EARLY,
            started_at=now,
        )
    with pytest.raises(ValueError, match="started_at"):
        await store.async_start_checkup(
            checkup_id=store.mint_checkup_id(),
            growspace_id="gs-1",
            growspace_name="Flower Tent",
            trigger_source=CaptureTrigger.SCHEDULED,
            light_window=LightWindow.EARLY,
            started_at=now.replace(tzinfo=None),
        )

    checkup_id = store.mint_checkup_id()
    await store.async_start_checkup(
        checkup_id=checkup_id,
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at=now,
    )
    capture_arguments = {
        "checkup_id": checkup_id,
        "growspace_id": "gs-1",
        "growspace_name": "Flower Tent",
        "camera_id": "camera.canopy",
        "captured_at": now,
        "light_window": LightWindow.EARLY,
        "light_state": LightState.ON,
        "trigger_source": CaptureTrigger.SCHEDULED,
        "image": b"capture",
        "content_type": "image/jpeg",
    }
    with pytest.raises(ValueError, match="capture_id"):
        await store.async_start_capture(
            capture_id=str(uuid.uuid4()), **capture_arguments
        )
    with pytest.raises(ValueError, match="captured_at"):
        await store.async_start_capture(
            capture_id=store.mint_capture_id(),
            **(capture_arguments | {"captured_at": now.replace(tzinfo=None)}),
        )
    with pytest.raises(ValueError, match="JPEG or PNG"):
        await store.async_start_capture(
            capture_id=store.mint_capture_id(),
            **(capture_arguments | {"content_type": "image/webp"}),
        )
    with pytest.raises(KeyError, match="does not exist"):
        await store.async_start_capture(
            capture_id=store.mint_capture_id(),
            **(capture_arguments | {"checkup_id": store.mint_checkup_id()}),
        )
    with pytest.raises(ValueError, match="does not match"):
        await store.async_start_capture(
            capture_id=store.mint_capture_id(),
            **(capture_arguments | {"growspace_id": "gs-other"}),
        )
    with pytest.raises(KeyError, match="does not exist"):
        await store.async_add_capture_file(
            "missing",
            variant=CaptureFileVariant.PROCESSED,
            image=b"png",
            content_type="image/png",
        )
    with pytest.raises(ValueError, match="cannot be negative"):
        await store.async_prune_images(image_retention_days=-1, now=now)
    with pytest.raises(ValueError, match="timezone-aware"):
        await store.async_prune_images(
            image_retention_days=90, now=now.replace(tzinfo=None)
        )

    capture = await store.async_start_capture(
        capture_id=store.mint_capture_id(), **capture_arguments
    )
    processed = await store.async_add_capture_file(
        capture.capture_id,
        variant=CaptureFileVariant.PROCESSED,
        image=b"png",
        content_type="image/png; charset=binary",
    )
    assert processed.relative_path.endswith(".processed.png")

    await store.async_close()
    await store.async_close()
    with pytest.raises(RuntimeError, match="not open"):
        await store.async_get_capture(capture.capture_id)


@pytest.mark.asyncio
async def test_checkup_state_transitions_roll_back_invalid_updates(
    tmp_path: Path,
) -> None:
    """Duplicate starts and invalid finishes leave the original envelope intact."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    checkup_id = store.mint_checkup_id()
    now = datetime(2026, 9, 1, 6, tzinfo=UTC)
    arguments = {
        "checkup_id": checkup_id,
        "growspace_id": "gs-1",
        "growspace_name": "Flower Tent",
        "trigger_source": CaptureTrigger.SCHEDULED,
        "light_window": LightWindow.EARLY,
        "started_at": now,
    }
    pending = await store.async_start_checkup(**arguments)

    with pytest.raises(aiosqlite.IntegrityError):
        await store.async_start_checkup(**arguments)
    with pytest.raises(ValueError, match="completed_at"):
        await store.async_finish_checkup(
            checkup_id,
            status=CheckupStatus.COMPLETED,
            completed_at=now.replace(tzinfo=None),
        )
    with pytest.raises(KeyError, match="not found"):
        await store.async_finish_checkup(
            "missing",
            status=CheckupStatus.FAILED,
            completed_at=now,
        )
    assert await store.async_get_checkup(checkup_id) == pending

    await store.async_finish_checkup(
        checkup_id, status=CheckupStatus.COMPLETED, completed_at=now
    )
    with pytest.raises(KeyError, match="not found"):
        await store.async_finish_checkup(
            checkup_id, status=CheckupStatus.COMPLETED, completed_at=now
        )
    await store.async_close()


@pytest.mark.asyncio
async def test_image_index_refuses_existing_paths_and_cleans_up_commit_failures(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The filesystem side never overwrites a file or outlives a failed commit."""
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", image_root)
    await store.async_setup()
    now = datetime(2026, 9, 1, 6, tzinfo=UTC)
    checkup_id = store.mint_checkup_id()
    await store.async_start_checkup(
        checkup_id=checkup_id,
        growspace_id="gs-1",
        growspace_name="Flower Tent",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at=now,
    )
    arguments = {
        "checkup_id": checkup_id,
        "growspace_id": "gs-1",
        "growspace_name": "Flower Tent",
        "camera_id": "camera.canopy",
        "captured_at": now,
        "light_window": LightWindow.EARLY,
        "light_state": LightState.ON,
        "trigger_source": CaptureTrigger.SCHEDULED,
        "image": b"capture",
        "content_type": "image/jpeg",
    }

    occupied_id = store.mint_capture_id()
    occupied = image_root / "gs-1" / "camera.canopy" / f"{occupied_id}.raw.jpg"
    occupied.parent.mkdir(parents=True)
    occupied.write_bytes(b"do-not-replace")
    with pytest.raises(FileExistsError):
        await store.async_start_capture(capture_id=occupied_id, **arguments)
    assert occupied.read_bytes() == b"do-not-replace"
    assert await store.async_get_capture(occupied_id) is None

    db = store._require_db()
    original_commit = db.commit
    monkeypatch.setattr(
        db, "commit", AsyncMock(side_effect=aiosqlite.OperationalError("disk full"))
    )
    failed_id = store.mint_capture_id()
    with pytest.raises(aiosqlite.OperationalError, match="disk full"):
        await store.async_start_capture(capture_id=failed_id, **arguments)
    monkeypatch.setattr(db, "commit", original_commit)
    failed_path = image_root / "gs-1" / "camera.canopy" / f"{failed_id}.raw.jpg"
    assert not failed_path.exists()
    assert await store.async_get_capture(failed_id) is None

    capture = await store.async_start_capture(
        capture_id=store.mint_capture_id(), **arguments
    )
    processed_path = (
        image_root / "gs-1" / "camera.canopy" / f"{capture.capture_id}.processed.jpg"
    )
    processed_path.write_bytes(b"occupied")
    with pytest.raises(FileExistsError):
        await store.async_add_capture_file(
            capture.capture_id,
            variant=CaptureFileVariant.PROCESSED,
            image=b"processed",
            content_type="image/jpeg",
        )
    assert processed_path.read_bytes() == b"occupied"

    processed_path.unlink()
    monkeypatch.setattr(
        db, "commit", AsyncMock(side_effect=aiosqlite.OperationalError("disk full"))
    )
    with pytest.raises(aiosqlite.OperationalError, match="disk full"):
        await store.async_add_capture_file(
            capture.capture_id,
            variant=CaptureFileVariant.PROCESSED,
            image=b"processed",
            content_type="image/jpeg",
        )
    monkeypatch.setattr(db, "commit", original_commit)
    assert not processed_path.exists()
    assert {
        item.variant for item in await store.async_get_capture_files(capture.capture_id)
    } == {CaptureFileVariant.RAW}
    await store.async_close()


@pytest.mark.asyncio
async def test_analysis_rejects_cross_capture_and_incomplete_artifacts(
    tmp_path: Path,
) -> None:
    """Repository invariants reject evidence that cannot form one atomic analysis."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    completed, embedding, bucket, member, result = _analysis_records(capture)

    with pytest.raises(ValueError, match="belong to the capture"):
        await store.async_record_analysis(
            completed, embedding=replace(embedding, capture_id="other")
        )
    with pytest.raises(ValueError, match="matching bucket"):
        await store.async_record_analysis(completed, member=member)
    with pytest.raises(ValueError, match="same write"):
        await store.async_record_analysis(completed, comparison=result)
    with pytest.raises(ValueError, match="dimension"):
        await store.async_record_analysis(
            completed, embedding=replace(embedding, values_f32=b"short")
        )
    with pytest.raises(KeyError, match="does not exist"):
        await store.async_record_analysis(
            replace(completed, capture_id=store.mint_capture_id())
        )
    assert await store.async_get_capture(capture.capture_id) == capture
    await store.async_close()


@pytest.mark.asyncio
async def test_additive_repositories_roll_back_duplicate_and_invalid_writes(
    tmp_path: Path,
) -> None:
    """Fusion, report, membership and label failures leave prior evidence intact."""
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", tmp_path / "images")
    await store.async_setup()
    capture = await _start_capture(store)
    completed, embedding, bucket, member, result = _analysis_records(capture)
    await store.async_record_analysis(
        completed,
        embedding=embedding,
        comparison=result,
        bucket=bucket,
        member=member,
    )
    outcome = VisionFusionOutcome(
        outcome_id="fusion-duplicate",
        capture_id=capture.capture_id,
        evaluated_at="2026-09-01T06:00:02+00:00",
        scoring_policy_version=1,
        environmental_verdict="unavailable",
    )
    await store.async_record_fusion_outcome(outcome)
    with pytest.raises(aiosqlite.IntegrityError):
        await store.async_record_fusion_outcome(outcome)

    report = VisionExplainerReport(
        report_id="report-duplicate",
        capture_id=capture.capture_id,
        created_at="2026-09-01T06:00:03+00:00",
        ai_task_entity_id="ai_task.cloud",
        observation_source=ObservationSource.VISUAL_COMPARISON_ONLY,
        scoring_policy_version=1,
        observation="No image was inspected.",
        environmental_risk="",
        hypothesis="",
    )
    await store.async_add_explainer_report(report)
    with pytest.raises(aiosqlite.IntegrityError):
        await store.async_add_explainer_report(report)
    with pytest.raises(KeyError, match="not found"):
        await store.async_evict_baseline_member(
            bucket.bucket_id,
            "missing",
            evicted_at="2026-09-02T06:00:00+00:00",
            evicted_by_capture_id="newer",
        )

    invalid_label = VisionLabel(
        label_id="invalid-label",
        capture_id=capture.capture_id,
        label_kind=LabelKind.OBSERVATION,
        created_at="2026-09-01T07:00:00+00:00",
        author="grower",
        superseded_by="already-set",
    )
    with pytest.raises(ValueError, match="cannot already be superseded"):
        await store.async_add_label(invalid_label)

    assert await store.async_get_fusion_outcomes(capture.capture_id) == [outcome]
    assert await store.async_get_explainer_reports(capture.capture_id) == [report]
    assert await store.async_get_active_baseline_members(bucket.bucket_id) == [member]
    await store.async_close()


@pytest.mark.asyncio
async def test_corrupt_paths_are_contained_during_retention_and_deletion(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A corrupt row cannot make either cleanup operation escape the image root."""
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", image_root)
    await store.async_setup()
    old = datetime(2026, 5, 1, 6, tzinfo=UTC)
    capture = await _start_capture(store, captured_at=old)
    outside = tmp_path / "outside.jpg"
    outside.write_bytes(b"unrelated")
    db = store._require_db()
    await db.execute(
        "UPDATE vision_capture_file SET relative_path = '../outside.jpg'"
        " WHERE capture_id = ?",
        (capture.capture_id,),
    )
    await db.commit()

    assert (
        await store.async_prune_images(
            image_retention_days=90,
            now=datetime(2026, 9, 1, tzinfo=UTC),
        )
        == 0
    )
    assert await store.async_delete_growspace("gs-1") == 0
    assert outside.read_bytes() == b"unrelated"
    assert await store.async_get_capture(capture.capture_id) == capture
    assert "Failed to prune tracked vision image" in caplog.text
    assert "Failed to delete images" in caplog.text
    await store.async_close()


@pytest.mark.asyncio
async def test_growspace_delete_rolls_back_rows_when_database_cleanup_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A database failure retains recoverable rows after files are deleted first."""
    image_root = tmp_path / "images"
    store = VisionEvidenceStore(tmp_path / "growspace_vision.db", image_root)
    await store.async_setup()
    capture = await _start_capture(store)
    capture_file = (await store.async_get_capture_files(capture.capture_id))[0]
    db = store._require_db()
    original_execute = db.execute

    async def failing_execute(sql, parameters=None):
        if sql.startswith("DELETE FROM vision_grow_run_ref"):
            raise aiosqlite.OperationalError("database is read-only")
        if parameters is None:
            return await original_execute(sql)
        return await original_execute(sql, parameters)

    monkeypatch.setattr(db, "execute", failing_execute)
    with pytest.raises(aiosqlite.OperationalError, match="read-only"):
        await store.async_delete_growspace("gs-1")
    monkeypatch.setattr(db, "execute", original_execute)

    assert await store.async_get_capture(capture.capture_id) == capture
    assert not (image_root / capture_file.relative_path).exists()
    await store.async_close()
