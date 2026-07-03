"""Grow Light Coordinator for Growspace Manager.

Drives a growspace's plain ``switch.*`` / ``light.*`` grow lights from the
photoperiod schedule (ADR-0023 plain path). Unlike the fan controllers this is
not sensor-regulated: each tick reconciles the light to its desired level —
``power`` inside the photoperiod, off outside it — so control is level-based and
self-heals across restarts and missed ticks rather than firing edge transitions.
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
from .domain.light_schedule import desired_grow_light_power, resolve_photoperiod_hours

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models import EnvironmentConfig, Growspace

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)


class GrowLightCoordinator:
    """Drives plain grow lights on the growspace's photoperiod schedule."""

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
        """Whether any plain grow light is configured."""
        env = self._env_config
        return bool(env and env.growlight_entities)

    async def async_setup(self) -> None:
        """Start the 10-second reconcile tick when enabled and configured."""
        env = self._env_config
        if env is None or not env.growlight_config.enabled:
            return
        if not self._has_growlight_actuators:
            return

        self._remove_tick = async_track_time_interval(
            self.hass, self._on_tick, _TICK_INTERVAL
        )
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
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        now = dt_util.now()
        photoperiod_hours = resolve_photoperiod_hours(
            plants, env.veg_day_hours, env.flower_day_hours, now.date()
        )
        return desired_grow_light_power(
            now,
            gs.irrigation_strategy.lights_on_time,
            photoperiod_hours,
            env.growlight_config.power,
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
