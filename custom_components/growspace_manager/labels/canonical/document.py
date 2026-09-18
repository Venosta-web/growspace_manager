"""The `growspace.label-layout` version 1 document, and its validator.

A Label Layout is absolute millimetre geometry on a named stock, and nothing
else. It holds no CSS, no browser pixels, no `imagespec`, no DPI, no density,
no device, no resolved plant data and no rendered image: every one of those is
chosen at render time, which is what lets one saved revision print on a
different printer without being rewritten.

The schema is **closed**. An unknown field is an error rather than something to
drop, because dropping it is how a v2 document quietly becomes a lossy v1 one.
Validation never repairs: it does not clamp a coordinate, round a
finer-than-quantum number, reorder elements, substitute a token or omit a
failing element. It reports, and something upstream decides.

Only this layer runs here -- schema, geometry, identity, paint order, rotation
and required roles -- because it needs no printer and no record, and an error
it can attribute is an error nobody has to reproduce on hardware.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from .canonicalization import digest
from .catalogue import (
    BINDING_CATALOGUE,
    FONT_TOKENS,
    LABEL_SIZES,
    LINE_SPACING_TOKENS,
    MONOCHROME_TOKENS,
    REQUIRED_BINDING,
    ElementKind,
    ErrorCorrection,
    LabelSize,
)
from .diagnostics import Diagnostic, Layer, Severity

SCHEMA = "growspace.label-layout"
VERSION = 1

#: Every millimetre value in a document is a multiple of this. A finer one is
#: rejected rather than rounded, so publication cannot silently move a frame.
QUANTUM_MM = Decimal("0.01")

#: Clockwise degrees an element may be rotated by.
ROTATIONS = (0, 90, 180, 270)

#: A divider is a rectangular mark; 180 and 270 describe the same ink as 0
#: and 90, so admitting them would let two documents mean one label.
DIVIDER_ROTATIONS = (0, 90)

HORIZONTAL_ALIGNMENTS = ("left", "center", "right")
VERTICAL_ALIGNMENTS = ("top", "center", "bottom")
OVERFLOW_POLICIES = ("clip", "ellipsis", "shrink", "shrink_ellipsis")

_DOCUMENT_FIELDS = frozenset({"schema", "version", "label_size_id", "elements"})
_ELEMENT_COMMON_FIELDS = frozenset({"id", "kind", "frame", "rotation"})
_FRAME_FIELDS = ("x_mm", "y_mm", "width_mm", "height_mm")

_TEXT_STYLE_FIELDS = frozenset(
    {
        "font",
        "font_size_mm",
        "horizontal_align",
        "vertical_align",
        "line_spacing",
        "overflow",
        "minimum_font_size_mm",
        "maximum_lines",
    }
)
_LOGO_STYLE_FIELDS = frozenset({"monochrome", "fit"})
_QR_STYLE_FIELDS = frozenset({"error_correction", "quiet_zone_modules"})
_DIVIDER_STYLE_FIELDS = frozenset({"fill"})

#: Fields whose presence means a caller is trying to save a browser's or a
#: printer's vocabulary into the canonical document. Every unknown field is
#: rejected anyway; these are named so the diagnostic can say *why*.
FOREIGN_FIELDS: Mapping[str, str] = {
    "z_index": "paint order is the element array's order",
    "style_css": "a layout holds no CSS",
    "css": "a layout holds no CSS",
    "payload": "`imagespec` is a private printer-adapter format",
    "imagespec": "`imagespec` is a private printer-adapter format",
    "type": "element variants are spelled `kind`",
    "boxsize": "QR module size is resolved by the compiler",
    "dpi": "resolution belongs to the Capability Profile",
    "density": "density belongs to the print request",
    "x": "geometry is millimetres, spelled `x_mm`",
    "y": "geometry is millimetres, spelled `y_mm`",
    "width": "geometry is millimetres, spelled `width_mm`",
    "height": "geometry is millimetres, spelled `height_mm`",
    "visible": "a layout has no visibility flag",
    "name": "a display name belongs to the lifecycle envelope",
}


@dataclass(frozen=True, slots=True)
class Frame:
    """An element's axis-aligned physical rectangle, in millimetres.

    The frame is the post-rotation occupied and clipped rectangle: rotating an
    element never moves it, which is what makes rotation independent of which
    drag handle the editor happened to offer.
    """

    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float

    @property
    def right_mm(self) -> float:
        """The frame's right edge."""
        return self.x_mm + self.width_mm

    @property
    def bottom_mm(self) -> float:
        """The frame's bottom edge."""
        return self.y_mm + self.height_mm

    def as_dict(self) -> dict[str, float]:
        """Return the frame's document form."""
        return {
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "width_mm": self.width_mm,
            "height_mm": self.height_mm,
        }


@dataclass(frozen=True, slots=True)
class BindingSource:
    """A symbolic request for content, resolved once per subject."""

    binding: str
    parameters: Mapping[str, str]

    def as_dict(self) -> dict[str, Any]:
        """Return the source's document form."""
        return {"binding": self.binding, "parameters": dict(self.parameters)}


@dataclass(frozen=True, slots=True)
class LiteralSource:
    """Static text, where the catalogue permits it."""

    literal: str

    def as_dict(self) -> dict[str, Any]:
        """Return the source's document form."""
        return {"literal": self.literal}


@dataclass(frozen=True, slots=True)
class AssetSource:
    """An integration-owned asset identity. Logos only."""

    asset_id: str

    def as_dict(self) -> dict[str, Any]:
        """Return the source's document form."""
        return {"asset_id": self.asset_id}


ContentSource = BindingSource | LiteralSource | AssetSource


@dataclass(frozen=True, slots=True)
class TextStyle:
    """Printer-safe text controls. No face, no weight, no colour, no markup."""

    font: str
    font_size_mm: float
    horizontal_align: str
    vertical_align: str
    line_spacing: str
    overflow: str
    minimum_font_size_mm: float
    maximum_lines: int

    def as_dict(self) -> dict[str, Any]:
        """Return the style's document form."""
        return {
            "font": self.font,
            "font_size_mm": self.font_size_mm,
            "horizontal_align": self.horizontal_align,
            "vertical_align": self.vertical_align,
            "line_spacing": self.line_spacing,
            "overflow": self.overflow,
            "minimum_font_size_mm": self.minimum_font_size_mm,
            "maximum_lines": self.maximum_lines,
        }


@dataclass(frozen=True, slots=True)
class LogoStyle:
    """How an image becomes ink. `contain` is v1's only fit, stated anyway."""

    monochrome: str
    fit: str = "contain"

    def as_dict(self) -> dict[str, Any]:
        """Return the style's document form."""
        return {"monochrome": self.monochrome, "fit": self.fit}


@dataclass(frozen=True, slots=True)
class QrStyle:
    """Error correction and quiet zone. Module size is the compiler's."""

    error_correction: str
    quiet_zone_modules: int

    def as_dict(self) -> dict[str, Any]:
        """Return the style's document form."""
        return {
            "error_correction": self.error_correction,
            "quiet_zone_modules": self.quiet_zone_modules,
        }


@dataclass(frozen=True, slots=True)
class DividerStyle:
    """Black fill, stated so a future version cannot reinterpret absence."""

    fill: str = "black"

    def as_dict(self) -> dict[str, Any]:
        """Return the style's document form."""
        return {"fill": self.fill}


@dataclass(frozen=True, slots=True)
class LayoutElement:
    """One placed element: stable identity, frame, rotation, content, style."""

    id: str
    kind: ElementKind
    frame: Frame
    rotation: int
    style: TextStyle | LogoStyle | QrStyle | DividerStyle
    content: ContentSource | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return the element's document form."""
        value: dict[str, Any] = {
            "id": self.id,
            "kind": str(self.kind),
            "frame": self.frame.as_dict(),
            "rotation": self.rotation,
        }
        if self.content is not None:
            value["content"] = self.content.as_dict()
        value["style"] = self.style.as_dict()
        return value


@dataclass(frozen=True, slots=True)
class LabelLayout:
    """One complete printable design, as saved.

    `elements` is back-to-front paint order. There is no separate z-index,
    because two orderings would let one document describe two labels.
    """

    label_size_id: str
    elements: tuple[LayoutElement, ...]
    schema: str = SCHEMA
    version: int = VERSION

    def as_dict(self) -> dict[str, Any]:
        """Return the normalized document, ready to canonicalize."""
        return {
            "schema": self.schema,
            "version": self.version,
            "label_size_id": self.label_size_id,
            "elements": [element.as_dict() for element in self.elements],
        }

    @property
    def digest(self) -> str:
        """The normalized layout digest every Render Context carries."""
        return digest(self.as_dict())


@dataclass(frozen=True, slots=True)
class DocumentValidation:
    """What document validation produced: a layout, diagnostics, or both."""

    layout: LabelLayout | None
    diagnostics: tuple[Diagnostic, ...]


def validate_document(value: object) -> DocumentValidation:
    """Validate one candidate Label Layout against the closed v1 schema."""
    return _Validator().run(value)


class _Validator:
    """Collects every attributable document diagnostic in one pass.

    One pass rather than fail-fast because an editor showing the first of six
    problems makes six round trips out of one correction.
    """

    def __init__(self) -> None:
        """Start with an empty diagnostic list."""
        self._diagnostics: list[Diagnostic] = []

    def run(self, value: object) -> DocumentValidation:
        """Validate `value`, returning a layout only when it is intact."""
        if not isinstance(value, Mapping):
            self._error(
                "document.not_an_object",
                "A Label Layout is a JSON object.",
                path="",
            )
            return DocumentValidation(None, tuple(self._diagnostics))

        self._check_fields(value, _DOCUMENT_FIELDS, "")
        self._check_constant(value, "schema", SCHEMA)
        self._check_constant(value, "version", VERSION)
        size = self._label_size(value)
        elements = self._elements(value, size)

        if size is None or elements is None:
            return DocumentValidation(None, tuple(self._diagnostics))

        self._check_required_role(elements)
        layout = LabelLayout(label_size_id=size.id, elements=elements)
        return DocumentValidation(layout, tuple(self._diagnostics))

    # -- document level ----------------------------------------------------

    def _label_size(self, value: Mapping[str, Any]) -> LabelSize | None:
        """Resolve the referenced Label Size, or report it."""
        size_id = value.get("label_size_id")
        if not isinstance(size_id, str) or size_id not in LABEL_SIZES:
            self._error(
                "document.unknown_label_size",
                f"Label Size {size_id!r} is not in the catalogue.",
                path="/label_size_id",
                parameters={"label_size_id": size_id},
            )
            return None
        return LABEL_SIZES[size_id]

    def _elements(
        self, value: Mapping[str, Any], size: LabelSize | None
    ) -> tuple[LayoutElement, ...] | None:
        """Validate the ordered element array."""
        raw = value.get("elements")
        if not isinstance(raw, Sequence) or isinstance(raw, (str, bytes)):
            self._error(
                "document.elements_not_an_array",
                "`elements` is an ordered array of Label Elements.",
                path="/elements",
            )
            return None

        elements: list[LayoutElement] = []
        seen: set[str] = set()
        intact = True
        for index, item in enumerate(raw):
            element = self._element(item, f"/elements/{index}", size, seen)
            if element is None:
                intact = False
                continue
            elements.append(element)
        return tuple(elements) if intact else None

    def _check_required_role(self, elements: tuple[LayoutElement, ...]) -> None:
        """Every publishable layout carries a text element bound to the strain."""
        if any(
            element.kind is ElementKind.TEXT
            and isinstance(element.content, BindingSource)
            and element.content.binding == REQUIRED_BINDING
            for element in elements
        ):
            return
        self._error(
            "document.missing_required_strain_name",
            "A Label Layout needs one text element bound to `strain.name`.",
            path="/elements",
            parameters={"binding": REQUIRED_BINDING},
        )

    # -- element level -----------------------------------------------------

    def _element(
        self, value: object, path: str, size: LabelSize | None, seen: set[str]
    ) -> LayoutElement | None:
        """Validate one element of any kind."""
        if not isinstance(value, Mapping):
            self._error("element.not_an_object", "An element is a JSON object.", path)
            return None

        kind = self._kind(value, path)
        if kind is None:
            return None

        allowed = _ELEMENT_COMMON_FIELDS | {"style"}
        if kind is not ElementKind.DIVIDER:
            allowed = allowed | {"content"}
        self._check_fields(value, allowed, path)

        element_id = self._element_id(value, path, seen)
        frame = self._frame(value.get("frame"), f"{path}/frame", size, element_id)
        rotation = self._rotation(value, path, kind, element_id)
        content = self._content(value, path, kind, element_id)
        style = self._style(value.get("style"), f"{path}/style", kind, element_id)

        if element_id is None or frame is None or rotation is None or style is None:
            return None
        if kind is not ElementKind.DIVIDER and content is None:
            return None

        return LayoutElement(
            id=element_id,
            kind=kind,
            frame=frame,
            rotation=rotation,
            style=style,
            content=content,
        )

    def _kind(self, value: Mapping[str, Any], path: str) -> ElementKind | None:
        """Resolve the element variant, never coercing an unknown one."""
        kind = value.get("kind")
        if isinstance(kind, str):
            try:
                return ElementKind(kind)
            except ValueError:
                pass
        self._error(
            "element.unknown_kind",
            f"Element kind {kind!r} is not one of the four v1 variants.",
            path=f"{path}/kind",
            parameters={"kind": kind},
        )
        return None

    def _element_id(
        self, value: Mapping[str, Any], path: str, seen: set[str]
    ) -> str | None:
        """Validate the element's opaque, layout-unique identity."""
        element_id = value.get("id")
        if not isinstance(element_id, str) or not element_id:
            self._error(
                "element.invalid_id",
                "An element needs an opaque, non-empty `id`.",
                path=f"{path}/id",
            )
            return None
        if element_id in seen:
            self._error(
                "element.duplicate_id",
                f"Element ID {element_id!r} appears more than once.",
                path=f"{path}/id",
                element_id=element_id,
                parameters={"id": element_id},
            )
            return None
        seen.add(element_id)
        return element_id

    def _rotation(
        self,
        value: Mapping[str, Any],
        path: str,
        kind: ElementKind,
        element_id: str | None,
    ) -> int | None:
        """Validate clockwise rotation, narrowed per kind."""
        allowed = DIVIDER_ROTATIONS if kind is ElementKind.DIVIDER else ROTATIONS
        rotation = value.get("rotation")
        if isinstance(rotation, int) and not isinstance(rotation, bool):
            if rotation in allowed:
                return rotation
        self._error(
            "element.unsupported_rotation",
            f"Rotation {rotation!r} is not one of {allowed} for a {kind} element.",
            path=f"{path}/rotation",
            element_id=element_id,
            parameters={"rotation": rotation, "allowed": list(allowed)},
        )
        return None

    # -- geometry ----------------------------------------------------------

    def _frame(
        self,
        value: object,
        path: str,
        size: LabelSize | None,
        element_id: str | None,
    ) -> Frame | None:
        """Validate one Element Frame against the quantum and the stock."""
        if not isinstance(value, Mapping):
            self._error(
                "frame.not_an_object",
                "A frame is an object of four millimetre values.",
                path,
                element_id,
            )
            return None
        self._check_fields(value, frozenset(_FRAME_FIELDS), path, element_id)

        values: dict[str, float] = {}
        for field_name in _FRAME_FIELDS:
            measurement = self._millimetres(
                value.get(field_name), f"{path}/{field_name}", element_id
            )
            if measurement is None:
                return None
            values[field_name] = measurement

        frame = Frame(**values)
        if frame.width_mm <= 0 or frame.height_mm <= 0:
            self._error(
                "frame.non_positive_extent",
                "A frame's width and height are positive millimetre extents.",
                path,
                element_id,
                parameters=frame.as_dict(),
            )
            return None
        if frame.x_mm < 0 or frame.y_mm < 0:
            self._error(
                "frame.negative_origin",
                "A frame's origin is relative to the stock's top-left corner.",
                path,
                element_id,
                parameters=frame.as_dict(),
            )
            return None
        if size is not None and (
            frame.right_mm > size.width_mm or frame.bottom_mm > size.height_mm
        ):
            self._error(
                "frame.outside_stock",
                (
                    f"The frame reaches {frame.right_mm}x{frame.bottom_mm} mm, "
                    f"outside the {size.width_mm}x{size.height_mm} mm stock."
                ),
                path,
                element_id,
                parameters={
                    **frame.as_dict(),
                    "stock_width_mm": size.width_mm,
                    "stock_height_mm": size.height_mm,
                },
            )
            return None
        return frame

    def _millimetres(
        self, value: object, path: str, element_id: str | None
    ) -> float | None:
        """Validate one finite millimetre value quantized to 0.01 mm."""
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            self._error(
                "geometry.not_a_number",
                "A millimetre value is a finite JSON number.",
                path,
                element_id,
                parameters={"value": value},
            )
            return None
        quantum: Decimal | None = None
        try:
            quantum = Decimal(str(value))
        except InvalidOperation:
            quantum = None
        if quantum is None or not quantum.is_finite():
            self._error(
                "geometry.not_finite",
                "A millimetre value is a finite JSON number.",
                path,
                element_id,
                parameters={"value": value},
            )
            return None
        if quantum != quantum.quantize(QUANTUM_MM):
            self._error(
                "geometry.finer_than_quantum",
                f"{value} mm is finer than the 0.01 mm coordinate quantum.",
                path,
                element_id,
                parameters={"value": value, "quantum_mm": float(QUANTUM_MM)},
            )
            return None
        return float(quantum)

    # -- content -----------------------------------------------------------

    def _content(
        self,
        value: Mapping[str, Any],
        path: str,
        kind: ElementKind,
        element_id: str | None,
    ) -> ContentSource | None:
        """Validate the element's single content source."""
        if kind is ElementKind.DIVIDER:
            if "content" in value:
                self._error(
                    "element.divider_has_content",
                    "A divider is a mark, not a container for content.",
                    path=f"{path}/content",
                    element_id=element_id,
                )
            return None

        raw = value.get("content")
        source_path = f"{path}/content"
        if not isinstance(raw, Mapping):
            self._error(
                "content.not_an_object",
                "An element's `content` is a single source object.",
                source_path,
                element_id,
            )
            return None

        variants = [name for name in ("binding", "literal", "asset_id") if name in raw]
        if len(variants) != 1:
            self._error(
                "content.ambiguous_source",
                (
                    "Content is exactly one of `binding`, `literal` or "
                    f"`asset_id`; got {variants or 'none'}."
                ),
                source_path,
                element_id,
                parameters={"variants": variants},
            )
            return None

        if variants[0] == "literal":
            return self._literal(raw, source_path, element_id)
        if variants[0] == "asset_id":
            return self._asset(raw, source_path, kind, element_id)
        return self._binding(raw, source_path, kind, element_id)

    def _literal(
        self, raw: Mapping[str, Any], path: str, element_id: str | None
    ) -> LiteralSource | None:
        """Validate a static string source."""
        self._check_fields(raw, frozenset({"literal"}), path, element_id)
        literal = raw.get("literal")
        if not isinstance(literal, str) or not literal.strip():
            self._error(
                "content.invalid_literal",
                "A literal source is a non-empty string.",
                path,
                element_id,
            )
            return None
        return LiteralSource(literal)

    def _asset(
        self,
        raw: Mapping[str, Any],
        path: str,
        kind: ElementKind,
        element_id: str | None,
    ) -> AssetSource | None:
        """Validate an integration-owned asset reference."""
        self._check_fields(raw, frozenset({"asset_id"}), path, element_id)
        if kind is not ElementKind.LOGO:
            self._error(
                "content.asset_not_permitted",
                f"An asset source is only allowed on a logo, not on a {kind}.",
                path,
                element_id,
                parameters={"kind": str(kind)},
            )
            return None
        asset_id = raw.get("asset_id")
        if not isinstance(asset_id, str) or not asset_id:
            self._error(
                "content.invalid_asset",
                "An asset source is a non-empty opaque identity.",
                path,
                element_id,
            )
            return None
        return AssetSource(asset_id)

    def _binding(
        self,
        raw: Mapping[str, Any],
        path: str,
        kind: ElementKind,
        element_id: str | None,
    ) -> BindingSource | None:
        """Validate a catalogue binding and its closed parameter object."""
        self._check_fields(raw, frozenset({"binding", "parameters"}), path, element_id)
        binding_id = raw.get("binding")
        definition = (
            BINDING_CATALOGUE.get(binding_id) if isinstance(binding_id, str) else None
        )
        if definition is None:
            self._error(
                "content.unknown_binding",
                f"Binding {binding_id!r} is not in the v1 catalogue.",
                path,
                element_id,
                parameters={"binding": binding_id},
            )
            return None
        if kind not in definition.kinds:
            self._error(
                "content.binding_kind_mismatch",
                f"Binding {definition.id} does not apply to a {kind} element.",
                path,
                element_id,
                parameters={
                    "binding": definition.id,
                    "kind": str(kind),
                    "kinds": [str(item) for item in definition.kinds],
                },
            )
            return None

        parameters = raw.get("parameters")
        if not isinstance(parameters, Mapping):
            self._error(
                "content.parameters_not_an_object",
                "`parameters` is a closed object, `{}` where there are none.",
                f"{path}/parameters",
                element_id,
            )
            return None

        resolved: dict[str, str] = {}
        for name, choice in parameters.items():
            allowed = definition.parameters.get(name)
            if allowed is None:
                self._error(
                    "content.unknown_parameter",
                    f"Binding {definition.id} takes no parameter {name!r}.",
                    f"{path}/parameters/{name}",
                    element_id,
                    parameters={"binding": definition.id, "parameter": name},
                )
                return None
            if choice not in allowed:
                self._error(
                    "content.invalid_parameter",
                    f"{name}={choice!r} is not one of {list(allowed)}.",
                    f"{path}/parameters/{name}",
                    element_id,
                    parameters={
                        "parameter": name,
                        "value": choice,
                        "allowed": list(allowed),
                    },
                )
                return None
            resolved[name] = str(choice)

        for name, allowed in definition.parameters.items():
            resolved.setdefault(name, allowed[0])
        return BindingSource(definition.id, resolved)

    # -- style -------------------------------------------------------------

    def _style(
        self, value: object, path: str, kind: ElementKind, element_id: str | None
    ) -> TextStyle | LogoStyle | QrStyle | DividerStyle | None:
        """Validate the kind's closed style object."""
        if not isinstance(value, Mapping):
            self._error(
                "style.not_an_object",
                "An element's `style` is an object.",
                path,
                element_id,
            )
            return None
        if kind is ElementKind.TEXT:
            return self._text_style(value, path, element_id)
        if kind is ElementKind.LOGO:
            return self._logo_style(value, path, element_id)
        if kind is ElementKind.QR:
            return self._qr_style(value, path, element_id)
        return self._divider_style(value, path, element_id)

    def _text_style(
        self, value: Mapping[str, Any], path: str, element_id: str | None
    ) -> TextStyle | None:
        """Validate the constrained text style."""
        self._check_fields(value, _TEXT_STYLE_FIELDS, path, element_id)
        font = self._token(value.get("font"), FONT_TOKENS, f"{path}/font", element_id)
        spacing = self._token(
            value.get("line_spacing"),
            LINE_SPACING_TOKENS,
            f"{path}/line_spacing",
            element_id,
        )
        size = self._millimetres(
            value.get("font_size_mm"), f"{path}/font_size_mm", element_id
        )
        minimum = self._millimetres(
            value.get("minimum_font_size_mm"),
            f"{path}/minimum_font_size_mm",
            element_id,
        )
        horizontal = self._choice(
            value.get("horizontal_align"),
            HORIZONTAL_ALIGNMENTS,
            f"{path}/horizontal_align",
            element_id,
        )
        vertical = self._choice(
            value.get("vertical_align"),
            VERTICAL_ALIGNMENTS,
            f"{path}/vertical_align",
            element_id,
        )
        overflow = self._choice(
            value.get("overflow"), OVERFLOW_POLICIES, f"{path}/overflow", element_id
        )
        maximum_lines = self._positive_integer(
            value.get("maximum_lines"), f"{path}/maximum_lines", element_id
        )

        if (
            font is None
            or spacing is None
            or horizontal is None
            or vertical is None
            or overflow is None
            or maximum_lines is None
            or size is None
            or minimum is None
        ):
            return None
        if size <= 0 or minimum <= 0:
            self._error(
                "style.non_positive_font_size",
                "Font sizes are positive millimetre values.",
                path,
                element_id,
            )
            return None
        if minimum > size:
            self._error(
                "style.minimum_above_requested",
                (
                    f"The minimum font size {minimum} mm is larger than the "
                    f"requested {size} mm."
                ),
                path,
                element_id,
                parameters={"minimum_font_size_mm": minimum, "font_size_mm": size},
            )
            return None
        return TextStyle(
            font=str(font),
            font_size_mm=size,
            horizontal_align=str(horizontal),
            vertical_align=str(vertical),
            line_spacing=str(spacing),
            overflow=str(overflow),
            minimum_font_size_mm=minimum,
            maximum_lines=maximum_lines,
        )

    def _logo_style(
        self, value: Mapping[str, Any], path: str, element_id: str | None
    ) -> LogoStyle | None:
        """Validate the logo style. `contain` is the only v1 fit."""
        self._check_fields(value, _LOGO_STYLE_FIELDS, path, element_id)
        monochrome = self._token(
            value.get("monochrome"), MONOCHROME_TOKENS, f"{path}/monochrome", element_id
        )
        fit = self._choice(value.get("fit"), ("contain",), f"{path}/fit", element_id)
        if monochrome is None or fit is None:
            return None
        return LogoStyle(monochrome=str(monochrome), fit=str(fit))

    def _qr_style(
        self, value: Mapping[str, Any], path: str, element_id: str | None
    ) -> QrStyle | None:
        """Validate the QR style."""
        self._check_fields(value, _QR_STYLE_FIELDS, path, element_id)
        correction = self._choice(
            value.get("error_correction"),
            tuple(str(level) for level in ErrorCorrection),
            f"{path}/error_correction",
            element_id,
        )
        quiet_zone = self._positive_integer(
            value.get("quiet_zone_modules"), f"{path}/quiet_zone_modules", element_id
        )
        if correction is None or quiet_zone is None:
            return None
        return QrStyle(error_correction=str(correction), quiet_zone_modules=quiet_zone)

    def _divider_style(
        self, value: Mapping[str, Any], path: str, element_id: str | None
    ) -> DividerStyle | None:
        """Validate the divider style."""
        self._check_fields(value, _DIVIDER_STYLE_FIELDS, path, element_id)
        fill = self._choice(value.get("fill"), ("black",), f"{path}/fill", element_id)
        if fill is None:
            return None
        return DividerStyle(fill=str(fill))

    # -- shared checks -----------------------------------------------------

    def _check_fields(
        self,
        value: Mapping[str, Any],
        allowed: frozenset[str],
        path: str,
        element_id: str | None = None,
    ) -> None:
        """Reject unknown and missing fields of a closed object."""
        for name in value:
            if name in allowed:
                continue
            reason = FOREIGN_FIELDS.get(str(name))
            if reason is not None:
                self._error(
                    "schema.foreign_field",
                    f"`{name}` does not belong in a Label Layout: {reason}.",
                    f"{path}/{name}",
                    element_id,
                    parameters={"field": name, "reason": reason},
                )
                continue
            self._error(
                "schema.unknown_field",
                f"`{name}` is not a field of this v1 object.",
                f"{path}/{name}",
                element_id,
                parameters={"field": name},
            )
        for name in sorted(allowed - set(value)):
            self._error(
                "schema.missing_field",
                f"`{name}` is required.",
                f"{path}/{name}",
                element_id,
                parameters={"field": name},
            )

    def _check_constant(
        self, value: Mapping[str, Any], name: str, expected: object
    ) -> None:
        """Check one of the two document constants."""
        actual = value.get(name)
        if actual == expected and type(actual) is type(expected):
            return
        self._error(
            "document.unsupported_version"
            if name == "version"
            else "document.unknown_schema",
            f"`{name}` is {actual!r}; this backend reads {expected!r}.",
            path=f"/{name}",
            parameters={"expected": expected, "actual": actual},
        )

    def _token(
        self,
        value: object,
        catalogue: Mapping[str, Any],
        path: str,
        element_id: str | None,
    ) -> str | None:
        """Resolve a Style Token, never substituting a similar one."""
        if isinstance(value, str) and value in catalogue:
            return value
        self._error(
            "style.unknown_token",
            f"Style Token {value!r} is not in the catalogue.",
            path,
            element_id,
            parameters={"token": value},
        )
        return None

    def _choice(
        self,
        value: object,
        allowed: tuple[str, ...],
        path: str,
        element_id: str | None,
    ) -> str | None:
        """Check one closed enumeration."""
        if isinstance(value, str) and value in allowed:
            return value
        self._error(
            "style.invalid_value",
            f"{value!r} is not one of {list(allowed)}.",
            path,
            element_id,
            parameters={"value": value, "allowed": list(allowed)},
        )
        return None

    def _positive_integer(
        self, value: object, path: str, element_id: str | None
    ) -> int | None:
        """Check a positive whole number."""
        if isinstance(value, int) and not isinstance(value, bool) and value >= 1:
            return value
        self._error(
            "style.invalid_value",
            f"{value!r} is not a positive whole number.",
            path,
            element_id,
            parameters={"value": value},
        )
        return None

    def _error(
        self,
        code: str,
        message: str,
        path: str = "",
        element_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
    ) -> None:
        """Record one blocking document diagnostic."""
        self._diagnostics.append(
            Diagnostic(
                code=code,
                severity=Severity.ERROR,
                layer=Layer.DOCUMENT,
                message=message,
                path=path,
                element_id=element_id,
                parameters=parameters or {},
            )
        )
