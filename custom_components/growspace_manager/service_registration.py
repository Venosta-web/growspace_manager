"""Service registration helper for Growspace Manager."""
from __future__ import annotations

from collections.abc import Callable, Coroutine
from functools import partial
import importlib
import logging
import pkgutil
from typing import Any, cast

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError

from .const import DOMAIN
from .coordinator import GrowspaceCoordinator
from .exceptions import GrowspaceError
from . import services as services_pkg
from .strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


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

    # Iterate over all modules in the services package
    for module_info in pkgutil.iter_modules(services_pkg.__path__, f"{services_pkg.__name__}."):
        # Skip internal modules
        if module_info.name.endswith("._definition") or module_info.name.endswith(".utils"):
            continue

        try:
            module = importlib.import_module(module_info.name)
        except Exception:
            _LOGGER.exception("Failed to import service module: %s", module_info.name)
            continue

        if not hasattr(module, "SERVICES"):
            continue

        services = getattr(module, "SERVICES")
        for service_def in services:
            service_name = service_def.name
            handler = service_def.handler
            schema = service_def.schema
            needs_strain_lib = service_def.needs_strain_lib
            supports_response = service_def.supports_response

            # Wrap the handler
            wrapped_handler = partial(_wrap_dynamic, handler, needs_strain_lib)

            # Register the service
            hass.services.async_register(
                DOMAIN,
                service_name,
                cast(Any, wrapped_handler),
                schema=schema,
                supports_response=supports_response,
            )
            _LOGGER.debug("Registered service: %s", service_name)
