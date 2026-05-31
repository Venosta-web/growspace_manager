"""Tank level monitor — event-driven low-level tank notifications."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.helpers.event import async_track_state_change_event

from .const import NotificationTier
from .presentation import EntityQueries

if TYPE_CHECKING:
    from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant

    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class TankLevelMonitor:
    """Subscribes to tank sensor state changes and fires low-level notifications."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: GrowspaceCoordinator,
        notify: Callable[..., Coroutine[Any, Any, None]],
    ) -> None:
        """Initialise the monitor."""
        self.hass = hass
        self.coordinator = coordinator
        self._notify = notify
        self._unsubs: list[CALLBACK_TYPE] = []
        self._entity_queries = EntityQueries(hass)

    async def async_start(self) -> None:
        """Subscribe to state changes for all configured tank sensors."""
        for growspace in self.coordinator.growspaces.values():
            if (
                not growspace.environment_config
                or not growspace.environment_config.irrigation_tanks
            ):
                continue
            for tank in growspace.environment_config.irrigation_tanks:
                self._subscribe_tank(growspace.id, growspace.name, tank)

    def _subscribe_tank(self, growspace_id: str, growspace_name: str, tank: Any) -> None:
        """Register a state-change listener for a single tank sensor."""
        entity_queries = self._entity_queries

        async def _on_state_change(event: Event) -> None:
            new_state = event.data.get("new_state")
            if new_state is None:
                return
            level = entity_queries.parse_tank_level(new_state.state)
            if level is not None and level <= tank.warning_level:
                await self._notify(
                    growspace_id,
                    title="⚠️ Low Irrigation Tank Level",
                    message=(
                        f"{tank.name} in {growspace_name} is at {level:.0f}%"
                        f" (warning at {tank.warning_level:.0f}%)"
                    ),
                    tier=NotificationTier.CRITICAL,
                )

        unsub = async_track_state_change_event(
            self.hass, tank.sensor_entity, _on_state_change
        )
        self._unsubs.append(unsub)

    def async_stop(self) -> None:
        """Cancel all subscriptions."""
        for unsub in self._unsubs:
            unsub()
        self._unsubs.clear()
