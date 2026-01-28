"""Shared utilities for service handlers."""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ServiceValidationError

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

from custom_components.growspace_manager.exceptions import GrowspaceError

_LOGGER = logging.getLogger(__name__)


def get_validated_coordinator(config_entry: ConfigEntry) -> GrowspaceCoordinator:
    """Get and validate coordinator from config entry.

    Args:
        config_entry: Configuration entry to get coordinator from

    Returns:
        Validated GrowspaceCoordinator instance

    Raises:
        ServiceValidationError: If coordinator not available
    """
    if not config_entry or not config_entry.runtime_data:
        raise ServiceValidationError("Coordinator not available")
    return config_entry.runtime_data


def handle_service_errors(func: Callable[..., Any]) -> Callable[..., Any]:
    """Decorator to standardize service error handling.

    Catches GrowspaceError and generic exceptions, converting them to
    ServiceValidationError with appropriate logging.

    Args:
        func: Async service handler function to wrap

    Returns:
        Wrapped function with error handling
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await func(*args, **kwargs)
        except ServiceValidationError:
            # Already a ServiceValidationError, re-raise as-is
            raise
        except GrowspaceError as err:
            # Domain-specific errors, convert to ServiceValidationError
            raise ServiceValidationError(str(err)) from err
        except Exception as err:
            # Unexpected errors, log and convert
            _LOGGER.exception("Unexpected error in %s", func.__name__)
            raise ServiceValidationError(f"Operation failed: {err}") from err

    return wrapper
