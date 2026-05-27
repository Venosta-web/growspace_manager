"""Alert monitor for AI-detected stress and mold events.

Listens for off→on transitions on Bayesian binary sensors and creates
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
are evicted when the cap is exceeded.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
import uuid

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import ATTR_PROBABILITY, ATTR_REASONS

_LOGGER = logging.getLogger(__name__)


class AlertMonitor:
    """Monitors binary sensor state changes and persists AI alert records."""

    MAX_ALERTS: int = 500

    def __init__(
        self,
        hass: HomeAssistant,
        store: Store,
        ai_assistant_factory: Callable[[], Any] | None = None,
    ) -> None:
        """Initialise the monitor.

        Args:
            hass: Home Assistant instance.
            store: Pre-constructed ``homeassistant.helpers.storage.Store``
                targeting ``growspace_manager.ai_alerts``.
            ai_assistant_factory: Zero-argument callable that returns a
                ``GrowAssistant``-compatible object with an async
                ``generate_alert_message(growspace_id, alert_type, reasons)``
                method.  Pass ``None`` to skip AI enrichment.
        """
        self._hass = hass
        self._store = store
        self._ai_assistant_factory = ai_assistant_factory
        self._alerts: list[dict[str, Any]] = []
        # entity_id → (growspace_id, alert_type)
        self._watched: dict[str, tuple[str, str]] = {}
        self._cancel_listener: Callable[[], None] | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def async_setup(self) -> None:
        """Load persisted alerts and register state-change listener."""
        data = await self._store.async_load() or {}
        self._alerts = list(data.get("alerts", []))

        self._cancel_listener = self._hass.bus.async_listen(
            "state_changed", self._async_handle_state_change
        )

    @callback
    def async_unload(self) -> None:
        """Cancel the state-change listener."""
        if self._cancel_listener is not None:
            self._cancel_listener()
            self._cancel_listener = None

    # ------------------------------------------------------------------
    # Sensor registration
    # ------------------------------------------------------------------

    def register_sensor(
        self,
        entity_id: str,
        growspace_id: str,
        alert_type: str,
    ) -> None:
        """Register a binary sensor entity to watch for off→on transitions.

        Only ``stress`` and ``mold`` sensor types generate alerts.
        """
        if alert_type in ("stress", "mold"):
            self._watched[entity_id] = (growspace_id, alert_type)

    # ------------------------------------------------------------------
    # State-change handler
    # ------------------------------------------------------------------

    async def _async_handle_state_change(self, event: Any) -> None:
        """Handle a ``state_changed`` HA bus event.

        Creates an alert only when a *registered* sensor transitions from
        any non-on state to ``"on"`` (rising edge).
        """
        entity_id: str = event.data.get("entity_id", "")
        if entity_id not in self._watched:
            return

        new_state = event.data.get("new_state")
        old_state = event.data.get("old_state")

        if new_state is None or new_state.state != "on":
            return

        if old_state is not None and old_state.state == "on":
            return  # Not a rising edge

        growspace_id, alert_type = self._watched[entity_id]
        reasons: list[str] = new_state.attributes.get(ATTR_REASONS) or []
        probability: float = float(new_state.attributes.get(ATTR_PROBABILITY, 0.0))

        await self.async_record_alert(growspace_id, alert_type, reasons, probability)

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

        # Enforce cap — evict oldest
        if len(self._alerts) > self.MAX_ALERTS:
            self._alerts = self._alerts[-self.MAX_ALERTS :]

        await self._async_save()

        # Attempt async AI enrichment (failures are non-fatal)
        if self._ai_assistant_factory is not None:
            await self._async_enrich_with_ai(alert)

        return alert

    # ------------------------------------------------------------------
    # AI enrichment
    # ------------------------------------------------------------------

    async def _async_enrich_with_ai(self, alert: dict[str, Any]) -> None:
        """Populate ``ai_reasoning`` via the injected AI assistant.

        Failures are logged as warnings; the alert record is **not** deleted.
        """
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
        return results

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

    async def _async_save(self) -> None:
        """Persist the current alerts list to the Store."""
        await self._store.async_save({"alerts": self._alerts})
