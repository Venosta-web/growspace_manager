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


class Recovery(StrEnum):
    """The kind of correction that clears one diagnostic.

    It names a destination, not a repair: nothing here is applied for the
    user. A layout error routes to the element that carries it, a device
    error to profile selection or calibration rather than into the element
    controls, and a renderer or transport failure to retrying the same
    request. "Fix it for me" is deliberately absent.
    """

    #: Change this element's geometry or style.
    EDIT_ELEMENT = "edit_element"
    #: Change the record this label is about, or print a different one.
    EDIT_CONTENT = "edit_content"
    #: Choose a printer, stock or density this layout can reach.
    SELECT_PROFILE = "select_profile"
    #: Run the guided calibration flow for this printer and stock.
    CALIBRATE = "calibrate"
    #: Reload, restore or replace the template itself.
    RESTORE_TEMPLATE = "restore_template"
    #: Ask again; nothing about the layout has to change.
    RETRY = "retry"
    #: Nothing to correct.
    NONE = "none"


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
    #: Where a user goes to clear this. Left unset, the layer decides, so a
    #: diagnostic raised before this field existed still routes somewhere.
    recovery: Recovery | None = None

    @property
    def recovery_action(self) -> Recovery:
        """The correction kind this diagnostic routes to."""
        if self.recovery is not None:
            return self.recovery
        return DEFAULT_RECOVERY[self.layer]

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
            "recovery": str(self.recovery_action),
        }


#: Where each layer's diagnostics route when one does not say for itself.
DEFAULT_RECOVERY: Mapping[Layer, Recovery] = {
    Layer.DOCUMENT: Recovery.EDIT_ELEMENT,
    Layer.CONTENT: Recovery.EDIT_CONTENT,
    Layer.PROFILE_COMPILATION: Recovery.SELECT_PROFILE,
    Layer.RASTER: Recovery.RETRY,
    Layer.TRANSPORT: Recovery.RETRY,
}


def has_blocking(diagnostics: Iterable[Diagnostic]) -> bool:
    """Return whether any diagnostic blocks the operation it belongs to."""
    return any(item.severity is Severity.ERROR for item in diagnostics)
