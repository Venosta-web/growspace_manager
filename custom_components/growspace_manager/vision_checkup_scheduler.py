"""Schedule and execute evidence-based Vision Checkups."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from dataclasses import dataclass, replace
from datetime import datetime, time, timedelta
import logging
import struct
from typing import TYPE_CHECKING, Any, cast
import uuid

from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util.dt import now as ha_now, utcnow

from .const import CONF_AI_TASK_ENTITY_ID, CONF_VISION_EXPLAINER_SEES_IMAGE
from .data_access.vision_evidence_store import VisionEvidenceStore
from .domain.capture_continuity import (
    CaptureContinuityEvent,
    ContinuityTransition,
    evaluate_capture_continuity,
)
from .domain.environmental_evidence import (
    NormalizedEnvironmentalEvidence,
    environmental_evidence_at,
)
from .domain.evidence_fusion import (
    AvailableFusionOutcome,
    EvidenceFusionState,
    FusionOutcome,
    UnavailableFusionOutcome,
    VisualEvidence as FusionVisualEvidence,
    VisualPersistenceEvent,
    VisualPersistenceKey,
    evaluate_visual_persistence,
    fuse_evidence,
)
from .domain.light_schedule import resolve_photoperiod_hours
from .domain.vision_explainer_prompt import (
    VISION_EXPLANATION_SCHEMA,
    VISION_OBSERVATION_SCHEMA,
    EnvironmentalEvidence as ExplainerEnvironmentalEvidence,
    ExplanationPassInput,
    FusionSummary,
    ObservationPassInput,
    TrendEntry,
    VisualEvidence as ExplainerVisualEvidence,
    build_explanation_prompt,
    build_observation_prompt,
    observation_from_visual_comparison,
)
from .domain.vision_quality import QualitySignals as RelativeQualitySignals
from .domain.visual_comparison import (
    BaselineEntry,
    BaselineKey,
    BaselineSnapshot,
    ComparisonDecision,
    VisualComparisonEngine,
    VisualEmbeddingCapture,
)
from .image_processor import GrowspaceImageProcessor
from .models.vision_evidence import (
    AdmissionPhase,
    AnalysisState,
    BaselineBucket,
    BaselineMember,
    CaptureFileVariant,
    CaptureTrigger,
    CheckupStatus,
    ComparisonOutcome,
    ComparisonVerdict,
    EmbeddingSource,
    LightState,
    LightWindow,
    ObservationSource,
    VisionCapture,
    VisionCheckup,
    VisionEmbedding,
    VisionExplainerReport,
    VisionFusionOutcome,
    VisualComparisonResult,
)
from .vision_connection import VisionAvailability

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, HomeAssistant

    from .coordinator import GrowspaceCoordinator
    from .models import Growspace
    from .vision_client import GrowspaceVisionClient, VisionSession

_LOGGER = logging.getLogger(__name__)
SCORING_POLICY_VERSION = 1


@dataclass(frozen=True, slots=True)
class VisionCaptureOutcome:
    """The evidence produced for one camera in a Vision Checkup."""

    capture: VisionCapture
    comparison: VisualComparisonResult | None
    fusion: VisionFusionOutcome
    report: VisionExplainerReport | None
    media_content_id: str


@dataclass(frozen=True, slots=True)
class VisionCheckupOutcome:
    """One completed operational checkup and its capture-specific evidence."""

    checkup: VisionCheckup
    captures: tuple[VisionCaptureOutcome, ...]


def calculate_checkup_times(
    lights_on_time: time,
    day_hours: int,
    early_offset_minutes: int = 60,
    mid_check_hours: int = 6,
    late_offset_minutes: int = 60,
) -> dict[str, time]:
    """Calculate the three checkup times within a light cycle."""
    reference = datetime(2000, 1, 1, lights_on_time.hour, lights_on_time.minute)
    return {
        "early": (reference + timedelta(minutes=early_offset_minutes)).time(),
        "mid": (reference + timedelta(hours=mid_check_hours)).time(),
        "late": (
            reference
            + timedelta(hours=day_hours)
            - timedelta(minutes=late_offset_minutes)
        ).time(),
    }


class VisionCheckupScheduler:
    """Own timing and orchestrate one local Vision Analysis per camera."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
        *,
        evidence_store: VisionEvidenceStore | None = None,
    ) -> None:
        """Bind scheduling to the local service and durable evidence store."""
        self.hass = hass
        self.coordinator = coordinator
        self._store = evidence_store
        self._unsub_timers: dict[str, list[CALLBACK_TYPE]] = {}
        self._comparison_engine = VisualComparisonEngine()

    def _get_ai_task_entity_id(self) -> str | None:
        settings = self.coordinator.options.get("ai_settings", {})
        return cast("str | None", settings.get(CONF_AI_TASK_ENTITY_ID))

    def _get_active_day_hours(self, growspace: Growspace) -> int:
        plants = self.coordinator.services.growspaces.get_growspace_plants(growspace.id)
        environment = growspace.environment_config
        return int(
            resolve_photoperiod_hours(
                plants,
                environment.veg_day_hours,
                environment.flower_day_hours,
                ha_now().date(),
            )
        )

    def _get_lights_on_time(self, growspace: Growspace) -> time:
        raw = growspace.irrigation_strategy.lights_on_time
        try:
            return datetime.strptime(raw, "%H:%M:%S").time()
        except ValueError:
            return datetime.strptime(raw, "%H:%M").time()

    def _cancel_growspace_timers(self, growspace_id: str) -> None:
        for unsubscribe in self._unsub_timers.pop(growspace_id, []):
            unsubscribe()

    def async_stop(self) -> None:
        """Cancel every scheduled Vision Checkup timer."""
        for growspace_id in list(self._unsub_timers):
            self._cancel_growspace_timers(growspace_id)

    def schedule_growspace(self, growspace_id: str) -> None:
        """Register the next early, mid and late checkup for one growspace."""
        self._cancel_growspace_timers(growspace_id)
        growspace = self.coordinator.growspaces.get(growspace_id)
        if growspace is None:
            return
        config = growspace.environment_config.vision_checkup_config
        if not config.enabled or not growspace.environment_config.camera_entities:
            return
        checkup_times = calculate_checkup_times(
            self._get_lights_on_time(growspace),
            self._get_active_day_hours(growspace),
            config.early_check_offset_minutes,
            config.mid_check_hours,
            config.late_check_offset_minutes,
        )
        current = ha_now()
        subscriptions: list[CALLBACK_TYPE] = []
        for check_type, check_time in checkup_times.items():
            next_run = current.replace(
                hour=check_time.hour,
                minute=check_time.minute,
                second=0,
                microsecond=0,
            )
            if next_run <= current:
                next_run += timedelta(days=1)
            subscriptions.append(
                async_track_point_in_utc_time(
                    self.hass,
                    self._create_checkup_callback(growspace_id, check_type),
                    next_run,
                )
            )
        self._unsub_timers[growspace_id] = subscriptions

    def schedule_all_growspaces(self) -> None:
        """Schedule every configured growspace."""
        for growspace_id in self.coordinator.growspaces:
            self.schedule_growspace(growspace_id)

    def _create_checkup_callback(
        self, growspace_id: str, check_type: str
    ) -> Callable[[datetime], Coroutine[Any, Any, None]]:
        async def _callback(_now: datetime) -> None:
            try:
                status = (
                    await self.coordinator.vision_connection.async_refresh_if_stale()
                )
                if status.availability is not VisionAvailability.READY:
                    _LOGGER.info(
                        "Skipping scheduled Vision Checkup for %s: %s",
                        growspace_id,
                        status.reason,
                    )
                    return
                await self.run_vision_analysis(growspace_id, check_type)
            except Exception:
                _LOGGER.exception(
                    "Scheduled %s Vision Checkup failed for %s",
                    check_type,
                    growspace_id,
                )
            finally:
                self.schedule_growspace(growspace_id)

        return _callback

    async def run_vision_analysis(
        self, growspace_id: str, check_type: str
    ) -> VisionCheckupOutcome:
        """Run one evidence-based Vision Checkup through its public action seam."""
        growspace = self.coordinator.growspaces.get(growspace_id)
        if growspace is None:
            raise ServiceValidationError(f"Growspace '{growspace_id}' not found")
        cameras = growspace.environment_config.camera_entities
        if not cameras:
            raise ServiceValidationError(
                "No cameras configured for this growspace. Please add cameras in the environment settings."
            )
        if self._store is None:
            raise ServiceValidationError("The Vision Evidence Store is unavailable")

        status = await self.coordinator.vision_connection.async_refresh_if_stale()
        session = self.coordinator.vision_connection.negotiated
        if status.availability is not VisionAvailability.READY or session is None:
            reason = status.reason.value if status.reason is not None else "unavailable"
            raise ServiceValidationError(f"Growspace Vision is not ready: {reason}")
        endpoint = await self.coordinator.vision_connection.async_resolve_endpoint()
        client = self.coordinator.vision_connection.build_client(endpoint)

        light_window = LightWindow(check_type)
        trigger = (
            CaptureTrigger.MANUAL
            if light_window is LightWindow.MANUAL
            else CaptureTrigger.SCHEDULED
        )
        started_at = utcnow()
        checkup_id = self._store.mint_checkup_id()
        await self._store.async_start_checkup(
            checkup_id=checkup_id,
            growspace_id=growspace_id,
            growspace_name=growspace.name,
            trigger_source=trigger,
            light_window=light_window,
            started_at=started_at,
        )
        outcomes: list[VisionCaptureOutcome] = []
        failures = 0
        for camera_id in cameras:
            try:
                outcome = await self._run_capture(
                    checkup_id=checkup_id,
                    growspace=growspace,
                    camera_id=camera_id,
                    captured_at=utcnow(),
                    light_window=light_window,
                    trigger=trigger,
                    client=client,
                    session=session,
                )
            except Exception:
                failures += 1
                _LOGGER.exception(
                    "Vision capture failed for %s/%s", growspace_id, camera_id
                )
            else:
                outcomes.append(outcome)
                if outcome.capture.analysis_state is AnalysisState.FAILED:
                    failures += 1
        successes = len(cameras) - failures
        if failures == 0:
            checkup_status = CheckupStatus.COMPLETED
        elif successes > 0:
            checkup_status = CheckupStatus.PARTIAL
        else:
            checkup_status = CheckupStatus.FAILED
        checkup = await self._store.async_finish_checkup(
            checkup_id, status=checkup_status, completed_at=utcnow()
        )
        return VisionCheckupOutcome(checkup=checkup, captures=tuple(outcomes))

    async def _run_capture(
        self,
        *,
        checkup_id: str,
        growspace: Growspace,
        camera_id: str,
        captured_at: datetime,
        light_window: LightWindow,
        trigger: CaptureTrigger,
        client: GrowspaceVisionClient,
        session: VisionSession,
    ) -> VisionCaptureOutcome:
        from homeassistant.components.camera import async_get_image  # noqa: PLC0415

        assert self._store is not None
        image = await async_get_image(self.hass, camera_id)
        content_type = (getattr(image, "content_type", None) or "").partition(";")[0]
        capture = await self._store.async_start_capture(
            capture_id=self._store.mint_capture_id(),
            checkup_id=checkup_id,
            growspace_id=growspace.id,
            growspace_name=growspace.name,
            camera_id=camera_id,
            captured_at=captured_at,
            light_window=light_window,
            light_state=(
                LightState.UNKNOWN
                if trigger is CaptureTrigger.MANUAL
                else LightState.ON
            ),
            trigger_source=trigger,
            image=image.content,
            content_type=content_type,
        )
        media_content_id, has_grid = await self._processed_image(capture, image.content)
        try:
            analysis = await client.async_analyze(
                session=session,
                image=image.content,
                content_type=content_type,
                camera_id=camera_id,
                growspace_id=growspace.id,
                captured_at=captured_at,
                light_state=capture.light_state,
            )
            capture, comparison = await self._record_analysis(capture, analysis)
        except Exception as error:  # noqa: BLE001 - failure is persisted as evidence
            failed = replace(
                capture,
                analysis_state=AnalysisState.FAILED,
                analysis_error_code=type(error).__name__.lower(),
                vision_schema_version=session.schema_version,
                service_version=session.service_version,
            )
            await self._store.async_record_analysis(failed)
            return await self._finish_capture(
                failed,
                comparison=None,
                media_content_id=media_content_id,
                has_grid=has_grid,
            )
        return await self._finish_capture(
            capture,
            comparison=comparison,
            media_content_id=media_content_id,
            has_grid=has_grid,
        )

    async def _record_analysis(
        self, capture: VisionCapture, analysis: Any
    ) -> tuple[VisionCapture, VisualComparisonResult | None]:
        assert self._store is not None
        signals = analysis.quality.signals
        history = await self._store.async_get_quality_history(capture.camera_id)
        quality = history.evaluate(
            RelativeQualitySignals(
                mean_luminance=signals.mean_luminance,
                clipped_pixel_fraction=signals.clipped_pixel_fraction,
                mean_absolute_gradient=signals.mean_absolute_gradient,
            ),
            service_accepted=analysis.accepted,
            service_reasons=tuple(reason.value for reason in analysis.quality.reasons),
        )
        negotiated = self.coordinator.vision_connection.negotiated
        if negotiated is None:
            raise RuntimeError("Vision negotiation disappeared during a capture")
        completed = replace(
            capture,
            analysis_state=(
                AnalysisState.ANALYZED if quality.accepted else AnalysisState.REJECTED
            ),
            request_id=analysis.request_id,
            vision_schema_version=analysis.schema_version,
            service_version=negotiated.service_version,
            quality_mean_luminance=signals.mean_luminance,
            quality_clipped_pixel_fraction=signals.clipped_pixel_fraction,
            quality_mean_absolute_gradient=signals.mean_absolute_gradient,
            quality_reasons=quality.reasons,
            quality_history_reanchored=quality.reanchored,
        )
        if not quality.accepted:
            await self._store.async_record_analysis(completed)
            return completed, None
        assert analysis.model is not None and analysis.embedding is not None
        embedding = VisionEmbedding(
            capture_id=capture.capture_id,
            model_id=analysis.model.model_id,
            model_version=analysis.model.model_version,
            dimension=analysis.embedding.dimension,
            values_f32=_pack_f32(analysis.embedding.values),
            derived_at=capture.captured_at,
            source=EmbeddingSource.LIVE,
        )
        comparison, decision = await self._compare(completed, embedding)
        bucket, member = self._persistence_records(completed, decision)
        await self._store.async_record_analysis(
            completed,
            embedding=embedding,
            comparison=comparison,
            bucket=bucket,
            member=member,
            evict_capture_id=decision.evicted_capture_id,
        )
        return completed, comparison

    async def _compare(
        self, capture: VisionCapture, embedding: VisionEmbedding
    ) -> tuple[VisualComparisonResult, ComparisonDecision]:
        assert self._store is not None
        key = BaselineKey(
            growspace_id=capture.growspace_id,
            camera_id=capture.camera_id,
            light_window=capture.light_window,
            grow_run_id=capture.grow_run_id,
            model_id=embedding.model_id,
            model_version=embedding.model_version,
            framing_epoch_id=capture.framing_epoch_id,
            scoring_policy_version=SCORING_POLICY_VERSION,
        )
        stored = await self._store.async_find_baseline_bucket(
            camera_id=key.camera_id,
            light_window=key.light_window,
            grow_run_id=key.grow_run_id,
            model_id=key.model_id,
            model_version=key.model_version,
            framing_epoch_id=key.framing_epoch_id,
            scoring_policy_version=key.scoring_policy_version,
        )
        baseline = await self._baseline_snapshot(stored, key)
        decision = self._comparison_engine.evaluate(
            key,
            VisualEmbeddingCapture(
                capture_id=capture.capture_id,
                captured_at=datetime.fromisoformat(capture.captured_at),
                values=_unpack_f32(embedding.values_f32),
                trigger_source=capture.trigger_source,
                quality_accepted=True,
            ),
            baseline,
        )
        value = decision.comparison
        if value is None:  # pragma: no cover
            raise RuntimeError("Accepted capture produced no comparison")
        return VisualComparisonResult(
            result_id=str(uuid.uuid7()),
            capture_id=capture.capture_id,
            bucket_id=(decision.baseline.bucket_id if decision.baseline else None),
            evaluated_at=capture.captured_at,
            outcome=value.outcome,
            baseline_state=value.baseline_state,
            samples_collected=value.samples_collected,
            samples_required=value.samples_required,
            raw_distance=value.raw_distance,
            anomaly_score=value.anomaly_score,
            verdict=value.verdict,
            comparison_confidence=value.comparison_confidence,
            admitted_to_baseline=decision.admitted,
            trigger_source=capture.trigger_source,
            model_id=embedding.model_id,
            model_version=embedding.model_version,
            scoring_policy_version=SCORING_POLICY_VERSION,
        ), decision

    async def _baseline_snapshot(
        self, bucket: BaselineBucket | None, key: BaselineKey
    ) -> BaselineSnapshot | None:
        if bucket is None:
            return None
        assert self._store is not None
        entries: list[BaselineEntry] = []
        for member in await self._store.async_get_active_baseline_members(
            bucket.bucket_id
        ):
            embedding = await self._store.async_get_embedding(
                member.capture_id, bucket.model_id, bucket.model_version
            )
            if embedding is None:
                raise RuntimeError("Baseline member has no matching embedding")
            entries.append(
                BaselineEntry(
                    capture_id=member.capture_id,
                    admitted_at=datetime.fromisoformat(member.admitted_at),
                    values=_unpack_f32(embedding.values_f32),
                )
            )
        return BaselineSnapshot(
            bucket_id=bucket.bucket_id,
            key=key,
            created_at=datetime.fromisoformat(bucket.created_at),
            state=bucket.state,
            members=tuple(entries),
            centroid=_unpack_f32(bucket.centroid),
            calibration_distances=_unpack_f32(bucket.calibration_distances),
            last_admitted_at=(
                datetime.fromisoformat(bucket.last_admitted_at)
                if bucket.last_admitted_at
                else None
            ),
        )

    def _persistence_records(
        self, capture: VisionCapture, decision: ComparisonDecision
    ) -> tuple[BaselineBucket | None, BaselineMember | None]:
        baseline = decision.baseline
        if baseline is None:
            return None, None
        bucket = BaselineBucket(
            bucket_id=baseline.bucket_id,
            growspace_id=baseline.key.growspace_id,
            camera_id=baseline.key.camera_id,
            light_window=baseline.key.light_window,
            grow_run_id=baseline.key.grow_run_id,
            model_id=baseline.key.model_id,
            model_version=baseline.key.model_version,
            framing_epoch_id=baseline.key.framing_epoch_id,
            state=baseline.state,
            member_count=len(baseline.members),
            members_required=30,
            centroid=_pack_f32(baseline.centroid) if baseline.centroid else None,
            calibration_distances=(
                _pack_f32(baseline.calibration_distances)
                if baseline.calibration_distances
                else None
            ),
            last_admitted_at=(
                baseline.last_admitted_at.isoformat()
                if baseline.last_admitted_at
                else None
            ),
            recomputed_at=capture.captured_at,
            scoring_policy_version=baseline.key.scoring_policy_version,
            created_at=baseline.created_at.isoformat(),
        )
        if not decision.admitted:
            return bucket, None
        comparison = decision.comparison
        phase = (
            AdmissionPhase.BOOTSTRAP
            if comparison is not None
            and comparison.outcome is ComparisonOutcome.MONITORING
            else AdmissionPhase.NORMAL
        )
        return bucket, BaselineMember(
            bucket_id=baseline.bucket_id,
            capture_id=capture.capture_id,
            admitted_at=capture.captured_at,
            admission_phase=phase,
        )

    async def _finish_capture(
        self,
        capture: VisionCapture,
        *,
        comparison: VisualComparisonResult | None,
        media_content_id: str,
        has_grid: bool,
    ) -> VisionCaptureOutcome:
        assert self._store is not None
        captured_at = datetime.fromisoformat(capture.captured_at)
        environment = self._environmental_evidence(capture.growspace_id, captured_at)
        persistence_met = await self._visual_persistence_met(capture)
        fused = fuse_evidence(
            environment.fusion_input(),
            _fusion_visual(capture, comparison),
            persistence_met=persistence_met,
        )
        fusion = _fusion_record(capture, environment, fused)
        await self._store.async_record_fusion_outcome(fusion)
        await self._update_continuity(capture, comparison)
        report = await self._maybe_explain(
            capture,
            comparison=comparison,
            environment=environment,
            fusion=fused,
            media_content_id=media_content_id,
            has_grid=has_grid,
        )
        return VisionCaptureOutcome(
            capture=capture,
            comparison=comparison,
            fusion=fusion,
            report=report,
            media_content_id=media_content_id,
        )

    def _environmental_evidence(
        self, growspace_id: str, captured_at: datetime
    ) -> NormalizedEnvironmentalEvidence:
        notifications = self.coordinator.services.notifications
        return environmental_evidence_at(
            captured_at,
            stress=notifications.latest_evaluation(growspace_id, "stress"),
            mold=notifications.latest_evaluation(growspace_id, "mold"),
        )

    async def _visual_persistence_met(self, capture: VisionCapture) -> bool:
        """Replay the two scheduled evidence rows that can establish persistence."""
        if capture.trigger_source is CaptureTrigger.MANUAL:
            return False
        assert self._store is not None
        state = None
        decision = None
        for historical in await self._store.async_get_recent_scheduled_captures(
            capture.camera_id, limit=2
        ):
            comparison = await self._latest_comparison(historical.capture_id)
            event = VisualPersistenceEvent(
                key=VisualPersistenceKey(
                    camera_id=historical.camera_id,
                    grow_run_id=historical.grow_run_id,
                    model_id=comparison.model_id if comparison else "unavailable",
                    model_version=(
                        comparison.model_version if comparison else "unavailable"
                    ),
                    framing_epoch_id=historical.framing_epoch_id,
                ),
                capture_id=historical.capture_id,
                captured_at=datetime.fromisoformat(historical.captured_at),
                trigger_source=historical.trigger_source,
                verdict=comparison.verdict if comparison else None,
                comparison_confidence=(
                    comparison.comparison_confidence if comparison else None
                ),
                baseline_state=comparison.baseline_state if comparison else None,
            )
            decision = evaluate_visual_persistence(state, event)
            state = decision.state
        return bool(decision and decision.persistence_met)

    async def _update_continuity(
        self,
        capture: VisionCapture,
        comparison: VisualComparisonResult | None,
    ) -> None:
        quality_accepted: bool | None
        if capture.analysis_state is AnalysisState.ANALYZED:
            quality_accepted = True
        elif capture.analysis_state is AnalysisState.REJECTED:
            quality_accepted = False
        else:
            quality_accepted = None
        if capture.trigger_source is CaptureTrigger.MANUAL or quality_accepted is None:
            return
        if quality_accepted and (
            comparison is None
            or comparison.verdict is not ComparisonVerdict.MATERIAL_SCENE_CHANGE
        ):
            await self.coordinator.alert_monitor.async_clear_capture_continuity_break(
                capture.camera_id,
                cleared_at=datetime.fromisoformat(capture.captured_at),
            )
            return
        assert self._store is not None
        state = None
        decision = None
        for historical in await self._store.async_get_recent_scheduled_captures(
            capture.camera_id, limit=3
        ):
            historical_comparison = await self._latest_comparison(historical.capture_id)
            decision = evaluate_capture_continuity(
                state,
                CaptureContinuityEvent(
                    growspace_id=historical.growspace_id,
                    camera_id=historical.camera_id,
                    capture_id=historical.capture_id,
                    captured_at=datetime.fromisoformat(historical.captured_at),
                    trigger_source=historical.trigger_source,
                    quality_accepted=(
                        historical.analysis_state is AnalysisState.ANALYZED
                    ),
                    comparison_verdict=(
                        historical_comparison.verdict if historical_comparison else None
                    ),
                ),
            )
            state = decision.state
        if decision is None:
            return
        if decision.transition is ContinuityTransition.ACTIVATED:
            assert decision.state is not None
            await self.coordinator.alert_monitor.async_record_capture_continuity_break(
                decision.state
            )

    async def _latest_comparison(
        self, capture_id: str
    ) -> VisualComparisonResult | None:
        assert self._store is not None
        comparisons = await self._store.async_get_comparison_results(capture_id)
        return comparisons[-1] if comparisons else None

    async def _processed_image(
        self, capture: VisionCapture, image: bytes
    ) -> tuple[str, bool]:
        assert self._store is not None
        raw_file = (await self._store.async_get_capture_files(capture.capture_id))[0]
        media_id = self._media_content_id(raw_file.relative_path)
        try:
            processed, _coverage = await self.hass.async_add_executor_job(
                GrowspaceImageProcessor().process_snapshot, image
            )
            processed_file = await self._store.async_add_capture_file(
                capture.capture_id,
                variant=CaptureFileVariant.PROCESSED,
                image=processed,
                content_type="image/jpeg",
            )
        except Exception:  # noqa: BLE001 - overlay failure leaves the raw evidence
            _LOGGER.debug("Could not produce grid overlay for %s", capture.capture_id)
            return media_id, False
        return self._media_content_id(processed_file.relative_path), True

    def _media_content_id(self, relative_path: str) -> str:
        media_dirs = self.hass.config.media_dirs
        source = "local" if "local" in media_dirs else next(iter(media_dirs))
        return f"media-source://media_source/{source}/growspace_vision/{relative_path}"

    async def _maybe_explain(
        self,
        capture: VisionCapture,
        *,
        comparison: VisualComparisonResult | None,
        environment: NormalizedEnvironmentalEvidence,
        fusion: FusionOutcome,
        media_content_id: str,
        has_grid: bool,
    ) -> VisionExplainerReport | None:
        entity_id = self._get_ai_task_entity_id()
        if entity_id is None:
            return None
        from homeassistant.components import ai_task  # noqa: PLC0415

        visual = _explainer_visual(capture, comparison)
        settings = self.coordinator.options.get("ai_settings", {})
        observation_source = ObservationSource.VISUAL_COMPARISON_ONLY
        observation = observation_from_visual_comparison(visual)
        if settings.get(CONF_VISION_EXPLAINER_SEES_IMAGE, True):
            try:
                observed = await ai_task.async_generate_data(
                    self.hass,
                    task_name="growspace_vision_observation",
                    entity_id=entity_id,
                    instructions=build_observation_prompt(
                        ObservationPassInput(
                            light_window=capture.light_window,
                            photograph_count=1,
                            grid_overlay=has_grid,
                        )
                    ),
                    structure=VISION_OBSERVATION_SCHEMA,
                    attachments=[{"media_content_id": media_content_id}],
                )
                observation = (observed.data or {})["observation"]
                observation_source = ObservationSource.IMAGE_PASS
            except Exception:  # noqa: BLE001 - documented comparison-only fallback
                _LOGGER.warning(
                    "Visual Observation Pass failed for %s; using comparison text",
                    capture.capture_id,
                )
        explanation_input = ExplanationPassInput(
            observation=observation,
            observation_source=observation_source,
            fusion=_explainer_fusion(fusion),
            environment=ExplainerEnvironmentalEvidence(
                verdict=environment.verdict,
                stress_reasons=environment.stress_reasons,
                mold_reasons=environment.mold_reasons,
            ),
            visual=visual,
            trend=await self._trend(capture, comparison),
        )
        try:
            explained = await ai_task.async_generate_data(
                self.hass,
                task_name="growspace_vision_evidence_explanation",
                entity_id=entity_id,
                instructions=build_explanation_prompt(explanation_input),
                structure=VISION_EXPLANATION_SCHEMA,
                attachments=[],
            )
            data = explained.data or {}
            report = VisionExplainerReport(
                report_id=str(uuid.uuid7()),
                capture_id=capture.capture_id,
                created_at=utcnow().isoformat(),
                ai_task_entity_id=entity_id,
                observation_source=observation_source,
                scoring_policy_version=SCORING_POLICY_VERSION,
                observation=observation,
                environmental_risk=data["environmental_risk"],
                hypothesis=data["hypothesis"],
                recommendations=tuple(data["recommendations"]),
                fusion_state=(
                    fusion.state.value
                    if isinstance(fusion, AvailableFusionOutcome)
                    else None
                ),
                fusion_confidence=(
                    fusion.confidence.value
                    if isinstance(fusion, AvailableFusionOutcome)
                    else None
                ),
                fusion_coverage=(
                    fusion.coverage.value
                    if isinstance(fusion, AvailableFusionOutcome)
                    else None
                ),
                fusion_unavailable_reasons=(
                    fusion.unavailable_reasons
                    if isinstance(fusion, UnavailableFusionOutcome)
                    else ()
                ),
            )
            assert self._store is not None
            await self._store.async_add_explainer_report(report)
        except Exception:  # noqa: BLE001 - an absent report is valid degradation
            _LOGGER.warning(
                "Evidence Explanation Pass failed for %s", capture.capture_id
            )
            return None
        else:
            return report

    async def _trend(
        self,
        capture: VisionCapture,
        comparison: VisualComparisonResult | None,
    ) -> tuple[TrendEntry, ...]:
        """Return up to seven earlier scored measurements with no narratives."""
        if comparison is None:
            return ()
        assert self._store is not None
        rows = await self._store.async_get_comparison_trend(
            capture_id=capture.capture_id,
            camera_id=capture.camera_id,
            grow_run_id=capture.grow_run_id,
            framing_epoch_id=capture.framing_epoch_id,
            model_id=comparison.model_id,
            model_version=comparison.model_version,
            scoring_policy_version=comparison.scoring_policy_version,
            before_evaluated_at=comparison.evaluated_at,
        )
        return tuple(
            TrendEntry(
                evaluated_at=item.evaluated_at,
                anomaly_score=item.anomaly_score,
                verdict=item.verdict,
                fusion_state=(EvidenceFusionState(state) if state else None),
            )
            for item, state in rows
        )


def _fusion_visual(
    capture: VisionCapture, comparison: VisualComparisonResult | None
) -> FusionVisualEvidence:
    if capture.analysis_state is AnalysisState.REJECTED:
        return FusionVisualEvidence(unavailable_reasons=("frame_rejected",))
    if capture.analysis_state is AnalysisState.FAILED:
        return FusionVisualEvidence(unavailable_reasons=("vision_unavailable",))
    if comparison is None:
        return FusionVisualEvidence(unavailable_reasons=("vision_unavailable",))
    if comparison.outcome is ComparisonOutcome.SCORED:
        return FusionVisualEvidence(
            verdict=comparison.verdict,
            comparison_confidence=comparison.comparison_confidence,
        )
    reason = (
        "baseline_stale"
        if comparison.baseline_state is not None
        and comparison.baseline_state.value == "stale"
        else "baseline_monitoring"
    )
    return FusionVisualEvidence(unavailable_reasons=(reason,))


def _fusion_record(
    capture: VisionCapture,
    environment: NormalizedEnvironmentalEvidence,
    fusion: FusionOutcome,
) -> VisionFusionOutcome:
    available = fusion if isinstance(fusion, AvailableFusionOutcome) else None
    return VisionFusionOutcome(
        outcome_id=str(uuid.uuid7()),
        capture_id=capture.capture_id,
        evaluated_at=capture.captured_at,
        scoring_policy_version=SCORING_POLICY_VERSION,
        environmental_verdict=environment.verdict.value,
        environmental_evaluated_at=(
            environment.evaluated_at.isoformat() if environment.evaluated_at else None
        ),
        stress_reasons=environment.stress_reasons,
        mold_reasons=environment.mold_reasons,
        fusion_state=available.state.value if available else None,
        fusion_confidence=available.confidence.value if available else None,
        fusion_coverage=available.coverage.value if available else None,
        unavailable_reasons=(
            fusion.unavailable_reasons
            if isinstance(fusion, UnavailableFusionOutcome)
            else ()
        ),
    )


def _explainer_visual(
    capture: VisionCapture, comparison: VisualComparisonResult | None
) -> ExplainerVisualEvidence:
    if comparison is None:
        reason = (
            "frame_rejected"
            if capture.analysis_state is AnalysisState.REJECTED
            else "vision_unavailable"
        )
        return ExplainerVisualEvidence(
            outcome=ComparisonOutcome.UNAVAILABLE,
            unavailable_reasons=(reason,),
        )
    return ExplainerVisualEvidence(
        outcome=comparison.outcome,
        verdict=comparison.verdict,
        anomaly_score=comparison.anomaly_score,
        comparison_confidence=comparison.comparison_confidence,
        baseline_state=comparison.baseline_state,
        samples_collected=comparison.samples_collected,
        samples_required=comparison.samples_required,
        unavailable_reasons=comparison.unavailable_reasons,
    )


def _explainer_fusion(fusion: FusionOutcome) -> FusionSummary:
    if isinstance(fusion, AvailableFusionOutcome):
        return FusionSummary(
            state=fusion.state,
            confidence=fusion.confidence,
            coverage=fusion.coverage,
        )
    return FusionSummary(unavailable_reasons=fusion.unavailable_reasons)


def _pack_f32(values: tuple[float, ...]) -> bytes:
    return struct.pack(f"<{len(values)}f", *values)


def _unpack_f32(values: bytes | None) -> tuple[float, ...]:
    if not values:
        return ()
    return tuple(item[0] for item in struct.iter_unpack("<f", values))
