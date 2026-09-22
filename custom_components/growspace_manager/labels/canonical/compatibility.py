"""The transient canonical inputs a Classic request compiles from.

A Classic `print_label` request names a legacy Label Size and five visibility
flags; it never names a layout. This module is the fixed answer to "which
layout, then": one versioned **compatibility layout** per legacy size and flag
combination, one **compatibility content snapshot** per request, and one
**compatibility profile** per legacy size. The Compatibility Adapter hands all
three to `compile_layout`, the same compiler every Label Template goes through,
so there is one compiler and one rasterizer and the fixed-coordinate renderer
is left with nothing to do.

All three are bounded operational artifacts, and each is shaped so it cannot
become anything else:

- The layout binds only the private `classic.*` namespace, which is absent
  from the binding catalogue. `validate_document` therefore refuses it, so it
  can never be saved, published, exported, imported or made a default -- and
  nothing that was not validated can reach Template print eligibility.
- Its elements carry the Classic styles below, which the document schema has
  no spelling for. They exist because Classic prints unwrapped, proportionally
  auto-sized text, stretched logos and module-sized QR codes, and the canonical
  styles deliberately do none of those things.
- The profile is provisional, names no printer and is absent from `PROFILES`,
  so it authorizes no production print and appears in no capability response.

The geometry is the Classic design's own: a 400x240 reference composition,
scaled independently per axis onto each stock with Python's `round`, exactly
as the fixed renderer scales it. The pixels are then re-expressed as the
millimetres the compiler turns back into those same pixels, so the compiled
plan is the Classic one element for element.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .catalogue import LABEL_SIZES, ElementKind, PrintContext
from .content import ContentAbsence, LabelContentSnapshot
from .diagnostics import Severity
from .document import (
    QUANTUM_MM,
    BindingSource,
    DividerStyle,
    Frame,
    LabelLayout,
    LayoutElement,
)
from .profiles import MM_PER_INCH, CalibratedLimits, CapabilityProfile, ProfileEvidence

#: Bumped whenever any compatibility layout below changes, which is also a
#: change to what every Classic request prints.
COMPATIBILITY_LAYOUT_VERSION = "growspace.classic-layout.v1"

#: The resolution the compatibility layouts are written against. Classic
#: paints eight dots per millimetre; the compiler speaks integer DPI, and 203
#: reaches every Classic pixel edge once the millimetres are chosen for it.
COMPATIBILITY_DPI = 203

#: The five visibility flags a Classic request may send, in the order the
#: Classic body text lists its lines.
FIELD_FLAGS: tuple[str, ...] = ("phenotype", "breeder", "lineage", "logo", "qr")

#: The body lines a flag can suppress, in the order they are printed.
DETAIL_LINES: tuple[str, ...] = ("phenotype", "breeder", "lineage")

#: What an absent or unrecognised Classic `label_size` has always meant.
#: Tightening that into an error is a compatibility decision, not a refactor.
DEFAULT_CLASSIC_SIZE = "50x30"

#: The raster each legacy size has always been painted on, in device pixels.
CLASSIC_CANVASES: Mapping[str, tuple[int, int]] = {
    "50x30": (400, 240),
    "40x30": (320, 240),
    "50x50": (400, 400),
    "50x80": (400, 640),
    "50x15": (400, 120),
}

#: The canvas the Classic composition is drawn against before it is scaled.
_REFERENCE = CLASSIC_CANVASES[DEFAULT_CLASSIC_SIZE]

#: The private binding namespace. None of these is in the binding catalogue,
#: which is what keeps a compatibility layout from ever validating.
TITLE = "classic.title"
DETAILS = "classic.details"
LOGO = "classic.logo"
QR = "classic.qr"
PRINTED_ON = "classic.printed_on"
DETAIL_BINDINGS: Mapping[str, str] = {line: f"classic.{line}" for line in DETAIL_LINES}
CLASSIC_BINDINGS = frozenset(
    {TITLE, DETAILS, LOGO, QR, PRINTED_ON, *DETAIL_BINDINGS.values()}
)

_TITLE_FONT = "growspace.sans.bold.v1"
_BODY_FONT = "growspace.sans.regular.v1"


# ---------------------------------------------------------------------------
# The Classic styles
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClassicTextStyle:
    """Unwrapped text shrunk proportionally until it fits its frame.

    `x_end_mm` is the right edge the Classic payload has always carried beside
    its fitting width. The renderer ignores it; it is kept so the payload is
    the Classic one byte for byte.
    """

    font: str
    font_size_mm: float
    x_end_mm: float
    uppercase: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the style's wire form."""
        return {
            "classic": "text",
            "font": self.font,
            "font_size_mm": self.font_size_mm,
            "x_end_mm": self.x_end_mm,
            "uppercase": self.uppercase,
        }


@dataclass(frozen=True, slots=True)
class ClassicLineStyle:
    """One unwrapped line drawn from its frame's top-left corner, never fitted."""

    font: str
    font_size_mm: float

    def as_dict(self) -> dict[str, Any]:
        """Return the style's wire form."""
        return {
            "classic": "line",
            "font": self.font,
            "font_size_mm": self.font_size_mm,
        }


@dataclass(frozen=True, slots=True)
class ClassicLogoStyle:
    """An image stretched to its frame, undithered."""

    def as_dict(self) -> dict[str, Any]:
        """Return the style's wire form."""
        return {"classic": "logo"}


@dataclass(frozen=True, slots=True)
class ClassicQrStyle:
    """A QR code sized by its module, anchored at its frame's corner.

    The extent falls where the encoded data puts it, which is why the frame
    runs to the edge of the label rather than claiming a box.
    """

    boxsize: int

    def as_dict(self) -> dict[str, Any]:
        """Return the style's wire form."""
        return {"classic": "qr", "boxsize": self.boxsize}


ClassicStyle = ClassicTextStyle | ClassicLineStyle | ClassicLogoStyle | ClassicQrStyle


# ---------------------------------------------------------------------------
# The content snapshot
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CompatibilityContentSnapshot(LabelContentSnapshot):
    """What one Classic request says, resolved once by the adapter.

    It answers the `classic.*` bindings and nothing else. `values` holds the
    request's already-normalized strings; which body lines print is the
    layout's choice, passed as the `lines` parameter of `classic.details`.
    """

    def supports(self, binding_id: str) -> bool:
        """Return whether this is one of the Classic bindings."""
        return binding_id in CLASSIC_BINDINGS

    def absence(self, binding_id: str) -> ContentAbsence | None:
        """Every Classic binding is optional: an absent one simply prints nothing."""
        if binding_id not in CLASSIC_BINDINGS:
            return None
        return ContentAbsence(
            code="content.missing_optional",
            severity=Severity.WARNING,
            parameters={"binding": binding_id},
        )

    def resolve(self, binding_id: str, parameters: Mapping[str, str]) -> str | None:
        """Return one Classic value; the body is the selected lines, joined.

        An empty body is still a body. Classic has always drawn its body text
        element with nothing in it when every line is suppressed or blank, and
        the empty string, unlike `None`, is placed.
        """
        if binding_id == DETAILS:
            selected = [line for line in parameters.get("lines", "").split(",") if line]
            return "\n".join(
                value
                for line in selected
                if (value := self.values.get(DETAIL_BINDINGS.get(line, "")))
            )
        return self.values.get(binding_id) or None


def compatibility_snapshot(
    *,
    context: PrintContext,
    subject: str,
    as_of: Any,
    values: Mapping[str, str | None],
) -> CompatibilityContentSnapshot:
    """Capture one Classic request's content, dropping anything absent."""
    return CompatibilityContentSnapshot(
        context=context,
        subject=subject,
        as_of=as_of,
        values={key: value for key, value in values.items() if value},
        source="classic",
    )


# ---------------------------------------------------------------------------
# The layouts
# ---------------------------------------------------------------------------


def classic_size(requested: object) -> str:
    """Resolve a Classic `label_size` to a legacy key, falling back to 50x30."""
    if isinstance(requested, str) and requested in CLASSIC_CANVASES:
        return requested
    return DEFAULT_CLASSIC_SIZE


def label_size_id(classic_key: str) -> str:
    """The canonical stock identity of one legacy size."""
    for size in LABEL_SIZES.values():
        if size.classic_key == classic_key:
            return size.id
    raise KeyError(f"No canonical Label Size spells {classic_key!r}")


def visible_fields(fields: Mapping[str, Any] | None) -> frozenset[str]:
    """The flags a Classic request leaves on. Absent means shown."""
    flags = fields or {}
    return frozenset(flag for flag in FIELD_FLAGS if flags.get(flag, True))


def layout_id(classic_key: str, visible: frozenset[str]) -> str:
    """The versioned identity of one compatibility layout."""
    shown = "+".join(flag for flag in FIELD_FLAGS if flag in visible) or "none"
    return f"{COMPATIBILITY_LAYOUT_VERSION}/{classic_key}/{shown}"


def millimetres(pixels: int) -> float:
    """The quantized millimetre edge the compiler turns back into `pixels`."""
    exact = Decimal(pixels) * Decimal(str(MM_PER_INCH)) / Decimal(COMPATIBILITY_DPI)
    return float(exact.quantize(QUANTUM_MM, rounding=ROUND_HALF_UP))


class _Scale:
    """The Classic stretch from the reference canvas onto one legacy stock."""

    def __init__(self, classic_key: str) -> None:
        self.width, self.height = CLASSIC_CANVASES[classic_key]
        self._x = self.width / _REFERENCE[0]
        self._y = self.height / _REFERENCE[1]

    def x(self, reference: int) -> int:
        """One horizontal reference pixel, rounded the way Classic rounds it."""
        return round(reference * self._x)

    def y(self, reference: int) -> int:
        """One vertical reference pixel, rounded the way Classic rounds it."""
        return round(reference * self._y)


def _frame(left: int, top: int, right: int, bottom: int) -> Frame:
    """A frame from pixel edges, in the millimetres that reproduce them."""
    x_mm, y_mm = millimetres(left), millimetres(top)
    return Frame(
        x_mm=x_mm,
        y_mm=y_mm,
        width_mm=round(millimetres(right) - x_mm, 2),
        height_mm=round(millimetres(bottom) - y_mm, 2),
    )


def compatibility_layout(classic_key: str, visible: frozenset[str]) -> LabelLayout:
    """The Classic composition for one legacy size and set of visible fields.

    Paint order is the Classic one: title, rule, body, logo, QR code, date.
    """
    scale = _Scale(classic_key)

    def text(
        element_id: str,
        binding: BindingSource,
        *,
        y: int,
        height: int,
        size: int,
        font: str,
        uppercase: bool = False,
    ) -> LayoutElement:
        left, top = scale.x(0), scale.y(y)
        return LayoutElement(
            id=element_id,
            kind=ElementKind.TEXT,
            frame=_frame(left, top, left + scale.x(250), top + scale.y(height)),
            rotation=0,
            style=ClassicTextStyle(
                font=font,
                font_size_mm=millimetres(size),
                x_end_mm=millimetres(scale.x(260)),
                uppercase=uppercase,
            ),
            content=binding,
        )

    def to_the_corner(
        element_id: str,
        kind: ElementKind,
        binding: str,
        style: ClassicLineStyle | ClassicQrStyle,
        *,
        x: int,
        y: int,
    ) -> LayoutElement:
        return LayoutElement(
            id=element_id,
            kind=kind,
            frame=_frame(scale.x(x), scale.y(y), scale.width, scale.height),
            rotation=0,
            style=style,
            content=BindingSource(binding, {}),
        )

    lines = ",".join(line for line in DETAIL_LINES if line in visible)
    elements: list[LayoutElement] = [
        text(
            "title",
            BindingSource(TITLE, {}),
            y=20,
            height=50,
            size=50,
            font=_TITLE_FONT,
            uppercase=True,
        ),
        LayoutElement(
            id="rule",
            kind=ElementKind.DIVIDER,
            # The compiled rule is inclusive of its last pixel, so the frame
            # ends one past the Classic rectangle's own end coordinates.
            frame=_frame(scale.x(0), scale.y(85), scale.x(260) + 1, scale.y(88) + 1),
            rotation=0,
            style=DividerStyle(),
        ),
        text(
            "details",
            BindingSource(DETAILS, {"lines": lines}),
            y=100,
            height=100,
            size=40,
            font=_BODY_FONT,
        ),
    ]
    if "logo" in visible:
        left, top = scale.x(290), scale.y(20)
        elements.append(
            LayoutElement(
                id="logo",
                kind=ElementKind.LOGO,
                frame=_frame(left, top, left + scale.x(100), top + scale.y(100)),
                rotation=0,
                style=ClassicLogoStyle(),
                content=BindingSource(LOGO, {}),
            )
        )
    if "qr" in visible:
        elements.append(
            to_the_corner(
                "qr", ElementKind.QR, QR, ClassicQrStyle(boxsize=3), x=290, y=130
            )
        )
    elements.append(
        to_the_corner(
            "printed_on",
            ElementKind.TEXT,
            PRINTED_ON,
            ClassicLineStyle(font=_BODY_FONT, font_size_mm=millimetres(6)),
            x=290,
            y=224,
        )
    )
    return LabelLayout(
        label_size_id=label_size_id(classic_key), elements=tuple(elements)
    )


# ---------------------------------------------------------------------------
# The profile
# ---------------------------------------------------------------------------

#: The Classic density table, as the legacy printer behaviour it has always
#: been. It is what `density` means on a Classic request; it is not a claim
#: about any printer, and the adapter checks the resolved value against the
#: selected printer's own range before anything is sent.
CLASSIC_DENSITY_LEVELS: Mapping[str, int] = {"low": 3, "normal": 5, "high": 8}

#: A compatibility profile is judged against nothing: no Classic output was
#: ever measured, and every number here is a zero rather than an invented
#: floor. The safety pass that reads limits is never run on this path.
_NO_LIMITS = CalibratedLimits(
    text_readable_floor_mm=0.0,
    text_comfort_threshold_mm=0.0,
    qr_minimum_dots_per_module=0,
    qr_minimum_quiet_zone_modules=0,
    qr_maximum_encoded_bytes=0,
    qr_error_correction_levels=(),
    image_minimum_effective_dpi=0.0,
    divider_minimum_thickness_mm=0.0,
    measured=False,
)


def compatibility_profile(classic_key: str) -> CapabilityProfile:
    """The transient profile one legacy size compiles against.

    Its Printable Area is the Classic raster itself, stated in the millimetres
    that compile to exactly that many pixels -- a hair over the stock on the
    wider sizes, because 203 dpi is a rounding of Classic's eight dots per
    millimetre. It names no printer and no device model, and it is
    provisional, so nothing compiled against it can authorize production.
    """
    width, height = CLASSIC_CANVASES[classic_key]
    return CapabilityProfile(
        id=f"growspace.profile.classic.{classic_key}.v1",
        printer_class="classic",
        label_size_id=label_size_id(classic_key),
        dpi=COMPATIBILITY_DPI,
        printhead_pixels=width,
        printable_origin_x_mm=0.0,
        printable_origin_y_mm=0.0,
        printable_width_mm=millimetres(width),
        printable_height_mm=millimetres(height),
        safe_area_inset_mm=0.0,
        density_levels=CLASSIC_DENSITY_LEVELS,
        evidence=ProfileEvidence.PROVISIONAL,
        limits=_NO_LIMITS,
    )
