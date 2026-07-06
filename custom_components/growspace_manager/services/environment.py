"""Service handlers for environment configuration.

Every EnvironmentConfig write routes through the Environment Patch seam
(ADR-0026): a writer-specific builder in ``domain/environment_patch.py``
validates and normalises the payload, and ``async_commit_environment_patch``
performs the assign → save → refresh → controller-restart → repair sequence.
Patch semantics: an omitted field keeps its current value; an explicitly sent
empty value is a deliberate clear.
"""

from __future__ import annotations

import logging

from custom_components.growspace_manager.const import GrowspaceService
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.environment_patch import (
    EnvironmentPatch,
    EnvironmentPatchError,
    circulation_fan_patch,
    exhaust_fan_patch,
    patch_from_service_call,
)
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.schemas import (
    CONFIGURE_CIRCULATION_FAN_SCHEMA,
    CONFIGURE_ENVIRONMENT_SCHEMA,
    CONFIGURE_EXHAUST_FAN_SCHEMA,
    REMOVE_ENVIRONMENT_SCHEMA,
    SET_DEHUMIDIFIER_CONTROL_SCHEMA,
    SET_HUMIDIFIER_CONTROL_SCHEMA,
)
from custom_components.growspace_manager.services.environment_patch_commit import (
    async_commit_environment_patch,
)
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from ._definition import ServiceDefinition

_LOGGER = logging.getLogger(__name__)


def _get_growspace(coordinator: GrowspaceCoordinator, call: ServiceCall) -> Growspace:
    """Resolve the target growspace or raise a user-facing error."""
    growspace_id = call.data.get("growspace_id")
    if growspace_id not in coordinator.growspaces:
        error_msg = f"Growspace '{growspace_id}' not found"
        _LOGGER.error(error_msg)
        raise ServiceValidationError(error_msg)
    return coordinator.growspaces[growspace_id]


async def _commit_or_raise(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    growspace: Growspace,
    patch: EnvironmentPatch,
) -> None:
    """Commit a built patch, mapping seam errors to ServiceValidationError."""
    try:
        await async_commit_environment_patch(hass, coordinator, growspace, patch)
    except EnvironmentPatchError as err:
        raise ServiceValidationError(str(err)) from err


async def handle_configure_environment(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the configure_environment service call (patch semantics)."""
    growspace = _get_growspace(coordinator, call)
    try:
        patch = patch_from_service_call(call.data)
    except EnvironmentPatchError as err:
        raise ServiceValidationError(str(err)) from err
    await _commit_or_raise(hass, coordinator, growspace, patch)


async def handle_remove_environment(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the remove_environment service call."""
    growspace = _get_growspace(coordinator, call)

    # A deliberate whole reset, not a merge — the one writer that bypasses
    # the patch seam by design.
    growspace.environment_config = EnvironmentConfig()

    await coordinator.services.save()
    await coordinator.services.request_refresh()

    _LOGGER.info("Environment monitoring removed for '%s'", growspace.name)


async def handle_set_dehumidifier_control(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the set_dehumidifier_control service call."""
    growspace = _get_growspace(coordinator, call)
    enabled = bool(call.data.get("enabled"))
    await _commit_or_raise(
        hass,
        coordinator,
        growspace,
        EnvironmentPatch(values={"control_dehumidifier": enabled}),
    )
    status = "enabled" if enabled else "disabled"
    _LOGGER.info("Dehumidifier control %s for '%s'", status, growspace.name)


async def handle_set_humidifier_control(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the set_humidifier_control service call."""
    growspace = _get_growspace(coordinator, call)
    enabled = bool(call.data.get("enabled"))
    await _commit_or_raise(
        hass,
        coordinator,
        growspace,
        EnvironmentPatch(values={"control_humidifier": enabled}),
    )
    status = "enabled" if enabled else "disabled"
    _LOGGER.info("Humidifier control %s for '%s'", status, growspace.name)


async def handle_configure_circulation_fan(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the configure_circulation_fan service call."""
    growspace = _get_growspace(coordinator, call)
    try:
        patch = circulation_fan_patch(call.data)
    except EnvironmentPatchError as err:
        raise ServiceValidationError(str(err)) from err
    await _commit_or_raise(hass, coordinator, growspace, patch)
    _LOGGER.info("Circulation fan controller configured for '%s'", growspace.name)


async def handle_configure_exhaust_fan(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    call: ServiceCall,
) -> None:
    """Handle the configure_exhaust_fan service call.

    Exhaust demand is always combined (temperature/humidity/VPD), so there is
    no regulation mode or wind layer.
    """
    growspace = _get_growspace(coordinator, call)
    try:
        patch = exhaust_fan_patch(call.data)
    except EnvironmentPatchError as err:
        raise ServiceValidationError(str(err)) from err
    await _commit_or_raise(hass, coordinator, growspace, patch)
    _LOGGER.info("Exhaust fan controller configured for '%s'", growspace.name)


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
    ServiceDefinition(
        GrowspaceService.CONFIGURE_EXHAUST_FAN,
        handle_configure_exhaust_fan,
        CONFIGURE_EXHAUST_FAN_SCHEMA,
    ),
]
