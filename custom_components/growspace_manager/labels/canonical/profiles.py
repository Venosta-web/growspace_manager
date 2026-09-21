"""[[Capability Profile]]: the printer, stock and calibration one render uses.

"203 dpi" is not a global property of this product. A profile names one
printer class, one resolution, one printhead width, one stock, one
orientation, one density range, one calibrated Printable Area and the limits
below which its output stops being readable -- and a render is against a
profile or it is against nothing. That is what lets the same saved millimetre
layout compile onto different hardware without being rewritten, and what lets
an incompatible combination fail by name instead of by clipping.

Three nested regions, all in the stock's own unrotated millimetres:

    stock area      the physical label
    Printable Area  where this printer can put ink without mechanical clipping
    Safe Area       the more conservative inset inside it

Ink outside the stock or the Printable Area is an error; ink between the
Printable Area and the Safe Area is a warning. The profile declares the
regions; it never moves anything into them.

Evidence is part of the identity, and it is the identity that decides what a
render may authorize. A **provisional** profile has enough known geometry to
render and to produce a calibration label; its calibrated limits are declared
rather than measured, and it cannot authorize a production print. Promotion to
product-verified is a physical-evidence decision recorded elsewhere, and it
advances the capability generation rather than editing this file in place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .catalogue import LABEL_SIZES, LabelSize
from .geometry import AreaMm

#: Millimetres per inch, the one constant the whole compiler turns on.
MM_PER_INCH = 25.4

PROFILE_CATALOGUE_VERSION = "growspace.label-profiles.v1"


class ProfileEvidence(StrEnum):
    """How far a profile has been proven."""

    #: Geometry is known; no physical matrix has been run. Renders, does not
    #: authorize production printing.
    PROVISIONAL = "provisional"
    #: The physical matrix passed for this printer class, stock and
    #: orientation, and the evidence record was reviewed.
    PRODUCT_VERIFIED = "product_verified"


class StockOrientation(StrEnum):
    """How the stock is mounted, which the profile owns and a layout does not."""

    PORTRAIT = "portrait"
    LANDSCAPE = "landscape"


class FeedAxis(StrEnum):
    """Which of the stock's own axes the media travels along.

    Declared rather than derived, because "feed alignment" is a measurement
    in one direction and there is no way to know which one from the stock's
    dimensions: a 50x30 label can be fed either way round depending on how the
    roll was slit. It is part of a calibration's identity for the same reason
    -- a printer re-loaded with the roll turned is not the printer that was
    measured.
    """

    #: Along the stock's width, in its own unrotated coordinate system.
    X = "x"
    #: Along the stock's height.
    Y = "y"


@dataclass(frozen=True, slots=True)
class CalibratedLimits:
    """The thresholds below which this combination stops being readable.

    Every number here is an output of the physical evidence matrix, which is
    why a profile carries its own rather than deriving one from DPI. A
    provisional profile still carries them -- a render has to be judged
    against something -- but `measured` is false and the profile cannot
    authorize production, so no unverified number is ever the last thing
    between a layout and paper.
    """

    #: Resolved text below this height is unreadable: an error.
    text_readable_floor_mm: float
    #: Resolved text below this height is legible but tight: a warning.
    text_comfort_threshold_mm: float
    #: Device dots each QR module must get.
    qr_minimum_dots_per_module: int
    #: Quiet-zone modules this printer class needs on every side.
    qr_minimum_quiet_zone_modules: int
    #: The longest target verified to scan.
    qr_maximum_encoded_bytes: int
    #: Error-correction levels the evidence covers.
    qr_error_correction_levels: tuple[str, ...]
    #: Source pixels per printed inch, below which an image is mush.
    image_minimum_effective_dpi: float
    #: The thinnest rule this printer reproduces.
    divider_minimum_thickness_mm: float
    #: Whether these numbers come from recorded physical tests.
    measured: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return the limits' wire form."""
        return {
            "text_readable_floor_mm": self.text_readable_floor_mm,
            "text_comfort_threshold_mm": self.text_comfort_threshold_mm,
            "qr_minimum_dots_per_module": self.qr_minimum_dots_per_module,
            "qr_minimum_quiet_zone_modules": self.qr_minimum_quiet_zone_modules,
            "qr_maximum_encoded_bytes": self.qr_maximum_encoded_bytes,
            "qr_error_correction_levels": list(self.qr_error_correction_levels),
            "image_minimum_effective_dpi": self.image_minimum_effective_dpi,
            "divider_minimum_thickness_mm": self.divider_minimum_thickness_mm,
            "measured": self.measured,
        }


@dataclass(frozen=True, slots=True)
class CapabilityProfile:
    """One immutable printer/stock/orientation contract.

    The Printable Area is expressed in the stock's own millimetre coordinate
    system, so a layout never has to know it exists: the compiler translates,
    and geometry that falls outside is diagnosed rather than moved.
    """

    id: str
    printer_class: str
    label_size_id: str
    dpi: int
    #: The transport's hard per-row limit. A raster wider than this must never
    #: reach the driver, which does not reject it.
    printhead_pixels: int
    printable_origin_x_mm: float
    printable_origin_y_mm: float
    printable_width_mm: float
    printable_height_mm: float
    #: The recommended inset inside the Printable Area.
    safe_area_inset_mm: float
    #: Symbolic density to this printer class's own valid integer range.
    density_levels: Mapping[str, int]
    evidence: ProfileEvidence
    limits: CalibratedLimits
    #: How the stock is mounted. Whole-stock orientation is the profile's;
    #: element rotation is the layout's.
    orientation: StockOrientation = StockOrientation.LANDSCAPE
    #: The axis the media travels along, which is the axis feed alignment is
    #: measured in.
    feed_axis: FeedAxis = FeedAxis.X
    #: Clockwise element rotations this profile and the compiler both realise.
    #: An angle outside this set is refused by name, never mapped to a
    #: neighbour.
    supported_element_rotations: tuple[int, ...] = (0,)
    #: When the physical matrix was recorded, for a verified profile.
    evidence_recorded_at: str | None = None
    #: Where that record lives.
    evidence_reference: str | None = None
    #: Why an earlier evidence state was withdrawn, where one was.
    evidence_invalidated_by: tuple[str, ...] = field(default_factory=tuple)

    @property
    def label_size(self) -> LabelSize:
        """The stock this profile is for."""
        return LABEL_SIZES[self.label_size_id]

    @property
    def stock_area(self) -> AreaMm:
        """The physical label, in its own millimetres."""
        size = self.label_size
        return AreaMm(0.0, 0.0, size.width_mm, size.height_mm)

    @property
    def printable_area(self) -> AreaMm:
        """Where this printer can place ink without mechanical clipping."""
        return AreaMm(
            self.printable_origin_x_mm,
            self.printable_origin_y_mm,
            self.printable_width_mm,
            self.printable_height_mm,
        )

    @property
    def safe_area(self) -> AreaMm:
        """The recommended inset inside the Printable Area."""
        return self.printable_area.inset_by(self.safe_area_inset_mm)

    @property
    def authorizes_production(self) -> bool:
        """Whether a render against this profile may reach paper."""
        return self.evidence is ProfileEvidence.PRODUCT_VERIFIED

    def density_level(self, density: str) -> int | None:
        """Resolve a symbolic density to this printer's own scale."""
        return self.density_levels.get(density)

    def supports_rotation(self, degrees: int) -> bool:
        """Whether this profile realises one element rotation."""
        return degrees in self.supported_element_rotations

    def as_dict(self) -> dict[str, Any]:
        """Return the profile's wire form, regions and limits included."""
        return {
            "id": self.id,
            "printer_class": self.printer_class,
            "label_size_id": self.label_size_id,
            "dpi": self.dpi,
            "printhead_pixels": self.printhead_pixels,
            "orientation": str(self.orientation),
            "feed_axis": str(self.feed_axis),
            "stock_area": self.stock_area.as_dict(),
            "printable_area": self.printable_area.as_dict(),
            "safe_area": self.safe_area.as_dict(),
            "density_levels": dict(self.density_levels),
            "supported_element_rotations": list(self.supported_element_rotations),
            "evidence": str(self.evidence),
            "evidence_recorded_at": self.evidence_recorded_at,
            "evidence_reference": self.evidence_reference,
            "evidence_invalidated_by": list(self.evidence_invalidated_by),
            "authorizes_production": self.authorizes_production,
            "limits": self.limits.as_dict(),
        }


#: The B1's declared limits. Every one of them is a starting point taken from
#: the symbology, the upstream device table or this printhead's own geometry
#: -- not from a print anyone measured, which is exactly why `measured` is
#: false and the profile carrying them is provisional.
#:
#: Two of them are worth saying out loud. The quiet zone is four modules
#: because that is what ISO/IEC 18004 requires, not because anyone here
#: chose it; it is the one number a physical matrix cannot lower. And two
#: dots per module is this printhead's floor rather than a preference: 203
#: dpi over a 12 mm code gives a typical plant URL exactly two, so a higher
#: declared minimum would not be strict, it would make a QR impossible on
#: 50x30 stock while claiming to be about readability.
NIIMBOT_B1_DECLARED_LIMITS = CalibratedLimits(
    text_readable_floor_mm=1.6,
    text_comfort_threshold_mm=2.2,
    qr_minimum_dots_per_module=2,
    qr_minimum_quiet_zone_modules=4,
    qr_maximum_encoded_bytes=256,
    qr_error_correction_levels=("medium", "quartile", "high"),
    image_minimum_effective_dpi=203.0,
    divider_minimum_thickness_mm=0.25,
    measured=False,
)

#: The first profile, and deliberately provisional: a Niimbot B1 at 203 dpi on
#: 50x30 mm stock. Its numbers come from the upstream device table rather than
#: from a measured print, which is exactly why it cannot authorize one.
#:
#: The Printable Area is 48 mm, not the stock's 50: the B1's printhead is 384
#: pixels, and 384 pixels at 203 dpi is 48.05 mm. Compiling onto the stock's
#: full width would build a 400-pixel raster for a 384-pixel head -- which the
#: upstream transport does not reject, and which no preview would reveal.
NIIMBOT_B1_50X30 = CapabilityProfile(
    id="growspace.profile.niimbot-b1.50x30.v1",
    printer_class="niimbot.b1",
    label_size_id="growspace.stock.50x30.v1",
    dpi=203,
    printhead_pixels=384,
    printable_origin_x_mm=0.0,
    printable_origin_y_mm=0.0,
    printable_width_mm=48.0,
    printable_height_mm=30.0,
    safe_area_inset_mm=1.0,
    # The B1 accepts 1-5. The Classic path's global 3/5/8 is invalid here at
    # its top value, which is the kind of thing a profile exists to stop.
    density_levels={"low": 2, "normal": 3, "high": 5},
    evidence=ProfileEvidence.PROVISIONAL,
    limits=NIIMBOT_B1_DECLARED_LIMITS,
    orientation=StockOrientation.LANDSCAPE,
    # The printhead is the 384-dot line across the stock's 50 mm axis, so the
    # media advances along the other one. That is the same fact the printhead
    # width above is: a head spanning x cannot also be the direction paper
    # moves in. It is declared rather than derived because a roll slit the
    # other way round would keep every number here and change this one.
    feed_axis=FeedAxis.Y,
    # The renderer expresses element rotation through a rotating group whose
    # anchoring no golden render has pinned yet. Zero is what this compiler
    # realises, so zero is what the profile admits.
    supported_element_rotations=(0,),
)

PROFILES: Mapping[str, CapabilityProfile] = {
    NIIMBOT_B1_50X30.id: NIIMBOT_B1_50X30,
}


def profiles_for_size(label_size_id: str) -> tuple[CapabilityProfile, ...]:
    """Return every profile that can render one stock."""
    return tuple(
        profile
        for profile in PROFILES.values()
        if profile.label_size_id == label_size_id
    )


def profile_by_id(profile_id: str) -> CapabilityProfile | None:
    """Return one shipped profile by identity, whatever stock it is for."""
    return PROFILES.get(profile_id)


def select_profile(
    label_size_id: str, profile_id: str | None = None
) -> CapabilityProfile | None:
    """Return the profile one request selected for one stock, or nothing.

    No selection means the first profile that can render the stock, which is
    what every preview did before a client could choose. A selection naming a
    profile of another stock is not a profile for this one, however valid it
    is elsewhere: answering with it would compile the layout onto paper it was
    not drawn for.
    """
    candidates = profiles_for_size(label_size_id)
    if profile_id is None:
        return candidates[0] if candidates else None
    return next((profile for profile in candidates if profile.id == profile_id), None)
