"""Millimetres to device pixels, against one [[Capability Profile]].

The compiler is the only authoritative converter. It takes a validated Label
Layout, an immutable [[Label Content Snapshot]] and a profile, and produces a
[[Label Render Plan]] a printer adapter can realise, plus one outcome per
stable element ID and the diagnostics of the two layers it owns: content
resolution and profile compilation.

It converts **edges, not extents**:

    left   = round_half_up(x_mm * dpi / 25.4)
    right  = round_half_up((x_mm + width_mm) * dpi / 25.4)

so two frames that share a millimetre edge share a pixel edge. Rounding widths
independently is how adjacent elements acquire a one-pixel gap at one
resolution and a one-pixel overlap at another.

It never repairs. Nothing here clamps a coordinate, moves a frame, shrinks an
element, substitutes a token or drops a failing element to make a raster come
out; each of those produces a diagnostic and leaves the geometry alone.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from ..model import (
    Canvas,
    Divider,
    FittedText,
    LabelElement,
    LabelRenderPlan,
    Logo,
    QrCode,
)
from .catalogue import (
    FONT_TOKENS,
    LINE_SPACING_TOKENS,
    MONOCHROME_TOKENS,
    MissingPolicy,
)
from .content import ContentAbsence, LabelContentSnapshot, missing_policy
from .diagnostics import Diagnostic, Layer, Severity
from .document import (
    AssetSource,
    BindingSource,
    DividerStyle,
    Frame,
    LabelLayout,
    LayoutElement,
    LiteralSource,
    LogoStyle,
    QrStyle,
    TextStyle,
)
from .profiles import MM_PER_INCH, CapabilityProfile

#: Bumped when the arithmetic, the fitting search or the element mapping
#: changes. A Render Context carries it so a cached raster from an older
#: compiler stops matching even though the saved layout did not move.
COMPILER_VERSION = "growspace.label-compiler.v1"

#: Error-correction names to the single letters the renderer speaks.
_ERROR_CORRECTION = {"low": "l", "medium": "m", "quartile": "q", "high": "h"}

#: Overflow policies to the renderer's bounded fitting modes. `clip` has no
#: mode of its own: it is ellipsis with nothing to append, which truncates at
#: glyph boundaries rather than mid-stroke. That difference is real, so it is
#: reported as an outcome rather than hidden.
_OVERFLOW = {
    "clip": ("ellipsis", ""),
    "ellipsis": ("ellipsis", "…"),
    "shrink": ("shrink", "…"),
    "shrink_ellipsis": ("shrink_ellipsis", "…"),
}

_DECIMAL_MM_PER_INCH = Decimal(str(MM_PER_INCH))


@dataclass(frozen=True, slots=True)
class PixelFrame:
    """One element's compiled extent, in device pixels on the raster."""

    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        """Pixel width, as the difference of two converted edges."""
        return self.right - self.left

    @property
    def height(self) -> int:
        """Pixel height, as the difference of two converted edges."""
        return self.bottom - self.top

    def as_dict(self) -> dict[str, int]:
        """Return the frame's wire form."""
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True, slots=True)
class ElementOutcome:
    """What became of one stable element ID on this render.

    `status` is the compiler's verdict, not the renderer's: `placed` means the
    element reached the render plan, not that its ink survived fitting. What
    the raster did with it is the renderer's to report, and what it cannot
    report yet is named in the render result rather than guessed at here.
    """

    element_id: str
    kind: str
    status: str
    pixel_frame: PixelFrame | None = None
    binding: str | None = None
    notes: Mapping[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        """Return the outcome's wire form."""
        return {
            "element_id": self.element_id,
            "kind": self.kind,
            "status": self.status,
            "binding": self.binding,
            "pixel_frame": self.pixel_frame.as_dict() if self.pixel_frame else None,
            "notes": dict(self.notes),
        }


#: An element that reached the plan.
PLACED = "placed"
#: An optional binding with nothing to say for this subject. No ink, frame kept.
OMITTED_MISSING_CONTENT = "omitted_missing_content"
#: A binding this subject's context does not have at all -- a plant line on a
#: strain label. Distinct from missing content, because the correction is a
#: different one: this template is being printed from somewhere it was not
#: designed for, not this record is incomplete.
OMITTED_UNSUPPORTED_CONTEXT = "omitted_unsupported_context"
#: An element the compiler refused. Its diagnostic says why.
BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class CompiledLabel:
    """A render plan, one outcome per element, and how it was arrived at.

    Its diagnostics open with the snapshot's own record-level ones, so a
    record that cannot print says so before any element does.
    """

    plan: LabelRenderPlan
    outcomes: tuple[ElementOutcome, ...]
    diagnostics: tuple[Diagnostic, ...]


def compile_layout(
    layout: LabelLayout,
    snapshot: LabelContentSnapshot,
    profile: CapabilityProfile,
    *,
    density: str = "normal",
) -> CompiledLabel:
    """Compile one validated layout for one subject onto one profile."""
    return _Compiler(layout, snapshot, profile, density).run()


def to_pixels(millimetres: float, dpi: int) -> int:
    """Convert one millimetre edge to its device pixel, rounding half up."""
    exact = Decimal(str(millimetres)) * Decimal(dpi) / _DECIMAL_MM_PER_INCH
    return int(exact.quantize(Decimal(1), rounding=ROUND_HALF_UP))


class _Compiler:
    """One compilation, so the diagnostics of one render stay together."""

    def __init__(
        self,
        layout: LabelLayout,
        snapshot: LabelContentSnapshot,
        profile: CapabilityProfile,
        density: str,
    ) -> None:
        """Prepare the origin offsets and the canvas this render lands on."""
        self._layout = layout
        self._snapshot = snapshot
        self._profile = profile
        self._density = density
        self._diagnostics: list[Diagnostic] = []
        self._origin_x = to_pixels(profile.printable_origin_x_mm, profile.dpi)
        self._origin_y = to_pixels(profile.printable_origin_y_mm, profile.dpi)
        self._canvas = Canvas(
            width=to_pixels(
                profile.printable_origin_x_mm + profile.printable_width_mm, profile.dpi
            )
            - self._origin_x,
            height=to_pixels(
                profile.printable_origin_y_mm + profile.printable_height_mm, profile.dpi
            )
            - self._origin_y,
        )

    def run(self) -> CompiledLabel:
        """Compile every element in paint order."""
        self._check_profile()
        elements: list[LabelElement] = []
        outcomes: list[ElementOutcome] = []
        for element in self._layout.elements:
            placed, outcome = self._element(element)
            outcomes.append(outcome)
            if placed is not None:
                elements.append(placed)

        plan = LabelRenderPlan(
            canvas=self._canvas,
            elements=tuple(elements),
            density=self._density,
            density_level=self._profile.density_level(self._density),
        )
        return CompiledLabel(
            plan,
            tuple(outcomes),
            (*self._snapshot.diagnostics, *self._diagnostics),
        )

    # -- profile -----------------------------------------------------------

    def _check_profile(self) -> None:
        """Refuse a profile that cannot carry this layout's stock or raster."""
        if self._profile.label_size_id != self._layout.label_size_id:
            self._add(
                "profile.stock_mismatch",
                Severity.ERROR,
                (
                    f"Profile {self._profile.id} prints "
                    f"{self._profile.label_size_id}, not "
                    f"{self._layout.label_size_id}."
                ),
                parameters={
                    "profile": self._profile.id,
                    "profile_label_size_id": self._profile.label_size_id,
                    "layout_label_size_id": self._layout.label_size_id,
                },
            )
        if self._canvas.width > self._profile.printhead_pixels:
            self._add(
                "profile.raster_wider_than_printhead",
                Severity.ERROR,
                (
                    f"A {self._canvas.width}px raster is wider than the "
                    f"{self._profile.printhead_pixels}px printhead."
                ),
                parameters={
                    "raster_width": self._canvas.width,
                    "printhead_pixels": self._profile.printhead_pixels,
                },
            )
        if self._profile.density_level(self._density) is None:
            self._add(
                "profile.unsupported_density",
                Severity.ERROR,
                f"Profile {self._profile.id} has no {self._density!r} density.",
                parameters={
                    "density": self._density,
                    "available": sorted(self._profile.density_levels),
                },
            )

    # -- elements ----------------------------------------------------------

    def _element(
        self, element: LayoutElement
    ) -> tuple[LabelElement | None, ElementOutcome]:
        """Compile one element, or say why it did not reach the plan."""
        frame = self._pixel_frame(element.frame)
        binding = (
            element.content.binding
            if isinstance(element.content, BindingSource)
            else None
        )

        if element.rotation != 0:
            # The renderer expresses element rotation through a rotating group
            # whose anchoring needs golden renders this compiler version has
            # not earned. Refusing by name beats emitting untested geometry.
            return None, self._blocked(
                element,
                frame,
                binding,
                "compiler.rotation_unsupported",
                (
                    f"Compiler {COMPILER_VERSION} places unrotated elements "
                    f"only; element {element.id} is rotated {element.rotation}."
                ),
                {"rotation": element.rotation},
            )

        if not self._inside_printable_area(frame):
            return None, self._blocked(
                element,
                frame,
                binding,
                "profile.outside_printable_area",
                (
                    f"Element {element.id} compiles to {frame.as_dict()}, "
                    f"outside the {self._canvas.width}x{self._canvas.height}px "
                    "Printable Area."
                ),
                {"pixel_frame": frame.as_dict()},
            )

        style = element.style
        if isinstance(style, DividerStyle):
            return self._divider(style, frame), ElementOutcome(
                element_id=element.id,
                kind=str(element.kind),
                status=PLACED,
                pixel_frame=frame,
            )

        value = self._content(element, binding)
        if value is None:
            status = self._missing_status(element, binding)
            return None, ElementOutcome(
                element_id=element.id,
                kind=str(element.kind),
                status=status,
                pixel_frame=frame,
                binding=binding,
            )

        if isinstance(style, TextStyle):
            placed: LabelElement = self._text(style, frame, value)
        elif isinstance(style, QrStyle):
            placed = self._qr(style, frame, value)
        else:
            placed = self._logo(style, frame, value)
        return placed, ElementOutcome(
            element_id=element.id,
            kind=str(element.kind),
            status=PLACED,
            pixel_frame=frame,
            binding=binding,
            notes=self._notes(style, frame),
        )

    def _blocked(
        self,
        element: LayoutElement,
        frame: PixelFrame,
        binding: str | None,
        code: str,
        message: str,
        parameters: Mapping[str, Any],
    ) -> ElementOutcome:
        """Record a compilation refusal and its outcome."""
        self._add(
            code,
            Severity.ERROR,
            message,
            element_id=element.id,
            parameters=parameters,
        )
        return ElementOutcome(
            element_id=element.id,
            kind=str(element.kind),
            status=BLOCKED,
            pixel_frame=frame,
            binding=binding,
        )

    def _pixel_frame(self, frame: Frame) -> PixelFrame:
        """Convert one Element Frame's four edges into the raster's pixels."""
        dpi = self._profile.dpi
        return PixelFrame(
            left=to_pixels(frame.x_mm, dpi) - self._origin_x,
            top=to_pixels(frame.y_mm, dpi) - self._origin_y,
            right=to_pixels(frame.right_mm, dpi) - self._origin_x,
            bottom=to_pixels(frame.bottom_mm, dpi) - self._origin_y,
        )

    def _inside_printable_area(self, frame: PixelFrame) -> bool:
        """Whether a compiled frame lies wholly on the raster."""
        return (
            frame.left >= 0
            and frame.top >= 0
            and frame.right <= self._canvas.width
            and frame.bottom <= self._canvas.height
        )

    # -- content -----------------------------------------------------------

    def _content(self, element: LayoutElement, binding: str | None) -> str | None:
        """Resolve one element's content source against the snapshot.

        An empty resolved value is absent, whichever variant produced it. The
        validator already refuses a blank literal and a blank asset identity,
        but a compiler that trusted that would report an element as `placed`
        while painting nothing -- and an outcome that does not match the ink
        is worse than no outcome.
        """
        source = element.content
        if isinstance(source, LiteralSource):
            return source.literal or None
        if isinstance(source, AssetSource):
            return source.asset_id or None
        if not isinstance(source, BindingSource) or binding is None:
            return None
        if not self._snapshot.supports(binding):
            return None
        return self._snapshot.resolve(binding, source.parameters)

    def _missing_status(self, element: LayoutElement, binding: str | None) -> str:
        """Say why one element painted nothing, and what that does.

        Four different silences, and none of them may read as another: a
        literal or asset the validator admitted but that resolves to nothing,
        a binding this context does not have, a resolution that recorded why
        it found nothing, and a value the subject simply does not carry. Only
        the last falls back to the catalogue's own missing policy.
        """
        if binding is None:
            return BLOCKED
        if not self._snapshot.supports(binding):
            self._add(
                "content.unsupported_context",
                Severity.WARNING,
                (
                    f"Binding {binding} is not available when printing a "
                    f"{self._snapshot.context}, so its frame stays empty."
                ),
                element_id=element.id,
                parameters={
                    "binding": binding,
                    "context": str(self._snapshot.context),
                },
                layer=Layer.CONTENT,
            )
            return OMITTED_UNSUPPORTED_CONTEXT

        absence = self._snapshot.absence(binding)
        if absence is not None:
            return self._absent(element, binding, absence)

        policy = missing_policy(binding)
        severity = (
            Severity.WARNING
            if policy is MissingPolicy.WARN_AND_OMIT
            else Severity.ERROR
        )
        return self._absent(
            element,
            binding,
            ContentAbsence(
                code=(
                    "content.missing_optional"
                    if severity is Severity.WARNING
                    else "content.missing_required"
                ),
                severity=severity,
                parameters={"binding": binding},
            ),
        )

    def _absent(
        self, element: LayoutElement, binding: str, absence: ContentAbsence
    ) -> str:
        """Report one recorded absence against the element that asked for it."""
        self._add(
            absence.code,
            absence.severity,
            f"{binding} has no value for {self._snapshot.subject}.",
            element_id=element.id,
            parameters=dict(absence.parameters),
            layer=Layer.CONTENT,
        )
        return (
            OMITTED_MISSING_CONTENT if absence.severity is Severity.WARNING else BLOCKED
        )

    # -- element variants --------------------------------------------------

    def _text(self, style: TextStyle, frame: PixelFrame, value: str) -> FittedText:
        """Place one text element in the renderer's bounded fitting primitive."""
        size = to_pixels(style.font_size_mm, self._profile.dpi)
        minimum = to_pixels(style.minimum_font_size_mm, self._profile.dpi)
        fit, ellipsis = _OVERFLOW[style.overflow]
        return FittedText(
            value=value,
            x=frame.left,
            y=frame.top,
            width=frame.width,
            height=frame.height,
            size=max(size, 1),
            min_size=max(min(minimum, size), 1),
            max_lines=style.maximum_lines,
            line_spacing=to_pixels(
                LINE_SPACING_TOKENS[style.line_spacing].ratio * style.font_size_mm,
                self._profile.dpi,
            ),
            align=style.horizontal_align,
            valign=style.vertical_align,
            fit=fit,
            ellipsis=ellipsis,
            font=FONT_TOKENS[style.font].file,
        )

    def _qr(self, style: QrStyle, frame: PixelFrame, value: str) -> QrCode:
        """Place one QR element in the box its frame compiled to.

        The renderer chooses the largest integer pixels-per-module that fits
        the box, so `boxsize` is a floor rather than the extent; the frame is
        what the layout promised and the frame is what it gets.
        """
        return QrCode(
            data=value,
            x=frame.left,
            y=frame.top,
            boxsize=1,
            width=frame.width,
            height=frame.height,
            border=style.quiet_zone_modules,
            error_correction=_ERROR_CORRECTION[style.error_correction],
        )

    def _logo(self, style: LogoStyle, frame: PixelFrame, value: str) -> Logo:
        """Place one logo, preserving its own aspect ratio inside the frame."""
        return Logo(
            url=value,
            x=frame.left,
            y=frame.top,
            xsize=frame.width,
            ysize=frame.height,
            mode="contain",
            dither=MONOCHROME_TOKENS[style.monochrome].dither,
        )

    def _divider(self, style: DividerStyle, frame: PixelFrame) -> Divider:
        """Place one divider: its frame is its complete inked extent."""
        return Divider(
            x_start=frame.left,
            x_end=frame.right,
            y_start=frame.top,
            y_end=frame.bottom,
            fill=style.fill,
        )

    def _notes(
        self, style: TextStyle | LogoStyle | QrStyle, frame: PixelFrame
    ) -> Mapping[str, Any]:
        """Return what the compiler knows about one placed element."""
        if not isinstance(style, TextStyle):
            return {}
        return {
            "requested_font_size_px": to_pixels(style.font_size_mm, self._profile.dpi),
            "minimum_font_size_px": to_pixels(
                style.minimum_font_size_mm, self._profile.dpi
            ),
            "maximum_lines": style.maximum_lines,
            "overflow": style.overflow,
            "box_pixels": [frame.width, frame.height],
        }

    # -- diagnostics -------------------------------------------------------

    def _add(
        self,
        code: str,
        severity: Severity,
        message: str,
        *,
        element_id: str | None = None,
        parameters: Mapping[str, Any] | None = None,
        layer: Layer = Layer.PROFILE_COMPILATION,
    ) -> None:
        """Record one diagnostic of the layer that produced it."""
        self._diagnostics.append(
            Diagnostic(
                code=code,
                severity=severity,
                layer=layer,
                message=message,
                path="",
                element_id=element_id,
                parameters=parameters or {},
            )
        )
