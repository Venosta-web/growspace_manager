"""Day/night tracking from light sensors."""

from __future__ import annotations

import logging
import time

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
_UNAVAILABLE_WARN_SECONDS = 300


class DayNightTracker:
    """Tracks day/night state from light sensors with OR logic and fallback cache.

    Returns True when any light sensor reads as on, False when all read as off.
    When all sensors are unavailable, returns the last known state (defaulting to
    True) and warns after _UNAVAILABLE_WARN_SECONDS of continuous unavailability.
    """

    def __init__(self, growspace_id: str) -> None:
        """Initialize the day/night resolver for a single growspace."""
        self._growspace_id = growspace_id
        self._last_known_is_day: bool | None = None
        self._sensors_unavailable_since: float | None = None

    def determine(self, hass: HomeAssistant, light_sensors: list[str]) -> bool:
        """Return True if lights are on (OR logic across all sensors)."""
        if not light_sensors:
            return True

        any_valid = False
        any_on = False
        for sensor_id in light_sensors:
            state = hass.states.get(sensor_id)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                any_valid = True
                try:
                    if float(state.state) > 0:
                        any_on = True
                except ValueError:
                    if state.state == STATE_ON:
                        any_on = True

        if any_valid:
            self._last_known_is_day = any_on
            self._sensors_unavailable_since = None
            return any_on

        now = time.monotonic()
        if self._sensors_unavailable_since is None:
            self._sensors_unavailable_since = now
        elif now - self._sensors_unavailable_since >= _UNAVAILABLE_WARN_SECONDS:
            _LOGGER.warning(
                "All light sensors for growspace %s have been unavailable for over %d seconds; "
                "using last known day/night state",
                self._growspace_id,
                int(now - self._sensors_unavailable_since),
            )

        return self._last_known_is_day if self._last_known_is_day is not None else True
