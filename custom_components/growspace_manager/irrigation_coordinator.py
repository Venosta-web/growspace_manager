"""Coordinator for handling irrigation and drain schedules."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from functools import partial
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


class IrrigationCoordinator:
    """Manages irrigation and drain schedules for a specific growspace."""

    def __init__(
        self, hass: HomeAssistant, config_entry: ConfigEntry, growspace_id: str
    ):
        """Initialize the irrigation coordinator."""
        self.hass = hass
        self._config_entry = config_entry
        self._growspace_id = growspace_id
        self._listeners: list[callable] = []
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}

    async def async_setup(self):
        """Set up the irrigation schedules."""
        await self.async_update_listeners()

    async def async_update_listeners(self, *args):
        """Remove old listeners and create new ones based on current config."""
        self.async_cancel_listeners()

        options = self._config_entry.options.get("irrigation", {}).get(
            self._growspace_id, {}
        )
        irrigation_times = options.get("irrigation_times", [])
        drain_times = options.get("drain_times", [])

        for event in irrigation_times:
            self._schedule_event(event, "irrigation")

        for event in drain_times:
            self._schedule_event(event, "drain")

    def _schedule_event(self, event: dict[str, Any], event_type: str):
        """Helper to schedule a single irrigation or drain event."""
        try:
            time_str = event.get("time")
            if not isinstance(time_str, str):
                _LOGGER.warning(
                    "Skipping %s event with invalid time format: %s",
                    event_type,
                    time_str,
                )
                return

            time_obj = datetime.strptime(time_str, "%H:%M:%S").time()

            handler = partial(
                self._handle_event, event_type=event_type, event_data=event
            )

            self._listeners.append(
                async_track_time_change(
                    self.hass,
                    handler,
                    hour=time_obj.hour,
                    minute=time_obj.minute,
                    second=time_obj.second,
                )
            )
            _LOGGER.debug(
                "Scheduled %s event for growspace %s at %s",
                event_type,
                self._growspace_id,
                time_obj.isoformat(),
            )
        except (ValueError, KeyError) as e:
            _LOGGER.error(
                "Invalid %s time format for growspace %s in event %s: %s",
                event_type,
                self._growspace_id,
                event,
                e,
            )

    @callback
    def async_cancel_listeners(self):
        """Cancel all scheduled listeners."""
        for listener in self._listeners:
            listener()
        self._listeners = []

        for task in self._running_tasks.values():
            if task and not task.done():
                task.cancel()
        self._running_tasks = {}
        _LOGGER.debug(
            "Cancelled all irrigation listeners for growspace %s", self._growspace_id
        )

    async def _handle_event(
        self, now: datetime, *, event_type: str, event_data: dict[str, Any]
    ):
        """Handle a scheduled event."""
        if (
            event_type in self._running_tasks
            and self._running_tasks[event_type]
            and not self._running_tasks[event_type].done()
        ):
            _LOGGER.warning(
                "Cancelling previous %s event for growspace %s as a new one is starting.",
                event_type,
                self._growspace_id,
            )
            self._running_tasks[event_type].cancel()

        options = self._config_entry.options.get("irrigation", {}).get(
            self._growspace_id, {}
        )
        pump_entity = options.get(f"{event_type}_pump_entity")
        duration = event_data.get("duration") or options.get(f"{event_type}_duration")

        if not pump_entity or not duration:
            _LOGGER.warning(
                "%s event for growspace %s is not fully configured. Missing entity or duration.",
                event_type.capitalize(),
                self._growspace_id,
            )
            return

        task = self.hass.async_create_task(
            self._run_pump_cycle(event_type, pump_entity, int(duration), event_data)
        )
        self._running_tasks[event_type] = task

    async def _run_pump_cycle(
        self,
        event_type: str,
        pump_entity: str,
        duration: int,
        event_data: dict[str, Any],
    ):
        """Run the on-off cycle for a pump and send notifications."""
        try:
            _LOGGER.info(
                "Starting %s for %s (entity: %s), running for %s seconds.",
                event_type,
                self._growspace_id,
                pump_entity,
                duration,
            )
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": pump_entity}, blocking=True
            )

            # Send notification
            coordinator = self.hass.data[DOMAIN][self._config_entry.entry_id][
                "coordinator"
            ]
            growspace = coordinator.growspaces.get(self._growspace_id)
            if growspace and growspace.notification_target:
                time_str = event_data.get("time", "Unknown Time")
                message = (
                    f"{event_type.capitalize()} Event Started at {time_str}, running for {duration} seconds."
                )
                title = f"Growspace: {growspace.name}"

                await self.hass.services.async_call(
                    "notify",
                    growspace.notification_target,
                    {"message": message, "title": title},
                    blocking=False,
                )

            await asyncio.sleep(duration)

        except asyncio.CancelledError:
            _LOGGER.info(
                "%s event for %s (entity: %s) was cancelled.",
                event_type.capitalize(),
                self._growspace_id,
                pump_entity,
            )
        except Exception as e:
            _LOGGER.error(
                "Error during %s cycle for %s (entity: %s): %s",
                event_type,
                self._growspace_id,
                pump_entity,
                e,
            )
        finally:
            _LOGGER.info(
                "Stopping %s for %s (entity: %s).",
                event_type,
                self._growspace_id,
                pump_entity,
            )
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": pump_entity}, blocking=True
            )
            if event_type in self._running_tasks:
                self._running_tasks.pop(event_type)
