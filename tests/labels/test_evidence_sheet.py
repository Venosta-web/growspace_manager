"""Tests for the evidence label (hub issue #231).

The sheet exists to put a profile's claims on paper, so every property here is
about a claim reaching paper unaltered: each probe sized from the number the
profile claims rather than one chosen here, nothing a safety pass would refuse,
and the edge scales exactly where the calibration sheet puts them so the same
four offsets can be read off either.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime

import pytest

from custom_components.growspace_manager.labels.calibration import (
    ELEMENT_PREFIX,
    EVIDENCE_PREFIX,
    EVIDENCE_SHEET_VERSION,
    CalibrationSheetUnavailable,
    calibration_content,
    calibration_layout,
    evidence_layout,
    long_qr_target,
    weakest_error_correction,
)
from custom_components.growspace_manager.labels.calibration.evidence_sheet import (
    LONG_QR_PREFIX,
)
from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    ElementKind,
    Severity,
    validate_document,
)
from custom_components.growspace_manager.labels.canonical.compiler import to_pixels
from custom_components.growspace_manager.labels.canonical.qr import symbol_for

from .support import compile_and_judge

PROFILE = NIIMBOT_B1_50X30
AS_OF = datetime(2026, 9, 21, 9, 0, tzinfo=UTC)


def _sheet(profile=PROFILE, density: str = "normal"):
    return evidence_layout(profile, density=density)


def _element(suffix: str, layout=None):
    layout = layout or _sheet()
    return next(e for e in layout.elements if e.id == f"{EVIDENCE_PREFIX}.{suffix}")


def _probes(layout=None):
    layout = layout or _sheet()
    return [e for e in layout.elements if e.id.startswith(f"{EVIDENCE_PREFIX}.")]


# ---------------------------------------------------------------------------
# It prints
# ---------------------------------------------------------------------------


def test_the_sheet_is_a_valid_v1_document_except_for_the_strain_it_is_not_about() -> (
    None
):
    validation = validate_document(_sheet().as_dict())
    assert [item.code for item in validation.diagnostics] == [
        "document.missing_required_strain_name"
    ]


def test_nothing_on_the_sheet_blocks_its_own_print() -> None:
    """Probing the floor means sitting on it, which is a warning; it must never
    be the error that stops the print meant to prove the floor.

    The one error allowed here is the stub face's: Pillow's bundled font has
    no accented glyphs, and the printer integration's faces do. That the real
    faces carry them is what the accented probe is on paper to show.
    """
    compiled, report = compile_and_judge(
        _sheet(), calibration_content(PROFILE, as_of=AS_OF), PROFILE
    )
    everything = (*compiled.diagnostics, *report.diagnostics)
    errors = [
        (item.code, item.element_id)
        for item in everything
        if item.severity is Severity.ERROR
    ]
    assert errors in (
        [],
        [("raster.missing_glyph", f"{EVIDENCE_PREFIX}.text.floor.accented")],
    )


def test_every_probe_stays_inside_the_edge_scales() -> None:
    inner = PROFILE.printable_area.inset_by(3.0)
    for element in _probes():
        frame = element.frame
        assert frame.x_mm >= inner.x_mm - 1e-9, element.id
        assert frame.y_mm >= inner.y_mm - 1e-9, element.id
        assert frame.right_mm <= inner.right_mm + 1e-9, element.id
        assert frame.bottom_mm <= inner.bottom_mm + 1e-9, element.id


def test_no_two_probes_overlap() -> None:
    probes = _probes()
    for index, one in enumerate(probes):
        for other in probes[index + 1 :]:
            a, b = one.frame, other.frame
            apart = (
                a.right_mm <= b.x_mm
                or b.right_mm <= a.x_mm
                or a.bottom_mm <= b.y_mm
                or b.bottom_mm <= a.y_mm
            )
            assert apart, (one.id, other.id)


def test_the_edge_scales_are_the_calibration_sheet_s_own() -> None:
    """So the four offsets read off either sheet are the same four numbers."""

    def scales(layout):
        return {
            element.id: element.frame
            for element in layout.elements
            if element.id.startswith(f"{ELEMENT_PREFIX}.")
            and element.id.split(".")[-2] in {"top", "right", "bottom", "left"}
        }

    assert scales(_sheet()) == scales(calibration_layout(PROFILE))


# ---------------------------------------------------------------------------
# Every probe is the profile's claim, not a number chosen here
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("suffix", ["qr.short", "qr.typical", "qr.long"])
def test_each_qr_gets_exactly_the_claimed_minimum_dots_per_module(suffix: str) -> None:
    """More would test a kinder claim than the profile makes; fewer would
    test one it does not make at all."""
    element = _element(suffix)
    limits = PROFILE.limits
    side = symbol_for(element.content.literal, element.style.error_correction)
    modules = side.side_modules(element.style.quiet_zone_modules)
    pixels = to_pixels(element.frame.right_mm, PROFILE.dpi) - to_pixels(
        element.frame.x_mm, PROFILE.dpi
    )
    assert pixels // modules == limits.qr_minimum_dots_per_module
    assert element.style.quiet_zone_modules == limits.qr_minimum_quiet_zone_modules


def test_the_qr_probes_use_the_weakest_claimed_correction() -> None:
    """The hardest to scan, and therefore the one the evidence has to prove."""
    assert weakest_error_correction(PROFILE) == "medium"
    for suffix in ("qr.short", "qr.typical", "qr.long"):
        assert _element(suffix).style.error_correction == "medium"


def test_the_weakest_correction_follows_the_profile() -> None:
    stricter = replace(
        PROFILE, limits=replace(PROFILE.limits, qr_error_correction_levels=("high",))
    )
    assert weakest_error_correction(stricter) == "high"


def test_the_long_target_is_exactly_the_claimed_maximum_and_says_so() -> None:
    target = _element("qr.long").content.literal
    maximum = PROFILE.limits.qr_maximum_encoded_bytes
    assert len(target.encode()) == maximum
    assert target.startswith(LONG_QR_PREFIX)
    assert target.endswith(f"#{maximum}")


def test_the_long_target_is_encoded_as_bytes_like_a_real_url() -> None:
    """Digit filler would pack in numeric mode and draw a far smaller symbol
    than a real URL of the same length."""
    target = long_qr_target(PROFILE.limits.qr_maximum_encoded_bytes)
    real = LONG_QR_PREFIX + "x" * (len(target) - len(LONG_QR_PREFIX))
    assert symbol_for(target, "medium").version == symbol_for(real, "medium").version


def test_a_claimed_maximum_shorter_than_the_prefix_still_has_that_length() -> None:
    target = long_qr_target(20)
    assert len(target) == 20
    assert target.endswith("#20")


def test_the_text_probes_sit_at_the_claimed_sizes_and_never_shrink() -> None:
    limits = PROFILE.limits
    sizes = {
        element.id.removeprefix(f"{EVIDENCE_PREFIX}."): element.style.font_size_mm
        for element in _probes()
        if element.kind is ElementKind.TEXT
    }
    assert sizes["text.comfort.bold"] == limits.text_comfort_threshold_mm
    assert sizes["text.comfort.regular"] == limits.text_comfort_threshold_mm
    for suffix in ("text.floor.bold", "text.floor.regular", "text.floor.accented"):
        assert sizes[suffix] == limits.text_readable_floor_mm
    for element in _probes():
        if element.kind is ElementKind.TEXT:
            assert element.style.minimum_font_size_mm == element.style.font_size_mm


def test_the_long_text_probe_has_room_to_wrap() -> None:
    """A frame shorter than two of the bold face's lines draws one line and
    silently refuses the second."""
    element = _element("text.floor.long")
    assert element.style.maximum_lines == 2
    assert element.frame.height_mm >= 2 * 1.46 * element.style.font_size_mm


def test_the_rules_are_the_claimed_minimum_and_twice_it() -> None:
    thinnest = PROFILE.limits.divider_minimum_thickness_mm
    assert _element("rule.minimum").frame.height_mm == pytest.approx(thinnest)
    assert _element("rule.double").frame.height_mm == pytest.approx(2 * thinnest)


# ---------------------------------------------------------------------------
# It says what it is
# ---------------------------------------------------------------------------


def test_the_sheet_names_its_profile_its_density_and_its_date() -> None:
    assert _element("identity.profile").content.literal == "niimbot-b1.50x30.v1"
    assert _element("identity.density").content.literal == "normal (3)"
    assert _element("identity.printed_on").content.binding == "print.date"
    assert _element("identity.density", _sheet(density="high")).content.literal == (
        "high (5)"
    )


def test_a_density_the_profile_does_not_map_is_named_as_such() -> None:
    assert _element("identity.density", _sheet(density="extra")).content.literal == (
        "extra (unmapped)"
    )


def test_the_sheet_version_is_stated() -> None:
    assert EVIDENCE_SHEET_VERSION.startswith("growspace.label-evidence-sheet.")


# ---------------------------------------------------------------------------
# Where it does not fit
# ---------------------------------------------------------------------------


def test_a_printable_area_too_narrow_for_the_qr_probes_is_refused() -> None:
    cramped = replace(PROFILE, printable_width_mm=30.0)
    with pytest.raises(CalibrationSheetUnavailable, match="across"):
        evidence_layout(cramped)


def test_probes_that_would_run_into_the_edge_scales_are_refused() -> None:
    """Shrinking a probe to fit would test a different claim."""
    short = replace(PROFILE, printable_height_mm=22.0)
    with pytest.raises(CalibrationSheetUnavailable, match="edge scales begin"):
        evidence_layout(short)
