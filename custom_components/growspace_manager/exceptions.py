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


class VisionError(GrowspaceError):
    """Base error for every Growspace Vision failure.

    Catching this is the whole "the service failed" case.  ADR 0003 (Vision)
    makes that one rule: on any of these, Home Assistant must not add the frame
    to a Baseline Bucket, create a Visual Comparison Result, or substitute an
    empty, normal or healthy result.  Nothing retries automatically.
    """


class VisionNotConfiguredError(VisionError):
    """No Vision endpoint is available.

    Either the App is not installed or not running and Supervisor discovery
    yielded nothing, or the integration is on manual connection mode with no
    endpoint and token entered.  ``reason`` carries which of those it was, so
    the status projection does not have to re-derive it from the message.
    """

    def __init__(self, message: str, *, reason: str | None = None) -> None:
        """Record why no endpoint could be resolved."""
        super().__init__(message)
        self.reason = reason


class VisionTransportError(VisionError):
    """The App could not be reached, or did not answer within the timeout.

    An integration-side timeout has no response body but exactly the same
    no-write semantics as an App-side failure.
    """


class VisionProtocolError(VisionError):
    """A response did not match the frozen V1 contract.

    Raised for an unknown key, a missing key, a wrong type, a non-finite
    number, or a value outside its declared range.  V1 objects are closed, so
    an additive field is a violation and not a tolerable difference.
    """


class VisionServiceError(VisionError):
    """The App answered with a typed non-2xx error.

    ``code`` is the contract's error code where the body was parseable and
    ``None`` where it was not; ``status`` is always the HTTP status.
    """

    def __init__(
        self,
        message: str,
        *,
        status: int,
        code: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Record the transport status and the typed code behind this failure."""
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id


class VisionBusyError(VisionServiceError):
    """The App's sole inference slot was occupied (429).

    Normal load, not a fault: the App refuses to queue.  It is still a failure
    for this capture, because V1 does not retry automatically.
    """


class VisionAuthError(VisionServiceError):
    """The bearer token was missing or rejected (401)."""


class VisionModelUnavailableError(VisionError):
    """No model this integration may use is loaded.

    Raised both for a `503 model_not_loaded` and for a `/models` catalogue in
    which the pinned model is absent or `unavailable`.  Silently switching to
    another model is never the answer: embeddings from a different model
    version are not comparable, so the Baseline Bucket would be invalidated
    without anyone deciding to.
    """


class VisionIncompatibleError(VisionError):
    """The App shares no analysis schema version with this integration.

    Its `/info` bootstrap still parses — that is why V1 froze it — so an
    incompatible App reports itself rather than looking unreachable.
    """
