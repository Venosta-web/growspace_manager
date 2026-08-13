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


class LayoutConflictError(GrowspaceError):
    """The supplied Layout Revision is no longer current."""


class PlantNotFoundError(EntityNotFoundError):
    """Raised when a plant is not found."""


class GrowspaceNotFoundError(EntityNotFoundError):
    """Raised when a growspace is not found."""


class ValidationChangeError(GrowspaceError):
    """Raised when a validation check fails for a state change."""


class StrainReferenceError(ValidationChangeError):
    """Raised when cultivation records prevent removing a strain."""

    def __init__(
        self, strain: str, *, plant_count: int = 0, has_harvest_history: bool = False
    ) -> None:
        """Describe the references that must be resolved before removal."""
        references = []
        if plant_count:
            record = "record" if plant_count == 1 else "records"
            references.append(f"{plant_count} Plant {record}")
        if has_harvest_history:
            references.append("harvest history")
        reference_summary = " and ".join(references)
        verb = (
            "references"
            if (plant_count == 1 and not has_harvest_history)
            or (not plant_count and has_harvest_history)
            else "reference"
        )
        self.strain = strain
        self.plant_count = plant_count
        self.has_harvest_history = has_harvest_history
        # Rendered separately from the message so UI surfaces can place the phrase
        # into their own translated sentence instead of re-deriving the wording.
        self.detail = f"{reference_summary} still {verb} it"
        super().__init__(
            f"Cannot remove strain '{strain}': {self.detail}. "
            "Resolve the cultivation references first."
        )
