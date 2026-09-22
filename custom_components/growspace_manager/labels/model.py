"""The vocabulary of the label rendering seam.

Everything here is printer-neutral and free of Home Assistant: a
[[Label Content]] snapshot is what a label says, a [[Label Render Plan]] is
where every mark sits on the stock, and neither knows what will realise it.
The Niimbot adapter is one consumer of a plan, not its author.

Geometry is device pixels on a named [[Canvas]], which is what the Classic
fixed-coordinate design has always been expressed in. The canonical
millimetre document from hub issue #206 replaces this coordinate space later;
it does not change where the seam sits.
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any

# The geometry words every element variant shares. Resizing a plan means
# scaling exactly these, which is why an element that means "right edge" is
# always spelled `x_end` and one that means "how wide" is always `width`.
_X_FIELDS = frozenset({"x", "x_start", "x_end", "width", "xsize"})
_Y_FIELDS = frozenset({"y", "y_start", "y_end", "height", "ysize"})


@dataclass(frozen=True, slots=True)
class Canvas:
    """The printable extent of one label, in device pixels."""

    width: int
    height: int


@dataclass(frozen=True, slots=True)
class TextBlock:
    """Wrapping text auto-fitted into a box."""

    value: str
    x: int
    y: int
    x_end: int
    width: int
    height: int
    size: int
    font: str
    fit: bool = True


@dataclass(frozen=True, slots=True)
class TextLine:
    """One unwrapped line drawn from its top-left corner."""

    value: str
    x: int
    y: int
    size: int
    font: str


@dataclass(frozen=True, slots=True)
class FittedText:
    """Text fitted into a fixed box: wrapped, aligned and auto-sized.

    The bounded primitive the canonical millimetre document compiles to, and
    the one that owns wrapping, line limits, alignment, shrinking and
    ellipsis. `TextBlock` is the Classic design's unwrapped ancestor; both
    exist while both paths do.
    """

    value: str
    x: int
    y: int
    width: int
    height: int
    size: int
    font: str
    min_size: int
    max_lines: int
    line_spacing: int
    align: str
    valign: str
    fit: str
    #: Truncation mark. Empty spells the `clip` policy, whose glyphs are
    #: dropped whole rather than cut mid-stroke.
    ellipsis: str = "\u2026"


@dataclass(frozen=True, slots=True)
class Divider:
    """A filled rectangle. The only v1 use is a horizontal rule."""

    x_start: int
    x_end: int
    y_start: int
    y_end: int
    fill: str = "black"


@dataclass(frozen=True, slots=True)
class Logo:
    """An image placed by URL or inline data URI, drawn into its box.

    `mode` and `dither` are the canonical path's: `contain` preserves the
    source's own aspect ratio inside the frame, and the monochrome Style Token
    decides whether the conversion dithers. Both stay `None` on the Classic
    path, which stretches and never dithers, so its payload is unchanged.
    """

    url: str
    x: int
    y: int
    xsize: int
    ysize: int
    mode: str | None = None
    dither: bool | None = None


@dataclass(frozen=True, slots=True)
class QrCode:
    """A QR code, sized either by module or by the box it must fit.

    The Classic path sets `boxsize` and lets the extent fall where it may. The
    canonical path sets `width`/`height` instead, because a saved frame is a
    promise about millimetres that a module-sized code cannot keep.
    """

    data: str
    x: int
    y: int
    boxsize: int
    width: int | None = None
    height: int | None = None
    border: int | None = None
    error_correction: str | None = None


LabelElement = TextBlock | TextLine | FittedText | Divider | Logo | QrCode


@dataclass(frozen=True, slots=True)
class LabelContent:
    """What one label says, resolved once and never resolved again.

    Already filtered: a caller that suppressed the breeder line leaves it out
    of `info_lines`, and one that suppressed the logo passes `logo=None`. The
    renderer places what it is given and never re-decides visibility, because
    a second opinion about content is how a preview and its print drift apart.
    """

    title: str
    info_lines: tuple[str, ...]
    logo: str | None
    qr_data: str | None
    printed_on: str


@dataclass(frozen=True, slots=True)
class LabelRenderPlan:
    """One composed label: every element placed on a known canvas.

    This is the seam's output and a printer adapter's only input. Density
    stays symbolic here — mapping it onto a device's scale is the adapter's
    job, because the same word means different heat on different hardware.
    """

    canvas: Canvas
    elements: tuple[LabelElement, ...]
    density: str
    #: The device value a [[Capability Profile]] resolved `density` to. The
    #: canonical path sets it; the Classic path leaves it unset and the
    #: adapter falls back to its own global table.
    density_level: int | None = None

    def scaled_to(self, canvas: Canvas) -> LabelRenderPlan:
        """Return this plan re-expressed on `canvas`.

        Each axis scales independently, so a stock with a different aspect
        ratio stretches rather than letterboxes. That is the Classic
        behaviour; the canonical millimetre model exists to end it.
        """
        if canvas == self.canvas:
            return self

        scale_x = canvas.width / self.canvas.width
        scale_y = canvas.height / self.canvas.height
        return replace(
            self,
            canvas=canvas,
            elements=tuple(
                _scale_element(element, scale_x, scale_y) for element in self.elements
            ),
        )


def _scale_element(
    element: LabelElement, scale_x: float, scale_y: float
) -> LabelElement:
    """Scale every geometry field of one element, leaving the rest alone.

    Font `size` and QR `boxsize` are deliberately absent from both axis sets.
    Both are already auto-fitted or module-quantized by the printer, so
    scaling them a second time would fight that fitting rather than help it.
    """
    placed: dict[str, Any] = {}
    for field in fields(element):
        value = getattr(element, field.name)
        if value is None:
            # An optional geometry field the Classic path never sets.
            placed[field.name] = None
            continue
        if field.name in _X_FIELDS:
            value = round(value * scale_x)
        elif field.name in _Y_FIELDS:
            value = round(value * scale_y)
        placed[field.name] = value
    return type(element)(**placed)
