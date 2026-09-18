"""The [[Render Context]] and the [[Render Result]] one render produces.

A Render Context is the complete identity of one render: which layout, which
subject, which profile, which compiler, renderer and adapter, which catalogues
and which instant. It exists so that "is this preview still the truth?" is a
comparison rather than a guess -- and so that a font, profile or compiler
update invalidates a cached raster without anyone pretending the saved layout
changed.

The cache identity is a digest of that whole context. Two requests sharing it
share their raster; anything else, however similar it looks, does not.

A Render Result is the authoritative raster plus the outcomes and diagnostics
that explain it. Print eligibility is decided here and read by the card -- it
is never inferred from a warning count on the other side of the wire.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .canonicalization import digest
from .catalogue import (
    BINDING_CATALOGUE_VERSION,
    CAPABILITY_GENERATION,
    LABEL_SIZE_CATALOGUE_VERSION,
    STYLE_TOKEN_CATALOGUE_VERSION,
)
from .compiler import COMPILER_VERSION, ElementOutcome
from .diagnostics import Diagnostic, has_blocking

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
    compiler_version: str = COMPILER_VERSION
    renderer_version: str = RENDERER_VERSION
    adapter_version: str = ADAPTER_VERSION
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
            "content_identity": self.content_identity,
            "content_context": self.content_context,
            "content_source": self.content_source,
            "locale": self.locale,
            "time_zone": self.time_zone,
            "as_of": self.as_of,
            "density": self.density,
            "density_level": self.density_level,
            "operation": self.operation,
            "compiler_version": self.compiler_version,
            "renderer_version": self.renderer_version,
            "adapter_version": self.adapter_version,
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


#: A result whose raster matches the request that asked for it.
CURRENT = "current"
#: A result that could not be rastered. Its diagnostics say why.
FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RenderResult:
    """One render: the raster, what happened to each element, and whether it may print."""

    context: RenderContext
    status: str
    raster: Raster | None
    outcomes: tuple[ElementOutcome, ...]
    diagnostics: tuple[Diagnostic, ...]
    #: Whether this exact result may reach paper. Decided here.
    printable: bool

    @property
    def cache_identity(self) -> str:
        """The identity this result may be reused under."""
        return self.context.cache_identity

    def as_dict(self) -> dict[str, Any]:
        """Return the complete wire form of this result."""
        return {
            "status": self.status,
            "printable": self.printable,
            "cache_identity": self.cache_identity,
            "render_context": self.context.as_dict(),
            "raster": self.raster.as_dict() if self.raster else None,
            "elements": [outcome.as_dict() for outcome in self.outcomes],
            "diagnostics": [item.as_dict() for item in self.diagnostics],
        }


def decide_printable(
    diagnostics: Sequence[Diagnostic],
    raster: Raster | None,
    *,
    profile_authorizes_production: bool,
) -> bool:
    """Decide whether one result may reach paper.

    Three independent reasons it may not, and each is reported as itself: a
    blocking diagnostic, no raster at all, or a profile whose physical
    evidence has not been recorded. A provisional profile renders an exact
    bitmap and still cannot authorize a print, because an exact bitmap is a
    claim about the driver and not about the paper.
    """
    if raster is None or has_blocking(diagnostics):
        return False
    return profile_authorizes_production


def merged_diagnostics(*groups: Sequence[Diagnostic]) -> tuple[Diagnostic, ...]:
    """Concatenate diagnostics in layer order, preserving each group's order."""
    merged: list[Diagnostic] = []
    for group in groups:
        merged.extend(group)
    return tuple(merged)
