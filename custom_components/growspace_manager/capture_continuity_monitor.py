"""Durable ownership of one camera assignment's Capture Continuity Break.

The Vision Checkup scheduler hands finished captures here and the Alert
Monitor keeps the durable Triage Alert; everything between the two — turning a
capture into the evidence ADR 0044 recognises, carrying the streak across
checkups, and retiring it when the camera stops being assigned — belongs to
this module. The streak decision itself stays in the pure
``domain/capture_continuity.py`` state machine, which this module is the only
runtime caller of.

The unit of ownership is a **Camera Assignment**: one camera assigned to one
Growspace. Two growspaces holding the same camera keep two streaks that never
see each other's evidence, and un-assigning a camera retires its streak, so a
later assignment starts from nothing.

Storage layout (``growspace_manager.capture_continuity``)::

    {
        "streaks": [
            {
                "growspace_id": "<id>",
                "camera_id": "camera.canopy",
                "streak_started_at": "<ISO-8601>",
                "consecutive_count": 3,
                "reason_counts": {"frame_rejected": 2, "material_scene_change": 1},
                "latest_capture_id": "<id>",
                "latest_captured_at": "<ISO-8601>",
                "condition_active": true
            },
            ...
        ]
    }

Only live streaks are stored. A cleared or retired condition leaves no row
here — its durable Triage Alert and the grower's acknowledgement live in the
Alert Monitor and are never touched by this module beyond marking the
condition inactive.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .domain.capture_continuity import (
    CaptureContinuityEvent,
    CaptureContinuityState,
    ContinuityReason,
    ContinuityTransition,
    evaluate_capture_continuity,
)
from .models.vision_evidence import AnalysisState

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

    from .alert_monitor import AlertMonitor
    from .models.vision_evidence import VisionCapture, VisualComparisonResult

_LOGGER = logging.getLogger(__name__)

_QUALITY_ACCEPTED: dict[AnalysisState, bool | None] = {
    AnalysisState.ANALYZED: True,
    AnalysisState.REJECTED: False,
    # A transport failure and a capture that never reached analysis carry no
    # frame-quality verdict at all. ADR 0044 lets neither advance the streak,
    # and calling them rejections is exactly the reclassification this module
    # exists to prevent.
    AnalysisState.FAILED: None,
    AnalysisState.PENDING: None,
}

type _AssignmentKey = tuple[str, str]


class CaptureContinuityMonitor:
    """Carry each Camera Assignment's non-comparable streak across checkups."""

    def __init__(
        self,
        store: Store[dict[str, Any]],
        alert_monitor: AlertMonitor,
    ) -> None:
        """Initialise the monitor.

        Args:
            store: Pre-constructed ``Store`` targeting
                ``growspace_manager.capture_continuity``.
            alert_monitor: The durable Triage Alert record keeper. This module
                reports condition transitions to it and never resolves an
                alert on the grower's behalf.
        """
        self._store = store
        self._alert_monitor = alert_monitor
        self._streaks: dict[_AssignmentKey, CaptureContinuityState] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Load the streaks that were live when Home Assistant last stopped."""
        data = await self._store.async_load() or {}
        streaks: dict[_AssignmentKey, CaptureContinuityState] = {}
        for row in data.get("streaks", []):
            try:
                state = _deserialize(row)
            except KeyError, TypeError, ValueError:
                _LOGGER.warning("Discarding unreadable continuity streak %s", row)
                continue
            streaks[(state.growspace_id, state.camera_id)] = state
        self._streaks = streaks

    # ------------------------------------------------------------------
    # Capture intake
    # ------------------------------------------------------------------

    def active_streak(
        self, growspace_id: str, camera_id: str
    ) -> CaptureContinuityState | None:
        """Return the live streak for one Camera Assignment, if any."""
        return self._streaks.get((growspace_id, camera_id))

    async def async_record_capture(
        self,
        capture: VisionCapture,
        comparison: VisualComparisonResult | None,
    ) -> ContinuityTransition:
        """Fold one finished capture into its Camera Assignment's streak.

        The capture is normalised here rather than re-read from history, so a
        transport failure stays a failure and a manual capture stays inert.
        Returns the transition the condition made, which is ``NONE`` for the
        captures that only update an already active break.
        """
        key = (capture.growspace_id, capture.camera_id)
        decision = evaluate_capture_continuity(
            self._streaks.get(key),
            self._event(capture, comparison),
        )
        if decision.state is self._streaks.get(key):
            return decision.transition

        if decision.state is None:
            self._streaks.pop(key, None)
        else:
            self._streaks[key] = decision.state
        await self._async_save()

        if decision.transition is ContinuityTransition.CLEARED:
            await self._alert_monitor.async_clear_capture_continuity_break(
                capture.growspace_id,
                capture.camera_id,
                cleared_at=_parsed(capture.captured_at),
            )
        elif decision.state is not None and decision.state.condition_active:
            # Also on ContinuityTransition.NONE: a later capture in an active
            # streak updates the same alert's count, reason counts and latest
            # capture without creating a second one.
            await self._alert_monitor.async_record_capture_continuity_break(
                decision.state
            )
        return decision.transition

    # ------------------------------------------------------------------
    # Assignment intake
    # ------------------------------------------------------------------

    async def async_apply_camera_assignment(
        self,
        growspace_id: str,
        camera_ids: Iterable[str],
    ) -> None:
        """Retire the streaks of cameras this Growspace no longer holds.

        Called after a configuration change has been persisted, so a refused
        change cannot reset a streak. An active condition is cleared, which
        leaves its durable Triage Alert and any grower resolution untouched;
        the streak itself is dropped, so re-adding the camera — or adding it
        to another Growspace — starts from nothing.
        """
        assigned = set(camera_ids)
        retired = [
            key
            for key in self._streaks
            if key[0] == growspace_id and key[1] not in assigned
        ]
        if not retired:
            return
        cleared_at = dt_util.utcnow()
        for key in retired:
            state = self._streaks.pop(key)
            if state.condition_active:
                await self._alert_monitor.async_clear_capture_continuity_break(
                    growspace_id,
                    key[1],
                    cleared_at=cleared_at,
                )
        await self._async_save()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _event(
        self,
        capture: VisionCapture,
        comparison: VisualComparisonResult | None,
    ) -> CaptureContinuityEvent:
        """Normalise one capture into the evidence the state machine reads."""
        return CaptureContinuityEvent(
            growspace_id=capture.growspace_id,
            camera_id=capture.camera_id,
            capture_id=capture.capture_id,
            captured_at=_parsed(capture.captured_at),
            trigger_source=capture.trigger_source,
            quality_accepted=_QUALITY_ACCEPTED.get(capture.analysis_state),
            comparison_verdict=comparison.verdict if comparison else None,
        )

    async def _async_save(self) -> None:
        """Persist every live streak."""
        await self._store.async_save(
            {"streaks": [_serialize(state) for state in self._streaks.values()]}
        )


def _parsed(value: str) -> datetime:
    """Parse a stored ISO-8601 timestamp, refusing an unusable one loudly."""
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Unparsable capture timestamp {value!r}")
    return parsed


def _serialize(state: CaptureContinuityState) -> dict[str, Any]:
    """Convert one streak to its storage row."""
    return {
        "growspace_id": state.growspace_id,
        "camera_id": state.camera_id,
        "streak_started_at": state.streak_started_at.isoformat(),
        "consecutive_count": state.consecutive_count,
        "reason_counts": {reason.value: count for reason, count in state.reason_counts},
        "latest_capture_id": state.latest_capture_id,
        "latest_captured_at": state.latest_captured_at.isoformat(),
        "condition_active": state.condition_active,
    }


def _deserialize(row: dict[str, Any]) -> CaptureContinuityState:
    """Rebuild one streak from its storage row."""
    counts = row["reason_counts"]
    return CaptureContinuityState(
        growspace_id=row["growspace_id"],
        camera_id=row["camera_id"],
        streak_started_at=_parsed(row["streak_started_at"]),
        consecutive_count=int(row["consecutive_count"]),
        reason_counts=tuple(
            (reason, int(counts[reason.value]))
            for reason in ContinuityReason
            if reason.value in counts
        ),
        latest_capture_id=row["latest_capture_id"],
        latest_captured_at=_parsed(row["latest_captured_at"]),
        condition_active=bool(row["condition_active"]),
    )
