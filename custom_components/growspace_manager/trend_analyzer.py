"""Trend analysis service for Growspace Manager sensors."""

from __future__ import annotations

import itertools
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
            numeric_states = []
            for s in states:
                if not isinstance(s, State):
                    continue
                if s.state in [STATE_UNKNOWN, STATE_UNAVAILABLE, None, ""]:
                    continue
                try:
                    numeric_states.append((s.last_updated, float(s.state)))
                except (ValueError, TypeError):
                    # Skip states that cannot be converted to float
                    continue

            values = [val for _, val in numeric_states]
            trend = self._calculate_trend_direction(values)

            # Check if value was consistently above threshold
            crossed_threshold = all(value > threshold for value in values)

            return {"trend": trend, "crossed_threshold": crossed_threshold}

        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.error("Error analyzing sensor history for %s: %s", sensor_id, e)
            return {"trend": "unknown", "crossed_threshold": False}

    def _calculate_trend_direction(self, values: list[float]) -> str:
        """Calculate trend direction using pairwise comparison."""
        if len(values) < 2:
            return "stable"

        # Calculate deltas between consecutive points
        deltas = [y - x for x, y in itertools.pairwise(values)]
        net_change = sum(deltas)

        match net_change:
            case x if x > 0.01:
                return "rising"
            case x if x < -0.01:
                return "falling"
            case _:
                return "stable"
