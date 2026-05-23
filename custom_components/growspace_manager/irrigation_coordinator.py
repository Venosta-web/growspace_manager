"""Coordinator for handling irrigation and drain schedules."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, timedelta
from functools import partial
import logging
from typing import TYPE_CHECKING, Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_time_change
from homeassistant.util.dt import utcnow

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from .const import ATTR_GROWSPACE_ID, CATEGORY_ALERT, EVENT_GROWSPACE_LOG_ENTRY
from .exceptions import GrowspaceError
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
        self._last_cycle_timestamp: str | None = None

    @property
    def last_cycle_timestamp(self) -> str | None:
        """Return the ISO timestamp of the most recently completed irrigation cycle start."""
        return self._last_cycle_timestamp

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
            for task in list(self._running_tasks.values()):
                if task and not task.done():
                    task.cancel()
            self._running_tasks.clear()
        _LOGGER.debug(
            "Cancelled all irrigation listeners for growspace %s", self._growspace_id
        )

    def get_default_duration(self, event_type: str) -> int | None:
        """Get the default duration for a given event type."""
        try:
            return getattr(
                self.growspace.irrigation_config, f"{event_type}_duration", None
            )
        except (KeyError, AttributeError):
            return None

    async def _save_and_reload(self, reload_listeners: bool = True) -> None:
        """Save changes to storage and reload listeners."""
        await self._main_coordinator.async_refresh_growspace_data(self._growspace_id)
        await self._main_coordinator.async_commit()
        self._main_coordinator.async_set_updated_data(self._main_coordinator.data)
        if reload_listeners:
            await self.async_request_refresh()

    async def async_add_schedule_item(
        self, schedule_key: str, time_str: str, duration: int | None
    ) -> None:
        """Add a time entry to an irrigation or drain schedule."""
        if not time_str:
            raise ValueError("Time cannot be empty")

        if len(time_str) == 5:
            time_str = f"{time_str}:00"

        try:
            datetime.strptime(time_str, "%H:%M:%S")
        except ValueError as err:
            raise ValueError(f"Invalid time '{time_str}': hours must be 00-23") from err

        if not hasattr(self.growspace.irrigation_config, schedule_key):
            _LOGGER.error("Invalid schedule key %s", schedule_key)
            return

        current_schedule: list[dict[str, Any]] = getattr(
            self.growspace.irrigation_config, schedule_key
        )

        existing_item = next(
            (item for item in current_schedule if item.get("time") == time_str),
            None,
        )

        if existing_item:
            existing_item["duration"] = duration
            _LOGGER.info(
                "Updated %s in %s for growspace %s. Duration set to %s",
                time_str,
                schedule_key,
                self._growspace_id,
                duration,
            )
            new_list = list(current_schedule)
            setattr(self.growspace.irrigation_config, schedule_key, new_list)
        else:
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

            await self._save_and_reload()

        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ):
            _LOGGER.exception(
                "Unexpected error removing schedule item from %s", schedule_key
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

    async def _async_wait_for_switch_state(
        self, entity_id: str, target_state: str, timeout: float = 10.0
    ) -> bool:
        """Wait for entity to reach target state.

        This is critical for Matter smart plugs and other devices with high latency.
        We don't start the irrigation timer until the device confirms it's ON.

        Args:
            entity_id: The entity to monitor
            target_state: The state to wait for ("on" or "off")
            timeout: Maximum time to wait in seconds

        Returns:
            True if state was confirmed, False if timed out
        """
        # Check if already in target state
        current_state = self.hass.states.get(entity_id)
        if current_state and current_state.state == target_state:
            _LOGGER.debug(
                "%s is already in state '%s'",
                entity_id,
                target_state,
            )
            return True

        # Set up event to signal when state changes
        state_reached = asyncio.Event()

        @callback
        def state_change_listener(event: Event) -> None:
            """Listen for state changes."""
            event_entity_id = event.data.get("entity_id")
            if event_entity_id != entity_id:
                return

            new_state = event.data.get("new_state")
            if new_state and new_state.state == target_state:
                state_reached.set()

        # Subscribe to state change events
        remove_listener = self.hass.bus.async_listen(
            EVENT_STATE_CHANGED, state_change_listener
        )

        try:
            # Wait for state change or timeout
            await asyncio.wait_for(state_reached.wait(), timeout=timeout)
        except TimeoutError:
            _LOGGER.warning(
                "%s did not confirm state '%s' within %s seconds. "
                "This may indicate high device latency (e.g., Matter smart plug). "
                "Proceeding anyway, but irrigation duration may be inaccurate",
                entity_id,
                target_state,
                timeout,
            )
            return False
        else:
            _LOGGER.debug(
                "%s confirmed state '%s'",
                entity_id,
                target_state,
            )
            return True
        finally:
            remove_listener()


class IrrigationCoordinator(BaseIrrigationCoordinator):
    """Manages irrigation and drain schedules for a specific growspace."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize with daily safety-guard counters."""
        super().__init__(hass, config_entry, growspace_id, main_coordinator)
        self._cycles_today: int = 0
        self._volume_dispensed_today: float = 0.0

    @property
    def cycles_today(self) -> int:
        """Return the number of irrigation cycles completed today."""
        return self._cycles_today

    @property
    def volume_dispensed_today(self) -> float:
        """Return total irrigation volume dispensed today in litres."""
        return self._volume_dispensed_today

    @override
    async def async_request_refresh(self) -> None:
        """Refresh listeners when configuration changes."""
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

    @override
    async def async_setup(self) -> None:
        """Set up the irrigation schedules."""
        # Register midnight reset for daily counters
        self._listeners.append(
            async_track_time_change(
                self.hass,
                self._async_reset_daily_counters,
                hour=0,
                minute=0,
                second=0,
            )
        )

        # Load schedules without triggering updates
        await self.async_update_listeners()

    async def _async_reset_daily_counters(self, *_: Any) -> None:
        """Reset daily safety-guard counters at local midnight."""
        _LOGGER.debug(
            "Resetting daily irrigation counters for growspace %s",
            self._growspace_id,
        )
        self._cycles_today = 0
        self._volume_dispensed_today = 0.0

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

        task = self._config_entry.async_create_background_task(
            self.hass,
            self._run_pump_cycle(event_type, pump_entity, int(duration), event_data),
            f"irrigation_pump_{self._growspace_id}_{event_type}",
        )
        self._running_tasks[event_type] = task

    def _compute_cycle_volume_liters(self, duration: int) -> float:
        """Return the estimated water volume for a cycle in litres.

        Returns 0.0 when the flow rate is not configured, which disables the
        volume-cap check for that cycle.
        """
        flow_rate = self.growspace.irrigation_config.pump_flow_rate_ml_per_sec
        if not flow_rate:
            return 0.0
        return duration * flow_rate / 1000.0

    def _is_lights_dark(self) -> bool:
        """Return True when all configured light sensors report off or are unavailable.

        Returns False (lights considered on) when no light sensors are configured,
        so irrigation is not blocked by default.
        """
        light_sensors = self.growspace.environment_config.light_sensors
        if not light_sensors:
            return False
        return all(
            (state := self.hass.states.get(sensor)) is None or state.state != "on"
            for sensor in light_sensors
        )

    def _find_low_tank(self) -> tuple[str, float, float] | None:
        """Return (name, current_level, warning_level) for the first below-warning tank.

        Returns None when all tanks are above their warning levels or none are configured.
        """
        for tank in self.growspace.environment_config.irrigation_tanks:
            level = self._get_sensor_value(tank.sensor_entity)
            if level is not None and level < tank.warning_level:
                return (tank.name, level, tank.warning_level)
        return None

    async def _async_fire_low_tank_notification(
        self, tank_name: str, level: float
    ) -> None:
        """Fire a persistent HA warning notification when irrigation is skipped due to low tank."""
        growspace = self.growspace
        message = (
            f"Irrigation skipped in '{growspace.name}': "
            f"tank '{tank_name}' is low ({level:.1f}%). "
            "Refill the reservoir before the next cycle."
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": message,
                "title": f"Low Tank — {growspace.name}",
                "notification_id": f"growspace_low_tank_{self._growspace_id}",
            },
            blocking=False,
        )

    def _check_safety_guards(self, duration: int) -> str | None:
        """Return a skip reason string if a safety guard blocks the cycle, else None.

        Only applies to irrigation cycles — drain cycles are never blocked.
        """
        config = self.growspace.irrigation_config

        if config.max_cycles_per_day is not None and self._cycles_today >= config.max_cycles_per_day:
            return (
                f"Daily cycle limit reached ({self._cycles_today}/{config.max_cycles_per_day})"
            )

        cycle_volume = self._compute_cycle_volume_liters(duration)
        if (
            cycle_volume > 0
            and config.daily_volume_cap_liters is not None
            and self._volume_dispensed_today + cycle_volume > config.daily_volume_cap_liters
        ):
            return (
                f"Daily volume cap would be exceeded "
                f"({self._volume_dispensed_today:.3f}L + {cycle_volume:.3f}L "
                f"> {config.daily_volume_cap_liters}L cap)"
            )

        return None

    def _fire_logbook_event(self, message: str, category: str = CATEGORY_ALERT) -> None:
        """Fire a Home Assistant logbook event for this growspace."""
        self.hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                ATTR_GROWSPACE_ID: self._growspace_id,
                "message": message,
                "category": category,
                "timestamp": utcnow().isoformat(),
            },
        )

    async def _run_pump_cycle(
        self,
        event_type: str,
        pump_entity: str,
        duration: int,
        event_data: Mapping[str, Any],
    ) -> None:
        """Run the on-off cycle for a pump and send notifications."""
        # Low tank check applies to ALL cycles (scheduled and manual).
        config = self.growspace.irrigation_config
        if config.pause_on_low_tank:
            low_tank = self._find_low_tank()
            if low_tank:
                tank_name, level, warn = low_tank
                skip_reason = (
                    f"tank '{tank_name}' is low ({level:.1f}% < {warn:.1f}%)"
                )
                _LOGGER.warning(
                    "Skipping %s cycle for growspace %s: %s",
                    event_type,
                    self._growspace_id,
                    skip_reason,
                )
                await self._async_fire_low_tank_notification(tank_name, level)
                if config.log_to_logbook:
                    self._fire_logbook_event(
                        f"{event_type.capitalize()} skipped — {skip_reason}",
                    )
                return

        # Safety guards and dark skip apply only to irrigation cycles.
        if event_type == "irrigation":
            skip_reason = self._check_safety_guards(duration)
            if skip_reason:
                _LOGGER.warning(
                    "Skipping irrigation cycle for growspace %s: %s",
                    self._growspace_id,
                    skip_reason,
                )
                if config.log_to_logbook:
                    self._fire_logbook_event(
                        f"Irrigation skipped — {skip_reason}",
                    )
                return

            # Dark skip: scheduled cycles only — manual runs bypass this check.
            is_manual = event_data.get("manual", False)
            if not is_manual and config.skip_during_dark and self._is_lights_dark():
                skip_reason = "lights are currently off (dark period)"
                _LOGGER.warning(
                    "Skipping scheduled irrigation for growspace %s: %s",
                    self._growspace_id,
                    skip_reason,
                )
                if config.log_to_logbook:
                    self._fire_logbook_event(
                        f"Irrigation skipped — {skip_reason}",
                    )
                return

        # Track active event for frontend animation
        self._active_events[event_type] = {
            "start": utcnow().isoformat(),
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

            _LOGGER.info(
                "Starting %s for %s (entity: %s), running for %s seconds",
                event_type,
                self._growspace_id,
                pump_entity,
                duration,
            )

            if event_type == "irrigation" and self.growspace.irrigation_config.log_to_logbook:
                self._fire_logbook_event(
                    f"Irrigation started — {duration}s on {pump_entity}",
                )

            await self.hass.services.async_call(
                "switch", "turn_on", {"entity_id": pump_entity}, blocking=True
            )

            # Wait for switch to confirm ON state (critical for Matter smart plugs)
            await self._async_wait_for_switch_state(pump_entity, "on")

            # Start timing AFTER switch confirms ON
            start_dt = utcnow()
            if event_type == "irrigation":
                self._last_cycle_timestamp = start_dt.isoformat()

            await self._async_send_cycle_notification(event_type, duration, event_data)

            await asyncio.sleep(duration)

        except asyncio.CancelledError:
            _LOGGER.info(
                "%s event for %s (entity: %s) was cancelled",
                event_type.capitalize(),
                self._growspace_id,
                pump_entity,
            )
        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ) as e:
            _LOGGER.error(
                "Error during %s cycle for %s (entity: %s): %s",
                event_type,
                self._growspace_id,
                pump_entity,
                e,
            )
        finally:
            # Record end time BEFORE turning off (to exclude turn-off latency)
            end_dt = utcnow()

            try:
                # Clear active event
                self._active_events.pop(event_type, None)

                # Ensure start_dt is defined
                if start_dt:
                    duration_sec = (end_dt - start_dt).total_seconds()

                    # Update daily counters for completed irrigation cycles.
                    # Use the planned duration (not measured elapsed) for volume
                    # accounting because asyncio.sleep duration is the driver.
                    if event_type == "irrigation":
                        self._cycles_today += 1
                        cycle_volume = self._compute_cycle_volume_liters(duration)
                        self._volume_dispensed_today += cycle_volume

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

                    if (
                        event_type == "irrigation"
                        and self.growspace.irrigation_config.log_to_logbook
                    ):
                        self._fire_logbook_event(
                            f"Irrigation completed — {int(duration_sec)}s "
                            f"({self._volume_dispensed_today:.3f}L dispensed today)",
                        )

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
            except (
                AttributeError,
                KeyError,
                ValueError,
                ServiceValidationError,
                GrowspaceError,
            ) as e:
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

    @property
    def next_scheduled_cycle(self) -> str | None:
        """Return the ISO datetime of the next upcoming scheduled irrigation cycle.

        Scans the configured irrigation_times and returns the soonest future occurrence.
        Returns None when no times are configured.
        """
        irrigation_times = self.growspace.irrigation_config.irrigation_times
        if not irrigation_times:
            return None

        now = utcnow()
        today = now.date()
        soonest: datetime | None = None

        for item in irrigation_times:
            time_str = item.get("time")
            if not isinstance(time_str, str):
                continue
            if len(time_str) == 5:
                time_str = f"{time_str}:00"
            try:
                t = datetime.strptime(time_str, "%H:%M:%S").time()
            except ValueError:
                continue

            candidate = datetime.combine(today, t, tzinfo=now.tzinfo)
            if candidate <= now:
                candidate = datetime.combine(
                    today + timedelta(days=1), t, tzinfo=now.tzinfo
                )
            if soonest is None or candidate < soonest:
                soonest = candidate

        return soonest.isoformat() if soonest else None

    async def async_manual_run(self, duration: int | None) -> None:
        """Trigger a manual irrigation cycle, bypassing the schedule.

        Args:
            duration: Duration in seconds. Uses the configured default when None.

        Raises:
            ServiceValidationError: When no irrigation pump entity is configured or
                no duration can be determined.
        """
        options = self.growspace.irrigation_config
        pump_entity = options.irrigation_pump_entity
        if not pump_entity:
            raise ServiceValidationError(
                f"No irrigation pump entity configured for growspace '{self._growspace_id}'"
            )

        effective_duration = duration or options.irrigation_duration
        if not effective_duration:
            raise ServiceValidationError(
                f"No irrigation duration provided or configured for growspace '{self._growspace_id}'"
            )

        if (
            "irrigation" in self._running_tasks
            and self._running_tasks["irrigation"]
            and not self._running_tasks["irrigation"].done()
        ):
            _LOGGER.warning(
                "Cancelling running irrigation cycle for %s to start manual run",
                self._growspace_id,
            )
            self._running_tasks["irrigation"].cancel()

        task = self._config_entry.async_create_background_task(
            self.hass,
            self._run_pump_cycle(
                "irrigation", pump_entity, int(effective_duration), {"manual": True}
            ),
            f"irrigation_manual_run_{self._growspace_id}",
        )
        self._running_tasks["irrigation"] = task
