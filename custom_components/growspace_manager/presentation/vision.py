"""Card-facing projections for Vision Checkups and service status."""

from __future__ import annotations

from typing import Any

from custom_components.growspace_manager.data_access.vision_evidence_store import (
    VisionEvidenceStore,
)
from custom_components.growspace_manager.models.vision_evidence import (
    AnalysisState,
    CaptureFileVariant,
    VisionCapture,
    VisionCheckup,
    VisionExplainerReport,
    VisionFusionOutcome,
    VisualComparisonResult,
)
from custom_components.growspace_manager.vision_connection import VisionStatus


def serialize_vision_status(status: VisionStatus) -> dict[str, Any]:
    """Project the cached service status without exposing connection credentials."""
    payload: dict[str, Any] = {
        "availability": status.availability.value,
        "connection_source": status.connection_source.value,
    }
    if status.reason is not None:
        payload["reason"] = status.reason.value
    if status.service_version is not None:
        payload["service_version"] = status.service_version
    if status.vision_schema_version is not None:
        payload["vision_schema_version"] = status.vision_schema_version
    if status.model is not None:
        payload["model"] = {
            "id": status.model.id,
            "version": status.model.version,
            "dimension": status.model.dimension,
        }
    return payload


def serialize_legacy_vision_result(result: Any) -> dict[str, Any]:
    """Attribute one frozen cloud-era row without changing its payload."""
    return {
        "result_schema": "legacy_cloud_v1",
        "timestamp": result.timestamp,
        "check_type": result.check_type,
        "snapshot_paths": list(result.snapshot_paths),
        "analysis": result.analysis,
        "issues_detected": list(result.issues_detected),
        "severity": result.severity,
        "recommendations": list(result.recommendations),
    }


async def async_serialize_vision_checkup(
    store: VisionEvidenceStore,
    checkup: VisionCheckup,
    *,
    media_source: str,
) -> dict[str, Any]:
    """Project one durable Vision Checkup into the versioned card contract."""
    captures = [
        await _async_serialize_capture(store, capture, media_source=media_source)
        for capture in await store.async_get_checkup_captures(checkup.checkup_id)
    ]
    return {
        "result_schema": "evidence_v1",
        "checkup_id": checkup.checkup_id,
        "growspace_id": checkup.growspace_id,
        "trigger_source": checkup.trigger_source.value,
        "light_window": checkup.light_window.value,
        "started_at": checkup.started_at,
        "completed_at": checkup.completed_at,
        "status": checkup.status.value if checkup.status is not None else None,
        "captures": captures,
    }


async def _async_serialize_capture(
    store: VisionEvidenceStore,
    capture: VisionCapture,
    *,
    media_source: str,
) -> dict[str, Any]:
    comparisons = await store.async_get_comparison_results(capture.capture_id)
    fusions = await store.async_get_fusion_outcomes(capture.capture_id)
    reports = await store.async_get_explainer_reports(capture.capture_id)
    comparison = comparisons[-1] if comparisons else None
    fusion = fusions[-1] if fusions else None
    report = reports[-1] if reports else None

    payload: dict[str, Any] = {
        "capture_id": capture.capture_id,
        "camera_id": capture.camera_id,
        "captured_at": capture.captured_at,
        "analysis_state": capture.analysis_state.value,
        "image": await _async_image(store, capture, media_source),
        "quality": _quality(capture),
        "provenance": _provenance(capture, comparison),
        "visual": _visual(capture, comparison),
        "environment": _environment(fusion),
        "fusion": _fusion(fusion),
        "trend": await _async_trend(store, capture, comparison),
    }
    if report is not None:
        payload["report"] = _report(report)
    return payload


async def _async_image(
    store: VisionEvidenceStore, capture: VisionCapture, media_source: str
) -> dict[str, Any]:
    files = await store.async_get_capture_files(capture.capture_id)
    available = [item for item in files if item.deleted_at is None]
    preferred = next(
        (item for item in available if item.variant is CaptureFileVariant.PROCESSED),
        available[0] if available else None,
    )
    if preferred is None:
        return {"available": False}
    return {
        "available": True,
        "media_content_id": (
            f"media-source://media_source/{media_source}/growspace_vision/"
            f"{preferred.relative_path}"
        ),
    }


def _quality(capture: VisionCapture) -> dict[str, Any]:
    metrics = {
        "mean_luminance": capture.quality_mean_luminance,
        "clipped_pixel_fraction": capture.quality_clipped_pixel_fraction,
        "mean_absolute_gradient": capture.quality_mean_absolute_gradient,
    }
    payload: dict[str, Any] = {
        "accepted": capture.analysis_state is AnalysisState.ANALYZED,
        "reasons": list(capture.quality_reasons),
    }
    if any(value is not None for value in metrics.values()):
        payload["metrics"] = metrics
    return payload


def _provenance(
    capture: VisionCapture, comparison: VisualComparisonResult | None
) -> dict[str, Any]:
    values = {
        "vision_schema_version": capture.vision_schema_version,
        "service_version": capture.service_version,
        "model_id": comparison.model_id if comparison is not None else None,
        "model_version": comparison.model_version if comparison is not None else None,
        "scoring_policy_version": (
            comparison.scoring_policy_version if comparison is not None else None
        ),
    }
    return {key: value for key, value in values.items() if value is not None}


def _visual(
    capture: VisionCapture, comparison: VisualComparisonResult | None
) -> dict[str, Any]:
    if comparison is None:
        reason = {
            AnalysisState.PENDING: "analysis_pending",
            AnalysisState.REJECTED: "frame_rejected",
            AnalysisState.FAILED: "vision_unavailable",
        }.get(capture.analysis_state, "comparison_unavailable")
        return {"outcome": "unavailable", "unavailable_reasons": [reason]}
    values = {
        "outcome": comparison.outcome.value,
        "baseline_state": (
            comparison.baseline_state.value
            if comparison.baseline_state is not None
            else None
        ),
        "samples_collected": comparison.samples_collected,
        "samples_required": comparison.samples_required,
        "raw_distance": comparison.raw_distance,
        "anomaly_score": comparison.anomaly_score,
        "verdict": comparison.verdict.value if comparison.verdict is not None else None,
        "comparison_confidence": comparison.comparison_confidence,
        "unavailable_reasons": list(comparison.unavailable_reasons),
    }
    return {key: value for key, value in values.items() if value is not None}


def _environment(fusion: VisionFusionOutcome | None) -> dict[str, Any]:
    if fusion is None:
        return {
            "verdict": "unavailable",
            "stress_reasons": [],
            "mold_reasons": [],
        }
    payload: dict[str, Any] = {
        "verdict": fusion.environmental_verdict,
        "stress_reasons": list(fusion.stress_reasons),
        "mold_reasons": list(fusion.mold_reasons),
    }
    if fusion.environmental_evaluated_at is not None:
        payload["evaluated_at"] = fusion.environmental_evaluated_at
    return payload


def _fusion(fusion: VisionFusionOutcome | None) -> dict[str, Any]:
    if fusion is None:
        return {"unavailable_reasons": ["fusion_unavailable"]}
    values = {
        "state": fusion.fusion_state,
        "confidence": fusion.fusion_confidence,
        "coverage": fusion.fusion_coverage,
        "unavailable_reasons": list(fusion.unavailable_reasons),
    }
    return {key: value for key, value in values.items() if value is not None}


async def _async_trend(
    store: VisionEvidenceStore,
    capture: VisionCapture,
    comparison: VisualComparisonResult | None,
) -> list[dict[str, Any]]:
    if comparison is None:
        return []
    rows = await store.async_get_comparison_trend(
        capture_id=capture.capture_id,
        camera_id=capture.camera_id,
        grow_run_id=capture.grow_run_id,
        framing_epoch_id=capture.framing_epoch_id,
        model_id=comparison.model_id,
        model_version=comparison.model_version,
        scoring_policy_version=comparison.scoring_policy_version,
        before_evaluated_at=comparison.evaluated_at,
    )
    trend: list[dict[str, Any]] = []
    for item, fusion_state in rows:
        point: dict[str, Any] = {
            "evaluated_at": item.evaluated_at,
            "anomaly_score": item.anomaly_score,
            "verdict": item.verdict.value if item.verdict is not None else None,
        }
        if fusion_state is not None:
            point["fusion_state"] = fusion_state
        trend.append(point)
    return trend


def _report(report: VisionExplainerReport) -> dict[str, Any]:
    return {
        "observation": report.observation,
        "environmental_risk": report.environmental_risk,
        "hypothesis": report.hypothesis,
        "recommendations": list(report.recommendations),
    }
