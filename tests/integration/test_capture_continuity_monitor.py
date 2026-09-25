"""Tests for the Capture Continuity Break's runtime owner."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.capture_continuity_monitor import (
    ActivationOrigin,
    CaptureContinuityMonitor,
)
from custom_components.growspace_manager.data_access.vision_evidence_store import (
    VisionEvidenceStore,
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
    monitor.async_reconcile_capture_continuity = AsyncMock()
    return monitor


@pytest.fixture
def store():
    return _MemoryStore()


@pytest.fixture
async def evidence(tmp_path):
    """An empty Vision Evidence Store: nothing on record, nothing to recover."""
    subject = VisionEvidenceStore(tmp_path / "vision.db", tmp_path / "images")
    await subject.async_setup()
    yield subject
    await subject.async_close()


@pytest.fixture
async def monitor(store, alert_monitor, evidence):
    subject = CaptureContinuityMonitor(store, alert_monitor, evidence)
    await subject.async_start({GROWSPACE_ID: [CAMERA_ID], "tent2": [CAMERA_ID]})
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


async def test_manual_capture_neither_advances_nor_clears(
    monitor, alert_monitor
) -> None:
    """A grower's on-demand check cannot move the streak either way."""
    await monitor.async_record_capture(_capture(1), None)

    transition = await monitor.async_record_capture(
        _capture(2, trigger=CaptureTrigger.MANUAL), None
    )

    assert transition is ContinuityTransition.NONE
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID).consecutive_count == 1
    alert_monitor.async_clear_capture_continuity_break.assert_not_awaited()


async def test_a_capture_already_folded_in_is_ignored(monitor) -> None:
    """Processing the same capture twice cannot count it twice."""
    await monitor.async_record_capture(_capture(1), None)
    await monitor.async_record_capture(_capture(2), None)

    transition = await monitor.async_record_capture(_capture(1), None)

    assert transition is ContinuityTransition.NONE
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID).consecutive_count == 2


async def test_live_activation_is_new_until_its_condition_clears(monitor) -> None:
    """The activation a checkup raises is news; comparable evidence ends it."""
    for number in (1, 2, 3):
        await monitor.async_record_capture(_capture(number), None)

    activation = monitor.activation(GROWSPACE_ID, CAMERA_ID)
    assert activation is not None
    assert activation.activation_id == "capture-1"
    assert activation.activated_at == BASE_TIME + timedelta(hours=3)
    assert activation.origin is ActivationOrigin.NEW

    await monitor.async_record_capture(
        _capture(4, analysis_state=AnalysisState.ANALYZED),
        _comparison(ComparisonVerdict.NORMAL),
    )

    assert monitor.activation(GROWSPACE_ID, CAMERA_ID) is None


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
    assert monitor.activation(GROWSPACE_ID, CAMERA_ID) is None

    # A capture that was in flight when the camera left belongs to nobody.
    assert (
        await monitor.async_record_capture(_capture(4), None)
        is ContinuityTransition.NONE
    )
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID) is None

    await monitor.async_apply_camera_assignment(
        GROWSPACE_ID, ["camera.side", CAMERA_ID]
    )
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


async def test_unchanged_assignment_writes_nothing(monitor, store) -> None:
    """Re-saving the same cameras is not an assignment change."""
    saved = store.data

    await monitor.async_apply_camera_assignment(GROWSPACE_ID, [CAMERA_ID])

    assert store.data is saved


async def test_assignments_follow_configuration_at_start(
    alert_monitor, evidence
) -> None:
    """Stored rows are kept, unreadable ones reopened, unconfigured ones retired."""
    kept = {"captured_at": BASE_TIME.isoformat(), "capture_id": "capture-0"}
    store = _MemoryStore(
        {
            "assignments": [
                {"growspace_id": GROWSPACE_ID, "camera_id": CAMERA_ID},
                {
                    "growspace_id": GROWSPACE_ID,
                    "camera_id": "camera.side",
                    "evidence_after": kept,
                    "processed_through": kept,
                },
                {
                    "growspace_id": "tent2",
                    "camera_id": "camera.gone",
                    "evidence_after": None,
                    "processed_through": None,
                },
                {
                    "growspace_id": "tent2",
                    "camera_id": "camera.garbled",
                    "evidence_after": "not a marker",
                    "processed_through": None,
                },
            ]
        }
    )
    monitor = CaptureContinuityMonitor(store, alert_monitor, evidence)

    await monitor.async_start(
        {GROWSPACE_ID: [CAMERA_ID, "camera.side"], "tent2": ["camera.garbled"]}
    )

    rows = {
        (row["growspace_id"], row["camera_id"]): row
        for row in store.data["assignments"]
    }
    assert set(rows) == {
        (GROWSPACE_ID, CAMERA_ID),
        (GROWSPACE_ID, "camera.side"),
        ("tent2", "camera.garbled"),
    }
    assert rows[(GROWSPACE_ID, "camera.side")]["evidence_after"] == kept
    assert rows[(GROWSPACE_ID, CAMERA_ID)]["evidence_after"] is None
    alert_monitor.async_reconcile_capture_continuity.assert_awaited_once()
    assert alert_monitor.async_reconcile_capture_continuity.await_args.args == ([],)


async def test_without_an_evidence_store_nothing_is_recovered(
    store, alert_monitor
) -> None:
    """No store means no checkup ever ran here, so there is nothing to rebuild."""
    monitor = CaptureContinuityMonitor(store, alert_monitor, None)

    await monitor.async_start({GROWSPACE_ID: [CAMERA_ID]})

    assert store.data is None
    alert_monitor.async_reconcile_capture_continuity.assert_not_awaited()

    # An assignment made while nothing on record can be read begins now, so
    # evidence written before it can never be adopted later.
    await monitor.async_apply_camera_assignment(GROWSPACE_ID, [CAMERA_ID])
    (row,) = store.data["assignments"]
    assert row["evidence_after"]["capture_id"] == ""
    earlier = replace(
        _capture(1), captured_at=datetime(2025, 12, 1, tzinfo=UTC).isoformat()
    )
    assert earlier.captured_at < row["evidence_after"]["captured_at"]
    await monitor.async_record_capture(earlier, None)
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID) is None

    await monitor.async_record_capture(_capture(2), None)
    assert monitor.active_streak(GROWSPACE_ID, CAMERA_ID).consecutive_count == 1


async def test_an_unparsable_capture_time_is_refused_loudly(monitor) -> None:
    """A capture the store could not have written is a bug, not evidence."""
    with pytest.raises(ValueError, match="Unparsable capture timestamp"):
        await monitor.async_record_capture(
            replace(_capture(1), captured_at="the day before yesterday"), None
        )
