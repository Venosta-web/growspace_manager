"""Custom exceptions for the Growspace Manager integration."""

from homeassistant.exceptions import HomeAssistantError, ServiceValidationError


class GrowspaceError(HomeAssistantError):
    """Base error for Growspace Manager."""


class EntityNotFoundError(GrowspaceError):
    """A referenced growspace/plant/record does not exist.

    Maps to the ``entity_not_found`` wire code in the WS Command Lifecycle
    (ADR-0027); service-call paths treat it as any other GrowspaceError.
    """


class CoordinatorNotReadyError(ServiceValidationError):
    """No Growspace Manager instance is loaded yet.

    Maps to the ``coordinator_not_ready`` wire code (ADR-0027). Subclasses
    ServiceValidationError so direct service-call raises keep today's type.
    """


class RateLimitedError(GrowspaceError):
    """An upstream dependency asked us to back off.

    Maps to the ``rate_limited`` wire code (ADR-0027).
    """


class PlantNotFoundError(EntityNotFoundError):
    """Raised when a plant is not found."""


class GrowspaceNotFoundError(EntityNotFoundError):
    """Raised when a growspace is not found."""


class ValidationChangeError(GrowspaceError):
    """Raised when a validation check fails for a state change."""
