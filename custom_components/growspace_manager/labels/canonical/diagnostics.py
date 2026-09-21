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

DIAGNOSTIC_VERSION = "growspace.label-diagnostics.v1"


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


@dataclass(frozen=True, slots=True)
class DiagnosticSpec:
    """What one diagnostic code promises a client that localizes it.

    The code is the stable key; the layer and severities say where it can
    appear; the parameters are the only named values copy may interpolate. A
    translation that names a parameter the producer never sends renders a
    hole, and one the producer renames silently goes stale -- which is why
    the catalogue is published to the card as a contract fixture and held to
    every diagnostic the pipeline actually emits.
    """

    layer: Layer
    severities: frozenset[Severity]
    parameters: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        """Return the catalogue entry's wire form."""
        return {
            "layer": str(self.layer),
            "severities": sorted(str(severity) for severity in self.severities),
            "parameters": list(self.parameters),
        }


#: Every diagnostic code the label pipeline can produce. Adding a code without
#: declaring it here fails the suite; so does emitting one with a parameter,
#: layer or severity it does not declare.
DIAGNOSTIC_CATALOGUE: Mapping[str, DiagnosticSpec] = {
    "content.ambiguous_source": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("variants",)
    ),
    "content.asset_not_permitted": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("kind",)
    ),
    "content.binding_kind_mismatch": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("binding", "kind", "kinds")
    ),
    "content.invalid_asset": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "content.invalid_literal": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "content.invalid_parameter": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("allowed", "parameter", "value")
    ),
    "content.logo_unusable": DiagnosticSpec(
        Layer.CONTENT, frozenset({Severity.WARNING}), ("binding", "reason")
    ),
    "content.missing_optional": DiagnosticSpec(
        Layer.CONTENT, frozenset({Severity.WARNING}), ("binding",)
    ),
    "content.missing_required": DiagnosticSpec(
        Layer.CONTENT, frozenset({Severity.ERROR}), ("binding", "subject")
    ),
    "content.not_an_object": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "content.parameters_not_an_object": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "content.qr_target_unavailable": DiagnosticSpec(
        Layer.CONTENT, frozenset({Severity.ERROR}), ("binding", "target")
    ),
    "content.source_unresolved": DiagnosticSpec(
        Layer.CONTENT, frozenset({Severity.WARNING}), ("binding", "strain")
    ),
    "content.stage_date_in_future": DiagnosticSpec(
        Layer.CONTENT,
        frozenset({Severity.ERROR}),
        ("as_of", "stage", "started_on", "subject"),
    ),
    "content.stage_date_missing": DiagnosticSpec(
        Layer.CONTENT, frozenset({Severity.WARNING}), ("binding", "stage")
    ),
    "content.unknown_binding": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("binding",)
    ),
    "content.unknown_parameter": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("binding", "parameter")
    ),
    "content.unsupported_context": DiagnosticSpec(
        Layer.CONTENT, frozenset({Severity.WARNING}), ("binding", "context")
    ),
    "document.elements_not_an_array": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "document.missing_required_strain_name": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("binding",)
    ),
    "document.not_an_object": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "document.unknown_label_size": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("label_size_id",)
    ),
    "document.unknown_schema": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("actual", "expected")
    ),
    "document.unsupported_version": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("actual", "expected")
    ),
    "element.divider_has_content": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "element.duplicate_id": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("id",)
    ),
    "element.invalid_id": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "element.not_an_object": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "element.unknown_kind": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("kind",)
    ),
    "element.unsupported_rotation": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("allowed", "rotation")
    ),
    "frame.negative_origin": DiagnosticSpec(
        Layer.DOCUMENT,
        frozenset({Severity.ERROR}),
        ("height_mm", "width_mm", "x_mm", "y_mm"),
    ),
    "frame.non_positive_extent": DiagnosticSpec(
        Layer.DOCUMENT,
        frozenset({Severity.ERROR}),
        ("height_mm", "width_mm", "x_mm", "y_mm"),
    ),
    "frame.not_an_object": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "frame.outside_stock": DiagnosticSpec(
        Layer.DOCUMENT,
        frozenset({Severity.ERROR}),
        ("height_mm", "stock_height_mm", "stock_width_mm", "width_mm", "x_mm", "y_mm"),
    ),
    "geometry.finer_than_quantum": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("quantum_mm", "value")
    ),
    "geometry.not_a_number": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("value",)
    ),
    "geometry.not_finite": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("value",)
    ),
    "profile.divider_below_reproducible_thickness": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.WARNING}),
        ("minimum_thickness_mm", "thickness_mm"),
    ),
    "profile.image_below_effective_resolution": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.WARNING}),
        ("effective_dpi", "minimum_effective_dpi"),
    ),
    "profile.ink_outside_printable_area": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("ink_bounds", "printable_area"),
    ),
    "profile.ink_outside_safe_area": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.WARNING}),
        ("ink_bounds", "safe_area", "safe_area_inset_mm"),
    ),
    "profile.outside_printable_area": DiagnosticSpec(
        Layer.PROFILE_COMPILATION, frozenset({Severity.ERROR}), ("pixel_frame",)
    ),
    "profile.qr_below_module_floor": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("dots_per_module", "minimum_dots_per_module"),
    ),
    "profile.qr_error_correction_unsupported": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("error_correction", "supported"),
    ),
    "profile.qr_quiet_zone_too_small": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("minimum_quiet_zone_modules", "quiet_zone_modules"),
    ),
    "profile.qr_target_too_long": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("encoded_bytes", "maximum_encoded_bytes"),
    ),
    "profile.raster_wider_than_printhead": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("printhead_pixels", "raster_width"),
    ),
    "profile.rotation_unsupported": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("rotation", "supported"),
    ),
    "profile.stock_mismatch": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("layout_label_size_id", "profile", "profile_label_size_id"),
    ),
    "profile.text_below_comfort_threshold": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.WARNING}),
        ("comfort_threshold_mm", "resolved_font_size_mm"),
    ),
    "profile.text_below_readable_floor": DiagnosticSpec(
        Layer.PROFILE_COMPILATION,
        frozenset({Severity.ERROR}),
        ("readable_floor_mm", "resolved_font_size_mm"),
    ),
    "profile.unsupported_density": DiagnosticSpec(
        Layer.PROFILE_COMPILATION, frozenset({Severity.ERROR}), ("available", "density")
    ),
    "raster.image_leaves_no_ink": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.WARNING}), ()
    ),
    "raster.image_not_inspected": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.WARNING}), ("remote",)
    ),
    "raster.image_undecodable": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.WARNING}), ("remote",)
    ),
    "raster.ink_overlap": DiagnosticSpec(
        Layer.RASTER,
        frozenset({Severity.WARNING}),
        ("first_element_id", "region", "required_content", "second_element_id"),
    ),
    "raster.missing": DiagnosticSpec(Layer.RASTER, frozenset({Severity.ERROR}), ()),
    "raster.missing_glyph": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("characters", "font_file")
    ),
    "raster.qr_does_not_fit": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("box_px", "side_modules")
    ),
    "raster.qr_not_encodable": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("encoded_bytes",)
    ),
    "raster.qr_quiet_zone_violated": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("qr_element_id", "region")
    ),
    "raster.render_failed": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("error",)
    ),
    "raster.required_content_occluded": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("required_binding",)
    ),
    "raster.text_does_not_fit": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("minimum_font_size_px", "overflow")
    ),
    "raster.text_truncated": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.WARNING}), ("lines", "overflow")
    ),
    "raster.text_unmeasured": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.WARNING}), ("font_file",)
    ),
    "raster.unexpected_format": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.WARNING}), ("format",)
    ),
    "raster.unreadable": DiagnosticSpec(
        Layer.RASTER, frozenset({Severity.ERROR}), ("error",)
    ),
    "schema.foreign_field": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("field", "reason")
    ),
    "schema.missing_field": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("field",)
    ),
    "schema.unknown_field": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("field",)
    ),
    "style.invalid_value": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("allowed", "value")
    ),
    "style.minimum_above_requested": DiagnosticSpec(
        Layer.DOCUMENT,
        frozenset({Severity.ERROR}),
        ("font_size_mm", "minimum_font_size_mm"),
    ),
    "style.non_positive_font_size": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "style.not_an_object": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ()
    ),
    "style.unknown_token": DiagnosticSpec(
        Layer.DOCUMENT, frozenset({Severity.ERROR}), ("token",)
    ),
}
