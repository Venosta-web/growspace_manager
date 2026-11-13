"""Run Supplemental Light Windows on Home Assistant light and switch entities."""

from __future__ import annotations

from datetime import time
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_OFF, STATE_ON
from homeassistant.core import Event, EventStateChangedData, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
)
import homeassistant.util.dt as dt_util

from .actuator_driver import async_confirm_state, resolve_actuator_driver
from .domain.light_schedule import resolve_photoperiod_hours
from .domain.manual_override import Subsystem
from .domain.supplemental_light_schedule import (
    DAY_MINUTES,
    LightPeriod,
    current_or_next_period,
    resolve_windows,
)
from .exceptions import GrowspaceNotFoundError
from .lighting_assignments import lighting_assignment_lock, lighting_assignments

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime

    from .coordinator import GrowspaceCoordinator
    from .models import Growspace
    from .models.supplemental_light import SupplementalLight

_NO_MAIN_CYCLE = "A valid managed main-light cycle is required."


class SupplementalLightCoordinator:
    """Own the timers, commands and configuration writes for one growspace."""

    def __init__(self, coordinator: GrowspaceCoordinator, growspace_id: str) -> None:
        """Bind the controller to the live growspace and Home Assistant."""
        self.coordinator = coordinator
        self.hass = coordinator.hass
        self.growspace_id = growspace_id
        self._listeners: list[Callable[[], None]] = []
        self._command_errors: dict[str, str] = {}
        self._active = False
        self._pending = False

    @property
    def _growspace(self) -> Growspace:
        return self.coordinator.growspaces[self.growspace_id]

    async def async_setup(self) -> None:
        """Restore listeners and apply the current schedule on startup."""
        self._active = True
        self._listen()
        if self._growspace.supplemental_lights:
            await self.async_reconcile()

    def unload(self) -> None:
        """Detach the controller while keeping its assignments persisted."""
        self._active = False
        self._unlisten()

    def _unlisten(self) -> None:
        for unsubscribe in self._listeners:
            unsubscribe()
        self._listeners.clear()

    def _listen(self) -> None:
        self._unlisten()
        entities = [
            light.entity_id
            for light in self._growspace.supplemental_lights
            if light.enabled
        ]
        if not self._active or not entities:
            return
        self._listeners.extend(
            (
                async_track_time_change(self.hass, self._schedule_reconcile, second=0),
                async_track_state_change_event(
                    self.hass, entities, self._on_state_changed
                ),
                self.coordinator.async_add_listener(self._schedule_reconcile),
                self.coordinator.irrigation_safety.add_override_listener(
                    self._on_override
                ),
            )
        )

    @callback
    def _on_state_changed(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if new is not None and (old is None or old.state != new.state):
            self._schedule_reconcile()

    @callback
    def _on_override(self, growspace_id: str, subsystem: Subsystem) -> None:
        if growspace_id == self.growspace_id and subsystem == Subsystem.LIGHTS:
            self._schedule_reconcile()

    @callback
    def _schedule_reconcile(self, _event: object = None) -> None:
        if self._pending or not self._active:
            return
        self._pending = True
        self.coordinator.config_entry.async_create_background_task(
            self.hass, self.async_reconcile(), "supplemental_light_reconcile"
        )

    def _cycle(self, now: datetime) -> tuple[int, int] | None:
        space = self._growspace
        env = space.environment_config
        if not env.growlight_config.enabled or not (
            env.growlight_entities or env.growlight_ac_infinity_devices
        ):
            return None
        try:
            start = time.fromisoformat(space.light_cycle.lights_on_time)
        except ValueError:
            return None
        plants = self.coordinator.services.growspaces.get_growspace_plants(space.id)
        duration = round(
            resolve_photoperiod_hours(
                plants, env.veg_day_hours, env.flower_day_hours, now.date()
            )
            * 60
        )
        if not 0 < duration <= DAY_MINUTES:
            return None
        return start.hour * 60 + start.minute, duration

    def _ownership_problem(self, light: SupplementalLight) -> str | None:
        for space, role, entity in lighting_assignments(
            self.coordinator, self._growspace
        ):
            if entity == light.entity_id and (
                space is not self._growspace or role == "main light"
            ):
                return f"{entity} is already assigned as a {role} in {space.name}."
        return None

    def _hold_reason(self) -> str | None:
        safety = self.coordinator.irrigation_safety
        if safety.override_for(self.growspace_id, Subsystem.LIGHTS) is not None:
            return "Lights Manual Override is active."
        if not safety.commands_allowed(self.growspace_id, Subsystem.LIGHTS):
            return "Growspace automation is stopped."
        return None

    def _reported_state(self, entity_id: str) -> str:
        state = self.hass.states.get(entity_id)
        return state.state if state is not None else "unavailable"

    def _period(
        self, light: SupplementalLight, now: datetime, cycle: tuple[int, int] | None
    ) -> tuple[LightPeriod | None, bool, list[str]]:
        if cycle is None:
            return None, False, []
        start, duration = cycle
        periods, reasons = resolve_windows(light.windows, duration)
        elapsed = (now.hour * 60 + now.minute - start) % DAY_MINUTES
        period, running = current_or_next_period(periods, elapsed)
        return period, running, reasons

    def status(self) -> dict[str, Any]:
        """Report the cycle, device state and active or next union of windows."""
        now = dt_util.now()
        cycle = self._cycle(now)
        lights = []
        for light in self._growspace.supplemental_lights:
            period, running, warnings = self._period(light, now, cycle)
            state = self._reported_state(light.entity_id)
            reason = (
                "Supplemental Light is disabled."
                if not light.enabled
                else self._ownership_problem(light) or self._hold_reason()
            )
            if reason is None and state not in (STATE_ON, STATE_OFF):
                reason = "Output is unavailable."
            if reason is None and cycle is None:
                reason = _NO_MAIN_CYCLE
            if reason is None:
                reason = self._command_errors.get(light.entity_id)
            if reason is None and not running:
                reason = (
                    "Outside the scheduled windows." if period else "No valid windows."
                )
            lights.append(
                {
                    "light": light.to_dict(),
                    "state": state,
                    "active": running,
                    "window": period.resolve(cycle[0]) if period and cycle else None,
                    "reason": reason,
                    "warnings": warnings,
                }
            )
        return {
            "cycle": (
                {"start_minute": cycle[0], "duration_minutes": cycle[1]}
                if cycle
                else None
            ),
            "lights": lights,
        }

    async def _command(self, entity: str, turn_on: bool) -> None:
        driver = resolve_actuator_driver(self.hass, entity, raise_errors=True)
        if driver is None:
            raise ValueError(f"{entity} is not a supported Supplemental Light output.")
        if turn_on:
            await driver.turn_on()
        else:
            await driver.turn_off()

    async def async_reconcile(self) -> None:
        """Follow the current clock and never replay a window lost to downtime."""
        async with lighting_assignment_lock(self.hass):
            self._pending = False
            if not self._active or self.growspace_id not in self.coordinator.growspaces:
                return
            for light in self._growspace.supplemental_lights:
                if not self._active or self._hold_reason():
                    return
                if light.enabled and self._ownership_problem(light) is None:
                    await self._reconcile_light(light)

    async def _reconcile_light(self, light: SupplementalLight) -> None:
        entity = light.entity_id
        state = self._reported_state(entity)
        now = dt_util.now()
        _, running, _ = self._period(light, now, self._cycle(now))
        if state not in (STATE_ON, STATE_OFF):
            return
        if running == (state == STATE_ON):
            self._command_errors.pop(entity, None)
            return
        try:
            await self._command(entity, running)
        except Exception as err:  # noqa: BLE001 - an actuator can fail with any exception
            action = "on" if running else "off"
            self._command_errors[entity] = f"Could not switch {entity} {action}: {err}"
        else:
            self._command_errors.pop(entity, None)

    async def _try_release(self, light: SupplementalLight) -> str | None:
        entity = light.entity_id
        if reason := self._ownership_problem(light) or self._hold_reason():
            return reason
        if self._reported_state(entity) not in (STATE_ON, STATE_OFF):
            return f"{entity} is unavailable."
        try:
            await self._command(entity, False)
        except Exception as err:  # noqa: BLE001 - an actuator can fail with any exception
            return f"Could not switch {entity} off: {err}"
        if not await async_confirm_state(self.hass, entity, STATE_OFF, first_read=0):
            return f"{entity} did not report off after the command."
        return None

    async def async_save(
        self,
        original_entity: str | None,
        light: SupplementalLight | None,
        release_anyway: bool,
    ) -> dict[str, Any]:
        """Validate, safely release the old output, and persist the change."""
        async with lighting_assignment_lock(self.hass):
            space = self.coordinator.growspaces.get(self.growspace_id)
            if space is None:
                raise GrowspaceNotFoundError(
                    f"Growspace {self.growspace_id} not found."
                )
            previous = space.supplemental_lights
            old = next(
                (item for item in previous if item.entity_id == original_entity), None
            )
            if original_entity is not None and old is None:
                raise ValueError("The original Supplemental Light no longer exists.")
            if light is not None:
                self._validate_light(light, old)
            if (
                old is not None
                and old.enabled
                and (
                    light is None
                    or not light.enabled
                    or light.entity_id != old.entity_id
                )
                and (reason := await self._try_release(old))
                and not release_anyway
            ):
                return {
                    "release_required": {"entity_id": old.entity_id, "reason": reason}
                }

            space.supplemental_lights = [item for item in previous if item is not old]
            if light is not None:
                index = previous.index(old) if old else len(previous)
                space.supplemental_lights.insert(index, light)
            try:
                await self.coordinator.services.save()
            except Exception:
                space.supplemental_lights = previous
                self._schedule_reconcile()
                raise
            if old is not None:
                self._command_errors.pop(old.entity_id, None)
            self._listen()
        await self.async_reconcile()
        return {"release_required": None}

    def _validate_light(
        self, light: SupplementalLight, old: SupplementalLight | None
    ) -> None:
        if problem := self._ownership_problem(light):
            raise ValueError(problem)
        if any(
            item is not old and item.entity_id == light.entity_id
            for item in self._growspace.supplemental_lights
        ):
            raise ValueError(
                f"{light.entity_id} is already assigned as a supplemental light "
                f"in {self._growspace.name}."
            )

        # Disabling a formerly valid assignment must remain possible after
        # a main schedule edit or removal makes its saved windows invalid.
        if (
            old
            and not light.enabled
            and light.entity_id == old.entity_id
            and light.windows == old.windows
        ):
            return
        cycle = self._cycle(dt_util.now())
        if cycle is None:
            raise ValueError(_NO_MAIN_CYCLE)
        _, reasons = resolve_windows(light.windows, cycle[1])
        if reasons:
            raise ValueError(" ".join(reasons))

    async def async_release_all(self) -> None:
        """Switch off assigned outputs before their growspace is removed."""
        for light in self._growspace.supplemental_lights:
            if light.enabled and (reason := await self._try_release(light)):
                raise HomeAssistantError(
                    f"{reason} Release {light.entity_id} in Growlights before removing the growspace."
                )
