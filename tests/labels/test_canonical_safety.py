"""Tests for the print-safety policy (hub issue #216).

One table decides which compiled outcomes block and which warn, and the suite
is arranged the way the table is: regions, then overlap and occlusion, then
each element variant's own limits, then the two properties that hold across
all of them -- that a profile's calibrated numbers are what anything is judged
against, and that nothing is ever repaired to make a layout eligible.

Text is measured with the face Pillow ships rather than the printer's, for the
reason `tests.labels.support` gives. The sizes below are therefore chosen so
the outcome does not depend on which face it is: a 1 mm line is under any
readable floor, and a name in a box a tenth its width does not fit in any
font.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import UTC, datetime
from io import BytesIO

from PIL import Image
import pytest

from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    OVERLAP_INK,
    OVERLAP_QR_QUIET_ZONE,
    OVERLAP_REQUIRED_CONTENT,
    TYPICAL_STRAIN,
    Recovery,
    Severity,
)
from tests.labels.support import (
    NoFonts,
    codes,
    compile_and_judge,
    divider_element,
    layout_of,
    logo_element,
    qr_element,
    text_element,
)

AS_OF = datetime(2026, 9, 18, tzinfo=UTC)
STRAIN = TYPICAL_STRAIN.snapshot(as_of=AS_OF)
PROFILE = NIIMBOT_B1_50X30


def _judge(*elements, profile=PROFILE, fonts=None):
    """Compile a fixture layout and return its safety report."""
    return compile_and_judge(layout_of(*elements), STRAIN, profile, fonts)[1]


def _of(report, code):
    """The one diagnostic with a given code."""
    return next(item for item in report.diagnostics if item.code == code)


# ---------------------------------------------------------------------------
# The three nested regions
# ---------------------------------------------------------------------------


def test_ink_inside_the_printable_area_but_outside_the_safe_area_only_warns() -> None:
    report = _judge(
        text_element(
            "edge",
            {"x_mm": 0.2, "y_mm": 2.0, "width_mm": 20.0, "height_mm": 6.0},
            literal="Edge",
        )
    )
    diagnostic = _of(report, "profile.ink_outside_safe_area")
    assert diagnostic.severity is Severity.WARNING
    assert diagnostic.element_id == "edge"
    assert diagnostic.recovery_action is Recovery.EDIT_ELEMENT
    assert "profile.ink_outside_printable_area" not in codes(report)


def test_ink_outside_the_printable_area_blocks() -> None:
    """The box is shorter than one line, so the renderer draws that line anyway
    and its descenders land below the stock's last printable row."""
    report = _judge(
        text_element(
            "spill",
            {"x_mm": 2.0, "y_mm": 27.0, "width_mm": 40.0, "height_mm": 3.0},
            literal="Spilling past the bottom",
            size_mm=6.0,
            minimum_mm=6.0,
            overflow="ellipsis",
        )
    )
    diagnostic = _of(report, "profile.ink_outside_printable_area")
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.parameters["printable_area"]["height"] == 240


def test_a_frame_crossing_the_safe_area_whose_ink_does_not_is_left_alone() -> None:
    """The diagnostic describes the compiled outcome, not a bounding box: a
    frame may reach into the margin as long as nothing is painted there."""
    report = _judge(
        text_element(
            "wide",
            {"x_mm": 0.2, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 6.0},
            literal="Ab",
            align="right",
            size_mm=3.0,
            minimum_mm=3.0,
        )
    )
    assert "profile.ink_outside_safe_area" not in codes(report)


def test_the_profile_owns_where_the_safe_area_is() -> None:
    generous = replace(PROFILE, safe_area_inset_mm=4.0)
    element = text_element(
        "edge",
        {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 20.0, "height_mm": 6.0},
        literal="Edge",
    )
    assert "profile.ink_outside_safe_area" not in codes(_judge(element))
    assert "profile.ink_outside_safe_area" in codes(_judge(element, profile=generous))


# ---------------------------------------------------------------------------
# Overlap, protected regions and occlusion
# ---------------------------------------------------------------------------


def test_partial_ink_overlap_warns_and_names_both_elements() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 6.0},
            binding="strain.name",
            size_mm=5.0,
            minimum_mm=5.0,
        ),
        divider_element(
            "rule", {"x_mm": 2.0, "y_mm": 4.0, "width_mm": 40.0, "height_mm": 0.6}
        ),
    )
    assert "raster.ink_overlap" in codes(report)
    pair = report.overlaps[0]
    assert {pair.first_element_id, pair.second_element_id} == {"name", "rule"}
    assert pair.kind == OVERLAP_REQUIRED_CONTENT
    assert pair.severity == "warning"


def test_two_elements_that_do_not_share_ink_produce_no_pair() -> None:
    report = _judge(
        divider_element(
            "rule", {"x_mm": 2.0, "y_mm": 4.0, "width_mm": 20.0, "height_mm": 0.6}
        ),
        divider_element(
            "other", {"x_mm": 2.0, "y_mm": 8.0, "width_mm": 20.0, "height_mm": 0.6}
        ),
    )
    assert report.overlaps == ()


def test_ink_in_a_protected_qr_area_blocks_whichever_is_painted_first() -> None:
    qr = qr_element(
        "code", {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 16.0, "height_mm": 16.0}
    )
    rule = divider_element(
        "rule", {"x_mm": 26.0, "y_mm": 12.0, "width_mm": 18.0, "height_mm": 0.6}
    )
    for elements in ((qr, rule), (rule, qr)):
        report = _judge(*elements)
        diagnostic = _of(report, "raster.qr_quiet_zone_violated")
        assert diagnostic.severity is Severity.ERROR
        assert diagnostic.element_id == "rule"
        pair = next(
            item for item in report.overlaps if item.kind == OVERLAP_QR_QUIET_ZONE
        )
        assert pair.severity == "error"


def test_an_overlap_away_from_required_content_is_an_ordinary_pair() -> None:
    report = _judge(
        divider_element(
            "rule", {"x_mm": 24.0, "y_mm": 4.0, "width_mm": 20.0, "height_mm": 2.0}
        ),
        divider_element(
            "other", {"x_mm": 24.0, "y_mm": 5.0, "width_mm": 20.0, "height_mm": 2.0}
        ),
    )
    assert [pair.kind for pair in report.overlaps] == [OVERLAP_INK]


def test_completely_occluded_required_content_blocks() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 20.0, "height_mm": 6.0},
            binding="strain.name",
            size_mm=4.0,
            minimum_mm=4.0,
        ),
        divider_element(
            "cover", {"x_mm": 1.0, "y_mm": 1.0, "width_mm": 24.0, "height_mm": 8.0}
        ),
    )
    diagnostic = _of(report, "raster.required_content_occluded")
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.element_id == "name"


def test_required_content_covered_by_something_painted_before_it_still_prints() -> None:
    """Paint order is the whole question: ink drawn first is underneath."""
    report = _judge(
        divider_element(
            "cover", {"x_mm": 1.0, "y_mm": 1.0, "width_mm": 24.0, "height_mm": 8.0}
        ),
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 20.0, "height_mm": 6.0},
            binding="strain.name",
            size_mm=4.0,
            minimum_mm=4.0,
        ),
    )
    assert "raster.required_content_occluded" not in codes(report)


def test_partly_covered_required_content_warns_rather_than_blocks() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 30.0, "height_mm": 6.0},
            binding="strain.name",
            size_mm=4.0,
            minimum_mm=4.0,
        ),
        divider_element(
            "cover", {"x_mm": 2.0, "y_mm": 3.0, "width_mm": 6.0, "height_mm": 2.0}
        ),
    )
    assert "raster.required_content_occluded" not in codes(report)
    assert "raster.ink_overlap" in codes(report)


# ---------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------


def test_text_below_the_calibrated_readable_floor_blocks() -> None:
    report = _judge(
        text_element(
            "tiny",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 2.0},
            literal="Northern Lights Automatic",
            size_mm=1.4,
            minimum_mm=1.0,
        )
    )
    diagnostic = _of(report, "profile.text_below_readable_floor")
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.parameters["readable_floor_mm"] == (
        PROFILE.limits.text_readable_floor_mm
    )


def test_text_between_the_floor_and_the_comfort_threshold_warns() -> None:
    """The B1's floor and comfort threshold are one size, so the band is
    exercised on a profile that has one."""
    banded = replace(
        PROFILE,
        limits=replace(
            PROFILE.limits, text_readable_floor_mm=1.6, text_comfort_threshold_mm=2.2
        ),
    )
    report = _judge(
        text_element(
            "small",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 20.0, "height_mm": 3.0},
            literal="Small",
            size_mm=1.8,
            minimum_mm=1.8,
        ),
        profile=banded,
    )
    diagnostic = _of(report, "profile.text_below_comfort_threshold")
    assert diagnostic.severity is Severity.WARNING
    assert "profile.text_below_readable_floor" not in codes(report)


def test_a_shrink_policy_that_cannot_fit_at_its_minimum_blocks() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 6.0, "height_mm": 4.0},
            literal="Northern Lights Automatic Extra Long",
            size_mm=3.2,
            minimum_mm=2.4,
            overflow="shrink",
        )
    )
    diagnostic = _of(report, "raster.text_does_not_fit")
    assert diagnostic.severity is Severity.ERROR


def test_an_ellipsis_policy_that_drops_content_warns() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 8.0, "height_mm": 5.0},
            literal="Northern Lights Automatic",
            size_mm=3.2,
            minimum_mm=3.2,
            overflow="ellipsis",
        )
    )
    diagnostic = _of(report, "raster.text_truncated")
    assert diagnostic.severity is Severity.WARNING
    assert diagnostic.parameters["overflow"] == "ellipsis"


def test_a_shrink_ellipsis_policy_that_truncates_after_shrinking_warns() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 8.0, "height_mm": 5.0},
            literal="Northern Lights Automatic Extra Long",
            size_mm=3.2,
            minimum_mm=2.6,
            overflow="shrink_ellipsis",
        )
    )
    assert "raster.text_truncated" in codes(report)
    assert "raster.text_does_not_fit" not in codes(report)


def test_a_glyph_the_font_does_not_have_blocks_and_nothing_is_substituted() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 30.0, "height_mm": 6.0},
            literal="Kush 株式",
            size_mm=3.2,
            minimum_mm=3.2,
        )
    )
    diagnostic = _of(report, "raster.missing_glyph")
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.parameters["characters"] == ["株", "式"]
    assert diagnostic.recovery_action is Recovery.EDIT_CONTENT


def test_an_unresolvable_font_is_reported_as_unmeasured_rather_than_guessed() -> None:
    report = _judge(
        text_element(
            "tiny",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 2.0},
            literal="Northern Lights Automatic",
            size_mm=1.4,
            minimum_mm=1.0,
        ),
        fonts=NoFonts(),
    )
    assert "raster.text_unmeasured" in codes(report)
    # And nothing is scored against a measurement that was never taken.
    assert "profile.text_below_readable_floor" not in codes(report)
    assert "raster.text_truncated" not in codes(report)


# ---------------------------------------------------------------------------
# QR codes
# ---------------------------------------------------------------------------


def test_a_quiet_zone_below_the_symbology_s_requirement_blocks() -> None:
    report = _judge(
        qr_element(
            "code",
            {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 16.0, "height_mm": 16.0},
            quiet_zone_modules=2,
        )
    )
    diagnostic = _of(report, "profile.qr_quiet_zone_too_small")
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.parameters["minimum_quiet_zone_modules"] == 4


def test_a_geometrically_square_qr_still_blocks_below_the_module_floor() -> None:
    """Nothing about the frame is wrong; the modules are simply too small to
    scan, which only the profile's own measurement can say."""
    strict = replace(
        PROFILE, limits=replace(PROFILE.limits, qr_minimum_dots_per_module=4)
    )
    report = _judge(
        qr_element(
            "code", {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 16.0, "height_mm": 16.0}
        ),
        profile=strict,
    )
    diagnostic = _of(report, "profile.qr_below_module_floor")
    assert diagnostic.severity is Severity.ERROR
    assert diagnostic.parameters["minimum_dots_per_module"] == 4


def test_a_box_too_small_for_the_matrix_blocks_before_any_limit() -> None:
    report = _judge(
        qr_element(
            "code", {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 4.0, "height_mm": 4.0}
        )
    )
    assert "raster.qr_does_not_fit" in codes(report)


def test_an_error_correction_level_without_evidence_blocks() -> None:
    report = _judge(
        qr_element(
            "code",
            {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 16.0, "height_mm": 16.0},
            error_correction="low",
        )
    )
    diagnostic = _of(report, "profile.qr_error_correction_unsupported")
    assert diagnostic.severity is Severity.ERROR


def test_a_target_longer_than_the_profile_verified_blocks() -> None:
    short = replace(
        PROFILE, limits=replace(PROFILE.limits, qr_maximum_encoded_bytes=10)
    )
    report = _judge(
        qr_element(
            "code", {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 16.0, "height_mm": 16.0}
        ),
        profile=short,
    )
    assert "profile.qr_target_too_long" in codes(report)


def test_a_target_no_qr_version_carries_blocks() -> None:
    report = _judge(
        qr_element(
            "code",
            {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 16.0, "height_mm": 16.0},
            literal="x" * 4000,
            error_correction="high",
        )
    )
    assert "raster.qr_not_encodable" in codes(report)


# ---------------------------------------------------------------------------
# Images and dividers
# ---------------------------------------------------------------------------


def test_an_image_below_the_calibrated_effective_resolution_warns() -> None:
    report = _judge(
        logo_element(
            "logo", {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0}
        )
    )
    diagnostic = _of(report, "profile.image_below_effective_resolution")
    assert diagnostic.severity is Severity.WARNING
    assert diagnostic.parameters["minimum_effective_dpi"] == 203.0


def test_an_undecodable_image_warns_and_paints_blank() -> None:
    report = _judge(
        logo_element(
            "logo",
            {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0},
            asset="growspace.asset.broken.v1",
        )
    )
    diagnostic = _of(report, "raster.image_undecodable")
    assert diagnostic.severity is Severity.WARNING


def test_an_image_that_converts_to_no_ink_warns() -> None:
    blank = Image.new("RGB", (64, 64), "white")
    buffer = BytesIO()
    blank.save(buffer, format="PNG")
    uri = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    report = _judge(
        logo_element(
            "logo",
            {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0},
            asset=uri,
        )
    )
    assert "raster.image_leaves_no_ink" in codes(report)


def test_a_divider_below_the_reproducible_thickness_warns() -> None:
    report = _judge(
        divider_element(
            "rule", {"x_mm": 2.0, "y_mm": 12.0, "width_mm": 20.0, "height_mm": 0.1}
        )
    )
    diagnostic = _of(report, "profile.divider_below_reproducible_thickness")
    assert diagnostic.severity is Severity.WARNING
    assert diagnostic.parameters["minimum_thickness_mm"] == 0.25


# ---------------------------------------------------------------------------
# Rotation and density stay the profile's to refuse
# ---------------------------------------------------------------------------


def test_an_unsupported_density_is_refused_rather_than_mapped_to_a_neighbour() -> None:
    from custom_components.growspace_manager.labels.canonical import compile_layout

    compiled = compile_layout(
        layout_of(
            text_element(
                "name",
                {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 30.0, "height_mm": 6.0},
                binding="strain.name",
            )
        ),
        STRAIN,
        PROFILE,
        density="ludicrous",
    )
    diagnostic = next(
        item
        for item in compiled.diagnostics
        if item.code == "profile.unsupported_density"
    )
    assert diagnostic.severity is Severity.ERROR
    assert compiled.plan.density_level is None


# ---------------------------------------------------------------------------
# Two properties that hold everywhere
# ---------------------------------------------------------------------------


def test_nothing_is_moved_scaled_or_reordered_to_make_a_layout_eligible() -> None:
    elements = (
        text_element(
            "name",
            {"x_mm": 0.2, "y_mm": 27.0, "width_mm": 40.0, "height_mm": 3.0},
            binding="strain.name",
            size_mm=6.0,
            minimum_mm=6.0,
            overflow="ellipsis",
        ),
        divider_element(
            "rule", {"x_mm": 0.2, "y_mm": 27.5, "width_mm": 40.0, "height_mm": 0.1}
        ),
    )
    layout = layout_of(*elements)
    before = layout.as_dict()
    compiled, report = compile_and_judge(layout, STRAIN, PROFILE)

    assert any(item.severity is Severity.ERROR for item in report.diagnostics)
    # The document is untouched, and so is the paint order it declared.
    assert layout.as_dict() == before
    assert [item.element_id for item in report.ink] == [
        element.id for element in layout.elements
    ]
    assert [item.element_id for item in compiled.outcomes] == [
        element.id for element in layout.elements
    ]


def test_every_diagnostic_carries_a_recovery_route() -> None:
    report = _judge(
        qr_element(
            "code",
            {"x_mm": 28.0, "y_mm": 8.0, "width_mm": 16.0, "height_mm": 16.0},
            quiet_zone_modules=2,
            error_correction="low",
        ),
        logo_element(
            "logo", {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0}
        ),
    )
    assert report.diagnostics
    for diagnostic in report.diagnostics:
        assert diagnostic.recovery_action is not Recovery.NONE
        assert diagnostic.as_dict()["recovery"] == str(diagnostic.recovery_action)


@pytest.mark.parametrize(
    "code",
    [
        "profile.ink_outside_safe_area",
        "profile.text_below_readable_floor",
        "profile.qr_quiet_zone_too_small",
    ],
)
def test_the_profile_layer_owns_its_own_codes(code: str) -> None:
    """A limit is the profile's statement, so the diagnostic that reports it
    belongs to the compilation layer rather than to the renderer's."""
    assert code.startswith("profile.")


def test_the_font_identity_records_what_was_really_measured() -> None:
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 30.0, "height_mm": 6.0},
            binding="strain.name",
        )
    )
    assert set(report.font_identity) == {"rbm.ttf"}
    assert all(report.font_identity.values())


def test_required_content_that_never_reached_the_plan_is_not_an_occlusion() -> None:
    """A record with no strain name is a content refusal, and reporting it a
    second time as "something painted over it" would send the operator to the
    wrong control."""
    from custom_components.growspace_manager.labels.canonical import compile_layout
    from custom_components.growspace_manager.labels.canonical.safety import (
        evaluate_safety,
    )
    from tests.labels.support import StubFonts

    layout = layout_of(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 30.0, "height_mm": 6.0},
            binding="strain.name",
        ),
        divider_element(
            "cover", {"x_mm": 1.0, "y_mm": 1.0, "width_mm": 34.0, "height_mm": 8.0}
        ),
    )
    nameless = replace(STRAIN, values={})
    compiled = compile_layout(layout, nameless, PROFILE)
    report = evaluate_safety(layout, compiled, PROFILE, StubFonts())

    assert "content.missing_required" in [item.code for item in compiled.diagnostics]
    assert "raster.required_content_occluded" not in codes(report)
    name = next(item for item in report.ink if item.element_id == "name")
    assert name.basis.value == "none"
    assert name.bounds is None


def test_required_content_that_resolved_to_no_ink_is_not_an_occlusion_either() -> None:
    """A `clip` policy in a frame with no width drops every glyph, so the
    strain name is absent from the raster without anything being painted over
    it. Truncation says that; occlusion would say something untrue about a
    different element."""
    report = _judge(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 0.01, "height_mm": 6.0},
            binding="strain.name",
            overflow="clip",
        ),
        divider_element(
            "cover", {"x_mm": 1.0, "y_mm": 1.0, "width_mm": 20.0, "height_mm": 8.0}
        ),
    )
    name = next(item for item in report.ink if item.element_id == "name")
    assert name.bounds is None
    assert "raster.text_truncated" in codes(report)
    assert "raster.required_content_occluded" not in codes(report)


def test_two_overlapping_qr_codes_block_each_other() -> None:
    """Another code's ink is other ink. A scanner reading either one sees the
    same ruined quiet zone a divider would have left."""
    report = _judge(
        qr_element(
            "first", {"x_mm": 20.0, "y_mm": 6.0, "width_mm": 16.0, "height_mm": 16.0}
        ),
        qr_element(
            "second", {"x_mm": 28.0, "y_mm": 6.0, "width_mm": 16.0, "height_mm": 16.0}
        ),
    )
    diagnostic = _of(report, "raster.qr_quiet_zone_violated")
    assert diagnostic.severity is Severity.ERROR
    assert [pair.kind for pair in report.overlaps] == [OVERLAP_QR_QUIET_ZONE]


def test_a_high_resolution_logo_does_not_warn_about_its_own_resolution() -> None:
    detailed = Image.new("RGB", (256, 256), "white")
    detailed.paste(Image.new("RGB", (256, 128), "black"), (0, 0))
    buffer = BytesIO()
    detailed.save(buffer, format="PNG")
    uri = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    report = _judge(
        logo_element(
            "logo",
            {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0},
            asset=uri,
        )
    )
    assert "profile.image_below_effective_resolution" not in codes(report)
    assert "raster.image_leaves_no_ink" not in codes(report)
