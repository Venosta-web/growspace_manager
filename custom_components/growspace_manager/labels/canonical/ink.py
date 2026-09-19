"""What each element actually paints, rather than what its frame reserves.

A frame is a promise about millimetres. Ink is what lands on the stock, and
the two are different in every way that matters to print safety: a divider
fills its frame, a contained logo letterboxes inside it, a QR occupies an
integer number of modules anchored at its top-left corner and a fitted line
of text occupies whatever the chosen size, wrapping and alignment left it.

Judging overlap, occlusion or Safe Area excursions from frames would
therefore be a different product's answer. This module produces the real
thing: for every placed element, the pixels it inks, as a one-bit mask on the
raster's own grid, plus the measurements the policy layer needs -- resolved
font size, truncation, missing glyphs, module scale, effective image
resolution.

Every geometry here reproduces the pinned renderer's, deliberately and
literally: the same fitting search, the same line box, the same anchors, the
same square integer scale, the same centred contain. Where the renderer
cannot be reproduced -- a font file this installation does not hold, an image
behind an HTTP URL that validation must not fetch -- the element's ink is
declared to be its frame and the basis says so, so nothing downstream mistakes
a fallback for a measurement.
"""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
from io import BytesIO
from typing import Any

from PIL import Image, ImageChops, ImageDraw, UnidentifiedImageError

from ..model import Divider, FittedText, LabelElement, Logo, QrCode
from .fonts import FontLibrary, MeasuredFont, new_mask
from .geometry import PixelFrame
from .qr import QrDataOverflow, dots_per_module, symbol_for


def _margin(canvas_width: int, canvas_height: int) -> int:
    """How far outside the raster an ink mask still records ink.

    Masks are drawn on a padded canvas because the interesting case is ink
    that leaves the Printable Area, and a mask exactly the size of the raster
    would clip precisely that away -- reporting a layout whose text runs off
    the bottom of the stock as one whose ink lies neatly inside it. The margin
    is the raster's own larger dimension, which no element's line box can
    exceed from a frame the compiler already refused to place outside.
    """
    return max(canvas_width, canvas_height)


class _Mask:
    """One element's ink, drawn on a padded canvas in raster coordinates."""

    def __init__(self, canvas_width: int, canvas_height: int) -> None:
        """Allocate the padded bitmap and remember where the raster sits."""
        self.offset = _margin(canvas_width, canvas_height)
        self.image = new_mask(
            canvas_width + 2 * self.offset, canvas_height + 2 * self.offset
        )

    def draw(self) -> ImageDraw.ImageDraw:
        """A draw handle in padded coordinates."""
        return ImageDraw.Draw(self.image)

    def rectangle(self, left: int, top: int, right: int, bottom: int) -> None:
        """Fill one inclusive rectangle given in raster coordinates."""
        self.draw().rectangle(
            [
                (left + self.offset, top + self.offset),
                (right + self.offset, bottom + self.offset),
            ],
            fill=1,
        )

    def paste(self, image: Image.Image, x: int, y: int) -> None:
        """Paste one already-monochrome image at a raster coordinate."""
        self.image.paste(image, (x + self.offset, y + self.offset))

    def bounds(self) -> PixelFrame | None:
        """The tight box of what was drawn, back in raster coordinates."""
        box = self.image.getbbox()
        if box is None:
            return None
        return PixelFrame(
            left=box[0] - self.offset,
            top=box[1] - self.offset,
            right=box[2] - self.offset,
            bottom=box[3] - self.offset,
        )


class InkBasis(StrEnum):
    """How much of an element's ink the backend really knows."""

    #: Measured or computed from the same inputs the renderer uses.
    EXACT = "exact"
    #: Not measurable here; the element's compiled frame stands in for it.
    FRAME = "frame"
    #: The element paints nothing at all.
    NONE = "none"


@dataclass(frozen=True, slots=True)
class ElementInk:
    """One element's painted extent and the measurements behind it."""

    element_id: str
    kind: str
    basis: InkBasis
    #: The tight bounding box of the painted pixels.
    bounds: PixelFrame | None
    #: Identity of the mask, so a client can cache and audit without holding
    #: the bitmap the backend compared.
    mask_digest: str
    #: A region no other element may ink. Only a QR has one.
    protected: PixelFrame | None = None
    measurements: Mapping[str, Any] = field(default_factory=dict)
    #: The mask itself, kept for the policy layer and never serialized.
    mask: Image.Image | None = field(default=None, repr=False, compare=False)
    #: Where the raster's origin sits inside that padded mask.
    mask_offset: int = 0

    def as_dict(self) -> dict[str, Any]:
        """Return the ink's wire form, which never carries the bitmap."""
        return {
            "element_id": self.element_id,
            "kind": self.kind,
            "basis": str(self.basis),
            "bounds": self.bounds.as_dict() if self.bounds else None,
            "mask_digest": self.mask_digest,
            "protected_area": self.protected.as_dict() if self.protected else None,
            "measurements": dict(self.measurements),
        }


@dataclass(frozen=True, slots=True)
class FittedLines:
    """What the renderer's bounded fitting did to one string."""

    lines: tuple[str, ...]
    size: int
    line_height: int
    #: Content was dropped or replaced by the truncation mark.
    truncated: bool
    #: A shrinking policy found a size at which everything fitted.
    fitted_within_minimum: bool


def element_ink(
    element: LabelElement,
    *,
    element_id: str,
    kind: str,
    frame: PixelFrame,
    canvas_width: int,
    canvas_height: int,
    dpi: int,
    fonts: FontLibrary,
) -> ElementInk:
    """Compute one placed element's ink on the raster."""
    if isinstance(element, Divider):
        return _divider_ink(element, element_id, kind, canvas_width, canvas_height, dpi)
    if isinstance(element, QrCode):
        return _qr_ink(element, element_id, kind, frame, canvas_width, canvas_height)
    if isinstance(element, Logo):
        return _logo_ink(
            element, element_id, kind, frame, canvas_width, canvas_height, dpi
        )
    if isinstance(element, FittedText):
        return _text_ink(
            element, element_id, kind, frame, canvas_width, canvas_height, dpi, fonts
        )
    return _frame_ink(element_id, kind, frame, canvas_width, canvas_height, {})


# -- text --------------------------------------------------------------------


def fit_lines(
    value: str, font: MeasuredFont, max_width: float, max_lines: int, ellipsis: str
) -> tuple[list[str], bool]:
    """Wrap `value` into at most `max_lines`, reporting whether it all fitted."""
    wrapped = _wrap(value, font, max_width)
    fits = True
    lines = wrapped[:max_lines]
    if len(wrapped) > max_lines:
        fits = False
        lines[-1] = _ellipsize(font, lines[-1], max_width, ellipsis)
    for index, line in enumerate(lines):
        if font.advance(line) > max_width:
            fits = False
            lines[index] = _ellipsize(font, line, max_width, ellipsis)
    return lines, fits


def fit_text(
    element: FittedText, font_at: Callable[[int], MeasuredFont]
) -> FittedLines:
    """Reproduce the renderer's bounded fitting for one text element.

    `font_at` loads the face at a pixel size. The three policies differ only
    in where they give up: `shrink` stops at the declared minimum and stays
    too big, `ellipsis` keeps the declared size and drops content, and
    `shrink_ellipsis` does both in that order.
    """
    inner_width = element.width
    inner_height = element.height

    def layout(size: int) -> tuple[MeasuredFont, list[str], bool, int]:
        font = font_at(size)
        ascent, descent = font.metrics()
        line_height = ascent + descent + element.line_spacing
        lines, fits = fit_lines(
            element.value, font, inner_width, element.max_lines, element.ellipsis
        )
        return font, lines, fits, line_height

    if element.fit in ("shrink", "shrink_ellipsis"):
        for size in range(int(element.size), int(element.min_size) - 1, -1):
            font, lines, fits, line_height = layout(size)
            if fits and line_height * len(lines) <= inner_height:
                return FittedLines(
                    lines=tuple(lines),
                    size=size,
                    line_height=line_height,
                    truncated=False,
                    fitted_within_minimum=True,
                )
        font, lines, _, line_height = layout(int(element.min_size))
        truncated = True
        if element.fit == "shrink_ellipsis":
            lines = _trim_rows(
                font, lines, inner_width, inner_height, line_height, element.ellipsis
            )
        return FittedLines(
            lines=tuple(lines),
            size=int(element.min_size),
            line_height=line_height,
            truncated=truncated,
            fitted_within_minimum=False,
        )

    font, lines, fits, line_height = layout(int(element.size))
    rows = len(lines)
    lines = _trim_rows(
        font, lines, inner_width, inner_height, line_height, element.ellipsis
    )
    return FittedLines(
        lines=tuple(lines),
        size=int(element.size),
        line_height=line_height,
        truncated=not fits or len(lines) != rows,
        fitted_within_minimum=True,
    )


def _trim_rows(
    font: MeasuredFont,
    lines: list[str],
    inner_width: float,
    inner_height: int,
    line_height: int,
    ellipsis: str,
) -> list[str]:
    """Drop the rows that do not fit the box, marking the last one kept."""
    max_rows = max(1, inner_height // max(line_height, 1))
    if len(lines) <= max_rows:
        return lines
    kept = lines[:max_rows]
    kept[-1] = _ellipsize(font, kept[-1], inner_width, ellipsis)
    return kept


def _wrap(text: str, font: MeasuredFont, max_width: float) -> list[str]:
    """Greedy word wrap; one over-long word stays on its own line."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        trial = f"{current} {word}".strip()
        if current and font.advance(trial) > max_width:
            lines.append(current)
            current = word
        else:
            current = trial
    if current:
        lines.append(current)
    return lines


def _ellipsize(font: MeasuredFont, line: str, max_width: float, ellipsis: str) -> str:
    """Trim one line until it and the truncation mark fit."""
    if font.advance(line + ellipsis) <= max_width:
        return line + ellipsis
    trimmed = line
    while trimmed and font.advance(trimmed + ellipsis) > max_width:
        trimmed = trimmed[:-1]
    return trimmed + ellipsis


def _text_ink(
    element: FittedText,
    element_id: str,
    kind: str,
    frame: PixelFrame,
    canvas_width: int,
    canvas_height: int,
    dpi: int,
    fonts: FontLibrary,
) -> ElementInk:
    """Measure and rasterize one fitted text element."""
    loaded: dict[int, MeasuredFont] = {}

    def font_at(size: int) -> MeasuredFont | None:
        if size not in loaded:
            face = fonts.load(element.font, size)
            if face is None:
                return None
            loaded[size] = face
        return loaded[size]

    probe = font_at(int(element.size))
    if probe is None:
        return _frame_ink(
            element_id,
            kind,
            frame,
            canvas_width,
            canvas_height,
            {
                "measured": False,
                "font_file": element.font,
                "requested_font_size_px": int(element.size),
            },
        )

    fitted = fit_text(element, lambda size: font_at(size) or probe)
    face = font_at(fitted.size) or probe
    missing = face.missing_glyphs(element.value)

    mask = _Mask(canvas_width, canvas_height)
    draw = mask.draw()
    draw.fontmode = "1"
    total_height = fitted.line_height * len(fitted.lines)
    if element.valign == "middle":
        origin_y = element.y + (element.height - total_height) // 2
    elif element.valign == "bottom":
        origin_y = element.y + element.height - total_height
    else:
        origin_y = element.y

    for index, line in enumerate(fitted.lines):
        line_y = origin_y + index * fitted.line_height
        if element.align == "center":
            line_x, anchor = element.x + element.width // 2, "ma"
        elif element.align == "right":
            line_x, anchor = element.x + element.width, "ra"
        else:
            line_x, anchor = element.x, "la"
        face.draw_line(draw, (line_x + mask.offset, line_y + mask.offset), line, anchor)

    return _from_mask(
        element_id,
        kind,
        mask,
        {
            "measured": True,
            "font_file": element.font,
            "font_digest": face.digest,
            "requested_font_size_px": int(element.size),
            "resolved_font_size_px": fitted.size,
            "resolved_font_size_mm": round(fitted.size * 25.4 / dpi, 4),
            "minimum_font_size_px": int(element.min_size),
            "lines": list(fitted.lines),
            "line_count": len(fitted.lines),
            "truncated": fitted.truncated,
            "fitted_within_minimum": fitted.fitted_within_minimum,
            "overflow": element.fit,
            "missing_glyphs": list(missing),
        },
    )


# -- qr ----------------------------------------------------------------------


def _qr_ink(
    element: QrCode,
    element_id: str,
    kind: str,
    frame: PixelFrame,
    canvas_width: int,
    canvas_height: int,
) -> ElementInk:
    """Compute the square a QR really paints, quiet zone included."""
    quiet_zone = element.border or 0
    correction = {"l": "low", "m": "medium", "q": "quartile", "h": "high"}[
        element.error_correction or "h"
    ]
    encoded_bytes = len(element.data.encode("utf-8"))
    measurements: dict[str, Any] = {
        "error_correction": correction,
        "quiet_zone_modules": quiet_zone,
        "encoded_bytes": encoded_bytes,
    }

    try:
        symbol = symbol_for(element.data, correction)
    except QrDataOverflow:
        measurements["encodable"] = False
        return _frame_ink(
            element_id, kind, frame, canvas_width, canvas_height, measurements
        )

    side_modules = symbol.side_modules(quiet_zone)
    box = min(element.width or frame.width, element.height or frame.height)
    scale = dots_per_module(box, side_modules)
    painted = side_modules * scale if scale else box
    measurements.update(
        {
            "encodable": True,
            "qr_version": symbol.version,
            "modules": symbol.modules,
            "side_modules": side_modules,
            "dots_per_module": scale,
            "painted_side_px": painted,
            "integer_module_scale": scale >= 1,
            "box_px": box,
        }
    )

    area = PixelFrame(
        left=element.x,
        top=element.y,
        right=element.x + painted,
        bottom=element.y + painted,
    )
    mask = _Mask(canvas_width, canvas_height)
    mask.rectangle(area.left, area.top, area.right - 1, area.bottom - 1)
    ink = _from_mask(element_id, kind, mask, measurements)
    # A QR's whole painted square is protected, not just its dark modules:
    # the quiet zone is part of the symbol and ink anywhere inside it is what
    # stops a scanner, so the protected region is the square the renderer
    # pastes rather than the subset of it that happens to be black.
    return ElementInk(
        element_id=ink.element_id,
        kind=ink.kind,
        basis=ink.basis,
        bounds=ink.bounds,
        mask_digest=ink.mask_digest,
        protected=area,
        measurements=ink.measurements,
        mask=ink.mask,
        mask_offset=ink.mask_offset,
    )


# -- logo --------------------------------------------------------------------


def _logo_ink(
    element: Logo,
    element_id: str,
    kind: str,
    frame: PixelFrame,
    canvas_width: int,
    canvas_height: int,
    dpi: int,
) -> ElementInk:
    """Decode a logo and place it the way the renderer contains it."""
    measurements: dict[str, Any] = {"fit": element.mode, "dither": element.dither}
    source = _decode_image(element.url)
    if source is None:
        measurements["decoded"] = False
        measurements["remote"] = element.url.startswith(("http://", "https://"))
        return _frame_ink(
            element_id, kind, frame, canvas_width, canvas_height, measurements
        )

    with source:
        source_width, source_height = source.size
        painted_width, painted_height = _contain(
            source_width, source_height, element.xsize, element.ysize
        )
        resized = source.convert("RGBA").resize(
            (max(painted_width, 1), max(painted_height, 1)), Image.Resampling.LANCZOS
        )

    offset_x = element.x + (element.xsize - painted_width) // 2
    offset_y = element.y + (element.ysize - painted_height) // 2
    mask = _Mask(canvas_width, canvas_height)
    mask.paste(_monochrome(resized), offset_x, offset_y)

    effective = min(
        source_width / max(painted_width, 1), source_height / max(painted_height, 1)
    )
    measurements.update(
        {
            "decoded": True,
            "remote": False,
            "source_width": source_width,
            "source_height": source_height,
            "painted_width": painted_width,
            "painted_height": painted_height,
            "effective_dpi": round(dpi * effective, 2),
        }
    )
    return _from_mask(element_id, kind, mask, measurements)


def _contain(
    source_width: int, source_height: int, box_width: int, box_height: int
) -> tuple[int, int]:
    """The extent a contained image takes inside its box, aspect preserved."""
    target_ratio = box_width / box_height if box_height else 1
    source_ratio = source_width / source_height if source_height else 1
    if source_ratio > target_ratio:
        return box_width, round(box_width / source_ratio)
    return round(box_height * source_ratio), box_height


def _decode_image(url: str) -> Image.Image | None:
    """Decode an inline image, or decline to reach out over the network.

    Validation never fetches an HTTP logo. Doing so would make a saved layout's
    diagnostics depend on a third party's uptime, and the renderer is the one
    that has to survive that anyway.
    """
    if not url.startswith("data:"):
        return None
    _, _, payload = url.partition(",")
    if not payload:
        return None
    try:
        raw = base64.b64decode(payload + "=" * (-len(payload) % 4), validate=False)
        image = Image.open(BytesIO(raw))
        image.load()
    except binascii.Error, ValueError, OSError, UnidentifiedImageError:
        return None
    return image


def _monochrome(image: Image.Image) -> Image.Image:
    """Reduce one placed image to the ink it leaves, transparency included."""
    alpha = image.getchannel("A").point(lambda value: 255 if value > 127 else 0)
    dark = image.convert("L").point(lambda value: 255 if value < 128 else 0)
    return ImageChops.multiply(dark, alpha).convert("1")


# -- dividers and fallbacks --------------------------------------------------


def _divider_ink(
    element: Divider,
    element_id: str,
    kind: str,
    canvas_width: int,
    canvas_height: int,
    dpi: int,
) -> ElementInk:
    """A divider inks its whole rectangle; its frame is its extent exactly.

    Both edges are inclusive, because that is how the renderer's rectangle
    reads them.
    """
    mask = _Mask(canvas_width, canvas_height)
    mask.rectangle(element.x_start, element.y_start, element.x_end, element.y_end)
    thickness = element.y_end - element.y_start + 1
    return _from_mask(
        element_id,
        kind,
        mask,
        {
            "thickness_px": thickness,
            "thickness_mm": round(thickness * 25.4 / dpi, 4),
            "length_px": element.x_end - element.x_start + 1,
        },
    )


def _frame_ink(
    element_id: str,
    kind: str,
    frame: PixelFrame,
    canvas_width: int,
    canvas_height: int,
    measurements: Mapping[str, Any],
) -> ElementInk:
    """Stand the compiled frame in for ink the backend cannot measure."""
    mask = _Mask(canvas_width, canvas_height)
    if not frame.is_empty:
        mask.rectangle(frame.left, frame.top, frame.right - 1, frame.bottom - 1)
    return ElementInk(
        element_id=element_id,
        kind=kind,
        basis=InkBasis.FRAME,
        bounds=frame,
        mask_digest=_digest(mask.image),
        measurements=dict(measurements),
        mask=mask.image,
        mask_offset=mask.offset,
    )


def omitted_ink(element_id: str, kind: str) -> ElementInk:
    """The ink of an element that reached no plan: none, and stated as none."""
    return ElementInk(
        element_id=element_id,
        kind=kind,
        basis=InkBasis.NONE,
        bounds=None,
        mask_digest=_digest(new_mask(1, 1)),
        measurements={},
        mask=None,
    )


def _from_mask(
    element_id: str, kind: str, mask: _Mask, measurements: Mapping[str, Any]
) -> ElementInk:
    """Build one exact ink record from the mask its element painted."""
    return ElementInk(
        element_id=element_id,
        kind=kind,
        basis=InkBasis.EXACT,
        bounds=mask.bounds(),
        mask_digest=_digest(mask.image),
        measurements=dict(measurements),
        mask=mask.image,
        mask_offset=mask.offset,
    )


def _digest(mask: Image.Image) -> str:
    """A short identity for one ink mask."""
    return hashlib.sha256(mask.tobytes()).hexdigest()[:16]


def overlap_of(first: ElementInk, second: ElementInk) -> PixelFrame | None:
    """Return where two elements' ink coincides, or `None` when it does not."""
    if first.mask is None or second.mask is None:
        return None
    box = ImageChops.logical_and(first.mask, second.mask).getbbox()
    if box is None:
        return None
    offset = first.mask_offset
    return PixelFrame(
        left=box[0] - offset,
        top=box[1] - offset,
        right=box[2] - offset,
        bottom=box[3] - offset,
    )


def ink_pixels(ink: ElementInk) -> int:
    """How many pixels one element inks."""
    if ink.mask is None:
        return 0
    return _set_pixels(ink.mask)


def occluded_pixels(ink: ElementInk, covering: Image.Image | None) -> int:
    """How many of an element's inked pixels another element paints over."""
    if ink.mask is None or covering is None:
        return 0
    return _set_pixels(ImageChops.logical_and(ink.mask, covering))


def _set_pixels(mask: Image.Image) -> int:
    """Count the set pixels of a one-bit mask.

    A `"1"` image's histogram bins its two values at 0 and 1 rather than at 0
    and 255, whatever `getpixel` reports -- so the sum is taken over
    everything above zero rather than read off a remembered index.
    """
    return sum(mask.histogram()[1:])


def union_of(masks: list[Image.Image]) -> Image.Image | None:
    """Combine several ink masks into the region they cover together."""
    if not masks:
        return None
    combined = masks[0]
    for mask in masks[1:]:
        combined = ImageChops.logical_or(combined, mask)
    return combined
