"""Alert monitor for AI-detected stress and mold events.

Consumes Evaluation Snapshot inactive-to-active transitions and creates
persistent alert records.  An async background task subsequently enriches
each alert with AI reasoning; if AI is unavailable the record is kept with
Bayesian data only.

Storage layout (``growspace_manager.ai_alerts``)::

    {
        "alerts": [
            {
                "alert_id": "<uuid>",
                "growspace_id": "<id>",
                "alert_type": "stress" | "mold",
                "bayesian_reasons": ["..."],
                "bayesian_probability": 0.91,
                "ai_reasoning": "..." | null,
                "timestamp": "<ISO-8601>",
                "resolved": false,
                "resolution_notes": null | "..."
            },
            ...
        ]
    }

The list is capped at :attr:`AlertMonitor.MAX_ALERTS` entries; oldest entries
are evicted when the cap is exceeded — except a Capture Continuity Break whose
condition is still active, which is current rather than old. The Inbox is never
the authority for streak state: the Capture Continuity Monitor rebuilds that
from the Vision Evidence Store and reconciles the Inbox to it.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
import logging
from typing import TYPE_CHECKING, Any
import uuid

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import CONF_AI_AUTO_ALERTS, CONF_AI_ENABLED
from .domain.capture_continuity import CAPTURE_CONTINUITY_MESSAGE
from .notifications.evaluation_snapshot import EvaluationSnapshot

if TYPE_CHECKING:
    from datetime import datetime

    from .domain.capture_continuity import CaptureContinuityState

_LOGGER = logging.getLogger(__name__)

_SEVERITY_MAP: dict[str, str] = {
    "stress": "danger",
    "mold": "warning",
    "capture_continuity_break": "warning",
}


def _serialize_alert(alert: dict[str, Any]) -> dict[str, Any]:
    """Convert an internal storage alert dict to the public wire format.

    Renames fields, converts the ISO-8601 timestamp to a Unix epoch int, and
    injects a ``severity`` value derived from ``alert_type``.  The internal
    storage dict is never mutated.
    """
    ts_iso: str = alert["timestamp"]
    parsed_dt = dt_util.parse_datetime(ts_iso)
    unix_ts = int(parsed_dt.timestamp()) if parsed_dt is not None else 0

    serialized = {
        **{
            k: v
            for k, v in alert.items()
            if k
            not in {
                "alert_id",
                "alert_type",
                "timestamp",
                "resolution_notes",
                "activation_id",
            }
        },
        "id": alert["alert_id"],
        "type": alert["alert_type"],
        "severity": _SEVERITY_MAP.get(alert["alert_type"], "info"),
        "timestamp": unix_ts,
        "resolution_note": alert.get("resolution_notes"),
    }
    for field in ("streak_started_at", "latest_captured_at", "cleared_at"):
        if field not in alert:
            continue
        value = alert[field]
        parsed = dt_util.parse_datetime(value) if value is not None else None
        serialized[field] = int(parsed.timestamp()) if parsed is not None else None
    return serialized


class AlertMonitor:
    """Monitor evaluation transitions and persist AI alert records."""

    MAX_ALERTS: int = 500

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: Any,
        store: Store,
        ai_assistant_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Initialise the monitor.

        Args:
            hass: Home Assistant instance.
            coordinator: The GrowspaceCoordinator instance; used to read
                runtime options (``CONF_AI_ENABLED``, ``CONF_AI_AUTO_ALERTS``)
                at enrichment time.
            store: Pre-constructed ``homeassistant.helpers.storage.Store``
                targeting ``growspace_manager.ai_alerts``.
            ai_assistant_factory: Zero-argument callable that returns a
                ``GrowAssistant``-compatible object with an async
                ``generate_alert_message(growspace_id, alert_type, reasons)``
                method.  Pass ``None`` to skip AI enrichment.
        """
        self._hass = hass
        self._coordinator = coordinator
        self._store = store
        self._ai_assistant_factory = ai_assistant_factory
        self._alerts: list[dict[str, Any]] = []
        self._active_evaluations: set[tuple[str, str]] = set()

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_start(self) -> None:
        """Load persisted alerts."""
        data = await self._store.async_load() or {}
        self._alerts = list(data.get("alerts", []))

    # ------------------------------------------------------------------
    # Evaluation intake
    # ------------------------------------------------------------------

    @callback
    def report_evaluation(self, snapshot: EvaluationSnapshot) -> None:
        """Persist a Triage Alert on a stress or mold rising edge."""
        if snapshot.sensor_type not in ("stress", "mold"):
            return

        key = (snapshot.growspace_id, snapshot.sensor_type)
        if not snapshot.is_on:
            self._active_evaluations.discard(key)
            return

        if key in self._active_evaluations:
            return
        self._active_evaluations.add(key)

        reasons = [
            reason for _weight, reason in sorted(snapshot.reasons, reverse=True)[:5]
        ]
        self._hass.async_create_task(
            self.async_record_alert(
                snapshot.growspace_id,
                snapshot.sensor_type,
                reasons,
                snapshot.probability,
            ),
            f"record_triage_alert_{snapshot.growspace_id}_{snapshot.sensor_type}",
        )

    # ------------------------------------------------------------------
    # Core alert creation
    # ------------------------------------------------------------------

    async def async_record_alert(
        self,
        growspace_id: str,
        alert_type: str,
        reasons: list[str],
        probability: float,
    ) -> dict[str, Any]:
        """Create and persist an alert record.

        Synchronously writes the record with Bayesian data, then fires a
        background task to attempt AI enrichment.
        """
        alert: dict[str, Any] = {
            "alert_id": str(uuid.uuid4()),
            "growspace_id": growspace_id,
            "alert_type": alert_type,
            "bayesian_reasons": list(reasons),
            "bayesian_probability": probability,
            "ai_reasoning": None,
            "timestamp": dt_util.utcnow().isoformat(),
            "resolved": False,
            "resolution_notes": None,
        }

        self._alerts.append(alert)
        self._trim()

        await self._async_save()

        # Attempt async AI enrichment (failures are non-fatal)
        if self._ai_assistant_factory is not None:
            await self._async_enrich_with_ai(alert)

        return alert

    async def async_record_capture_continuity_break(
        self,
        state: CaptureContinuityState,
    ) -> dict[str, Any]:
        """Create one equipment Triage Alert per active continuity streak.

        A streak activates once, so its alert is found by the Camera Assignment
        and the activation it records. An active alert of the same assignment
        that records an *earlier* activation is a condition whose clear never
        arrived; it is closed rather than made to answer for the new streak.
        """
        activation_id = state.streak_started_capture_id
        for active_alert in reversed(self._alerts):
            if not _is_active_condition(
                active_alert, state.growspace_id, state.camera_id
            ):
                continue
            if active_alert.get("activation_id", activation_id) == activation_id:
                active_alert.update(_continuity_evidence(state))
                await self._async_save()
                return active_alert
            active_alert["condition_active"] = False
            active_alert["cleared_at"] = state.streak_started_at.isoformat()
            break

        alert = _continuity_alert(state, raised_at=state.latest_captured_at)
        self._alerts.append(alert)
        self._trim()
        await self._async_save()
        return alert

    async def async_reconcile_capture_continuity(
        self,
        active: Iterable[tuple[CaptureContinuityState, datetime]],
        *,
        cleared_at: datetime,
    ) -> None:
        """Make the Inbox agree with the conditions recovered from evidence.

        ``active`` holds every currently active streak with the moment it
        activated. Each one's alert has its derived evidence corrected in place
        — identity, raise time, grower resolution and notes are kept — and an
        alert recorded before activations had identity adopts the current one.
        An active condition with no alert gets exactly one, raised at its
        activation. Every other active condition, including one whose Camera
        Assignment no longer exists, is cleared. Nothing is created for a
        condition that has already cleared.
        """
        current = {
            (state.growspace_id, state.camera_id): (state, activated_at)
            for state, activated_at in active
        }
        reconciled: set[tuple[str, str]] = set()
        changed = False
        for alert in reversed(self._alerts):
            if not _is_continuity_condition(alert):
                continue
            key = (alert["growspace_id"], alert["camera_id"])
            recovered = current.get(key)
            if (
                recovered is not None
                and key not in reconciled
                and alert.get("activation_id", recovered[0].streak_started_capture_id)
                == recovered[0].streak_started_capture_id
            ):
                alert.update(_continuity_evidence(recovered[0]))
                reconciled.add(key)
            else:
                alert["condition_active"] = False
                alert["cleared_at"] = cleared_at.isoformat()
            changed = True
        for key, (state, activated_at) in current.items():
            if key in reconciled:
                continue
            self._alerts.append(_continuity_alert(state, raised_at=activated_at))
            changed = True
        if changed:
            self._trim()
            await self._async_save()

    async def async_clear_capture_continuity_break(
        self,
        growspace_id: str,
        camera_id: str,
        *,
        cleared_at: datetime,
    ) -> bool:
        """Clear one Camera Assignment's condition without acknowledging it.

        The durable Triage Alert and any grower resolution survive: only the
        condition status moves, so a short recovery — or the camera leaving
        this Growspace — cannot erase an equipment event before it is seen.
        """
        for alert in reversed(self._alerts):
            if _is_active_condition(alert, growspace_id, camera_id):
                alert["condition_active"] = False
                alert["cleared_at"] = cleared_at.isoformat()
                await self._async_save()
                return True
        return False

    # ------------------------------------------------------------------
    # AI enrichment
    # ------------------------------------------------------------------

    async def _async_enrich_with_ai(self, alert: dict[str, Any]) -> None:
        """Populate ``ai_reasoning`` via the injected AI assistant.

        Skipped when ``CONF_AI_ENABLED`` or ``CONF_AI_AUTO_ALERTS`` is off.
        Failures are logged as warnings; the alert record is **not** deleted.
        """
        options = self._coordinator.options
        if not options.get(CONF_AI_ENABLED, False):
            return
        if not options.get(CONF_AI_AUTO_ALERTS, False):
            return
        try:
            assistant = self._ai_assistant_factory()  # type: ignore[misc]
            ai_text: str = await assistant.generate_alert_message(
                alert["growspace_id"],
                alert["alert_type"],
                alert["bayesian_reasons"],
            )
            alert["ai_reasoning"] = ai_text
            await self._async_save()
        except Exception:  # noqa: BLE001
            _LOGGER.warning(
                "AI enrichment failed for alert %s (%s / %s). "
                "Persisting with Bayesian data only",
                alert["alert_id"],
                alert["growspace_id"],
                alert["alert_type"],
            )

    # ------------------------------------------------------------------
    # Query / mutation
    # ------------------------------------------------------------------

    def get_alerts(
        self,
        growspace_id: str | None = None,
        alert_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return alerts, optionally filtered.

        Args:
            growspace_id: If given, only return alerts for this growspace.
            alert_type: If given, only return ``"stress"`` or ``"mold"`` alerts.

        Returns:
            A list of alert dicts (same format as stored).
        """
        results = self._alerts
        if growspace_id is not None:
            results = [a for a in results if a["growspace_id"] == growspace_id]
        if alert_type is not None:
            results = [a for a in results if a["alert_type"] == alert_type]
        return [_serialize_alert(a) for a in results]

    async def resolve_alert(
        self,
        alert_id: str,
        notes: str | None = None,
    ) -> bool:
        """Mark an alert as resolved.

        Args:
            alert_id: UUID of the alert to resolve.
            notes: Optional resolution notes to attach.

        Returns:
            ``True`` if the alert was found and updated, ``False`` otherwise.
        """
        for alert in self._alerts:
            if alert["alert_id"] == alert_id:
                alert["resolved"] = True
                alert["resolution_notes"] = notes
                await self._async_save()
                return True
        return False

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _trim(self) -> None:
        """Evict the oldest alerts beyond the cap, never a live condition.

        A Capture Continuity Break whose condition is still active is current,
        not old: evicting it would leave the condition invisible and let its
        next capture raise the same activation as a new alert.
        """
        excess = len(self._alerts) - self.MAX_ALERTS
        if excess <= 0:
            return
        kept: list[dict[str, Any]] = []
        for alert in self._alerts:
            if excess > 0 and not _is_continuity_condition(alert):
                excess -= 1
                continue
            kept.append(alert)
        self._alerts = kept

    async def _async_save(self) -> None:
        """Persist the current alerts list to the Store."""
        await self._store.async_save({"alerts": self._alerts})


def _is_continuity_condition(alert: dict[str, Any]) -> bool:
    """Match any Capture Continuity Break whose condition is still active."""
    return bool(
        alert["alert_type"] == "capture_continuity_break" and alert["condition_active"]
    )


def _is_active_condition(
    alert: dict[str, Any],
    growspace_id: str,
    camera_id: str,
) -> bool:
    """Match the live condition of one camera's assignment to one growspace.

    Streak ownership is the pair, not the camera alone: one camera assigned to
    two growspaces keeps two conditions, and neither may answer for the other.
    """
    return (
        _is_continuity_condition(alert)
        and alert["growspace_id"] == growspace_id
        and alert["camera_id"] == camera_id
    )


def _continuity_alert(
    state: CaptureContinuityState, *, raised_at: datetime
) -> dict[str, Any]:
    """Build a new equipment Triage Alert for one activated streak."""
    return {
        "alert_id": str(uuid.uuid4()),
        "growspace_id": state.growspace_id,
        "alert_type": "capture_continuity_break",
        "title": "Capture continuity break",
        "description": CAPTURE_CONTINUITY_MESSAGE,
        **_continuity_evidence(state),
        "condition_active": True,
        "cleared_at": None,
        "timestamp": raised_at.isoformat(),
        "resolved": False,
        "resolution_notes": None,
    }


def _continuity_evidence(state: CaptureContinuityState) -> dict[str, Any]:
    """Serialize only equipment evidence, never Bayesian or AI fields.

    ``activation_id`` is internal: it lets recovery and a notifier recognise
    one activation, and never reaches the wire.
    """
    return {
        "activation_id": state.streak_started_capture_id,
        "camera_id": state.camera_id,
        "streak_started_at": state.streak_started_at.isoformat(),
        "consecutive_count": state.consecutive_count,
        "reason_counts": {reason.value: count for reason, count in state.reason_counts},
        "latest_capture_id": state.latest_capture_id,
        "latest_captured_at": state.latest_captured_at.isoformat(),
    }
