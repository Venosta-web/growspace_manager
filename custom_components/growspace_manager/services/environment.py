"""Service handlers for environment configuration."""

from __future__ import annotations

from dataclasses import fields
import logging
from typing import cast

from custom_components.growspace_manager.const import (
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_CONTROL_DEHUMIDIFIER,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_EXHAUST_ENTITY,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_MOLD_THRESHOLD,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_STRESS_THRESHOLD,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    IrrigationTank,
    SensorGroup,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

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

    for t_data in tanks_data:
        try:
            filtered_tank = {k: v for k, v in t_data.items() if k in tank_valid_keys}
            irrigation_tanks.append(IrrigationTank.from_dict(filtered_tank))
        except (TypeError, ValueError, LookupError) as e:
            _LOGGER.warning("Invalid irrigation tank data: %s (%s)", t_data, e)

    # Build environment config from service call
    env_config = EnvironmentConfig(
        temperature_sensor=call.data.get(CONF_TEMP_SENSOR),
        humidity_sensor=call.data.get(CONF_HUMIDITY_SENSOR),
        vpd_sensor=call.data.get(CONF_VPD_SENSOR),
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
