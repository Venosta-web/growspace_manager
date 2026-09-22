"""Pure state machine for the three-capture Capture Continuity Break."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from custom_components.growspace_manager.models.vision_evidence import (
    CaptureTrigger,
    ComparisonVerdict,
)

CAPTURE_CONTINUITY_THRESHOLD = 3
CAPTURE_CONTINUITY_MESSAGE = (
    "Camera captures no longer match recent history. Inspect the camera, lens, "
    "lighting, and growspace. Restart the visual baseline only if the framing "
    "change was intentional."
)


class ContinuityReason(StrEnum):
    """Which non-comparable result advanced a continuity streak."""

    FRAME_REJECTED = "frame_rejected"
    MATERIAL_SCENE_CHANGE = "material_scene_change"


class ContinuityTransition(StrEnum):
    """The side effect an outer orchestration layer must deliver."""

    NONE = "none"
    ACTIVATED = "activated"
    CLEARED = "cleared"


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureContinuityEvent:
    """One capture normalized to the evidence continuity consumes."""

    growspace_id: str
    camera_id: str
    capture_id: str
    captured_at: datetime
    trigger_source: CaptureTrigger
    quality_accepted: bool | None
    comparison_verdict: ComparisonVerdict | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureContinuityState:
    """The current non-comparable streak for one camera."""

    growspace_id: str
    camera_id: str
    streak_started_at: datetime
    consecutive_count: int
    reason_counts: tuple[tuple[ContinuityReason, int], ...]
    latest_capture_id: str
    latest_captured_at: datetime
    condition_active: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class CaptureContinuityDecision:
    """The next streak state and its one externally meaningful transition."""

    state: CaptureContinuityState | None
    transition: ContinuityTransition


def evaluate_capture_continuity(
    state: CaptureContinuityState | None,
    event: CaptureContinuityEvent,
) -> CaptureContinuityDecision:
    """Advance, clear, or ignore one capture according to ADR 0044."""
    if state is not None and (
        state.growspace_id != event.growspace_id or state.camera_id != event.camera_id
    ):
        raise ValueError("Capture Continuity State belongs to a different camera")
    if event.trigger_source is CaptureTrigger.MANUAL:
        return CaptureContinuityDecision(
            state=state,
            transition=ContinuityTransition.NONE,
        )

    reason = _non_comparable_reason(event)
    if reason is None:
        if event.quality_accepted is None or event.comparison_verdict is None:
            return CaptureContinuityDecision(
                state=state,
                transition=ContinuityTransition.NONE,
            )
        transition = (
            ContinuityTransition.CLEARED
            if state is not None and state.condition_active
            else ContinuityTransition.NONE
        )
        return CaptureContinuityDecision(state=None, transition=transition)

    counts = dict(state.reason_counts) if state is not None else {}
    counts[reason] = counts.get(reason, 0) + 1
    consecutive_count = (state.consecutive_count if state is not None else 0) + 1
    was_active = state.condition_active if state is not None else False
    condition_active = consecutive_count >= CAPTURE_CONTINUITY_THRESHOLD
    next_state = CaptureContinuityState(
        growspace_id=event.growspace_id,
        camera_id=event.camera_id,
        streak_started_at=(
            state.streak_started_at if state is not None else event.captured_at
        ),
        consecutive_count=consecutive_count,
        reason_counts=tuple(
            (candidate, counts[candidate])
            for candidate in ContinuityReason
            if candidate in counts
        ),
        latest_capture_id=event.capture_id,
        latest_captured_at=event.captured_at,
        condition_active=condition_active,
    )
    transition = (
        ContinuityTransition.ACTIVATED
        if condition_active and not was_active
        else ContinuityTransition.NONE
    )
    return CaptureContinuityDecision(state=next_state, transition=transition)


def _non_comparable_reason(
    event: CaptureContinuityEvent,
) -> ContinuityReason | None:
    """Classify only the two observations ADR 0044 permits to advance."""
    if event.quality_accepted is False:
        return ContinuityReason.FRAME_REJECTED
    if (
        event.quality_accepted is True
        and event.comparison_verdict is ComparisonVerdict.MATERIAL_SCENE_CHANGE
    ):
        return ContinuityReason.MATERIAL_SCENE_CHANGE
    return None
