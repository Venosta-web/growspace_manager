"""Service handlers for environment configuration."""

from __future__ import annotations

from dataclasses import fields
import logging
from typing import cast

from ..const import (
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
    GrowspaceService,
)
from ..coordinator import GrowspaceCoordinator
from ..models import (
    EnvironmentConfig,
    IrrigationTank,
    SensorGroup,
)
from ..schemas import (
    CONFIGURE_ENVIRONMENT_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    SET_DEHUMIDIFIER_CONTROL_SCHEMA,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ._definition import ServiceDefinition

_LOGGER = logging.getLogger(__name__)


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
        control_humidifier=call.data.get(CONF_CONTROL_HUMIDIFIER, False),
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
        ph_sensors=call.data.get(CONF_PH_SENSORS, []),
        feed_ec_sensors=call.data.get(CONF_FEED_EC_SENSORS, []),
        substrate_ec_sensors=call.data.get(CONF_SUBSTRATE_EC_SENSORS, []),
        runoff_ec_sensors=call.data.get(CONF_RUNOFF_EC_SENSORS, []),
        drain_volume_sensors=call.data.get(CONF_DRAIN_VOLUME_SENSORS, []),
        irrigation_flow_sensors=call.data.get(CONF_IRRIGATION_FLOW_SENSORS, []),
        power_sensors=call.data.get(CONF_POWER_SENSORS, []),
        energy_sensors=call.data.get(CONF_ENERGY_SENSORS, []),
        electricity_cost_per_kwh=call.data.get(CONF_ELECTRICITY_COST),
    )

    # Store in growspace
    growspace.environment_config = env_config

    # Save to storage
    await coordinator.async_save()

    # Trigger coordinator update to create/update binary sensors
    await coordinator.async_refresh()

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
    await coordinator.async_save()

    # Trigger coordinator update
    await coordinator.async_refresh()

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
    await coordinator.async_save()

    # Trigger coordinator update
    await coordinator.async_refresh()

    status = "enabled" if enabled else "disabled"
    _LOGGER.info("Dehumidifier control %s for '%s'", status, growspace.name)


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
]
