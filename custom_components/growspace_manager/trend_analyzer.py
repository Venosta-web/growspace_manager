"""Trend analysis service for Growspace Manager sensors."""
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.recorder import history
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers.recorder import get_instance as get_recorder_instance
from homeassistant.util.dt import utcnow

_LOGGER = logging.getLogger(__name__)


class TrendAnalyzer:
    """Helper class to analyze sensor trends."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the trend analyzer."""
        self.hass = hass

    async def async_analyze_sensor_trend(
        self, sensor_id: str, duration_minutes: int, threshold: float
    ) -> dict[str, Any]:
        """Analyze the trend of a sensor's history to detect rising or falling patterns."""
        start_time = utcnow() - timedelta(minutes=duration_minutes)
        end_time = utcnow()

        try:
            history_list = await get_recorder_instance(
                self.hass
            ).async_add_executor_job(
                lambda: history.get_significant_states(
                    self.hass,
                    start_time,
                    end_time,
                    [sensor_id],
                    include_start_time_state=True,
                )
            )

            states = history_list.get(sensor_id, [])
            numeric_states = [
                (s.last_updated, float(s.state))
                for s in states
                if isinstance(s, State)
                and s.state not in [STATE_UNKNOWN, STATE_UNAVAILABLE]
                and s.state is not None
            ]

            if len(numeric_states) < 2:
                return {"trend": "stable", "crossed_threshold": False}

            # Trend calculation (simplified: change between first and last value)
            start_value = numeric_states[0][1]
            end_value = numeric_states[-1][1]
            change = end_value - start_value

            trend = "stable"
            if change > 0.01:
                trend = "rising"
            elif change < -0.01:
                trend = "falling"

            # Check if value was consistently above threshold
            crossed_threshold = all(value > threshold for _, value in numeric_states)

            return {"trend": trend, "crossed_threshold": crossed_threshold}

        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.error("Error analyzing sensor history for %s: %s", sensor_id, e)
            return {"trend": "unknown", "crossed_threshold": False}
