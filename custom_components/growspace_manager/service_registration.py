"""Service registration helper for Growspace Manager."""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import partial
import logging
from types import ModuleType
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .coordinator import GrowspaceCoordinator
from .exceptions import GrowspaceError
from .services import (
    ai_assistant,
    batch,
    config_facade,
    debug,
    drain_ec,
    drying,
    ec_ramp,
    environment,
    genetics,
    growspace_facade,
    irrigation,
    irrigation_recipes,
    irrigation_watering,
    nutrient_presets,
    plant_cloning,
    plant_facade,
    plant_lifecycle,
    plant_scoring,
    plant_spatial,
    report,
    strain_library,
    tank_config,
    vision_checkup,
    water_analytics,
)
from .strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)

_SERVICE_MODULES: list[ModuleType] = [
    ai_assistant,
    batch,
    config_facade,
    debug,
    drain_ec,
    drying,
    ec_ramp,
    environment,
    genetics,
    growspace_facade,
    irrigation,
    irrigation_recipes,
    irrigation_watering,
    nutrient_presets,
    plant_cloning,
    plant_facade,
    plant_lifecycle,
    plant_scoring,
    plant_spatial,
    report,
    strain_library,
    tank_config,
    vision_checkup,
    water_analytics,
]


async def register_services(
    hass: HomeAssistant,
    strain_lib: StrainLibrary,
) -> None:
    """Register services for the Growspace Manager integration."""

    async def _wrap_dynamic(
        handler: Callable[..., Coroutine[Any, Any, Any]],
        needs_strain_lib: bool,
        call: ServiceCall,
    ) -> Any:
        try:
            coordinator = GrowspaceCoordinator.get_for_service_call(hass, call)
            if needs_strain_lib:
                return await handler(hass, coordinator, strain_lib, call)
            return await handler(hass, coordinator, call)
        except GrowspaceError as err:
            raise ServiceValidationError(str(err)) from err

    for module in _SERVICE_MODULES:
        for service_def in module.SERVICES:
            service_name = service_def.name
            handler = service_def.handler
            schema = service_def.schema
            needs_strain_lib = service_def.needs_strain_lib
            supports_response = service_def.supports_response

            wrapped_handler = partial(_wrap_dynamic, handler, needs_strain_lib)

            hass.services.async_register(
                DOMAIN,
                service_name,
                cast(Any, wrapped_handler),
                schema=schema,
                supports_response=supports_response,
            )
            _LOGGER.debug("Registered service: %s", service_name)
