"""Tests for operation-specific print eligibility (hub issues #216, #221).

"Printable" is four different questions, and the reason they are asked
separately is that their answers differ for the same result: a provisional
profile may put its own calibration label on paper and never a real one, a
draft may test-print and never publish, a warning stops nothing and an error
stops everything. Each test below is one of those divergences.

The second property is the refusals themselves. An operation says every reason
it was refused rather than the first, because fixing one of three and finding
the button still disabled is how a recovery path loses people.

Issue #221 adds the second question. `decide_eligibility` answers what one
*result* authorizes; `decide_print_request` answers what one *request* does,
adding the three facts only the print route holds. The tests for it are at the
bottom, and the property they guard is that it only ever adds reasons.
"""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    Blocker,
    Diagnostic,
    Layer,
    Operation,
    PrintProvenance,
    Severity,
    decide_eligibility,
    decide_print_request,
)
from tests.labels.support import product_verified

PROVISIONAL = NIIMBOT_B1_50X30
VERIFIED = product_verified(NIIMBOT_B1_50X30)

ERROR = Diagnostic(
    code="profile.text_below_readable_floor",
    severity=Severity.ERROR,
    layer=Layer.PROFILE_COMPILATION,
    message="too small",
)
WARNING = Diagnostic(
    code="raster.ink_overlap",
    severity=Severity.WARNING,
    layer=Layer.RASTER,
    message="overlap",
)


def _decide(
    diagnostics=(),
    *,
    has_raster=True,
    profile=VERIFIED,
    calibration="cal-1",
    stale=(),
):
    return decide_eligibility(
        diagnostics,
        has_raster=has_raster,
        profile=profile,
        local_calibration=calibration,
        calibration_stale_reasons=stale,
    )


#: A request that asserts everything a production print needs of it.
COMPLETE = PrintProvenance(
    published_revision=True, actual_content=True, result_current=True
)


def _blocked(decisions, operation):
    return decisions[str(operation)].blocked_by


# ---------------------------------------------------------------------------
# The matrix
# ---------------------------------------------------------------------------


def test_a_clean_result_on_a_verified_calibrated_profile_authorizes_everything() -> (
    None
):
    decisions = _decide()
    assert all(decision.allowed for decision in decisions.values())
    assert set(decisions) == {str(operation) for operation in Operation}


def test_a_warning_stops_nothing() -> None:
    """A single print does not collect a ceremony for a warning; the operator
    can read it and print. The batch acknowledgement is the deliberate
    exception, and it belongs to the batch route rather than here."""
    decisions = _decide([WARNING])
    assert all(decision.allowed for decision in decisions.values())


def test_an_error_stops_every_operation_that_asserts_anything() -> None:
    decisions = _decide([ERROR])
    assert decisions[str(Operation.DRAFT_AUTOSAVE)].allowed is True
    assert decisions[str(Operation.CANDIDATE_VALIDATION)].allowed is True
    assert decisions[str(Operation.PREVIEW)].allowed is True
    for operation in (
        Operation.PUBLISH,
        Operation.TEST_PRINT,
        Operation.SINGLE_PRINT,
        Operation.BATCH_PREFLIGHT,
    ):
        assert _blocked(decisions, operation) == (str(Blocker.BLOCKING_DIAGNOSTICS),)


def test_invalid_work_is_still_kept() -> None:
    decisions = _decide(
        [ERROR], has_raster=False, profile=PROVISIONAL, calibration=None
    )
    assert decisions[str(Operation.DRAFT_AUTOSAVE)].allowed is True
    assert decisions[str(Operation.DRAFT_AUTOSAVE)].blocked_by == ()


def test_validation_grants_nothing_and_is_refused_by_nothing() -> None:
    decisions = _decide([ERROR], has_raster=False)
    assert decisions[str(Operation.CANDIDATE_VALIDATION)].allowed is True


# ---------------------------------------------------------------------------
# Evidence and calibration
# ---------------------------------------------------------------------------


def test_a_provisional_profile_previews_and_test_prints_but_never_produces() -> None:
    """That is how a provisional profile stops being provisional: it has to be
    able to put its own calibration label on paper."""
    decisions = _decide(profile=PROVISIONAL, calibration=None)
    assert decisions[str(Operation.PREVIEW)].allowed is True
    assert decisions[str(Operation.TEST_PRINT)].allowed is True
    assert decisions[str(Operation.PUBLISH)].allowed is True
    assert _blocked(decisions, Operation.SINGLE_PRINT) == (
        str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
        str(Blocker.LOCAL_CALIBRATION_MISSING),
    )


def test_a_verified_profile_without_local_calibration_cannot_produce() -> None:
    decisions = _decide(calibration=None)
    assert decisions[str(Operation.TEST_PRINT)].allowed is True
    assert _blocked(decisions, Operation.SINGLE_PRINT) == (
        str(Blocker.LOCAL_CALIBRATION_MISSING),
    )
    assert _blocked(decisions, Operation.BATCH_PREFLIGHT) == (
        str(Blocker.LOCAL_CALIBRATION_MISSING),
    )


def test_local_calibration_cannot_promote_an_unverified_profile() -> None:
    """One alignment label cannot establish readable fonts, QR scanning or
    density mapping, so measuring this printer does not make its class
    supported."""
    decisions = _decide(profile=PROVISIONAL, calibration="cal-1")
    assert _blocked(decisions, Operation.SINGLE_PRINT) == (
        str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
    )


# ---------------------------------------------------------------------------
# Refusals are complete
# ---------------------------------------------------------------------------


def test_every_independent_reason_is_named_rather_than_the_first() -> None:
    decisions = _decide(
        [ERROR], has_raster=False, profile=PROVISIONAL, calibration=None
    )
    assert _blocked(decisions, Operation.SINGLE_PRINT) == (
        str(Blocker.BLOCKING_DIAGNOSTICS),
        str(Blocker.NO_RASTER),
        str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
        str(Blocker.LOCAL_CALIBRATION_MISSING),
    )


def test_a_result_with_no_raster_cannot_be_previewed_or_printed() -> None:
    decisions = _decide(has_raster=False)
    assert _blocked(decisions, Operation.PREVIEW) == (str(Blocker.NO_RASTER),)
    assert str(Blocker.NO_RASTER) in _blocked(decisions, Operation.TEST_PRINT)
    # Publication is about the document, not about whether a raster came back.
    assert decisions[str(Operation.PUBLISH)].allowed is True


@pytest.mark.parametrize("operation", list(Operation))
def test_every_decision_serializes_for_the_wire(operation: Operation) -> None:
    decision = _decide([ERROR])[str(operation)]
    wire = decision.as_dict()
    assert set(wire) == {"operation", "allowed", "blocked_by"}
    assert wire["operation"] == str(operation)


# ---------------------------------------------------------------------------
# Stale calibration
# ---------------------------------------------------------------------------


def test_a_stale_calibration_blocks_production_by_its_own_name() -> None:
    decisions = _decide(calibration=None, stale=("renderer_version",))
    assert _blocked(decisions, Operation.SINGLE_PRINT) == (
        str(Blocker.LOCAL_CALIBRATION_STALE),
    )


def test_stale_and_missing_are_never_reported_together() -> None:
    """They are mutually exclusive accounts of the same printer. Telling an
    administrator both that they never measured it and that their measurement
    moved is one sentence too many, and the wrong one of the two is the
    discouraging one."""
    blocked = _blocked(
        _decide(calibration=None, stale=("dpi",)), Operation.SINGLE_PRINT
    )
    assert str(Blocker.LOCAL_CALIBRATION_MISSING) not in blocked


def test_a_stale_calibration_still_test_prints() -> None:
    """Which is how it stops being stale: the calibration label goes through
    the test-print route."""
    decisions = _decide(calibration=None, stale=("dpi",))
    assert decisions[str(Operation.TEST_PRINT)].allowed is True


# ---------------------------------------------------------------------------
# The request, on top of the result
# ---------------------------------------------------------------------------


def test_a_complete_request_on_an_allowed_result_prints() -> None:
    decision = decide_print_request(
        _decide(), Operation.SINGLE_PRINT, provenance=COMPLETE
    )
    assert decision.allowed
    assert decision.blocked_by == ()


def test_provenance_only_ever_adds_reasons() -> None:
    """It can never grant what the result refused."""
    decision = decide_print_request(
        _decide([ERROR]), Operation.SINGLE_PRINT, provenance=COMPLETE
    )
    assert decision.blocked_by == (str(Blocker.BLOCKING_DIAGNOSTICS),)


def test_the_result_s_reasons_come_first_and_keep_their_order() -> None:
    """So an operator reading them sees the same reasons in the same places
    whether they arrived from the raster or from the request."""
    decision = decide_print_request(
        _decide(profile=PROVISIONAL, calibration=None),
        Operation.SINGLE_PRINT,
        provenance=PrintProvenance(
            published_revision=False, actual_content=False, result_current=False
        ),
    )
    assert decision.blocked_by == (
        str(Blocker.PROFILE_NOT_PRODUCT_VERIFIED),
        str(Blocker.LOCAL_CALIBRATION_MISSING),
        str(Blocker.REVISION_NOT_PUBLISHED),
        str(Blocker.CONTENT_NOT_ACTUAL),
        str(Blocker.RESULT_NOT_CURRENT),
    )


@pytest.mark.parametrize(
    ("provenance", "blocker"),
    [
        (
            PrintProvenance(
                published_revision=False, actual_content=True, result_current=True
            ),
            Blocker.REVISION_NOT_PUBLISHED,
        ),
        (
            PrintProvenance(
                published_revision=True, actual_content=False, result_current=True
            ),
            Blocker.CONTENT_NOT_ACTUAL,
        ),
        (
            PrintProvenance(
                published_revision=True, actual_content=True, result_current=False
            ),
            Blocker.RESULT_NOT_CURRENT,
        ),
    ],
)
def test_each_missing_assertion_is_refused_by_its_own_name(
    provenance: PrintProvenance, blocker: Blocker
) -> None:
    decision = decide_print_request(
        _decide(), Operation.SINGLE_PRINT, provenance=provenance
    )
    assert decision.blocked_by == (str(blocker),)


@pytest.mark.parametrize(
    "operation",
    [
        Operation.DRAFT_AUTOSAVE,
        Operation.CANDIDATE_VALIDATION,
        Operation.PREVIEW,
        Operation.PUBLISH,
        Operation.TEST_PRINT,
    ],
)
def test_an_operation_that_puts_no_record_on_paper_is_asked_nothing(
    operation: Operation,
) -> None:
    """A test print asserting a published revision would make an editor's own
    draft unprintable, which is the one thing a test print is for."""
    nothing = PrintProvenance(
        published_revision=False, actual_content=False, result_current=False
    )
    assert (
        decide_print_request(_decide(), operation, provenance=nothing)
        == _decide()[str(operation)]
    )


def test_a_batch_preflight_asserts_the_same_five_things_a_single_print_does() -> None:
    assert (
        decide_print_request(
            _decide(), Operation.BATCH_PREFLIGHT, provenance=COMPLETE
        ).allowed
        is True
    )
    assert decide_print_request(
        _decide(),
        Operation.BATCH_PREFLIGHT,
        provenance=PrintProvenance(
            published_revision=False, actual_content=True, result_current=True
        ),
    ).blocked_by == (str(Blocker.REVISION_NOT_PUBLISHED),)


def test_provenance_serializes_for_the_wire() -> None:
    assert set(COMPLETE.as_dict()) == {
        "published_revision",
        "actual_content",
        "result_current",
    }
