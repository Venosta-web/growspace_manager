"""Durable ownership of one camera assignment's Capture Continuity Break.

The Vision Checkup scheduler hands finished captures here and the Alert
Monitor keeps the durable Triage Alert; everything between the two — turning a
capture into the evidence ADR 0044 recognises, carrying the streak across
checkups and restarts, and retiring it when the camera stops being assigned —
belongs to this module. The streak decision itself stays in the pure
``domain/capture_continuity.py`` state machine, which this module is the only
runtime caller of.

The unit of ownership is a **Camera Assignment**: one camera assigned to one
Growspace. Two growspaces holding the same camera keep two streaks that never
see each other's evidence, and un-assigning a camera retires its streak, so a
later assignment starts from nothing.

**The Vision Evidence Store is the authority for streak state.** Every capture
is durable there before it reaches this module, so on start each current
assignment's streak is rebuilt by replaying *all* of that assignment's retained
captures through the same normalisation and state machine live intake uses.
Nothing caps the replay and nothing reads an image file, so image retention
cannot shorten a streak. The Triage Alert Inbox is reconciled to the result,
never read from.

What this module stores itself (``growspace_manager.capture_continuity``) is
only what evidence cannot say::

    {
        "assignments": [
            {
                "growspace_id": "<id>",
                "camera_id": "camera.canopy",
                "evidence_after": {"captured_at": "<ISO>", "capture_id": "<id>"},
                "processed_through": {"captured_at": "<ISO>", "capture_id": "<id>"}
            },
            ...
        ]
    }

``evidence_after`` is where the assignment began: captures of the same
growspace and camera at or before it belong to an earlier assignment, so a
returning camera — or a recreated growspace with the same id — cannot inherit
them. ``null`` adopts every retained capture: an upgrade adopts what the
camera already has, and a camera with nothing on record has nothing to exclude.
``processed_through`` is how far live intake got. An activation at or before it
was already seen, so recovery reports it as **historical**; one after it was
persisted by a checkup that never finished processing, and is still **new**.

A file without ``assignments`` — no file at all, or the streak rows an earlier
version stored — is an upgrade: every configured assignment adopts its retained
evidence, and everything that evidence activated is historical.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.util import dt as dt_util

from .domain.capture_continuity import (
    CaptureContinuityDecision,
    CaptureContinuityEvent,
    CaptureContinuityState,
    ContinuityTransition,
    evaluate_capture_continuity,
)
from .models.vision_evidence import AnalysisState, CaptureMarker

if TYPE_CHECKING:
    from homeassistant.helpers.storage import Store

    from .alert_monitor import AlertMonitor
    from .continuity_notifier import ContinuityNotifier
    from .data_access.vision_evidence_store import VisionEvidenceStore
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


class ActivationOrigin(StrEnum):
    """Whether an activation is news to the grower or was already known."""

    NEW = "new"
    HISTORICAL = "historical"


@dataclass(frozen=True, slots=True, kw_only=True)
class ContinuityActivation:
    """One activated Capture Continuity Break and whether it is news.

    ``activation_id`` is the capture that began the streak, so it is the same
    for a live activation and for the one recovery rebuilds from evidence.
    Delivery work reads ``origin`` to tell a genuinely new activation from one
    a restart or an upgrade merely rediscovered.
    """

    activation_id: str
    growspace_id: str
    camera_id: str
    activated_at: datetime
    origin: ActivationOrigin


@dataclass(slots=True, kw_only=True)
class _Assignment:
    """What evidence cannot say about one Camera Assignment."""

    evidence_after: CaptureMarker | None
    processed_through: CaptureMarker | None

    def owns(self, marker: CaptureMarker) -> bool:
        """Whether a capture belongs to this assignment."""
        return self.evidence_after is None or marker > self.evidence_after

    def processed(self, marker: CaptureMarker) -> bool:
        """Whether live intake has already folded a capture in."""
        return self.processed_through is not None and marker <= self.processed_through


@dataclass(frozen=True, slots=True, kw_only=True)
class _Replayed:
    """A streak rebuilt from evidence, with the capture that activated it."""

    state: CaptureContinuityState | None
    activated_by: CaptureMarker | None = None
    activated_at: datetime | None = None


class CaptureContinuityMonitor:
    """Carry each Camera Assignment's non-comparable streak across checkups."""

    def __init__(
        self,
        store: Store[dict[str, Any]],
        alert_monitor: AlertMonitor,
        evidence_store: VisionEvidenceStore | None,
        notifier: ContinuityNotifier,
    ) -> None:
        """Initialise the monitor.

        Args:
            store: Pre-constructed ``Store`` targeting
                ``growspace_manager.capture_continuity``.
            alert_monitor: The durable Triage Alert record keeper. This module
                reports condition transitions to it and never resolves an
                alert on the grower's behalf.
            evidence_store: The Vision Evidence Store streaks are recovered
                from, or ``None`` when it failed to open. Without it no
                checkup can run, so there is nothing to recover or record.
            notifier: Announces each genuinely new activation to the grower.
                It is started here, once recovery has settled which
                activations are historical.
        """
        self._store = store
        self._alert_monitor = alert_monitor
        self._evidence = evidence_store
        self._notifier = notifier
        self._assignments: dict[_AssignmentKey, _Assignment] = {}
        self._streaks: dict[_AssignmentKey, CaptureContinuityState] = {}
        self._activations: dict[_AssignmentKey, ContinuityActivation] = {}

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self, assignments: Mapping[str, Iterable[str]]) -> None:
        """Recover every current assignment's streak from durable evidence.

        ``assignments`` maps each configured Growspace to the cameras it holds;
        a stored assignment missing from it is retired, and its active
        condition cleared. Must run before the first checkup is scheduled. It
        starts notification delivery itself, last, so that which activations
        are historical is settled before anything could announce one.
        """
        if self._evidence is None:
            _LOGGER.debug("No Vision Evidence Store; continuity recovery skipped")
            await self._notifier.async_start(())
            return
        data = await self._store.async_load() or {}
        upgrading = "assignments" not in data
        stored = {} if upgrading else _load_assignments(data["assignments"])

        recovered: list[tuple[CaptureContinuityState, datetime]] = []
        for key in _assignment_keys(assignments):
            assignment = stored.get(key) or await self._open_assignment(
                key, adopt=upgrading
            )
            self._assignments[key] = assignment
            evidence = await self._evidence.async_get_capture_evidence(
                *key, after=assignment.evidence_after
            )
            if upgrading and evidence:
                # Whatever an upgrade finds was either already in front of the
                # grower or never announced at all; neither is news now.
                assignment.processed_through = CaptureMarker.of(evidence[-1][0])
            replayed = _replay(evidence)
            if replayed.state is None:
                continue
            self._streaks[key] = replayed.state
            if replayed.activated_by is None or replayed.activated_at is None:
                continue
            self._activations[key] = _activation(
                replayed.state,
                replayed.activated_at,
                ActivationOrigin.HISTORICAL
                if assignment.processed(replayed.activated_by)
                else ActivationOrigin.NEW,
            )
            recovered.append((replayed.state, replayed.activated_at))

        await self._alert_monitor.async_reconcile_capture_continuity(
            recovered, cleared_at=dt_util.utcnow()
        )
        await self._async_save()
        await self._notifier.async_start(self._activations.values())

    # ------------------------------------------------------------------
    # Capture intake
    # ------------------------------------------------------------------

    def active_streak(
        self, growspace_id: str, camera_id: str
    ) -> CaptureContinuityState | None:
        """Return the live streak for one Camera Assignment, if any."""
        return self._streaks.get((growspace_id, camera_id))

    def activation(
        self, growspace_id: str, camera_id: str
    ) -> ContinuityActivation | None:
        """Return the active condition of one Camera Assignment, if any."""
        return self._activations.get((growspace_id, camera_id))

    async def async_record_capture(
        self,
        capture: VisionCapture,
        comparison: VisualComparisonResult | None,
    ) -> ContinuityTransition:
        """Fold one finished capture into its Camera Assignment's streak.

        The capture is normalised here rather than re-read from history, so a
        transport failure stays a failure and a manual capture stays inert.
        A capture of a camera this Growspace no longer holds — one that was in
        flight when the assignment changed — and a capture already folded in
        are both ignored. Returns the transition the condition made, which is
        ``NONE`` for the captures that only update an already active break.
        """
        key = (capture.growspace_id, capture.camera_id)
        marker = CaptureMarker.of(capture)
        assignment = self._assignments.get(key)
        if assignment is None or not assignment.owns(marker):
            _LOGGER.debug(
                "Capture %s is outside any current Camera Assignment",
                capture.capture_id,
            )
            return ContinuityTransition.NONE
        if assignment.processed(marker):
            return ContinuityTransition.NONE

        event = continuity_event(capture, comparison)
        previous = self._streaks.get(key)
        decision = evaluate_capture_continuity(previous, event)
        if decision.state is not previous:
            await self._async_report(key, event, decision)

        # Only after the alert and its delivery record: a crash before this
        # line leaves the capture unprocessed, so recovery still treats what
        # it activated as new and announces it if nothing recorded it yet.
        assignment.processed_through = marker
        await self._async_save()
        return decision.transition

    async def _async_report(
        self,
        key: _AssignmentKey,
        event: CaptureContinuityEvent,
        decision: CaptureContinuityDecision,
    ) -> None:
        """Hold a streak that moved and report its condition to the Alert Monitor."""
        if decision.state is None:
            self._streaks.pop(key)
        else:
            self._streaks[key] = decision.state

        if decision.transition is ContinuityTransition.CLEARED:
            self._activations.pop(key, None)
            await self._alert_monitor.async_clear_capture_continuity_break(
                *key, cleared_at=event.captured_at
            )
        elif decision.state is not None and decision.state.condition_active:
            if decision.transition is ContinuityTransition.ACTIVATED:
                self._activations[key] = _activation(
                    decision.state, event.captured_at, ActivationOrigin.NEW
                )
            # Also on ContinuityTransition.NONE: a later capture in an active
            # streak updates the same alert's count, reason counts and latest
            # capture without creating a second one.
            await self._alert_monitor.async_record_capture_continuity_break(
                decision.state
            )
            if decision.transition is ContinuityTransition.ACTIVATED:
                await self._notifier.async_announce(self._activations[key])

    # ------------------------------------------------------------------
    # Assignment intake
    # ------------------------------------------------------------------

    async def async_apply_camera_assignment(
        self,
        growspace_id: str,
        camera_ids: Iterable[str],
    ) -> None:
        """Bring one Growspace's Camera Assignments in line with its cameras.

        Called after a configuration change has been persisted, so a refused
        change cannot reset a streak. A retired assignment's active condition
        is cleared, which leaves its durable Triage Alert and any grower
        resolution untouched, and its streak is dropped. A new assignment
        begins after the newest capture already on record for that camera in
        this Growspace, so re-adding the camera — or adding it to another
        Growspace — starts from nothing.
        """
        assigned = set(camera_ids)
        retired = [
            key
            for key in self._assignments
            if key[0] == growspace_id and key[1] not in assigned
        ]
        added = [
            (growspace_id, camera_id)
            for camera_id in sorted(assigned)
            if (growspace_id, camera_id) not in self._assignments
        ]
        if not retired and not added:
            return
        cleared_at = dt_util.utcnow()
        for key in retired:
            del self._assignments[key]
            self._activations.pop(key, None)
            state = self._streaks.pop(key, None)
            if state is not None and state.condition_active:
                await self._alert_monitor.async_clear_capture_continuity_break(
                    growspace_id,
                    key[1],
                    cleared_at=cleared_at,
                )
        for key in added:
            self._assignments[key] = await self._open_assignment(key, adopt=False)
        await self._async_save()

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _open_assignment(
        self, key: _AssignmentKey, *, adopt: bool
    ) -> _Assignment:
        """Begin a Camera Assignment, adopting retained evidence or not."""
        if adopt:
            return _Assignment(evidence_after=None, processed_through=None)
        if self._evidence is None:
            # What is on record cannot be read, so the boundary is now: an
            # empty identity sorts before every capture taken from here on.
            return _Assignment(
                evidence_after=CaptureMarker(
                    captured_at=dt_util.utcnow().isoformat(), capture_id=""
                ),
                processed_through=None,
            )
        # With nothing on record there is nothing to exclude.
        return _Assignment(
            evidence_after=await self._evidence.async_get_latest_capture_marker(*key),
            processed_through=None,
        )

    async def _async_save(self) -> None:
        """Persist every current Camera Assignment."""
        await self._store.async_save(
            {
                "assignments": [
                    {
                        "growspace_id": key[0],
                        "camera_id": key[1],
                        "evidence_after": _marker_row(assignment.evidence_after),
                        "processed_through": _marker_row(assignment.processed_through),
                    }
                    for key, assignment in self._assignments.items()
                ]
            }
        )


def continuity_event(
    capture: VisionCapture,
    comparison: VisualComparisonResult | None,
) -> CaptureContinuityEvent:
    """Normalise one capture into the evidence the state machine reads.

    Live intake and recovery both call this, so a replayed capture is
    classified exactly as it was when its checkup ran.
    """
    return CaptureContinuityEvent(
        growspace_id=capture.growspace_id,
        camera_id=capture.camera_id,
        capture_id=capture.capture_id,
        captured_at=_parsed(capture.captured_at),
        trigger_source=capture.trigger_source,
        quality_accepted=_QUALITY_ACCEPTED.get(capture.analysis_state),
        comparison_verdict=comparison.verdict if comparison else None,
    )


def _replay(
    evidence: Sequence[tuple[VisionCapture, VisualComparisonResult | None]],
) -> _Replayed:
    """Fold retained evidence through the state machine in capture order."""
    replayed = _Replayed(state=None)
    for capture, comparison in evidence:
        event = continuity_event(capture, comparison)
        decision = evaluate_capture_continuity(replayed.state, event)
        if decision.transition is ContinuityTransition.ACTIVATED:
            replayed = _Replayed(
                state=decision.state,
                activated_by=CaptureMarker.of(capture),
                activated_at=event.captured_at,
            )
        elif decision.state is None:
            replayed = _Replayed(state=None)
        else:
            replayed = _Replayed(
                state=decision.state,
                activated_by=replayed.activated_by,
                activated_at=replayed.activated_at,
            )
    return replayed


def _activation(
    state: CaptureContinuityState,
    activated_at: datetime,
    origin: ActivationOrigin,
) -> ContinuityActivation:
    return ContinuityActivation(
        activation_id=state.streak_started_capture_id,
        growspace_id=state.growspace_id,
        camera_id=state.camera_id,
        activated_at=activated_at,
        origin=origin,
    )


def _assignment_keys(
    assignments: Mapping[str, Iterable[str]],
) -> list[_AssignmentKey]:
    return [
        (growspace_id, camera_id)
        for growspace_id, camera_ids in assignments.items()
        for camera_id in dict.fromkeys(camera_ids)
    ]


def _load_assignments(rows: Any) -> dict[_AssignmentKey, _Assignment]:
    """Read stored assignments, discarding only a row that cannot be read.

    A discarded row costs only its own assignment, which recovery reopens as
    a fresh one.
    """
    assignments: dict[_AssignmentKey, _Assignment] = {}
    for row in rows:
        try:
            key = (str(row["growspace_id"]), str(row["camera_id"]))
            assignments[key] = _Assignment(
                evidence_after=_marker(row["evidence_after"]),
                processed_through=_marker(row["processed_through"]),
            )
        except KeyError, TypeError:
            _LOGGER.warning("Discarding unreadable continuity assignment %s", row)
    return assignments


def _marker(row: Mapping[str, Any] | None) -> CaptureMarker | None:
    if row is None:
        return None
    return CaptureMarker(
        captured_at=str(row["captured_at"]), capture_id=str(row["capture_id"])
    )


def _marker_row(marker: CaptureMarker | None) -> dict[str, str] | None:
    if marker is None:
        return None
    return {"captured_at": marker.captured_at, "capture_id": marker.capture_id}


def _parsed(value: str) -> datetime:
    """Parse a stored ISO-8601 timestamp, refusing an unusable one loudly."""
    parsed = dt_util.parse_datetime(value)
    if parsed is None:
        raise ValueError(f"Unparsable capture timestamp {value!r}")
    return parsed
