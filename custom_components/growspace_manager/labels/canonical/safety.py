"""The print-safety policy: which compiled outcomes block, and which warn.

The compiler says where every element landed. This says whether that is safe
to print, against one [[Capability Profile]]'s calibrated limits, and it says
it in one vocabulary: an **error** names output that is known unsafe,
incompatible or unverifiable, and a **warning** names a printable outcome
that deserves a look.

The whole policy is a table, and it is the one the cross-repository
specification settled:

    ink outside the Printable Area .............................. error
    ink inside the Printable Area, outside the Safe Area ........ warning
    any other ink inside a Protected QR Area .................... error
    a QR clipped, or below its calibrated module floor .......... error
    a required element's ink completely occluded ................ error
    any other ink-to-ink overlap ................................ warning
    text below the calibrated readable floor .................... error
    text below the comfort threshold ............................ warning
    text truncated by clip, ellipsis or a failed shrink ......... warning
    text a shrink policy cannot fit at its own minimum ........... error
    a glyph the selected font does not have ..................... error
    an image below the calibrated effective resolution .......... warning
    an image, divider or logo that leaves no ink ................ warning
    a divider below the profile's reproducible thickness ........ warning

Three properties hold throughout. **Nothing is repaired**: no frame moves, no
font is substituted, no code is rescaled, no element is dropped to make a
raster come out. **Nothing is judged from a frame** where its ink is known:
the questions are asked of the pixels each element really lays down, so a
frame may cross the Safe Area as long as its text does not. And **nothing is
guessed**: a limit comes from the profile, an ink mask comes from the pinned
toolchain, and an element the backend could not measure says so instead of
being scored against an invented number.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..model import Divider, FittedText, Logo, QrCode
from .catalogue import REQUIRED_BINDING, ElementKind
from .compiler import PLACED, CompiledLabel, to_pixels
from .diagnostics import Diagnostic, Layer, Recovery, Severity
from .document import BindingSource, LabelLayout
from .fonts import FontLibrary
from .geometry import PixelFrame
from .ink import (
    ElementInk,
    InkBasis,
    element_ink,
    ink_pixels,
    occluded_pixels,
    omitted_ink,
    overlap_of,
    union_of,
)
from .profiles import CapabilityProfile

#: Bumped when the table above changes. A Render Context carries it, so a
#: result judged by an older policy cannot authorize a print under a newer one.
SAFETY_POLICY_VERSION = "growspace.label-safety.v1"


@dataclass(frozen=True, slots=True)
class OverlapPair:
    """Two elements whose ink coincides, and what that costs."""

    first_element_id: str
    second_element_id: str
    region: PixelFrame
    #: `qr_quiet_zone`, `required_content` or `ink`.
    kind: str
    severity: str

    def as_dict(self) -> dict[str, Any]:
        """Return the pair's wire form."""
        return {
            "first_element_id": self.first_element_id,
            "second_element_id": self.second_element_id,
            "region": self.region.as_dict(),
            "kind": self.kind,
            "severity": self.severity,
        }


@dataclass(frozen=True, slots=True)
class SafetyReport:
    """What one compiled label's ink is, and what the policy makes of it."""

    ink: tuple[ElementInk, ...]
    overlaps: tuple[OverlapPair, ...]
    diagnostics: tuple[Diagnostic, ...]
    #: Font files measured, to their content digests. The Render Context
    #: carries these, so a font update invalidates a cached raster.
    font_identity: Mapping[str, str] = field(default_factory=dict)


#: Ordinary ink-to-ink overlap.
OVERLAP_INK = "ink"
#: Ink inside a QR's matrix or quiet zone.
OVERLAP_QR_QUIET_ZONE = "qr_quiet_zone"
#: Ink over a required element.
OVERLAP_REQUIRED_CONTENT = "required_content"


def evaluate_safety(
    layout: LabelLayout,
    compiled: CompiledLabel,
    profile: CapabilityProfile,
    fonts: FontLibrary,
) -> SafetyReport:
    """Judge one compiled label against one profile's calibrated limits."""
    return _Evaluation(layout, compiled, profile, fonts).run()


class _Evaluation:
    """One safety pass, so the diagnostics of one render stay together."""

    def __init__(
        self,
        layout: LabelLayout,
        compiled: CompiledLabel,
        profile: CapabilityProfile,
        fonts: FontLibrary,
    ) -> None:
        """Prepare the raster's extent and the regions ink is judged against."""
        self._layout = layout
        self._compiled = compiled
        self._profile = profile
        self._fonts = fonts
        self._diagnostics: list[Diagnostic] = []
        self._canvas = compiled.plan.canvas
        self._printable = PixelFrame(0, 0, self._canvas.width, self._canvas.height)
        self._safe = self._safe_area_pixels()
        self._required = self._required_element_ids()

    # -- the pass ---------------------------------------------------------

    def run(self) -> SafetyReport:
        """Measure every placed element's ink, then apply the policy to it."""
        inks = self._measure()
        by_id = {ink.element_id: ink for ink in inks}

        for ink in inks:
            if ink.basis is InkBasis.NONE:
                continue
            self._regions(ink)
            self._variant(ink)

        overlaps = self._overlaps(inks)
        self._occlusion(inks, by_id)
        return SafetyReport(
            ink=tuple(inks),
            overlaps=tuple(overlaps),
            diagnostics=tuple(self._diagnostics),
            font_identity=self._font_identity(inks),
        )

    def _measure(self) -> list[ElementInk]:
        """Compute one ink record per stable element ID, in paint order."""
        frames = {
            outcome.element_id: outcome.pixel_frame
            for outcome in self._compiled.outcomes
        }
        inks: list[ElementInk] = []
        for outcome in self._compiled.outcomes:
            placed = self._compiled.placed.get(outcome.element_id)
            frame = frames.get(outcome.element_id)
            if outcome.status != PLACED or placed is None or frame is None:
                inks.append(omitted_ink(outcome.element_id, outcome.kind))
                continue
            inks.append(
                element_ink(
                    placed,
                    element_id=outcome.element_id,
                    kind=outcome.kind,
                    frame=frame,
                    canvas_width=self._canvas.width,
                    canvas_height=self._canvas.height,
                    dpi=self._profile.dpi,
                    fonts=self._fonts,
                )
            )
        return inks

    # -- regions ----------------------------------------------------------

    def _safe_area_pixels(self) -> PixelFrame:
        """The Safe Area, translated into the raster's own pixel grid."""
        area = self._profile.safe_area
        dpi = self._profile.dpi
        origin_x = to_pixels(self._profile.printable_origin_x_mm, dpi)
        origin_y = to_pixels(self._profile.printable_origin_y_mm, dpi)
        return PixelFrame(
            left=to_pixels(area.x_mm, dpi) - origin_x,
            top=to_pixels(area.y_mm, dpi) - origin_y,
            right=to_pixels(area.right_mm, dpi) - origin_x,
            bottom=to_pixels(area.bottom_mm, dpi) - origin_y,
        )

    def _regions(self, ink: ElementInk) -> None:
        """Judge one element's ink against the Printable and Safe Areas."""
        bounds = ink.bounds
        if bounds is None:
            return
        if not self._printable.contains(bounds):
            self._add(
                "profile.ink_outside_printable_area",
                Severity.ERROR,
                (
                    f"Element {ink.element_id} inks {bounds.as_dict()}, outside "
                    f"the {self._canvas.width}x{self._canvas.height}px "
                    "Printable Area."
                ),
                ink.element_id,
                {
                    "ink_bounds": bounds.as_dict(),
                    "printable_area": self._printable.as_dict(),
                },
                Recovery.EDIT_ELEMENT,
            )
            return
        if not self._safe.contains(bounds):
            self._add(
                "profile.ink_outside_safe_area",
                Severity.WARNING,
                (
                    f"Element {ink.element_id} inks outside the Safe Area. It "
                    "prints, but close to an edge."
                ),
                ink.element_id,
                {
                    "ink_bounds": bounds.as_dict(),
                    "safe_area": self._safe.as_dict(),
                    "safe_area_inset_mm": self._profile.safe_area_inset_mm,
                },
                Recovery.EDIT_ELEMENT,
            )

    # -- per variant ------------------------------------------------------

    def _variant(self, ink: ElementInk) -> None:
        """Apply the checks one element kind owns."""
        placed = self._compiled.placed.get(ink.element_id)
        if isinstance(placed, FittedText):
            self._text(ink, placed)
        elif isinstance(placed, QrCode):
            self._qr(ink, placed)
        elif isinstance(placed, Logo):
            self._logo(ink)
        elif isinstance(placed, Divider):
            self._divider(ink)

    def _text(self, ink: ElementInk, placed: FittedText) -> None:
        """Judge resolved size, glyph coverage and truncation."""
        limits = self._profile.limits
        measurements = ink.measurements
        if not measurements.get("measured"):
            self._add(
                "raster.text_unmeasured",
                Severity.WARNING,
                (
                    f"Font {placed.font} is not installed beside this "
                    "integration, so the text of element "
                    f"{ink.element_id} could not be measured. Its frame "
                    "stands in for its ink."
                ),
                ink.element_id,
                {"font_file": placed.font},
                Recovery.RETRY,
                layer=Layer.RASTER,
            )
            return

        missing = tuple(measurements.get("missing_glyphs", ()))
        if missing:
            self._add(
                "raster.missing_glyph",
                Severity.ERROR,
                (
                    f"Font {placed.font} has no glyph for "
                    f"{''.join(missing)!r}. Nothing is substituted."
                ),
                ink.element_id,
                {"font_file": placed.font, "characters": list(missing)},
                Recovery.EDIT_CONTENT,
                layer=Layer.RASTER,
            )

        size_mm = float(measurements.get("resolved_font_size_mm", 0.0))
        if size_mm < limits.text_readable_floor_mm:
            self._add(
                "profile.text_below_readable_floor",
                Severity.ERROR,
                (
                    f"Element {ink.element_id} resolved to {size_mm} mm, below "
                    f"the {limits.text_readable_floor_mm} mm this profile can "
                    "be read at."
                ),
                ink.element_id,
                {
                    "resolved_font_size_mm": size_mm,
                    "readable_floor_mm": limits.text_readable_floor_mm,
                },
                Recovery.EDIT_ELEMENT,
            )
        elif size_mm < limits.text_comfort_threshold_mm:
            self._add(
                "profile.text_below_comfort_threshold",
                Severity.WARNING,
                (
                    f"Element {ink.element_id} auto-fitted down to {size_mm} mm, "
                    f"under this profile's {limits.text_comfort_threshold_mm} mm "
                    "comfortable size."
                ),
                ink.element_id,
                {
                    "resolved_font_size_mm": size_mm,
                    "comfort_threshold_mm": limits.text_comfort_threshold_mm,
                },
                Recovery.EDIT_ELEMENT,
            )

        if placed.fit == "shrink" and not measurements.get("fitted_within_minimum"):
            self._add(
                "raster.text_does_not_fit",
                Severity.ERROR,
                (
                    f"Element {ink.element_id} does not fit its frame even at "
                    f"its {placed.min_size}px minimum, and its policy is to "
                    "shrink rather than truncate."
                ),
                ink.element_id,
                {
                    "minimum_font_size_px": placed.min_size,
                    "overflow": placed.fit,
                },
                Recovery.EDIT_ELEMENT,
                layer=Layer.RASTER,
            )
        elif measurements.get("truncated"):
            self._add(
                "raster.text_truncated",
                Severity.WARNING,
                (
                    f"Element {ink.element_id} does not fit its frame; its "
                    f"{placed.fit} policy dropped content."
                ),
                ink.element_id,
                {
                    "overflow": placed.fit,
                    "lines": list(measurements.get("lines", ())),
                },
                Recovery.EDIT_ELEMENT,
                layer=Layer.RASTER,
            )

    def _qr(self, ink: ElementInk, placed: QrCode) -> None:
        """Judge encodability, module scale, quiet zone and clipping."""
        limits = self._profile.limits
        measurements = ink.measurements
        encoded = int(measurements.get("encoded_bytes", 0))

        if not measurements.get("encodable", False):
            self._add(
                "raster.qr_not_encodable",
                Severity.ERROR,
                (
                    f"The target of element {ink.element_id} is {encoded} bytes, "
                    "which no QR version encodes at this correction level."
                ),
                ink.element_id,
                {"encoded_bytes": encoded},
                Recovery.EDIT_ELEMENT,
                layer=Layer.RASTER,
            )
            return

        if encoded > limits.qr_maximum_encoded_bytes:
            self._add(
                "profile.qr_target_too_long",
                Severity.ERROR,
                (
                    f"The target of element {ink.element_id} is {encoded} bytes; "
                    f"this profile is verified to {limits.qr_maximum_encoded_bytes}."
                ),
                ink.element_id,
                {
                    "encoded_bytes": encoded,
                    "maximum_encoded_bytes": limits.qr_maximum_encoded_bytes,
                },
                Recovery.EDIT_ELEMENT,
            )

        correction = str(measurements.get("error_correction", ""))
        if correction not in limits.qr_error_correction_levels:
            self._add(
                "profile.qr_error_correction_unsupported",
                Severity.ERROR,
                (
                    f"Element {ink.element_id} asks for {correction} error "
                    "correction, which this profile has no evidence for."
                ),
                ink.element_id,
                {
                    "error_correction": correction,
                    "supported": list(limits.qr_error_correction_levels),
                },
                Recovery.EDIT_ELEMENT,
            )

        quiet_zone = int(measurements.get("quiet_zone_modules", 0))
        if quiet_zone < limits.qr_minimum_quiet_zone_modules:
            self._add(
                "profile.qr_quiet_zone_too_small",
                Severity.ERROR,
                (
                    f"Element {ink.element_id} keeps {quiet_zone} quiet-zone "
                    f"modules; this profile needs "
                    f"{limits.qr_minimum_quiet_zone_modules}."
                ),
                ink.element_id,
                {
                    "quiet_zone_modules": quiet_zone,
                    "minimum_quiet_zone_modules": limits.qr_minimum_quiet_zone_modules,
                },
                Recovery.EDIT_ELEMENT,
            )

        dots = int(measurements.get("dots_per_module", 0))
        if dots < 1:
            self._add(
                "raster.qr_does_not_fit",
                Severity.ERROR,
                (
                    f"Element {ink.element_id} needs "
                    f"{measurements.get('side_modules')} modules but its box is "
                    f"{measurements.get('box_px')}px, so the renderer would "
                    "shrink it off its module grid."
                ),
                ink.element_id,
                {
                    "side_modules": measurements.get("side_modules"),
                    "box_px": measurements.get("box_px"),
                },
                Recovery.EDIT_ELEMENT,
                layer=Layer.RASTER,
            )
        elif dots < limits.qr_minimum_dots_per_module:
            self._add(
                "profile.qr_below_module_floor",
                Severity.ERROR,
                (
                    f"Element {ink.element_id} gives each module {dots} dots; "
                    f"this profile scans reliably at "
                    f"{limits.qr_minimum_dots_per_module}."
                ),
                ink.element_id,
                {
                    "dots_per_module": dots,
                    "minimum_dots_per_module": limits.qr_minimum_dots_per_module,
                },
                Recovery.EDIT_ELEMENT,
            )

    def _logo(self, ink: ElementInk) -> None:
        """Judge effective resolution, decode failure and blank output."""
        limits = self._profile.limits
        measurements = ink.measurements
        if not measurements.get("decoded"):
            code, message = (
                (
                    "raster.image_not_inspected",
                    "is served over HTTP, so it is fetched by the renderer "
                    "rather than measured here",
                )
                if measurements.get("remote")
                else (
                    "raster.image_undecodable",
                    "could not be decoded; the renderer will paint nothing there",
                )
            )
            self._add(
                code,
                Severity.WARNING,
                f"The image of element {ink.element_id} {message}.",
                ink.element_id,
                {"remote": bool(measurements.get("remote"))},
                Recovery.EDIT_CONTENT,
                layer=Layer.RASTER,
            )
            return

        effective = float(measurements.get("effective_dpi", 0.0))
        if effective < limits.image_minimum_effective_dpi:
            self._add(
                "profile.image_below_effective_resolution",
                Severity.WARNING,
                (
                    f"The image of element {ink.element_id} prints at "
                    f"{effective} effective dpi, below this profile's "
                    f"{limits.image_minimum_effective_dpi}."
                ),
                ink.element_id,
                {
                    "effective_dpi": effective,
                    "minimum_effective_dpi": limits.image_minimum_effective_dpi,
                },
                Recovery.EDIT_CONTENT,
            )

        if ink_pixels(ink) == 0:
            self._add(
                "raster.image_leaves_no_ink",
                Severity.WARNING,
                (
                    f"The image of element {ink.element_id} converts to no ink "
                    "at all, so its frame prints blank."
                ),
                ink.element_id,
                {},
                Recovery.EDIT_CONTENT,
                layer=Layer.RASTER,
            )

    def _divider(self, ink: ElementInk) -> None:
        """Judge whether a rule is thick enough for this printer to draw."""
        limits = self._profile.limits
        thickness = float(ink.measurements.get("thickness_mm", 0.0))
        if thickness < limits.divider_minimum_thickness_mm:
            self._add(
                "profile.divider_below_reproducible_thickness",
                Severity.WARNING,
                (
                    f"Element {ink.element_id} is {thickness} mm thick, under "
                    f"the {limits.divider_minimum_thickness_mm} mm this profile "
                    "reproduces."
                ),
                ink.element_id,
                {
                    "thickness_mm": thickness,
                    "minimum_thickness_mm": limits.divider_minimum_thickness_mm,
                },
                Recovery.EDIT_ELEMENT,
            )
        if ink_pixels(ink) == 0:
            self._add(
                "raster.divider_leaves_no_ink",
                Severity.WARNING,
                f"Element {ink.element_id} draws no ink at this resolution.",
                ink.element_id,
                {},
                Recovery.EDIT_ELEMENT,
                layer=Layer.RASTER,
            )

    # -- overlap and occlusion --------------------------------------------

    def _overlaps(self, inks: Sequence[ElementInk]) -> list[OverlapPair]:
        """Find every pair of elements whose ink coincides, and grade it."""
        pairs: list[OverlapPair] = []
        painted = [ink for ink in inks if ink.basis is not InkBasis.NONE]
        for index, first in enumerate(painted):
            for second in painted[index + 1 :]:
                region = overlap_of(first, second)
                if region is None:
                    continue
                pairs.append(self._graded(first, second, region))
        return pairs

    def _graded(
        self, first: ElementInk, second: ElementInk, region: PixelFrame
    ) -> OverlapPair:
        """Grade one overlapping pair, and record the diagnostic it earns."""
        protector = self._protecting(first, second, region)
        if protector is not None:
            other = second if protector is first else first
            self._add(
                "raster.qr_quiet_zone_violated",
                Severity.ERROR,
                (
                    f"Element {other.element_id} inks inside the protected area "
                    f"of QR {protector.element_id}, whichever is painted first."
                ),
                other.element_id,
                {
                    "qr_element_id": protector.element_id,
                    "region": region.as_dict(),
                },
                Recovery.EDIT_ELEMENT,
                layer=Layer.RASTER,
            )
            return OverlapPair(
                first_element_id=first.element_id,
                second_element_id=second.element_id,
                region=region,
                kind=OVERLAP_QR_QUIET_ZONE,
                severity=str(Severity.ERROR),
            )

        touches_required = bool(self._required & {first.element_id, second.element_id})
        self._add(
            "raster.ink_overlap",
            Severity.WARNING,
            (
                f"The ink of {first.element_id} and {second.element_id} overlaps. "
                "It prints in paint order."
            ),
            second.element_id,
            {
                "first_element_id": first.element_id,
                "second_element_id": second.element_id,
                "region": region.as_dict(),
                "required_content": touches_required,
            },
            Recovery.EDIT_ELEMENT,
            layer=Layer.RASTER,
        )
        return OverlapPair(
            first_element_id=first.element_id,
            second_element_id=second.element_id,
            region=region,
            kind=OVERLAP_REQUIRED_CONTENT if touches_required else OVERLAP_INK,
            severity=str(Severity.WARNING),
        )

    def _protecting(
        self, first: ElementInk, second: ElementInk, region: PixelFrame
    ) -> ElementInk | None:
        """Return whichever of a pair owns a Protected QR Area the other enters."""
        for candidate, other in ((first, second), (second, first)):
            if candidate.protected is None or other.protected is not None:
                continue
            if candidate.protected.intersection(region) is not None:
                return candidate
        return None

    def _occlusion(
        self, inks: Sequence[ElementInk], by_id: Mapping[str, ElementInk]
    ) -> None:
        """Refuse a label whose required content is painted over completely."""
        order = [ink.element_id for ink in inks]
        for element_id in self._required:
            ink = by_id.get(element_id)
            if ink is None or ink.basis is InkBasis.NONE or ink.mask is None:
                continue
            total = ink_pixels(ink)
            if total == 0:
                continue
            later = [
                other.mask
                for other in inks
                if other.mask is not None
                and other.element_id != element_id
                and order.index(other.element_id) > order.index(element_id)
            ]
            covering = union_of(later)
            if occluded_pixels(ink, covering) < total:
                continue
            self._add(
                "raster.required_content_occluded",
                Severity.ERROR,
                (
                    f"Every inked pixel of required element {element_id} is "
                    "painted over by something drawn after it."
                ),
                element_id,
                {"required_binding": REQUIRED_BINDING},
                Recovery.EDIT_ELEMENT,
                layer=Layer.RASTER,
            )

    def _required_element_ids(self) -> frozenset[str]:
        """The stable IDs of the elements a label may not print without."""
        return frozenset(
            element.id
            for element in self._layout.elements
            if element.kind is ElementKind.TEXT
            and isinstance(element.content, BindingSource)
            and element.content.binding == REQUIRED_BINDING
        )

    # -- odds and ends ----------------------------------------------------

    def _font_identity(self, inks: Sequence[ElementInk]) -> Mapping[str, str]:
        """The digests of the font files this render really measured."""
        identity: dict[str, str] = {}
        for ink in inks:
            file = ink.measurements.get("font_file")
            if isinstance(file, str):
                identity[file] = str(ink.measurements.get("font_digest", "unresolved"))
        return dict(sorted(identity.items()))

    def _add(
        self,
        code: str,
        severity: Severity,
        message: str,
        element_id: str | None,
        parameters: Mapping[str, Any],
        recovery: Recovery,
        *,
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
                parameters=dict(parameters),
                recovery=recovery,
            )
        )
