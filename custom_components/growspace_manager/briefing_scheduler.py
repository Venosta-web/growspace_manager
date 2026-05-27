"""AI Briefing Scheduler for Growspace Manager.

Manages automated briefing generation through three trigger paths:

- **Interval**: fires every ``briefing_interval_minutes`` (default 30, range 5–1440).
- **Entity event**: fires on state change to ``on`` for any entity in
  ``briefing_trigger_entities``; rapid successive changes are debounced with a
  5-second delay.
- **Manual**: ``async_get_briefing(force_refresh=True)`` bypasses the cache and
  generates a fresh briefing immediately.

Generated briefings are persisted to ``growspace_manager.ai_briefing`` via HA
Storage so they survive restarts.  When AI is unavailable the briefing is
produced from Bayesian binary-sensor data and ``ai_available`` is ``False``.
"""

from __future__ import annotations

from datetime import timedelta
import logging
import time
from typing import TYPE_CHECKING, Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.storage import Store

from .const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_BRIEFING_INTERVAL_MINUTES,
    CONF_BRIEFING_TRIGGER_ENTITIES,
    DEFAULT_BRIEFING_INTERVAL_MINUTES,
    DOMAIN,
    STORAGE_KEY_AI_BRIEFING,
    STORAGE_VERSION,
)

if TYPE_CHECKING:
    import asyncio

    from homeassistant.core import CALLBACK_TYPE, Event

    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

_DEBOUNCE_SECONDS = 5.0


class BriefingScheduler:
    """Schedules and executes AI briefing generation for Growspace Manager."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialise the scheduler."""
        self.hass = hass
        self.coordinator = coordinator
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_AI_BRIEFING
        )
        self._unsubs: list[CALLBACK_TYPE] = []
        self._debounce_handle: asyncio.TimerHandle | None = None
        self._cached_briefing: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _ai_settings(self) -> dict[str, Any]:
        return self.coordinator.options.get("ai_settings", {})

    def _get_interval_minutes(self) -> int:
        return int(
            self._ai_settings().get(
                CONF_BRIEFING_INTERVAL_MINUTES, DEFAULT_BRIEFING_INTERVAL_MINUTES
            )
        )

    def _get_trigger_entities(self) -> list[str]:
        return self._ai_settings().get(CONF_BRIEFING_TRIGGER_ENTITIES) or []

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Register interval and entity-event listeners.

        Listeners are stored in ``_unsubs`` so ``async_stop`` can cancel them.
        """
        interval = timedelta(minutes=self._get_interval_minutes())
        unsub_interval = async_track_time_interval(
            self.hass,
            self._async_on_interval,
            interval,
        )
        self._unsubs.append(unsub_interval)

        trigger_entities = self._get_trigger_entities()
        if trigger_entities:
            unsub_entities = async_track_state_change_event(
                self.hass,
                trigger_entities,
                self._async_on_entity_change,
            )
            self._unsubs.append(unsub_entities)

    def async_stop(self) -> None:
        """Cancel all registered listeners and any pending debounce timer."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()

        if self._debounce_handle is not None:
            self._debounce_handle.cancel()
            self._debounce_handle = None

    # ------------------------------------------------------------------
    # Trigger callbacks
    # ------------------------------------------------------------------

    async def _async_on_interval(self, _now: Any) -> None:
        """Generate and cache a fresh briefing on each interval tick."""
        await self._async_generate_and_cache()

    @callback
    def _async_on_entity_change(self, event: Event) -> None:
        """Handle entity state-change events.

        Only fires for transitions to ``on``; rapid changes are debounced so that
        a burst of events triggers at most one generation, 5 seconds after the
        last one.
        """
        new_state = event.data.get("new_state")
        if new_state is None or new_state.state != "on":
            return

        if self._debounce_handle is not None:
            self._debounce_handle.cancel()

        self._debounce_handle = self.hass.loop.call_later(
            _DEBOUNCE_SECONDS,
            lambda: self.hass.async_create_task(self._async_generate_and_cache()),
        )

    # ------------------------------------------------------------------
    # Briefing generation
    # ------------------------------------------------------------------

    async def _async_generate_and_cache(self) -> None:
        """Generate a briefing, update the in-memory cache, and persist it."""
        briefing = await self._generate_briefing()
        self._cached_briefing = briefing
        await self._store.async_save(briefing)

    async def _generate_briefing(self) -> dict[str, Any]:
        """Build a briefing dict, falling back to Bayesian data if AI is unavailable."""
        generated_at = time.time()
        kpis = self._collect_kpis()

        ai_settings = self._ai_settings()
        ai_enabled = ai_settings.get(CONF_AI_ENABLED, False)
        agent_id = ai_settings.get(CONF_ASSISTANT_ID)

        if ai_enabled and agent_id:
            try:
                summary_text, recommendations = await self._generate_ai_content(
                    agent_id, kpis
                )
                return {
                    "generated_at": generated_at,
                    "summary_text": summary_text,
                    "kpis": kpis,
                    "recommendations": recommendations,
                    "ai_available": True,
                }
            except Exception:
                _LOGGER.warning(
                    "AI briefing generation failed, falling back to Bayesian report"
                )

        summary_text = self._generate_bayesian_summary()
        return {
            "generated_at": generated_at,
            "summary_text": summary_text,
            "kpis": kpis,
            "recommendations": [],
            "ai_available": False,
        }

    async def _generate_ai_content(
        self, agent_id: str, kpis: list[dict[str, Any]]
    ) -> tuple[str, list[dict[str, Any]]]:
        """Generate briefing text and recommendations using the conversation agent."""
        from homeassistant.components import conversation  # noqa: PLC0415
        from homeassistant.core import Context  # noqa: PLC0415

        kpi_by_label = {k["label"]: k["value"] for k in kpis}
        growspace_names = [gs.name for gs in self.coordinator.growspaces.values()]
        context_summary = (
            f"Active growspaces: {', '.join(growspace_names) or 'none'}. "
            f"KPIs — avg VPD: {kpi_by_label.get('Avg VPD', 'n/a')}, "
            f"water use: {kpi_by_label.get('Water Use', 'n/a')} L, "
            f"open issues: {kpi_by_label.get('Open Issues', 0)}."
        )
        prompt = (
            "You are an expert cannabis cultivation assistant. "
            "Provide a brief status briefing (2–3 sentences) for the grower "
            "based on the current data, then list up to 3 actionable recommendations "
            "as JSON with fields 'text', 'impact' (high/medium/low), "
            "and 'suggested_action' (dict). "
            "Return format: SUMMARY: <text> RECOMMENDATIONS: <json array>\n\n"
            f"Current data:\n{context_summary}"
        )

        result = await conversation.async_converse(
            self.hass,
            text=prompt,
            conversation_id=None,
            context=Context(),
            agent_id=agent_id,
        )

        speech: str | None = None
        if (
            result
            and result.response
            and result.response.speech
            and result.response.speech.get("plain")
        ):
            speech = str(result.response.speech["plain"].get("speech", ""))

        if not speech:
            return self._generate_bayesian_summary(), []

        # Parse out summary and recommendations from the structured response
        import json  # noqa: PLC0415

        recommendations: list[dict[str, Any]] = []
        summary_text = speech

        if "RECOMMENDATIONS:" in speech:
            parts = speech.split("RECOMMENDATIONS:", 1)
            summary_text = parts[0].replace("SUMMARY:", "").strip()
            try:
                recommendations = json.loads(parts[1].strip())
            except json.JSONDecodeError, ValueError:
                recommendations = []
        elif "SUMMARY:" in speech:
            summary_text = speech.replace("SUMMARY:", "").strip()

        return summary_text, recommendations

    def _collect_kpis(self) -> list[dict[str, Any]]:
        """Collect KPI snapshot from coordinator state as a list of {label, value, unit?} objects."""
        vpd_readings: list[float] = []
        water_use_l: float = 0.0
        open_issues: int = 0

        for growspace in self.coordinator.growspaces.values():
            env_state = getattr(growspace, "environment_state", None)
            if env_state is not None:
                vpd = getattr(env_state, "vpd", None)
                if vpd is not None:
                    vpd_readings.append(float(vpd))

            water_usage = getattr(growspace, "water_usage", None)
            if water_usage is not None:
                water_use_l += float(getattr(water_usage, "total_water_l", 0.0))

        avg_vpd = (
            round(sum(vpd_readings) / len(vpd_readings), 2) if vpd_readings else None
        )

        alert_monitor = getattr(self.coordinator, "alert_monitor", None)
        if alert_monitor is not None:
            alerts = alert_monitor.get_alerts()
            open_issues = len([a for a in alerts if not a.get("resolved")])

        kpis: list[dict[str, Any]] = [
            {"label": "Open Issues", "value": open_issues},
        ]
        if avg_vpd is not None:
            kpis.append({"label": "Avg VPD", "value": avg_vpd, "unit": "kPa"})
        if water_use_l:
            kpis.append({"label": "Water Use", "value": round(water_use_l, 1), "unit": "L"})

        return kpis

    def _generate_bayesian_summary(self) -> str:
        """Build a plain-text status report from Bayesian binary-sensor states."""
        lines: list[str] = []

        for growspace in self.coordinator.growspaces.values():
            name = getattr(growspace, "name", growspace)
            bayesian = self._read_bayesian_states(getattr(growspace, "id", ""))
            issues: list[str] = []
            for key, label in (
                ("stress", "plant stress"),
                ("mold_risk", "mold risk"),
            ):
                data = bayesian.get(key, {})
                if data.get("active"):
                    reasons = data.get("reasons", [])
                    detail = f" ({'; '.join(reasons)})" if reasons else ""
                    issues.append(f"{label}{detail}")

            if issues:
                lines.append(f"{name}: {', '.join(issues)} detected.")
            else:
                optimal = bayesian.get("optimal", {})
                if optimal.get("active"):
                    lines.append(f"{name}: conditions optimal.")
                else:
                    lines.append(f"{name}: conditions normal.")

        if not lines:
            return "No active growspaces. System is idle."

        return " ".join(lines)

    def _read_bayesian_states(self, growspace_id: str) -> dict[str, Any]:
        """Read binary sensor states for a growspace from HA state machine."""
        result: dict[str, Any] = {}

        sensors_map = {
            "stress": f"binary_sensor.{DOMAIN}_{growspace_id}_stress",
            "mold_risk": f"binary_sensor.{DOMAIN}_{growspace_id}_mold_risk",
            "optimal": f"binary_sensor.{DOMAIN}_{growspace_id}_optimal",
        }

        for key, entity_id in sensors_map.items():
            state = self.hass.states.get(entity_id)
            if state is None:
                result[key] = {"active": False, "reasons": []}
                continue
            result[key] = {
                "active": state.state == "on",
                "reasons": state.attributes.get("reasons", []),
            }

        return result

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def async_get_briefing(self, force_refresh: bool = False) -> dict[str, Any]:
        """Return a briefing dict.

        - ``force_refresh=True``: bypass cache and generate fresh immediately.
        - otherwise: return in-memory cache → persisted store → generate fresh.
        """
        if force_refresh:
            await self._async_generate_and_cache()
            return self._cached_briefing  # type: ignore[return-value]

        if self._cached_briefing is None:
            stored = await self._store.async_load()
            if stored and isinstance(stored.get("kpis"), list):
                self._cached_briefing = stored
            else:
                await self._async_generate_and_cache()

        return self._cached_briefing  # type: ignore[return-value]
