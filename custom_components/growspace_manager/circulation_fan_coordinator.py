"""Circulation Fan Coordinator for Growspace Manager."""

from __future__ import annotations

from collections.abc import Callable
from datetime import timedelta
import logging
import math
import time
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.event import async_track_time_interval

from .const import FanRegulationMode, PlantStage
from .domain.stage_calculator import determine_coordinator_stage

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)

_TICK_INTERVAL = timedelta(seconds=10)

# Per-stage VPD targets (day / night) for dynamic VPD mode.
# Values are midpoints of the tightest Bayesian optimal range for each stage.
FAN_VPD_STAGE_DEFAULTS: dict[PlantStage, dict[str, float]] = {
    PlantStage.SEEDLING:      {"day": 0.60, "night": 0.60},
    PlantStage.CLONE:         {"day": 0.50, "night": 0.50},
    PlantStage.MOTHER:        {"day": 0.70, "night": 0.60},
    PlantStage.VEG:           {"day": 0.70, "night": 0.60},
    PlantStage.FLOWER_EARLY:  {"day": 1.15, "night": 1.00},
    PlantStage.FLOWER_MID:    {"day": 1.20, "night": 1.00},
    PlantStage.FLOWER_LATE:   {"day": 1.25, "night": 1.05},
    PlantStage.DRY:           {"day": 0.95, "night": 0.95},
    PlantStage.CURE:          {"day": 0.75, "night": 0.75},
}


def evaluate_temp_override(
    current_temp: float,
    critical_temp_low: float | None,
    critical_temp_high: float | None,
    hysteresis: float,
    override_active: bool,
    override_direction: str | None,
    vpd_speed: int,
    min_speed: int,
    max_speed: int,
) -> tuple[int, bool, str | None]:
    """Apply temperature safety override logic for VPD mode.

    Returns (final_speed, new_override_active, new_override_direction).
    Override direction is "high" or "low" when active, None otherwise.
    """
    if critical_temp_low is None and critical_temp_high is None:
        return vpd_speed, False, None

    if not override_active:
        if critical_temp_high is not None and current_temp > critical_temp_high:
            return max_speed, True, "high"
        if critical_temp_low is not None and current_temp < critical_temp_low:
            return min_speed, True, "low"
        return vpd_speed, False, None

    if override_direction == "high":
        if critical_temp_high is not None and current_temp <= critical_temp_high - hysteresis:
            return vpd_speed, False, None
        return max_speed, True, "high"

    # override_direction == "low"
    if critical_temp_low is not None and current_temp >= critical_temp_low + hysteresis:
        return vpd_speed, False, None
    return min_speed, True, "low"


def compute_wind_offset(
    amplitude_pct: int,
    elapsed_seconds: float,
    period_seconds: int,
) -> float:
    """Compute wind offset as amplitude × sin(2π × elapsed / period)."""
    return amplitude_pct * math.sin(2 * math.pi * elapsed_seconds / period_seconds)


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
        self._temp_override_active: bool = False
        self._temp_override_direction: str | None = None
        self._start_time: float = 0.0
        self._last_known_is_day: bool | None = None

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
                is_day = self._determine_is_day()
                effective_vpd_target = self._get_stage_vpd_target(is_day)
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

    def _determine_is_day(self) -> bool:
        """Return True if lights are on (OR logic across all light sensors)."""
        light_sensors = self._env_config.light_sensors if self._env_config else []
        if not light_sensors:
            return True

        any_valid = False
        any_on = False
        for sensor_id in light_sensors:
            state = self.hass.states.get(sensor_id)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                any_valid = True
                try:
                    if float(state.state) > 0:
                        any_on = True
                except ValueError:
                    if state.state == STATE_ON:
                        any_on = True

        if any_valid:
            self._last_known_is_day = any_on
            return any_on

        return self._last_known_is_day if self._last_known_is_day is not None else True

    def _get_stage_vpd_target(self, is_day: bool) -> float:
        """Resolve the effective VPD target from stage defaults.

        Falls back to the static vpd_target when the growspace has no plants.
        """
        cfg = self._env_config.circulation_fan_config
        plants = self.main_coordinator.services.growspaces.get_growspace_plants(
            self.growspace_id
        )
        if not plants:
            return cfg.vpd_target

        stage = determine_coordinator_stage(plants)
        day_key = "day" if is_day else "night"
        stage_entry = FAN_VPD_STAGE_DEFAULTS.get(stage)
        if stage_entry:
            return stage_entry[day_key]
        return cfg.vpd_target

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

    def unload(self) -> None:
        """Stop the polling tick."""
        if self._remove_tick is not None:
            self._remove_tick()
            self._remove_tick = None
