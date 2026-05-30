"""Trend analysis service for Growspace Manager sensors."""

from __future__ import annotations

from datetime import timedelta
import itertools
import logging
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.dt import utcnow

from .exceptions import GrowspaceError

_LOGGER = logging.getLogger(__name__)


def get_recorder_instance(hass: HomeAssistant):
    """Get the recorder instance (deferred import)."""
    from homeassistant.helpers.recorder import get_instance  # noqa: PLC0415
    return get_instance(hass)


class TrendAnalyzer:
    """Helper class to analyze sensor trends."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the trend analyzer."""
        self.hass = hass

    async def async_analyze_sensors_trends(
        self, sensor_ids: list[str], duration_minutes: int, threshold: float
    ) -> dict[str, dict[str, Any]]:
        """Analyze the trend of multiple sensors' history in a single DB query."""
        if not sensor_ids:
            return {}

        start_time = utcnow() - timedelta(minutes=duration_minutes)
        end_time = utcnow()
        results = {}

        try:
            from homeassistant.components.recorder import history  # noqa: PLC0415

            # OPTIMIZATION: Fetch ALL sensors in ONE executor job (Single DB Query)
            history_dict = await get_recorder_instance(
                self.hass
            ).async_add_executor_job(
                lambda: history.get_significant_states(
                    self.hass,
                    start_time,
                    end_time,
                    sensor_ids,
                    include_start_time_state=True,
                )
            )

            # Process results in memory (CPU bound, fast)
            for sensor_id in sensor_ids:
                states = history_dict.get(sensor_id, [])
                numeric_states = []

                for s in states:
                    if not isinstance(s, State):
                        continue
                    if s.state in [STATE_UNKNOWN, STATE_UNAVAILABLE, None, ""]:
                        continue
                    try:
                        numeric_states.append(float(s.state))
                    except (ValueError, TypeError):
                        continue

                # Calculate trend
                trend = self._calculate_trend_direction(numeric_states)
                crossed = (
                    all(val > threshold for val in numeric_states)
                    if numeric_states
                    else False
                )

                results[sensor_id] = {"trend": trend, "crossed_threshold": crossed}

        except (AttributeError, KeyError, ValueError, ServiceValidationError, GrowspaceError):
            _LOGGER.exception("Error analyzing bulk sensor history")
            return {
                sid: {"trend": "unknown", "crossed_threshold": False}
                for sid in sensor_ids
            }
        else:
            return results

    async def async_analyze_sensor_trend(
        self, sensor_id: str, duration_minutes: int, threshold: float
    ) -> dict[str, Any]:
        """Analyze the trend of a sensor's history to detect rising or falling patterns."""
        result = await self.async_analyze_sensors_trends(
            [sensor_id], duration_minutes, threshold
        )
        return result.get(sensor_id, {"trend": "unknown", "crossed_threshold": False})

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
