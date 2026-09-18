"""[[Capability Profile]]: the printer, stock and calibration one render uses.

"203 dpi" is not a global property of this product. A profile names one
printer class, one resolution, one printhead width, one stock, one orientation,
one density range and one calibrated Printable Area -- and a render is against
a profile or it is against nothing. That is what lets the same saved
millimetre layout compile onto different hardware without being rewritten, and
what lets an incompatible combination fail by name instead of by clipping.

Evidence is part of the identity. A **provisional** profile has enough known
geometry to render and to produce a calibration label; it cannot authorize a
production print. Promotion to product-verified is a physical-evidence
decision recorded elsewhere, and it advances the capability generation rather
than editing this file in place.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .catalogue import LABEL_SIZES, LabelSize

#: Millimetres per inch, the one constant the whole compiler turns on.
MM_PER_INCH = 25.4


class ProfileEvidence(StrEnum):
    """How far a profile has been proven."""

    #: Geometry is known; no physical matrix has been run. Renders, does not
    #: authorize production printing.
    PROVISIONAL = "provisional"
    #: The physical matrix passed for this printer class, stock and
    #: orientation, and the evidence record was reviewed.
    PRODUCT_VERIFIED = "product_verified"


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

    @property
    def label_size(self) -> LabelSize:
        """The stock this profile is for."""
        return LABEL_SIZES[self.label_size_id]

    @property
    def authorizes_production(self) -> bool:
        """Whether a render against this profile may reach paper."""
        return self.evidence is ProfileEvidence.PRODUCT_VERIFIED

    def density_level(self, density: str) -> int | None:
        """Resolve a symbolic density to this printer's own scale."""
        return self.density_levels.get(density)


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
