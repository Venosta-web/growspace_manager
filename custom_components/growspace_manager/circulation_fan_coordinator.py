"""Circulation Fan Coordinator for Growspace Manager."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
import time
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from .const import FanRegulationMode
from .domain.day_night import DayNightTracker
from .domain.fan_control import (
    FAN_VPD_STAGE_DEFAULTS,
    compute_fan_speed,
    compute_wind_offset,
    evaluate_temp_override,
    resolve_stage_vpd_target,
)

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models import CirculationFanConfig, EnvironmentConfig

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)

# Re-exported from .domain.fan_control so existing importers keep working.
__all__ = [
    "FAN_VPD_STAGE_DEFAULTS",
    "CirculationFanCoordinator",
    "compute_fan_speed",
    "compute_wind_offset",
    "evaluate_temp_override",
]


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
        self._temp_override_active: bool = False
        self._temp_override_direction: str | None = None
        self._start_time: float = 0.0
        self._day_night = DayNightTracker(growspace_id)

    @property
    def _env_config(self) -> EnvironmentConfig | None:
        gs = self.main_coordinator.growspaces.get(self.growspace_id)
        return gs.environment_config if gs else None

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

        self._start_time = time.monotonic()
        self._remove_tick = async_track_time_interval(
            self.hass, self._on_tick, _TICK_INTERVAL
        )
        _LOGGER.info(
            "CirculationFanCoordinator started for %s", self.growspace_id
        )

    @callback
    def _on_tick(self, _now: object) -> None:
        """Handle polling tick — schedule async regulation."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_regulate(), "circulation_fan_regulate"
        )

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
        elif cfg.regulation_mode == FanRegulationMode.VPD:
            if cfg.stage_vpd_enabled:
                light_sensors = self._env_config.light_sensors if self._env_config else []
                is_day = self._day_night.determine(self.hass, light_sensors)
                effective_vpd_target = self._get_stage_vpd_target(cfg, is_day)
            else:
                effective_vpd_target = cfg.vpd_target
            speed = compute_fan_speed(
                sensor_value,
                effective_vpd_target,
                cfg.vpd_tolerance,
                cfg.min_speed,
                cfg.max_speed,
            )
            if cfg.critical_temp_low is not None or cfg.critical_temp_high is not None:
                temp_value = self._read_sensor(FanRegulationMode.TEMPERATURE)
                if temp_value is not None:
                    speed, self._temp_override_active, self._temp_override_direction = (
                        evaluate_temp_override(
                            temp_value,
                            cfg.critical_temp_low,
                            cfg.critical_temp_high,
                            cfg.critical_temp_hysteresis,
                            self._temp_override_active,
                            self._temp_override_direction,
                            speed,
                            cfg.min_speed,
                            cfg.max_speed,
                        )
                    )
        else:
            return

        if cfg.wind_enabled:
            elapsed = time.monotonic() - self._start_time
            wind_offset = compute_wind_offset(
                cfg.wind_amplitude_pct, elapsed, cfg.wind_period_seconds
            )
            speed = max(cfg.min_speed, min(cfg.max_speed, round(speed + wind_offset)))

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

    def _get_stage_vpd_target(self, cfg: CirculationFanConfig, is_day: bool) -> float:
        """Resolve the effective VPD target from stage defaults.

        Falls back to the static vpd_target when the growspace has no plants.
        """
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        return resolve_stage_vpd_target(
            plants, cfg.stage_vpd_overrides, cfg.vpd_target, is_day
        )

    def _read_sensor(self, mode: FanRegulationMode) -> float | None:
        """Read the first available sensor value for the given regulation mode."""
        if mode == FanRegulationMode.HUMIDITY:
            sensors = self._env_config.humidity_sensors
        elif mode == FanRegulationMode.TEMPERATURE:
            sensors = self._env_config.temperature_sensors
        elif mode == FanRegulationMode.VPD:
            sensors = self._env_config.vpd_sensors
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

    async def async_restart(self) -> None:
        """Restart the polling tick after a config change."""
        self.unload()
        self._temp_override_active = False
        self._temp_override_direction = None
        self._start_time = 0.0
        await self.async_setup()

    def unload(self) -> None:
        """Stop the polling tick."""
        if self._remove_tick is not None:
            self._remove_tick()
            self._remove_tick = None
