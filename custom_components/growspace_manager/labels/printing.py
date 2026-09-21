"""Putting one label on paper: the three routes, and what each one asserts.

The canonical renderer answers "what does this look like and may it print?".
This module is what happens next, and it exists because the three ways a label
reaches paper assert three different things:

    calibration label   the standardized sheet, against a profile that may
                        still be provisional. It is how a provisional profile
                        and an unmeasured printer stop being either. The
                        evidence label rides the same route: it probes the
                        profile's claimed limits for a person to photograph,
                        and records nothing here.
    test print          an administrator's own draft or revision, against a
                        representative subject, to look at it on paper.
    production print    one real record, from a published revision, on a
                        product-verified profile this installation has
                        measured, printing the exact raster the operator
                        approved.

**Nothing reaches paper that has not been judged.** `async_render` sends to
the printer integration and only then reports what the diagnostics were, so a
route that rendered straight to paper would find out that a layout was
unprintable from the label already in the tray. Every route here therefore
renders twice: once as a preview, which is judged, and then -- only if that
judgement allows it -- once as the print. The second render is the first one's
bitmap because the raster inputs are a pure function of the layout, the
immutable content snapshot, the profile and the density, none of which can
move between the two. That is not an assumption: both renders report the
digest of the exact payload the adapter was handed, and the routes compare
them.

That same property is what makes a **retry** honest. A caller passes the
raster identity of the result it approved, and a route refuses rather than
prints when the identity it would produce now is a different one. Reprinting
"the same label" from a template that has since been edited, a record that has
since changed or a font that has since been replaced is the failure this
prevents, and it cannot be prevented by looking at the picture.

Who may do what is asked at the moment of the print and never captured
earlier. Calibration and test printing are administrators' operations --
both put unproven output on paper deliberately. A production print is any
authenticated user's, because printing a label for a plant is ordinary work.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from ..exceptions import GrowspaceError
from .calibration.errors import CalibrationSheetNotPrinted
from .calibration.evidence_sheet import evidence_layout
from .calibration.ledger import (
    LocalCalibrationLedger,
    recorded_dependencies,
    required_dependencies,
)
from .calibration.records import CalibrationDependencies
from .calibration.sheet import calibration_content, calibration_layout
from .calibration.staleness import CalibrationStatus
from .canonical.content import LabelContentSnapshot
from .canonical.diagnostics import Layer, Severity
from .canonical.document import LabelLayout
from .canonical.eligibility import (
    Blocker,
    Operation,
    OperationEligibility,
    PrintProvenance,
    decide_print_request,
)
from .canonical.factory import FactoryTemplate
from .canonical.fonts import FontLibrary
from .canonical.preview import PREVIEW, async_render, font_library_for
from .canonical.profiles import CapabilityProfile
from .canonical.result import RenderResult
from .canonical.subjects import RECORD_SOURCE
from .library.actor import Actor

_LOGGER = logging.getLogger(__name__)

#: How a layout that came from somewhere unpublished names itself.
DRAFT = "draft"
#: A shipped Factory Template, which is published by virtue of being shipped.
FACTORY = "factory"
#: An administrator's Named Template, at one immutable revision.
REVISION = "revision"
#: The standardized calibration sheet, which is neither.
CALIBRATION = "calibration"
#: The evidence label, which probes a profile's claimed limits on paper.
EVIDENCE = "evidence"


class PrintRefused(GrowspaceError):
    """One print route refused, naming every reason rather than the first.

    Carries the operation and its blockers so a caller can route a user to the
    correction -- profile selection, calibration, the editor, a fresh preview
    -- instead of showing a sentence and a disabled button.
    """

    def __init__(
        self, operation: str, blockers: Sequence[str], detail: str = ""
    ) -> None:
        """Name the operation, its blockers, and anything extra worth saying."""
        self.operation = operation
        self.blockers = tuple(blockers)
        reasons = ", ".join(self.blockers) or "no reason was recorded"
        super().__init__(
            f"{operation} was refused: {reasons}.{f' {detail}' if detail else ''}"
        )


class PrintFailed(HomeAssistantError):
    """Every gate passed, the label was sent, and the printer did not take it.

    Not a refusal: nothing about the request was wrong, and the same request
    may succeed a minute later. A batch records it as a failed attempt that
    retry can send again; a single print says so rather than reporting a
    label that never reached paper as printed.
    """


@dataclass(frozen=True, slots=True)
class LayoutSource:
    """Where a print's layout came from, as a fact rather than a claim.

    `published` is the one thing a production print cannot take on trust, so
    it is set by the constructors rather than by callers: a Template Revision
    and a Factory Template are published because there is no way to hold one
    that is not, and a draft is not because there is no way to publish one
    without it becoming a revision.
    """

    layout: LabelLayout
    published: bool
    kind: str
    #: What an audit record names this layout by.
    reference: str

    @classmethod
    def from_revision(
        cls, layout: LabelLayout, *, template_id: str, revision: int
    ) -> LayoutSource:
        """One immutable published revision of a Named Template."""
        return cls(
            layout=layout,
            published=True,
            kind=REVISION,
            reference=f"{REVISION}:{template_id}@{revision}",
        )

    @classmethod
    def from_factory(cls, template: FactoryTemplate) -> LayoutSource:
        """One shipped layout, at the revision this integration version ships."""
        return cls(
            layout=template.layout,
            published=True,
            kind=FACTORY,
            reference=f"{FACTORY}:{template.id}@{template.revision}",
        )

    @classmethod
    def from_draft(cls, layout: LabelLayout, *, draft_key: str) -> LayoutSource:
        """One administrator's unpublished work."""
        return cls(
            layout=layout,
            published=False,
            kind=DRAFT,
            reference=f"{DRAFT}:{draft_key}",
        )

    @classmethod
    def from_calibration(cls, layout: LabelLayout, *, profile_id: str) -> LayoutSource:
        """The standardized sheet, which is published by nobody and about nothing."""
        return cls(
            layout=layout,
            published=False,
            kind=CALIBRATION,
            reference=f"{CALIBRATION}:{profile_id}",
        )

    @classmethod
    def from_evidence(cls, layout: LabelLayout, *, profile_id: str) -> LayoutSource:
        """The evidence label, which is as unpublished as the calibration sheet."""
        return cls(
            layout=layout,
            published=False,
            kind=EVIDENCE,
            reference=f"{EVIDENCE}:{profile_id}",
        )

    def as_dict(self) -> dict[str, Any]:
        """Return the source's wire form, without the layout itself."""
        return {
            "kind": self.kind,
            "reference": self.reference,
            "published": self.published,
        }


@dataclass(frozen=True, slots=True)
class PrintOutcome:
    """One label that reached paper, and everything that authorized it."""

    operation: str
    source: LayoutSource
    #: The judged preview: what was decided, and the raster that was decided on.
    judged: RenderResult
    #: The committed print. Its raster inputs are the judged one's.
    printed: RenderResult
    decision: OperationEligibility

    @property
    def raster_identity(self) -> str:
        """The identity every operation drawing this bitmap shares."""
        return self.judged.raster_identity

    @property
    def raster_input_digest(self) -> str | None:
        """The digest of the exact payload the printer adapter was handed."""
        return self.printed.raster_input_digest

    def as_dict(self) -> dict[str, Any]:
        """Return the outcome's wire form."""
        return {
            "operation": self.operation,
            "source": self.source.as_dict(),
            "raster_identity": self.raster_identity,
            "raster_input_digest": self.raster_input_digest,
            "decision": self.decision.as_dict(),
            "result": self.printed.as_dict(),
        }


@dataclass(frozen=True, slots=True)
class CalibrationPrint:
    """The standardized sheet that was printed, and what it was printed with.

    `dependencies` is the reason this is a type rather than a `PrintOutcome`:
    the measurements an operator is about to enter belong to the identities of
    *this* sheet, and handing them back together is what stops four numbers
    being recorded against a render that never happened.
    """

    outcome: PrintOutcome
    dependencies: CalibrationDependencies

    @property
    def sheet_raster_identity(self) -> str:
        """The raster identity the resulting record will name."""
        return self.outcome.raster_identity


async def async_print_calibration_label(
    hass: HomeAssistant,
    *,
    profile: CapabilityProfile,
    actor: Actor,
    device_id: str,
    density: str = "normal",
    firmware: str | None = None,
    as_of: datetime | None = None,
    locale: str = "en",
    time_zone: str = "UTC",
    fonts: FontLibrary | None = None,
) -> CalibrationPrint:
    """Put the standardized calibration label on paper for one printer.

    The one print a **provisional** profile can make, and the reason it can:
    a profile with declared-but-unmeasured geometry still knows where it
    believes it can put ink, and printing that belief is how anybody finds out
    whether it is right. It authorizes through `test_print` exactly like an
    administrator's own draft does -- both are unproven output an
    administrator asked for deliberately -- and like a draft it can never
    become a production print.

    `device_id` is required. A calibration that did not name the printer it
    measured would be a measurement of the model, which is the other proof.
    """
    actor.administrator()
    library = fonts or font_library_for(hass)
    layout = calibration_layout(profile, density=density)
    content = calibration_content(
        profile,
        as_of=as_of or dt_util.utcnow(),
        locale=locale,
        time_zone=time_zone,
    )
    source = LayoutSource.from_calibration(layout, profile_id=profile.id)

    try:
        outcome = await _async_judge_then_print(
            hass,
            operation=Operation.TEST_PRINT,
            source=source,
            content=content,
            profile=profile,
            density=density,
            device_id=device_id,
            fonts=library,
            provenance=_UNASSERTED,
            expected_raster_identity=None,
        )
    except (PrintRefused, PrintFailed) as err:
        raise CalibrationSheetNotPrinted(str(err)) from err

    return CalibrationPrint(
        outcome=outcome,
        dependencies=recorded_dependencies(
            outcome.printed.context,
            profile,
            library,
            device_id=device_id,
            firmware=firmware,
        ),
    )


async def async_print_evidence_label(
    hass: HomeAssistant,
    *,
    profile: CapabilityProfile,
    actor: Actor,
    device_id: str,
    density: str = "normal",
    as_of: datetime | None = None,
    locale: str = "en",
    time_zone: str = "UTC",
    fonts: FontLibrary | None = None,
) -> PrintOutcome:
    """Put the evidence label on paper, to be photographed and measured.

    It is how a profile's claims about readable text, scannable QR codes and
    thin rules meet paper, so like the calibration sheet it has to print on a
    profile that is still provisional -- and like it, it authorizes through
    `test_print` and can never be a production print. Nothing is held: what it
    proves is recorded by a person in a Release Evidence Record, not by this
    installation's calibration ledger.
    """
    actor.administrator()
    layout = evidence_layout(profile, density=density)
    content = calibration_content(
        profile,
        as_of=as_of or dt_util.utcnow(),
        locale=locale,
        time_zone=time_zone,
    )
    return await _async_judge_then_print(
        hass,
        operation=Operation.TEST_PRINT,
        source=LayoutSource.from_evidence(layout, profile_id=profile.id),
        content=content,
        profile=profile,
        density=density,
        device_id=device_id,
        fonts=fonts or font_library_for(hass),
        provenance=_UNASSERTED,
        expected_raster_identity=None,
    )


async def async_test_print(
    hass: HomeAssistant,
    *,
    source: LayoutSource,
    content: LabelContentSnapshot,
    profile: CapabilityProfile,
    actor: Actor,
    device_id: str | None = None,
    density: str = "normal",
    expected_raster_identity: str | None = None,
    fonts: FontLibrary | None = None,
) -> PrintOutcome:
    """Put an administrator's own layout on paper, to look at it.

    Asserts nothing about provenance, and that is what makes it the operation
    a draft and a provisional profile can both reach. It is still judged: a
    layout with a blocking diagnostic does not print because somebody called
    it a test.

    A stale draft is deliberately printable here. Somebody else publishing
    past it does not make the work in front of its owner unprintable, and
    seeing it on paper beside the revision that overtook it is exactly how
    they decide what to do about it.
    """
    actor.administrator()
    return await _async_judge_then_print(
        hass,
        operation=Operation.TEST_PRINT,
        source=source,
        content=content,
        profile=profile,
        density=density,
        device_id=device_id,
        fonts=fonts or font_library_for(hass),
        provenance=_UNASSERTED,
        expected_raster_identity=expected_raster_identity,
    )


async def async_print_record(
    hass: HomeAssistant,
    *,
    source: LayoutSource,
    content: LabelContentSnapshot,
    profile: CapabilityProfile,
    ledger: LocalCalibrationLedger,
    actor: Actor,
    device_id: str,
    expected_raster_identity: str,
    density: str = "normal",
    firmware: str | None = None,
    fonts: FontLibrary | None = None,
) -> PrintOutcome:
    """Put one real record on paper, from a published revision.

    Five things have to hold, and each is refused by its own name:

    - the layout is a **published revision** -- a draft is somebody's work in
      progress, and a label in a grow room outlives the session that printed
      it;
    - the content is an **actual record's** immutable snapshot, not a
      representative fixture and not a calibration sheet;
    - the caller presents the **raster identity it approved**, and it is still
      the identity this render produces;
    - the profile is **product-verified**; and
    - this installation's **local calibration** for this printer, stock and
      orientation is current.

    The calibration is resolved before anything is rendered, so its identity
    is *in* the Render Context rather than compared against it afterwards --
    which is what makes a raster cached under that context unable to outlive
    the measurement it was authorized by.
    """
    actor.authenticated()
    library = fonts or font_library_for(hass)
    status = await ledger.async_status(
        required=required_dependencies(
            profile, library, device_id=device_id, firmware=firmware
        )
    )
    return await _async_judge_then_print(
        hass,
        operation=Operation.SINGLE_PRINT,
        source=source,
        content=content,
        profile=profile,
        density=density,
        device_id=device_id,
        fonts=library,
        provenance=PrintProvenance(
            published_revision=source.published,
            actual_content=content.source == RECORD_SOURCE,
            # An identity the caller never presented is not a match: a
            # production print without an approved preview behind it is
            # exactly the thing this route exists to refuse.
            result_current=bool(expected_raster_identity),
        ),
        expected_raster_identity=expected_raster_identity,
        calibration=status,
    )


#: What a route that asserts no provenance passes. Spelled once, because three
#: separate `PrintProvenance(False, False, False)` literals would read as three
#: different decisions rather than as one rule.
_UNASSERTED = PrintProvenance(
    published_revision=False, actual_content=False, result_current=False
)


async def _async_judge_then_print(
    hass: HomeAssistant,
    *,
    operation: Operation,
    source: LayoutSource,
    content: LabelContentSnapshot,
    profile: CapabilityProfile,
    density: str,
    device_id: str | None,
    fonts: FontLibrary,
    provenance: PrintProvenance,
    expected_raster_identity: str | None,
    calibration: CalibrationStatus | None = None,
) -> PrintOutcome:
    """Render, judge, and only then commit -- in that order, always."""
    identity = calibration.identity if calibration else None
    stale_reasons = calibration.stale_reasons if calibration else ()

    judged = await async_render(
        hass,
        layout=source.layout,
        content=content,
        profile=profile,
        density=density,
        device_id=device_id,
        operation=PREVIEW,
        local_calibration=identity,
        calibration_stale_reasons=stale_reasons,
        fonts=fonts,
    )

    if (
        expected_raster_identity is not None
        and expected_raster_identity != judged.raster_identity
    ):
        raise PrintRefused(
            str(operation),
            (str(Blocker.RESULT_NOT_CURRENT),),
            "Something this label depends on has changed since it was "
            "approved. Preview it again before printing.",
        )

    decision = decide_print_request(
        judged.eligibility, operation, provenance=provenance
    )
    if not decision.allowed:
        raise PrintRefused(str(operation), decision.blocked_by, _explain(calibration))

    printed = await async_render(
        hass,
        layout=source.layout,
        content=content,
        profile=profile,
        density=density,
        device_id=device_id,
        operation=str(operation),
        local_calibration=identity,
        calibration_stale_reasons=stale_reasons,
        fonts=fonts,
    )

    if printed.raster is None:
        # The adapter turns a transport failure into a raster diagnostic, which
        # is right for a preview and wrong here: for a committed print "no
        # raster came back" means the printer did not take the label.
        reasons = "; ".join(
            item.message
            for item in printed.diagnostics
            if item.layer is Layer.RASTER and item.severity is Severity.ERROR
        )
        _LOGGER.error(
            "The %s of %s did not reach the printer: %s",
            operation,
            source.reference,
            reasons,
        )
        raise PrintFailed(reasons or "The printer did not accept the label.")

    if printed.raster_input_digest != judged.raster_input_digest:  # pragma: no cover
        # Unreachable without a defect: the raster inputs are a pure function
        # of four immutable things, none of which moved between these two
        # calls. It is checked anyway, and loudly, because the alternative is
        # returning success for a label nobody can prove was the approved one
        # -- and by this point it is already on paper.
        _LOGGER.error(
            "The %s of %s did not reproduce the approved raster inputs",
            operation,
            source.reference,
        )
        raise PrintRefused(
            str(operation),
            (str(Blocker.RESULT_NOT_CURRENT),),
            "A label was printed, but its raster inputs are not the ones that "
            "were approved. Do not treat it as the approved output.",
        )

    _LOGGER.info("Printed %s for %s", source.reference, content.subject)
    return PrintOutcome(
        operation=str(operation),
        source=source,
        judged=judged,
        printed=printed,
        decision=decision,
    )


def _explain(calibration: CalibrationStatus | None) -> str:
    """Say which dependency stale calibration blames, where one does."""
    if calibration is None or not calibration.stale_reasons:
        return ""
    return (
        "The local calibration no longer applies because "
        f"{', '.join(calibration.stale_reasons)} changed since it was measured."
    )
