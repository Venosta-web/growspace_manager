"""The evidence label: one print that probes a profile's claimed limits.

The standardized calibration sheet answers one question -- where does this
printer put ink -- and it is deliberately plain so nothing else on it can fail.
A [[Release Evidence Record]] asks more than that: whether the smallest text
the profile calls readable is readable, whether a QR at the profile's minimum
dots per module scans at the shortest, a typical and the longest target it
admits, and whether the thinnest rule it claims comes out as a line. This
sheet puts every one of those claims on the same piece of paper as the edge
scales, so one print per density is most of the physical matrix.

It is built from the profile rather than drawn for one stock, for the same
reason the calibration sheet is: every probe is sized from the number the
profile claims, so a profile whose limits move gets a sheet that tests the
new limits rather than the old ones.

    edge scales   the calibration sheet's own, in the same positions, so the
                  four edge offsets read off either sheet are the same four
                  numbers. Feed alignment is the offset along the feed axis,
                  so this sheet needs no separate ruler for it.

    QR probes     three literal targets at the profile's weakest claimed error
                  correction, each in a box of exactly the claimed minimum
                  dots per module: the shortest real plant route, a typical
                  dashboard URL, and a target of exactly the claimed maximum
                  encoded bytes. The long one ends with its own byte count, so
                  a scan that decoded it whole says so.

    text probes   the readable floor and the comfort threshold, in both faces,
                  with short, typical, accented and long text. The long probe
                  wraps to two lines and then truncates, which is what a long
                  strain name does on a real label.

    rule probes   the thinnest divider the profile claims, and twice it.

    identity      which profile and density this is, and the print date, so
                  the photograph of it can be attributed afterwards. It is
                  printed at the readable floor, so it is a probe as well.

Two things it deliberately does not probe. A **logo** needs an asset this
integration does not ship, so the logo row of the matrix is a real strain
label with a breeder logo. And a **missing glyph** is not a physical case at
all: the safety policy refuses to print one, and that refusal is what the
evidence records.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from decimal import ROUND_CEILING, Decimal

from ..canonical.catalogue import ElementKind, ErrorCorrection
from ..canonical.document import (
    BindingSource,
    DividerStyle,
    Frame,
    LabelLayout,
    LayoutElement,
    LiteralSource,
    QrStyle,
    TextStyle,
)
from ..canonical.geometry import AreaMm
from ..canonical.profiles import MM_PER_INCH, CapabilityProfile
from ..canonical.qr import symbol_for
from .sheet import (
    _INNER_INSET_MM,
    CLEARANCE_MM,
    CalibrationSheetUnavailable,
    _edge_scales,
    _quantized,
)

#: Bumped when any probe moves or changes what it prints. It names the sheet
#: a Release Evidence Record's measurements were read off.
EVIDENCE_SHEET_VERSION = "growspace.label-evidence-sheet.v1"

#: The prefix every element ID on this sheet carries.
EVIDENCE_PREFIX = "growspace.evidence"

#: The three QR targets, as the operator will read them back off a phone.
#: The first two are the two forms a real plant label's QR takes; the third is
#: padded to the profile's claimed maximum by `long_qr_target`.
SHORT_QR_TARGET = "homeassistant://navigate/growspace/plant/p1"
TYPICAL_QR_TARGET = (
    "http://homeassistant.local:8123/growspace/plant/01JB7Q9K3M4N5P6R7S8T9V0W1X"
)
#: What the longest target starts with. The rest is filler up to the claimed
#: maximum, and it ends with `#<bytes>`.
LONG_QR_PREFIX = "http://homeassistant.local:8123/growspace/evidence/qr-max/"

#: Lowercase letters, because they are what a real URL is mostly made of and
#: they force the renderer into byte mode. Digit filler would be packed in
#: numeric mode at less than half the bits, and the "longest" probe would be a
#: much smaller symbol than a real 256-byte URL.
_FILLER = "abcdefghijklmnopqrstuvwxyz"

#: Accented Latin a strain name really carries. Both faces the printer
#: integration ships draw every character here; a face that did not would
#: refuse this print with `raster.missing_glyph`, and that refusal would be
#: the evidence.
ACCENTED_PROBE = "Äöü éñ ç"

_HEADING_FONT = "growspace.sans.bold.v1"
_BODY_FONT = "growspace.sans.regular.v1"
_COMPACT = "growspace.spacing.compact.v1"

#: How much taller than its font size a probe line's frame is. The renderer
#: fits a line in its font's ascent plus descent plus the line spacing, which
#: is about 1.46 of the size for the bold face; a frame shorter than that
#: still draws one line, but silently refuses a second.
_LINE_HEIGHT_RATIO = 1.5

#: The margin a QR box is given past its exact dot count, so rounding its two
#: edges to device pixels can never take a dot away from it.
_QR_SLACK_MM = 0.1


@dataclass(frozen=True, slots=True)
class _QrProbe:
    """One QR target and the box it is measured in."""

    suffix: str
    target: str
    side_mm: float


@dataclass(frozen=True, slots=True)
class _TextProbe:
    """One line of text at one claimed size."""

    suffix: str
    value: str
    font: str
    size_mm: float
    maximum_lines: int = 1


def evidence_layout(
    profile: CapabilityProfile, *, density: str = "normal"
) -> LabelLayout:
    """Build the evidence label for one profile and density.

    Refused rather than shrunk where the probes do not fit: a sheet whose QR
    boxes were made smaller than the claimed minimum would be testing a
    different claim.
    """
    area = profile.printable_area
    inner = _inner(area)
    qr = _qr_probes(profile)
    widest = max(probe.side_mm for probe in qr[:2])
    longest = qr[2]

    needed_width = longest.side_mm + widest + 2 * CLEARANCE_MM
    if needed_width >= inner.width_mm:
        raise CalibrationSheetUnavailable(
            profile.id,
            f"its QR probes need {needed_width:.2f} mm across inside the edge "
            f"scales, which leave {inner.width_mm:.2f} mm.",
        )

    right = inner.x_mm + inner.width_mm
    long_x = right - longest.side_mm
    middle_x = long_x - CLEARANCE_MM - widest
    text_width = middle_x - CLEARANCE_MM - inner.x_mm

    elements = [
        *_edge_scales(area),
        *_qr_column(qr[:2], x_mm=middle_x, top_mm=inner.y_mm, profile=profile),
        _qr(longest, x_mm=long_x, y_mm=inner.y_mm, profile=profile),
        *_text_column(
            profile,
            AreaMm(inner.x_mm, inner.y_mm, text_width, inner.height_mm),
            density=density,
        ),
        *_identity(
            profile,
            AreaMm(
                long_x,
                inner.y_mm + longest.side_mm + CLEARANCE_MM,
                longest.side_mm,
                inner.height_mm - longest.side_mm - CLEARANCE_MM,
            ),
        ),
    ]
    _refuse_overflow(profile, inner, elements)
    return LabelLayout(label_size_id=profile.label_size_id, elements=tuple(elements))


def weakest_error_correction(profile: CapabilityProfile) -> str:
    """Return the lowest error correction the profile claims.

    It is the hardest to scan, and therefore the one the evidence has to prove.
    """
    claimed = set(profile.limits.qr_error_correction_levels)
    return next(str(level) for level in ErrorCorrection if str(level) in claimed)


def long_qr_target(maximum_bytes: int) -> str:
    """A target of exactly `maximum_bytes` bytes, ending with its own length.

    ASCII throughout, so bytes and characters are the same count and a phone
    showing the decoded text shows the length that was encoded.
    """
    suffix = f"#{maximum_bytes}"
    filler = maximum_bytes - len(LONG_QR_PREFIX) - len(suffix)
    if filler < 0:
        return LONG_QR_PREFIX[: maximum_bytes - len(suffix)] + suffix
    letters = "".join(_FILLER[index % len(_FILLER)] for index in range(filler))
    return f"{LONG_QR_PREFIX}{letters}{suffix}"


# ---------------------------------------------------------------------------
# Probes
# ---------------------------------------------------------------------------


def _qr_probes(profile: CapabilityProfile) -> tuple[_QrProbe, _QrProbe, _QrProbe]:
    """The three targets, each in a box of exactly the claimed minimum dots."""
    limits = profile.limits
    correction = weakest_error_correction(profile)

    def probe(suffix: str, target: str) -> _QrProbe:
        side = symbol_for(target, correction).side_modules(
            limits.qr_minimum_quiet_zone_modules
        )
        exact = Decimal(side * limits.qr_minimum_dots_per_module) * Decimal(
            str(MM_PER_INCH)
        ) / Decimal(profile.dpi) + Decimal(str(_QR_SLACK_MM))
        return _QrProbe(
            suffix,
            target,
            float(exact.quantize(Decimal("0.01"), rounding=ROUND_CEILING)),
        )

    return (
        probe("qr.short", SHORT_QR_TARGET),
        probe("qr.typical", TYPICAL_QR_TARGET),
        probe("qr.long", long_qr_target(limits.qr_maximum_encoded_bytes)),
    )


def _qr_column(
    probes: tuple[_QrProbe, ...],
    *,
    x_mm: float,
    top_mm: float,
    profile: CapabilityProfile,
) -> Iterator[LayoutElement]:
    """Stack the shorter targets in one column."""
    y = top_mm
    for probe in probes:
        yield _qr(probe, x_mm=x_mm, y_mm=y, profile=profile)
        y += probe.side_mm + CLEARANCE_MM


def _text_column(
    profile: CapabilityProfile, region: AreaMm, *, density: str
) -> Iterator[LayoutElement]:
    """Each claimed size in each face, then the rules, then the density.

    The density line is at the readable floor too, so it is one more probe
    as well as the thing that says which of the three prints this is.
    """
    limits = profile.limits
    floor = limits.text_readable_floor_mm
    comfort = limits.text_comfort_threshold_mm
    level = profile.density_level(density)
    probes = (
        _TextProbe("text.comfort.bold", f"Bold {comfort:g}", _HEADING_FONT, comfort),
        _TextProbe("text.comfort.regular", f"Mg {comfort:g} Ok", _BODY_FONT, comfort),
        _TextProbe("text.floor.bold", f"Bold {floor:g}", _HEADING_FONT, floor),
        _TextProbe("text.floor.regular", f"Hamburg {floor:g}", _BODY_FONT, floor),
        _TextProbe("text.floor.accented", ACCENTED_PROBE, _BODY_FONT, floor),
        _TextProbe(
            "text.floor.long",
            "Gelato Cake x Runtz Muffin Blueberry Haze Pheno 12",
            _BODY_FONT,
            floor,
            maximum_lines=2,
        ),
    )
    y = region.y_mm
    for probe in probes:
        height = _line_height(probe.size_mm) * probe.maximum_lines
        yield _text(
            probe.suffix,
            Frame(region.x_mm, y, region.width_mm, height),
            LiteralSource(probe.value),
            font=probe.font,
            size_mm=probe.size_mm,
            maximum_lines=probe.maximum_lines,
        )
        y += height

    thinnest = limits.divider_minimum_thickness_mm
    for suffix, thickness in (
        ("rule.minimum", thinnest),
        ("rule.double", 2 * thinnest),
    ):
        y += CLEARANCE_MM
        yield _divider(suffix, Frame(region.x_mm, y, region.width_mm, thickness))
        y += thickness

    yield _text(
        "identity.density",
        Frame(region.x_mm, y + CLEARANCE_MM, region.width_mm, _line_height(floor)),
        LiteralSource(f"{density} ({'unmapped' if level is None else level})"),
        font=_BODY_FONT,
        size_mm=floor,
    )


def _identity(profile: CapabilityProfile, region: AreaMm) -> Iterator[LayoutElement]:
    """Which profile this is a print of, and when, under the long QR."""
    floor = profile.limits.text_readable_floor_mm
    lines = (
        (
            "identity.profile",
            LiteralSource(profile.id.removeprefix("growspace.profile.")),
        ),
        ("identity.printed_on", BindingSource("print.date", {"date_style": "iso"})),
    )
    y = region.y_mm
    for suffix, content in lines:
        yield _text(
            suffix,
            Frame(region.x_mm, y, region.width_mm, _line_height(floor)),
            content,
            font=_BODY_FONT,
            size_mm=floor,
        )
        y += _line_height(floor)


def _line_height(size_mm: float) -> float:
    """The frame height one line of text at `size_mm` is given."""
    return size_mm * _LINE_HEIGHT_RATIO


def _refuse_overflow(
    profile: CapabilityProfile, inner: AreaMm, elements: list[LayoutElement]
) -> None:
    """Refuse a sheet whose probes run into the edge scales.

    The probes are sized from the profile's claims rather than chosen, so a
    profile with bigger claimed minimums or a smaller Printable Area can run
    out of room. Shrinking a probe to fit would test a different claim.
    """
    probes = [e for e in elements if e.id.startswith(f"{EVIDENCE_PREFIX}.")]
    bottom = max(element.frame.bottom_mm for element in probes)
    limit = inner.y_mm + inner.height_mm
    if bottom > limit + 1e-9:
        raise CalibrationSheetUnavailable(
            profile.id,
            f"its probes reach {bottom:.2f} mm and the edge scales begin at "
            f"{limit:.2f} mm.",
        )


# ---------------------------------------------------------------------------
# Elements
# ---------------------------------------------------------------------------


def _inner(area: AreaMm) -> AreaMm:
    """The Printable Area inside the edge scales."""
    return AreaMm(
        x_mm=area.x_mm + _INNER_INSET_MM,
        y_mm=area.y_mm + _INNER_INSET_MM,
        width_mm=area.width_mm - 2 * _INNER_INSET_MM,
        height_mm=area.height_mm - 2 * _INNER_INSET_MM,
    )


def _qr(
    probe: _QrProbe, *, x_mm: float, y_mm: float, profile: CapabilityProfile
) -> LayoutElement:
    """One QR probe at the weakest claimed correction and minimum quiet zone."""
    return LayoutElement(
        id=f"{EVIDENCE_PREFIX}.{probe.suffix}",
        kind=ElementKind.QR,
        frame=_quantized(Frame(x_mm, y_mm, probe.side_mm, probe.side_mm)),
        rotation=0,
        style=QrStyle(
            error_correction=weakest_error_correction(profile),
            quiet_zone_modules=profile.limits.qr_minimum_quiet_zone_modules,
        ),
        content=LiteralSource(probe.target),
    )


def _divider(suffix: str, frame: Frame) -> LayoutElement:
    """One rule probe."""
    return LayoutElement(
        id=f"{EVIDENCE_PREFIX}.{suffix}",
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
    maximum_lines: int = 1,
) -> LayoutElement:
    """One text probe, at exactly its size unless it says otherwise.

    A probe's size is the claim under test, so it does not shrink: text that
    does not fit is truncated with an ellipsis, and the truncation is itself
    part of what the long probe shows.
    """
    return LayoutElement(
        id=f"{EVIDENCE_PREFIX}.{suffix}",
        kind=ElementKind.TEXT,
        frame=_quantized(frame),
        rotation=0,
        style=TextStyle(
            font=font,
            font_size_mm=size_mm,
            horizontal_align="left",
            vertical_align="top",
            line_spacing=_COMPACT,
            overflow="ellipsis" if maximum_lines == 1 else "shrink_ellipsis",
            minimum_font_size_mm=size_mm,
            maximum_lines=maximum_lines,
        ),
        content=content,
    )
