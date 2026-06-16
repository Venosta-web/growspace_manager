"""Exhaust Fan Coordinator for Growspace Manager.

Drives the configured exhaust devices on a fixed tick using a combined demand
signal: the maximum of a temperature term, a humidity term and an inverted-VPD
term (see ADR 0018 and CONTEXT.md "Exhaust Demand"). Unlike the circulation
fan, exhaust has no single regulation mode and no dynamic wind layer.

This slice excludes the source-air gate and the critical-temperature override —
those are handled by separate slices.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from .const import FanRegulationMode
from .domain.day_night import DayNightTracker
from .domain.fan_control import compute_exhaust_demand, resolve_stage_vpd_target
from .utils import VPDCalculator

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models import EnvironmentConfig, ExhaustFanConfig

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)

# Entity domains driven on/off rather than by percentage.
_SWITCH_DOMAINS = ("switch", "input_boolean")


class ExhaustFanCoordinator:
    """Controls exhaust devices via combined temperature/humidity/VPD demand."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
    ) -> None:
        """Initialize the ExhaustFanCoordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._remove_tick: Callable[[], None] | None = None
        self._day_night = DayNightTracker(growspace_id)

    @property
    def _env_config(self) -> EnvironmentConfig | None:
        gs = self.main_coordinator.growspaces.get(self.growspace_id)
        return gs.environment_config if gs else None

    async def async_setup(self) -> None:
        """Start the polling tick when enabled and exhaust entities are configured."""
        if self._env_config is None:
            return

        cfg = self._env_config.exhaust_fan_config
        if not cfg.enabled:
            _LOGGER.debug("ExhaustFanCoordinator disabled for %s", self.growspace_id)
            return

        if not self._env_config.exhaust_fan_entities:
            _LOGGER.debug(
                "ExhaustFanCoordinator: no exhaust entities for %s", self.growspace_id
            )
            return

        self._remove_tick = async_track_time_interval(
            self.hass, self._on_tick, _TICK_INTERVAL
        )
        _LOGGER.info("ExhaustFanCoordinator started for %s", self.growspace_id)

    @callback
    def _on_tick(self, _now: object) -> None:
        """Handle polling tick — schedule async regulation."""
        self.config_entry.async_create_background_task(
            self.hass, self._async_regulate(), "exhaust_fan_regulate"
        )

    async def _async_regulate(self) -> None:
        """Read sensors, compute combined demand, and dispatch to each device."""
        if self._env_config is None:
            return

        cfg = self._env_config.exhaust_fan_config
        if not cfg.enabled or not self._env_config.exhaust_fan_entities:
            return

        vpd_target = self._effective_vpd_target(cfg)
        lung_room_temp, lung_room_vpd = self._read_lung_room_conditions()
        speed = compute_exhaust_demand(
            self._read_sensor(FanRegulationMode.TEMPERATURE),
            self._read_sensor(FanRegulationMode.HUMIDITY),
            self._read_sensor(FanRegulationMode.VPD),
            temperature_target=cfg.temperature_target,
            temperature_tolerance=cfg.temperature_tolerance,
            humidity_target=cfg.humidity_target,
            humidity_tolerance=cfg.humidity_tolerance,
            vpd_target=vpd_target,
            vpd_tolerance=cfg.vpd_tolerance,
            min_speed=cfg.min_speed,
            max_speed=cfg.max_speed,
            lung_room_temperature=lung_room_temp,
            lung_room_vpd=lung_room_vpd,
            minimum_source_air_temperature=(
                self._env_config.minimum_source_air_temperature
            ),
        )
        if speed is None:
            return

        for entity_id in self._env_config.exhaust_fan_entities:
            await self._dispatch(entity_id, speed, cfg.min_speed)

    def _effective_vpd_target(self, cfg: ExhaustFanConfig) -> float:
        """Resolve the VPD target, honoring stage-aware overrides when enabled."""
        if not cfg.stage_vpd_enabled:
            return cfg.vpd_target

        light_sensors = self._env_config.light_sensors if self._env_config else []
        is_day = self._day_night.determine(self.hass, light_sensors)
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        return resolve_stage_vpd_target(
            plants, cfg.stage_vpd_overrides, cfg.vpd_target, is_day
        )

    async def _dispatch(self, entity_id: str, speed: int, min_speed: int) -> None:
        """Drive a single exhaust device by domain.

        ``fan`` entities receive the speed as a percentage; ``switch`` and
        ``input_boolean`` devices are turned on when the demand exceeds
        ``min_speed`` and off otherwise.
        """
        domain = entity_id.split(".", 1)[0]
        if domain == "fan":
            await self._call_service(
                "fan",
                "set_percentage",
                {ATTR_ENTITY_ID: entity_id, "percentage": speed},
            )
        elif domain in _SWITCH_DOMAINS:
            service = SERVICE_TURN_ON if speed > min_speed else SERVICE_TURN_OFF
            await self._call_service(domain, service, {ATTR_ENTITY_ID: entity_id})

    async def _call_service(
        self, domain: str, service: str, data: dict[str, object]
    ) -> None:
        """Call a Home Assistant service, logging device failures without raising."""
        try:
            await self.hass.services.async_call(domain, service, data, blocking=False)
        except HomeAssistantError, TimeoutError:
            _LOGGER.warning(
                "Failed to call %s.%s on %s",
                domain,
                service,
                data.get(ATTR_ENTITY_ID),
                exc_info=True,
            )

    def _read_sensor(self, mode: FanRegulationMode) -> float | None:
        """Read the first available sensor value for the given measurement."""
        if self._env_config is None:
            return None
        if mode == FanRegulationMode.HUMIDITY:
            sensors = self._env_config.humidity_sensors
        elif mode == FanRegulationMode.TEMPERATURE:
            sensors = self._env_config.temperature_sensors
        elif mode == FanRegulationMode.VPD:
            sensors = self._env_config.vpd_sensors
        else:
            return None

        return self._read_entity_value(sensors[0]) if sensors else None

    def _read_entity_value(self, entity_id: str | None) -> float | None:
        """Read a single entity's numeric state, or None when unavailable."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None
        try:
            return float(state.state)
        except ValueError:
            return None

    def _read_lung_room_conditions(self) -> tuple[float | None, float | None]:
        """Read the source-air (lung-room) temperature and VPD for the gate.

        The lung-room sensors live in the install-wide ``global_settings`` (the
        same source the air-exchange recommendations use). Returns ``(None,
        None)`` when no lung-room sensor is configured, which leaves the
        source-air gate inert.
        """
        global_settings = self.main_coordinator.options.get("global_settings", {})
        lung_room_temp = self._read_entity_value(
            global_settings.get("lung_room_temp_sensor")
        )
        lung_room_humidity = self._read_entity_value(
            global_settings.get("lung_room_humidity_sensor")
        )
        lung_room_vpd = (
            VPDCalculator.calculate_vpd(lung_room_temp, lung_room_humidity)
            if lung_room_temp is not None and lung_room_humidity is not None
            else None
        )
        return lung_room_temp, lung_room_vpd

    async def async_restart(self) -> None:
        """Restart the polling tick after a config change."""
        self.unload()
        await self.async_setup()

    def unload(self) -> None:
        """Stop the polling tick."""
        if self._remove_tick is not None:
            self._remove_tick()
            self._remove_tick = None
