"""Public-boundary tests for the V1 Vision Checkup pipeline."""

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.data_access.vision_evidence_store import (
    VisionEvidenceStore,
)
from custom_components.growspace_manager.models.vision_evidence import (
    AnalysisState,
    CheckupStatus,
    ComparisonOutcome,
    ObservationSource,
)
from custom_components.growspace_manager.notifications.evaluation_snapshot import (
    EvaluationSnapshot,
)
from custom_components.growspace_manager.vision_checkup_scheduler import (
    VisionCheckupScheduler,
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
        client = SimpleNamespace(
            async_analyze=AsyncMock(
                return_value=VisionAnalysis(
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
            )
        )
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
            alert_monitor=SimpleNamespace(
                async_record_capture_continuity_break=AsyncMock(),
                async_clear_capture_continuity_break=AsyncMock(),
            ),
        )
        hass = MagicMock()
        hass.config.media_dirs = {"local": str(tmp_path / "media")}
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

        persisted = await pipeline.store.async_get_checkup_captures(
            outcome.checkup.checkup_id
        )
        assert [capture.analysis_state for capture in persisted] == [
            AnalysisState.ANALYZED
        ]
        pipeline.client.async_analyze.assert_awaited_once()


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
async def test_third_scheduled_rejection_raises_one_continuity_break(tmp_path) -> None:
    async with _pipeline(tmp_path) as pipeline:
        pipeline.client.async_analyze.return_value = VisionAnalysis(
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

        outcomes = [
            await pipeline.scheduler.run_vision_analysis("tent1", "early")
            for _ in range(3)
        ]

        assert [outcome.checkup.status for outcome in outcomes] == [
            CheckupStatus.COMPLETED,
            CheckupStatus.COMPLETED,
            CheckupStatus.COMPLETED,
        ]
        record = (
            pipeline.coordinator.alert_monitor.async_record_capture_continuity_break
        )
        record.assert_awaited_once()
        assert record.await_args.args[0].consecutive_count == 3
