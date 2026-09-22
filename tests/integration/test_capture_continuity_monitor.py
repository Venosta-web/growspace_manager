"""Tests for the Capture Continuity Break's runtime owner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.capture_continuity_monitor import (
    CaptureContinuityMonitor,
)
from custom_components.growspace_manager.domain.capture_continuity import (
    ContinuityReason,
    ContinuityTransition,
)
from custom_components.growspace_manager.models.vision_evidence import (
    AnalysisState,
    CaptureTrigger,
    ComparisonOutcome,
    ComparisonVerdict,
    LightState,
    LightWindow,
    VisionCapture,
    VisualComparisonResult,
)

GROWSPACE_ID = "tent1"
CAMERA_ID = "camera.canopy"
BASE_TIME = datetime(2026, 9, 1, 6, tzinfo=UTC)


class _MemoryStore:
    """Stand-in for a Home Assistant Store that keeps one payload in memory."""

    def __init__(self, data: dict | None = None) -> None:
        self.data = data

    async def async_load(self) -> dict | None:
        return self.data

    async def async_save(self, data: dict) -> None:
        self.data = data


def _capture(
    number: int,
    *,
    analysis_state: AnalysisState = AnalysisState.REJECTED,
    trigger: CaptureTrigger = CaptureTrigger.SCHEDULED,
    growspace_id: str = GROWSPACE_ID,
    camera_id: str = CAMERA_ID,
) -> VisionCapture:
    return VisionCapture(
        capture_id=f"capture-{number}",
        checkup_id=f"checkup-{number}",
        growspace_id=growspace_id,
        growspace_name="Test Tent",
        camera_id=camera_id,
        grow_run_id="run-1",
        framing_epoch_id="epoch-1",
        captured_at=(BASE_TIME + timedelta(hours=number)).isoformat(),
        light_window=LightWindow.EARLY,
        light_state=LightState.ON,
        trigger_source=trigger,
        analysis_state=analysis_state,
        created_at=BASE_TIME.isoformat(),
    )


def _comparison(verdict: ComparisonVerdict | None) -> VisualComparisonResult:
    return VisualComparisonResult(
        result_id="result-1",
        capture_id="capture-1",
        bucket_id="bucket-1",
        evaluated_at=BASE_TIME.isoformat(),
        outcome=(
            ComparisonOutcome.SCORED
            if verdict is not None
            else ComparisonOutcome.MONITORING
        ),
        verdict=verdict,
        trigger_source=CaptureTrigger.SCHEDULED,
        model_id="dinov2-small",
        model_version="1.0.0",
        scoring_policy_version=1,
    )


@pytest.fixture
def alert_monitor():
    """Record the condition transitions the monitor delivers."""
    monitor = MagicMock()
    monitor.async_record_capture_continuity_break = AsyncMock()
    monitor.async_clear_capture_continuity_break = AsyncMock()
    return monitor


@pytest.fixture
def store():
    return _MemoryStore()


@pytest.fixture
async def monitor(store, alert_monitor):
    subject = CaptureContinuityMonitor(store, alert_monitor)
    await subject.async_start()
    return subject


async def test_failed_capture_is_not_a_quality_rejection(
    monitor, alert_monitor
) -> None:
    """A transport failure carries no frame verdict and must not be given one."""
    for number in (1, 2):
        await monitor.async_record_capture(_capture(number), None)

    transition = await monitor.async_record_capture(
        _capture(3, analysis_state=AnalysisState.FAILED), None
    )

    assert transition is ContinuityTransition.NONE
    alert_monitor.async_record_capture_continuity_break.assert_not_awaited()
    streak = monitor.active_streak(GROWSPACE_ID, CAMERA_ID)
    assert streak is not None
    assert streak.consecutive_count == 2


async def test_accepted_capture_without_a_verdict_neither_advances_nor_clears(
    monitor, alert_monitor
) -> None:
    """A baseline that cannot score yet is missing evidence, not recovery."""
    for number in (1, 2, 3):
        await monitor.async_record_capture(_capture(number), None)
    alert_monitor.async_record_capture_continuity_break.reset_mock()

    transition = await monitor.async_record_capture(
        _capture(4, analysis_state=AnalysisState.ANALYZED),
        _comparison(None),
    )

    assert transition is ContinuityTransition.NONE
    alert_monitor.async_clear_capture_continuity_break.assert_not_awaited()
    alert_monitor.async_record_capture_continuity_break.assert_not_awaited()
    streak = monitor.active_streak(GROWSPACE_ID, CAMERA_ID)
    assert streak is not None
    assert streak.condition_active is True


async def test_later_captures_update_the_same_alert(monitor, alert_monitor) -> None:
    """The fourth qualifying capture updates the break rather than raising one."""
    transitions = [
        await monitor.async_record_capture(_capture(number), None)
        for number in (1, 2, 3)
    ]
    transitions.append(
        await monitor.async_record_capture(
            _capture(4, analysis_state=AnalysisState.ANALYZED),
            _comparison(ComparisonVerdict.MATERIAL_SCENE_CHANGE),
        )
    )

    assert transitions == [
        ContinuityTransition.NONE,
        ContinuityTransition.NONE,
        ContinuityTransition.ACTIVATED,
        ContinuityTransition.NONE,
    ]
    assert alert_monitor.async_record_capture_continuity_break.await_count == 2
    latest = alert_monitor.async_record_capture_continuity_break.await_args.args[0]
    assert latest.consecutive_count == 4
    assert latest.streak_started_at == BASE_TIME + timedelta(hours=1)
    assert latest.reason_counts == (
        (ContinuityReason.FRAME_REJECTED, 3),
        (ContinuityReason.MATERIAL_SCENE_CHANGE, 1),
    )


async def test_manual_capture_leaves_no_trace(monitor, store) -> None:
    """A grower's on-demand check cannot advance, clear or persist anything."""
    transition = await monitor.async_record_capture(
        _capture(1, trigger=CaptureTrigger.MANUAL), None
    )

    assert transition is ContinuityTransition.NONE
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID) is None
    assert store.data is None


async def test_concurrent_assignments_keep_separate_evidence(
    monitor, alert_monitor
) -> None:
    """One camera in two growspaces is two streaks that never pool captures."""
    for number in (1, 2, 3):
        await monitor.async_record_capture(_capture(number), None)
    await monitor.async_record_capture(_capture(4, growspace_id="tent2"), None)

    other = monitor.active_streak("tent2", CAMERA_ID)
    assert other is not None
    assert other.consecutive_count == 1
    assert other.condition_active is False
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID).consecutive_count == 3


async def test_unassigning_clears_the_condition_and_drops_the_streak(
    monitor, alert_monitor
) -> None:
    """Retiring an assignment ends its condition and starts the next one fresh."""
    for number in (1, 2, 3):
        await monitor.async_record_capture(_capture(number), None)

    await monitor.async_apply_camera_assignment(GROWSPACE_ID, ["camera.side"])

    alert_monitor.async_clear_capture_continuity_break.assert_awaited_once()
    call = alert_monitor.async_clear_capture_continuity_break.await_args
    assert call.args == (GROWSPACE_ID, CAMERA_ID)
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID) is None

    await monitor.async_record_capture(_capture(5), None)
    streak = monitor.active_streak(GROWSPACE_ID, CAMERA_ID)
    assert streak is not None
    assert streak.consecutive_count == 1
    assert streak.streak_started_at == BASE_TIME + timedelta(hours=5)


async def test_unassigning_an_unbroken_camera_clears_no_alert(
    monitor, alert_monitor
) -> None:
    """A streak that never activated has no condition to clear."""
    await monitor.async_record_capture(_capture(1), None)

    await monitor.async_apply_camera_assignment(GROWSPACE_ID, [])

    alert_monitor.async_clear_capture_continuity_break.assert_not_awaited()
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID) is None


async def test_assignment_of_another_growspace_leaves_this_streak_alone(
    monitor, alert_monitor
) -> None:
    """Reconciliation is scoped to the growspace whose configuration changed."""
    await monitor.async_record_capture(_capture(1), None)

    await monitor.async_apply_camera_assignment("tent2", [])

    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID) is not None
    alert_monitor.async_clear_capture_continuity_break.assert_not_awaited()


async def test_streaks_survive_a_restart(store, alert_monitor) -> None:
    """A live streak is durable, so a restart cannot re-arm a break from zero."""
    first = CaptureContinuityMonitor(store, alert_monitor)
    await first.async_start()
    for number in (1, 2):
        await first.async_record_capture(_capture(number), None)

    restarted = CaptureContinuityMonitor(store, alert_monitor)
    await restarted.async_start()
    transition = await restarted.async_record_capture(_capture(3), None)

    assert transition is ContinuityTransition.ACTIVATED
    reloaded = restarted.active_streak(GROWSPACE_ID, CAMERA_ID)
    assert reloaded is not None
    assert reloaded.consecutive_count == 3
    assert reloaded.streak_started_at == BASE_TIME + timedelta(hours=1)
    assert reloaded.reason_counts == ((ContinuityReason.FRAME_REJECTED, 3),)


async def test_unreadable_stored_streak_is_discarded(alert_monitor) -> None:
    """A corrupt row costs its own streak, not every other camera's."""
    store = _MemoryStore(
        {
            "streaks": [
                {"growspace_id": "tent2", "camera_id": "camera.missing-fields"},
                {
                    "growspace_id": "tent2",
                    "camera_id": "camera.bad-timestamp",
                    "streak_started_at": "the day before yesterday",
                    "consecutive_count": 2,
                    "reason_counts": {"frame_rejected": 2},
                    "latest_capture_id": "capture-2",
                    "latest_captured_at": BASE_TIME.isoformat(),
                    "condition_active": False,
                },
                {
                    "growspace_id": GROWSPACE_ID,
                    "camera_id": CAMERA_ID,
                    "streak_started_at": BASE_TIME.isoformat(),
                    "consecutive_count": 2,
                    "reason_counts": {"frame_rejected": 2},
                    "latest_capture_id": "capture-2",
                    "latest_captured_at": BASE_TIME.isoformat(),
                    "condition_active": False,
                },
            ]
        }
    )
    monitor = CaptureContinuityMonitor(store, alert_monitor)

    await monitor.async_start()

    assert monitor.active_streak("tent2", "camera.missing-fields") is None
    assert monitor.active_streak("tent2", "camera.bad-timestamp") is None
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID) is not None
