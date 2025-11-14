"""Helper functions for the Growspace Manager integration."""

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
    """Set up a trend sensor for a given source sensor and return its unique_id."""
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
        "binary_sensor",
        "trend",
        config,
        {DOMAIN: config}
    )
    _LOGGER.info(f"Setting up trend sensor: {name}")
    return unique_id


async def async_setup_statistics_sensor(
    hass: HomeAssistant, source_sensor_entity_id: str, growspace_id: str, growspace_name: str, sensor_type: str
) -> Optional[str]:
    """Set up a statistics sensor for a given source sensor and return its unique_id."""
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
        "sensor",
        "statistics",
        config,
        {DOMAIN: config}
    )
    _LOGGER.info(f"Setting up statistics sensor: {name}")
    return unique_id
