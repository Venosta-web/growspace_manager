"""Helper functions for the Growspace Manager integration.

This file contains utility functions for creating and managing Home Assistant
entities, such as trend and statistics sensors, that are used by the main
integration components.
"""
from __future__ import annotations

import logging
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery import async_load_platform
from homeassistant.const import CONF_PLATFORM

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_trend_sensor(
    hass: HomeAssistant, source_sensor_entity_id: str, growspace_id: str, growspace_name: str, sensor_type: str
) -> Optional[str]:
    """Set up a trend binary sensor to monitor the gradient of a source sensor.

    This function dynamically creates a `trend` binary sensor that will turn 'on'
    if the value of the `source_sensor_entity_id` is increasing.

    Args:
        hass: The Home Assistant instance.
        source_sensor_entity_id: The entity ID of the sensor to monitor.
        growspace_id: The unique ID of the growspace.
        growspace_name: The display name of the growspace.
        sensor_type: The type of sensor being monitored (e.g., 'temperature').

    Returns:
        The unique ID of the created trend sensor, or None if setup failed.
    """
    entity_registry = er.async_get(hass)
    if not entity_registry.async_get(source_sensor_entity_id):
        _LOGGER.warning(f"Source sensor {source_sensor_entity_id} not found in entity registry for trend sensor setup")
        return None

    name = f"{growspace_name} {sensor_type.replace('_', ' ').title()} Trend"
    unique_id = f"{DOMAIN}_{growspace_id}_{sensor_type}_trend"

    if entity_registry.async_get_entity_id("binary_sensor", "trend", unique_id):
        _LOGGER.debug(f"Trend sensor with unique_id {unique_id} already exists.")
        return unique_id

    config = {
        CONF_PLATFORM: "trend",
        "sensors": {
            unique_id: {
                "friendly_name": name,
                "entity_id": source_sensor_entity_id,
            }
        },
    }

    await async_load_platform(
        hass,
        "trend",
        "binary_sensor",
        {},
        {"binary_sensor": [config]},
    )
    _LOGGER.info(f"Setting up trend sensor: {name}")
    return unique_id


async def async_setup_statistics_sensor(
    hass: HomeAssistant, source_sensor_entity_id: str, growspace_id: str, growspace_name: str, sensor_type: str
) -> Optional[str]:
    """Set up a statistics sensor to calculate metrics for a source sensor.

    This function dynamically creates a `statistics` sensor that provides
    various statistical measures (e.g., mean, change) for the
    `source_sensor_entity_id`.

    Args:
        hass: The Home Assistant instance.
        source_sensor_entity_id: The entity ID of the sensor to gather statistics for.
        growspace_id: The unique ID of the growspace.
        growspace_name: The display name of the growspace.
        sensor_type: The type of sensor being monitored (e.g., 'humidity').

    Returns:
        The unique ID of the created statistics sensor, or None if setup failed.
    """
    entity_registry = er.async_get(hass)
    if not entity_registry.async_get(source_sensor_entity_id):
        _LOGGER.warning(f"Source sensor {source_sensor_entity_id} not found for statistics sensor setup")
        return None

    name = f"{growspace_name} {sensor_type.replace('_', ' ').title()} Stats"
    unique_id = f"{DOMAIN}_{growspace_id}_{sensor_type}_stats"

    if entity_registry.async_get_entity_id("sensor", "statistics", unique_id):
        _LOGGER.debug(f"Statistics sensor with unique_id {unique_id} already exists.")
        return unique_id

    config = {
        CONF_PLATFORM: "statistics",
        "name": name,
        "entity_id": source_sensor_entity_id,
        "unique_id": unique_id,
        "sampling_size": 100,
        "max_age": {"hours": 12},
    }

    await async_load_platform(
        hass,
        "statistics",  # <-- Platform name
        "sensor",      # <-- Entity domain
        config,
        {DOMAIN: config}
    )
    _LOGGER.info(f"Setting up statistics sensor: {name}")
    return unique_id
