"""Service handlers for environment configuration."""

from __future__ import annotations

import logging

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ..coordinator import GrowspaceCoordinator
from ..strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


async def handle_configure_environment(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
    call: ServiceCall,
) -> None:
    """Handle the configure_environment service call."""
    growspace_id = call.data.get("growspace_id")

    if growspace_id not in coordinator.growspaces:
        error_msg = f"Growspace '{growspace_id}' not found"
        _LOGGER.error(error_msg)
        raise ServiceValidationError(error_msg)

    growspace = coordinator.growspaces[growspace_id]

    # Build environment config from service call
    env_config = {
        "temperature_sensor": call.data.get("temperature_sensor"),
        "humidity_sensor": call.data.get("humidity_sensor"),
        "vpd_sensor": call.data.get("vpd_sensor"),
    }

    # Add optional sensors if provided
    if call.data.get("co2_sensor"):
        env_config["co2_sensor"] = call.data.get("co2_sensor")

    if call.data.get("circulation_fan"):
        env_config["circulation_fan"] = call.data.get("circulation_fan")

    # Add thresholds
    env_config["stress_threshold"] = call.data.get("stress_threshold", 0.70)
    env_config["mold_threshold"] = call.data.get("mold_threshold", 0.75)

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
    strain_library: StrainLibrary,
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
    growspace.environment_config = {}

    # Save to storage
    await coordinator.async_save()

    # Trigger coordinator update
    await coordinator.async_refresh()

    success_msg = f"Environment monitoring removed for '{growspace.name}'"
    _LOGGER.info(success_msg)


async def handle_set_dehumidifier_control(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    strain_library: StrainLibrary,
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

    if not growspace.environment_config:
        growspace.environment_config = {}

    # Update configuration
    growspace.environment_config["control_dehumidifier"] = enabled

    # Save to storage
    await coordinator.async_save()

    # Trigger coordinator update
    await coordinator.async_refresh()

    status = "enabled" if enabled else "disabled"
    _LOGGER.info("Dehumidifier control %s for '%s'", status, growspace.name)
