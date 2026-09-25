"""Public-boundary tests for the V1 Vision Checkup pipeline."""

from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import UTC, datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_capture_events,
    async_fire_time_changed,
)

from custom_components.growspace_manager.alert_monitor import AlertMonitor
from custom_components.growspace_manager.capture_continuity_monitor import (
    ActivationOrigin,
    CaptureContinuityMonitor,
)
from custom_components.growspace_manager.const import DOMAIN, NotificationTier
from custom_components.growspace_manager.continuity_notifier import (
    MAX_ATTEMPTS,
    RETRY_DELAYS,
    ContinuityNotifier,
)
from custom_components.growspace_manager.data_access.vision_evidence_store import (
    VisionEvidenceStore,
)
from custom_components.growspace_manager.domain.capture_continuity import (
    CAPTURE_CONTINUITY_MESSAGE,
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
from custom_components.growspace_manager.notification_manager import NotificationManager
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
from homeassistant.components import persistent_notification
from homeassistant.const import EVENT_CALL_SERVICE
from homeassistant.exceptions import HomeAssistantError
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

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
    """Stand-in for a Home Assistant Store that keeps one payload in memory.

    Payloads round-trip through JSON as a real Store's do, so what survives a
    restart here is exactly what would survive one on disk.
    """

    def __init__(self) -> None:
        self.data: str | None = None

    async def async_load(self) -> dict | None:
        return json.loads(self.data) if self.data is not None else None

    async def async_save(self, data: dict) -> None:
        self.data = json.dumps(data)


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


def _notifier(hass, coordinator, delivery_store):
    """Deliver through a real notifier on a real Home Assistant, or record only.

    Most pipeline tests run on a mock Home Assistant and are not about
    delivery; they get a notifier that only records what it was told.
    """
    if hass is None:
        return SimpleNamespace(async_start=AsyncMock(), async_announce=AsyncMock())
    return ContinuityNotifier(hass, coordinator, delivery_store)


@asynccontextmanager
async def _pipeline(tmp_path, *, ai_settings: dict | None = None, hass=None):
    store = VisionEvidenceStore(tmp_path / "vision.db", tmp_path / "images")
    await store.async_setup()
    pipeline = None
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
        notifications_enabled: dict[str, bool] = {}
        notifications = SimpleNamespace(
            latest_evaluation=lambda _growspace_id, sensor_type: _evaluation(
                sensor_type
            ),
            is_notifications_enabled=lambda growspace_id: notifications_enabled.get(
                growspace_id, True
            ),
        )
        coordinator = SimpleNamespace(
            growspaces={"tent1": growspace},
            vision_connection=connection,
            options={"ai_settings": ai_settings or {}},
            services=SimpleNamespace(notifications=notifications),
            async_update_listeners=MagicMock(),
        )
        real_hass = hass
        if hass is None:
            hass = MagicMock()
        else:
            entry = MockConfigEntry(domain=DOMAIN)
            entry.add_to_hass(hass)
            coordinator.config_entry = entry
        hass.config.media_dirs = {"local": str(tmp_path / "media")}
        # The durable alert path is the thing under test, so the checkup runs
        # against the real Alert Monitor and the real continuity owner rather
        # than mocks that would accept any policy the scheduler invented.
        alert_store = _MemoryStore()
        alert_monitor = AlertMonitor(
            hass,
            coordinator=coordinator,
            store=alert_store,
            ai_assistant_factory=None,
        )
        await alert_monitor.async_start()
        continuity_store = _MemoryStore()
        delivery_store = _MemoryStore()
        notifier = _notifier(real_hass, coordinator, delivery_store)
        capture_continuity = CaptureContinuityMonitor(
            continuity_store, alert_monitor, store, notifier
        )
        await capture_continuity.async_start({"tent1": ["camera.canopy"]})
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
            pipeline = SimpleNamespace(
                scheduler=scheduler,
                store=store,
                client=client,
                growspace=growspace,
                coordinator=coordinator,
                analyzed=analyzed,
                alert_monitor=alert_monitor,
                capture_continuity=capture_continuity,
                alert_store=alert_store,
                continuity_store=continuity_store,
                delivery_store=delivery_store,
                notifier=notifier,
                notifications_enabled=notifications_enabled,
                real_hass=real_hass,
                paths=(tmp_path / "vision.db", tmp_path / "images"),
            )
            yield pipeline
    finally:
        # A restart inside the test replaces the store; close whichever is open.
        if pipeline is not None and hasattr(pipeline.notifier, "async_stop"):
            pipeline.notifier.async_stop()
        await store.async_close()
        if pipeline is not None:
            await pipeline.store.async_close()


async def _restart(pipeline, assignments: dict | None = None) -> None:
    """Stop and start again over the durable stores the pipeline wrote.

    The Vision Evidence Store is closed and reopened from its file; the Alert
    Monitor and the continuity owner are rebuilt from their persisted payloads
    alone, so nothing in memory survives.
    """
    await pipeline.store.async_close()
    store = VisionEvidenceStore(*pipeline.paths)
    await store.async_setup()
    pipeline.store = store
    alert_monitor = AlertMonitor(
        pipeline.scheduler.hass,
        coordinator=pipeline.coordinator,
        store=pipeline.alert_store,
        ai_assistant_factory=None,
    )
    await alert_monitor.async_start()
    if hasattr(pipeline.notifier, "async_stop"):
        pipeline.notifier.async_stop()
    notifier = _notifier(
        pipeline.real_hass, pipeline.coordinator, pipeline.delivery_store
    )
    capture_continuity = CaptureContinuityMonitor(
        pipeline.continuity_store, alert_monitor, store, notifier
    )
    await capture_continuity.async_start(
        assignments
        if assignments is not None
        else {"tent1": pipeline.growspace.environment_config.camera_entities}
    )
    pipeline.alert_monitor = pipeline.coordinator.alert_monitor = alert_monitor
    pipeline.notifier = notifier
    pipeline.capture_continuity = pipeline.coordinator.capture_continuity = (
        capture_continuity
    )
    pipeline.scheduler = VisionCheckupScheduler(
        pipeline.scheduler.hass, pipeline.coordinator, evidence_store=store
    )


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


async def _fail(pipeline) -> None:
    """Run a scheduled checkup whose Vision Analysis never completes."""
    pipeline.client.async_analyze.side_effect = RuntimeError("vision unavailable")
    await pipeline.scheduler.run_vision_analysis("tent1", "early")


async def _manual(pipeline) -> None:
    """Run a grower-requested checkup the quality gate rejects."""
    pipeline.client.async_analyze.side_effect = None
    pipeline.client.async_analyze.return_value = REJECTED_ANALYSIS
    await pipeline.scheduler.run_vision_analysis("tent1", "manual")


async def _scene_change(pipeline) -> None:
    """Run a scheduled checkup scored as a material scene change."""
    pipeline.client.async_analyze.side_effect = None
    pipeline.client.async_analyze.return_value = replace(
        pipeline.analyzed,
        embedding=SimpleNamespace(dimension=2, values=(0.0, 1.0)),
    )
    await pipeline.scheduler.run_vision_analysis("tent1", "early")


def _streak(pipeline):
    return pipeline.capture_continuity.active_streak("tent1", "camera.canopy")


def _activation(pipeline):
    return pipeline.capture_continuity.activation("tent1", "camera.canopy")


def _stored_alerts(pipeline) -> list[dict]:
    return json.loads(pipeline.alert_store.data)["alerts"]


def _rewrite_alerts(pipeline, alerts: list[dict]) -> None:
    pipeline.alert_store.data = json.dumps({"alerts": alerts})


@pytest.mark.asyncio
async def test_recovery_agrees_with_live_evaluation_over_a_long_mixed_streak(
    tmp_path,
) -> None:
    """Replaying retained evidence rebuilds exactly the streak live intake held.

    Twelve qualifying captures with failures, manual captures and accepted
    captures no baseline could score yet between them: far past any three-row
    window, and every non-qualifying kind in the gaps.
    """
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)
        await _accept(pipeline, BASELINE_SIZE)
        await _fail(pipeline)
        await _manual(pipeline)
        await _scene_change(pipeline)
        await _reject(pipeline, 4)
        await _fail(pipeline)
        await _scene_change(pipeline)
        await _manual(pipeline)
        await _reject(pipeline, 4)
        live = _streak(pipeline)
        live_activation = _activation(pipeline)
        assert live is not None
        assert live.consecutive_count == 12
        assert live_activation is not None
        assert live_activation.origin is ActivationOrigin.NEW
        (alert,) = _continuity_alerts(pipeline)

        await _restart(pipeline)

        assert _streak(pipeline) == live
        recovered = _activation(pipeline)
        assert recovered == replace(live_activation, origin=ActivationOrigin.HISTORICAL)
        assert _continuity_alerts(pipeline) == [alert]


@pytest.mark.asyncio
async def test_restart_keeps_pre_threshold_progress(tmp_path) -> None:
    """Two qualifying captures before a restart still count toward the third."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)
        started = _streak(pipeline)

        await _restart(pipeline)

        assert _streak(pipeline) == started
        assert _activation(pipeline) is None
        assert _continuity_alerts(pipeline) == []

        await _reject(pipeline)

        (alert,) = _continuity_alerts(pipeline)
        assert alert["consecutive_count"] == 3
        assert _streak(pipeline).streak_started_capture_id == (
            started.streak_started_capture_id
        )
        assert _activation(pipeline).origin is ActivationOrigin.NEW


@pytest.mark.asyncio
async def test_restart_keeps_an_active_streak_and_its_one_alert(tmp_path) -> None:
    """The original start, count, condition and acknowledgement all survive."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 4)
        (alert,) = _continuity_alerts(pipeline)
        assert await pipeline.alert_monitor.resolve_alert(alert["id"], "cleaned lens")
        before = _streak(pipeline)

        await _restart(pipeline)

        assert _streak(pipeline) == before
        (recovered,) = _continuity_alerts(pipeline)
        assert recovered["id"] == alert["id"]
        assert recovered["timestamp"] == alert["timestamp"]
        assert recovered["consecutive_count"] == 4
        assert recovered["condition_active"] is True
        assert recovered["resolved"] is True
        assert recovered["resolution_note"] == "cleaned lens"
        assert _activation(pipeline).origin is ActivationOrigin.HISTORICAL

        await _reject(pipeline)

        (continued,) = _continuity_alerts(pipeline)
        assert continued["id"] == alert["id"]
        assert continued["consecutive_count"] == 5


@pytest.mark.asyncio
async def test_pruned_images_do_not_shorten_a_recovered_streak(tmp_path) -> None:
    """Image retention deletes files, never the evidence rows a replay reads."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 3)
        before = _streak(pipeline)
        pruned = await pipeline.store.async_prune_images(
            image_retention_days=1, now=NOW + timedelta(days=30)
        )
        assert pruned > 0

        await _restart(pipeline)

        assert _streak(pipeline) == before
        assert _continuity_alerts(pipeline)[0]["condition_active"] is True


@pytest.mark.asyncio
async def test_capture_persisted_but_never_processed_activates_as_new(
    tmp_path,
) -> None:
    """A checkup interrupted after its evidence was written is not history."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)
        with patch.object(
            pipeline.capture_continuity,
            "async_record_capture",
            side_effect=RuntimeError("stopped mid-checkup"),
        ):
            await _reject(pipeline)
        assert _continuity_alerts(pipeline) == []

        await _restart(pipeline)

        (alert,) = _continuity_alerts(pipeline)
        assert alert["condition_active"] is True
        assert alert["consecutive_count"] == 3
        assert _activation(pipeline).origin is ActivationOrigin.NEW


@pytest.mark.asyncio
async def test_interruption_after_the_alert_does_not_duplicate_it(tmp_path) -> None:
    """The alert landed but progress was not recorded: one alert, still new."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)
        with patch.object(
            pipeline.continuity_store,
            "async_save",
            side_effect=OSError("disk full"),
        ):
            await _reject(pipeline)
        (alert,) = _continuity_alerts(pipeline)

        await _restart(pipeline)

        assert _continuity_alerts(pipeline) == [alert]
        assert _activation(pipeline).origin is ActivationOrigin.NEW


@pytest.mark.asyncio
async def test_cleared_alerts_and_acknowledgement_survive_restart(tmp_path) -> None:
    """Cleared conditions stay cleared, resolved or not, and nothing is invented."""
    async with _pipeline(tmp_path) as pipeline:
        await _accept(pipeline, BASELINE_SIZE)
        await _reject(pipeline, 3)
        first = _continuity_alerts(pipeline)[0]
        assert await pipeline.alert_monitor.resolve_alert(first["id"], "re-aimed")
        await _accept(pipeline)
        await _reject(pipeline, 3)
        await _accept(pipeline)
        before = _continuity_alerts(pipeline)
        assert [alert["condition_active"] for alert in before] == [False, False]
        assert [alert["resolved"] for alert in before] == [True, False]

        await _restart(pipeline)

        assert _continuity_alerts(pipeline) == before
        assert _streak(pipeline) is None
        assert _activation(pipeline) is None

        await _reject(pipeline, 3)

        alerts = _continuity_alerts(pipeline)
        assert len(alerts) == 3
        assert alerts[2]["condition_active"] is True


@pytest.mark.asyncio
async def test_inbox_trimming_cannot_reset_or_renew_an_activation(tmp_path) -> None:
    """The bounded Inbox keeps a live condition and is never the streak's source."""
    async with _pipeline(tmp_path) as pipeline:
        pipeline.alert_monitor.MAX_ALERTS = 2
        await _reject(pipeline, 3)
        (alert,) = _continuity_alerts(pipeline)
        for _ in range(3):
            await pipeline.alert_monitor.async_record_alert(
                "tent1", "stress", ["vpd"], 0.9
            )
        assert _continuity_alerts(pipeline) == [alert]
        assert len(pipeline.alert_monitor.get_alerts()) == 2

        await _restart(pipeline)
        await _reject(pipeline)

        (continued,) = _continuity_alerts(pipeline)
        assert continued["id"] == alert["id"]
        assert continued["consecutive_count"] == 4
        assert _activation(pipeline).origin is ActivationOrigin.HISTORICAL


@pytest.mark.asyncio
async def test_an_inbox_that_lost_the_alert_does_not_make_the_activation_new(
    tmp_path,
) -> None:
    """Streak state comes from evidence; the current condition is shown again."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 3)
        activation = _activation(pipeline)
        _rewrite_alerts(pipeline, [])

        await _restart(pipeline)

        assert _streak(pipeline).consecutive_count == 3
        assert _activation(pipeline) == replace(
            activation, origin=ActivationOrigin.HISTORICAL
        )
        (alert,) = _continuity_alerts(pipeline)
        assert alert["condition_active"] is True
        assert alert["timestamp"] == int(activation.activated_at.timestamp())


@pytest.mark.asyncio
async def test_a_returning_camera_does_not_inherit_its_previous_assignment(
    tmp_path,
) -> None:
    """Evidence from before a re-assignment cannot complete a streak after it."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)
        await pipeline.capture_continuity.async_apply_camera_assignment("tent1", [])
        await pipeline.capture_continuity.async_apply_camera_assignment(
            "tent1", ["camera.canopy"]
        )

        await _restart(pipeline)

        assert _streak(pipeline) is None
        await _reject(pipeline)
        assert _streak(pipeline).consecutive_count == 1
        assert _continuity_alerts(pipeline) == []


@pytest.mark.asyncio
async def test_a_camera_moved_elsewhere_leaves_its_condition_behind(
    tmp_path,
) -> None:
    """Another Growspace never recovers this one's evidence; this one's clears."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 3)
        assert await pipeline.alert_monitor.resolve_alert(
            _continuity_alerts(pipeline)[0]["id"], "moved it"
        )

        await _restart(pipeline, {"tent2": ["camera.canopy"]})

        assert pipeline.capture_continuity.active_streak("tent2", "camera.canopy") is (
            None
        )
        assert _streak(pipeline) is None
        (alert,) = _continuity_alerts(pipeline)
        assert alert["condition_active"] is False
        assert alert["cleared_at"] is not None
        assert alert["resolved"] is True
        assert alert["resolution_note"] == "moved it"


@pytest.mark.asyncio
async def test_orphan_evidence_cannot_activate_a_recreated_growspace(tmp_path) -> None:
    """Pinned captures a deleted growspace left behind stay out of its successor."""
    async with _pipeline(tmp_path) as pipeline:
        await _accept(pipeline, BASELINE_SIZE)
        await _scene_change(pipeline)
        await _scene_change(pipeline)
        await pipeline.capture_continuity.async_apply_camera_assignment("tent1", [])
        await pipeline.store.async_delete_growspace("tent1")
        orphans = await pipeline.store.async_get_capture_evidence(
            "tent1", "camera.canopy"
        )
        assert [
            comparison.verdict
            for _capture, comparison in orphans
            if comparison is not None and comparison.verdict is not None
        ] == [ComparisonVerdict.MATERIAL_SCENE_CHANGE] * 2
        await pipeline.capture_continuity.async_apply_camera_assignment(
            "tent1", ["camera.canopy"]
        )

        await _restart(pipeline)
        await _reject(pipeline)

        assert _streak(pipeline).consecutive_count == 1
        assert _continuity_alerts(pipeline) == []


@pytest.mark.asyncio
async def test_upgrade_corrects_three_row_evidence_and_keeps_the_grower_note(
    tmp_path,
) -> None:
    """An alert raised by the old window is corrected in place, not replaced."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)
        await _fail(pipeline)
        await _manual(pipeline)
        await _reject(pipeline, 3)
        streak = _streak(pipeline)
        (stored,) = _stored_alerts(pipeline)
        # What the three-row window wrote: no activation identity, a count of
        # three and a start inside the streak rather than at its beginning.
        stored.pop("activation_id")
        stored.update(
            consecutive_count=3,
            reason_counts={"frame_rejected": 3},
            streak_started_at=(NOW + timedelta(hours=1)).isoformat(),
            resolved=True,
            resolution_notes="checked the camera",
        )
        _rewrite_alerts(pipeline, [stored])
        pipeline.continuity_store.data = json.dumps(
            {"streaks": [{"growspace_id": "tent1", "camera_id": "camera.canopy"}]}
        )

        await _restart(pipeline)

        (alert,) = _continuity_alerts(pipeline)
        assert alert["id"] == stored["alert_id"]
        assert alert["consecutive_count"] == 5
        assert alert["reason_counts"] == {"frame_rejected": 5}
        assert alert["streak_started_at"] == int(NOW.timestamp())
        assert alert["latest_capture_id"] == streak.latest_capture_id
        assert alert["condition_active"] is True
        assert alert["resolved"] is True
        assert alert["resolution_note"] == "checked the camera"
        assert _stored_alerts(pipeline)[0]["activation_id"] == (
            streak.streak_started_capture_id
        )
        assert _activation(pipeline).origin is ActivationOrigin.HISTORICAL


@pytest.mark.asyncio
async def test_upgrade_clears_a_condition_the_old_window_invented(tmp_path) -> None:
    """Transport failures were never rejections; the streak keeps its real count."""
    async with _pipeline(tmp_path) as pipeline:
        await _reject(pipeline, 2)
        await _fail(pipeline)
        await pipeline.alert_monitor.async_record_capture_continuity_break(
            replace(_streak(pipeline), consecutive_count=3, condition_active=True)
        )
        (stored,) = _stored_alerts(pipeline)
        stored.pop("activation_id")
        stored["resolution_notes"] = "saw it"
        _rewrite_alerts(pipeline, [stored])
        pipeline.continuity_store.data = None

        await _restart(pipeline)

        (alert,) = _continuity_alerts(pipeline)
        assert alert["id"] == stored["alert_id"]
        assert alert["condition_active"] is False
        assert alert["cleared_at"] is not None
        assert alert["resolution_note"] == "saw it"
        assert _streak(pipeline).consecutive_count == 2
        assert _activation(pipeline) is None


@pytest.mark.asyncio
async def test_upgrade_manufactures_no_alert_for_a_break_that_already_ended(
    tmp_path,
) -> None:
    """History nobody was shown is not written into the Inbox after the fact."""
    async with _pipeline(tmp_path) as pipeline:
        await _accept(pipeline, BASELINE_SIZE)
        await _reject(pipeline, 3)
        await _accept(pipeline)
        await _reject(pipeline, 3)
        _rewrite_alerts(pipeline, [])
        pipeline.continuity_store.data = None

        await _restart(pipeline)

        (alert,) = _continuity_alerts(pipeline)
        assert alert["condition_active"] is True
        assert _activation(pipeline).origin is ActivationOrigin.HISTORICAL
        assert _streak(pipeline).consecutive_count == 3


# ---------------------------------------------------------------------------
# Continuity notifications (#741): the grower hears about each new break once
# ---------------------------------------------------------------------------


@pytest.fixture
async def notifications(hass):
    """A real Home Assistant with persistent notifications available."""
    assert await async_setup_component(hass, "persistent_notification", {})
    return hass


def _shown(hass) -> dict:
    """Every continuity notification Home Assistant is currently showing."""
    return {
        notification_id: notification
        for notification_id, notification in (
            persistent_notification._async_get_or_create_notifications(hass).items()
        )
        if notification_id.startswith("growspace_capture_continuity_")
    }


def _sends(calls) -> list[dict]:
    """Every persistent notification the integration asked Home Assistant for."""
    return [
        call.data["service_data"]
        for call in calls
        if call.data["domain"] == "persistent_notification"
        and call.data["service"] == "create"
    ]


def _deliveries(pipeline) -> list[dict]:
    return json.loads(pipeline.delivery_store.data)["deliveries"]


def _channel(pipeline) -> dict:
    (delivery,) = _deliveries(pipeline)
    return delivery["channels"]["home_assistant"]


async def _settle(pipeline) -> None:
    await pipeline.real_hass.async_block_till_done(wait_background_tasks=True)


async def _advance(pipeline, delay: timedelta) -> None:
    """Let Home Assistant's clock run on, so due retries fire."""
    async_fire_time_changed(pipeline.real_hass, dt_util.utcnow() + delay)
    await _settle(pipeline)


async def _mute(pipeline) -> None:
    """Flip the growspace notification switch off, as the switch entity does."""
    pipeline.notifications_enabled["tent1"] = False
    await pipeline.notifier.async_mute("tent1")


@asynccontextmanager
async def _unsendable(pipeline):
    """Refuse every persistent notification until the block ends.

    Yields the requests that were refused.
    """
    hass = pipeline.real_hass
    create = hass.services.async_services_for_domain("persistent_notification")[
        "create"
    ]
    refused: list = []

    async def _refuse(call) -> None:
        refused.append(call)
        raise HomeAssistantError("persistent notifications unavailable")

    hass.services.async_register("persistent_notification", "create", _refuse)
    try:
        yield refused
    finally:
        hass.services.async_register(
            "persistent_notification", "create", create.job.target, create.schema
        )


@pytest.mark.asyncio
async def test_a_new_break_shows_one_notification_without_a_device_target(
    notifications, tmp_path
) -> None:
    """Third qualifying capture: one alert, one notification, one delivery record."""
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        pipeline.growspace.notification_target = None
        notifications.states.async_set(
            "camera.canopy", "idle", {"friendly_name": "Canopy"}
        )

        await _reject(pipeline, 2)
        await _settle(pipeline)
        assert _shown(notifications) == {}

        await _reject(pipeline)
        await _settle(pipeline)

        (alert,) = _continuity_alerts(pipeline)
        activation = _activation(pipeline)
        (notification,) = _shown(notifications).values()
        assert notification["notification_id"] == (
            "growspace_capture_continuity_tent1_camera.canopy_"
            f"{activation.activation_id}"
        )
        assert notification["title"] == "⚠️ Capture Continuity Break: Test Tent"
        assert notification["message"] == (
            f"{CAPTURE_CONTINUITY_MESSAGE}\n\n"
            "Camera: Canopy (camera.canopy)\nGrowspace: Test Tent"
        )
        assert alert["description"] == CAPTURE_CONTINUITY_MESSAGE
        assert _deliveries(pipeline) == [
            {
                "activation_id": activation.activation_id,
                "growspace_id": "tent1",
                "camera_id": "camera.canopy",
                "activated_at": activation.activated_at.isoformat(),
                "channels": {"home_assistant": {"status": "delivered", "attempts": 0}},
            }
        ]


@pytest.mark.asyncio
async def test_a_break_is_announced_once_per_streak(notifications, tmp_path) -> None:
    """Continuation, restart and Inbox trimming stay quiet; a new streak does not."""
    calls = async_capture_events(notifications, EVENT_CALL_SERVICE)
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        pipeline.alert_monitor.MAX_ALERTS = 2
        await _reject(pipeline, 4)
        await _settle(pipeline)
        assert len(_sends(calls)) == 1

        for _ in range(3):
            await pipeline.alert_monitor.async_record_alert(
                "tent1", "stress", ["vpd"], 0.9
            )
        await _restart(pipeline)
        await _reject(pipeline)
        await _settle(pipeline)

        assert _activation(pipeline).origin is ActivationOrigin.HISTORICAL
        assert len(_sends(calls)) == 1
        assert _channel(pipeline)["status"] == "delivered"

        # A baseline, then one scored comparable capture to clear and re-arm.
        await _accept(pipeline, BASELINE_SIZE + 1)
        assert _activation(pipeline) is None
        await _reject(pipeline, 3)
        await _settle(pipeline)

        first, second = _sends(calls)
        assert first["notification_id"] != second["notification_id"]
        assert len(_shown(notifications)) == 2
        # The finished record of the streak that ended has nothing left to guard.
        (delivery,) = _deliveries(pipeline)
        assert delivery["activation_id"] == _activation(pipeline).activation_id


@pytest.mark.asyncio
async def test_an_upgrade_announces_nothing_it_rediscovers(
    notifications, tmp_path
) -> None:
    """Activations found by an upgrade were never news to this delivery store."""
    calls = async_capture_events(notifications, EVENT_CALL_SERVICE)
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        pipeline.notifications_enabled["tent1"] = False
        await _reject(pipeline, 3)
        pipeline.notifications_enabled["tent1"] = True
        pipeline.continuity_store.data = None
        pipeline.delivery_store.data = None

        await _restart(pipeline)
        await _settle(pipeline)

        assert _activation(pipeline).origin is ActivationOrigin.HISTORICAL
        assert _sends(calls) == []
        assert _deliveries(pipeline) == []


@pytest.mark.asyncio
async def test_muting_suppresses_delivery_but_never_the_alert(
    notifications, tmp_path
) -> None:
    """A muted activation stays unannounced, even once notifications return."""
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        pipeline.notifications_enabled["tent1"] = False

        await _reject(pipeline, 3)
        await _settle(pipeline)

        (alert,) = _continuity_alerts(pipeline)
        assert alert["condition_active"] is True
        assert _channel(pipeline) == {"status": "suppressed", "attempts": 0}
        assert _shown(notifications) == {}

        pipeline.notifications_enabled["tent1"] = True
        await _reject(pipeline)
        await _restart(pipeline)
        await _settle(pipeline)

        assert _shown(notifications) == {}
        assert _channel(pipeline)["status"] == "suppressed"

        # A baseline, then one scored comparable capture to clear and re-arm.
        await _accept(pipeline, BASELINE_SIZE + 1)
        assert _activation(pipeline) is None
        await _reject(pipeline, 3)
        await _settle(pipeline)

        assert len(_shown(notifications)) == 1


@pytest.mark.asyncio
async def test_unrelated_cooldowns_plants_and_ai_cannot_touch_the_warning(
    notifications, tmp_path
) -> None:
    """The generic sender's cooldown, no-Plants gate and AI rewrite do not apply."""
    ai_settings = {"ai_enabled": True, "assistant_id": "conversation.grow_master"}
    async with _pipeline(
        tmp_path, hass=notifications, ai_settings=ai_settings
    ) as pipeline:
        rewriter = SimpleNamespace(async_rewrite=AsyncMock(return_value="rewritten"))
        manager = NotificationManager(notifications, pipeline.coordinator, rewriter)
        pipeline.coordinator.services.notifications.manager = manager
        pipeline.coordinator.services.growspaces = SimpleNamespace(
            get_growspace_plants=lambda _growspace_id: []
        )
        manager.trigger_cooldown("tent1")
        assert manager._is_on_cooldown(
            "tent1", NotificationTier.WARNING, dt_util.utcnow()
        )

        await _reject(pipeline, 3)
        await _settle(pipeline)

        (notification,) = _shown(notifications).values()
        assert notification["message"].startswith(CAPTURE_CONTINUITY_MESSAGE)
        rewriter.async_rewrite.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_failed_delivery_retries_without_failing_the_checkup(
    notifications, tmp_path
) -> None:
    """The checkup completes, the alert is recorded once, and delivery follows."""
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        await _reject(pipeline, 2)
        async with _unsendable(pipeline):
            outcome = await pipeline.scheduler.run_vision_analysis("tent1", "early")
            await _settle(pipeline)

            assert outcome.checkup.status is CheckupStatus.COMPLETED
            assert len(_continuity_alerts(pipeline)) == 1
            assert _channel(pipeline) == {"status": "pending", "attempts": 1}
            assert await pipeline.store.async_get_capture_evidence(
                "tent1", "camera.canopy"
            )

        await _advance(pipeline, RETRY_DELAYS[0])

        assert len(_shown(notifications)) == 1
        assert _channel(pipeline) == {"status": "delivered", "attempts": 1}
        assert len(_continuity_alerts(pipeline)) == 1


@pytest.mark.asyncio
async def test_retries_are_bounded(notifications, tmp_path) -> None:
    """A channel that keeps failing is given up; its Triage Alert remains."""
    calls = async_capture_events(notifications, EVENT_CALL_SERVICE)
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        async with _unsendable(pipeline) as refused:
            await _reject(pipeline, 3)
            await _settle(pipeline)
            for delay in RETRY_DELAYS:
                await _advance(pipeline, delay)
            assert len(refused) == MAX_ATTEMPTS

            await _advance(pipeline, timedelta(days=1))

            assert len(refused) == MAX_ATTEMPTS
        assert _channel(pipeline) == {"status": "failed", "attempts": MAX_ATTEMPTS}
        assert _continuity_alerts(pipeline)[0]["condition_active"] is True

        await _restart(pipeline)
        await _settle(pipeline)

        assert len(_sends(calls)) == MAX_ATTEMPTS
        assert _shown(notifications) == {}


@pytest.mark.asyncio
async def test_muting_cancels_a_pending_retry(notifications, tmp_path) -> None:
    """A retry due after the switch went off is never sent, nor after un-muting."""
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        async with _unsendable(pipeline):
            await _reject(pipeline, 3)
            await _settle(pipeline)
        assert _channel(pipeline)["status"] == "pending"

        await _mute(pipeline)
        pipeline.notifications_enabled["tent1"] = True
        await _advance(pipeline, timedelta(days=1))
        await _restart(pipeline)
        await _settle(pipeline)

        assert _shown(notifications) == {}
        assert _channel(pipeline) == {"status": "suppressed", "attempts": 1}


@pytest.mark.asyncio
async def test_a_retry_that_finds_the_growspace_muted_is_suppressed(
    notifications, tmp_path
) -> None:
    """Muting by any route is honoured when the retry comes due."""
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        async with _unsendable(pipeline):
            await _reject(pipeline, 3)
            await _settle(pipeline)
        pipeline.notifications_enabled["tent1"] = False

        await _advance(pipeline, RETRY_DELAYS[0])

        assert _shown(notifications) == {}
        assert _channel(pipeline) == {"status": "suppressed", "attempts": 1}


@pytest.mark.asyncio
async def test_unload_cancels_retries_and_restart_resumes_them(
    notifications, tmp_path
) -> None:
    """Retry work follows the integration's lifecycle; progress survives it."""
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        async with _unsendable(pipeline):
            await _reject(pipeline, 3)
            await _settle(pipeline)

        pipeline.notifier.async_stop()
        await _advance(pipeline, timedelta(days=1))
        assert _shown(notifications) == {}

        await _restart(pipeline)
        await _settle(pipeline)

        assert len(_shown(notifications)) == 1
        assert _channel(pipeline) == {"status": "delivered", "attempts": 1}


@pytest.mark.asyncio
async def test_restart_before_the_send_delivers_once(notifications, tmp_path) -> None:
    """The record was written but the attempt never ran: restart sends it."""
    calls = async_capture_events(notifications, EVENT_CALL_SERVICE)
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        with patch.object(pipeline.notifier, "_spawn"):
            await _reject(pipeline, 3)
        assert _channel(pipeline)["status"] == "pending"

        await _restart(pipeline)
        await _settle(pipeline)

        assert len(_sends(calls)) == 1
        assert _channel(pipeline)["status"] == "delivered"


@pytest.mark.asyncio
async def test_restart_between_send_and_recorded_success_may_resend_the_same_id(
    notifications, tmp_path
) -> None:
    """At-least-once: the repeat carries the same id, so one notification shows."""
    calls = async_capture_events(notifications, EVENT_CALL_SERVICE)
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        save = pipeline.delivery_store.async_save

        async def _lose_success(data: dict) -> None:
            if any(
                channel["status"] == "delivered"
                for delivery in data["deliveries"]
                for channel in delivery["channels"].values()
            ):
                raise OSError("power cut")
            await save(data)

        with patch.object(
            pipeline.delivery_store, "async_save", side_effect=_lose_success
        ):
            await _reject(pipeline, 3)
            await _settle(pipeline)
        assert _channel(pipeline)["status"] == "pending"

        await _restart(pipeline)
        await _settle(pipeline)

        first, second = _sends(calls)
        assert first == second
        assert len(_shown(notifications)) == 1
        assert _channel(pipeline)["status"] == "delivered"


@pytest.mark.asyncio
async def test_a_checkup_interrupted_before_delivery_is_announced_after_restart(
    notifications, tmp_path
) -> None:
    """Evidence written, intake crashed: the new activation is still announced."""
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        await _reject(pipeline, 2)
        with patch.object(
            pipeline.capture_continuity,
            "async_record_capture",
            side_effect=RuntimeError("stopped mid-checkup"),
        ):
            await _reject(pipeline)

        await _restart(pipeline)
        await _settle(pipeline)

        assert _activation(pipeline).origin is ActivationOrigin.NEW
        assert len(_shown(notifications)) == 1
        assert _channel(pipeline)["status"] == "delivered"


@pytest.mark.asyncio
async def test_a_recorded_delivery_is_not_repeated_for_an_unprocessed_capture(
    notifications, tmp_path
) -> None:
    """Delivered, then progress was lost: the activation is new but already told."""
    calls = async_capture_events(notifications, EVENT_CALL_SERVICE)
    async with _pipeline(tmp_path, hass=notifications) as pipeline:
        await _reject(pipeline, 2)
        with patch.object(
            pipeline.continuity_store,
            "async_save",
            side_effect=OSError("disk full"),
        ):
            await _reject(pipeline)
            await _settle(pipeline)

        await _restart(pipeline)
        await _settle(pipeline)

        assert _activation(pipeline).origin is ActivationOrigin.NEW
        assert len(_sends(calls)) == 1
        assert _channel(pipeline)["status"] == "delivered"


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
