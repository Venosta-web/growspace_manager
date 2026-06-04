"""Service handlers for environment configuration."""

from __future__ import annotations

from dataclasses import fields
import logging
from typing import cast

from custom_components.growspace_manager.circulation_fan_coordinator import (
    FAN_VPD_STAGE_DEFAULTS,
)
from custom_components.growspace_manager.const import (
    CONF_CAMERA_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_CONTROL_DEHUMIDIFIER,
    CONF_CONTROL_HUMIDIFIER,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_DRAIN_VOLUME_SENSORS,
    CONF_ELECTRICITY_COST,
    CONF_ENERGY_SENSORS,
    CONF_EXHAUST_ENTITY,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_FEED_EC_SENSORS,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDIFIER_THRESHOLDS,
    CONF_HUMIDITY_SENSOR,
    CONF_IRRIGATION_FLOW_SENSORS,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_LUNG_ROOM_TEMP_SENSORS,
    CONF_MOLD_THRESHOLD,
    CONF_PH_SENSORS,
    CONF_POWER_SENSORS,
    CONF_RUNOFF_EC_SENSORS,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_STRESS_THRESHOLD,
    CONF_SUBSTRATE_EC_SENSORS,
    CONF_SUBSTRATE_TEMP_SENSORS,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    FanRegulationMode,
    GrowspaceService,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    CirculationFanConfig,
    EnvironmentConfig,
    IrrigationTank,
    SensorGroup,
)
from custom_components.growspace_manager.schemas import (
    CONFIGURE_CIRCULATION_FAN_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    SET_DEHUMIDIFIER_CONTROL_SCHEMA,
    SET_HUMIDIFIER_CONTROL_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ._definition import ServiceDefinition

_LOGGER = logging.getLogger(__name__)


_VALID_STAGE_KEYS = {stage.value for stage in FAN_VPD_STAGE_DEFAULTS}
_VPD_OVERRIDE_MIN = 0.1
_VPD_OVERRIDE_MAX = 3.0


def _validate_stage_vpd_overrides(overrides: dict) -> dict[str, dict[str, float]]:
    """Validate and return stage_vpd_overrides, raising ServiceValidationError on bad input."""
    for stage_key, entry in overrides.items():
        if stage_key not in _VALID_STAGE_KEYS:
            raise ServiceValidationError(
                f"Unknown stage key '{stage_key}' in stage_vpd_overrides. "
                f"Valid keys: {sorted(_VALID_STAGE_KEYS)}"
            )
        if not isinstance(entry, dict) or "day" not in entry or "night" not in entry:
            raise ServiceValidationError(
                f"Stage '{stage_key}' entry must contain both 'day' and 'night' keys."
            )
        for period in ("day", "night"):
            val = entry[period]
            if not (_VPD_OVERRIDE_MIN <= val <= _VPD_OVERRIDE_MAX):
                raise ServiceValidationError(
                    f"Stage '{stage_key}' {period} VPD override {val} kPa is out of range "
                    f"({_VPD_OVERRIDE_MIN}–{_VPD_OVERRIDE_MAX} kPa)."
                )
    return overrides


def _parse_fan_config(
    raw: dict | None,
    existing_env: EnvironmentConfig | None,
) -> CirculationFanConfig:
    """Return a CirculationFanConfig from a raw dict payload, falling back to the existing config."""
    if raw:
        return CirculationFanConfig(
            enabled=bool(raw.get("enabled", False)),
            regulation_mode=FanRegulationMode(raw.get("regulation_mode", FanRegulationMode.VPD)),
            min_speed=int(raw.get("min_speed", 0)),
            max_speed=int(raw.get("max_speed", 100)),
            vpd_target=float(raw.get("vpd_target", 1.0)),
            vpd_tolerance=float(raw.get("vpd_tolerance", 0.2)),
            humidity_target=float(raw.get("humidity_target", 60.0)),
            humidity_tolerance=float(raw.get("humidity_tolerance", 5.0)),
            temperature_target=float(raw.get("temperature_target", 25.0)),
            temperature_tolerance=float(raw.get("temperature_tolerance", 2.0)),
            critical_temp_low=raw.get("critical_temp_low"),
            critical_temp_high=raw.get("critical_temp_high"),
            critical_temp_hysteresis=float(raw.get("critical_temp_hysteresis", 1.0)),
            wind_enabled=bool(raw.get("wind_enabled", False)),
            wind_period_seconds=int(raw.get("wind_period_seconds", 60)),
            wind_amplitude_pct=int(raw.get("wind_amplitude_pct", 10)),
            stage_vpd_enabled=bool(raw.get("stage_vpd_enabled", False)),
            stage_vpd_overrides=_validate_stage_vpd_overrides(raw.get("stage_vpd_overrides", {})),
        )
    if existing_env is not None:
        return existing_env.circulation_fan_config
    return CirculationFanConfig()


async def handle_configure_environment(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the configure_environment service call."""
    growspace_id = call.data.get("growspace_id")

    if growspace_id not in coordinator.growspaces:
        error_msg = f"Growspace '{growspace_id}' not found"
        _LOGGER.error(error_msg)
        raise ServiceValidationError(error_msg)

    growspace = coordinator.growspaces[growspace_id]

    def _get_list(key_singular: str, key_plural: str) -> list[str]:
        if val := call.data.get(key_plural):
            return cast(list[str], val)
        if val := call.data.get(key_singular):
            return cast(list[str], [val] if isinstance(val, str) else val)
        return []

    # Process Sensor Groups
    sensor_groups_data = call.data.get("sensor_groups", [])
    sensor_groups = []

    valid_keys = {f.name for f in fields(SensorGroup)}

    for g_data in sensor_groups_data:
        try:
            # Filter keys
            filtered_data = {k: v for k, v in g_data.items() if k in valid_keys}
            # simple dict to SensorGroup conversion
            sensor_groups.append(SensorGroup.from_dict(filtered_data))
        except (TypeError, ValueError, LookupError) as e:
            _LOGGER.warning("Invalid sensor group data: %s (%s)", g_data, e)

    # Process Irrigation Tanks
    tanks_data = call.data.get("irrigation_tanks", [])
    irrigation_tanks = []

    tank_valid_keys = {f.name for f in fields(IrrigationTank)}

    # Build map of existing tanks to preserve runtime data (water_history, last_recorded_level)
    existing_tanks_by_entity: dict[str, IrrigationTank] = {}
    if growspace.environment_config and growspace.environment_config.irrigation_tanks:
        existing_tanks_by_entity = {
            t.sensor_entity: t for t in growspace.environment_config.irrigation_tanks
        }

    for t_data in tanks_data:
        try:
            filtered_tank = {k: v for k, v in t_data.items() if k in tank_valid_keys}
            new_tank = IrrigationTank.from_dict(filtered_tank)
            # Preserve accumulated runtime data for tanks that already exist
            existing = existing_tanks_by_entity.get(new_tank.sensor_entity)
            if existing is not None:
                new_tank.water_history = existing.water_history
                new_tank.last_recorded_level = existing.last_recorded_level
                new_tank.peak_level = existing.peak_level
            irrigation_tanks.append(new_tank)
        except (TypeError, ValueError, LookupError) as e:
            _LOGGER.warning("Invalid irrigation tank data: %s (%s)", t_data, e)

    # Build environment config from service call
    env_config = EnvironmentConfig(
        temperature_sensor=call.data.get(CONF_TEMP_SENSOR),
        temperature_sensors=_get_list(CONF_TEMP_SENSOR, "temperature_sensors"),
        humidity_sensor=call.data.get(CONF_HUMIDITY_SENSOR),
        humidity_sensors=_get_list(CONF_HUMIDITY_SENSOR, "humidity_sensors"),
        vpd_sensor=call.data.get(CONF_VPD_SENSOR),
        vpd_sensors=_get_list(CONF_VPD_SENSOR, "vpd_sensors"),
        co2_sensor=call.data.get(CONF_CO2_SENSOR),
        circulation_fan_entities=_get_list(
            CONF_CIRCULATION_FAN_ENTITY, CONF_CIRCULATION_FAN_ENTITIES
        ),
        light_sensors=_get_list(CONF_LIGHT_SENSOR, CONF_LIGHT_SENSORS),
        exhaust_fan_entities=_get_list(CONF_EXHAUST_ENTITY, CONF_EXHAUST_FAN_ENTITIES),
        humidifier_entities=_get_list(CONF_HUMIDIFIER_ENTITY, CONF_HUMIDIFIER_ENTITIES),
        dehumidifier_entities=_get_list(
            CONF_DEHUMIDIFIER_ENTITY, CONF_DEHUMIDIFIER_ENTITIES
        ),
        soil_moisture_sensor=call.data.get(CONF_SOIL_MOISTURE_SENSOR),
        control_dehumidifier=call.data.get(CONF_CONTROL_DEHUMIDIFIER, False),
        dehumidifier_thresholds=call.data.get(CONF_DEHUMIDIFIER_THRESHOLDS, {}),
        humidifier_thresholds=call.data.get(CONF_HUMIDIFIER_THRESHOLDS, {}),
        stress_threshold=call.data.get(CONF_STRESS_THRESHOLD, 0.70),
        mold_threshold=call.data.get(CONF_MOLD_THRESHOLD, 0.75),
        veg_day_hours=call.data.get("veg_day_hours", 18),
        flower_day_hours=call.data.get("flower_day_hours", 12),
        minimum_source_air_temperature=call.data.get(
            "minimum_source_air_temperature", 18.0
        ),
        sensor_groups=sensor_groups,
        sensor_coordinates=call.data.get("sensor_coordinates", {}),
        irrigation_tanks=irrigation_tanks,
        substrate_temperature_sensors=call.data.get(CONF_SUBSTRATE_TEMP_SENSORS, []),
        camera_entities=call.data.get(CONF_CAMERA_ENTITIES, []),
        lung_room_temp_sensors=call.data.get(CONF_LUNG_ROOM_TEMP_SENSORS, []),
        ph_sensors=call.data.get(CONF_PH_SENSORS, []),
        feed_ec_sensors=call.data.get(CONF_FEED_EC_SENSORS, []),
        substrate_ec_sensors=call.data.get(CONF_SUBSTRATE_EC_SENSORS, []),
        runoff_ec_sensors=call.data.get(CONF_RUNOFF_EC_SENSORS, []),
        drain_volume_sensors=call.data.get(CONF_DRAIN_VOLUME_SENSORS, []),
        irrigation_flow_sensors=call.data.get(CONF_IRRIGATION_FLOW_SENSORS, []),
        power_sensors=call.data.get(CONF_POWER_SENSORS, []),
        energy_sensors=call.data.get(CONF_ENERGY_SENSORS, []),
        electricity_cost_per_kwh=call.data.get(CONF_ELECTRICITY_COST),
        circulation_fan_config=_parse_fan_config(
            call.data.get("circulation_fan_config"),
            growspace.environment_config,
        ),
    )

    # Store in growspace
    growspace.environment_config = env_config

    # Save to storage
    await coordinator.services.save()

    # Trigger coordinator update to create/update binary sensors
    await coordinator.services.request_refresh()

    fan_coord = coordinator.subsystem_manager.circulation_fan_coordinators.get(growspace_id)
    if fan_coord:
        await fan_coord.async_restart()

    success_msg = f"Environment monitoring configured for '{growspace.name}'"
    _LOGGER.info("%s: %s", success_msg, env_config)


async def handle_remove_environment(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the remove_environment service call."""
    growspace_id = call.data.get("growspace_id")

    if growspace_id not in coordinator.growspaces:
        error_msg = f"Growspace '{growspace_id}' not found"
        _LOGGER.error(error_msg)
        raise ServiceValidationError(error_msg)

    growspace = coordinator.growspaces[growspace_id]

    # Remove environment config
    growspace.environment_config = EnvironmentConfig()

    # Save to storage
    await coordinator.services.save()

    # Trigger coordinator update
    await coordinator.services.request_refresh()

    success_msg = f"Environment monitoring removed for '{growspace.name}'"
    _LOGGER.info(success_msg)


async def handle_set_dehumidifier_control(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the set_dehumidifier_control service call."""
    growspace_id = call.data.get("growspace_id")
    enabled = call.data.get("enabled")

    if growspace_id not in coordinator.growspaces:
        error_msg = f"Growspace '{growspace_id}' not found"
        _LOGGER.error(error_msg)
        raise ServiceValidationError(error_msg)

    growspace = coordinator.growspaces[growspace_id]

    # Update configuration
    growspace.environment_config.control_dehumidifier = bool(enabled)

    # Save to storage
    await coordinator.services.save()

    # Trigger coordinator update
    await coordinator.services.request_refresh()

    status = "enabled" if enabled else "disabled"
    _LOGGER.info("Dehumidifier control %s for '%s'", status, growspace.name)


async def handle_set_humidifier_control(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the set_humidifier_control service call."""
    growspace_id = call.data.get("growspace_id")
    enabled = call.data.get("enabled")

    if growspace_id not in coordinator.growspaces:
        error_msg = f"Growspace '{growspace_id}' not found"
        _LOGGER.error(error_msg)
        raise ServiceValidationError(error_msg)

    growspace = coordinator.growspaces[growspace_id]
    growspace.environment_config.control_humidifier = bool(enabled)

    await coordinator.services.save()
    await coordinator.services.request_refresh()

    status = "enabled" if enabled else "disabled"
    _LOGGER.info("Humidifier control %s for '%s'", status, growspace.name)


async def handle_configure_circulation_fan(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the configure_circulation_fan service call."""
    growspace_id = call.data.get("growspace_id")

    if growspace_id not in coordinator.growspaces:
        error_msg = f"Growspace '{growspace_id}' not found"
        _LOGGER.error(error_msg)
        raise ServiceValidationError(error_msg)

    growspace = coordinator.growspaces[growspace_id]

    fan_cfg = CirculationFanConfig(
        enabled=bool(call.data.get("enabled", False)),
        regulation_mode=FanRegulationMode(call.data.get("regulation_mode", FanRegulationMode.VPD)),
        min_speed=int(call.data.get("min_speed", 0)),
        max_speed=int(call.data.get("max_speed", 100)),
        vpd_target=float(call.data.get("vpd_target", 1.0)),
        vpd_tolerance=float(call.data.get("vpd_tolerance", 0.2)),
        humidity_target=float(call.data.get("humidity_target", 60.0)),
        humidity_tolerance=float(call.data.get("humidity_tolerance", 5.0)),
        temperature_target=float(call.data.get("temperature_target", 25.0)),
        temperature_tolerance=float(call.data.get("temperature_tolerance", 2.0)),
        critical_temp_low=call.data.get("critical_temp_low"),
        critical_temp_high=call.data.get("critical_temp_high"),
        critical_temp_hysteresis=float(call.data.get("critical_temp_hysteresis", 1.0)),
        wind_enabled=bool(call.data.get("wind_enabled", False)),
        wind_period_seconds=int(call.data.get("wind_period_seconds", 60)),
        wind_amplitude_pct=int(call.data.get("wind_amplitude_pct", 10)),
        stage_vpd_enabled=bool(call.data.get("stage_vpd_enabled", False)),
        stage_vpd_overrides=_validate_stage_vpd_overrides(
            call.data.get("stage_vpd_overrides", {})
        ),
    )

    if growspace.environment_config is None:
        growspace.environment_config = EnvironmentConfig()

    growspace.environment_config.circulation_fan_config = fan_cfg

    await coordinator.services.save()
    await coordinator.services.request_refresh()

    fan_coord = coordinator.subsystem_manager.circulation_fan_coordinators.get(growspace_id)
    if fan_coord:
        await fan_coord.async_restart()

    _LOGGER.info("Circulation fan controller configured for '%s'", growspace.name)


SERVICES = [
    ServiceDefinition(
        GrowspaceService.CONFIGURE_ENVIRONMENT,
        handle_configure_environment,
        CONFIGURE_ENVIRONMENT_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.REMOVE_ENVIRONMENT,
        handle_remove_environment,
        REMOVE_ENVIRONMENT_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_DEHUMIDIFIER_CONTROL,
        handle_set_dehumidifier_control,
        SET_DEHUMIDIFIER_CONTROL_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.SET_HUMIDIFIER_CONTROL,
        handle_set_humidifier_control,
        SET_HUMIDIFIER_CONTROL_SCHEMA,
    ),
    ServiceDefinition(
        GrowspaceService.CONFIGURE_CIRCULATION_FAN,
        handle_configure_circulation_fan,
        CONFIGURE_CIRCULATION_FAN_SCHEMA,
    ),
]
