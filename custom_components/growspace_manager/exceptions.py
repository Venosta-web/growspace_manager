"""Custom exceptions for the Growspace Manager integration."""

from homeassistant.exceptions import HomeAssistantError


class GrowspaceError(HomeAssistantError):
    """Base error for Growspace Manager."""


class PlantNotFoundError(GrowspaceError):
    """Raised when a plant is not found."""


class GrowspaceNotFoundError(GrowspaceError):
    """Raised when a growspace is not found."""


class ValidationChangeError(GrowspaceError):
    """Raised when a validation check fails for a state change."""
