"""Helper functions for the Growspace Manager integration.

This file contains utility functions for creating and managing Home Assistant
entities, such as trend and statistics sensors, that are used by the main
integration components.
"""

from __future__ import annotations

import logging

from homeassistant.const import CONF_PLATFORM, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.discovery import async_load_platform

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_trend_sensor(
    hass: HomeAssistant,
    source_sensor_entity_id: str,
    growspace_id: str,
    growspace_name: str,
    sensor_type: str,
) -> str | None:
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
    # Removing strict check to allow internal/queued entities to work
    # if not entity_registry.async_get(source_sensor_entity_id):
    #     _LOGGER.warning(
    #         "Source sensor %s not found in entity registry for trend sensor setup",
    #         source_sensor_entity_id,
    #     )
    #     return None

    name = f"{growspace_name} {sensor_type.replace('_', ' ').title()} Trend"
    unique_id = f"{DOMAIN}_{growspace_id}_{sensor_type}_trend"

    if entity_registry.async_get_entity_id("binary_sensor", "trend", unique_id):
        _LOGGER.debug("Trend sensor with unique_id %s already exists", unique_id)
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

    # Force entity category to diagnostic
    # We need to wait for the entity to be registered?
    # Actually, async_load_platform doesn't return the entity.
    # But usually it's fast. Or we can just try to update it if it exists.
    # However, if it doesn't exist yet, we can't update it.
    # But we know the unique_id.

    # Since we can't easily hook into the creation, we might accept that it might fail
    # if not immediate. But let's try to look it up.
    # A better way might be to pre-create the registry entry?
    # "If you use unique_id, you can create the entry in the registry before you add the entity."

    if not entity_registry.async_get_entity_id("binary_sensor", "trend", unique_id):
        entity_registry.async_get_or_create(
            "binary_sensor",
            "trend",
            unique_id,
            suggested_object_id=f"{growspace_name.lower().replace(' ', '_')}_{sensor_type}_trend",
            original_name=name,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )

    entity_id = entity_registry.async_get_entity_id("binary_sensor", "trend", unique_id)
    if entity_id:
        entity_registry.async_update_entity(
            entity_id, entity_category=EntityCategory.DIAGNOSTIC
        )

    _LOGGER.info("Setting up trend sensor: %s", name)
    return unique_id


async def async_setup_statistics_sensor(
    hass: HomeAssistant,
    source_sensor_entity_id: str,
    growspace_id: str,
    growspace_name: str,
    sensor_type: str,
) -> str | None:
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
    # Removing strict check to allow internal/queued entities to work
    # if not entity_registry.async_get(source_sensor_entity_id):
    #     _LOGGER.warning(
    #         "Source sensor %s not found for statistics sensor setup",
    #         source_sensor_entity_id,
    #     )
    #     return None

    name = f"{growspace_name} {sensor_type.replace('_', ' ').title()} Stats"
    unique_id = f"{DOMAIN}_{growspace_id}_{sensor_type}_stats"

    if entity_registry.async_get_entity_id("sensor", "statistics", unique_id):
        _LOGGER.debug("Statistics sensor with unique_id %s already exists", unique_id)
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
        "sensor",  # <-- Entity domain
        config,
        {DOMAIN: config},
    )
    _LOGGER.info("Setting up statistics sensor: %s", name)

    # Force entity category to diagnostic
    if not entity_registry.async_get_entity_id("sensor", "statistics", unique_id):
        entity_registry.async_get_or_create(
            "sensor",
            "statistics",
            unique_id,
            suggested_object_id=f"{growspace_name.lower().replace(' ', '_')}_{sensor_type}_stats",
            original_name=name,
            disabled_by=er.RegistryEntryDisabler.INTEGRATION,
        )

    entity_id = entity_registry.async_get_entity_id("sensor", "statistics", unique_id)
    if entity_id:
        entity_registry.async_update_entity(
            entity_id, entity_category=EntityCategory.DIAGNOSTIC
        )

    return unique_id
