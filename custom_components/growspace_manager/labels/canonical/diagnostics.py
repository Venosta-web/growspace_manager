"""Structured diagnostics: every outcome the label pipeline reports.

A diagnostic is machine-readable first. It carries a stable code, a severity,
the validation layer that produced it, a JSON pointer into the document, the
stable element ID it concerns and named parameters -- so a card can select the
element, focus a control and re-render without parsing prose. The message is
there for a log and a fallback, never as the only content.

The layers are the ones the cross-repository specification fixes, and they are
ordered: a document error is attributable without a printer, a content error
without a raster, and a transport error says nothing about whether the raster
was right. Collapsing them is how "printer offline" ends up standing for a
missing font.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class Severity(StrEnum):
    """What a diagnostic does to the operation that produced it."""

    #: Blocks the operation named by the diagnostic's layer and metadata.
    ERROR = "error"
    #: A printable outcome that stays visible and auditable.
    WARNING = "warning"
    #: Neither; recorded because it explains a decision the renderer made.
    INFO = "info"


class Layer(StrEnum):
    """Which validation layer produced a diagnostic."""

    #: Schema, geometry, identity and required roles. Needs no printer.
    DOCUMENT = "document"
    #: Binding resolution against one subject. Needs no printer.
    CONTENT = "content"
    #: Stock, safe area, pixel geometry and compiler support.
    PROFILE_COMPILATION = "profile_compilation"
    #: The pinned renderer: fonts, assets, images, the raster itself.
    RASTER = "raster"
    #: Device availability and protocol. Says nothing about the raster.
    TRANSPORT = "transport"


@dataclass(frozen=True, slots=True)
class Diagnostic:
    """One attributable outcome of one validation layer."""

    code: str
    severity: Severity
    layer: Layer
    message: str
    #: JSON pointer into the Label Layout document, where one applies.
    path: str = ""
    #: The stable element ID this concerns, where one applies.
    element_id: str | None = None
    #: Named values the message is built from, for a client that localizes it.
    parameters: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the wire form of this diagnostic."""
        return {
            "code": self.code,
            "severity": str(self.severity),
            "layer": str(self.layer),
            "message": self.message,
            "path": self.path,
            "element_id": self.element_id,
            "parameters": dict(self.parameters),
        }


def has_blocking(diagnostics: Iterable[Diagnostic]) -> bool:
    """Return whether any diagnostic blocks the operation it belongs to."""
    return any(item.severity is Severity.ERROR for item in diagnostics)
