"""Coordinator for handling irrigation and drain schedules."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, time
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
from .const import (
    ATTR_GROWSPACE_ID,
    CATEGORY_ALERT,
    CATEGORY_IRRIGATION_ERROR,
    EVENT_GROWSPACE_LOG_ENTRY,
    SENSOR_SETTLING_DELAY_CAP_SECONDS,
)
from .domain.irrigation_schedule import (
    next_occurrence,
    remove_items,
    schedulable_events,
    upsert_item,
)
from .domain.pump_cycle import (
    CycleVerdict,
    SkipReason,
    TankReading,
    cycle_volume_liters,
    decide_cycle,
    safety_cap_blocks,
)
from .domain.water_aggregation import (
    WATER_SOURCE_PUMP_ESTIMATE,
    is_tank_derived_mode,
    record_daily_water,
)
from .exceptions import GrowspaceError
from .models import Growspace, GrowspaceEvent, IrrigationConfig
from .utils import any_light_sensor_on

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
        self._settling_tasks: set[asyncio.Task[Any]] = set()
        self._active_events: dict[str, dict[str, Any]] = {}
        self._last_cycle_timestamp: str | None = None
        # Daily safety-guard counters (reset by sub-coordinators at midnight)
        self._cycles_today: int = 0
        self._volume_dispensed_today: float = 0.0

    @property
    def last_cycle_timestamp(self) -> str | None:
        """Return the ISO timestamp of the most recently completed irrigation cycle start."""
        return self._last_cycle_timestamp

    @property
    def active_events(self) -> dict[str, dict[str, Any]]:
        """Return currently active events (start_time, duration)."""
        return self._active_events

    @property
    def next_scheduled_cycle(self) -> str | None:
        """Return the ISO datetime of the next scheduled irrigation cycle, or None."""
        return None

    @property
    def projected_shot_window(self) -> dict[str, str] | None:
        """Return the {start, end} ISO range of the next projected shot, or None.

        Crop-steering-only concept (see VWCIrrigationCoordinator); base/manual
        scheduling has no equivalent estimate to project.
        """
        return None

    @property
    def cycles_today(self) -> int:
        """Return the number of irrigation cycles completed today."""
        return self._cycles_today

    @property
    def volume_dispensed_today(self) -> float:
        """Return total irrigation volume dispensed today in litres."""
        return self._volume_dispensed_today

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

    def _register_daily_reset_listener(self) -> None:
        """Register a midnight listener that resets the daily safety-guard counters."""
        self._listeners.append(
            async_track_time_change(
                self.hass,
                self._async_reset_daily_counters,
                hour=0,
                minute=0,
                second=0,
            )
        )

    async def _async_reset_daily_counters(self, *_: Any) -> None:
        """Reset daily safety-guard counters at local midnight."""
        _LOGGER.debug(
            "Resetting daily irrigation counters for growspace %s",
            self._growspace_id,
        )
        self._cycles_today = 0
        self._volume_dispensed_today = 0.0
        self._reset_extra_daily_state()

    def _reset_extra_daily_state(self) -> None:
        """Reset subclass-specific daily state. Override for additional fields."""

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

            for settling_task in list(self._settling_tasks):
                if not settling_task.done():
                    settling_task.cancel()
            self._settling_tasks.clear()
        _LOGGER.debug(
            "Cancelled all irrigation listeners for growspace %s", self._growspace_id
        )

    def get_default_duration(self, event_type: str) -> int | None:
        """Get the default duration for a given event type."""
        try:
            return getattr(
                self.growspace.irrigation_config, f"{event_type}_duration", None
            )
        except KeyError, AttributeError:
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
        """Add a time entry to an irrigation or drain schedule.

        The list mutation is the Irrigation Schedule's `upsert_item`
        (ADR-0029); this method owns the assign + persist effects.
        """
        if not hasattr(self.growspace.irrigation_config, schedule_key):
            _LOGGER.error("Invalid schedule key %s", schedule_key)
            return

        current_schedule: list[dict[str, Any]] = getattr(
            self.growspace.irrigation_config, schedule_key
        )
        change = upsert_item(current_schedule, time_str, duration)
        setattr(self.growspace.irrigation_config, schedule_key, change.items)

        if change.updated:
            _LOGGER.info(
                "Updated %s in %s for growspace %s. Duration set to %s",
                time_str,
                schedule_key,
                self._growspace_id,
                duration,
            )
        else:
            _LOGGER.info(
                "Added %s to %s for growspace %s. Schedule now has %d items",
                time_str,
                schedule_key,
                self._growspace_id,
                len(change.items),
            )

        await self._save_and_reload()

    async def async_remove_schedule_item(
        self, schedule_key: str, time_str: str
    ) -> None:
        """Remove all matching time entries from a schedule.

        Matching runs through the Irrigation Schedule's shared normalizer
        (ADR-0029), so removing "08:00" also matches the stored "08:00:00"
        — the raw-string comparison this replaces silently removed nothing.
        """
        if not hasattr(self.growspace.irrigation_config, schedule_key):
            _LOGGER.warning(
                "Cannot remove item: schedule '%s' not found for growspace %s",
                schedule_key,
                self._growspace_id,
            )
            return

        schedule = getattr(self.growspace.irrigation_config, schedule_key)
        change = remove_items(schedule, time_str)

        if not change.removed:
            _LOGGER.warning(
                "Time %s not found in %s for growspace %s. No items removed",
                time_str,
                schedule_key,
                self._growspace_id,
            )
            return

        setattr(self.growspace.irrigation_config, schedule_key, change.items)
        _LOGGER.info(
            "Removed %d item(s) with time %s from %s for growspace %s",
            change.removed,
            time_str,
            schedule_key,
            self._growspace_id,
        )

        await self._save_and_reload()

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

    def _compute_cycle_volume_liters(self, duration: int) -> float:
        """Return the estimated water volume for a cycle in litres."""
        return cycle_volume_liters(self.growspace.irrigation_config, duration)

    async def _async_record_pump_water(self, liters: float) -> None:
        """Persist an estimated pump-cycle volume into WaterUsageData (ADR-0017).

        Skipped in Tank-Derived Water Mode, where the reservoir already measures
        this water — writing a pump estimate too would double-count. Commits
        through the main coordinator so the figure survives a restart (the
        in-memory daily-cap counter does not).
        """
        if liters <= 0:
            return
        growspace = self.growspace
        if is_tank_derived_mode(growspace):
            return
        record_daily_water(growspace, liters, source=WATER_SOURCE_PUMP_ESTIMATE)
        await self._main_coordinator.async_commit()

    def _is_lights_dark(self) -> bool:
        """Return True when no configured light sensor reports lights on.

        Returns False (lights considered on) when no light sensors are configured,
        so irrigation is not blocked by default. Sensors that are unavailable or
        unknown fail toward "dark" — under-watering for one cycle is recoverable,
        whereas watering during an actual dark/dry-back period is not.
        """
        light_sensors = self.growspace.environment_config.light_sensors
        if not light_sensors:
            return False
        return any_light_sensor_on(self.hass, light_sensors) is not True

    def _resolve_tank_readings(self) -> list[TankReading]:
        """Resolve configured irrigation tanks into readings for the Pump Cycle Gate.

        Tanks whose sensor is unavailable are omitted (matching the previous
        behaviour of skipping unreadable tanks rather than treating them as low).
        """
        readings: list[TankReading] = []
        for tank in self.growspace.environment_config.irrigation_tanks:
            level = self._get_sensor_value(tank.sensor_entity)
            if level is not None:
                readings.append(
                    TankReading(
                        name=tank.name,
                        level=level,
                        warning_level=tank.warning_level,
                    )
                )
        return readings

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

    def _check_safety_guards(self, duration: int) -> SkipReason | None:
        """Return the cap/limit reason blocking an irrigation cycle, else None.

        Thin delegator to the Pump Cycle Gate's safety_cap_blocks (ADR-0021);
        the Adaptive Shot Control loop probes this to set its capped diagnostic.
        """
        return safety_cap_blocks(
            self.growspace.irrigation_config,
            self._cycles_today,
            self._volume_dispensed_today,
            self._compute_cycle_volume_liters(duration),
        )

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

    async def _apply_skip_verdict(
        self, config: IrrigationConfig, verdict: CycleVerdict
    ) -> None:
        """Drive the effects for a skipped cycle from a Pump Cycle Gate verdict.

        Low-tank additionally fires a persistent notification; every reason logs
        to the logbook, except a dark-period skip which is gated on log_to_logbook.
        """
        _LOGGER.warning("%s (growspace %s)", verdict.message, self._growspace_id)
        if verdict.reason is SkipReason.LOW_TANK and verdict.low_tank is not None:
            await self._async_fire_low_tank_notification(
                verdict.low_tank.name, verdict.low_tank.level
            )
        if verdict.reason is not SkipReason.DARK or config.log_to_logbook:
            self._fire_logbook_event(verdict.message, CATEGORY_IRRIGATION_ERROR)

    async def _run_pump_cycle(
        self,
        event_type: str,
        pump_entity: str,
        duration: int,
        event_data: Mapping[str, Any],
    ) -> None:
        """Run the on-off cycle for a pump and send notifications."""
        # Ask the Pump Cycle Gate whether this cycle may fire (ADR-0021). The
        # gate is a pure decision; this method owns the resulting effects.
        config = self.growspace.irrigation_config
        cycle_volume_l = self._compute_cycle_volume_liters(duration)
        verdict = decide_cycle(
            event_type=event_type,
            is_manual=bool(event_data.get("manual", False)),
            config=config,
            tank_readings=self._resolve_tank_readings(),
            lights_dark=self._is_lights_dark(),
            cycles_today=self._cycles_today,
            volume_today=self._volume_dispensed_today,
            cycle_volume_l=cycle_volume_l,
        )
        if not verdict.fire:
            await self._apply_skip_verdict(config, verdict)
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

            if (
                event_type == "irrigation"
                and self.growspace.irrigation_config.log_to_logbook
            ):
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
            self._fire_logbook_event(
                f"{event_type.capitalize()} aborted — cycle was cancelled",
                CATEGORY_IRRIGATION_ERROR,
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
            self._fire_logbook_event(
                f"{event_type.capitalize()} failed — {e}",
                CATEGORY_IRRIGATION_ERROR,
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
                        self._volume_dispensed_today += cycle_volume_l
                        await self._async_record_pump_water(cycle_volume_l)

                    self._async_spawn_settling_report(
                        event_type=event_type,
                        start_dt=start_dt,
                        end_dt=end_dt,
                        duration_sec=duration_sec,
                        moisture_before=moisture_before,
                        volume_dispensed_today=self._volume_dispensed_today,
                    )
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

    @callback
    def _async_spawn_settling_report(
        self,
        *,
        event_type: str,
        start_dt: datetime,
        end_dt: datetime,
        duration_sec: float,
        moisture_before: float | None,
        volume_dispensed_today: float,
    ) -> None:
        """Spawn a background task that reports cycle completion after the sensor settles.

        Snapshots everything the report needs up front so a fast-following
        cycle can't corrupt the numbers describing this one — the only "live"
        read the background task performs is the post-wait moisture value.
        """
        wait_seconds = min(duration_sec, SENSOR_SETTLING_DELAY_CAP_SECONDS)
        task = self.hass.async_create_task(
            self._async_report_cycle_completion(
                event_type=event_type,
                start_dt=start_dt,
                end_dt=end_dt,
                duration_sec=duration_sec,
                moisture_before=moisture_before,
                volume_dispensed_today=volume_dispensed_today,
                wait_seconds=wait_seconds,
            ),
            name=f"irrigation_settling_report_{self._growspace_id}_{event_type}",
        )
        self._settling_tasks.add(task)
        task.add_done_callback(self._settling_tasks.discard)

    async def _async_report_cycle_completion(
        self,
        *,
        event_type: str,
        start_dt: datetime,
        end_dt: datetime,
        duration_sec: float,
        moisture_before: float | None,
        volume_dispensed_today: float,
        wait_seconds: float,
    ) -> None:
        """Wait for the moisture sensor to settle, then report cycle completion."""
        try:
            # Water needs time to redistribute through the substrate before the
            # sensor reflects the cycle's true effect.
            await asyncio.sleep(wait_seconds)
        except asyncio.CancelledError:
            return

        moisture_after = None
        if self.growspace.environment_config.soil_moisture_sensor:
            moisture_after = self._get_sensor_value(
                self.growspace.environment_config.soil_moisture_sensor
            )

        reasons = [
            f"{event_type.capitalize()} cycle completed",
            f"Duration: {int(duration_sec)}s",
        ]

        if moisture_before is not None and moisture_after is not None:
            reasons.append(f"Moisture: {moisture_before:.1f}% -> {moisture_after:.1f}%")
        elif moisture_after is not None:
            reasons.append(f"Moisture: {moisture_after:.1f}%")

        if (
            event_type == "irrigation"
            and self.growspace.irrigation_config.log_to_logbook
        ):
            self._fire_logbook_event(
                f"Irrigation completed — {int(duration_sec)}s "
                f"({volume_dispensed_today:.3f}L dispensed today)",
            )

        event = GrowspaceEvent(
            sensor_type="irrigation" if event_type == "irrigation" else "drain",
            growspace_id=self._growspace_id,
            start_time=start_dt.isoformat(),
            end_time=end_dt.isoformat(),
            duration_sec=int(duration_sec),
            severity=1.0,
            category="irrigation",
            reasons=reasons,
        )
        self._main_coordinator.add_event(self._growspace_id, event)

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
        if not effective_duration or effective_duration <= 0:
            raise ServiceValidationError(
                f"No valid irrigation duration provided or configured for growspace '{self._growspace_id}'"
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
        self._register_daily_reset_listener()

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

        # Dedup and time parsing live behind the Irrigation Schedule (ADR-0029)
        for times, event_type in (
            (irrigation_times, "irrigation"),
            (drain_times, "drain"),
        ):
            events = schedulable_events(times)
            for event in events.malformed:
                _LOGGER.warning(
                    "Skipping %s event with invalid time format: %s",
                    event_type,
                    event.get("time"),
                )
            for time_obj, event in events.valid:
                self._schedule_event(time_obj, event, event_type)

    def _schedule_event(
        self, time_obj: time, event: Mapping[str, Any], event_type: str
    ) -> None:
        """Register the time-change listener for one parsed schedule entry."""
        handler = partial(self._handle_event, event_type=event_type, event_data=event)

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

    @property
    def next_scheduled_cycle(self) -> str | None:
        """Return the ISO datetime of the next upcoming scheduled irrigation cycle.

        Scans the configured irrigation_times and returns the soonest future occurrence.
        Returns None when no times are configured.
        """
        soonest = next_occurrence(
            self.growspace.irrigation_config.irrigation_times, utcnow()
        )
        return soonest.isoformat() if soonest else None
