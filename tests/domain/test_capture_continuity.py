"""Behavior tests for the three-capture Capture Continuity Break."""

from datetime import UTC, datetime, timedelta

import pytest

from custom_components.growspace_manager.domain.capture_continuity import (
    CaptureContinuityEvent,
    ContinuityReason,
    ContinuityTransition,
    evaluate_capture_continuity,
)
from custom_components.growspace_manager.models.vision_evidence import (
    CaptureTrigger,
    ComparisonVerdict,
)

BASE_TIME = datetime(2026, 9, 1, 6, tzinfo=UTC)


def _event(
    number: int,
    *,
    quality_accepted: bool | None = False,
    verdict: ComparisonVerdict | None = None,
    trigger: CaptureTrigger = CaptureTrigger.SCHEDULED,
) -> CaptureContinuityEvent:
    return CaptureContinuityEvent(
        growspace_id="gs-1",
        camera_id="camera.canopy",
        capture_id=f"capture-{number}",
        captured_at=BASE_TIME + timedelta(hours=number),
        trigger_source=trigger,
        quality_accepted=quality_accepted,
        comparison_verdict=verdict,
    )


def test_third_scheduled_non_comparable_capture_activates_once_per_streak() -> None:
    """Later captures update evidence but cannot duplicate an active break."""
    state = None
    for number in (1, 2):
        decision = evaluate_capture_continuity(state, _event(number))
        state = decision.state
        assert decision.transition is ContinuityTransition.NONE

    third = evaluate_capture_continuity(state, _event(3))
    fourth = evaluate_capture_continuity(third.state, _event(4))

    assert third.transition is ContinuityTransition.ACTIVATED
    assert third.state is not None
    assert third.state.condition_active is True
    assert third.state.consecutive_count == 3
    assert third.state.reason_counts == ((ContinuityReason.FRAME_REJECTED, 3),)
    assert fourth.transition is ContinuityTransition.NONE
    assert fourth.state is not None
    assert fourth.state.consecutive_count == 4
    assert fourth.state.latest_capture_id == "capture-4"


def test_quality_rejections_and_material_changes_share_one_camera_streak() -> None:
    """Different non-comparable causes still express one equipment condition."""
    first = evaluate_capture_continuity(None, _event(1))
    second = evaluate_capture_continuity(
        first.state,
        _event(
            2,
            quality_accepted=True,
            verdict=ComparisonVerdict.MATERIAL_SCENE_CHANGE,
        ),
    )
    third = evaluate_capture_continuity(second.state, _event(3))

    assert third.transition is ContinuityTransition.ACTIVATED
    assert third.state is not None
    assert third.state.reason_counts == (
        (ContinuityReason.FRAME_REJECTED, 2),
        (ContinuityReason.MATERIAL_SCENE_CHANGE, 1),
    )


def test_manual_captures_neither_advance_nor_reset_the_streak() -> None:
    """A grower cannot manipulate continuity with an on-demand check."""
    first = evaluate_capture_continuity(None, _event(1))

    manual = evaluate_capture_continuity(
        first.state,
        _event(
            2,
            quality_accepted=True,
            verdict=ComparisonVerdict.NORMAL,
            trigger=CaptureTrigger.MANUAL,
        ),
    )

    assert manual.transition is ContinuityTransition.NONE
    assert manual.state is first.state


def test_comparable_capture_clears_and_rearms_a_later_break() -> None:
    """Condition clearing is separate from durable alert acknowledgement."""
    state = None
    for number in (1, 2, 3):
        state = evaluate_capture_continuity(state, _event(number)).state
    assert state is not None and state.condition_active

    cleared = evaluate_capture_continuity(
        state,
        _event(
            4,
            quality_accepted=True,
            verdict=ComparisonVerdict.UNCERTAIN,
        ),
    )
    assert cleared.transition is ContinuityTransition.CLEARED
    assert cleared.state is None

    decisions = []
    for number in (5, 6, 7):
        decision = evaluate_capture_continuity(
            decisions[-1].state if decisions else cleared.state,
            _event(number),
        )
        decisions.append(decision)
    assert decisions[-1].transition is ContinuityTransition.ACTIVATED


def test_unavailable_scheduled_capture_does_not_change_streak_evidence() -> None:
    """A transport or comparison failure is neither comparable nor a rejection."""
    first = evaluate_capture_continuity(None, _event(1))

    unavailable = evaluate_capture_continuity(
        first.state,
        _event(2, quality_accepted=None),
    )

    assert unavailable.transition is ContinuityTransition.NONE
    assert unavailable.state is first.state


def test_state_cannot_be_reused_for_a_different_camera() -> None:
    """Per-camera continuity state cannot leak across orchestration keys."""
    first = evaluate_capture_continuity(None, _event(1))
    assert first.state is not None

    with pytest.raises(ValueError, match="different camera"):
        evaluate_capture_continuity(
            first.state,
            CaptureContinuityEvent(
                growspace_id="gs-1",
                camera_id="camera.side",
                capture_id="capture-2",
                captured_at=BASE_TIME + timedelta(hours=2),
                trigger_source=CaptureTrigger.SCHEDULED,
                quality_accepted=False,
            ),
        )
