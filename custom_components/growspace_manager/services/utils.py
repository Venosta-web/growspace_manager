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

# Typed WebSocket error codes (stay inside HA's wire format — ADR 0005)
WS_ERR_COORDINATOR_NOT_READY = "coordinator_not_ready"
WS_ERR_CONFLICT = "conflict"
WS_ERR_ENTITY_NOT_FOUND = "entity_not_found"
WS_ERR_VALIDATION_FAILED = "validation_failed"
WS_ERR_INTERNAL_ERROR = "internal_error"
WS_ERR_RATE_LIMITED = "rate_limited"


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


def invalidates_cache(growspace_id_kwarg: str = "growspace_id") -> Callable[..., Any]:
    """Decorator that clears the view-model cache for the affected growspace after a mutation.

    The 30-second TTL in ViewModelBuilder.build_serialized_growspace is the stale-data
    window identified in ADR 0005. Explicit invalidation on mutation closes that window
    without changing the frontend's refresh architecture.

    Args:
        growspace_id_kwarg: Name of the kwarg (or first positional after call data) that
                            holds the growspace_id. Defaults to ``"growspace_id"``.
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = await func(*args, **kwargs)
            growspace_id: str | None = kwargs.get(growspace_id_kwarg) or (
                args[1].get(growspace_id_kwarg)
                if len(args) > 1 and isinstance(args[1], dict)
                else None
            )
            if growspace_id:
                try:
                    coordinator: GrowspaceCoordinator = args[0]
                    coordinator.cache.pop(growspace_id, None)
                except AttributeError, IndexError:
                    pass
            return result

        return wrapper

    return decorator
