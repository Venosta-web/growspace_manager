"""Light Cycle Tracker for Growspace Manager."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class LightCycleTracker:
    """Tracks daily lights off→on transitions and records detected_lights_on_time."""

    def __init__(
        self,
        hass: HomeAssistant,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the LightCycleTracker."""
        self.hass = hass
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_listeners: list[Any] = []
        self._last_states: dict[str, bool | None] = {}

    def _is_active(self) -> bool:
        growspace = self.main_coordinator.growspaces.get(self.growspace_id)
        if not growspace:
            return False
        strategy = getattr(growspace, "irrigation_strategy", None)
        if not strategy:
            return False
        env = getattr(growspace, "environment_config", None)
        light_sensors = getattr(env, "light_sensors", []) if env else []
        return (
            strategy.enabled
            and strategy.auto_light_tracking
            and bool(light_sensors)
        )

    def _light_sensors(self) -> list[str]:
        growspace = self.main_coordinator.growspaces.get(self.growspace_id)
        if not growspace:
            return []
        env = getattr(growspace, "environment_config", None)
        return list(getattr(env, "light_sensors", []) if env else [])

    def _is_sensor_on(self, entity_id: str, state_str: str, domain: str) -> bool | None:
        """Return True/False for on/off; None if unavailable/unknown."""
        if state_str in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        if domain == "sensor":
            try:
                return float(state_str) > 0
            except ValueError:
                return None
        return state_str == "on"

    async def async_setup(self) -> None:
        """Start listening if preconditions are met."""
        if not self._is_active():
            return
        sensors = self._light_sensors()
        self._remove_listeners.append(
            async_track_state_change_event(self.hass, sensors, self._on_sensor_change)
        )
        for sensor in sensors:
            self._last_states[sensor] = None

    async def _on_sensor_change(self, event: Any) -> None:
        entity_id: str = event.data["entity_id"]
        old_state_obj = event.data.get("old_state")
        new_state_obj = event.data.get("new_state")

        if not new_state_obj or not self._is_active():
            return

        domain = new_state_obj.domain
        old_val = (
            self._is_sensor_on(entity_id, old_state_obj.state, domain)
            if old_state_obj
            else self._last_states.get(entity_id)
        )
        new_val = self._is_sensor_on(entity_id, new_state_obj.state, domain)

        self._last_states[entity_id] = new_val

        if old_val is False and new_val is True:
            await self._record_lights_on()

    async def _record_lights_on(self) -> None:
        growspace = self.main_coordinator.growspaces.get(self.growspace_id)
        if not growspace:
            return
        strategy = getattr(growspace, "irrigation_strategy", None)
        if not strategy:
            return
        detected = dt_util.now().time().strftime("%H:%M:%S")
        strategy.detected_lights_on_time = detected
        _LOGGER.debug(
            "Light Cycle Tracker: detected lights-on at %s for growspace %s",
            detected,
            self.growspace_id,
        )
        await self.main_coordinator.async_commit()

    def unload(self) -> None:
        """Remove all listeners."""
        for remove in self._remove_listeners:
            remove()
        self._remove_listeners.clear()
