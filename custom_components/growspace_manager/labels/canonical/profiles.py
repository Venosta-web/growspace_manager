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
product-verified is a physical-evidence decision, and it advances the
capability generation rather than editing this file in place.

`evidence` is a profile's *claim*. The claim of product-verified is honoured
only with a complete, current [[Release Evidence Record]] attached (see
`evidence.py`); without one the profile is advertised, judged and refused as
provisional, with the reasons in `evidence_invalidated_by`.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from .canonicalization import digest
from .catalogue import LABEL_SIZES, LabelSize
from .evidence import (
    EVIDENCE_PROCEDURE_VERSION,
    DimensionResult,
    EvidenceDimension,
    ReleaseEvidenceRecord,
    evidence_problems,
)
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
    #: The physical proof behind a product-verified claim.
    evidence_record: ReleaseEvidenceRecord | None = None
    #: The printer models, as the printer integration reports them to Home
    #: Assistant's device registry, that were physically tested on this
    #: profile. Evidence does not transfer between models however alike
    #: their datasheets are, so a production print to any other device is
    #: refused. Empty means no model has been tested.
    device_models: tuple[str, ...] = ()

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
    def definition_digest(self) -> str:
        """The identity of what was measured: everything but the evidence.

        A Release Evidence Record names this, so moving an edge, a density
        level or a limit after the prints were made invalidates them.
        """
        return digest({**self._definition(), "device_models": list(self.device_models)})

    @property
    def evidence_problems(self) -> tuple[str, ...]:
        """Why a product-verified claim is not honoured; empty when it is."""
        if self.evidence is not ProfileEvidence.PRODUCT_VERIFIED:
            return ()
        return evidence_problems(
            self.evidence_record,
            profile_id=self.id,
            profile_definition=self.definition_digest,
            rotations=self.supported_element_rotations,
            densities=self.density_levels,
        )

    @property
    def effective_evidence(self) -> ProfileEvidence:
        """The evidence state the product acts on and advertises."""
        if self.evidence is ProfileEvidence.PRODUCT_VERIFIED and (
            not self.evidence_problems
        ):
            return ProfileEvidence.PRODUCT_VERIFIED
        return ProfileEvidence.PROVISIONAL

    @property
    def authorizes_production(self) -> bool:
        """Whether a render against this profile may reach paper."""
        return self.effective_evidence is ProfileEvidence.PRODUCT_VERIFIED

    def covers_device_model(self, model: str | None) -> bool:
        """Whether a printer of this model is one the evidence was taken on."""
        return model is not None and model in self.device_models

    def density_level(self, density: str) -> int | None:
        """Resolve a symbolic density to this printer's own scale."""
        return self.density_levels.get(density)

    def supports_rotation(self, degrees: int) -> bool:
        """Whether this profile realises one element rotation."""
        return degrees in self.supported_element_rotations

    def _definition(self) -> dict[str, Any]:
        """The wire form of everything a physical print measured."""
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
            "limits": self.limits.as_dict(),
        }

    def as_dict(self) -> dict[str, Any]:
        """Return the profile's wire form, regions and limits included.

        The evidence advertised is the effective one. An unproven claim is
        sent as provisional, with the claim's problems listed as the reasons
        it was withdrawn, so no client can read authority the profile lacks.
        """
        certified = self.effective_evidence is ProfileEvidence.PRODUCT_VERIFIED
        record = self.evidence_record if certified else None
        return {
            **self._definition(),
            "evidence": str(self.effective_evidence),
            "evidence_recorded_at": (
                record.recorded_on if record else self.evidence_recorded_at
            ),
            "evidence_reference": (
                record.reference if record else self.evidence_reference
            ),
            "evidence_invalidated_by": [
                *self.evidence_invalidated_by,
                *self.evidence_problems,
            ],
            "authorizes_production": self.authorizes_production,
        }


#: The B1's limits, as the physical evidence matrix measured them on
#: 2026-09-22 (see `NIIMBOT_B1_50X30_EVIDENCE`).
#:
#: Text is the one limit the matrix moved. The declared 1.6 mm floor came from
#: nowhere in particular, and on paper the regular face at 1.6 mm was
#: unreadable at every density while bold at 1.6 mm was not. A profile has one
#: floor for both faces, so it is the smaller of the two sizes that read in
#: both: 2.2 mm. Nothing between 1.6 and 2.2 was printed, so the floor is the
#: tested size rather than an interpolated one, and the comfort threshold sits
#: on it because no size was shown to be readable-but-tight.
#:
#: The QR numbers held. The quiet zone is four modules because ISO/IEC 18004
#: requires it, and two dots per module is this printhead's floor -- 203 dpi
#: over a 12 mm code gives a typical plant URL exactly two -- and all three
#: targets, the 256-byte one included, scanned at two dots per module on every
#: density. Only `medium` correction was printed; `quartile` and `high` keep the
#: same module size and add redundancy, so they are kept rather than narrowed,
#: and the record says so.
NIIMBOT_B1_MEASURED_LIMITS = CalibratedLimits(
    text_readable_floor_mm=2.2,
    text_comfort_threshold_mm=2.2,
    qr_minimum_dots_per_module=2,
    qr_minimum_quiet_zone_modules=4,
    qr_maximum_encoded_bytes=256,
    qr_error_correction_levels=("medium", "quartile", "high"),
    image_minimum_effective_dpi=203.0,
    divider_minimum_thickness_mm=0.25,
    measured=True,
)

#: Where the B1 record, its run log and its photograph are kept.
_B1_EVIDENCE = "docs/evidence/labels/niimbot-b1.50x30.v1/2026-09-22"
_B1_STRIP = f"{_B1_EVIDENCE}/strip.jpg"
_B1_RUN = f"{_B1_EVIDENCE}/run.json"

#: The physical proof behind the B1 profile: fifteen evidence labels, five at
#: each density, on a Niimbot B1 at firmware 5.22 (hardware 5.1), read by the
#: operator on 2026-09-22.
#:
#: `profile_definition` and `dependencies` are literals on purpose. They are
#: what the prints were made with, so moving an edge, a limit or a density
#: mapping, or shipping another compiler, renderer, font toolchain, QR model or
#: safety policy, stops matching them -- and the profile falls back to
#: provisional by name instead of carrying this record over a change nobody
#: printed.
NIIMBOT_B1_50X30_EVIDENCE = ReleaseEvidenceRecord(
    reference=_B1_EVIDENCE,
    profile_id="growspace.profile.niimbot-b1.50x30.v1",
    profile_definition=(
        "sha256:4c0430d3d9a240020d544741ac974905e10ebbb292c8a646e2554268583f8f91"
    ),
    printer_model="B1",
    firmware="5.22",
    driver="niimbot (Home Assistant integration) via growspace.niimbot-adapter.v1",
    stock="growspace.stock.50x30.v1",
    procedure=EVIDENCE_PROCEDURE_VERSION,
    operator="Venosta-web",
    reviewed_by="Venosta-web",
    recorded_on="2026-09-22",
    dependencies={
        "compiler": "growspace.label-compiler.v1",
        "renderer": "growspace.label-renderer.v1",
        "adapter": "growspace.niimbot-adapter.v1",
        "text_toolchain": "growspace.text-toolchain.v1",
        "style_tokens": "growspace.label-style-tokens.v1",
        "qr_model": "growspace.qr-model.v1",
        "safety_policy": "growspace.label-safety.v1",
    },
    results={
        EvidenceDimension.EDGES: DimensionResult(
            passed=True,
            measurements={
                "ticks_printed_of_five": {"top": 3, "right": 5, "bottom": 5, "left": 5},
                "top_reach_mm": 1.0,
                "copies": 15,
                "inside_safe_area": True,
            },
            artifacts=(_B1_STRIP, _B1_RUN),
        ),
        EvidenceDimension.ROTATION: DimensionResult(
            passed=True,
            measurements={"element_rotation_deg": 0, "orientation": "landscape"},
            artifacts=(_B1_STRIP,),
            covers=("0",),
        ),
        EvidenceDimension.TEXT: DimensionResult(
            passed=True,
            measurements={
                "readable_mm": {"bold": [1.6, 2.2], "regular": [2.2]},
                "unreadable_mm": {"regular": [1.6]},
                "accented_at_1_6_mm": "unreadable",
                "adopted_floor_mm": 2.2,
            },
            artifacts=(_B1_STRIP, _B1_RUN),
        ),
        EvidenceDimension.QR: DimensionResult(
            passed=True,
            measurements={
                "phone": "Google Pixel 9",
                "targets_bytes": [43, 74, 256],
                "error_correction": "medium",
                "dots_per_module": 2,
                "quiet_zone_modules": 4,
                "decoded": "all, at every density",
            },
            artifacts=(_B1_STRIP, _B1_RUN),
        ),
        EvidenceDimension.LOGO: DimensionResult(
            passed=True,
            measurements={"threshold": "readable", "dither": "readable"},
            artifacts=(_B1_RUN,),
        ),
        EvidenceDimension.DENSITY: DimensionResult(
            passed=True,
            measurements={"device_levels": {"low": 2, "normal": 3, "high": 5}},
            artifacts=(_B1_STRIP, _B1_RUN),
            covers=("low", "normal", "high"),
        ),
        EvidenceDimension.REPEATABILITY: DimensionResult(
            passed=True,
            measurements={
                "copies_per_density": 5,
                "tick_counts_identical": True,
                "raster_input_digests_per_density": 1,
            },
            artifacts=(_B1_STRIP, _B1_RUN),
        ),
        EvidenceDimension.BATCH: DimensionResult(
            passed=True,
            measurements={"skipped": 0, "doubled": 0, "misaligned": 0},
            artifacts=(_B1_RUN,),
        ),
    },
    deviations=(
        "Top edge: the first 1.0 mm of the declared Printable Area did not print on "
        "any copy; accepted because it lies outside the 1.0 mm Safe Area inset.",
        "Text floor raised from the declared 1.6 mm to 2.2 mm: regular 1.6 mm was "
        "unreadable at every density.",
        "QR: only medium correction was printed; quartile and high are kept at the "
        "same module size.",
        "Logo and batch rows rest on the operator's attestation in run.json; no "
        "photograph was retained for either.",
    ),
)

#: The first profile: a Niimbot B1 at 203 dpi on 50x30 mm stock, promoted to
#: product-verified by `NIIMBOT_B1_50X30_EVIDENCE`. It claims only that exact
#: combination; a B21, a B1 Pro or any other stock proves itself separately.
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
    evidence=ProfileEvidence.PRODUCT_VERIFIED,
    limits=NIIMBOT_B1_MEASURED_LIMITS,
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
    evidence_record=NIIMBOT_B1_50X30_EVIDENCE,
    # The model string the niimbot integration registers the tested printer
    # under. A B21 shares the printhead and the resolution and is still not
    # this evidence.
    device_models=("B1",),
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
