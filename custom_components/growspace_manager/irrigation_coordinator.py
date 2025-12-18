"""Coordinator for handling irrigation and drain schedules."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC
from collections.abc import Callable
from datetime import datetime
from functools import partial
from typing import TYPE_CHECKING, Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util.dt import utcnow

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from .models import Growspace, GrowspaceEvent, IrrigationConfig

_LOGGER = logging.getLogger(__name__)


class BaseIrrigationCoordinator(ABC):
    """Base class for irrigation coordinators."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the base irrigation coordinator."""
        self.hass = hass
        self._config_entry = config_entry
        self._growspace_id = growspace_id
        self._main_coordinator = main_coordinator
        self._listeners: list[Callable] = []
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}

    @property
    def growspace(self) -> Growspace:
        """Return the growspace object."""
        return self._main_coordinator.growspaces[self._growspace_id]

    async def async_request_refresh(self) -> None:
        """Refresh listeners when configuration changes.

        Subclasses can override this if they need specific refresh logic.
        """
        pass

    async def async_setup(self) -> None:
        """Set up the coordinator."""
        pass

    async def async_unload(self) -> None:
        """Unload the coordinator and stop listeners."""
        self.async_cancel_listeners()

    @callback
    def async_cancel_listeners(self) -> None:
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

    def _get_sensor_value(self, entity_id: str) -> float | None:
        """Get float value from sensor state."""
        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable"):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None


class IrrigationCoordinator(BaseIrrigationCoordinator):
    """Manages irrigation and drain schedules for a specific growspace."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the irrigation coordinator."""
        super().__init__(hass, config_entry, growspace_id, main_coordinator)

    def get_default_duration(self, event_type: str) -> int | None:
        """Get the default duration for a given event type."""
        try:
            # Use getattr for dynamic field access on dataclass
            return getattr(
                self.growspace.irrigation_config, f"{event_type}_duration", None
            )
        except (KeyError, AttributeError):
            return None

    @override
    async def async_request_refresh(self) -> None:
        """Refresh listeners when configuration changes."""
        await self.async_update_listeners()

    async def _save_and_reload(self, reload_listeners: bool = True) -> None:
        """Save changes to storage and reload listeners."""
        # Save to custom storage via main coordinator
        await self._main_coordinator.async_save()

        # Notify listeners of update
        self._main_coordinator.async_set_updated_data(self._main_coordinator.data)

        # Reload the irrigation listeners with new schedule
        if reload_listeners:
            await self.async_update_listeners()

    async def async_set_settings(self, new_settings: dict[str, Any]) -> None:
        """Update the irrigation settings for the growspace."""
        # Update settings in growspace irrigation_config dataclass
        for key, value in new_settings.items():
            if hasattr(self.growspace.irrigation_config, key):
                setattr(self.growspace.irrigation_config, key, value)
            else:
                _LOGGER.warning("Unknown irrigation setting: %s", key)

        _LOGGER.debug(
            "Updating irrigation settings for %s with: %s",
            self._growspace_id,
            new_settings,
        )

        # Persist the changes
        await self._save_and_reload()

    async def async_add_schedule_item(
        self, schedule_key: str, time_str: str, duration: int | None
    ) -> None:
        """Add a time entry to an irrigation or drain schedule."""
        if not time_str:
            raise ValueError("Time cannot be empty")

        if len(time_str) == 5:
            time_str = f"{time_str}:00"

        if not hasattr(self.growspace.irrigation_config, schedule_key):
            _LOGGER.error("Invalid schedule key %s", schedule_key)
            return

        # Get current list
        current_schedule: list[dict] = getattr(
            self.growspace.irrigation_config, schedule_key
        )

        # Check if item with same time already exists
        existing_item = next(
            (item for item in current_schedule if item.get("time") == time_str),
            None,
        )

        if existing_item:
            # Update existing item
            existing_item["duration"] = duration
            _LOGGER.info(
                "Updated %s in %s for growspace %s. Duration set to %s",
                time_str,
                schedule_key,
                self._growspace_id,
                duration,
            )
            # Reference copy trick not strictly needed for dataclasses if we mutate the list
            # inside the object, unless we want to trigger some setter change logic.
            # But let's keep the pattern of creating a new list to be safe.
            new_list = list(current_schedule)
            # Re-find index to update in new list? Or since dicts are mutable references...
            # The existing_item is a ref to the dict in the list.
            # So creating a new list with same dicts means existing_item update is reflected.

            # Explicitly setting the attribute to the new list
            setattr(self.growspace.irrigation_config, schedule_key, new_list)
        else:
            # Add new schedule item
            new_list = list(current_schedule)
            new_list.append({"time": time_str, "duration": duration})
            setattr(self.growspace.irrigation_config, schedule_key, new_list)

            _LOGGER.info(
                "Added %s to %s for growspace %s. Schedule now has %d items",
                {"time": time_str, "duration": duration},
                schedule_key,
                self._growspace_id,
                len(new_list),
            )

        # Persist the changes
        await self._save_and_reload()

    async def async_remove_schedule_item(
        self, schedule_key: str, time_str: str
    ) -> None:
        """Remove all matching time entries from a schedule."""
        if not time_str:
            raise ValueError("Time cannot be empty")

        try:
            if not hasattr(self.growspace.irrigation_config, schedule_key):
                raise KeyError(schedule_key)

            schedule = getattr(self.growspace.irrigation_config, schedule_key)
            items_before = len(schedule)

            # Filter out matching times
            new_schedule = [item for item in schedule if item.get("time") != time_str]
            setattr(self.growspace.irrigation_config, schedule_key, new_schedule)

            items_after = len(new_schedule)

            if items_before == items_after:
                _LOGGER.warning(
                    "Time %s not found in %s for growspace %s. No items removed",
                    time_str,
                    schedule_key,
                    self._growspace_id,
                )
                return

            _LOGGER.info(
                "Removed %d item(s) with time %s from %s for growspace %s",
                items_before - items_after,
                time_str,
                schedule_key,
                self._growspace_id,
            )

            # Persist the changes
            await self._save_and_reload()

        except KeyError:
            _LOGGER.warning(
                "Cannot remove item: schedule '%s' not found for growspace %s",
                schedule_key,
                self._growspace_id,
            )

    @override
    async def async_setup(self):
        """Set up the irrigation schedules."""
        # MIGRATION: Check if we have legacy options in config entry but empty growspace config
        # Check if irrigation settings are effectively empty (default)
        if self.growspace.irrigation_config == IrrigationConfig():
            legacy_options = self._config_entry.options.get("irrigation", {}).get(
                self._growspace_id, {}
            )
            if legacy_options:
                _LOGGER.info(
                    "Migrating irrigation settings for %s from ConfigEntry to Storage",
                    self._growspace_id,
                )
                # Use from_dict to migrate logic if needed, or simple direct mapping
                # Since BaseModel handles from_dict, we use that.
                self.growspace.irrigation_config = IrrigationConfig.from_dict(
                    dict(legacy_options)
                )
                await self._main_coordinator.async_save()

        # Load schedules without triggering updates
        await self.async_update_listeners()

    async def async_update_listeners(self, *args):
        """Remove old listeners and create new ones based on current config."""
        self.async_cancel_listeners()

        # Get irrigation options from growspace object
        options = self.growspace.irrigation_config

        # Make defensive copies to avoid reference issues
        irrigation_times = list(options.irrigation_times)
        drain_times = list(options.drain_times)

        _LOGGER.debug(
            "Setting up listeners for growspace %s: %d irrigation times, %d drain times",
            self._growspace_id,
            len(irrigation_times),
            len(drain_times),
        )

        # Log the actual schedule data for debugging
        if irrigation_times:
            _LOGGER.debug("Irrigation schedule: %s", irrigation_times)
        if drain_times:
            _LOGGER.debug("Drain schedule: %s", drain_times)

        # Deduplicate events based on time
        unique_irrigation_times = {
            event["time"]: event for event in irrigation_times
        }.values()
        unique_drain_times = {event["time"]: event for event in drain_times}.values()

        for event in unique_irrigation_times:
            self._schedule_event(event, "irrigation")

        for event in unique_drain_times:
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

            if len(time_str) == 5:
                time_str = f"{time_str}:00"

            time_obj = datetime.strptime(time_str, "%H:%M:%S").time()

            handler = partial(
                self._handle_event, event_type=event_type, event_data=event
            )

            listener = async_track_time_change(
                self.hass,
                handler,
                hour=time_obj.hour,
                minute=time_obj.minute,
                second=time_obj.second,
            )

            self._listeners.append(listener)

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
                "Cancelling previous %s event for growspace %s as a new one is starting",
                event_type,
                self._growspace_id,
            )
            self._running_tasks[event_type].cancel()

        options = self.growspace.irrigation_config

        # Use getattr to fetch config entities dynamically
        pump_entity = getattr(options, f"{event_type}_pump_entity", None)
        default_duration = getattr(options, f"{event_type}_duration", None)

        duration = event_data.get("duration") or default_duration

        if not pump_entity or not duration:
            _LOGGER.warning(
                "%s event for growspace %s is not fully configured. Missing entity or duration",
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
        start_dt = None
        try:
            start_dt = utcnow()
            _LOGGER.info(
                "Starting %s for %s (entity: %s), running for %s seconds",
                event_type,
                self._growspace_id,
                pump_entity,
                duration,
            )
            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": pump_entity}, blocking=True
            )

            # Send notification
            coordinator = self._config_entry.runtime_data
            growspace = coordinator.growspaces.get(self._growspace_id)
            if growspace and growspace.notification_target:
                time_str = event_data.get("time", "Unknown Time")
                message = f"{event_type.capitalize()} Event Started at {time_str}, running for {duration} seconds."
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
                "%s event for %s (entity: %s) was cancelled",
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
            try:
                end_dt = utcnow()
                # Ensure start_dt is defined
                if start_dt:
                    duration_sec = (end_dt - start_dt).total_seconds()
                    # Create and add the event
                    event = GrowspaceEvent(
                        sensor_type="irrigation"
                        if event_type == "irrigation"
                        else "drain",
                        growspace_id=self._growspace_id,
                        start_time=start_dt.isoformat(),
                        end_time=end_dt.isoformat(),
                        duration_sec=int(duration_sec),
                        severity=1.0,
                        category="irrigation",
                        reasons=[f"{event_type.capitalize()} cycle completed"],
                    )
                    self._main_coordinator.add_event(self._growspace_id, event)
            except Exception as e:
                _LOGGER.error("Failed to log %s event: %s", event_type, e)

            _LOGGER.info(
                "Stopping %s for %s (entity: %s)",
                event_type,
                self._growspace_id,
                pump_entity,
            )
            await self.hass.services.async_call(
                "switch", "turn_off", {"entity_id": pump_entity}, blocking=True
            )
            if event_type in self._running_tasks:
                self._running_tasks.pop(event_type)
