"""Environment Reporter service for Growspace Manager."""

from __future__ import annotations

from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY
from homeassistant.components.recorder import history
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, HomeAssistant, State, callback
from homeassistant.helpers.event import (
    EventStateChangedData,
    async_track_state_change_event,
)
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class EnvironmentReporter:
    """Monitors light cycles and generates daily/nightly environmental reports."""

    def __init__(self, hass: HomeAssistant, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the reporter."""
        self.hass = hass
        self.coordinator = coordinator
        self._unsub_listeners: dict[str, Any] = {}
        # Track when the current state started (e.g. when lights turned ON)
        # Map: growspace_id -> datetime
        self._state_start_times: dict[str, datetime] = {}

    async def async_initialize(self) -> None:
        """Initialize listeners for all growspaces."""
        for growspace_id in self.coordinator.growspaces:
            await self._setup_growspace_listener(growspace_id)

    async def _setup_growspace_listener(self, growspace_id: str) -> None:
        """Set up light sensor listener for a specific growspace."""
        # Clean up existing listener if any
        if growspace_id in self._unsub_listeners:
            self._unsub_listeners[growspace_id]()
            del self._unsub_listeners[growspace_id]

        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace:
            return

        light_sensor = growspace.environment_config.light_sensor
        if not light_sensor:
            return

        _LOGGER.debug(
            "EnvironmentReporter: Monitoring %s for growspace %s",
            light_sensor,
            growspace.name,
        )

        # Initialize start time with current time if unknown (assumption)
        # Ideally we'd look back at history to find when it last changed, but
        # current time is a safe fallback to strictly avoid reporting on time
        # before the integration started monitoring.
        if growspace_id not in self._state_start_times:
            self._state_start_times[growspace_id] = dt_util.utcnow()

        @callback
        def _light_state_listener(event: Event[EventStateChangedData]) -> None:
            self.hass.async_create_task(
                self._handle_light_change(
                    growspace_id,
                    event.data.get("old_state"),
                    event.data.get("new_state"),
                )
            )

        self._unsub_listeners[growspace_id] = async_track_state_change_event(
            self.hass, [light_sensor], _light_state_listener
        )

    def _is_light_on(self, state_obj: State) -> bool:
        """Check if state represents an ON condition."""
        if state_obj.state == STATE_ON:
            return True
        if state_obj.state == STATE_OFF:
            return False
        try:
            # Handle numeric sensor (brightness or power) treated as light sensor
            return float(state_obj.state) > 0
        except (ValueError, TypeError):
            return False

    async def _handle_light_change(
        self, growspace_id: str, old_state: State | None, new_state: State | None
    ) -> None:
        """Handle light state change event."""
        if not old_state or not new_state:
            return

        if old_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        if new_state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return

        was_on = self._is_light_on(old_state)
        is_on = self._is_light_on(new_state)

        if was_on == is_on:
            return  # No logical state change (e.g. brightness change)

        # State has officially changed
        report_type = "day_report" if was_on else "night_report"
        start_time = self._state_start_times.get(growspace_id)
        end_time = dt_util.utcnow()

        # Update start time for the NEXT period
        self._state_start_times[growspace_id] = end_time

        if not start_time:
            # First transition seen, just tracking start time now
            return

        duration = end_time - start_time
        # Ignore very short cycles (e.g. < 30 mins) to avoid noise
        if duration < timedelta(minutes=30):
            _LOGGER.debug(
                "Skipping environmental report for %s: duration too short (%s)",
                growspace_id,
                duration,
            )
            return

        await self._generate_report(growspace_id, report_type, start_time, end_time)

    async def _get_sensor_stats(
        self, entity_id: str, start_time: datetime, end_time: datetime
    ) -> str | None:
        """Calculate average stats for a sensor during a period."""
        history_list = await self.hass.async_add_executor_job(
            history.state_changes_during_period,
            self.hass,
            start_time,
            end_time,
            entity_id,
        )

        states = history_list.get(entity_id, [])
        if not states:
            return None

        values = []
        for s in states:
            try:
                if s.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    values.append(float(s.state))
            except (ValueError, TypeError):
                continue

        if not values:
            return None

        avg_val = sum(values) / len(values)

        state_obj = self.hass.states.get(entity_id)
        unit = state_obj.attributes.get("unit_of_measurement", "") if state_obj else ""

        return f"{avg_val:.1f}{unit}"

    async def _generate_report(
        self,
        growspace_id: str,
        report_type: str,
        start_time: datetime,
        end_time: datetime,
    ) -> None:
        """Query history and generate the report event."""
        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace:
            return

        # Sensors to query
        env_config = growspace.environment_config
        sensors = {
            "Temperature": env_config.temperature_sensor,
            "Humidity": env_config.humidity_sensor,
            "VPD": env_config.vpd_sensor,
        }

        if not any(sensors.values()):
            return

        stats_summary = []

        for metric, entity_id in sensors.items():
            if not entity_id:
                continue

            stat_str = await self._get_sensor_stats(entity_id, start_time, end_time)
            if stat_str:
                stats_summary.append(f"{metric}: {stat_str}")

        if not stats_summary:
            return

        # Fire Event
        self.hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                "growspace_id": growspace_id,
                "category": "environmental_report",
                "sensor_type": report_type,
                "reasons": stats_summary,
                "severity": 0,
                "start_time": end_time.isoformat(),
                "timestamp": dt_util.now().isoformat(),
            },
        )
        _LOGGER.info(
            "Generated %s for growspace %s: %s",
            report_type,
            growspace.name,
            stats_summary,
        )

    def unload(self) -> None:
        """Unload the reporter and clear listeners."""
        for unsub in self._unsub_listeners.values():
            unsub()
        self._unsub_listeners.clear()
