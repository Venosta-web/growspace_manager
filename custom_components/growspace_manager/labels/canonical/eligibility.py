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
to the calibration route. What belongs here is that its absence -- and,
separately, its staleness -- is a named refusal of production printing rather
than a silent one.

There are two questions, and they are asked in two calls because they really
are two. `decide_eligibility` answers what **one result** authorizes: it knows
the diagnostics, the raster, the profile's evidence and this installation's
calibration, and nothing about where the layout came from. `decide_print_request`
answers what **one request** authorizes, starting from the result's own answer
and adding the facts only the print route holds -- whether the layout is a
published revision, whether the content is a real record's rather than a
fixture's, and whether the result being printed is still the one the operator
approved. Folding the second into the first would mean every preview render
carrying refusals about provenance it was never asked to assert.
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
    #: The profile is proven, but not on the model this printer is registered
    #: as -- including a printer Home Assistant has no model for yet, which is
    #: what the niimbot integration registers until the printer has answered.
    PRINTER_MODEL_NOT_COVERED = "printer_model_not_covered"
    #: This installation has not measured where its printer puts ink.
    LOCAL_CALIBRATION_MISSING = "local_calibration_missing"
    #: It measured, and something the measurement depended on has changed.
    #: Distinct from missing because the correction is the same and the
    #: explanation is not: the reasons name what moved.
    LOCAL_CALIBRATION_STALE = "local_calibration_stale"
    #: The layout being printed is a draft, not a published revision.
    REVISION_NOT_PUBLISHED = "revision_not_published"
    #: The content is a representative fixture, not a real record's snapshot.
    CONTENT_NOT_ACTUAL = "content_not_actual"
    #: The result presented for printing is not the one that would be
    #: produced now -- something upstream of the raster has changed since.
    RESULT_NOT_CURRENT = "result_not_current"
    #: This batch has warnings and nobody accepted this exact preflight.
    WARNING_ACKNOWLEDGEMENT_REQUIRED = "warning_acknowledgement_required"
    #: Consent or printer evidence belongs to another immutable preflight.
    PREFLIGHT_NOT_CURRENT = "preflight_not_current"


#: The refusals an operator may choose to print past.
#:
#: Every one of them is a judgement about a raster that exists and that the
#: operator has seen: how far this printer has been proven, or that a
#: diagnostic found something wrong with the layout. Whether that label is
#: good enough to stick on a pot is the operator's call to make -- they have
#: the preview in front of them and the label that comes out in their hand.
#: What stays a hard refusal is whatever would put something *other* than the
#: reviewed preview on paper: no raster at all, a draft, fixture content, or
#: a result that no longer matches the one approved.
OVERRIDABLE_BLOCKERS = frozenset(
    {
        str(Blocker.BLOCKING_DIAGNOSTICS),
        str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
        str(Blocker.PRINTER_MODEL_NOT_COVERED),
        str(Blocker.LOCAL_CALIBRATION_MISSING),
        str(Blocker.LOCAL_CALIBRATION_STALE),
    }
)


def overridable(blocked_by: Sequence[str]) -> bool:
    """Whether every one of these refusals may be printed past, and one exists."""
    return bool(blocked_by) and all(item in OVERRIDABLE_BLOCKERS for item in blocked_by)


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


@dataclass(frozen=True, slots=True)
class PrintProvenance:
    """Where one print request's layout, content and result came from.

    Three assertions the print route makes and a render cannot. Each is a
    fact somebody can check rather than a permission somebody granted: a
    revision is published or it is a draft, a snapshot came from a record or
    from the fixture catalogue, and the result presented either still matches
    what would be rendered now or it does not.
    """

    #: Whether the layout is an immutable published revision.
    published_revision: bool
    #: Whether the content snapshot is one real record's.
    actual_content: bool
    #: Whether the result being printed is still current for its request.
    result_current: bool

    def as_dict(self) -> dict[str, Any]:
        """Return the provenance's wire form."""
        return {
            "published_revision": self.published_revision,
            "actual_content": self.actual_content,
            "result_current": self.result_current,
        }


def decide_print_request(
    decisions: Mapping[str, OperationEligibility],
    operation: Operation,
    *,
    provenance: PrintProvenance,
    override: bool = False,
) -> OperationEligibility:
    """Decide one print request, from one result's answer plus its provenance.

    The result's own refusals come first and keep their order, so an operator
    reading them sees the same reasons in the same places whether they arrived
    from the raster or from the request. Nothing here can *grant* what the
    result refused: this only ever adds reasons.

    A test print asserts none of the three. That is what makes it the
    operation a provisional profile and an unpublished draft can both reach:
    it puts an administrator's own work on paper to be looked at, and it never
    claims to be a label about a record.

    `override` is an operator's consent to print past the
    :data:`OVERRIDABLE_BLOCKERS` -- and only those. It removes them from the
    result's refusals; any other reason still refuses, so an override can
    never be what lets a draft or a missing raster reach paper.
    """
    decision = decisions.get(
        str(operation),
        OperationEligibility(operation=str(operation), allowed=False, blocked_by=()),
    )
    if operation not in _PRODUCTION_OPERATIONS:
        return decision

    blocked = (
        *(
            blocker
            for blocker in decision.blocked_by
            if not (override and blocker in OVERRIDABLE_BLOCKERS)
        ),
        *(
            str(blocker)
            for holds, blocker in (
                (not provenance.published_revision, Blocker.REVISION_NOT_PUBLISHED),
                (not provenance.actual_content, Blocker.CONTENT_NOT_ACTUAL),
                (not provenance.result_current, Blocker.RESULT_NOT_CURRENT),
            )
            if holds
        ),
    )
    return OperationEligibility(
        operation=str(operation), allowed=not blocked, blocked_by=blocked
    )


#: The operations that put a real record on paper, and therefore the only ones
#: provenance is asked about.
_PRODUCTION_OPERATIONS = frozenset({Operation.SINGLE_PRINT, Operation.BATCH_PREFLIGHT})


def decide_eligibility(
    diagnostics: Sequence[Diagnostic],
    *,
    has_raster: bool,
    profile: CapabilityProfile,
    local_calibration: str | None = None,
    calibration_stale_reasons: Sequence[str] = (),
    printer_covered: bool = True,
) -> Mapping[str, OperationEligibility]:
    """Decide every operation for one result, with the reasons for each.

    `printer_covered` is false when the render names a printer whose model
    the profile's evidence was not taken on. That is its own blocker rather
    than the profile's: the commonest cause is a printer the evidence *was*
    taken on that Home Assistant registered before it had learned the model,
    and telling that operator their profile "has not passed physical testing"
    names the wrong thing entirely.

    Reasons accumulate rather than short-circuit: an operation refused for
    three independent reasons says all three, because fixing one of them and
    finding the button still disabled is how a recovery path loses people.
    """
    blocking = has_blocking(diagnostics)
    missing_raster = not has_raster
    provisional = not profile.authorizes_production
    uncovered = not printer_covered
    # A stale calibration contributes no identity, so it would otherwise read
    # as a missing one as well -- and the two are mutually exclusive accounts
    # of the same printer. Telling an administrator that they never measured
    # it *and* that their measurement moved is one sentence too many, and the
    # wrong one of the two is the discouraging one. Stale is the more specific
    # truth, so stale wins and missing means what it says.
    stale = bool(calibration_stale_reasons)
    uncalibrated = local_calibration is None and not stale

    def reasons(*conditions: tuple[bool, Blocker]) -> tuple[str, ...]:
        return tuple(str(blocker) for holds, blocker in conditions if holds)

    printable = (
        (blocking, Blocker.BLOCKING_DIAGNOSTICS),
        (missing_raster, Blocker.NO_RASTER),
    )
    production = (
        *printable,
        (provisional, Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
        (uncovered, Blocker.PRINTER_MODEL_NOT_COVERED),
        (uncalibrated, Blocker.LOCAL_CALIBRATION_MISSING),
        (stale, Blocker.LOCAL_CALIBRATION_STALE),
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
