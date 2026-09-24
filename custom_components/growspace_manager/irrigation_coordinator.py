"""Coordinator for handling irrigation and drain schedules."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import datetime, time, timedelta
from functools import partial
import logging
import time as monotonic_time
from typing import TYPE_CHECKING, Any, override

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED, STATE_OFF, STATE_ON
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util.dt import as_local, utcnow

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from .actuator_driver import async_confirm_state
from .const import (
    ATTR_GROWSPACE_ID,
    CATEGORY_ALERT,
    CATEGORY_IRRIGATION_ERROR,
    EVENT_GROWSPACE_LOG_ENTRY,
    SENSOR_SETTLING_DELAY_CAP_SECONDS,
    NotificationTier,
)
from .domain.irrigation_safety import (
    ON_COMMAND_FAILED,
    ON_UNCONFIRMED,
    ControllerSnapshot,
    ControllerState,
    SafetyReason,
    controller_snapshot,
    open_failure_latches,
    startup_inhibit,
)
from .domain.irrigation_schedule import (
    next_occurrence,
    remove_items,
    schedulable_events,
    upsert_item,
)
from .domain.manual_override import (
    FAULT_UNEXPECTED_ON,
    MANUAL_OVERRIDE,
    OVERRIDE_DETECTED,
    Subsystem,
    UnexpectedOnPolicy,
    UnexpectedOnResponse,
    detected_override_reason,
    respond_to_on,
)
from .domain.pump_cycle import (
    CycleVerdict,
    SkipReason,
    TankReading,
    cycle_runtime_limit,
    cycle_volume_liters,
    decide_cycle,
    safety_cap_blocks,
)
from .domain.sensor_validity import (
    TANK_LEVEL_RANGE,
    Invalidity,
    PlausibleRange,
    SensorAlert,
    SensorReading,
    SensorWatch,
    inhibit_code,
    inhibit_detail,
    invalid_alert_message,
    recovered_alert_message,
    substrate_moisture_range,
    validate_reading,
)
from .domain.unknown_tank_level import UnknownTankLevel
from .domain.water_aggregation import (
    WATER_SOURCE_PUMP_ESTIMATE,
    is_tank_derived_mode,
    record_daily_water,
)
from .exceptions import GrowspaceError
from .irrigation_safety_store import IrrigationSafetyStore
from .models import Growspace, GrowspaceEvent, IrrigationConfig
from .reliability_store import (
    AbortCause,
    ReliabilityCounter,
    ReliabilityStore,
    aborted,
    automated_seconds,
    inhibited,
    skipped,
)
from .tank_monitor import (
    TankLevelMonitor,
    TankWatchBook,
    stale_after,
    unknown_tank_skip_notification_id,
)
from .utils import any_light_sensor_on

_LOGGER = logging.getLogger(__name__)

# How often the Startup Inhibit is re-evaluated until it clears. Only the
# clearing edge needs it — the gate itself is evaluated wherever a cycle is
# decided — so the controller sensor leaves ``inhibited`` promptly instead of
# waiting for the next coordinator refresh.
STARTUP_INHIBIT_POLL = timedelta(seconds=30)
PUMP_WATCHDOG_GRACE_SECONDS = 10
# How long a pump has to report ON after turn_on — the wait that exists for
# high-latency devices such as Matter smart plugs.
ON_CONFIRM_TIMEOUT_SECONDS = 10.0
# While a pump that would not read OFF stays latched, OFF is re-sent this often
# until it does (#785).
OFF_RETRY_INTERVAL = timedelta(minutes=1)
# Fault codes whose output was last seen not reading OFF. A restart resumes the
# OFF retry for these, since the pump may still be running.
_OFF_UNCONFIRMED_CODES = ("fault_off_unconfirmed:", "fault_watchdog_off_unconfirmed:")


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
        self._watchdog_cancelled_tasks: set[asyncio.Task[Any]] = set()
        self._override_cancelled_tasks: set[asyncio.Task[Any]] = set()
        self._settling_tasks: set[asyncio.Task[Any]] = set()
        self._active_events: dict[str, dict[str, Any]] = {}
        # Daily safety-guard counters (reset by sub-coordinators at midnight)
        self._cycles_today: int = 0
        self._volume_dispensed_today: float = 0.0
        self._inhibit_since: dict[str, str] = {}
        # The Startup Inhibit (#786): None until setup begins it, so a
        # coordinator that was never set up is never held by it.
        self._startup_began_at: datetime | None = None
        self._startup_cleared = False
        self._cancel_startup_poll: Callable[[], None] | None = None
        self._cancel_sensor_probe: Callable[[], None] | None = None
        self._sensor_probe_states: dict[str, Invalidity | None] = {}
        # One watch per validated sensor (#789): its learned report cadence,
        # and for the moisture sensor the invalid episode its alert follows.
        self._sensor_watches: dict[str, SensorWatch] = {}
        # The moisture sensor's validity as of the last sensor tick, so an edge
        # is written to the Safety Ledger once rather than every minute.
        self._moisture_invalidity: Invalidity | None = None
        # Consecutive cycles per output that could not be opened (#785); a
        # confirmed ON on that output resets it.
        self._open_failures: dict[str, int] = {}
        # Outputs being re-sent OFF every minute until they read OFF.
        self._off_retries: dict[str, Callable[[], None]] = {}
        # Tank watches of our own, only when there is no TankLevelMonitor to
        # share (legacy isolated fixtures).
        self._own_tank_watches: TankWatchBook | None = None
        # Outputs a cycle of ours has commanded ON and not yet read back OFF —
        # the in-flight record an ON is checked against (#793).
        self._commanded_outputs: set[str] = set()
        # Outputs a person is running: an Unexpected On under the alert
        # policy, with when it was seen. Automatic irrigation holds on it.
        self._detected_overrides: dict[str, str] = {}
        # Outputs being switched off under enforce_off right now.
        self._enforcing_off: set[str] = set()
        self._watched_outputs: tuple[str, ...] = ()
        self._cancel_pump_watch: Callable[[], None] | None = None
        self._cancel_override_listener: Callable[[], None] | None = None

    @property
    def last_cycle_timestamp(self) -> str | None:
        """Return the ISO timestamp of the most recently completed irrigation cycle start."""
        return self._last_cycle_timestamp

    @property
    def _last_cycle_timestamp(self) -> str | None:
        """Return the persisted start of the last confirmed irrigation cycle.

        Stored on the growspace's substrate history rather than on this object
        so a restart restores the anchor every steering cooldown measures from
        (#786); there is no second, in-memory copy to drift from it.
        """
        return self.growspace.substrate_history.last_confirmed_shot_at

    @_last_cycle_timestamp.setter
    def _last_cycle_timestamp(self, value: str | None) -> None:
        self.growspace.substrate_history.last_confirmed_shot_at = value

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

    @property
    def _safety_store(self) -> IrrigationSafetyStore | None:
        """Return the safety store, absent only in legacy isolated test fixtures."""
        store = getattr(self._main_coordinator, "irrigation_safety", None)
        return store if isinstance(store, IrrigationSafetyStore) else None

    @property
    def _tank_watches(self) -> TankWatchBook:
        """Return the Unknown Tank Level watches the Tank Offline Alert also reads."""
        monitor = getattr(self._main_coordinator, "tank_monitor", None)
        if isinstance(monitor, TankLevelMonitor):
            return monitor.watches
        if self._own_tank_watches is None:
            self._own_tank_watches = TankWatchBook(self.hass)
        return self._own_tank_watches

    @property
    def _reliability(self) -> ReliabilityStore:
        """Return the entry's reliability evidence; recording never awaits."""
        return self._main_coordinator.reliability

    @callback
    def _record(self, counter: str, amount: float = 1) -> None:
        """Count one effect of this growspace in its reliability evidence."""
        self._reliability.record(self._growspace_id, counter, amount)

    def _configured_outputs(self) -> tuple[str, ...]:
        """Return every output that must be confirmed OFF before re-arming."""
        config = self.growspace.irrigation_config
        return tuple(
            entity
            for entity in (config.irrigation_pump_entity, config.drain_pump_entity)
            if entity
        )

    def controller_snapshot(self) -> ControllerSnapshot:
        """Resolve the current growspace state for the sensor and cycle gate."""
        config = self.growspace.irrigation_config
        store = self._safety_store
        fault = (
            store.fault_for(self._growspace_id, self._configured_outputs())
            if store
            else None
        )
        emergency_stop = store.emergency_stop_for(self._growspace_id) if store else None
        running = bool(self._active_events)
        automation_enabled = bool(
            config.irrigation_times
            or config.drain_times
            or (
                self.growspace.irrigation_strategy
                and self.growspace.irrigation_strategy.enabled
            )
        )
        inhibits: tuple[SafetyReason, ...] = ()
        if not running and fault is None and automation_enabled:
            operator_code = (
                "automation_off"
                if store and not store.automation_enabled(self._growspace_id)
                else "irrigation_disarmed"
                if store and not store.irrigation_armed(self._growspace_id)
                else None
            )
            if operator_code:
                detail = (
                    "Growspace automation is off"
                    if operator_code == "automation_off"
                    else "Automatic irrigation is disarmed"
                )
                since = self._inhibit_since.setdefault(
                    operator_code, utcnow().isoformat()
                )
                inhibits = (SafetyReason(operator_code, detail, since),)
            else:
                startup = self.startup_inhibit_reason()
                if startup is not None:
                    inhibits = (startup,)
                sensor = self._control_sensor_inhibit()
                if sensor is not None:
                    inhibits = (*inhibits, sensor)
                tank_readings, unknown_tanks = self._resolve_tanks()
                verdict = decide_cycle(
                    event_type="irrigation",
                    is_manual=False,
                    config=config,
                    tank_readings=tank_readings,
                    unknown_tanks=unknown_tanks,
                    lights_dark=self._is_lights_dark(),
                    cycles_today=self._cycles_today,
                    volume_today=self._volume_dispensed_today,
                    cycle_volume_l=self._compute_cycle_volume_liters(
                        config.irrigation_duration or 0
                    ),
                )
                if verdict.reason is not None:
                    code = {
                        SkipReason.LOW_TANK: "tank_low",
                        SkipReason.TANK_UNKNOWN: "tank_unknown",
                        SkipReason.CYCLE_LIMIT: "cap_cycles",
                        SkipReason.VOLUME_CAP: "cap_volume",
                        SkipReason.DARK: "dark",
                    }[verdict.reason]
                    since = self._inhibit_since.setdefault(code, utcnow().isoformat())
                    inhibits = (*inhibits, SafetyReason(code, verdict.message, since))
        self._inhibit_since = {reason.code: reason.since for reason in inhibits}
        return controller_snapshot(
            configured=bool(self._configured_outputs()),
            automation_enabled=automation_enabled,
            running=running,
            inhibits=inhibits,
            fault=fault,
            emergency_stop=emergency_stop.reason if emergency_stop else None,
            holds=self._override_reasons(),
            manual_overrides=tuple(store.active_overrides(self._growspace_id))
            if store
            else (),
        )

    def _override_reasons(self) -> tuple[SafetyReason, ...]:
        """Return the holds a person has on the pumps, the declared one first."""
        store = self._safety_store
        reasons: list[SafetyReason] = []
        if store is not None and (
            override := store.override_for(self._growspace_id, Subsystem.IRRIGATION)
        ):
            reasons.append(override.safety_reason())
        if self._detected_overrides:
            reasons.append(detected_override_reason(self._detected_overrides))
        return tuple(reasons)

    def _person_hold(self) -> str | None:
        """Return why a person holds the pumps, if one does (#793)."""
        reasons = self._override_reasons()
        return reasons[0].code if reasons else None

    def _in_flight(self, output: str) -> bool:
        """Whether an ON of ``output`` is ours: commanded, or being stopped."""
        return (
            output in self._commanded_outputs
            or output in self._off_retries
            or output in self._enforcing_off
        )

    def _unexpected_on_policy(self) -> UnexpectedOnPolicy:
        """Return the configured policy; an unreadable one alerts, never actuates."""
        try:
            return UnexpectedOnPolicy(
                self.growspace.irrigation_config.unexpected_on_policy
            )
        except ValueError:
            return UnexpectedOnPolicy.ALERT

    @callback
    def _ensure_pump_watch(self) -> None:
        """Follow every managed pump's state, resubscribing when they change."""
        outputs = self._configured_outputs()
        if outputs == self._watched_outputs and self._cancel_pump_watch is not None:
            return
        self._cancel_pump_watch_listener()
        self._watched_outputs = outputs
        for output in list(self._detected_overrides):
            if output not in outputs:
                del self._detected_overrides[output]
        if outputs:
            self._cancel_pump_watch = async_track_state_change_event(
                self.hass, list(outputs), self._on_pump_state
            )

    def _cancel_pump_watch_listener(self) -> None:
        if self._cancel_pump_watch is not None:
            self._cancel_pump_watch()
            self._cancel_pump_watch = None

    @callback
    def _on_pump_state(self, event: Event[EventStateChangedData]) -> None:
        """Hand a pump's ON edge, or the OFF ending a person's run, to the shell."""
        output = event.data["entity_id"]
        new_state, old_state = event.data["new_state"], event.data["old_state"]
        if new_state is None:
            return
        if new_state.state == STATE_ON and (
            old_state is None or old_state.state != STATE_ON
        ):
            self.hass.async_create_task(
                self._async_observe_on(output),
                name=f"growspace_pump_on_{self._growspace_id}_{output}",
            )
        elif new_state.state == STATE_OFF and output in self._detected_overrides:
            self.hass.async_create_task(
                self._async_person_finished(output),
                name=f"growspace_pump_off_{self._growspace_id}_{output}",
            )

    def _unexpected_on_notification_id(self, output: str) -> str:
        return f"growspace_pump_unexpected_on_{self._growspace_id}_{output}"

    async def _async_observe_on(self, output: str) -> None:
        """Answer a managed pump reading ON: ours, a person's, or to be stopped.

        Under the default ``alert`` policy it is a person's: it is announced,
        and automatic irrigation holds until it reads OFF. Under
        ``enforce_off`` it is switched off, read back and latched as a Fault.
        """
        if output in self._detected_overrides or output in self._enforcing_off:
            return
        store = self._safety_store
        policy = self._unexpected_on_policy()
        response = respond_to_on(
            in_flight=self._in_flight(output),
            overridden=store is not None
            and store.override_for(self._growspace_id, Subsystem.IRRIGATION)
            is not None,
            commands_allowed=store is None
            or store.automation_enabled(self._growspace_id),
            policy=policy,
        )
        if response is None:
            return
        self._record(ReliabilityCounter.UNEXPECTED_ON)
        name = self.growspace.name
        _LOGGER.warning(
            "%s switched on outside Growspace Manager in %s (%s)",
            output,
            self._growspace_id,
            response,
        )
        if response is UnexpectedOnResponse.ALERT:
            self._detected_overrides[output] = utcnow().isoformat()
            await self._async_record_unexpected_on(output, policy, response)
            message = (
                f"{output} was switched on outside Growspace Manager. It is "
                "treated as someone watering by hand: automatic irrigation in "
                f"'{name}' waits until it reads off, and Growspace Manager "
                "will not switch it off."
            )
            title = f"Pump switched on by hand — {name}"
            self._fire_logbook_event(message, CATEGORY_IRRIGATION_ERROR)
            await self._async_record_controller_state()
        else:
            self._enforcing_off.add(output)
            try:
                off_confirmed = await self._async_command_off(output)
                await self._async_record_unexpected_on(
                    output, policy, response, off_confirmed=off_confirmed
                )
                detail = f"{output} was switched on outside Growspace Manager"
                if off_confirmed:
                    await self._latch_fault(
                        f"{FAULT_UNEXPECTED_ON}:{output}",
                        f"{detail}; switched off under enforce_off",
                        output,
                    )
                else:
                    await self._async_off_unconfirmed(
                        output,
                        f"fault_off_unconfirmed:{output}",
                        f"{detail} and did not read back OFF after turn_off",
                    )
            finally:
                self._enforcing_off.discard(output)
            message = (
                f"{output} was switched on outside Growspace Manager and was "
                + ("switched off" if off_confirmed else "told to switch off")
                + f". Irrigation in '{name}' is stopped until an administrator "
                "acknowledges the fault."
            )
            title = f"Pump switched off — {name}"
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": self._unexpected_on_notification_id(output),
            },
            blocking=False,
        )
        await self._async_notify(title, message, tier=NotificationTier.UNEXPECTED_ON)

    async def _async_record_unexpected_on(
        self,
        output: str,
        policy: UnexpectedOnPolicy,
        response: UnexpectedOnResponse,
        **fields: Any,
    ) -> None:
        """Write an Unexpected On to the Safety Ledger, never blocking its effect."""
        store = self._safety_store
        if store is None or store.unreadable:
            return
        try:
            await store.async_record_event(
                self._growspace_id,
                "unexpected_on",
                output=output,
                policy=policy.value,
                response=response.value,
                **fields,
            )
        except Exception:
            # The store now reads unreadable, which holds every cycle.
            _LOGGER.exception("Could not record an unexpected ON of %s", output)

    async def _async_person_finished(self, output: str) -> None:
        """Release the hold once the pump a person was running reads OFF."""
        if self._detected_overrides.pop(output, None) is None:
            return
        store = self._safety_store
        if store is not None and not store.unreadable:
            try:
                await store.async_record_event(
                    self._growspace_id, "override_detected_cleared", output=output
                )
            except Exception:
                _LOGGER.exception("Could not record %s reading OFF again", output)
        self._fire_logbook_event(
            f"{output} reads off again — automatic irrigation resumes",
            category="irrigation",
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": self._unexpected_on_notification_id(output)},
            blocking=False,
        )
        await self._async_record_controller_state()

    @callback
    def _on_override_change(self, growspace_id: str, subsystem: Subsystem) -> None:
        """Hand irrigation over when a Manual Override of it starts, and report."""
        if growspace_id != self._growspace_id or subsystem is not Subsystem.IRRIGATION:
            return
        self.hass.async_create_task(
            self._async_override_changed(),
            name=f"growspace_override_{self._growspace_id}",
        )

    async def _async_override_changed(self) -> None:
        """Close our cycle as an override starts; look at the pumps as it ends."""
        store = self._safety_store
        if store is not None and store.override_for(
            self._growspace_id, Subsystem.IRRIGATION
        ):
            # A cycle of ours in flight is closed — its own OFF is the last
            # command Growspace Manager sends the pump until the override ends.
            for task in self._running_tasks.values():
                if task and not task.done():
                    self._override_cancelled_tasks.add(task)
                    task.cancel()
        else:
            # A pump the person left running is now an Unexpected On.
            for output in self._configured_outputs():
                state = self.hass.states.get(output)
                if state is not None and state.state == STATE_ON:
                    await self._async_observe_on(output)
        await self._async_record_controller_state()

    async def _latch_fault(self, code: str, detail: str, output: str) -> bool:
        """Persist a hardware disagreement and surface a Home Assistant repair.

        Returns whether this call latched it, rather than finding it latched.
        """
        store = self._safety_store
        if store is None:
            _LOGGER.error("Irrigation safety store unavailable: %s", detail)
            return False
        was_latched = store.fault_for(self._growspace_id, (output,)) is not None
        record = await store.async_latch(self._growspace_id, code, detail, (output,))
        if not was_latched:
            self._record(ReliabilityCounter.FAULT_LATCHED)
        from homeassistant.helpers.issue_registry import (  # noqa: PLC0415
            IssueSeverity,
            async_create_issue,
        )

        async_create_issue(
            self.hass,
            "growspace_manager",
            f"irrigation_fault_{self._growspace_id}",
            is_fixable=False,
            severity=IssueSeverity.ERROR,
            translation_key="irrigation_fault",
            translation_placeholders={
                "growspace": self.growspace.name,
                "detail": detail,
            },
        )
        self._fire_logbook_event(
            f"Irrigation fault {record.fault_id}: {detail}", CATEGORY_IRRIGATION_ERROR
        )
        self._main_coordinator.async_update_listeners()
        return not was_latched

    async def _record_safety_transition(
        self, state: str, reason_code: str | None = None
    ) -> None:
        """Persist and log each change to the controller's visible state."""
        store = self._safety_store
        if store is not None and await store.async_record_transition(
            self._growspace_id, state, reason_code
        ):
            if state == "inhibited":
                self._record(inhibited(reason_code))
            self._fire_logbook_event(
                f"Irrigation controller {state}"
                + (f" — {reason_code}" if reason_code else ""),
                category="irrigation",
            )
        self._main_coordinator.async_update_listeners()

    def _moisture_sensor(self) -> str | None:
        """Return the substrate moisture sensor while crop steering decides from it."""
        strategy = self.growspace.irrigation_strategy
        moisture = self.growspace.environment_config.soil_moisture_sensor
        return moisture if strategy and strategy.enabled and moisture else None

    def _control_sensors(self) -> tuple[str, ...]:
        """Return the sensors automatic irrigation decides from.

        The substrate moisture sensor while crop steering drives the pump, and
        every configured irrigation tank. The Startup Inhibit waits for each of
        them to report once before it lets an automatic cycle through.
        """
        sensors = [moisture] if (moisture := self._moisture_sensor()) else []
        for tank in self.growspace.environment_config.irrigation_tanks:
            if tank.sensor_entity and tank.sensor_entity not in sensors:
                sensors.append(tank.sensor_entity)
        return tuple(sensors)

    def _control_readings(self, now: datetime) -> dict[str, SensorReading]:
        """Validate every control sensor, each against its own window.

        The moisture sensor's window is its learned Observation Validity
        Window; a tank's is its own ``stale_after_minutes`` (never, at 0), the
        same one the Unknown Tank Level uses.
        """
        readings: dict[str, SensorReading] = {}
        if moisture := self._moisture_sensor():
            readings[moisture] = self._read_moisture(moisture, now)
        for tank in self.growspace.environment_config.irrigation_tanks:
            if not tank.sensor_entity or tank.sensor_entity in readings:
                continue
            state = self.hass.states.get(tank.sensor_entity)
            readings[tank.sensor_entity] = validate_reading(
                state.state if state else None,
                changed_at=state.last_changed if state else None,
                reported_at=state.last_reported if state else None,
                now=now,
                max_age=stale_after(tank),
                plausible=TANK_LEVEL_RANGE,
            )
        return readings

    def _sensor_stale_cap(self) -> timedelta | None:
        """Return the cap on a control sensor's validity window; None is off."""
        minutes = self.growspace.irrigation_config.sensor_stale_after_minutes
        return timedelta(minutes=minutes) if minutes > 0 else None

    def _read_sensor(
        self,
        entity_id: str,
        plausible: PlausibleRange,
        *,
        now: datetime | None = None,
        unit_scale: Callable[[str | None], float] | None = None,
    ) -> SensorReading:
        """Validate one sensor through its watch (``domain/sensor_validity.py``).

        ``unit_scale`` maps the state's unit of measurement to the factor that
        brings its value into ``plausible``'s unit.
        """
        now = now or utcnow()
        watch = self._sensor_watches.get(entity_id)
        if watch is None:
            watch = self._sensor_watches[entity_id] = SensorWatch(watching_since=now)
        state = self.hass.states.get(entity_id)
        scale = 1.0
        if state is not None and unit_scale is not None:
            scale = unit_scale(state.attributes.get("unit_of_measurement"))
        return watch.read(
            state.state if state else None,
            changed_at=state.last_changed if state else None,
            reported_at=state.last_reported if state else None,
            now=now,
            stale_cap=self._sensor_stale_cap(),
            plausible=plausible,
            scale=scale,
        )

    def _read_moisture(
        self, entity_id: str, now: datetime | None = None
    ) -> SensorReading:
        """Validate the substrate moisture sensor."""
        config = self.growspace.irrigation_config
        return self._read_sensor(
            entity_id,
            substrate_moisture_range(
                zero_is_implausible=config.moisture_zero_is_implausible
            ),
            now=now,
        )

    def _moisture_value(self) -> float | None:
        """Return the moisture sensor's value, or None when it cannot be trusted."""
        moisture = self.growspace.environment_config.soil_moisture_sensor
        return self._read_moisture(moisture).value if moisture else None

    def _control_sensor_inhibit(self) -> SafetyReason | None:
        """Return why automatic shots are withheld on the moisture sensor, if they are.

        Only the moisture sensor: a tank has its own grace and its own reason,
        ``tank_unknown``, from the Pump Cycle Gate.
        """
        moisture = self._moisture_sensor()
        if moisture is None:
            return None
        cause = self._read_moisture(moisture).invalidity
        if cause is None:
            return None
        since = self._sensor_watches[moisture].invalid_since or utcnow()
        return SafetyReason(
            inhibit_code(cause), inhibit_detail(moisture, cause), since.isoformat()
        )

    def _reported_since(self, entity_id: str, since: datetime) -> bool:
        """Return True when the sensor has reported a usable value since ``since``.

        ``last_reported`` moves on every report, including one that repeats the
        previous value, so a steady sensor still counts once it speaks; a state
        written before the start, or an unknown/unavailable one, does not.
        """
        state = self.hass.states.get(entity_id)
        if state is None or self._get_sensor_value(entity_id) is None:
            return False
        return state.last_reported >= since

    def startup_inhibit_reason(self) -> SafetyReason | None:
        """Return the Startup Inhibit while it holds, else None.

        Once it has cleared it stays cleared for the life of this coordinator:
        a sensor that drops out later is a stale-sensor problem, not a startup
        one.
        """
        if self._startup_began_at is None or self._startup_cleared:
            return None
        started_at = self._startup_began_at
        return startup_inhibit(
            started_at=started_at,
            now=utcnow(),
            grace=timedelta(
                minutes=self.growspace.irrigation_config.startup_grace_minutes
            ),
            awaiting=tuple(
                entity
                for entity in self._control_sensors()
                if not self._reported_since(entity, started_at)
            ),
        )

    async def _async_begin_startup_inhibit(self) -> None:
        """Hold automatic cycles from this start until the inhibit clears (#786)."""
        self._startup_began_at = utcnow()
        self._startup_cleared = False
        self._cancel_startup_poll_listener()
        self._cancel_startup_poll = async_track_time_interval(
            self.hass, self._async_poll_startup_inhibit, STARTUP_INHIBIT_POLL
        )
        if self._cancel_sensor_probe is None:
            self._cancel_sensor_probe = async_track_time_interval(
                self.hass, self._async_sensor_tick, timedelta(minutes=1)
            )
        store = self._safety_store
        if store is not None and self._cancel_override_listener is None:
            self._cancel_override_listener = store.add_override_listener(
                self._on_override_change
            )
        # A pump reading ON before any cycle of this start is an Unexpected On
        # like any other; from here on the watch sees each ON as it happens.
        self._ensure_pump_watch()
        for output in self._configured_outputs():
            state = self.hass.states.get(output)
            if state is not None and state.state == STATE_ON:
                await self._async_observe_on(output)
        await self._async_record_controller_state()

    @callback
    def _async_probe_control_sensors(self, *_: Any) -> None:
        """Sample unavailable minutes and count stale/implausible edges once.

        Validity is ``domain/sensor_validity.py``'s, with the same windows and
        ranges the controller decides on, so a tank that reports only on
        change (``stale_after_minutes: 0``) is never counted stale.
        """
        now = utcnow()
        for entity_id, reading in self._control_readings(now).items():
            invalidity = reading.invalidity
            if invalidity is Invalidity.UNAVAILABLE:
                self._record(ReliabilityCounter.SENSOR_UNAVAILABLE_MINUTES)
            if invalidity != self._sensor_probe_states.get(entity_id):
                if invalidity is Invalidity.STALE:
                    self._record(ReliabilityCounter.SENSOR_STALE_EVENTS)
                elif invalidity is Invalidity.IMPLAUSIBLE:
                    self._record(ReliabilityCounter.SENSOR_IMPLAUSIBLE_READINGS)
            self._sensor_probe_states[entity_id] = invalidity
        self._record(ReliabilityCounter.OBSERVED_MINUTES)
        safety = self._safety_store
        if (
            safety is not None
            and safety.irrigation_armed(self._growspace_id)
            and safety.fault_for(self._growspace_id, self._configured_outputs()) is None
        ):
            self._record(ReliabilityCounter.AUTOMATION_ELIGIBLE_MINUTES)

    async def _async_sensor_tick(self, *_: Any) -> None:
        """Probe the control sensors, then follow the moisture sensor's episode."""
        self._ensure_pump_watch()
        self._async_probe_control_sensors()
        await self._async_watch_moisture_sensor()

    async def _async_watch_moisture_sensor(self) -> None:
        """Write the moisture sensor's validity edges and send its alert (#789).

        Shots are withheld from the first invalid minute — the steering loop
        and the controller state read the same watch — but the alert waits out
        ``sensor_alert_delay_minutes``, once per episode.
        """
        now = utcnow()
        moisture = self._moisture_sensor()
        for entity_id, watch in self._sensor_watches.items():
            if watch.alerted and entity_id != moisture:
                # No longer a control input, so no longer withholding anything.
                watch.alerted = False
                await self._async_dismiss_sensor_alert(entity_id)
        if moisture is None:
            self._moisture_invalidity = None
            return
        invalidity = self._read_moisture(moisture, now).invalidity
        if invalidity != self._moisture_invalidity:
            self._moisture_invalidity = invalidity
            await self._async_record_controller_state()
        watch = self._sensor_watches[moisture]
        delay = timedelta(
            minutes=self.growspace.irrigation_config.sensor_alert_delay_minutes
        )
        transition = watch.alert(now, delay)
        if transition is SensorAlert.INVALID:
            await self._async_alert_sensor_invalid(moisture, watch)
        elif transition is SensorAlert.RECOVERED:
            await self._async_alert_sensor_recovered(moisture, watch)

    def _sensor_alert_notification_id(self, entity_id: str) -> str:
        return f"growspace_sensor_invalid_{self._growspace_id}_{entity_id}"

    async def _async_alert_sensor_invalid(
        self, entity_id: str, watch: SensorWatch
    ) -> None:
        """Send one episode's invalid moisture sensor alert."""
        growspace = self.growspace
        since = watch.invalid_since or utcnow()
        message = invalid_alert_message(
            entity_id,
            watch.cause or Invalidity.UNAVAILABLE,
            growspace_name=growspace.name,
            since_local=as_local(since).strftime("%H:%M"),
        )
        title = f"⚠️ Moisture Sensor Invalid: {growspace.name}"
        _LOGGER.warning("Growspace %s: %s", self._growspace_id, message)
        self._fire_logbook_event(message, CATEGORY_IRRIGATION_ERROR)
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": title,
                "message": message,
                "notification_id": self._sensor_alert_notification_id(entity_id),
            },
            blocking=False,
        )
        await self._async_notify(title, message)

    async def _async_alert_sensor_recovered(
        self, entity_id: str, watch: SensorWatch
    ) -> None:
        """Announce that an alerted moisture sensor reads again, and clear it."""
        growspace = self.growspace
        message = recovered_alert_message(
            entity_id, growspace.name, watch.last_valid_value
        )
        _LOGGER.info("Growspace %s: %s", self._growspace_id, message)
        self._fire_logbook_event(message, CATEGORY_ALERT)
        await self._async_dismiss_sensor_alert(entity_id)
        await self._async_notify(f"✅ Moisture Sensor Back: {growspace.name}", message)

    async def _async_dismiss_sensor_alert(self, entity_id: str) -> None:
        await self.hass.services.async_call(
            "persistent_notification",
            "dismiss",
            {"notification_id": self._sensor_alert_notification_id(entity_id)},
            blocking=False,
        )

    async def _async_notify(
        self,
        title: str,
        message: str,
        tier: NotificationTier = NotificationTier.SENSOR_INVALID,
    ) -> None:
        """Push to the growspace's notification target, on the sensor alert tier."""
        await self._main_coordinator.services.notifications.manager.async_send_notification(
            self._growspace_id,
            title,
            message,
            tier=tier,
        )

    async def _async_poll_startup_inhibit(self, *_: Any) -> None:
        """Latch the Startup Inhibit clear on the first evaluation that passes."""
        if self.startup_inhibit_reason() is not None:
            return
        self._startup_cleared = True
        self._cancel_startup_poll_listener()
        _LOGGER.info("Startup inhibit cleared for growspace %s", self._growspace_id)
        await self._async_record_controller_state()

    def _cancel_startup_poll_listener(self) -> None:
        if self._cancel_startup_poll is not None:
            self._cancel_startup_poll()
            self._cancel_startup_poll = None

    async def _async_record_controller_state(self) -> None:
        """Write the current controller state to the Safety Ledger.

        Skipped for an idle controller, which has nothing to hold, and for a
        latched one, whose ledger entry is the latch itself.
        """
        state = self.controller_snapshot()
        if state.requires_ack or state.state is ControllerState.IDLE:
            self._main_coordinator.async_update_listeners()
            return
        await self._record_safety_transition(
            state.state.value, state.reasons[0].code if state.reasons else None
        )

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
            if self._cancel_sensor_probe is not None:
                self._cancel_sensor_probe()
                self._cancel_sensor_probe = None
            # Teardown, not a schedule reload: the poll belongs to this
            # coordinator's start and must not outlive it.
            self._cancel_startup_poll_listener()
            self._cancel_pump_watch_listener()
            self._watched_outputs = ()
            if self._cancel_override_listener is not None:
                self._cancel_override_listener()
                self._cancel_override_listener = None
            for cancel_retry in self._off_retries.values():
                cancel_retry()
            self._off_retries.clear()
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
        def state_change_listener(event: Event[EventStateChangedData]) -> None:
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
                "This may indicate high device latency (e.g., Matter smart plug) "
                "or an offline device. Not a skip — the caller decides how to "
                "proceed",
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

    def _compute_cycle_volume_liters(self, duration: float) -> float:
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

    def _resolve_tanks(self) -> tuple[list[TankReading], list[UnknownTankLevel]]:
        """Resolve configured irrigation tanks for the Pump Cycle Gate.

        Each tank is a reading — its current level, or within the grace period
        its last valid one — or an Unknown Tank Level (ADR-0050). An unreadable
        tank is never simply left out.
        """
        growspace = self.growspace
        tanks = growspace.environment_config.irrigation_tanks
        if not tanks:
            return [], []
        now = utcnow()
        readings: list[TankReading] = []
        unknown: list[UnknownTankLevel] = []
        for tank in tanks:
            status = self._tank_watches.status(growspace, tank, now)
            if status.unknown is not None:
                unknown.append(status.unknown)
            elif status.level is not None:
                readings.append(
                    TankReading(
                        name=tank.name,
                        level=status.level,
                        warning_level=tank.warning_level,
                    )
                )
        return readings, unknown

    def tank_diagnostics(self) -> list[dict[str, Any]]:
        """Report every configured tank, including sensors without a valid reading."""
        readings = []
        for tank in self.growspace.environment_config.irrigation_tanks:
            level = self._get_sensor_value(tank.sensor_entity)
            readings.append(
                {
                    "name": tank.name,
                    "sensor_entity": tank.sensor_entity,
                    "valid": level is not None,
                    "level": level,
                    "warning_level": tank.warning_level,
                }
            )
        return readings

    async def _async_fire_low_tank_notification(
        self, tank_name: str, level: float | None
    ) -> None:
        """Fire a persistent HA warning when a cycle is skipped on a tank.

        ``level`` is None for an Unknown Tank Level, which gets its own wording.
        """
        growspace = self.growspace
        message = (
            f"Irrigation skipped in '{growspace.name}': "
            f"tank '{tank_name}' is low ({level:.1f}%). "
            "Refill the reservoir before the next cycle."
            if level is not None
            else f"Irrigation skipped in '{growspace.name}': "
            f"the level of tank '{tank_name}' is unknown. "
            "Check the tank sensor; irrigation resumes once it reports again."
        )
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "message": message,
                "title": (
                    f"Low Tank — {growspace.name}"
                    if level is not None
                    else f"Tank Level Unknown — {growspace.name}"
                ),
                "notification_id": (
                    f"growspace_low_tank_{self._growspace_id}"
                    if level is not None
                    else unknown_tank_skip_notification_id(self._growspace_id)
                ),
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
        if verdict.reason is SkipReason.TANK_UNKNOWN and verdict.unknown_tank:
            await self._async_fire_low_tank_notification(
                verdict.unknown_tank.name, None
            )
        if verdict.reason is not SkipReason.DARK or config.log_to_logbook:
            self._fire_logbook_event(verdict.message, CATEGORY_IRRIGATION_ERROR)

    async def _async_send_off(self, pump_entity: str) -> bool:
        """Command OFF once, bounded, logging rather than raising a refusal.

        A refused or hung command is not the verdict: whether the pump stopped
        is decided by reading it back, which every caller does next. Returns
        whether the command itself went through.
        """
        try:
            await asyncio.wait_for(
                self.hass.services.async_call(
                    "switch", "turn_off", {"entity_id": pump_entity}, blocking=True
                ),
                timeout=PUMP_WATCHDOG_GRACE_SECONDS,
            )
        except Exception:
            _LOGGER.exception("Could not turn off %s", pump_entity)
            return False
        return True

    async def _async_command_off(self, pump_entity: str) -> bool:
        """Command OFF and return whether the pump then reads back OFF.

        This is a stop attempt — a cycle closing, or the watchdog — so a
        refused command counts here, and not on the re-sends that follow an
        OFF-unconfirmed fault.
        """
        if not await self._async_send_off(pump_entity):
            self._record(ReliabilityCounter.COMMAND_FAILURE_OFF)
        return await async_confirm_state(self.hass, pump_entity, STATE_OFF)

    async def _async_off_unconfirmed(
        self, pump_entity: str, code: str, detail: str
    ) -> None:
        """Hold everything when a pump would not read OFF, and keep stopping it.

        The latch comes first, so no later cycle can start while the rest of
        this runs. OFF is then re-sent once at once and every minute after that
        until the pump reads OFF; the fault itself stays latched until an
        administrator acknowledges it.
        """
        # Counted on the latch, so a watchdog and the cycle it cancelled —
        # both reading the same pump not OFF — are one mismatch.
        if await self._latch_fault(code, detail, pump_entity):
            self._record(ReliabilityCounter.OFF_UNCONFIRMED)
        await self._async_send_off(pump_entity)
        await self.hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": f"Pump did not turn off — {self.growspace.name}",
                "message": (
                    f"{detail}. Growspace Manager has stopped every irrigation "
                    f"cycle in '{self.growspace.name}' and will keep sending OFF "
                    "every minute until it reads OFF. Check the pump and its "
                    "relay now, then acknowledge the fault."
                ),
                "notification_id": (
                    f"growspace_pump_off_unconfirmed_{self._growspace_id}_{pump_entity}"
                ),
            },
            blocking=False,
        )
        self._async_start_off_retry(pump_entity)

    @callback
    def _async_start_off_retry(self, pump_entity: str) -> None:
        """Re-send OFF every minute until the pump reads OFF."""
        if pump_entity in self._off_retries:
            return

        async def retry(_now: datetime) -> None:
            state = self.hass.states.get(pump_entity)
            if state is not None and state.state == STATE_OFF:
                self._off_retries.pop(pump_entity)()
                self._fire_logbook_event(
                    f"{pump_entity} reads OFF again — the fault stays latched "
                    "until it is acknowledged",
                    CATEGORY_IRRIGATION_ERROR,
                )
                return
            _LOGGER.warning("Re-sending OFF to %s, which is not OFF", pump_entity)
            await self._async_send_off(pump_entity)

        self._off_retries[pump_entity] = async_track_time_interval(
            self.hass, retry, OFF_RETRY_INTERVAL
        )

    @callback
    def _resume_off_retries(self) -> None:
        """After a restart, keep stopping a latched pump that may still run."""
        store = self._safety_store
        fault = store.faults.get(self._growspace_id) if store else None
        if fault is None or not fault.reason.code.startswith(_OFF_UNCONFIRMED_CODES):
            return
        for output in fault.outputs:
            state = self.hass.states.get(output)
            if state is None or state.state != STATE_OFF:
                self._async_start_off_retry(output)

    async def _async_record_open_failure(
        self, pump_entity: str, reason_code: str, detail: str, *, off_confirmed: bool
    ) -> None:
        """Book a cycle that never opened as not delivered, latching on a run."""
        consecutive = self._open_failures.get(pump_entity, 0) + 1
        self._open_failures[pump_entity] = consecutive
        _LOGGER.warning(
            "%s cycle not delivered (%s, %d in a row): %s",
            self._growspace_id,
            reason_code,
            consecutive,
            detail,
        )
        self._fire_logbook_event(
            f"Cycle not delivered — {detail}", CATEGORY_IRRIGATION_ERROR
        )
        store = self._safety_store
        if store is not None and not store.unreadable:
            await store.async_record_not_delivered(
                self._growspace_id,
                pump_entity,
                reason_code,
                detail,
                consecutive=consecutive,
                off_confirmed=off_confirmed,
            )
        if open_failure_latches(consecutive):
            await self._latch_fault(
                f"fault_{reason_code}:{pump_entity}",
                f"{consecutive} consecutive cycles on {pump_entity} were not "
                f"delivered; the last: {detail}",
                pump_entity,
            )

    async def _async_watchdog_off(
        self, event_type: str, pump_entity: str, cycle_task: asyncio.Task[Any] | None
    ) -> None:
        """Make an independent, bounded OFF attempt when a cycle hangs."""
        _LOGGER.error(
            "Pump watchdog expired for %s (%s)", self._growspace_id, pump_entity
        )
        self._fire_logbook_event(
            f"{event_type.capitalize()} watchdog_off — forcing {pump_entity} OFF",
            CATEGORY_IRRIGATION_ERROR,
        )
        if cycle_task and not cycle_task.done():
            self._watchdog_cancelled_tasks.add(cycle_task)
            cycle_task.cancel()
        if not await self._async_command_off(pump_entity):
            await self._async_off_unconfirmed(
                pump_entity,
                f"fault_watchdog_off_unconfirmed:{pump_entity}",
                f"Watchdog could not confirm {pump_entity} OFF",
            )
        await self._record_safety_transition("watchdog_off")

    def _operator_hold(self, *, manual: bool) -> str | None:
        """Return the operator control holding this cycle back, if any.

        Growspace automation off holds every cycle, and a disarmed irrigation
        every automatic one; an emergency stop turns automation off, and is
        named as itself. Checked on admission and again just before ON.
        """
        store = self._safety_store
        if store is None or (
            store.automation_enabled(self._growspace_id)
            and (manual or store.irrigation_armed(self._growspace_id))
        ):
            # A person holding the pumps holds manual runs too (#793).
            return self._person_hold()
        if store.emergency_stop_for(self._growspace_id):
            return SkipReason.EMERGENCY_STOP.value
        if not store.automation_enabled(self._growspace_id):
            return "automation_off"
        return "irrigation_disarmed"

    async def _run_pump_cycle(  # noqa: C901 - safety effect shell handles every exit
        self,
        event_type: str,
        pump_entity: str,
        duration: int,
        event_data: Mapping[str, Any],
    ) -> None:
        """Run the on-off cycle for a pump and send notifications."""
        self._record(ReliabilityCounter.REQUESTED)
        store = self._safety_store
        manual = bool(event_data.get("manual", False))
        hold = self._operator_hold(manual=manual)
        if hold is None and not self._in_flight(pump_entity):
            pump_state = self.hass.states.get(pump_entity)
            if pump_state is not None and pump_state.state == STATE_ON:
                # Already running, and not by us: confirming ON would book a
                # person's water as ours and then switch it off under them.
                await self._async_observe_on(pump_entity)
                hold = self._operator_hold(manual=manual)
        if hold is not None:
            self._record(skipped(hold))
            if hold in (MANUAL_OVERRIDE, OVERRIDE_DETECTED):
                await self._async_record_controller_state()
            return
        # Ask the Pump Cycle Gate whether this cycle may fire (ADR-0021). The
        # gate is a pure decision; this method owns the resulting effects.
        config = self.growspace.irrigation_config
        limit = cycle_runtime_limit(config)
        if duration > limit:
            _LOGGER.warning(
                "Clamping %s cycle for %s from %ss to %ss",
                event_type,
                self._growspace_id,
                duration,
                limit,
            )
            duration = limit
        snapshot = self.controller_snapshot()
        latched = snapshot.requires_ack
        startup = None if latched else self.startup_inhibit_reason()
        cycle_volume_l = self._compute_cycle_volume_liters(duration)
        tank_readings, unknown_tanks = ([], []) if latched else self._resolve_tanks()
        verdict = decide_cycle(
            event_type=event_type,
            is_manual=manual,
            config=config,
            tank_readings=tank_readings,
            unknown_tanks=unknown_tanks,
            lights_dark=False if latched else self._is_lights_dark(),
            cycles_today=self._cycles_today,
            volume_today=self._volume_dispensed_today,
            cycle_volume_l=cycle_volume_l,
            fault=snapshot.state.value == "fault",
            emergency_stop=snapshot.state.value == "emergency_stop",
            startup_inhibit=startup.detail if startup else None,
        )
        if not verdict.fire:
            self._record(skipped(verdict.reason.value if verdict.reason else "unknown"))
            if verdict.reason not in (SkipReason.FAULT, SkipReason.EMERGENCY_STOP):
                await self._record_safety_transition(
                    "inhibited", verdict.reason.value if verdict.reason else None
                )
            await self._apply_skip_verdict(config, verdict)
            return

        await self._record_safety_transition("running")

        # Track active event for frontend animation
        self._active_events[event_type] = {
            "start": utcnow().isoformat(),
            "duration": duration,
        }
        self._main_coordinator.async_update_listeners()

        start_dt = None
        cycle_finished = False
        abort_cause: AbortCause | None = None
        moisture_before = None
        off_confirmed = False
        closing = False
        # A cycle that could not be opened: (reason code, detail). Booked as
        # not delivered once the pump has been read back OFF (#785).
        open_failure: tuple[str, str] | None = None
        # Whether turn_on was sent. A cycle stopped before it sends no OFF
        # either: Growspace Manager stops only what it started (#793).
        commanded = False
        cycle_task = asyncio.current_task()
        # The ON wait is part of a healthy cycle, so the deadline allows for it.
        deadline = (
            monotonic_time.monotonic()
            + ON_CONFIRM_TIMEOUT_SECONDS
            + duration
            + PUMP_WATCHDOG_GRACE_SECONDS
        )

        @callback
        def watchdog_callback(_now: datetime) -> None:
            # Scheduled by HA's event loop, independently of the cycle task.
            # Once the cycle is closing it is bounded on its own — a bounded
            # OFF, a bounded readback — and must not be cancelled mid-readback.
            if not off_confirmed and not closing:
                self.hass.async_create_task(
                    self._async_watchdog_off(event_type, pump_entity, cycle_task),
                    name=f"pump_watchdog_{self._growspace_id}_{event_type}",
                )

        cancel_watchdog = async_call_later(
            self.hass,
            max(0.0, deadline - monotonic_time.monotonic()),
            watchdog_callback,
        )

        try:
            # Capture moisture before starting
            moisture_before = self._moisture_value()

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

            command_dt = utcnow()
            if self._operator_hold(manual=manual) is not None:
                abort_cause = AbortCause.OVERRIDE
                return
            commanded = True
            self._commanded_outputs.add(pump_entity)
            try:
                await self.hass.services.async_call(
                    "switch", "turn_on", {"entity_id": pump_entity}, blocking=True
                )
            except Exception as err:  # noqa: BLE001 — every refusal fails closed
                self._record(ReliabilityCounter.COMMAND_FAILURE_ON)
                # The command may still have reached the relay, so the pump is
                # stopped and read back in ``finally`` like any other cycle.
                open_failure = (
                    ON_COMMAND_FAILED,
                    f"{pump_entity} refused turn_on: {err}",
                )
                return

            # Wait for switch to confirm ON state (critical for Matter smart plugs)
            if not await self._async_wait_for_switch_state(
                pump_entity, "on", timeout=ON_CONFIRM_TIMEOUT_SECONDS
            ):
                self._record(ReliabilityCounter.ON_UNCONFIRMED)
                # The pump may be running, but a missing ON readback cannot
                # establish delivered water: stop it and book nothing.
                open_failure = (
                    ON_UNCONFIRMED,
                    f"{pump_entity} did not confirm ON within "
                    f"{ON_CONFIRM_TIMEOUT_SECONDS:g}s of turn_on at "
                    f"{command_dt.isoformat()}",
                )
                return

            # Start timing AFTER switch confirms ON: the device reported the
            # relay closing, so that is when water started moving.
            start_dt = utcnow()
            self._record(ReliabilityCounter.FIRED)
            self._open_failures.pop(pump_entity, None)
            self._reliability.mark_active(self._growspace_id, pump_entity)

            if event_type == "irrigation":
                self._last_cycle_timestamp = start_dt.isoformat()
                # Written the moment the pump confirms, not at the end of the
                # cycle, so a restart mid-shot still knows this shot happened.
                self._main_coordinator.async_schedule_save()

            await self._async_send_cycle_notification(event_type, duration, event_data)

            await asyncio.sleep(duration)
            cycle_finished = True

        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task in self._watchdog_cancelled_tasks:
                abort_cause = AbortCause.WATCHDOG
                self._watchdog_cancelled_tasks.discard(current_task)
            elif current_task in self._override_cancelled_tasks:
                abort_cause = AbortCause.OVERRIDE
                self._override_cancelled_tasks.discard(current_task)
            elif store and store.emergency_stop_for(self._growspace_id):
                abort_cause = AbortCause.E_STOP
            else:
                abort_cause = AbortCause.CANCEL
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
            abort_cause = AbortCause.ERROR
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
            if abort_cause is not None:
                self._record(aborted(abort_cause))

            try:
                # Ensure start_dt is defined
                if start_dt:
                    duration_sec = (end_dt - start_dt).total_seconds()

                    # Update daily counters for completed irrigation cycles.
                    # The planned duration is normally the driver — asyncio.sleep
                    # is what the pump runs for — but a late wake-up can run the
                    # pump past it. Book whichever is larger so the daily volume
                    # and its cap never under-count water that physically flowed.
                    # A cycle that never confirmed ON has no start_dt and books
                    # nothing here; it is recorded as not delivered instead.
                    if event_type == "irrigation":
                        billed_volume_l = max(
                            cycle_volume_l,
                            self._compute_cycle_volume_liters(duration_sec),
                        )
                        self._cycles_today += 1
                        self._volume_dispensed_today += billed_volume_l
                        self._record(
                            ReliabilityCounter.ESTIMATED_WATER_L, billed_volume_l
                        )
                        await self._async_record_pump_water(billed_volume_l)

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
            closing = True
            off_confirmed = (
                await self._async_command_off(pump_entity) if commanded else True
            )
            if start_dt is not None:
                if cycle_finished:
                    self._record(
                        ReliabilityCounter.COMPLETED_VERIFIED
                        if off_confirmed
                        else ReliabilityCounter.COMPLETED_UNVERIFIED
                    )
                if not manual:
                    self._record(
                        automated_seconds(pump_entity),
                        max(0.0, (end_dt - start_dt).total_seconds()),
                    )
            try:
                if not off_confirmed:
                    await self._async_off_unconfirmed(
                        pump_entity,
                        f"fault_off_unconfirmed:{pump_entity}",
                        f"{pump_entity} did not read back OFF after turn_off",
                    )
                if open_failure is not None:
                    await self._async_record_open_failure(
                        pump_entity, *open_failure, off_confirmed=off_confirmed
                    )
            finally:
                cancel_watchdog()
                # Read back OFF, or handed to the OFF retries: no longer ours.
                self._commanded_outputs.discard(pump_entity)
                self._reliability.clear_active(self._growspace_id, pump_entity)
                self._active_events.pop(event_type, None)
                self._main_coordinator.async_update_listeners()
            if off_confirmed:
                state = self.controller_snapshot()
                if not state.requires_ack:
                    await self._record_safety_transition(
                        state.state.value,
                        state.reasons[0].code if state.reasons else None,
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

        moisture_after = self._moisture_value()

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
        snapshot = self.controller_snapshot()
        if snapshot.requires_ack:
            raise ServiceValidationError(
                f"Irrigation is {snapshot.state.value} for growspace '{self._growspace_id}'"
            )
        if held := self._override_reasons():
            raise ServiceValidationError(
                f"Irrigation in growspace '{self._growspace_id}' is held: "
                f"{held[0].detail}"
            )
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
        limit = cycle_runtime_limit(options)
        if effective_duration > limit:
            raise ServiceValidationError(
                f"Irrigation duration exceeds max_cycle_seconds ({limit}s)"
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
            self._override_cancelled_tasks.add(self._running_tasks["irrigation"])
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
        self._resume_off_retries()
        await self._async_begin_startup_inhibit()

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
            events = schedulable_events([dict(item) for item in times])
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
        if event_type == "irrigation" and self._last_cycle_timestamp:
            last = datetime.fromisoformat(self._last_cycle_timestamp)
            minimum = timedelta(
                minutes=self.growspace.irrigation_config.min_interval_minutes
            )
            if now - last < minimum:
                _LOGGER.info(
                    "Skipping irrigation event for %s: minimum interval is %s minutes",
                    self._growspace_id,
                    self.growspace.irrigation_config.min_interval_minutes,
                )
                return
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
            [dict(item) for item in self.growspace.irrigation_config.irrigation_times],
            utcnow(),
        )
        return soonest.isoformat() if soonest else None
