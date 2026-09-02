"""Behavior tests for the card-facing Vision presentation seam."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.growspace_manager.models.vision_evidence import (
    AnalysisState,
    BaselineState,
    CaptureFileVariant,
    CaptureTrigger,
    CheckupStatus,
    ComparisonOutcome,
    ComparisonVerdict,
    LightState,
    LightWindow,
    ObservationSource,
    VisionCapture,
    VisionCaptureFile,
    VisionCheckup,
    VisionExplainerReport,
    VisionFusionOutcome,
    VisualComparisonResult,
)
from custom_components.growspace_manager.presentation.vision import (
    async_serialize_vision_checkup,
)


@pytest.mark.asyncio
async def test_checkup_projection_exposes_capture_evidence_and_authenticated_image() -> (
    None
):
    """One V1 row carries evidence and a media id, never a storage path."""
    checkup = VisionCheckup(
        checkup_id="01991f1d-5c00-7000-8000-000000000001",
        growspace_id="tent-1",
        growspace_name="Flower Tent",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at="2026-09-01T06:00:00+00:00",
        completed_at="2026-09-01T06:00:04+00:00",
        status=CheckupStatus.COMPLETED,
    )
    capture = VisionCapture(
        capture_id="01991f1d-5c01-7000-8000-000000000001",
        checkup_id=checkup.checkup_id,
        growspace_id="tent-1",
        growspace_name="Flower Tent",
        camera_id="camera.canopy",
        grow_run_id="run-1",
        framing_epoch_id="epoch-1",
        captured_at="2026-09-01T06:00:01+00:00",
        light_window=LightWindow.EARLY,
        light_state=LightState.ON,
        trigger_source=CaptureTrigger.SCHEDULED,
        analysis_state=AnalysisState.ANALYZED,
        created_at="2026-09-01T06:00:01+00:00",
        request_id="request-1",
        vision_schema_version=1,
        service_version="1.4.0",
        quality_mean_luminance=112.5,
        quality_clipped_pixel_fraction=0.08,
        quality_mean_absolute_gradient=14.25,
    )
    comparison = VisualComparisonResult(
        result_id="comparison-1",
        capture_id=capture.capture_id,
        evaluated_at="2026-09-01T06:00:02+00:00",
        outcome=ComparisonOutcome.SCORED,
        trigger_source=CaptureTrigger.SCHEDULED,
        model_id="dinov2-small",
        model_version="1.0.0",
        scoring_policy_version=1,
        baseline_state=BaselineState.READY,
        samples_collected=30,
        samples_required=30,
        raw_distance=0.04,
        anomaly_score=0.2,
        verdict=ComparisonVerdict.NORMAL,
        comparison_confidence=0.8,
        admitted_to_baseline=True,
    )
    prior = VisualComparisonResult(
        result_id="comparison-0",
        capture_id="prior-capture",
        evaluated_at="2026-08-31T06:00:02+00:00",
        outcome=ComparisonOutcome.SCORED,
        trigger_source=CaptureTrigger.SCHEDULED,
        model_id="dinov2-small",
        model_version="1.0.0",
        scoring_policy_version=1,
        anomaly_score=0.1,
        verdict=ComparisonVerdict.NORMAL,
        comparison_confidence=0.9,
    )
    fusion = VisionFusionOutcome(
        outcome_id="fusion-1",
        capture_id=capture.capture_id,
        evaluated_at="2026-09-01T06:00:03+00:00",
        scoring_policy_version=1,
        environmental_verdict="within_evaluated_range",
        environmental_evaluated_at="2026-09-01T05:55:00+00:00",
        fusion_state="no_detected_change",
        fusion_confidence="confirmed",
        fusion_coverage="complete",
    )
    report = VisionExplainerReport(
        report_id="report-1",
        capture_id=capture.capture_id,
        created_at="2026-09-01T06:00:03+00:00",
        ai_task_entity_id="ai_task.cloud",
        observation_source=ObservationSource.IMAGE_PASS,
        scoring_policy_version=1,
        observation="The canopy is even across the frame.",
        environmental_risk="Measurements are within their evaluated range.",
        hypothesis="",
        recommendations=("Continue monitoring.",),
    )
    processed = VisionCaptureFile(
        capture_id=capture.capture_id,
        variant=CaptureFileVariant.PROCESSED,
        relative_path=f"tent-1/camera.canopy/{capture.capture_id}.processed.jpg",
        byte_size=1234,
        content_type="image/jpeg",
    )
    store = AsyncMock()
    store.async_get_checkup_captures.return_value = [capture]
    store.async_get_capture_files.return_value = [processed]
    store.async_get_comparison_results.return_value = [comparison]
    store.async_get_fusion_outcomes.return_value = [fusion]
    store.async_get_explainer_reports.return_value = [report]
    store.async_get_comparison_trend.return_value = [(prior, "no_detected_change")]

    payload = await async_serialize_vision_checkup(store, checkup, media_source="local")

    assert payload == {
        "result_schema": "evidence_v1",
        "checkup_id": checkup.checkup_id,
        "growspace_id": "tent-1",
        "trigger_source": "scheduled",
        "light_window": "early",
        "started_at": "2026-09-01T06:00:00+00:00",
        "completed_at": "2026-09-01T06:00:04+00:00",
        "status": "completed",
        "captures": [
            {
                "capture_id": capture.capture_id,
                "camera_id": "camera.canopy",
                "captured_at": "2026-09-01T06:00:01+00:00",
                "analysis_state": "analyzed",
                "image": {
                    "available": True,
                    "media_content_id": (
                        "media-source://media_source/local/growspace_vision/"
                        f"tent-1/camera.canopy/{capture.capture_id}.processed.jpg"
                    ),
                },
                "quality": {
                    "accepted": True,
                    "reasons": [],
                    "metrics": {
                        "mean_luminance": 112.5,
                        "clipped_pixel_fraction": 0.08,
                        "mean_absolute_gradient": 14.25,
                    },
                },
                "provenance": {
                    "vision_schema_version": 1,
                    "service_version": "1.4.0",
                    "model_id": "dinov2-small",
                    "model_version": "1.0.0",
                    "scoring_policy_version": 1,
                },
                "visual": {
                    "outcome": "scored",
                    "baseline_state": "ready",
                    "samples_collected": 30,
                    "samples_required": 30,
                    "raw_distance": 0.04,
                    "anomaly_score": 0.2,
                    "verdict": "normal",
                    "comparison_confidence": 0.8,
                    "unavailable_reasons": [],
                },
                "environment": {
                    "verdict": "within_evaluated_range",
                    "evaluated_at": "2026-09-01T05:55:00+00:00",
                    "stress_reasons": [],
                    "mold_reasons": [],
                },
                "fusion": {
                    "state": "no_detected_change",
                    "confidence": "confirmed",
                    "coverage": "complete",
                    "unavailable_reasons": [],
                },
                "trend": [
                    {
                        "evaluated_at": "2026-08-31T06:00:02+00:00",
                        "anomaly_score": 0.1,
                        "verdict": "normal",
                        "fusion_state": "no_detected_change",
                    }
                ],
                "report": {
                    "observation": "The canopy is even across the frame.",
                    "environmental_risk": "Measurements are within their evaluated range.",
                    "hypothesis": "",
                    "recommendations": ["Continue monitoring."],
                },
            }
        ],
    }
    assert "relative_path" not in str(payload)
