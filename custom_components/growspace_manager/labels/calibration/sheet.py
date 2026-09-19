"""The standardized calibration label: the one sheet every printer is measured on.

Built from the Capability Profile rather than drawn for one stock, because
what it has to probe is that profile's own declared geometry. Every mark sits
at a known millimetre position inside the **declared** Printable Area, and
what the operator measures is the difference between where a mark should have
landed and where it did. A sheet drawn to the stock's physical edges instead
would ask the compiler to place ink outside the Printable Area, which is an
error -- so the one print that diagnoses a printer would be the one print the
safety policy refuses.

Four things on it, and each is on it for a reason somebody can check:

    edge scales   five staggered ticks per edge, 0.5 mm apart, running inward
                  from the declared Printable Area. The first tick that
                  printed is the first position this printer reaches, and the
                  distance back to the declared edge is that edge's offset.
                  They are staggered along the edge rather than stacked
                  because 0.5 mm at 203 dpi is four dots: ticks in one column
                  would merge into a smear and measure nothing.

    feed ruler    nine ticks, 1 mm apart, centred on the printable area's
                  midpoint along the profile's own feed axis, the middle one
                  longer. Feed alignment is signed, so the ruler has to run
                  both ways from a marked centre.

    identity      which profile, which resolution, stock and mounting, which
                  feed axis and density this sheet came out of. A calibration
                  label that does not say what it is a calibration of is a
                  piece of paper, and the measurements read off it cannot be
                  attributed to anything afterwards.

    print date    through the ordinary `print.date` binding, so the date on
                  the sheet is formatted by the same formatter every other
                  label's is rather than by a second one living here.

Two deliberate constraints on the text. It is **ASCII only** -- no middle
dots, no multiplication signs -- because a glyph the printer's font does not
carry is a hard error, and the print that must work on an unproven printer is
exactly this one. And the layout is **constructed rather than validated**:
`validate_document` requires a text element bound to `strain.name`, which this
sheet honestly does not have, because it is not about a strain. Everything
else about it is a valid v1 document, and the suite proves that by validating
it and admitting exactly that one diagnostic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime

from homeassistant.exceptions import HomeAssistantError

from ..canonical.catalogue import ElementKind, PrintContext
from ..canonical.content import LabelContentSnapshot
from ..canonical.document import (
    BindingSource,
    DividerStyle,
    Frame,
    LabelLayout,
    LayoutElement,
    LiteralSource,
    TextStyle,
)
from ..canonical.geometry import AreaMm
from ..canonical.profiles import CapabilityProfile, FeedAxis

#: Bumped when any mark below moves. It is a calibration dependency: a
#: measurement read off one arrangement of ticks does not transfer to another.
SHEET_VERSION = "growspace.label-calibration-sheet.v1"

#: What a calibration render's content snapshot declares itself to be. It is
#: not `record`, which is the whole point: no provenance check can ever mistake
#: a calibration sheet for a label about a real plant.
CALIBRATION_SOURCE = "calibration"

#: The prefix every element ID on this sheet carries. Structured rather than
#: opaque, unlike a saved template's: these elements are generated, and a
#: diagnostic naming `...top.3` says which tick far better than a ULID would.
ELEMENT_PREFIX = "growspace.calibration"

#: How far apart the edge ticks step inward. Four dots at 203 dpi, which is
#: the finest step that still reproduces as a separate mark.
TICK_PITCH_MM = 0.5
#: How many ticks each edge scale has, and therefore how deep it probes:
#: four steps of 0.5 mm, so an offset up to 2 mm reads directly off the sheet.
TICK_COUNT = 5
TICK_THICKNESS_MM = 0.4
TICK_LENGTH_MM = 2.6
#: How far each tick moves along the edge from the one before it, so that
#: adjacent ticks never share a column of dots.
TICK_STAGGER_MM = 3.0

FEED_TICK_COUNT = 9
FEED_TICK_PITCH_MM = 1.0
FEED_TICK_THICKNESS_MM = 0.4
FEED_TICK_LENGTH_MM = 2.0
FEED_CENTRE_LENGTH_MM = 3.2

#: Clearance between the edge scales and everything inside them.
CLEARANCE_MM = 0.6

_HEADING_FONT = "growspace.sans.bold.v1"
_BODY_FONT = "growspace.sans.regular.v1"
_COMPACT = "growspace.spacing.compact.v1"

#: How deep an edge scale reaches into the label.
_SCALE_DEPTH_MM = (TICK_COUNT - 1) * TICK_PITCH_MM + TICK_THICKNESS_MM
#: How far it runs along the edge.
_SCALE_RUN_MM = (TICK_COUNT - 1) * TICK_STAGGER_MM + TICK_LENGTH_MM
#: The inset inside which nothing may collide with an edge scale.
_INNER_INSET_MM = _SCALE_DEPTH_MM + CLEARANCE_MM
#: How far the feed ruler runs along the feed axis.
_FEED_RUN_MM = (FEED_TICK_COUNT - 1) * FEED_TICK_PITCH_MM + FEED_TICK_THICKNESS_MM

#: The smallest identity block worth printing. Below it the profile ID
#: shrinks past the readable floor and the sheet stops saying what it is of.
_IDENTITY_MINIMUM_MM = 18.0

#: The smallest Printable Area the standardized sheet fits in. Refused rather
#: than shrunk: a calibration label drawn smaller than its standard is no
#: longer the thing a measurement can be attributed to.
#:
#: Each is the larger of two requirements rather than a chosen number, so that
#: moving a tick pitch or the stagger moves the minimum with it instead of
#: leaving a constant behind that used to be right: the identity block and the
#: feed ruler need room between the edge scales, and an edge scale needs room
#: to run past the scale on the adjacent edge.
MINIMUM_PRINTABLE_WIDTH_MM = max(
    _INNER_INSET_MM * 2 + FEED_CENTRE_LENGTH_MM + _IDENTITY_MINIMUM_MM,
    _INNER_INSET_MM + _SCALE_RUN_MM,
)
MINIMUM_PRINTABLE_HEIGHT_MM = max(
    _INNER_INSET_MM * 2 + _IDENTITY_MINIMUM_MM,
    _INNER_INSET_MM + _SCALE_RUN_MM,
)


class CalibrationSheetUnavailable(HomeAssistantError):
    """This profile's Printable Area cannot carry the standardized sheet."""

    def __init__(self, profile_id: str, detail: str) -> None:
        """Name the profile and what does not fit."""
        self.profile_id = profile_id
        super().__init__(
            f"The standardized calibration label does not fit {profile_id}: {detail}"
        )


def calibration_layout(
    profile: CapabilityProfile, *, density: str = "normal"
) -> LabelLayout:
    """Build the standardized calibration label for one profile and density.

    `density` reaches the layout because the sheet names it. That makes the
    layout digest density-dependent, which is correct rather than incidental:
    two sheets printed at different heat are two different pieces of paper and
    a measurement has to be attributable to the one in the operator's hand.
    """
    area = profile.printable_area
    _refuse_if_too_small(profile, area)
    elements = [
        *_edge_scales(area),
        *_feed_ruler(area, profile.feed_axis),
        *_identity_block(profile, area, density=density),
    ]
    return LabelLayout(label_size_id=profile.label_size_id, elements=tuple(elements))


def calibration_content(
    profile: CapabilityProfile,
    *,
    as_of: datetime,
    locale: str = "en",
    time_zone: str = "UTC",
) -> LabelContentSnapshot:
    """The content snapshot a calibration render resolves against.

    Almost empty, because almost everything on the sheet is a literal the
    layout carries. What it is *not* is a fixture or a record: `source` says
    `calibration`, so the same provenance check that refuses to production-
    print a fixture refuses to production-print this.
    """
    return LabelContentSnapshot(
        context=PrintContext.STRAIN,
        subject=profile.id,
        as_of=as_of,
        locale=locale,
        time_zone=time_zone,
        source=CALIBRATION_SOURCE,
    )


def _refuse_if_too_small(profile: CapabilityProfile, area: AreaMm) -> None:
    """Refuse a Printable Area the standardized marks cannot fit inside."""
    if area.width_mm < MINIMUM_PRINTABLE_WIDTH_MM:
        raise CalibrationSheetUnavailable(
            profile.id,
            f"its Printable Area is {area.width_mm} mm wide and the sheet "
            f"needs {MINIMUM_PRINTABLE_WIDTH_MM} mm.",
        )
    if area.height_mm < MINIMUM_PRINTABLE_HEIGHT_MM:
        raise CalibrationSheetUnavailable(
            profile.id,
            f"its Printable Area is {area.height_mm} mm tall and the sheet "
            f"needs {MINIMUM_PRINTABLE_HEIGHT_MM} mm.",
        )


# ---------------------------------------------------------------------------
# The marks
# ---------------------------------------------------------------------------


def _edge_scales(area: AreaMm) -> Iterator[LayoutElement]:
    """Four graduated scales, one per edge, each stepping inward."""
    for index in range(TICK_COUNT):
        inward = index * TICK_PITCH_MM
        along = _INNER_INSET_MM + index * TICK_STAGGER_MM
        yield _divider(
            f"top.{index}",
            Frame(
                x_mm=area.x_mm + along,
                y_mm=area.y_mm + inward,
                width_mm=TICK_LENGTH_MM,
                height_mm=TICK_THICKNESS_MM,
            ),
        )
        yield _divider(
            f"bottom.{index}",
            Frame(
                x_mm=area.x_mm + along,
                y_mm=area.bottom_mm - inward - TICK_THICKNESS_MM,
                width_mm=TICK_LENGTH_MM,
                height_mm=TICK_THICKNESS_MM,
            ),
        )
        yield _divider(
            f"left.{index}",
            Frame(
                x_mm=area.x_mm + inward,
                y_mm=area.y_mm + along,
                width_mm=TICK_THICKNESS_MM,
                height_mm=TICK_LENGTH_MM,
            ),
        )
        yield _divider(
            f"right.{index}",
            Frame(
                x_mm=area.right_mm - inward - TICK_THICKNESS_MM,
                y_mm=area.y_mm + along,
                width_mm=TICK_THICKNESS_MM,
                height_mm=TICK_LENGTH_MM,
            ),
        )


def _feed_ruler(area: AreaMm, feed_axis: FeedAxis) -> Iterator[LayoutElement]:
    """A signed ruler along the feed axis, centred on the printable midpoint."""
    inner = _inner(area)
    middle = (FEED_TICK_COUNT - 1) // 2
    for index in range(FEED_TICK_COUNT):
        offset = (index - middle) * FEED_TICK_PITCH_MM
        length = FEED_CENTRE_LENGTH_MM if index == middle else FEED_TICK_LENGTH_MM
        if feed_axis is FeedAxis.Y:
            frame = Frame(
                x_mm=inner.x_mm,
                y_mm=_centre_y(area) + offset - FEED_TICK_THICKNESS_MM / 2,
                width_mm=length,
                height_mm=FEED_TICK_THICKNESS_MM,
            )
        else:
            frame = Frame(
                x_mm=_centre_x(area) + offset - FEED_TICK_THICKNESS_MM / 2,
                y_mm=inner.y_mm,
                width_mm=FEED_TICK_THICKNESS_MM,
                height_mm=length,
            )
        yield _divider(f"feed.{index}", frame)


def _identity_block(
    profile: CapabilityProfile, area: AreaMm, *, density: str
) -> Iterator[LayoutElement]:
    """What this sheet is of, in the space the scales and the ruler leave."""
    region = _text_area(area, profile.feed_axis)
    size = profile.label_size
    level = profile.density_level(density)
    lines = (
        _Line("title", "Label calibration", _HEADING_FONT, 2.8, 2.2, 3.4, 1),
        _Line("profile", profile.id, _BODY_FONT, 2.4, 1.8, 6.2, 2),
        _Line(
            "geometry",
            f"{profile.dpi} dpi | {size.width_mm:g}x{size.height_mm:g} mm"
            f" | {profile.orientation}",
            _BODY_FONT,
            2.4,
            1.8,
            3.4,
            1,
        ),
        _Line(
            "settings",
            f"feed {profile.feed_axis} | density {density}"
            f" ({'unmapped' if level is None else level})",
            _BODY_FONT,
            2.4,
            1.8,
            3.4,
            1,
        ),
    )
    stacked = sum(line.height_mm for line in lines) + _DATE_HEIGHT_MM
    gaps = CLEARANCE_MM * len(lines)
    top = region.y_mm + max((region.height_mm - stacked - gaps) / 2, 0.0)

    for line in lines:
        yield _text(
            line.suffix,
            Frame(
                x_mm=region.x_mm,
                y_mm=top,
                width_mm=region.width_mm,
                height_mm=line.height_mm,
            ),
            LiteralSource(line.value),
            font=line.font,
            size_mm=line.size_mm,
            minimum_mm=line.minimum_mm,
            maximum_lines=line.maximum_lines,
        )
        top += line.height_mm + CLEARANCE_MM

    yield _text(
        "printed_on",
        Frame(
            x_mm=region.x_mm,
            y_mm=top,
            width_mm=region.width_mm,
            height_mm=_DATE_HEIGHT_MM,
        ),
        BindingSource("print.date", {"date_style": "iso"}),
        font=_BODY_FONT,
        size_mm=2.2,
        minimum_mm=1.8,
        maximum_lines=1,
    )


#: How tall the printed-on line is. Beside the block rather than in it because
#: it is the one line whose text the layout does not carry.
_DATE_HEIGHT_MM = 3.0


@dataclass(frozen=True, slots=True)
class _Line:
    """One literal line of the identity block."""

    suffix: str
    value: str
    font: str
    size_mm: float
    minimum_mm: float
    height_mm: float
    maximum_lines: int


# ---------------------------------------------------------------------------
# Regions
# ---------------------------------------------------------------------------


def _inner(area: AreaMm) -> AreaMm:
    """The Printable Area with the four edge scales' depth taken off it."""
    return AreaMm(
        x_mm=area.x_mm + _INNER_INSET_MM,
        y_mm=area.y_mm + _INNER_INSET_MM,
        width_mm=area.width_mm - 2 * _INNER_INSET_MM,
        height_mm=area.height_mm - 2 * _INNER_INSET_MM,
    )


def _text_area(area: AreaMm, feed_axis: FeedAxis) -> AreaMm:
    """The inner region with the feed ruler's side taken off it too.

    Which side that is follows the ruler: a ruler running down the label hugs
    the left of the inner region and costs width; one running across it hugs
    the top and costs height. Nothing overlaps because nothing is placed
    without asking what the ruler already took.
    """
    inner = _inner(area)
    consumed = FEED_CENTRE_LENGTH_MM + CLEARANCE_MM
    if feed_axis is FeedAxis.Y:
        return AreaMm(
            x_mm=inner.x_mm + consumed,
            y_mm=inner.y_mm,
            width_mm=inner.width_mm - consumed,
            height_mm=inner.height_mm,
        )
    return AreaMm(
        x_mm=inner.x_mm,
        y_mm=inner.y_mm + consumed,
        width_mm=inner.width_mm,
        height_mm=inner.height_mm - consumed,
    )


def _centre_x(area: AreaMm) -> float:
    """The Printable Area's midpoint across the stock."""
    return area.x_mm + area.width_mm / 2


def _centre_y(area: AreaMm) -> float:
    """The Printable Area's midpoint down the stock."""
    return area.y_mm + area.height_mm / 2


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


def _divider(suffix: str, frame: Frame) -> LayoutElement:
    """One mark of the sheet, as a plain rectangle."""
    return LayoutElement(
        id=f"{ELEMENT_PREFIX}.{suffix}",
        kind=ElementKind.DIVIDER,
        frame=_quantized(frame),
        rotation=0,
        style=DividerStyle(fill="black"),
    )


def _text(
    suffix: str,
    frame: Frame,
    content: LiteralSource | BindingSource,
    *,
    font: str,
    size_mm: float,
    minimum_mm: float,
    maximum_lines: int,
) -> LayoutElement:
    """One line of the identity block."""
    return LayoutElement(
        id=f"{ELEMENT_PREFIX}.{suffix}",
        kind=ElementKind.TEXT,
        frame=_quantized(frame),
        rotation=0,
        style=TextStyle(
            font=font,
            font_size_mm=size_mm,
            horizontal_align="left",
            vertical_align="top",
            line_spacing=_COMPACT,
            overflow="shrink_ellipsis",
            minimum_font_size_mm=minimum_mm,
            maximum_lines=maximum_lines,
        ),
        content=content,
    )


def _quantized(frame: Frame) -> Frame:
    """Snap a computed frame to the document's own millimetre quantum.

    The arithmetic above divides by two and multiplies by pitches, so it can
    land a hundredth of a nanometre off a hundredth of a millimetre. A saved
    document would be refused for that; this one is constructed, so it is
    rounded here rather than left to be the one layout the quantum does not
    apply to.
    """
    return Frame(
        x_mm=round(frame.x_mm, 2),
        y_mm=round(frame.y_mm, 2),
        width_mm=round(frame.width_mm, 2),
        height_mm=round(frame.height_mm, 2),
    )
