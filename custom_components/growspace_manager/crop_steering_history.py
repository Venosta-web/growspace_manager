"""Crop steering history analysis for Growspace Manager sensors."""

from __future__ import annotations

from datetime import datetime, time, timedelta
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.util.dt import as_utc, now, utcnow

if TYPE_CHECKING:
    from .models import Growspace

_LOGGER = logging.getLogger(__name__)

_BUCKET_SIZE = timedelta(minutes=5)
_ANCHOR_LEAD = timedelta(hours=2)


def get_recorder_instance(hass: HomeAssistant):
    """Get the recorder instance (deferred import)."""
    from homeassistant.helpers.recorder import get_instance  # noqa: PLC0415

    return get_instance(hass)


def _parse_lights_on_time(value: str) -> time:
    """Parse a lights-on time string in either HH:MM:SS or HH:MM format."""
    try:
        return datetime.strptime(value, "%H:%M:%S").time()
    except ValueError:
        return datetime.strptime(value, "%H:%M").time()


class CropSteeringHistoryAnalyzer:
    """Helper class to build crop steering history chart data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the analyzer."""
        self.hass = hass

    async def async_get_history(self, growspace: Growspace) -> dict[str, Any]:
        """Build the crop steering history response for a growspace."""
        strategy = growspace.irrigation_strategy
        lights_on_source = strategy.detected_lights_on_time or strategy.lights_on_time
        lights_on_local = datetime.combine(
            now().date(), _parse_lights_on_time(lights_on_source), tzinfo=now().tzinfo
        )
        lights_on = as_utc(lights_on_local)
        anchor = lights_on - _ANCHOR_LEAD
        end_time = utcnow()

        env = growspace.environment_config
        soil_sensor_ids = (
            [env.soil_moisture_sensor] if env.soil_moisture_sensor else []
        )

        sensor_ids = [*soil_sensor_ids, *env.pore_ec_sensors, *env.bulk_ec_sensors]
        history = await self._async_fetch_history(sensor_ids, anchor, end_time)

        result: dict[str, Any] = {"lights_on": lights_on.isoformat()}
        result["soil_moisture"] = self._bucket_sensor(
            history.get(env.soil_moisture_sensor, [])
            if env.soil_moisture_sensor
            else [],
            anchor,
            end_time,
        )
        if env.pore_ec_sensors:
            result["pore_ec"] = self._bucket_sensor_group(
                env.pore_ec_sensors, history, anchor, end_time
            )
        if env.bulk_ec_sensors:
            result["bulk_ec"] = self._bucket_sensor_group(
                env.bulk_ec_sensors, history, anchor, end_time
            )
        return result

    def _bucket_sensor_group(
        self,
        sensor_ids: list[str],
        history: dict[str, list[State]],
        anchor: datetime,
        end_time: datetime,
    ) -> list[dict[str, Any]]:
        """Bucket each sensor independently, then average per-bucket across sensors."""
        per_sensor_buckets = [
            self._bucket_sensor(history.get(sensor_id, []), anchor, end_time)
            for sensor_id in sensor_ids
        ]

        buckets: list[dict[str, Any]] = []
        for bucket_index, reference in enumerate(per_sensor_buckets[0]):
            values = [
                sensor_buckets[bucket_index]["value"]
                for sensor_buckets in per_sensor_buckets
                if sensor_buckets[bucket_index]["value"] is not None
            ]
            buckets.append(
                {
                    "timestamp": reference["timestamp"],
                    "value": sum(values) / len(values) if values else None,
                }
            )
        return buckets

    async def _async_fetch_history(
        self, sensor_ids: list[str], start_time: datetime, end_time: datetime
    ) -> dict[str, list[State]]:
        """Fetch significant states for all sensors in a single batched query."""
        if not sensor_ids:
            return {}

        from homeassistant.components.recorder import history  # noqa: PLC0415

        result: dict[str, list[State]] = await get_recorder_instance(
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
        return result

    def _bucket_sensor(
        self, states: list[State], anchor: datetime, end_time: datetime
    ) -> list[dict[str, Any]]:
        """Bucket a single sensor's numeric readings into anchor-relative buckets."""
        readings = [
            (state.last_updated, value)
            for state in states
            if (value := self._numeric_state(state)) is not None
        ]

        buckets: list[dict[str, Any]] = []
        bucket_start = anchor
        while bucket_start < end_time:
            bucket_end = bucket_start + _BUCKET_SIZE
            values = [
                value
                for timestamp, value in readings
                if bucket_start <= timestamp < bucket_end
            ]
            buckets.append(
                {
                    "timestamp": bucket_start.isoformat(),
                    "value": sum(values) / len(values) if values else None,
                }
            )
            bucket_start = bucket_end
        return buckets

    @staticmethod
    def _numeric_state(state: State) -> float | None:
        """Convert a state's value to a float, or None if not numeric."""
        if state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE, None, ""):
            return None
        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None
