"""Service handlers for environment configuration."""

from __future__ import annotations

import logging

from homeassistant.components.persistent_notification import (
    async_create as create_notification,
)
from homeassistant.core import HomeAssistant, ServiceCall

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
        create_notification(
            hass,
            error_msg,
            title="Growspace Manager - Environment Config Error",
        )
        return

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
    _LOGGER.info(f"{success_msg}: {env_config}")

    create_notification(
        hass,
        f"{success_msg}\n\nPlease reload the integration for binary sensors to appear.",
        title="Growspace Manager - Environment Configured",
    )


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
        create_notification(
            hass,
            error_msg,
            title="Growspace Manager - Environment Config Error",
        )
        return

    growspace = coordinator.growspaces[growspace_id]

    # Remove environment config
    growspace.environment_config = None

    # Save to storage
    await coordinator.async_save()

    # Trigger coordinator update
    await coordinator.async_refresh()

    success_msg = f"Environment monitoring removed for '{growspace.name}'"
    _LOGGER.info(success_msg)

    create_notification(
        hass,
        f"{success_msg}\n\nPlease reload the integration for binary sensors to be removed.",
        title="Growspace Manager - Environment Removed",
    )


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
        create_notification(
            hass,
            error_msg,
            title="Growspace Manager - Error",
        )
        return

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
    _LOGGER.info(f"Dehumidifier control {status} for '{growspace.name}'")
