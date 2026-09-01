"""Durable repository for Home Assistant-owned vision evidence."""

# Transaction bodies deliberately raise into their adjacent rollback handlers.
# ruff: noqa: TRY301

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
import hashlib
import json
import logging
from pathlib import Path
import uuid

import aiosqlite

from custom_components.growspace_manager.domain.vision_quality import (
    MAX_CONSECUTIVE_RELATIVE_REJECTIONS,
    QUALITY_HISTORY_SIZE,
    QualityHistory,
    QualitySignals,
    RelativeQualityReason,
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
    VisionCapture,
    VisionCaptureFile,
    VisionCheckup,
    VisionEmbedding,
    VisionExplainerReport,
    VisionFusionOutcome,
    VisionLabel,
    VisualComparisonResult,
)

from .vision_evidence_schema import (
    VISION_EVIDENCE_MIGRATIONS,
    VISION_EVIDENCE_SCHEMA_VERSION,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_IMAGE_RETENTION_DAYS = 90


class VisionEvidenceSchemaTooNewError(RuntimeError):
    """Raised when a database was written by newer integration code."""


class VisionEvidenceStore:
    """Own the vision evidence database and its private image corpus."""

    def __init__(
        self,
        database_path: Path,
        image_root: Path,
        *,
        image_retention_days: int = DEFAULT_IMAGE_RETENTION_DAYS,
    ) -> None:
        """Initialize paths without opening resources."""
        self._database_path = database_path
        self._image_root = image_root
        self._image_retention_days = image_retention_days
        self._db: aiosqlite.Connection | None = None
        self._write_lock = asyncio.Lock()

    @staticmethod
    def mint_capture_id() -> str:
        """Mint the time-ordered identity used before a Vision Analysis call."""
        return str(uuid.uuid7())

    @staticmethod
    def mint_checkup_id() -> str:
        """Mint the time-ordered identity of a growspace observation task."""
        return str(uuid.uuid7())

    async def async_setup(self) -> None:
        """Open the database and apply every pending forward migration."""
        await asyncio.to_thread(
            self._database_path.parent.mkdir, parents=True, exist_ok=True
        )
        await asyncio.to_thread(self._image_root.mkdir, parents=True, exist_ok=True)

        connection = await aiosqlite.connect(self._database_path)
        connection.row_factory = aiosqlite.Row
        try:
            await connection.execute("PRAGMA foreign_keys = ON")
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.execute("PRAGMA synchronous = NORMAL")
            row = await (await connection.execute("PRAGMA user_version")).fetchone()
            if row is None:  # pragma: no cover - SQLite PRAGMA always returns one row
                raise RuntimeError("SQLite did not report a schema version")
            current_version = int(row[0])
            if current_version > VISION_EVIDENCE_SCHEMA_VERSION:
                raise VisionEvidenceSchemaTooNewError(
                    "Vision evidence schema "
                    f"{current_version} is newer than supported version "
                    f"{VISION_EVIDENCE_SCHEMA_VERSION}"
                )
            while current_version < VISION_EVIDENCE_SCHEMA_VERSION:
                migration = VISION_EVIDENCE_MIGRATIONS[current_version]
                next_version = current_version + 1
                await connection.executescript(
                    "BEGIN IMMEDIATE;\n"
                    f"{migration}\n"
                    f"PRAGMA user_version = {next_version};\n"
                    "COMMIT;"
                )
                current_version = next_version
            self._db = connection
            await self.async_prune_images(
                image_retention_days=self._image_retention_days,
                now=datetime.now(UTC),
            )
        except Exception:
            await connection.close()
            self._db = None
            raise

    async def async_run_retention(self, now: datetime | None = None) -> int:
        """Run the configured retention policy for setup and daily scheduling."""
        return await self.async_prune_images(
            image_retention_days=self._image_retention_days,
            now=now or datetime.now(UTC),
        )

    async def async_close(self) -> None:
        """Close the database connection, if open."""
        if self._db is None:
            return
        await self._db.close()
        self._db = None

    async def async_start_capture(
        self,
        *,
        capture_id: str,
        checkup_id: str,
        growspace_id: str,
        growspace_name: str,
        camera_id: str,
        captured_at: datetime,
        light_window: LightWindow,
        light_state: LightState,
        trigger_source: CaptureTrigger,
        image: bytes,
        content_type: str,
    ) -> VisionCapture:
        """Persist an image and its pending capture before analysis begins."""
        parsed_id = uuid.UUID(capture_id)
        if parsed_id.version != 7 or str(parsed_id) != capture_id:
            raise ValueError("capture_id must be a canonical UUIDv7 string")
        if captured_at.tzinfo is None:
            raise ValueError("captured_at must be timezone-aware")

        extension = _extension_for_content_type(content_type)
        relative_path = Path(growspace_id, camera_id, f"{capture_id}.raw{extension}")
        destination = self._resolve_image_path(relative_path.as_posix())
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        captured_at_text = captured_at.astimezone(UTC).isoformat()
        created_at = datetime.now(UTC).isoformat()

        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(temporary.write_bytes, image)

        moved = False
        try:
            async with self._write_lock:
                db = self._require_db()
                await db.execute("BEGIN IMMEDIATE")
                try:
                    grow_run_id = await self._async_get_or_create_grow_run(
                        growspace_id, captured_at_text
                    )
                    framing_epoch_id = await self._async_get_or_create_epoch(
                        growspace_id, camera_id, captured_at_text
                    )
                    checkup_cursor = await db.execute(
                        "SELECT growspace_id, trigger_source, light_window"
                        " FROM vision_checkup WHERE checkup_id = ?",
                        (checkup_id,),
                    )
                    checkup = await checkup_cursor.fetchone()
                    if checkup is None:
                        raise KeyError(f"Vision Checkup {checkup_id} does not exist")
                    if (
                        checkup["growspace_id"] != growspace_id
                        or checkup["trigger_source"] != trigger_source.value
                        or checkup["light_window"] != light_window.value
                    ):
                        raise ValueError("Capture metadata does not match its checkup")
                    await db.execute(
                        "INSERT INTO vision_capture"
                        " (capture_id, checkup_id, growspace_id, growspace_name, camera_id,"
                        " grow_run_id, framing_epoch_id, captured_at, light_window,"
                        " light_state, trigger_source, content_sha256, analysis_state,"
                        " quality_reasons, created_at)"
                        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            capture_id,
                            checkup_id,
                            growspace_id,
                            growspace_name,
                            camera_id,
                            grow_run_id,
                            framing_epoch_id,
                            captured_at_text,
                            light_window.value,
                            light_state.value,
                            trigger_source.value,
                            hashlib.sha256(image).hexdigest(),
                            AnalysisState.PENDING.value,
                            "[]",
                            created_at,
                        ),
                    )
                    await db.execute(
                        "INSERT INTO vision_capture_file"
                        " (capture_id, variant, relative_path, byte_size, content_type)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (
                            capture_id,
                            CaptureFileVariant.RAW.value,
                            relative_path.as_posix(),
                            len(image),
                            content_type,
                        ),
                    )
                    if await asyncio.to_thread(destination.exists):
                        raise FileExistsError(destination)
                    await asyncio.to_thread(temporary.replace, destination)
                    moved = True
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except Exception:
            if moved:
                await asyncio.to_thread(destination.unlink, missing_ok=True)
            raise
        finally:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)

        capture = await self.async_get_capture(capture_id)
        if capture is None:  # pragma: no cover - guarded by the transaction above
            raise RuntimeError(f"Capture {capture_id} disappeared after commit")
        return capture

    async def async_start_checkup(
        self,
        *,
        checkup_id: str,
        growspace_id: str,
        growspace_name: str,
        trigger_source: CaptureTrigger,
        light_window: LightWindow,
        started_at: datetime,
    ) -> VisionCheckup:
        """Persist a pending Vision Checkup before any camera is captured."""
        parsed_id = uuid.UUID(checkup_id)
        if parsed_id.version != 7 or str(parsed_id) != checkup_id:
            raise ValueError("checkup_id must be a canonical UUIDv7 string")
        if started_at.tzinfo is None:
            raise ValueError("started_at must be timezone-aware")
        async with self._write_lock:
            db = self._require_db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "INSERT INTO vision_checkup"
                    " (checkup_id, growspace_id, growspace_name, trigger_source,"
                    " light_window, started_at) VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        checkup_id,
                        growspace_id,
                        growspace_name,
                        trigger_source.value,
                        light_window.value,
                        started_at.astimezone(UTC).isoformat(),
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        checkup = await self.async_get_checkup(checkup_id)
        if checkup is None:  # pragma: no cover - guarded by the insert above
            raise RuntimeError(f"Vision Checkup {checkup_id} disappeared after commit")
        return checkup

    async def async_finish_checkup(
        self,
        checkup_id: str,
        *,
        status: CheckupStatus,
        completed_at: datetime,
    ) -> VisionCheckup:
        """Record the operational outcome of a Vision Checkup."""
        if completed_at.tzinfo is None:
            raise ValueError("completed_at must be timezone-aware")
        async with self._write_lock:
            db = self._require_db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "UPDATE vision_checkup SET completed_at = ?, status = ?"
                    " WHERE checkup_id = ? AND status IS NULL",
                    (
                        completed_at.astimezone(UTC).isoformat(),
                        status.value,
                        checkup_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Pending Vision Checkup {checkup_id} not found")
                await db.commit()
            except Exception:
                await db.rollback()
                raise
        checkup = await self.async_get_checkup(checkup_id)
        if checkup is None:  # pragma: no cover - guarded by the update above
            raise RuntimeError(f"Vision Checkup {checkup_id} disappeared after commit")
        return checkup

    async def async_get_checkup(self, checkup_id: str) -> VisionCheckup | None:
        """Return a Vision Checkup by identity."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_checkup WHERE checkup_id = ?", (checkup_id,)
        )
        row = await cursor.fetchone()
        return _checkup_from_row(row) if row is not None else None

    async def async_get_checkup_captures(self, checkup_id: str) -> list[VisionCapture]:
        """Return a checkup's captures in capture-time order."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_capture WHERE checkup_id = ?"
            " ORDER BY captured_at, capture_id",
            (checkup_id,),
        )
        return [_capture_from_row(row) for row in await cursor.fetchall()]

    async def async_get_capture(self, capture_id: str) -> VisionCapture | None:
        """Return a capture by identity."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_capture WHERE capture_id = ?", (capture_id,)
        )
        row = await cursor.fetchone()
        if row is None:
            return None
        return _capture_from_row(row)

    async def async_get_recent_scheduled_captures(
        self, camera_id: str, *, limit: int
    ) -> list[VisionCapture]:
        """Return recent scheduled captures oldest-first for temporal policies."""
        if limit < 1:
            raise ValueError("limit must be positive")
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_capture"
            " WHERE camera_id = ? AND trigger_source = 'scheduled'"
            " AND analysis_state <> 'pending'"
            " ORDER BY captured_at DESC, capture_id DESC LIMIT ?",
            (camera_id, limit),
        )
        captures = [_capture_from_row(row) for row in await cursor.fetchall()]
        captures.reverse()
        return captures

    async def async_get_quality_history(self, camera_id: str) -> QualityHistory:
        """Reconstruct one camera's durable relative-rail state."""
        db = self._require_db()
        cursor = await db.execute(
            "SELECT quality_mean_luminance, quality_clipped_pixel_fraction,"
            " quality_mean_absolute_gradient, quality_history_reanchored"
            " FROM vision_capture"
            " WHERE camera_id = ? AND analysis_state = 'analyzed'"
            " AND quality_mean_luminance IS NOT NULL"
            " AND quality_clipped_pixel_fraction IS NOT NULL"
            " AND quality_mean_absolute_gradient IS NOT NULL"
            " ORDER BY captured_at DESC, capture_id DESC LIMIT ?",
            (camera_id, QUALITY_HISTORY_SIZE),
        )
        accepted_rows = list(await cursor.fetchall())
        for index, row in enumerate(accepted_rows):
            if row["quality_history_reanchored"]:
                accepted_rows = accepted_rows[: index + 1]
                break
        accepted_rows.reverse()
        accepted = tuple(
            QualitySignals(
                mean_luminance=row["quality_mean_luminance"],
                clipped_pixel_fraction=row["quality_clipped_pixel_fraction"],
                mean_absolute_gradient=row["quality_mean_absolute_gradient"],
            )
            for row in accepted_rows
        )

        cursor = await db.execute(
            "SELECT analysis_state, quality_reasons FROM vision_capture"
            " WHERE camera_id = ? AND analysis_state <> 'pending'"
            " ORDER BY captured_at DESC, capture_id DESC LIMIT ?",
            (camera_id, MAX_CONSECUTIVE_RELATIVE_REJECTIONS),
        )
        relative_reasons = {reason.value for reason in RelativeQualityReason}
        rejection_streak = 0
        for row in await cursor.fetchall():
            reasons = set(json.loads(row["quality_reasons"] or "[]"))
            if row["analysis_state"] != AnalysisState.REJECTED.value or not (
                reasons & relative_reasons
            ):
                break
            rejection_streak += 1
        return QualityHistory(
            accepted=accepted,
            relative_rejection_streak=rejection_streak,
        )

    async def async_get_capture_files(self, capture_id: str) -> list[VisionCaptureFile]:
        """Return every recorded image variant for a capture."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_capture_file WHERE capture_id = ? ORDER BY variant",
            (capture_id,),
        )
        return [_capture_file_from_row(row) for row in await cursor.fetchall()]

    async def async_add_capture_file(
        self,
        capture_id: str,
        *,
        variant: CaptureFileVariant,
        image: bytes,
        content_type: str,
    ) -> VisionCaptureFile:
        """Persist and index another rendering of an existing capture."""
        extension = _extension_for_content_type(content_type)
        db = self._require_db()
        cursor = await db.execute(
            "SELECT growspace_id, camera_id FROM vision_capture WHERE capture_id = ?",
            (capture_id,),
        )
        capture = await cursor.fetchone()
        if capture is None:
            raise KeyError(f"Capture {capture_id} does not exist")
        relative_path = Path(
            capture["growspace_id"],
            capture["camera_id"],
            f"{capture_id}.{variant.value}{extension}",
        )
        destination = self._resolve_image_path(relative_path.as_posix())
        temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
        await asyncio.to_thread(destination.parent.mkdir, parents=True, exist_ok=True)
        await asyncio.to_thread(temporary.write_bytes, image)
        moved = False
        try:
            async with self._write_lock:
                await db.execute("BEGIN IMMEDIATE")
                try:
                    await db.execute(
                        "INSERT INTO vision_capture_file"
                        " (capture_id, variant, relative_path, byte_size, content_type)"
                        " VALUES (?, ?, ?, ?, ?)",
                        (
                            capture_id,
                            variant.value,
                            relative_path.as_posix(),
                            len(image),
                            content_type,
                        ),
                    )
                    if await asyncio.to_thread(destination.exists):
                        raise FileExistsError(destination)
                    await asyncio.to_thread(temporary.replace, destination)
                    moved = True
                    await db.commit()
                except Exception:
                    await db.rollback()
                    raise
        except Exception:
            if moved:
                await asyncio.to_thread(destination.unlink, missing_ok=True)
            raise
        finally:
            await asyncio.to_thread(temporary.unlink, missing_ok=True)
        files = await self.async_get_capture_files(capture_id)
        return next(item for item in files if item.variant is variant)

    async def async_record_analysis(
        self,
        capture: VisionCapture,
        *,
        embedding: VisionEmbedding | None = None,
        comparison: VisualComparisonResult | None = None,
        bucket: BaselineBucket | None = None,
        member: BaselineMember | None = None,
        evict_capture_id: str | None = None,
    ) -> None:
        """Commit one analysis and all evidence it produced atomically."""
        capture_id = capture.capture_id
        for record in (embedding, comparison, member):
            if record is not None and record.capture_id != capture_id:
                raise ValueError("Every analysis artifact must belong to the capture")
        if member is not None and (
            bucket is None or member.bucket_id != bucket.bucket_id
        ):
            raise ValueError("Baseline membership requires its matching bucket")
        if evict_capture_id is not None and (member is None or bucket is None):
            raise ValueError("Baseline eviction requires its replacement member")
        if evict_capture_id == capture_id:
            raise ValueError("A capture cannot evict its own baseline membership")
        if comparison is not None and comparison.bucket_id is not None:
            if bucket is None or comparison.bucket_id != bucket.bucket_id:
                raise ValueError("Comparison bucket must be part of the same write")
        if (
            embedding is not None
            and len(embedding.values_f32) != embedding.dimension * 4
        ):
            raise ValueError("Embedding byte length must equal dimension * 4")

        async with self._write_lock:
            db = self._require_db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "UPDATE vision_capture SET"
                    " analysis_state = ?, analysis_error_code = ?, request_id = ?,"
                    " vision_schema_version = ?, service_version = ?,"
                    " quality_mean_luminance = ?,"
                    " quality_clipped_pixel_fraction = ?,"
                    " quality_mean_absolute_gradient = ?, quality_reasons = ?,"
                    " quality_structural_correlation = ?,"
                    " quality_history_reanchored = ?"
                    " WHERE capture_id = ?",
                    (
                        capture.analysis_state.value,
                        capture.analysis_error_code,
                        capture.request_id,
                        capture.vision_schema_version,
                        capture.service_version,
                        capture.quality_mean_luminance,
                        capture.quality_clipped_pixel_fraction,
                        capture.quality_mean_absolute_gradient,
                        json.dumps(capture.quality_reasons),
                        capture.quality_structural_correlation,
                        int(capture.quality_history_reanchored),
                        capture_id,
                    ),
                )
                if cursor.rowcount != 1:
                    raise KeyError(f"Capture {capture_id} does not exist")
                if embedding is not None:
                    await self._async_insert_embedding(embedding)
                if bucket is not None:
                    await self._async_upsert_bucket(bucket)
                if evict_capture_id is not None:
                    assert member is not None
                    assert bucket is not None
                    cursor = await db.execute(
                        "UPDATE vision_baseline_member"
                        " SET evicted_at = ?, evicted_by_capture_id = ?"
                        " WHERE bucket_id = ? AND capture_id = ?"
                        " AND evicted_at IS NULL",
                        (
                            member.admitted_at,
                            capture_id,
                            bucket.bucket_id,
                            evict_capture_id,
                        ),
                    )
                    if cursor.rowcount != 1:
                        raise KeyError(
                            "Active baseline member"
                            f" {bucket.bucket_id}/{evict_capture_id} not found"
                        )
                if comparison is not None:
                    await self._async_insert_comparison(comparison)
                if member is not None:
                    await self._async_insert_member(member)
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def async_get_embedding(
        self, capture_id: str, model_id: str, model_version: str
    ) -> VisionEmbedding | None:
        """Return one model-specific embedding for a capture."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_embedding"
            " WHERE capture_id = ? AND model_id = ? AND model_version = ?",
            (capture_id, model_id, model_version),
        )
        row = await cursor.fetchone()
        return _embedding_from_row(row) if row is not None else None

    async def async_get_comparison_results(
        self, capture_id: str
    ) -> list[VisualComparisonResult]:
        """Return every additive scoring-policy result for a capture."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_comparison_result"
            " WHERE capture_id = ? ORDER BY evaluated_at, result_id",
            (capture_id,),
        )
        return [_comparison_from_row(row) for row in await cursor.fetchall()]

    async def async_get_comparison_trend(
        self,
        *,
        capture_id: str,
        camera_id: str,
        grow_run_id: str,
        framing_epoch_id: str,
        model_id: str,
        model_version: str,
        scoring_policy_version: int,
        before_evaluated_at: str,
        limit: int = 7,
    ) -> list[tuple[VisualComparisonResult, str | None]]:
        """Return earlier provenance-compatible scored measurements newest-first."""
        cursor = await self._require_db().execute(
            "SELECT r.*,(SELECT f.fusion_state FROM vision_fusion_outcome AS f"
            " WHERE f.capture_id = r.capture_id"
            " ORDER BY f.evaluated_at DESC, f.outcome_id DESC LIMIT 1)"
            " AS trend_fusion_state"
            " FROM vision_comparison_result AS r"
            " JOIN vision_capture AS c ON c.capture_id = r.capture_id"
            " WHERE r.capture_id <> ? AND r.evaluated_at < ? AND c.camera_id = ?"
            " AND c.grow_run_id = ? AND c.framing_epoch_id = ?"
            " AND r.model_id = ? AND r.model_version = ?"
            " AND r.scoring_policy_version = ? AND r.outcome = 'scored'"
            " ORDER BY r.evaluated_at DESC, r.result_id DESC LIMIT ?",
            (
                capture_id,
                before_evaluated_at,
                camera_id,
                grow_run_id,
                framing_epoch_id,
                model_id,
                model_version,
                scoring_policy_version,
                limit,
            ),
        )
        rows = await cursor.fetchall()
        return [(_comparison_from_row(row), row["trend_fusion_state"]) for row in rows]

    async def async_record_fusion_outcome(self, outcome: VisionFusionOutcome) -> None:
        """Persist capture-specific environmental and fusion evidence."""
        async with self._write_lock:
            db = self._require_db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "INSERT INTO vision_fusion_outcome"
                    " (outcome_id, capture_id, evaluated_at, scoring_policy_version,"
                    " environmental_verdict, environmental_evaluated_at, stress_reasons,"
                    " mold_reasons, fusion_state, fusion_confidence, fusion_coverage,"
                    " unavailable_reasons) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        outcome.outcome_id,
                        outcome.capture_id,
                        outcome.evaluated_at,
                        outcome.scoring_policy_version,
                        outcome.environmental_verdict,
                        outcome.environmental_evaluated_at,
                        json.dumps(outcome.stress_reasons),
                        json.dumps(outcome.mold_reasons),
                        outcome.fusion_state,
                        outcome.fusion_confidence,
                        outcome.fusion_coverage,
                        json.dumps(outcome.unavailable_reasons),
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def async_get_fusion_outcomes(
        self, capture_id: str
    ) -> list[VisionFusionOutcome]:
        """Return additive fusion outcomes for one capture."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_fusion_outcome WHERE capture_id = ?"
            " ORDER BY evaluated_at, outcome_id",
            (capture_id,),
        )
        return [_fusion_from_row(row) for row in await cursor.fetchall()]

    async def async_add_explainer_report(self, report: VisionExplainerReport) -> None:
        """Persist optional explainer prose with its fusion snapshot."""
        async with self._write_lock:
            db = self._require_db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "INSERT INTO vision_explainer_report"
                    " (report_id, capture_id, created_at, ai_task_entity_id,"
                    " observation_source, scoring_policy_version, observation,"
                    " environmental_risk, hypothesis, recommendations, fusion_state,"
                    " fusion_confidence, fusion_coverage, fusion_unavailable_reasons)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        report.report_id,
                        report.capture_id,
                        report.created_at,
                        report.ai_task_entity_id,
                        report.observation_source.value,
                        report.scoring_policy_version,
                        report.observation,
                        report.environmental_risk,
                        report.hypothesis,
                        json.dumps(report.recommendations),
                        report.fusion_state,
                        report.fusion_confidence,
                        report.fusion_coverage,
                        json.dumps(report.fusion_unavailable_reasons),
                    ),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def async_get_explainer_reports(
        self, capture_id: str
    ) -> list[VisionExplainerReport]:
        """Return optional explainer reports for one capture."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_explainer_report WHERE capture_id = ?"
            " ORDER BY created_at, report_id",
            (capture_id,),
        )
        return [_report_from_row(row) for row in await cursor.fetchall()]

    async def async_get_baseline_bucket(self, bucket_id: str) -> BaselineBucket | None:
        """Return a Baseline Bucket by identity."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_baseline_bucket WHERE bucket_id = ?", (bucket_id,)
        )
        row = await cursor.fetchone()
        return _bucket_from_row(row) if row is not None else None

    async def async_find_baseline_bucket(
        self,
        *,
        camera_id: str,
        light_window: LightWindow,
        grow_run_id: str,
        model_id: str,
        model_version: str,
        framing_epoch_id: str,
        scoring_policy_version: int,
    ) -> BaselineBucket | None:
        """Find the exact provenance-compatible Baseline Bucket."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_baseline_bucket"
            " WHERE camera_id = ? AND light_window = ? AND grow_run_id = ?"
            " AND model_id = ? AND model_version = ? AND framing_epoch_id = ?"
            " AND scoring_policy_version = ?",
            (
                camera_id,
                light_window.value,
                grow_run_id,
                model_id,
                model_version,
                framing_epoch_id,
                scoring_policy_version,
            ),
        )
        row = await cursor.fetchone()
        return _bucket_from_row(row) if row is not None else None

    async def async_get_active_baseline_members(
        self, bucket_id: str
    ) -> list[BaselineMember]:
        """Return active recorded membership in admission order."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_baseline_member"
            " WHERE bucket_id = ? AND evicted_at IS NULL"
            " ORDER BY admitted_at, capture_id",
            (bucket_id,),
        )
        return [_member_from_row(row) for row in await cursor.fetchall()]

    async def async_get_baseline_members(self, bucket_id: str) -> list[BaselineMember]:
        """Return the complete admission and eviction audit trail."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_baseline_member WHERE bucket_id = ?"
            " ORDER BY admitted_at, capture_id",
            (bucket_id,),
        )
        return [_member_from_row(row) for row in await cursor.fetchall()]

    async def async_get_active_baseline_embeddings(
        self, bucket_id: str
    ) -> list[VisionEmbedding]:
        """Return newest active embeddings matching the bucket's encoder."""
        cursor = await self._require_db().execute(
            "SELECT e.* FROM vision_baseline_member AS m"
            " JOIN vision_baseline_bucket AS b ON b.bucket_id = m.bucket_id"
            " JOIN vision_embedding AS e ON e.capture_id = m.capture_id"
            "  AND e.model_id = b.model_id AND e.model_version = b.model_version"
            " WHERE m.bucket_id = ? AND m.evicted_at IS NULL"
            " ORDER BY m.admitted_at DESC, m.capture_id DESC"
            " LIMIT (SELECT members_required FROM vision_baseline_bucket"
            "        WHERE bucket_id = ?)",
            (bucket_id, bucket_id),
        )
        return [_embedding_from_row(row) for row in await cursor.fetchall()]

    async def async_evict_baseline_member(
        self,
        bucket_id: str,
        capture_id: str,
        *,
        evicted_at: str,
        evicted_by_capture_id: str,
    ) -> None:
        """Record rolling-window eviction without deleting membership."""
        async with self._write_lock:
            db = self._require_db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                cursor = await db.execute(
                    "UPDATE vision_baseline_member"
                    " SET evicted_at = ?, evicted_by_capture_id = ?"
                    " WHERE bucket_id = ? AND capture_id = ? AND evicted_at IS NULL",
                    (evicted_at, evicted_by_capture_id, bucket_id, capture_id),
                )
                if cursor.rowcount != 1:
                    raise KeyError(
                        f"Active baseline member {bucket_id}/{capture_id} not found"
                    )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def async_add_label(
        self, label: VisionLabel, *, supersedes_label_id: str | None = None
    ) -> None:
        """Append a label and optionally supersede its predecessor atomically."""
        if label.superseded_by is not None:
            raise ValueError("A newly appended label cannot already be superseded")
        async with self._write_lock:
            db = self._require_db()
            await db.execute("BEGIN IMMEDIATE")
            try:
                await db.execute(
                    "INSERT INTO vision_label"
                    " (label_id, capture_id, label_kind, created_at, author,"
                    " model_verdict, model_anomaly_score, model_id, model_version,"
                    " scoring_policy_version, corrected_verdict, symptom_labels,"
                    " note, observed_from, observed_to, excluded, exclusion_reason)"
                    " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        label.label_id,
                        label.capture_id,
                        label.label_kind.value,
                        label.created_at,
                        label.author,
                        label.model_verdict.value if label.model_verdict else None,
                        label.model_anomaly_score,
                        label.model_id,
                        label.model_version,
                        label.scoring_policy_version,
                        (
                            label.corrected_verdict.value
                            if label.corrected_verdict
                            else None
                        ),
                        (
                            json.dumps(label.symptom_labels)
                            if label.symptom_labels
                            else None
                        ),
                        label.note,
                        label.observed_from,
                        label.observed_to,
                        int(label.excluded),
                        label.exclusion_reason,
                    ),
                )
                if supersedes_label_id is not None:
                    cursor = await db.execute(
                        "UPDATE vision_label SET superseded_by = ?"
                        " WHERE label_id = ? AND capture_id = ?"
                        " AND superseded_by IS NULL",
                        (label.label_id, supersedes_label_id, label.capture_id),
                    )
                    if cursor.rowcount != 1:
                        raise KeyError(
                            f"Active predecessor label {supersedes_label_id} not found"
                        )
                await db.commit()
            except Exception:
                await db.rollback()
                raise

    async def async_get_labels(self, capture_id: str) -> list[VisionLabel]:
        """Return the complete append-only label history for a capture."""
        cursor = await self._require_db().execute(
            "SELECT * FROM vision_label WHERE capture_id = ?"
            " ORDER BY created_at, label_id",
            (capture_id,),
        )
        return [_label_from_row(row) for row in await cursor.fetchall()]

    async def async_is_capture_pinned(self, capture_id: str) -> bool:
        """Return whether retention must preserve this capture's images."""
        cursor = await self._require_db().execute(
            "SELECT ("
            " EXISTS(SELECT 1 FROM vision_baseline_member"
            "        WHERE capture_id = ? AND evicted_at IS NULL)"
            " OR EXISTS(SELECT 1 FROM vision_label WHERE capture_id = ?)"
            " OR EXISTS(SELECT 1 FROM vision_comparison_result"
            "           WHERE capture_id = ?"
            "           AND verdict IN ('uncertain', 'material_scene_change'))"
            ")",
            (capture_id, capture_id, capture_id),
        )
        row = await cursor.fetchone()
        if row is None:  # pragma: no cover - aggregate SELECT always returns one row
            return False
        return bool(row[0])

    async def async_prune_images(
        self, *, image_retention_days: int, now: datetime
    ) -> int:
        """Delete old unpinned tracked files while retaining every evidence row."""
        if image_retention_days < 0:
            raise ValueError("image_retention_days cannot be negative")
        if image_retention_days == 0:
            return 0
        if now.tzinfo is None:
            raise ValueError("now must be timezone-aware")
        cutoff = (
            now.astimezone(UTC) - timedelta(days=image_retention_days)
        ).isoformat()
        deleted_at = now.astimezone(UTC).isoformat()

        async with self._write_lock:
            db = self._require_db()
            cursor = await db.execute(
                "SELECT f.* FROM vision_capture_file AS f"
                " JOIN vision_capture AS c ON c.capture_id = f.capture_id"
                " WHERE f.deleted_at IS NULL AND c.captured_at < ?"
                " AND NOT EXISTS ("
                "   SELECT 1 FROM vision_baseline_member AS m"
                "   WHERE m.capture_id = c.capture_id AND m.evicted_at IS NULL"
                " )"
                " AND NOT EXISTS ("
                "   SELECT 1 FROM vision_label AS l"
                "   WHERE l.capture_id = c.capture_id"
                " )"
                " AND NOT EXISTS ("
                "   SELECT 1 FROM vision_comparison_result AS r"
                "   WHERE r.capture_id = c.capture_id"
                "   AND r.verdict IN ('uncertain', 'material_scene_change')"
                " )"
                " ORDER BY c.captured_at, f.capture_id, f.variant",
                (cutoff,),
            )
            candidates = await cursor.fetchall()
            deleted = 0
            for row in candidates:
                try:
                    path = self._resolve_image_path(row["relative_path"])
                    await asyncio.to_thread(path.unlink, missing_ok=True)
                except OSError, ValueError:
                    _LOGGER.warning(
                        "Failed to prune tracked vision image %s",
                        row["relative_path"],
                        exc_info=True,
                    )
                    continue
                await db.execute(
                    "UPDATE vision_capture_file"
                    " SET deleted_at = ?, deletion_reason = ?"
                    " WHERE capture_id = ? AND variant = ? AND deleted_at IS NULL",
                    (
                        deleted_at,
                        FileDeletionReason.RETENTION.value,
                        row["capture_id"],
                        row["variant"],
                    ),
                )
                await db.commit()
                deleted += 1
            return deleted

    async def async_delete_growspace(self, growspace_id: str) -> int:
        """Delete ordinary evidence while preserving pinned captures as orphans."""
        async with self._write_lock:
            db = self._require_db()
            cursor = await db.execute(
                "SELECT c.capture_id FROM vision_capture AS c"
                " WHERE c.growspace_id = ?"
                " AND NOT EXISTS ("
                "   SELECT 1 FROM vision_baseline_member AS m"
                "   WHERE m.capture_id = c.capture_id AND m.evicted_at IS NULL"
                " )"
                " AND NOT EXISTS ("
                "   SELECT 1 FROM vision_label AS l"
                "   WHERE l.capture_id = c.capture_id"
                " )"
                " AND NOT EXISTS ("
                "   SELECT 1 FROM vision_comparison_result AS r"
                "   WHERE r.capture_id = c.capture_id"
                "   AND r.verdict IN ('uncertain', 'material_scene_change')"
                " ) ORDER BY c.capture_id",
                (growspace_id,),
            )
            candidates = [str(row[0]) for row in await cursor.fetchall()]
            deletable: list[str] = []
            for capture_id in candidates:
                files_cursor = await db.execute(
                    "SELECT relative_path FROM vision_capture_file"
                    " WHERE capture_id = ? AND deleted_at IS NULL",
                    (capture_id,),
                )
                paths = [str(row[0]) for row in await files_cursor.fetchall()]
                try:
                    for relative_path in paths:
                        path = self._resolve_image_path(relative_path)
                        await asyncio.to_thread(path.unlink, missing_ok=True)
                except OSError, ValueError:
                    _LOGGER.warning(
                        "Failed to delete images for removed growspace capture %s",
                        capture_id,
                        exc_info=True,
                    )
                    continue
                deletable.append(capture_id)

            await db.execute("BEGIN IMMEDIATE")
            try:
                if deletable:
                    await db.executemany(
                        "DELETE FROM vision_capture WHERE capture_id = ?",
                        ((capture_id,) for capture_id in deletable),
                    )
                await db.execute(
                    "DELETE FROM vision_baseline_bucket"
                    " WHERE growspace_id = ? AND NOT EXISTS ("
                    "   SELECT 1 FROM vision_baseline_member AS m"
                    "   WHERE m.bucket_id = vision_baseline_bucket.bucket_id"
                    " )",
                    (growspace_id,),
                )
                await db.execute(
                    "DELETE FROM vision_checkup"
                    " WHERE growspace_id = ? AND NOT EXISTS ("
                    "   SELECT 1 FROM vision_capture AS c"
                    "   WHERE c.checkup_id = vision_checkup.checkup_id"
                    " )",
                    (growspace_id,),
                )
                await db.execute(
                    "DELETE FROM vision_framing_epoch"
                    " WHERE growspace_id = ?"
                    " AND NOT EXISTS ("
                    "   SELECT 1 FROM vision_capture AS c"
                    "   WHERE c.framing_epoch_id = vision_framing_epoch.epoch_id"
                    " )"
                    " AND NOT EXISTS ("
                    "   SELECT 1 FROM vision_baseline_bucket AS b"
                    "   WHERE b.framing_epoch_id = vision_framing_epoch.epoch_id"
                    " )",
                    (growspace_id,),
                )
                await db.execute(
                    "DELETE FROM vision_grow_run_ref WHERE growspace_id = ?",
                    (growspace_id,),
                )
                await db.commit()
            except Exception:
                await db.rollback()
                raise
            return len(deletable)

    def _resolve_image_path(self, relative_path: str) -> Path:
        """Resolve a stored path while containing corrupt rows below the image root."""
        root = self._image_root.resolve()
        path = (root / relative_path).resolve()
        if not path.is_relative_to(root):
            raise ValueError(f"Vision image path escapes its root: {relative_path}")
        return path

    async def _async_insert_embedding(self, embedding: VisionEmbedding) -> None:
        """Insert an embedding inside the caller's transaction."""
        await self._require_db().execute(
            "INSERT INTO vision_embedding"
            " (capture_id, model_id, model_version, dimension, values_f32,"
            " derived_at, source) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                embedding.capture_id,
                embedding.model_id,
                embedding.model_version,
                embedding.dimension,
                embedding.values_f32,
                embedding.derived_at,
                embedding.source.value,
            ),
        )

    async def _async_upsert_bucket(self, bucket: BaselineBucket) -> None:
        """Insert or refresh a bucket's cached state inside a transaction."""
        await self._require_db().execute(
            "INSERT INTO vision_baseline_bucket"
            " (bucket_id, growspace_id, camera_id, light_window, grow_run_id,"
            " model_id, model_version, framing_epoch_id, state, member_count,"
            " members_required, centroid, calibration_distances, last_admitted_at,"
            " recomputed_at, scoring_policy_version, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(bucket_id) DO UPDATE SET"
            " state = excluded.state, member_count = excluded.member_count,"
            " members_required = excluded.members_required,"
            " centroid = excluded.centroid,"
            " calibration_distances = excluded.calibration_distances,"
            " last_admitted_at = excluded.last_admitted_at,"
            " recomputed_at = excluded.recomputed_at,"
            " scoring_policy_version = excluded.scoring_policy_version",
            (
                bucket.bucket_id,
                bucket.growspace_id,
                bucket.camera_id,
                bucket.light_window.value,
                bucket.grow_run_id,
                bucket.model_id,
                bucket.model_version,
                bucket.framing_epoch_id,
                bucket.state.value,
                bucket.member_count,
                bucket.members_required,
                bucket.centroid,
                bucket.calibration_distances,
                bucket.last_admitted_at,
                bucket.recomputed_at,
                bucket.scoring_policy_version,
                bucket.created_at,
            ),
        )

    async def _async_insert_comparison(
        self, comparison: VisualComparisonResult
    ) -> None:
        """Insert an additive comparison result inside a transaction."""
        await self._require_db().execute(
            "INSERT INTO vision_comparison_result"
            " (result_id, capture_id, bucket_id, evaluated_at, outcome,"
            " baseline_state, samples_collected, samples_required, raw_distance,"
            " anomaly_score, verdict, comparison_confidence, admitted_to_baseline,"
            " unavailable_reasons, trigger_source, model_id, model_version,"
            " scoring_policy_version)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                comparison.result_id,
                comparison.capture_id,
                comparison.bucket_id,
                comparison.evaluated_at,
                comparison.outcome.value,
                (
                    comparison.baseline_state.value
                    if comparison.baseline_state is not None
                    else None
                ),
                comparison.samples_collected,
                comparison.samples_required,
                comparison.raw_distance,
                comparison.anomaly_score,
                comparison.verdict.value if comparison.verdict is not None else None,
                comparison.comparison_confidence,
                int(comparison.admitted_to_baseline),
                json.dumps(comparison.unavailable_reasons),
                comparison.trigger_source.value,
                comparison.model_id,
                comparison.model_version,
                comparison.scoring_policy_version,
            ),
        )

    async def _async_insert_member(self, member: BaselineMember) -> None:
        """Record an admission fact inside a transaction."""
        await self._require_db().execute(
            "INSERT INTO vision_baseline_member"
            " (bucket_id, capture_id, admitted_at, admission_phase, evicted_at,"
            " evicted_by_capture_id) VALUES (?, ?, ?, ?, ?, ?)",
            (
                member.bucket_id,
                member.capture_id,
                member.admitted_at,
                member.admission_phase.value,
                member.evicted_at,
                member.evicted_by_capture_id,
            ),
        )

    async def _async_get_or_create_grow_run(
        self, growspace_id: str, started_at: str
    ) -> str:
        """Return the persisted surrogate Grow Run identity for a growspace."""
        db = self._require_db()
        cursor = await db.execute(
            "SELECT grow_run_id FROM vision_grow_run_ref WHERE growspace_id = ?",
            (growspace_id,),
        )
        row = await cursor.fetchone()
        if row is not None:
            return str(row[0])
        grow_run_id = str(uuid.uuid7())
        await db.execute(
            "INSERT INTO vision_grow_run_ref"
            " (growspace_id, grow_run_id, started_at, source)"
            " VALUES (?, ?, ?, 'surrogate')",
            (growspace_id, grow_run_id, started_at),
        )
        return grow_run_id

    async def _async_get_or_create_epoch(
        self, growspace_id: str, camera_id: str, started_at: str
    ) -> str:
        """Return the current Framing Epoch, creating the initial one if absent."""
        db = self._require_db()
        cursor = await db.execute(
            "SELECT epoch_id FROM vision_framing_epoch"
            " WHERE growspace_id = ? AND camera_id = ?"
            " ORDER BY started_at DESC LIMIT 1",
            (growspace_id, camera_id),
        )
        row = await cursor.fetchone()
        if row is not None:
            return str(row[0])
        epoch_id = str(uuid.uuid7())
        await db.execute(
            "INSERT INTO vision_framing_epoch"
            " (epoch_id, growspace_id, camera_id, started_at, reason)"
            " VALUES (?, ?, ?, ?, 'initial')",
            (epoch_id, growspace_id, camera_id, started_at),
        )
        return epoch_id

    def _require_db(self) -> aiosqlite.Connection:
        """Return the open connection or reject use outside its lifecycle."""
        if self._db is None:
            raise RuntimeError("Vision Evidence Store is not open")
        return self._db


def _extension_for_content_type(content_type: str) -> str:
    """Return the truthful extension accepted by the Vision V1 contract."""
    media_type = content_type.partition(";")[0].strip().lower()
    if media_type == "image/jpeg":
        return ".jpg"
    if media_type == "image/png":
        return ".png"
    raise ValueError("Vision captures must be JPEG or PNG")


def _capture_from_row(row: aiosqlite.Row) -> VisionCapture:
    """Decode a capture row into the locked record model."""
    return VisionCapture(
        capture_id=row["capture_id"],
        checkup_id=row["checkup_id"],
        growspace_id=row["growspace_id"],
        growspace_name=row["growspace_name"],
        camera_id=row["camera_id"],
        grow_run_id=row["grow_run_id"],
        framing_epoch_id=row["framing_epoch_id"],
        captured_at=row["captured_at"],
        light_window=LightWindow(row["light_window"]),
        light_state=LightState(row["light_state"]),
        trigger_source=CaptureTrigger(row["trigger_source"]),
        content_sha256=row["content_sha256"],
        analysis_state=AnalysisState(row["analysis_state"]),
        analysis_error_code=row["analysis_error_code"],
        request_id=row["request_id"],
        vision_schema_version=row["vision_schema_version"],
        service_version=row["service_version"],
        quality_mean_luminance=row["quality_mean_luminance"],
        quality_clipped_pixel_fraction=row["quality_clipped_pixel_fraction"],
        quality_mean_absolute_gradient=row["quality_mean_absolute_gradient"],
        quality_reasons=tuple(json.loads(row["quality_reasons"] or "[]")),
        quality_structural_correlation=row["quality_structural_correlation"],
        quality_history_reanchored=bool(row["quality_history_reanchored"]),
        created_at=row["created_at"],
    )


def _checkup_from_row(row: aiosqlite.Row) -> VisionCheckup:
    """Decode a durable Vision Checkup row."""
    status = row["status"]
    return VisionCheckup(
        checkup_id=row["checkup_id"],
        growspace_id=row["growspace_id"],
        growspace_name=row["growspace_name"],
        trigger_source=CaptureTrigger(row["trigger_source"]),
        light_window=LightWindow(row["light_window"]),
        started_at=row["started_at"],
        completed_at=row["completed_at"],
        status=CheckupStatus(status) if status is not None else None,
    )


def _capture_file_from_row(row: aiosqlite.Row) -> VisionCaptureFile:
    """Decode a file row into the locked record model."""
    deletion_reason = row["deletion_reason"]
    return VisionCaptureFile(
        capture_id=row["capture_id"],
        variant=CaptureFileVariant(row["variant"]),
        relative_path=row["relative_path"],
        byte_size=row["byte_size"],
        content_type=row["content_type"],
        deleted_at=row["deleted_at"],
        deletion_reason=(
            FileDeletionReason(deletion_reason) if deletion_reason is not None else None
        ),
    )


def _embedding_from_row(row: aiosqlite.Row) -> VisionEmbedding:
    """Decode an embedding row."""
    return VisionEmbedding(
        capture_id=row["capture_id"],
        model_id=row["model_id"],
        model_version=row["model_version"],
        dimension=row["dimension"],
        values_f32=row["values_f32"],
        derived_at=row["derived_at"],
        source=EmbeddingSource(row["source"]),
    )


def _comparison_from_row(row: aiosqlite.Row) -> VisualComparisonResult:
    """Decode a Visual Comparison Result row."""
    baseline_state = row["baseline_state"]
    verdict = row["verdict"]
    return VisualComparisonResult(
        result_id=row["result_id"],
        capture_id=row["capture_id"],
        bucket_id=row["bucket_id"],
        evaluated_at=row["evaluated_at"],
        outcome=ComparisonOutcome(row["outcome"]),
        baseline_state=(
            BaselineState(baseline_state) if baseline_state is not None else None
        ),
        samples_collected=row["samples_collected"],
        samples_required=row["samples_required"],
        raw_distance=row["raw_distance"],
        anomaly_score=row["anomaly_score"],
        verdict=ComparisonVerdict(verdict) if verdict is not None else None,
        comparison_confidence=row["comparison_confidence"],
        admitted_to_baseline=bool(row["admitted_to_baseline"]),
        unavailable_reasons=tuple(json.loads(row["unavailable_reasons"] or "[]")),
        trigger_source=CaptureTrigger(row["trigger_source"]),
        model_id=row["model_id"],
        model_version=row["model_version"],
        scoring_policy_version=row["scoring_policy_version"],
    )


def _fusion_from_row(row: aiosqlite.Row) -> VisionFusionOutcome:
    """Decode a capture-specific Evidence Fusion Outcome row."""
    return VisionFusionOutcome(
        outcome_id=row["outcome_id"],
        capture_id=row["capture_id"],
        evaluated_at=row["evaluated_at"],
        scoring_policy_version=row["scoring_policy_version"],
        environmental_verdict=row["environmental_verdict"],
        environmental_evaluated_at=row["environmental_evaluated_at"],
        stress_reasons=tuple(json.loads(row["stress_reasons"])),
        mold_reasons=tuple(json.loads(row["mold_reasons"])),
        fusion_state=row["fusion_state"],
        fusion_confidence=row["fusion_confidence"],
        fusion_coverage=row["fusion_coverage"],
        unavailable_reasons=tuple(json.loads(row["unavailable_reasons"])),
    )


def _report_from_row(row: aiosqlite.Row) -> VisionExplainerReport:
    """Decode an optional Vision Explainer Report row."""
    return VisionExplainerReport(
        report_id=row["report_id"],
        capture_id=row["capture_id"],
        created_at=row["created_at"],
        ai_task_entity_id=row["ai_task_entity_id"],
        observation_source=ObservationSource(row["observation_source"]),
        scoring_policy_version=row["scoring_policy_version"],
        observation=row["observation"],
        environmental_risk=row["environmental_risk"],
        hypothesis=row["hypothesis"],
        recommendations=tuple(json.loads(row["recommendations"])),
        fusion_state=row["fusion_state"],
        fusion_confidence=row["fusion_confidence"],
        fusion_coverage=row["fusion_coverage"],
        fusion_unavailable_reasons=tuple(
            json.loads(row["fusion_unavailable_reasons"] or "[]")
        ),
    )


def _bucket_from_row(row: aiosqlite.Row) -> BaselineBucket:
    """Decode a Baseline Bucket row."""
    return BaselineBucket(
        bucket_id=row["bucket_id"],
        growspace_id=row["growspace_id"],
        camera_id=row["camera_id"],
        light_window=LightWindow(row["light_window"]),
        grow_run_id=row["grow_run_id"],
        model_id=row["model_id"],
        model_version=row["model_version"],
        framing_epoch_id=row["framing_epoch_id"],
        state=BaselineState(row["state"]),
        member_count=row["member_count"],
        members_required=row["members_required"],
        centroid=row["centroid"],
        calibration_distances=row["calibration_distances"],
        last_admitted_at=row["last_admitted_at"],
        recomputed_at=row["recomputed_at"],
        scoring_policy_version=row["scoring_policy_version"],
        created_at=row["created_at"],
    )


def _member_from_row(row: aiosqlite.Row) -> BaselineMember:
    """Decode a recorded Baseline Bucket membership row."""
    return BaselineMember(
        bucket_id=row["bucket_id"],
        capture_id=row["capture_id"],
        admitted_at=row["admitted_at"],
        admission_phase=AdmissionPhase(row["admission_phase"]),
        evicted_at=row["evicted_at"],
        evicted_by_capture_id=row["evicted_by_capture_id"],
    )


def _label_from_row(row: aiosqlite.Row) -> VisionLabel:
    """Decode an append-only Vision Label row."""
    model_verdict = row["model_verdict"]
    corrected_verdict = row["corrected_verdict"]
    return VisionLabel(
        label_id=row["label_id"],
        capture_id=row["capture_id"],
        label_kind=LabelKind(row["label_kind"]),
        created_at=row["created_at"],
        author=row["author"],
        model_verdict=(
            ComparisonVerdict(model_verdict) if model_verdict is not None else None
        ),
        model_anomaly_score=row["model_anomaly_score"],
        model_id=row["model_id"],
        model_version=row["model_version"],
        scoring_policy_version=row["scoring_policy_version"],
        corrected_verdict=(
            ComparisonVerdict(corrected_verdict)
            if corrected_verdict is not None
            else None
        ),
        symptom_labels=tuple(json.loads(row["symptom_labels"] or "[]")),
        note=row["note"],
        observed_from=row["observed_from"],
        observed_to=row["observed_to"],
        excluded=bool(row["excluded"]),
        exclusion_reason=row["exclusion_reason"],
        superseded_by=row["superseded_by"],
    )
