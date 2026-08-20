"""Event bus for growspace-related events in Home Assistant."""

from __future__ import annotations

from dataclasses import asdict
import logging
from typing import TYPE_CHECKING

from homeassistant.core import HomeAssistant

# Event constants - defined locally to avoid circular imports
EVENT_GROWSPACE_LOG_ENTRY = "growspace_manager_log_entry"
EVENT_GROWSPACE_UPDATED = "growspace_manager_updated"

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import GrowspaceEvent

_LOGGER = logging.getLogger(__name__)


class GrowspaceEventBus:
    """Manages event firing for growspace-related events to the Home Assistant event bus."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the event bus.

        Args:
            hass: The Home Assistant instance.
        """
        self._hass = hass

    def fire_log_entry(self, event: GrowspaceEvent) -> None:
        """Fire a growspace log entry event to the HA Event Bus.

        This implements native event sourcing for growspace events.

        Args:
            event: The growspace event to fire.
        """
        event_data = asdict(event)
        # asdict ensures primitive types for JSON serialization
        self._hass.bus.async_fire(EVENT_GROWSPACE_LOG_ENTRY, event_data)
        _LOGGER.debug("Fired growspace log entry event: %s", event.sensor_type)

    def fire_growspace_updated(self) -> None:
        """Fire a growspace updated event to notify listeners of data changes.

        This event signals that growspace data has been modified and
        components should refresh their state.
        """
        payload = {"event_type": EVENT_GROWSPACE_UPDATED, "data": {}}
        self._hass.bus.async_fire(EVENT_GROWSPACE_UPDATED, payload)
        _LOGGER.debug("Fired growspace updated event")
