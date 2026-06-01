"""Circulation Fan Coordinator for Growspace Manager."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from .const import FanRegulationMode

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)


def compute_fan_speed(
    value: float,
    target: float,
    tolerance: float,
    min_speed: int,
    max_speed: int,
) -> int:
    """Compute fan speed via linear mapping of value relative to target band.

    Below (target - tolerance): min_speed
    Above (target + tolerance): max_speed
    Inside the band: linearly interpolated
    """
    lower = target - tolerance
    upper = target + tolerance
    if value <= lower:
        return min_speed
    if value >= upper:
        return max_speed
    t = (value - lower) / (upper - lower)
    return round(min_speed + t * (max_speed - min_speed))


class CirculationFanCoordinator:
    """Controls circulation fans via linear speed regulation on humidity or temperature."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the CirculationFanCoordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_tick: Callable[[], None] | None = None

        growspace = self.main_coordinator.growspaces.get(growspace_id)
        if not growspace:
            _LOGGER.error(
                "Growspace %s not found for CirculationFanCoordinator", growspace_id
            )
            self._env_config = None
            return

        self._env_config = growspace.environment_config

    async def async_setup(self) -> None:
        """Start the 10-second polling tick."""
        if self._env_config is None:
            return

        cfg = self._env_config.circulation_fan_config
        if not cfg.enabled:
            _LOGGER.debug(
                "CirculationFanCoordinator disabled for %s", self.growspace_id
            )
            return

        if not self._env_config.circulation_fan_entities:
            _LOGGER.debug(
                "CirculationFanCoordinator: no fan entities for %s", self.growspace_id
            )
            return

        self._remove_tick = async_track_time_interval(
            self.hass, self._on_tick, _TICK_INTERVAL
        )
        _LOGGER.info(
            "CirculationFanCoordinator started for %s", self.growspace_id
        )

    @callback
    def _on_tick(self, _now: object) -> None:
        """Handle polling tick — schedule async regulation."""
        self.hass.async_create_task(self._async_regulate())

    async def _async_regulate(self) -> None:
        """Read sensor, compute speed, and call fan.set_percentage on each entity."""
        if self._env_config is None:
            return

        cfg = self._env_config.circulation_fan_config
        if not cfg.enabled:
            return

        sensor_value = self._read_sensor(cfg.regulation_mode)
        if sensor_value is None:
            return

        if cfg.regulation_mode == FanRegulationMode.HUMIDITY:
            speed = compute_fan_speed(
                sensor_value,
                cfg.humidity_target,
                cfg.humidity_tolerance,
                cfg.min_speed,
                cfg.max_speed,
            )
        elif cfg.regulation_mode == FanRegulationMode.TEMPERATURE:
            speed = compute_fan_speed(
                sensor_value,
                cfg.temperature_target,
                cfg.temperature_tolerance,
                cfg.min_speed,
                cfg.max_speed,
            )
        else:
            return

        for entity_id in self._env_config.circulation_fan_entities:
            try:
                await self.hass.services.async_call(
                    "fan",
                    "set_percentage",
                    {ATTR_ENTITY_ID: entity_id, "percentage": speed},
                    blocking=False,
                )
            except (HomeAssistantError, TimeoutError):
                _LOGGER.warning(
                    "Failed to set percentage on %s", entity_id, exc_info=True
                )

    def _read_sensor(self, mode: FanRegulationMode) -> float | None:
        """Read the first available sensor value for the given regulation mode."""
        if mode == FanRegulationMode.HUMIDITY:
            sensors = self._env_config.humidity_sensors
        elif mode == FanRegulationMode.TEMPERATURE:
            sensors = self._env_config.temperature_sensors
        else:
            return None

        if not sensors:
            return None

        state = self.hass.states.get(sensors[0])
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def unload(self) -> None:
        """Stop the polling tick."""
        if self._remove_tick is not None:
            self._remove_tick()
            self._remove_tick = None
