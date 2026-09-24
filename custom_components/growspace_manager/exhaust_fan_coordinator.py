"""Exhaust Fan Coordinator for Growspace Manager.

Drives the configured exhaust devices on a fixed tick using a combined demand
signal: the maximum of a temperature term, a humidity term and an inverted-VPD
term (see ADR 0018 and CONTEXT.md "Exhaust Demand"). Unlike the circulation
fan, exhaust has no single regulation mode and no dynamic wind layer.

This slice excludes the source-air gate and the critical-temperature override —
those are handled by separate slices.

Its regulation sensors are read for freshness as well as plausibility through
the growspace's ``ClimateSafety``. When every one of them has had no usable
reading for the Fail-Safe Timeout, the exhaust runs at its fallback speed until
one reads again (#792); a shorter loss holds the last speed.
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
from .climate_safety import ClimateSafety, Plausible
from .const import FanRegulationMode
from .domain.climate_fail_safe import ClimateRole
from .domain.day_night import DayNightTracker
from .domain.fan_control import (
    compute_exhaust_demand,
    evaluate_temp_override,
    resolve_stage_vpd_target,
)
from .domain.sensor_validity import (
    HUMIDITY_RANGE,
    VPD_RANGE,
    PlausibleRange,
    temperature_range,
)
from .reliability_store import climate_command_failure
from .utils import VPDCalculator, read_plausible_value

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models import EnvironmentConfig, ExhaustFanConfig

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)

# The plausible range of each regulation measurement (#789).
_REGULATION_RANGES: dict[FanRegulationMode, Plausible] = {
    FanRegulationMode.TEMPERATURE: temperature_range,
    FanRegulationMode.HUMIDITY: HUMIDITY_RANGE,
    FanRegulationMode.VPD: VPD_RANGE,
}


def _regulation_sensors(env: EnvironmentConfig, mode: FanRegulationMode) -> list[str]:
    """Return the configured sensors of one regulation measurement."""
    return {
        FanRegulationMode.TEMPERATURE: env.temperature_sensors,
        FanRegulationMode.HUMIDITY: env.humidity_sensors,
        FanRegulationMode.VPD: env.vpd_sensors,
    }[mode]


class ExhaustFanCoordinator:
    """Controls exhaust devices via combined temperature/humidity/VPD demand."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        growspace_id: str,
        main_coordinator: GrowspaceCoordinator,
        safety: ClimateSafety | None = None,
    ) -> None:
        """Initialize the ExhaustFanCoordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self.growspace_id = growspace_id
        self.main_coordinator = main_coordinator
        self._safety = safety or ClimateSafety(hass, growspace_id, main_coordinator)
        self._remove_tick: Callable[[], None] | None = None
        self._day_night = DayNightTracker(growspace_id)
        self._temp_override_active: bool = False
        self._temp_override_direction: str | None = None
        self._last_command: int | None = None
        self._last_command_at: str | None = None

    @property
    def _env_config(self) -> EnvironmentConfig | None:
        gs = self.main_coordinator.growspaces.get(self.growspace_id)
        return gs.environment_config if gs else None

    @property
    def _has_exhaust_actuators(self) -> bool:
        """Whether any exhaust actuator — plain entity or AC Infinity — is configured."""
        env = self._env_config
        return bool(
            env and (env.exhaust_fan_entities or env.exhaust_fan_ac_infinity_devices)
        )

    async def async_setup(self) -> None:
        """Start the polling tick when enabled and exhaust entities are configured."""
        if self._env_config is None:
            return

        cfg = self._env_config.exhaust_fan_config
        if not cfg.enabled:
            _LOGGER.debug("ExhaustFanCoordinator disabled for %s", self.growspace_id)
            return

        if not self._has_exhaust_actuators:
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
        if not self.main_coordinator.irrigation_safety.automation_enabled(
            self.growspace_id
        ):
            return
        if self._env_config is None:
            return

        cfg = self._env_config.exhaust_fan_config
        if not cfg.enabled or not self._has_exhaust_actuators:
            return

        speed = await self._async_regulated_speed(self._env_config)
        if speed is None:
            return

        drivers = resolve_actuator_drivers(
            self.hass,
            self._env_config.exhaust_fan_entities,
            self._env_config.exhaust_fan_ac_infinity_devices,
            switch_off_threshold=cfg.min_speed,
        )
        for driver in drivers:
            if not self.main_coordinator.irrigation_safety.automation_enabled(
                self.growspace_id
            ):
                return
            if not await driver.set_speed(speed):
                self._safety.record(climate_command_failure(ClimateRole.EXHAUST))
            self._last_command = speed
            self._last_command_at = dt_util.now().isoformat()

    async def _async_regulated_speed(self, env: EnvironmentConfig) -> int | None:
        """Return the speed to command, or None to hold the last one.

        The fallback speed once every regulation sensor has been lost for the
        Fail-Safe Timeout; otherwise the combined demand, which is None while
        no sensor reads.
        """
        if await self._safety.async_failure(
            ClimateRole.EXHAUST, self._regulation_inputs(env)
        ):
            return self._safety.exhaust_fallback_speed()
        cfg = env.exhaust_fan_config
        vpd_target = self._effective_vpd_target(cfg)
        lung_room_temp, lung_room_vpd = self._read_lung_room_conditions()
        temperature = self._read_sensor(env, FanRegulationMode.TEMPERATURE)
        speed = compute_exhaust_demand(
            temperature,
            self._read_sensor(env, FanRegulationMode.HUMIDITY),
            self._read_sensor(env, FanRegulationMode.VPD),
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
            minimum_source_air_temperature=env.minimum_source_air_temperature,
        )
        return self._apply_critical_temp_override(cfg, temperature, speed)

    def diagnostics_snapshot(self) -> dict[str, object]:
        """Describe the configured exhaust controller and its last output."""
        env = self._env_config
        if env is None:
            return {}
        cfg = env.exhaust_fan_config
        return {
            "enabled": cfg.enabled,
            "entities": list(env.exhaust_fan_entities),
            "ac_infinity_ports": [
                {"mode_entity": device.mode_entity, "speed_entity": device.speed_entity}
                for device in env.exhaust_fan_ac_infinity_devices
            ],
            "thresholds": {
                "temperature": cfg.temperature_target,
                "humidity": cfg.humidity_target,
                "vpd": self._effective_vpd_target(cfg),
            },
            "last_command": self._last_command,
            "last_command_at": self._last_command_at,
            "fail_safe": self._safety.is_failed(ClimateRole.EXHAUST),
        }

    def _apply_critical_temp_override(
        self, cfg: ExhaustFanConfig, temperature: float | None, speed: int | None
    ) -> int | None:
        """Compose the critical-temperature safety override on the gated demand.

        A ``critical_temp_high`` breach forces ``max_speed`` — bypassing the
        source-air gate, since a heat emergency must vent regardless of whether
        incoming air is ideal — while a ``critical_temp_low`` breach forces
        ``min_speed``. The override latches until temperature returns within
        bounds plus ``critical_temp_hysteresis``. With no critical temps
        configured, or no temperature reading, the gated demand passes through.
        """
        if cfg.critical_temp_low is None and cfg.critical_temp_high is None:
            return speed
        if temperature is None:
            return speed

        base_speed = speed if speed is not None else cfg.min_speed
        speed, self._temp_override_active, self._temp_override_direction = (
            evaluate_temp_override(
                temperature,
                cfg.critical_temp_low,
                cfg.critical_temp_high,
                cfg.critical_temp_hysteresis,
                self._temp_override_active,
                self._temp_override_direction,
                base_speed,
                cfg.min_speed,
                cfg.max_speed,
            )
        )
        return speed

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

    def _regulation_inputs(self, env: EnvironmentConfig) -> dict[str, Plausible]:
        """Return the regulation sensors the demand reads, with their ranges."""
        inputs: dict[str, Plausible] = {}
        for mode, plausible in _REGULATION_RANGES.items():
            if sensors := _regulation_sensors(env, mode):
                inputs.setdefault(sensors[0], plausible)
        return inputs

    def _read_sensor(
        self, env: EnvironmentConfig, mode: FanRegulationMode
    ) -> float | None:
        """Read the measurement's regulation sensor, or None when it cannot be trusted."""
        sensors = _regulation_sensors(env, mode)
        if not sensors:
            return None
        return self._safety.reading(sensors[0], _REGULATION_RANGES[mode]).value

    def _read_entity_value(
        self,
        entity_id: str | None,
        plausible: PlausibleRange | Callable[[str | None], PlausibleRange],
    ) -> float | None:
        """Read one entity's value, or None when it is unavailable or implausible."""
        return read_plausible_value(self.hass, entity_id, plausible)

    def _read_lung_room_conditions(self) -> tuple[float | None, float | None]:
        """Read the source-air (lung-room) temperature and VPD for the gate.

        The lung-room sensors live in the install-wide ``global_settings`` (the
        same source the air-exchange recommendations use). Returns ``(None,
        None)`` when no lung-room sensor is configured, which leaves the
        source-air gate inert.
        """
        global_settings = self.main_coordinator.options.get("global_settings", {})
        lung_room_temp = self._read_entity_value(
            global_settings.get("lung_room_temp_sensor"), temperature_range
        )
        lung_room_humidity = self._read_entity_value(
            global_settings.get("lung_room_humidity_sensor"), HUMIDITY_RANGE
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
        self._temp_override_active = False
        self._temp_override_direction = None
        await self.async_setup()

    def unload(self) -> None:
        """Stop the polling tick."""
        self._safety.withdraw(ClimateRole.EXHAUST)
        if self._remove_tick is not None:
            self._remove_tick()
            self._remove_tick = None
