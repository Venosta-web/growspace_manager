"""Golden fixtures for the public Vision Checkup contracts."""

from __future__ import annotations

from dataclasses import replace
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models.vision_evidence import (
    AnalysisState,
    BaselineState,
    CaptureFileVariant,
    CaptureTrigger,
    CheckupStatus,
    ComparisonOutcome,
    ComparisonVerdict,
    FileDeletionReason,
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
from custom_components.growspace_manager.services.vision_checkup import (
    handle_trigger_vision_checkup,
)
from custom_components.growspace_manager.vision_connection import (
    VisionAvailability,
    VisionConnectionSource,
    VisionModelSummary,
    VisionStatus,
    VisionUnavailableReason,
)
from custom_components.growspace_manager.websocket import (
    websocket_get_vision_history_v2,
    websocket_get_vision_status,
)
from homeassistant.core import HomeAssistant

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "contract"
FIXTURE_PATHS = {
    "status": FIXTURE_DIR / "vision_status_response.json",
    "history": FIXTURE_DIR / "vision_history_response.json",
    "trigger": FIXTURE_DIR / "trigger_vision_checkup_response.json",
}
REGENERATION_COMMAND = (
    "../../.venv/bin/pytest tests/contract/test_vision_contract.py "
    "--regenerate-contract-fixture"
)


def _checkup(suffix: int, status: CheckupStatus, *, started_at: str) -> VisionCheckup:
    return VisionCheckup(
        checkup_id=f"01991f1d-5c0{suffix}-7000-8000-000000000001",
        growspace_id="contract-growspace",
        growspace_name="Contract Growspace",
        trigger_source=CaptureTrigger.SCHEDULED,
        light_window=LightWindow.EARLY,
        started_at=started_at,
        completed_at=started_at.replace("00+00:00", "04+00:00"),
        status=status,
    )


def _capture(
    checkup: VisionCheckup,
    suffix: int,
    state: AnalysisState,
) -> VisionCapture:
    analyzed = state is AnalysisState.ANALYZED
    rejected = state is AnalysisState.REJECTED
    return VisionCapture(
        capture_id=f"01991f1d-6c0{suffix}-7000-8000-000000000001",
        checkup_id=checkup.checkup_id,
        growspace_id=checkup.growspace_id,
        growspace_name=checkup.growspace_name,
        camera_id=f"camera.contract_{suffix}",
        grow_run_id="contract-run",
        framing_epoch_id="contract-epoch",
        captured_at=checkup.started_at.replace("00+00:00", "01+00:00"),
        light_window=checkup.light_window,
        light_state=LightState.ON,
        trigger_source=checkup.trigger_source,
        analysis_state=state,
        created_at=checkup.started_at,
        analysis_error_code="vision_unavailable"
        if state is AnalysisState.FAILED
        else None,
        request_id="contract-request" if analyzed or rejected else None,
        vision_schema_version=1 if analyzed or rejected else None,
        service_version="1.4.0" if analyzed or rejected else None,
        quality_mean_luminance=112.5 if analyzed else 2.0 if rejected else None,
        quality_clipped_pixel_fraction=0.08 if analyzed else 0.0 if rejected else None,
        quality_mean_absolute_gradient=14.25 if analyzed else 1.0 if rejected else None,
        quality_reasons=("too_dark",) if rejected else (),
    )


def _contract_store():
    completed = _checkup(
        3, CheckupStatus.COMPLETED, started_at="2026-09-03T06:00:00+00:00"
    )
    partial = _checkup(2, CheckupStatus.PARTIAL, started_at="2026-09-02T06:00:00+00:00")
    failed = _checkup(1, CheckupStatus.FAILED, started_at="2026-09-01T06:00:00+00:00")
    analyzed = _capture(completed, 4, AnalysisState.ANALYZED)
    rejected = _capture(partial, 3, AnalysisState.REJECTED)
    partial_failure = _capture(partial, 2, AnalysisState.FAILED)
    failed_capture = _capture(failed, 1, AnalysisState.FAILED)
    captures = {
        completed.checkup_id: [analyzed],
        partial.checkup_id: [rejected, partial_failure],
        failed.checkup_id: [failed_capture],
    }
    comparison = VisualComparisonResult(
        result_id="contract-comparison",
        capture_id=analyzed.capture_id,
        evaluated_at="2026-09-03T06:00:02+00:00",
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
        result_id="contract-prior-comparison",
        capture_id="contract-prior-capture",
        evaluated_at="2026-09-02T06:00:02+00:00",
        outcome=ComparisonOutcome.SCORED,
        trigger_source=CaptureTrigger.SCHEDULED,
        model_id="dinov2-small",
        model_version="1.0.0",
        scoring_policy_version=1,
        anomaly_score=0.1,
        verdict=ComparisonVerdict.NORMAL,
        comparison_confidence=0.9,
    )
    fusions = {
        analyzed.capture_id: VisionFusionOutcome(
            outcome_id="contract-fusion-analyzed",
            capture_id=analyzed.capture_id,
            evaluated_at="2026-09-03T06:00:03+00:00",
            scoring_policy_version=1,
            environmental_verdict="within_evaluated_range",
            environmental_evaluated_at="2026-09-03T05:55:00+00:00",
            fusion_state="no_detected_change",
            fusion_confidence="confirmed",
            fusion_coverage="complete",
        ),
        rejected.capture_id: VisionFusionOutcome(
            outcome_id="contract-fusion-rejected",
            capture_id=rejected.capture_id,
            evaluated_at="2026-09-02T06:00:03+00:00",
            scoring_policy_version=1,
            environmental_verdict="risk",
            environmental_evaluated_at="2026-09-02T05:55:00+00:00",
            stress_reasons=("high_vpd",),
            fusion_state="environmental_risk",
            fusion_confidence="monitor",
            fusion_coverage="partial",
        ),
        partial_failure.capture_id: VisionFusionOutcome(
            outcome_id="contract-fusion-partial-failure",
            capture_id=partial_failure.capture_id,
            evaluated_at="2026-09-02T06:00:03+00:00",
            scoring_policy_version=1,
            environmental_verdict="unavailable",
            unavailable_reasons=("vision_unavailable", "stress_evidence_stale"),
        ),
        failed_capture.capture_id: VisionFusionOutcome(
            outcome_id="contract-fusion-failed",
            capture_id=failed_capture.capture_id,
            evaluated_at="2026-09-01T06:00:03+00:00",
            scoring_policy_version=1,
            environmental_verdict="unavailable",
            unavailable_reasons=("vision_unavailable",),
        ),
    }
    report = VisionExplainerReport(
        report_id="contract-report",
        capture_id=analyzed.capture_id,
        created_at="2026-09-03T06:00:03+00:00",
        ai_task_entity_id="ai_task.contract",
        observation_source=ObservationSource.IMAGE_PASS,
        scoring_policy_version=1,
        observation="The canopy is even across the frame.",
        environmental_risk="Measurements are within their evaluated range.",
        hypothesis="",
        recommendations=("Continue monitoring.",),
    )
    available_file = VisionCaptureFile(
        capture_id=analyzed.capture_id,
        variant=CaptureFileVariant.PROCESSED,
        relative_path=f"contract-growspace/camera.contract_4/{analyzed.capture_id}.processed.jpg",
        byte_size=1234,
        content_type="image/jpeg",
    )
    pruned_file = VisionCaptureFile(
        capture_id=failed_capture.capture_id,
        variant=CaptureFileVariant.RAW,
        relative_path=f"contract-growspace/camera.contract_1/{failed_capture.capture_id}.raw.jpg",
        byte_size=1234,
        content_type="image/jpeg",
        deleted_at="2026-12-01T00:00:00+00:00",
        deletion_reason=FileDeletionReason.RETENTION,
    )
    store = AsyncMock()
    store.async_get_checkups.return_value = [completed, partial, failed]
    store.async_count_checkups.return_value = 3
    store.async_count_captures.return_value = 4
    store.async_get_checkup_captures.side_effect = lambda checkup_id: captures[
        checkup_id
    ]
    store.async_get_capture_files.side_effect = lambda capture_id: (
        [available_file]
        if capture_id == analyzed.capture_id
        else [pruned_file]
        if capture_id == failed_capture.capture_id
        else []
    )
    store.async_get_comparison_results.side_effect = lambda capture_id: (
        [comparison] if capture_id == analyzed.capture_id else []
    )
    store.async_get_fusion_outcomes.side_effect = lambda capture_id: [
        fusions[capture_id]
    ]
    store.async_get_explainer_reports.side_effect = lambda capture_id: (
        [report] if capture_id == analyzed.capture_id else []
    )
    store.async_get_comparison_trend.return_value = [(prior, "no_detected_change")]
    return store, completed, analyzed, report


async def _build_payloads(hass: HomeAssistant) -> dict[str, object]:
    store, completed, analyzed, report = _contract_store()
    legacy = SimpleNamespace(
        timestamp="2026-08-31T06:00:00+00:00",
        check_type="early",
        snapshot_paths=["/local/contract-legacy.jpg"],
        analysis="Historical cloud description.",
        issues_detected=["yellowing"],
        severity="high",
        recommendations=["Historical recommendation."],
    )
    growspace = SimpleNamespace(vision_checkup_history=[legacy])
    coordinator = MagicMock()
    coordinator.growspaces = {"contract-growspace": growspace}
    coordinator.vision_connection.status = VisionStatus(
        availability=VisionAvailability.READY,
        connection_source=VisionConnectionSource.SUPERVISOR,
        service_version="1.4.0",
        vision_schema_version=1,
        model=VisionModelSummary(id="dinov2-small", version="1.0.0", dimension=384),
    )
    hass.data.setdefault(DOMAIN, {})["vision_evidence_store"] = store
    hass.config.media_dirs = {"local": str(FIXTURE_DIR)}
    ready = await websocket_get_vision_status(
        hass, coordinator, {"id": 1, "type": f"{DOMAIN}/get_vision_status"}
    )
    coordinator.vision_connection.status = VisionStatus(
        availability=VisionAvailability.UNAVAILABLE,
        connection_source=VisionConnectionSource.SUPERVISOR,
        reason=VisionUnavailableReason.NOT_RUNNING,
    )
    unavailable = await websocket_get_vision_status(
        hass, coordinator, {"id": 2, "type": f"{DOMAIN}/get_vision_status"}
    )
    history = await websocket_get_vision_history_v2(
        hass,
        coordinator,
        {
            "id": 3,
            "type": f"{DOMAIN}/get_vision_history_v2",
            "growspace_id": "contract-growspace",
            "limit": 10,
        },
    )
    manual_checkup = replace(
        completed,
        trigger_source=CaptureTrigger.MANUAL,
        light_window=LightWindow.MANUAL,
    )
    coordinator.vision_scheduler.run_vision_analysis = AsyncMock(
        return_value=SimpleNamespace(
            checkup=manual_checkup,
            captures=(
                SimpleNamespace(
                    capture=analyzed,
                    report=report,
                    media_content_id=history["history"][0]["captures"][0]["image"][
                        "media_content_id"
                    ],
                ),
            ),
        )
    )
    trigger = await handle_trigger_vision_checkup(
        hass,
        coordinator,
        SimpleNamespace(data={"growspace_id": "contract-growspace"}),
    )
    return {
        "status": {"ready": ready, "unavailable": unavailable},
        "history": history,
        "trigger": trigger,
    }


@pytest.mark.asyncio
async def test_vision_contract_fixtures(
    hass: HomeAssistant, pytestconfig: pytest.Config
) -> None:
    """Keep real public projections synchronized with golden JSON fixtures."""
    payloads = json.loads(json.dumps(await _build_payloads(hass)))

    if pytestconfig.getoption("regenerate_contract_fixture"):
        FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
        for name, path in FIXTURE_PATHS.items():
            path.write_text(
                f"{json.dumps(payloads[name], indent=2, sort_keys=True)}\n",
                encoding="utf-8",
            )

    for name, path in FIXTURE_PATHS.items():
        assert path.exists(), (
            f"Vision {name} contract fixture is missing. Regenerate it with: "
            f"{REGENERATION_COMMAND}"
        )
        assert payloads[name] == json.loads(path.read_text(encoding="utf-8")), (
            f"Vision {name} payload changed. Review the contract diff, then regenerate "
            f"with: {REGENERATION_COMMAND}"
        )
