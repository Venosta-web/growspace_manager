"""The [[Render Context]] and the [[Render Result]] one render produces.

A Render Context is the complete identity of one render: which layout, which
subject, which profile and calibration, which compiler, renderer, adapter,
fonts, QR model and safety policy, which catalogues and which instant. It
exists so that "is this preview still the truth?" is a comparison rather than
a guess -- and so that a font, profile or compiler update invalidates a cached
raster without anyone pretending the saved layout changed.

The cache identity is a digest of that whole context. Two requests sharing it
share their raster; anything else, however similar it looks, does not.

A Render Result is the authoritative raster plus everything that explains it:
what became of each element, what ink each one laid down, where that ink
overlaps, which limits it was judged against, every diagnostic with the kind
of correction that clears it, and one eligibility answer per operation.
Eligibility is decided here and read by the card -- it is never inferred from
a warning count on the other side of the wire.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from .canonicalization import digest
from .catalogue import (
    BINDING_CATALOGUE_VERSION,
    CAPABILITY_GENERATION,
    LABEL_SIZE_CATALOGUE_VERSION,
    STYLE_TOKEN_CATALOGUE_VERSION,
)
from .compiler import COMPILER_VERSION, ElementOutcome
from .diagnostics import Diagnostic
from .eligibility import Operation, OperationEligibility, decide_eligibility
from .fonts import TEXT_TOOLCHAIN_VERSION
from .ink import ElementInk
from .profiles import CapabilityProfile
from .qr import QR_MODEL_VERSION
from .safety import SAFETY_POLICY_VERSION, OverlapPair

#: Bumped when this module's own composition of a result changes.
RENDERER_VERSION = "growspace.label-renderer.v1"

#: Bumped when the printer adapter's payload changes shape, because that
#: changes the raster without changing anything upstream of it.
ADAPTER_VERSION = "growspace.niimbot-adapter.v1"


@dataclass(frozen=True, slots=True)
class RenderContext:
    """Every identity one raster depends on, and nothing else."""

    layout_digest: str
    label_size_id: str
    profile_id: str
    profile_evidence: str
    content_identity: str
    content_context: str
    content_source: str
    locale: str
    time_zone: str
    as_of: str
    density: str
    density_level: int | None
    operation: str
    #: The installation's own calibration record for this printer and stock.
    #: `None` is a state, not a gap: it refuses production printing by name.
    local_calibration: str | None = None
    #: Font file to the digest of the bytes this render measured.
    font_identity: Mapping[str, str] = field(default_factory=dict)
    compiler_version: str = COMPILER_VERSION
    renderer_version: str = RENDERER_VERSION
    adapter_version: str = ADAPTER_VERSION
    text_toolchain_version: str = TEXT_TOOLCHAIN_VERSION
    qr_model_version: str = QR_MODEL_VERSION
    safety_policy_version: str = SAFETY_POLICY_VERSION
    binding_catalogue_version: str = BINDING_CATALOGUE_VERSION
    style_token_catalogue_version: str = STYLE_TOKEN_CATALOGUE_VERSION
    label_size_catalogue_version: str = LABEL_SIZE_CATALOGUE_VERSION
    capability_generation: int = CAPABILITY_GENERATION

    def as_dict(self) -> dict[str, Any]:
        """Return the context's wire form, which is also what it hashes."""
        return {
            "layout_digest": self.layout_digest,
            "label_size_id": self.label_size_id,
            "profile_id": self.profile_id,
            "profile_evidence": self.profile_evidence,
            "local_calibration": self.local_calibration,
            "content_identity": self.content_identity,
            "content_context": self.content_context,
            "content_source": self.content_source,
            "locale": self.locale,
            "time_zone": self.time_zone,
            "as_of": self.as_of,
            "density": self.density,
            "density_level": self.density_level,
            "operation": self.operation,
            "font_identity": dict(self.font_identity),
            "compiler_version": self.compiler_version,
            "renderer_version": self.renderer_version,
            "adapter_version": self.adapter_version,
            "text_toolchain_version": self.text_toolchain_version,
            "qr_model_version": self.qr_model_version,
            "safety_policy_version": self.safety_policy_version,
            "binding_catalogue_version": self.binding_catalogue_version,
            "style_token_catalogue_version": self.style_token_catalogue_version,
            "label_size_catalogue_version": self.label_size_catalogue_version,
            "capability_generation": self.capability_generation,
        }

    @property
    def cache_identity(self) -> str:
        """The digest two requests must share to share a raster.

        Density is in it even though it changes a printer command rather than
        the bitmap: the old context still cannot authorize the new request,
        and a cache that said otherwise would be the place that forgot.
        """
        return digest(self.as_dict())

    @property
    def raster_identity(self) -> str:
        """The digest two requests must share to produce the same bitmap.

        The cache identity without the two fields that decide what a raster is
        *allowed to do* rather than what it looks like:

        - `operation`, because a preview, a test print, a production print and
          a retry of any of them draw the same thing and are permitted
          different things; and
        - `local_calibration`, because a measurement of where this printer
          lands ink changes nothing about the bitmap sent to it.

        That is what makes "the operator is printing what they approved" a
        comparison rather than an assurance. An operator who previews, is told
        the printer needs calibrating, calibrates it and prints is printing
        the raster they looked at -- and the print is still judged afresh
        against the calibration that now exists, because eligibility is a
        separate question asked at the moment of the print.

        It is not a substitute for the cache identity. Two results sharing a
        raster identity can have different eligibility, and a client that
        cached on this would serve a preview's raster for a print request and
        lose the refusal that came with it.
        """
        return digest(
            {
                key: value
                for key, value in self.as_dict().items()
                if key not in _AUTHORIZATION_ONLY
            }
        )


@dataclass(frozen=True, slots=True)
class Raster:
    """The authoritative monochrome bitmap, as the renderer produced it."""

    content_type: str
    width: int
    height: int
    #: The PNG, as the `data:` URI the renderer returns it in.
    data_uri: str
    byte_length: int
    #: Whether the decoded image really carries at most two colours. Asked
    #: rather than assumed, because "monochrome" is a claim the preview makes.
    monochrome: bool

    def as_dict(self) -> dict[str, Any]:
        """Return the raster's wire form."""
        return {
            "content_type": self.content_type,
            "width": self.width,
            "height": self.height,
            "image": self.data_uri,
            "byte_length": self.byte_length,
            "monochrome": self.monochrome,
        }


#: The Render Context fields that decide what a raster may do rather than
#: what it looks like. Excluded from the raster identity, and deliberately
#: kept in the cache identity.
_AUTHORIZATION_ONLY = frozenset({"operation", "local_calibration"})

#: A result whose raster matches the request that asked for it.
CURRENT = "current"
#: A result that could not be rastered. Its diagnostics say why.
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RenderResult:
    """One render: the raster, what it did, and what it may authorize."""

    context: RenderContext
    status: str
    raster: Raster | None
    outcomes: tuple[ElementOutcome, ...]
    diagnostics: tuple[Diagnostic, ...]
    #: The profile this render was against, regions and calibrated limits
    #: included, so a client can explain a refusal without a second request.
    profile: CapabilityProfile | None = None
    #: What each element really inked.
    ink: tuple[ElementInk, ...] = ()
    #: Every pair of elements whose ink coincides, graded.
    overlaps: tuple[OverlapPair, ...] = ()
    #: One answer per operation, with the reasons for each refusal.
    eligibility: Mapping[str, OperationEligibility] = field(default_factory=dict)
    #: The digest of the exact inputs the printer adapter was handed. Two
    #: results sharing it were drawn from byte-identical instructions; a
    #: result whose raster never came back has none.
    raster_input_digest: str | None = None

    @property
    def cache_identity(self) -> str:
        """The identity this result may be reused under."""
        return self.context.cache_identity

    @property
    def raster_identity(self) -> str:
        """The identity every operation drawing this bitmap shares."""
        return self.context.raster_identity

    @property
    def printable(self) -> bool:
        """Whether this exact result may put one real record on paper.

        The same question as `eligibility["single_print"]`, kept as a property
        so there is one answer rather than two that can disagree.
        """
        decision = self.eligibility.get(str(Operation.SINGLE_PRINT))
        return bool(decision and decision.allowed)

    def as_dict(self) -> dict[str, Any]:
        """Return the complete wire form of this result."""
        return {
            "status": self.status,
            "printable": self.printable,
            "cache_identity": self.cache_identity,
            "raster_identity": self.raster_identity,
            "raster_input_digest": self.raster_input_digest,
            "render_context": self.context.as_dict(),
            "profile": self.profile.as_dict() if self.profile else None,
            "raster": self.raster.as_dict() if self.raster else None,
            "elements": [outcome.as_dict() for outcome in self.outcomes],
            "ink": [item.as_dict() for item in self.ink],
            "overlaps": [pair.as_dict() for pair in self.overlaps],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
            "eligibility": {
                name: decision.as_dict() for name, decision in self.eligibility.items()
            },
        }


def eligibility_for(
    diagnostics: Sequence[Diagnostic],
    raster: Raster | None,
    *,
    profile: CapabilityProfile,
    local_calibration: str | None = None,
    calibration_stale_reasons: Sequence[str] = (),
    printer_covered: bool = True,
) -> Mapping[str, OperationEligibility]:
    """Decide every operation this result could be asked to authorize."""
    return decide_eligibility(
        diagnostics,
        has_raster=raster is not None,
        profile=profile,
        local_calibration=local_calibration,
        calibration_stale_reasons=calibration_stale_reasons,
        printer_covered=printer_covered,
    )


def merged_diagnostics(*groups: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Concatenate diagnostics in layer order, preserving each group's order."""
    merged: list[Diagnostic] = []
    for group in groups:
        merged.extend(group)
    return tuple(merged)
