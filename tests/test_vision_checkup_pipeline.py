"""Public-boundary tests for the V1 Vision Checkup pipeline."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.alert_monitor import AlertMonitor
from custom_components.growspace_manager.capture_continuity_monitor import (
    CaptureContinuityMonitor,
)
from custom_components.growspace_manager.data_access.vision_evidence_store import (
    VisionEvidenceStore,
)
from custom_components.growspace_manager.domain.evidence_fusion import (
    AvailableFusionOutcome,
    ConfidenceQualifier,
    EvidenceCoverage,
    EvidenceFusionState,
)
from custom_components.growspace_manager.domain.visual_comparison import BASELINE_SIZE
from custom_components.growspace_manager.models.vision_evidence import (
    AnalysisState,
    CheckupStatus,
    ComparisonOutcome,
    ComparisonVerdict,
    ObservationSource,
)
from custom_components.growspace_manager.notifications.evaluation_snapshot import (
    EvaluationSnapshot,
)
from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
    _explainer_fusion,
    _fusion_visual,
    _unpack_f32,
)
from custom_components.growspace_manager.vision_client import VisionSession
from custom_components.growspace_manager.vision_connection import (
    VisionAvailability,
    VisionConnectionSource,
    VisionEndpoint,
    VisionModelSummary,
    VisionStatus,
)
from custom_components.growspace_manager.vision_models import (
    AnalysisStatus,
    FrameQualityResult,
    ModelIdentity,
    QualityReason,
    QualitySignals,
    VisionAnalysis,
)

NOW = datetime(2026, 9, 1, 12, tzinfo=UTC)
REJECTED_ANALYSIS = VisionAnalysis(
    schema_version=1,
    request_id="request-rejected",
    status=AnalysisStatus.REJECTED,
    quality=FrameQualityResult(
        signals=QualitySignals(
            mean_luminance=1.0,
            clipped_pixel_fraction=0.0,
            mean_absolute_gradient=1.0,
        ),
        reasons=(QualityReason.TOO_DARK,),
    ),
)


class _MemoryStore:
    """Stand-in for a Home Assistant Store that keeps one payload in memory."""

    def __init__(self) -> None:
        self.data: dict | None = None

    async def async_load(self) -> dict | None:
        return self.data

    async def async_save(self, data: dict) -> None:
        self.data = data


def _evaluation(sensor_type: str) -> EvaluationSnapshot:
    return EvaluationSnapshot(
        growspace_id="tent1",
        sensor_type=sensor_type,
        sensor_name=sensor_type,
        probability=0.1,
        threshold=0.7,
        is_on=False,
        reasons=[],
        sensor_states={},
        lights_on=True,
        notification_title=None,
        notification_message=None,
        evaluated_at=NOW,
        has_observations=True,
    )


@asynccontextmanager
async def _pipeline(tmp_path, *, ai_settings: dict | None = None):
    store = VisionEvidenceStore(tmp_path / "vision.db", tmp_path / "images")
    await store.async_setup()
    try:
        image = SimpleNamespace(content=b"jpeg bytes", content_type="image/jpeg")
        model = ModelIdentity(model_id="dinov2-small", model_version="1.0.0")
        session = VisionSession(
            schema_version=1,
            service_version="1.0.0",
            model=model,
            embedding_dimension=2,
        )
        analyzed = VisionAnalysis(
            schema_version=1,
            request_id="request-1",
            status=AnalysisStatus.ANALYZED,
            quality=FrameQualityResult(
                signals=QualitySignals(
                    mean_luminance=100.0,
                    clipped_pixel_fraction=0.01,
                    mean_absolute_gradient=10.0,
                ),
                reasons=(),
            ),
            model=model,
            embedding=SimpleNamespace(dimension=2, values=(1.0, 0.0)),
        )
        client = SimpleNamespace(async_analyze=AsyncMock(return_value=analyzed))
        ready = VisionStatus(
            availability=VisionAvailability.READY,
            connection_source=VisionConnectionSource.MANUAL,
            service_version="1.0.0",
            vision_schema_version=1,
            model=VisionModelSummary(id="dinov2-small", version="1.0.0", dimension=2),
        )
        connection = SimpleNamespace(
            negotiated=session,
            async_refresh_if_stale=AsyncMock(return_value=ready),
            async_resolve_endpoint=AsyncMock(
                return_value=VisionEndpoint(
                    base_url="http://vision.local:8099",
                    token="secret",
                    source=VisionConnectionSource.MANUAL,
                )
            ),
            build_client=MagicMock(return_value=client),
        )
        growspace = SimpleNamespace(
            id="tent1",
            name="Test Tent",
            vision_checkup_history=[],
            environment_config=SimpleNamespace(
                camera_entities=["camera.canopy"],
                vision_checkup_config=SimpleNamespace(enabled=True),
            ),
        )
        notifications = SimpleNamespace(
            latest_evaluation=lambda _growspace_id, sensor_type: _evaluation(
                sensor_type
            )
        )
        coordinator = SimpleNamespace(
            growspaces={"tent1": growspace},
            vision_connection=connection,
            options={"ai_settings": ai_settings or {}},
            services=SimpleNamespace(notifications=notifications),
            async_update_listeners=MagicMock(),
        )
        hass = MagicMock()
        hass.config.media_dirs = {"local": str(tmp_path / "media")}
        # The durable alert path is the thing under test, so the checkup runs
        # against the real Alert Monitor and the real continuity owner rather
        # than mocks that would accept any policy the scheduler invented.
        alert_monitor = AlertMonitor(
            hass,
            coordinator=coordinator,
            store=_MemoryStore(),
            ai_assistant_factory=None,
        )
        await alert_monitor.async_start()
        capture_continuity = CaptureContinuityMonitor(_MemoryStore(), alert_monitor)
        await capture_continuity.async_start()
        coordinator.alert_monitor = alert_monitor
        coordinator.capture_continuity = capture_continuity
        scheduler = VisionCheckupScheduler(hass, coordinator, evidence_store=store)
        with (
            patch(
                "homeassistant.components.camera.async_get_image",
                new_callable=AsyncMock,
                return_value=image,
            ),
            patch(
                "custom_components.growspace_manager.vision_checkup_scheduler.utcnow",
                return_value=NOW,
            ),
        ):
            yield SimpleNamespace(
                scheduler=scheduler,
                store=store,
                client=client,
                growspace=growspace,
                coordinator=coordinator,
                analyzed=analyzed,
                alert_monitor=alert_monitor,
                capture_continuity=capture_continuity,
            )
    finally:
        await store.async_close()


@pytest.mark.asyncio
async def test_local_only_checkup_persists_comparison_and_fusion(tmp_path) -> None:
    async with _pipeline(tmp_path) as pipeline:
        outcome = await pipeline.scheduler.run_vision_analysis("tent1", "manual")

        assert outcome.checkup.status is CheckupStatus.COMPLETED
        assert len(outcome.captures) == 1
        capture_outcome = outcome.captures[0]
        assert capture_outcome.capture.analysis_state is AnalysisState.ANALYZED
        assert capture_outcome.comparison is not None
        assert capture_outcome.comparison.outcome is ComparisonOutcome.MONITORING
        assert capture_outcome.fusion.unavailable_reasons == ("baseline_monitoring",)
        assert pipeline.growspace.vision_checkup_history == []
        assert pipeline.scheduler.latest_checkup("tent1")["checkup_id"] == (
            outcome.checkup.checkup_id
        )

        persisted = await pipeline.store.async_get_checkup_captures(
            outcome.checkup.checkup_id
        )
        assert [capture.analysis_state for capture in persisted] == [
            AnalysisState.ANALYZED
        ]
        pipeline.client.async_analyze.assert_awaited_once()


@pytest.mark.asyncio
async def test_latest_sensor_projection_reloads_from_durable_evidence(tmp_path) -> None:
    """The retained sensor does not depend on process-local checkup history."""
    async with _pipeline(tmp_path) as pipeline:
        outcome = await pipeline.scheduler.run_vision_analysis("tent1", "manual")
        reloaded = VisionCheckupScheduler(
            pipeline.scheduler.hass,
            pipeline.coordinator,
            evidence_store=pipeline.store,
        )

        await reloaded.async_load_latest_checkups(["tent1"])

        assert reloaded.latest_checkup("tent1")["checkup_id"] == (
            outcome.checkup.checkup_id
        )


@pytest.mark.asyncio
async def test_configured_explainer_uses_image_then_evidence_without_image(
    tmp_path,
) -> None:
    settings = {
        "ai_task_entity_id": "ai_task.growspace",
        "vision_explainer_sees_image": True,
    }
    responses = (
        SimpleNamespace(data={"observation": "Leaves are level in sectors A1-A4."}),
        SimpleNamespace(
            data={
                "environmental_risk": "Measurements are within evaluated range.",
                "hypothesis": "",
                "recommendations": [],
            }
        ),
    )
    async with _pipeline(tmp_path, ai_settings=settings) as pipeline:
        with patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            side_effect=responses,
        ) as generate:
            outcome = await pipeline.scheduler.run_vision_analysis("tent1", "manual")

        assert generate.await_count == 2
        observation_call, explanation_call = generate.await_args_list
        assert observation_call.kwargs["attachments"]
        assert "environmental" not in observation_call.kwargs["instructions"].lower()
        assert explanation_call.kwargs["attachments"] == []
        assert (
            "Leaves are level in sectors A1-A4."
            in explanation_call.kwargs["instructions"]
        )
        report = outcome.captures[0].report
        assert report is not None
        assert report.observation == "Leaves are level in sectors A1-A4."
        assert report.observation_source is ObservationSource.IMAGE_PASS

        stored = await pipeline.store.async_get_explainer_reports(
            outcome.captures[0].capture.capture_id
        )
        assert stored == [report]


@pytest.mark.asyncio
async def test_multi_camera_checkup_is_partial_when_one_camera_cannot_capture(
    tmp_path,
) -> None:
    async with _pipeline(tmp_path) as pipeline:
        pipeline.growspace.environment_config.camera_entities = [
            "camera.canopy",
            "camera.side",
        ]
        with patch(
            "homeassistant.components.camera.async_get_image",
            new_callable=AsyncMock,
            side_effect=(
                SimpleNamespace(content=b"jpeg bytes", content_type="image/jpeg"),
                RuntimeError("camera unavailable"),
            ),
        ):
            outcome = await pipeline.scheduler.run_vision_analysis("tent1", "manual")

        assert outcome.checkup.status is CheckupStatus.PARTIAL
        assert [item.capture.camera_id for item in outcome.captures] == [
            "camera.canopy"
        ]


@pytest.mark.asyncio
async def test_local_analysis_failure_is_durable_and_explainer_degrades(
    tmp_path,
) -> None:
    settings = {
        "ai_task_entity_id": "ai_task.growspace",
        "vision_explainer_sees_image": True,
    }
    async with _pipeline(tmp_path, ai_settings=settings) as pipeline:
        pipeline.client.async_analyze.side_effect = RuntimeError("vision unavailable")
        with patch(
            "homeassistant.components.ai_task.async_generate_data",
            new_callable=AsyncMock,
            side_effect=RuntimeError("explainer unavailable"),
        ) as generate:
            outcome = await pipeline.scheduler.run_vision_analysis("tent1", "manual")

        assert outcome.checkup.status is CheckupStatus.FAILED
        capture = outcome.captures[0]
        assert capture.capture.analysis_state is AnalysisState.FAILED
        assert capture.capture.analysis_error_code == "runtimeerror"
        assert capture.fusion.unavailable_reasons == ("vision_unavailable",)
        assert capture.report is None
        assert generate.await_count == 2


def _continuity_alerts(pipeline) -> list[dict]:
    return pipeline.alert_monitor.get_alerts(alert_type="capture_continuity_break")


async def _reject(pipeline, count: int = 1) -> None:
    """Run scheduled checkups whose frames the quality gate rejects."""
    pipeline.client.async_analyze.side_effect = None
    pipeline.client.async_analyze.return_value = REJECTED_ANALYSIS
    for _ in range(count):
        await pipeline.scheduler.run_vision_analysis("tent1", "early")


async def _accept(pipeline, count: int = 1) -> None:
    """Run scheduled checkups the quality gate accepts."""
    pipeline.client.async_analyze.side_effect = None
    pipeline.client.async_analyze.return_value = pipeline.analyzed
    for _ in range(count):
        await pipeline.scheduler.run_vision_analysis("tent1", "early")


@pytest.mark.asyncio
async def test_scheduled_comparable_capture_leaves_no_continuity_alert(
    tmp_path,
) -> None:
    """A camera that is behaving raises nothing and stores no streak."""
    async with _pipeline(tmp_path) as pipeline:
        await pipeline.scheduler.run_vision_analysis("tent1", "early")

        assert _continuity_alerts(pipeline) == []
        assert pipeline.capture_continuity.active_streak("tent1", "camera.canopy") is (
            None
        )


@pytest.mark.asyncio
async def test_streak_activates_once_and_later_captures_update_one_alert(
    tmp_path,
) -> None:
    """Four rejections raise one alert whose identity and streak start hold."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 4)

        alerts = _continuity_alerts(pipeline)
        assert len(alerts) == 1
        alert = alerts[0]
        assert alert["severity"] == "warning"
        assert alert["camera_id"] == "camera.canopy"
        assert alert["consecutive_count"] == 4
        assert alert["reason_counts"] == {"frame_rejected": 4}
        assert alert["condition_active"] is True
        assert alert["streak_started_at"] == int(NOW.timestamp())
        assert "bayesian_probability" not in alert

        streak = pipeline.capture_continuity.active_streak("tent1", "camera.canopy")
        assert streak is not None
        assert streak.consecutive_count == 4
        assert streak.streak_started_at == NOW


@pytest.mark.asyncio
async def test_transport_failures_and_manual_captures_do_not_move_the_streak(
    tmp_path,
) -> None:
    """Only quality rejection and material scene change are qualifying evidence."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)

        pipeline.client.async_analyze.side_effect = RuntimeError("vision unavailable")
        await pipeline.scheduler.run_vision_analysis("tent1", "early")
        assert _continuity_alerts(pipeline) == []

        pipeline.client.async_analyze.side_effect = None
        await pipeline.scheduler.run_vision_analysis("tent1", "manual")
        assert _continuity_alerts(pipeline) == []
        streak = pipeline.capture_continuity.active_streak("tent1", "camera.canopy")
        assert streak is not None
        assert streak.consecutive_count == 2

        await _reject(pipeline)

        alerts = _continuity_alerts(pipeline)
        assert len(alerts) == 1
        assert alerts[0]["consecutive_count"] == 3
        assert alerts[0]["reason_counts"] == {"frame_rejected": 3}


@pytest.mark.asyncio
async def test_a_baseline_that_cannot_yet_score_neither_advances_nor_clears(
    tmp_path,
) -> None:
    """An accepted capture with no verdict is unavailable evidence, not recovery."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 3)

        await _accept(pipeline)

        streak = pipeline.capture_continuity.active_streak("tent1", "camera.canopy")
        assert streak is not None
        assert streak.consecutive_count == 3
        assert _continuity_alerts(pipeline)[0]["condition_active"] is True


@pytest.mark.asyncio
async def test_comparable_capture_clears_the_condition_and_rearms(tmp_path) -> None:
    """Recovery ends the condition without acknowledging the durable alert."""
    async with _pipeline(tmp_path) as pipeline:
        # A verdict needs a scoring baseline, and only comparable scheduled
        # evidence builds one — so the recovery this asserts is the real thing.
        await _accept(pipeline, BASELINE_SIZE)
        await _reject(pipeline, 3)

        await _accept(pipeline)

        cleared = _continuity_alerts(pipeline)[0]
        assert cleared["condition_active"] is False
        assert cleared["cleared_at"] == int(NOW.timestamp())
        assert cleared["resolved"] is False
        assert pipeline.capture_continuity.active_streak("tent1", "camera.canopy") is (
            None
        )

        await _reject(pipeline, 3)

        alerts = _continuity_alerts(pipeline)
        assert len(alerts) == 2
        assert alerts[0]["id"] != alerts[1]["id"]
        assert alerts[1]["condition_active"] is True
        assert alerts[1]["consecutive_count"] == 3


@pytest.mark.asyncio
async def test_a_scored_visual_anomaly_creates_no_alert(tmp_path) -> None:
    """ADR 0044: no Anomaly Score or fusion state may reach the durable inbox."""
    async with _pipeline(tmp_path) as pipeline:
        await _accept(pipeline, BASELINE_SIZE)

        pipeline.client.async_analyze.return_value = replace(
            pipeline.analyzed,
            embedding=SimpleNamespace(dimension=2, values=(0.0, 1.0)),
        )
        outcome = await pipeline.scheduler.run_vision_analysis("tent1", "early")

        capture = outcome.captures[0]
        assert capture.comparison is not None
        assert capture.comparison.verdict is ComparisonVerdict.MATERIAL_SCENE_CHANGE
        assert capture.comparison.anomaly_score == 1.0
        assert capture.fusion.fusion_state == EvidenceFusionState.VISUAL_ANOMALY.value
        assert pipeline.alert_monitor.get_alerts() == []


@pytest.mark.asyncio
async def test_unassigning_the_camera_clears_without_erasing_the_alert(
    tmp_path,
) -> None:
    """Removing an assignment ends the condition and starts the next one fresh."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 3)
        assert await pipeline.alert_monitor.resolve_alert(
            _continuity_alerts(pipeline)[0]["id"], "swapped the lens"
        )

        await pipeline.capture_continuity.async_apply_camera_assignment("tent1", [])

        retired = _continuity_alerts(pipeline)[0]
        assert retired["condition_active"] is False
        assert retired["resolved"] is True
        assert retired["resolution_note"] == "swapped the lens"
        assert retired["consecutive_count"] == 3
        assert pipeline.capture_continuity.active_streak("tent1", "camera.canopy") is (
            None
        )

        await pipeline.capture_continuity.async_apply_camera_assignment(
            "tent1", ["camera.canopy"]
        )
        await _reject(pipeline, 2)

        assert len(_continuity_alerts(pipeline)) == 1
        streak = pipeline.capture_continuity.active_streak("tent1", "camera.canopy")
        assert streak is not None
        assert streak.consecutive_count == 2


def test_evidence_projection_helpers_cover_available_and_unavailable_shapes() -> None:
    failed_capture = SimpleNamespace(analysis_state=AnalysisState.FAILED)
    analyzed_capture = SimpleNamespace(analysis_state=AnalysisState.ANALYZED)
    scored = SimpleNamespace(
        outcome=ComparisonOutcome.SCORED,
        verdict=ComparisonVerdict.MATERIAL_SCENE_CHANGE,
        comparison_confidence=0.9,
    )

    assert _fusion_visual(failed_capture, None).unavailable_reasons == (
        "vision_unavailable",
    )
    assert _fusion_visual(analyzed_capture, None).unavailable_reasons == (
        "vision_unavailable",
    )
    visual = _fusion_visual(analyzed_capture, scored)
    assert visual.verdict is ComparisonVerdict.MATERIAL_SCENE_CHANGE
    assert visual.comparison_confidence == 0.9

    summary = _explainer_fusion(
        AvailableFusionOutcome(
            state=EvidenceFusionState.VISUAL_ANOMALY,
            confidence=ConfidenceQualifier.CONFIRMED,
            coverage=EvidenceCoverage.COMPLETE,
        )
    )
    assert summary.state is EvidenceFusionState.VISUAL_ANOMALY
    assert _unpack_f32(None) == ()
