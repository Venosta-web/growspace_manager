"""Grow Light Coordinator for Growspace Manager.

Drives a growspace's grow lights from the photoperiod schedule (ADR-0023). It is
not sensor-regulated and follows two paths by device kind: plain ``switch.*`` /
``light.*`` lights are ticked live (each 10s tick reconciles to the desired
level — ``power`` inside the photoperiod, off outside it — so control is
level-based and self-heals across restarts), while AC Infinity lights are
configured once into their onboard ``Schedule`` mode and then run autonomously.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.util import dt as dt_util

from .actuator_driver import resolve_actuator_drivers
from .domain.light_schedule import (
    desired_grow_light_power,
    resolve_cycle_end_time,
    resolve_photoperiod_hours,
)
from .grow_light_ac_infinity import push_ac_infinity_schedule

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models import EnvironmentConfig, Growspace

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)


class GrowLightCoordinator:
    """Drives a growspace's grow lights on its photoperiod schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the GrowLightCoordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_tick: Callable[[], None] | None = None

    @property
    def _growspace(self) -> Growspace | None:
        return self.main_coordinator.growspaces.get(self.growspace_id)

    @property
    def _env_config(self) -> EnvironmentConfig | None:
        gs = self._growspace
        return gs.environment_config if gs else None

    @property
    def _has_growlight_actuators(self) -> bool:
        """Whether any grow light — plain or AC Infinity — is configured."""
        env = self._env_config
        return bool(
            env and (env.growlight_entities or env.growlight_ac_infinity_devices)
        )

    async def async_setup(self) -> None:
        """Activate the controller: tick plain lights, configure AC Infinity ones."""
        env = self._env_config
        if env is None or not env.growlight_config.enabled:
            return
        if not self._has_growlight_actuators:
            return

        # Plain lights have no onboard schedule, so GSM ticks them live.
        if env.growlight_entities:
            self._remove_tick = async_track_time_interval(
                self.hass, self._on_tick, _TICK_INTERVAL
            )

        # AC Infinity lights are configured once and then run autonomously.
        if env.growlight_ac_infinity_devices:
            await self._push_ac_infinity_schedules(env)

        _LOGGER.info("GrowLightCoordinator started for %s", self.growspace_id)

    @callback
    def _on_tick(self, _now: object) -> None:
        """Handle the polling tick — schedule async reconciliation."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_regulate(), "grow_light_regulate"
        )

    async def _async_regulate(self) -> None:
        """Reconcile every configured grow light to its desired power."""
        env = self._env_config
        if env is None or not env.growlight_config.enabled:
            return

        power = self._desired_power(env)
        drivers = resolve_actuator_drivers(self.hass, env.growlight_entities)
        for driver in drivers:
            await driver.set_speed(power)

    def _desired_power(self, env: EnvironmentConfig) -> int:
        """Compute the demand for now from the photoperiod schedule."""
        gs = self._growspace
        assert gs is not None  # guarded by callers via _env_config
        photoperiod_hours = self._photoperiod_hours(env)
        return desired_grow_light_power(
            dt_util.now(),
            gs.irrigation_strategy.lights_on_time,
            photoperiod_hours,
            env.growlight_config.power,
        )

    def _photoperiod_hours(self, env: EnvironmentConfig) -> float:
        """Resolve today's day length from plant stage."""
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        return resolve_photoperiod_hours(
            plants, env.veg_day_hours, env.flower_day_hours, dt_util.now().date()
        )

    async def _push_ac_infinity_schedules(self, env: EnvironmentConfig) -> None:
        """Write the derived schedule to every configured AC Infinity grow light."""
        gs = self._growspace
        assert gs is not None  # guarded by callers via _env_config
        on_time = gs.irrigation_strategy.lights_on_time
        off_time = resolve_cycle_end_time(on_time, self._photoperiod_hours(env))
        for device in env.growlight_ac_infinity_devices:
            await push_ac_infinity_schedule(
                self.hass,
                device,
                on_time=on_time,
                off_time=off_time,
                power=env.growlight_config.power,
            )

    async def async_restart(self) -> None:
        """Restart the reconcile tick after a config change."""
        self.unload()
        await self.async_setup()

    def unload(self) -> None:
        """Stop the reconcile tick."""
        if self._remove_tick is not None:
            self._remove_tick()
            self._remove_tick = None
