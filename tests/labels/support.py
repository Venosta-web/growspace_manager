"""Shared scaffolding for the print-safety suites (hub issue #216).

Two things every one of them needs, and neither belongs in a test file.

The first is a font. The faces the renderer uses belong to the `niimbot`
integration and are not installable here, so measuring anything with them in
CI is not on the table -- and a suite that therefore skipped text measurement
would leave the readable floor, truncation and glyph rules unproven. Pillow
ships a real TrueType face of its own, so the suites measure with that: the
numbers are not the printer's, but the algorithm, the policy and the wiring
are exactly the product's, and a font is resolved through the same seam
production resolves one through.

The second is a layout. Building a document element by element and pushing it
through the real validator keeps the fixtures honest -- a test cannot assert
on a layout the product would refuse to save.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Any

from PIL import ImageFont

from custom_components.growspace_manager.labels.canonical import (
    CompiledLabel,
    LabelLayout,
    MeasuredFont,
    compile_layout,
    validate_document,
)
from custom_components.growspace_manager.labels.canonical.content import (
    LabelContentSnapshot,
)
from custom_components.growspace_manager.labels.canonical.evidence import (
    EVIDENCE_PROCEDURE_VERSION,
    DimensionResult,
    EvidenceDimension,
    ReleaseEvidenceRecord,
    current_dependencies,
)
from custom_components.growspace_manager.labels.canonical.profiles import (
    CapabilityProfile,
    ProfileEvidence,
)
from custom_components.growspace_manager.labels.canonical.safety import (
    SafetyReport,
    evaluate_safety,
)

#: What `digest` answers for the face below. A constant rather than a real
#: content hash, because the point of the identity is that it changes when the
#: bytes do, not what it happens to be here.
STUB_FONT_DIGEST = "pillow-default"


class StubFonts:
    """A [[Font Library]] backed by the face Pillow bundles."""

    def load(self, file: str, size: int) -> MeasuredFont:
        """Return the bundled face at `size`, whatever file was asked for."""
        return MeasuredFont(
            file=file,
            size=max(size, 1),
            digest=STUB_FONT_DIGEST,
            face=ImageFont.load_default(size=max(size, 1)),
        )

    def digest(self, file: str) -> str:
        """Return this library's one identity."""
        return STUB_FONT_DIGEST


class NoFonts:
    """A library that resolves nothing, the way an installation without the
    printer integration's fonts does."""

    def load(self, file: str, size: int) -> MeasuredFont | None:
        """Resolve nothing, and never substitute a similar face."""
        return None

    def digest(self, file: str) -> str:
        """Report that there are no bytes to identify."""
        return "unresolved"


def text_element(
    element_id: str,
    frame: Mapping[str, float],
    *,
    binding: str | None = None,
    literal: str | None = None,
    font: str = "growspace.sans.regular.v1",
    size_mm: float = 3.2,
    minimum_mm: float = 2.2,
    overflow: str = "shrink_ellipsis",
    maximum_lines: int = 1,
    align: str = "left",
    valign: str = "top",
) -> dict[str, Any]:
    """Spell one text element of a candidate document."""
    content: dict[str, Any] = (
        {"binding": binding, "parameters": {}}
        if binding is not None
        else {"literal": literal or "Text"}
    )
    return {
        "id": element_id,
        "kind": "text",
        "frame": dict(frame),
        "rotation": 0,
        "content": content,
        "style": {
            "font": font,
            "font_size_mm": size_mm,
            "horizontal_align": align,
            "vertical_align": valign,
            "line_spacing": "growspace.spacing.compact.v1",
            "overflow": overflow,
            "minimum_font_size_mm": minimum_mm,
            "maximum_lines": maximum_lines,
        },
    }


def qr_element(
    element_id: str,
    frame: Mapping[str, float],
    *,
    literal: str = "https://example.invalid/p/1",
    error_correction: str = "medium",
    quiet_zone_modules: int = 4,
) -> dict[str, Any]:
    """Spell one QR element of a candidate document."""
    return {
        "id": element_id,
        "kind": "qr",
        "frame": dict(frame),
        "rotation": 0,
        "content": {"literal": literal},
        "style": {
            "error_correction": error_correction,
            "quiet_zone_modules": quiet_zone_modules,
        },
    }


def logo_element(
    element_id: str,
    frame: Mapping[str, float],
    *,
    asset: str | None = None,
    binding: str | None = "strain.breeder.logo",
    monochrome: str = "growspace.mono.threshold.v1",
) -> dict[str, Any]:
    """Spell one logo element of a candidate document."""
    content: dict[str, Any] = (
        {"asset_id": asset}
        if asset is not None
        else {"binding": binding, "parameters": {}}
    )
    return {
        "id": element_id,
        "kind": "logo",
        "frame": dict(frame),
        "rotation": 0,
        "content": content,
        "style": {"monochrome": monochrome, "fit": "contain"},
    }


def divider_element(element_id: str, frame: Mapping[str, float]) -> dict[str, Any]:
    """Spell one divider element of a candidate document."""
    return {
        "id": element_id,
        "kind": "divider",
        "frame": dict(frame),
        "rotation": 0,
        "style": {"fill": "black"},
    }


#: Where `layout_of` puts the required strain name when a fixture does not
#: carry one of its own: bottom-left, out of the way of the region every other
#: fixture element uses, so adding it never creates an overlap a test did not
#: ask for.
REQUIRED_NAME_FRAME = {
    "x_mm": 1.0,
    "y_mm": 25.0,
    "width_mm": 18.0,
    "height_mm": 4.0,
}


def layout_of(*elements: Mapping[str, Any]) -> LabelLayout:
    """Validate a candidate document, refusing to build an invalid fixture.

    A publishable layout must carry the required strain name, so one is added
    when a fixture is about something else. Leaving it out would test the
    validator's refusal rather than whatever the fixture was for.
    """
    spelled = [dict(element) for element in elements]
    if not any(
        element.get("content", {}).get("binding") == "strain.name"
        for element in spelled
    ):
        spelled.insert(
            0,
            text_element(
                "required-name",
                REQUIRED_NAME_FRAME,
                binding="strain.name",
                size_mm=2.4,
                minimum_mm=1.8,
            ),
        )
    validation = validate_document(
        {
            "schema": "growspace.label-layout",
            "version": 1,
            "label_size_id": "growspace.stock.50x30.v1",
            "elements": spelled,
        }
    )
    assert validation.diagnostics == (), validation.diagnostics
    assert validation.layout is not None
    return validation.layout


def compile_and_judge(
    layout: LabelLayout,
    snapshot: LabelContentSnapshot,
    profile: CapabilityProfile,
    fonts: Any | None = None,
) -> tuple[CompiledLabel, SafetyReport]:
    """Compile one layout and judge it, the way a render does."""
    compiled = compile_layout(layout, snapshot, profile)
    return compiled, evaluate_safety(layout, compiled, profile, fonts or StubFonts())


def codes(report: SafetyReport) -> list[str]:
    """The diagnostic codes one safety pass produced, in order."""
    return [item.code for item in report.diagnostics]


def complete_evidence(profile: CapabilityProfile) -> ReleaseEvidenceRecord:
    """A complete, current physical evidence record for one profile.

    Every dimension run, passed, measured and retained, covering every
    rotation and density the profile permits, against the dependencies that
    ship -- the only record that certifies a product-verified claim.
    """
    return ReleaseEvidenceRecord(
        reference="evidence/test-record",
        profile_id=profile.id,
        profile_definition=profile.definition_digest,
        printer_model=profile.printer_class,
        firmware="5.14",
        driver="niimbot 0.0.0",
        stock=profile.label_size_id,
        procedure=EVIDENCE_PROCEDURE_VERSION,
        operator="operator",
        reviewed_by="reviewer",
        recorded_on="2026-09-21",
        dependencies=current_dependencies(),
        results={
            dimension: DimensionResult(
                passed=True,
                measurements={"within_tolerance": True},
                artifacts=(f"evidence/test-record/{dimension}.png",),
                covers=(
                    tuple(str(r) for r in profile.supported_element_rotations)
                    if dimension is EvidenceDimension.ROTATION
                    else tuple(profile.density_levels)
                    if dimension is EvidenceDimension.DENSITY
                    else ()
                ),
            )
            for dimension in EvidenceDimension
        },
    )


def product_verified(profile: CapabilityProfile) -> CapabilityProfile:
    """The same profile, claiming product-verified with the proof attached."""
    claimed = replace(profile, evidence=ProfileEvidence.PRODUCT_VERIFIED)
    return replace(claimed, evidence_record=complete_evidence(claimed))
