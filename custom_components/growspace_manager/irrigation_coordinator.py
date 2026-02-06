"""Coordinator for handling irrigation and drain schedules."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime
from functools import partial
import logging
from typing import TYPE_CHECKING, Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util.dt import now as dt_now, utcnow

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from .models import Growspace, GrowspaceEvent

_LOGGER = logging.getLogger(__name__)


class BaseIrrigationCoordinator:
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
        self._listeners: list[Callable[[], None]] = []
        self._running_tasks: dict[str, asyncio.Task[Any]] = {}
        self._active_events: dict[str, dict[str, Any]] = {}

    @property
    def active_events(self) -> dict[str, dict[str, Any]]:
        """Return currently active events (start_time, duration)."""
        return self._active_events

    @property
    def growspace(self) -> Growspace:
        """Return the growspace object."""
        return self._main_coordinator.growspaces[self._growspace_id]

    async def async_request_refresh(self) -> None:
        """Refresh listeners when configuration changes.

        Subclasses can override this if they need specific refresh logic.
        """

    async def async_setup(self) -> None:
        """Set up the coordinator."""

    async def async_unload(self) -> None:
        """Unload the coordinator and stop listeners."""
        self.async_cancel_listeners(cancel_tasks=True)

    async def _async_send_cycle_notification(
        self, event_type: str, duration: int, event_data: Mapping[str, Any]
    ) -> None:
        """Send a notification for the start of a pump cycle."""
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

    @callback
    def async_cancel_listeners(self, cancel_tasks: bool = True) -> None:
        """Cancel all scheduled listeners."""
        for listener in self._listeners:
            listener()
        self._listeners = []

        if cancel_tasks:
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

    # Removed useless __init__ delegation

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
        # Refresh the growspace data (invalidates cache and updates data property)
        await self._main_coordinator.async_refresh_growspace_data(self._growspace_id)

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
        current_schedule: list[dict[str, Any]] = getattr(
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

        if not hasattr(self.growspace.irrigation_config, schedule_key):
            _LOGGER.warning(
                "Cannot remove item: schedule '%s' not found for growspace %s",
                schedule_key,
                self._growspace_id,
            )
            return

        try:
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

        except Exception:
            _LOGGER.exception(
                "Unexpected error removing schedule item from %s", schedule_key
            )

    @override
    async def async_setup(self) -> None:
        """Set up the irrigation schedules."""

        # Load schedules without triggering updates
        await self.async_update_listeners()

    async def async_update_listeners(self, *args: Any) -> None:
        """Remove old listeners and create new ones based on current config."""
        self.async_cancel_listeners(cancel_tasks=False)

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

        # Deduplicate events based on time, skipping malformed records
        unique_irrigation_times = {
            t: event
            for event in irrigation_times
            if (t := event.get("time")) is not None
        }.values()
        unique_drain_times = {
            t: event for event in drain_times if (t := event.get("time")) is not None
        }.values()

        for event in unique_irrigation_times:
            self._schedule_event(event, "irrigation")

        for event in unique_drain_times:
            self._schedule_event(event, "drain")

    def _schedule_event(self, event: Mapping[str, Any], event_type: str) -> None:
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
        self, now: datetime, *, event_type: str, event_data: Mapping[str, Any]
    ) -> None:
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
        event_data: Mapping[str, Any],
    ) -> None:
        """Run the on-off cycle for a pump and send notifications."""
        # Track active event for frontend animation
        self._active_events[event_type] = {
            "start": dt_now().isoformat(),
            "duration": duration,
        }

        start_dt = None
        moisture_before = None

        try:
            # Capture moisture before starting
            if self.growspace.environment_config.soil_moisture_sensor:
                moisture_before = self._get_sensor_value(
                    self.growspace.environment_config.soil_moisture_sensor
                )

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

            await self._async_send_cycle_notification(event_type, duration, event_data)

            await asyncio.sleep(duration)

        except asyncio.CancelledError:
            _LOGGER.info(
                "%s event for %s (entity: %s) was cancelled",
                event_type.capitalize(),
                self._growspace_id,
                pump_entity,
            )
        except Exception as e:  # noqa: BLE001
            _LOGGER.error(
                "Error during %s cycle for %s (entity: %s): %s",
                event_type,
                self._growspace_id,
                pump_entity,
                e,
            )
        finally:
            try:
                # Clear active event
                self._active_events.pop(event_type, None)

                end_dt = utcnow()
                # Ensure start_dt is defined
                if start_dt:
                    duration_sec = (end_dt - start_dt).total_seconds()

                    # Capture moisture after
                    moisture_after = None
                    if self.growspace.environment_config.soil_moisture_sensor:
                        moisture_after = self._get_sensor_value(
                            self.growspace.environment_config.soil_moisture_sensor
                        )

                    # Build reasons
                    reasons = [f"{event_type.capitalize()} cycle completed"]

                    # Add Duration
                    reasons.append(f"Duration: {int(duration_sec)}s")

                    # Add Moisture Data
                    if moisture_before is not None and moisture_after is not None:
                        reasons.append(
                            f"Moisture: {moisture_before:.1f}% -> {moisture_after:.1f}%"
                        )
                    elif moisture_after is not None:
                        reasons.append(f"Moisture: {moisture_after:.1f}%")

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
                        reasons=reasons,
                    )
                    self._main_coordinator.add_event(self._growspace_id, event)
            except Exception as e:  # noqa: BLE001
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
