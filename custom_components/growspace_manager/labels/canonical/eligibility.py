"""What one Render Result is allowed to do, decided here and nowhere else.

"Printable" is not one boolean. A layout with a warning may reach paper as a
single print and still not reach a batch; a provisional profile renders an
exact bitmap and may print a calibration label but never a production one;
an administrator test print is permitted from a draft that must not publish.
So the result carries an answer per operation, each with the reasons it was
refused -- and the card reads those answers rather than inferring them from a
warning count on the other side of the wire.

The inputs are deliberately few, because every one of them is an identity
somebody can check: whether any diagnostic blocks, whether a raster exists at
all, how far the profile's evidence has been taken, and whether this
installation's own calibration is current. Nothing here looks at how a result
*feels*.

Local calibration is one of those inputs and not one of this module's
concerns: the measured record, how it is captured and what stales it belong
to the calibration route. What belongs here is that its absence is a named
refusal of production printing rather than a silent one.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .diagnostics import Diagnostic, has_blocking
from .profiles import CapabilityProfile


class Operation(StrEnum):
    """The operations a Render Result can be asked to authorize."""

    #: Keep the editor's work, valid or not.
    DRAFT_AUTOSAVE = "draft_autosave"
    #: Report every attributable diagnostic, and grant nothing.
    CANDIDATE_VALIDATION = "candidate_validation"
    #: Show the authoritative raster.
    PREVIEW = "preview"
    #: Turn a draft into an immutable revision.
    PUBLISH = "publish"
    #: Put an administrator's own draft on paper, to look at it.
    TEST_PRINT = "test_print"
    #: Put one real record on paper.
    SINGLE_PRINT = "single_print"
    #: Put many real records on paper under one immutable plan.
    BATCH_PREFLIGHT = "batch_preflight"


class Blocker(StrEnum):
    """Why one operation is refused. Stable, and never collapsed into a count."""

    #: At least one diagnostic of this result is an error.
    BLOCKING_DIAGNOSTICS = "blocking_diagnostics"
    #: There is no raster, so there is nothing to authorize.
    NO_RASTER = "no_raster"
    #: The profile's physical evidence matrix has not been recorded.
    PROFILE_NOT_PRODUCT_VERIFIED = "profile_not_product_verified"
    #: This installation has not measured where its printer puts ink.
    LOCAL_CALIBRATION_MISSING = "local_calibration_missing"


@dataclass(frozen=True, slots=True)
class OperationEligibility:
    """Whether one operation may proceed from this exact result."""

    operation: str
    allowed: bool
    blocked_by: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the decision's wire form."""
        return {
            "operation": self.operation,
            "allowed": self.allowed,
            "blocked_by": list(self.blocked_by),
        }


def decide_eligibility(
    diagnostics: Sequence[Diagnostic],
    *,
    has_raster: bool,
    profile: CapabilityProfile,
    local_calibration: str | None = None,
) -> Mapping[str, OperationEligibility]:
    """Decide every operation for one result, with the reasons for each.

    Reasons accumulate rather than short-circuit: an operation refused for
    three independent reasons says all three, because fixing one of them and
    finding the button still disabled is how a recovery path loses people.
    """
    blocking = has_blocking(diagnostics)
    missing_raster = not has_raster
    provisional = not profile.authorizes_production
    uncalibrated = local_calibration is None

    def reasons(*conditions: tuple[bool, Blocker]) -> tuple[str, ...]:
        return tuple(str(blocker) for holds, blocker in conditions if holds)

    printable = (
        (blocking, Blocker.BLOCKING_DIAGNOSTICS),
        (missing_raster, Blocker.NO_RASTER),
    )
    production = (
        *printable,
        (provisional, Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
        (uncalibrated, Blocker.LOCAL_CALIBRATION_MISSING),
    )

    decisions = {
        # Recoverable data is kept whatever state it is in. An editor that
        # refused to remember invalid work would make every diagnostic a
        # threat to the draft.
        Operation.DRAFT_AUTOSAVE: (),
        # Validation is the operation that reports; it authorizes nothing, so
        # nothing can refuse it either.
        Operation.CANDIDATE_VALIDATION: (),
        Operation.PREVIEW: reasons((missing_raster, Blocker.NO_RASTER)),
        Operation.PUBLISH: reasons((blocking, Blocker.BLOCKING_DIAGNOSTICS)),
        # A provisional profile may put its own calibration and test output on
        # paper -- that is how it stops being provisional -- so evidence and
        # calibration are not among a test print's blockers.
        Operation.TEST_PRINT: reasons(*printable),
        Operation.SINGLE_PRINT: reasons(*production),
        Operation.BATCH_PREFLIGHT: reasons(*production),
    }
    return {
        str(operation): OperationEligibility(
            operation=str(operation),
            allowed=not blocked,
            blocked_by=blocked,
        )
        for operation, blocked in decisions.items()
    }
