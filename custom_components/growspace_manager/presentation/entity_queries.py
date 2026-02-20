"""Entity registry queries and sensor value lookups.

This module contains all Home Assistant-specific entity operations.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from ..const import DOMAIN
from ..utils import generate_growspace_overview_unique_id

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class EntityQueries:
    """Handles entity registry lookups and sensor value queries."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize entity queries.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self._entity_registry = er.async_get(hass)

    def lookup_plant_entity_id(self, plant_id: str) -> str | None:
        """Look up the entity ID for a plant sensor.

        Args:
            plant_id: The plant's unique ID.

        Returns:
            Entity ID string or None if not found.
        """
        unique_id = f"{DOMAIN}_{plant_id}"
        return self._entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)

    def lookup_overview_entity_id(self, growspace_id: str) -> str | None:
        """Look up the entity ID for a growspace overview sensor.

        Args:
            growspace_id: The growspace's unique ID.

        Returns:
            Entity ID string or None if not found.
        """
        unique_id = generate_growspace_overview_unique_id(growspace_id)
        entity_id = self._entity_registry.async_get_entity_id("sensor", DOMAIN, unique_id)

        # Fallback for special growspaces (legacy support)
        if not entity_id and growspace_id in ("mother", "clone", "dry", "cure"):
            slug = slugify(growspace_id)
            entity_id = f"sensor.{slug}"

        return entity_id

    def get_sensor_value(self, sensor_id: str | None) -> float | None:
        """Safely get the numeric value from a sensor's state.

        Args:
            sensor_id: The entity ID of the sensor.

        Returns:
            Float value or None if unavailable/invalid.
        """
        if not sensor_id:
            return None

        state = self.hass.states.get(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    def get_sensor_state(self, sensor_id: str | None) -> str | None:
        """Get the raw state string from a sensor.

        Args:
            sensor_id: The entity ID of the sensor.

        Returns:
            State string or None if unavailable.
        """
        if not sensor_id:
            return None

        state = self.hass.states.get(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None

        return state.state

    def parse_tank_level(self, state_value: str | None) -> float | None:
        """Parse tank level from sensor state.

        Handles formats like:
        - "50.0 %"
        - "50,0 %" (European format)
        - "50" (plain number)

        Args:
            state_value: The sensor state value.

        Returns:
            Float percentage or None if invalid.
        """
        if not state_value:
            return None

        try:
            # Remove % sign and whitespace
            cleaned = state_value.replace("%", "").strip()
            # Replace European comma with period
            cleaned = cleaned.replace(",", ".")
            return float(cleaned)
        except (ValueError, TypeError, AttributeError):
            # If it's already a number or conversion failed
            try:
                return float(state_value)
            except (ValueError, TypeError):
                return None
