"""Tests for per-element ink measurement (hub issue #216).

The point of this layer is that a frame is not ink. Every test below is
therefore a case where judging the frame would give a different -- and wrong
-- answer than judging what the element really paints: a logo letterboxed
inside its box, a QR that occupies an integer number of modules and leaves the
remainder of its frame blank, a line of text that ends well short of the
right-hand edge it was given.

The second thing they pin is that the geometry is the renderer's rather than a
plausible one. Fitting, wrapping, truncation, alignment, the contain and the
integer module scale are all reproduced from `imagespec`'s own implementation,
so any of them drifting shows up here rather than on paper.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from io import BytesIO

from PIL import Image
import pytest

from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    TYPICAL_PLANT,
    TYPICAL_STRAIN,
    InkBasis,
    compile_layout,
)
from custom_components.growspace_manager.labels.canonical.geometry import PixelFrame
from custom_components.growspace_manager.labels.canonical.ink import (
    element_ink,
    fit_text,
    ink_pixels,
    occluded_pixels,
    omitted_ink,
    overlap_of,
)
from custom_components.growspace_manager.labels.model import FittedText, TextLine
from tests.labels.support import (
    NoFonts,
    StubFonts,
    divider_element,
    layout_of,
    logo_element,
    qr_element,
    text_element,
)

AS_OF = datetime(2026, 9, 18, tzinfo=UTC)
STRAIN = TYPICAL_STRAIN.snapshot(as_of=AS_OF)
PLANT = TYPICAL_PLANT.snapshot(as_of=AS_OF)


def _ink(document: dict, snapshot=STRAIN, fonts=None):
    """Compile one document and measure the ink of the element it is about."""
    layout = layout_of(document)
    compiled = compile_layout(layout, snapshot, NIIMBOT_B1_50X30)
    outcome = next(
        item for item in compiled.outcomes if item.element_id == document["id"]
    )
    placed = compiled.placed[outcome.element_id]
    assert outcome.pixel_frame is not None
    return element_ink(
        placed,
        element_id=outcome.element_id,
        kind=outcome.kind,
        frame=outcome.pixel_frame,
        canvas_width=compiled.plan.canvas.width,
        canvas_height=compiled.plan.canvas.height,
        dpi=NIIMBOT_B1_50X30.dpi,
        fonts=fonts or StubFonts(),
    )


# ---------------------------------------------------------------------------
# Dividers: the one element whose frame really is its ink
# ---------------------------------------------------------------------------


def test_a_divider_inks_its_whole_frame() -> None:
    ink = _ink(
        divider_element(
            "rule", {"x_mm": 2.0, "y_mm": 11.0, "width_mm": 43.0, "height_mm": 0.4}
        )
    )
    assert ink.basis is InkBasis.EXACT
    assert ink.bounds is not None
    assert (ink.bounds.width, ink.bounds.height) == (344, 3)
    assert ink.measurements["thickness_mm"] == pytest.approx(0.375, abs=1e-3)


def test_a_divider_thinner_than_the_grid_still_inks_one_row() -> None:
    """The renderer cannot draw half a dot, so a 0.01 mm rule is one row of
    them. That it is not the rule anyone designed is the policy's to say."""
    ink = _ink(
        divider_element(
            "rule", {"x_mm": 2.0, "y_mm": 11.0, "width_mm": 43.0, "height_mm": 0.01}
        )
    )
    assert ink.measurements["thickness_px"] == 1
    assert ink_pixels(ink) == 344


# ---------------------------------------------------------------------------
# QR: an integer module square anchored in the corner of its frame
# ---------------------------------------------------------------------------


def test_a_qr_paints_an_integer_module_square_not_its_frame() -> None:
    ink = _ink(
        qr_element(
            "code",
            {"x_mm": 30.0, "y_mm": 10.0, "width_mm": 14.0, "height_mm": 14.0},
            literal="https://example.invalid/p/1",
        )
    )
    measurements = ink.measurements
    # Version 3 is 29 modules; four quiet-zone modules on each side make 37,
    # and 14 mm is 112 device pixels, which is three dots a module with 1 left
    # over. The renderer does not stretch to use it, so neither does this.
    assert (measurements["qr_version"], measurements["modules"]) == (3, 29)
    assert measurements["side_modules"] == 37
    assert measurements["dots_per_module"] == 3
    assert measurements["painted_side_px"] == 111
    assert ink.bounds is not None
    assert (ink.bounds.width, ink.bounds.height) == (111, 111)


def test_a_qr_s_protected_area_is_the_square_it_pastes() -> None:
    ink = _ink(
        qr_element(
            "code",
            {"x_mm": 30.0, "y_mm": 10.0, "width_mm": 14.0, "height_mm": 14.0},
        )
    )
    assert ink.protected == ink.bounds


def test_a_box_too_small_for_the_matrix_reports_no_module_scale() -> None:
    ink = _ink(
        qr_element(
            "code",
            {"x_mm": 30.0, "y_mm": 10.0, "width_mm": 4.0, "height_mm": 4.0},
        )
    )
    assert ink.measurements["dots_per_module"] == 0
    assert ink.measurements["integer_module_scale"] is False


def test_a_target_no_version_carries_is_reported_rather_than_measured() -> None:
    ink = _ink(
        qr_element(
            "code",
            {"x_mm": 30.0, "y_mm": 10.0, "width_mm": 14.0, "height_mm": 14.0},
            literal="x" * 4000,
            error_correction="high",
        )
    )
    assert ink.measurements["encodable"] is False
    assert ink.basis is InkBasis.FRAME


# ---------------------------------------------------------------------------
# Logos: contained, centred, and measured for what they really resolve to
# ---------------------------------------------------------------------------


def _png(width: int, height: int, colour: str = "black") -> str:
    image = Image.new("RGB", (width, height), "white")
    image.paste(Image.new("RGB", (width, height // 2 or 1), colour), (0, 0))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"


def test_a_contained_logo_keeps_its_own_aspect_and_is_centred() -> None:
    ink = _ink(
        logo_element(
            "logo", {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0}
        )
    )
    # The fixture logo is 8x8, so a square box contains it exactly.
    assert ink.measurements["source_width"] == 8
    assert ink.measurements["painted_width"] == ink.measurements["painted_height"]
    assert ink.basis is InkBasis.EXACT


def test_a_logo_records_the_resolution_it_really_prints_at() -> None:
    ink = _ink(
        logo_element(
            "logo", {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0}
        )
    )
    # 8 source pixels stretched over 80 device pixels is a tenth of the
    # printer's own resolution, whatever the frame says.
    assert ink.measurements["effective_dpi"] == pytest.approx(20.3, abs=0.1)


def test_an_image_that_converts_to_no_ink_is_measured_as_blank() -> None:
    blank = Image.new("RGB", (8, 8), "white")
    buffer = BytesIO()
    blank.save(buffer, format="PNG")
    uri = f"data:image/png;base64,{base64.b64encode(buffer.getvalue()).decode()}"
    ink = _ink(
        logo_element(
            "logo",
            {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0},
            asset=uri,
        )
    )
    assert ink.measurements["decoded"] is True
    assert ink_pixels(ink) == 0


def test_an_undecodable_asset_falls_back_to_its_frame_and_says_so() -> None:
    ink = _ink(
        logo_element(
            "logo",
            {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0},
            asset="growspace.asset.missing.v1",
        )
    )
    assert ink.basis is InkBasis.FRAME
    assert ink.measurements["decoded"] is False
    assert ink.measurements["remote"] is False


def test_a_remote_image_is_never_fetched_to_validate_a_layout() -> None:
    ink = _ink(
        logo_element(
            "logo",
            {"x_mm": 34.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0},
            asset="https://example.invalid/logo.png",
        )
    )
    assert ink.basis is InkBasis.FRAME
    assert ink.measurements["remote"] is True


# ---------------------------------------------------------------------------
# Text: the renderer's own fitting, reproduced
# ---------------------------------------------------------------------------


def _fitted(value: str, **overrides) -> FittedText:
    defaults = {
        "value": value,
        "x": 0,
        "y": 0,
        "width": 120,
        "height": 40,
        "size": 20,
        "font": "rbm.ttf",
        "min_size": 8,
        "max_lines": 1,
        "line_spacing": 2,
        "align": "left",
        "valign": "top",
        "fit": "shrink",
        "ellipsis": "…",
    }
    defaults.update(overrides)
    return FittedText(**defaults)


def _fit(value: str, **overrides):
    fonts = StubFonts()
    element = _fitted(value, **overrides)
    return fit_text(element, lambda size: fonts.load(element.font, size))


def test_text_that_fits_keeps_its_declared_size() -> None:
    fitted = _fit("Hi")
    assert fitted.size == 20
    assert fitted.truncated is False
    assert fitted.fitted_within_minimum is True


def test_shrinking_stops_at_the_first_size_that_fits() -> None:
    fitted = _fit("Northern Lights Automatic")
    assert 8 <= fitted.size < 20
    assert fitted.truncated is False


def test_shrinking_that_cannot_fit_reports_the_failure_rather_than_hiding_it() -> None:
    fitted = _fit("Northern Lights Automatic Extra Long", width=40, height=12)
    assert fitted.size == 8
    assert fitted.fitted_within_minimum is False
    assert fitted.truncated is True


def test_an_ellipsis_policy_keeps_its_size_and_drops_content() -> None:
    fitted = _fit("Northern Lights Automatic", fit="ellipsis")
    assert fitted.size == 20
    assert fitted.truncated is True
    assert fitted.lines[0].endswith("…")


def test_a_clip_policy_truncates_at_a_glyph_boundary_with_no_mark() -> None:
    fitted = _fit("Northern Lights Automatic", fit="ellipsis", ellipsis="")
    assert fitted.truncated is True
    assert not fitted.lines[0].endswith("…")


def test_wrapping_respects_the_declared_line_limit() -> None:
    fitted = _fit(
        "Northern Lights Automatic", fit="ellipsis", max_lines=3, width=80, height=90
    )
    assert len(fitted.lines) <= 3


def test_alignment_moves_the_ink_without_moving_the_frame() -> None:
    left = _ink(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
            binding="strain.name",
            align="left",
        )
    )
    right = _ink(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
            binding="strain.name",
            align="right",
        )
    )
    assert left.bounds is not None and right.bounds is not None
    assert right.bounds.left > left.bounds.left
    assert right.bounds.width == pytest.approx(left.bounds.width, abs=2)


def test_text_ink_is_narrower_than_the_frame_that_reserved_it() -> None:
    """The whole reason overlap is judged from ink: a wide frame around a
    short word is empty nearly everywhere."""
    ink = _ink(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
            binding="strain.name",
        )
    )
    assert ink.bounds is not None
    assert ink.bounds.width < 320


def test_a_missing_glyph_is_named_rather_than_substituted() -> None:
    ink = _ink(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
            literal="Kush 株",
        )
    )
    assert ink.measurements["missing_glyphs"] == ["株"]


def test_an_unresolvable_font_measures_nothing_and_says_so() -> None:
    ink = _ink(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
            binding="strain.name",
        ),
        fonts=NoFonts(),
    )
    assert ink.basis is InkBasis.FRAME
    assert ink.measurements["measured"] is False


# ---------------------------------------------------------------------------
# Overlap is asked of the masks
# ---------------------------------------------------------------------------


def test_two_elements_sharing_a_frame_but_not_ink_do_not_overlap() -> None:
    layout = layout_of(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
            binding="strain.name",
            size_mm=2.5,
            maximum_lines=1,
        ),
        divider_element(
            "rule", {"x_mm": 38.0, "y_mm": 8.0, "width_mm": 4.0, "height_mm": 0.4}
        ),
    )
    compiled = compile_layout(layout, STRAIN, NIIMBOT_B1_50X30)
    inks = [
        element_ink(
            compiled.placed[outcome.element_id],
            element_id=outcome.element_id,
            kind=outcome.kind,
            frame=outcome.pixel_frame,
            canvas_width=compiled.plan.canvas.width,
            canvas_height=compiled.plan.canvas.height,
            dpi=NIIMBOT_B1_50X30.dpi,
            fonts=StubFonts(),
        )
        for outcome in compiled.outcomes
    ]
    assert overlap_of(inks[0], inks[1]) is None


# ---------------------------------------------------------------------------
# Placement inside the frame
# ---------------------------------------------------------------------------


def _top_of(valign: str) -> int:
    ink = _ink(
        text_element(
            "name",
            {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 30.0, "height_mm": 12.0},
            binding="strain.name",
            size_mm=3.0,
            minimum_mm=3.0,
            valign=valign,
        )
    )
    assert ink.bounds is not None
    return ink.bounds.top


def test_vertical_alignment_moves_the_ink_down_its_frame() -> None:
    assert _top_of("top") < _top_of("center") < _top_of("bottom")


def test_centring_reaches_the_renderer_as_the_word_it_understands() -> None:
    """The document says `center`, as it does horizontally; the renderer spells
    the vertical one `middle` and top-aligns everything else. Handing the
    document's word straight through therefore centred nothing."""
    assert _top_of("center") != _top_of("top")


def test_centred_text_sits_between_the_left_and_right_aligned_ones() -> None:
    lefts = {}
    for align in ("left", "center", "right"):
        ink = _ink(
            text_element(
                "name",
                {"x_mm": 2.0, "y_mm": 2.0, "width_mm": 40.0, "height_mm": 8.0},
                binding="strain.name",
                align=align,
            )
        )
        assert ink.bounds is not None
        lefts[align] = ink.bounds.left
    assert lefts["left"] < lefts["center"] < lefts["right"]


def test_rows_that_do_not_fit_the_box_are_dropped_and_the_last_kept_is_marked() -> None:
    """The renderer always draws at least one row, then stops at whatever the
    box holds -- it never shrinks under an `ellipsis` policy."""
    fitted = _fit(
        "Northern Lights Automatic Extra Long Name",
        fit="ellipsis",
        max_lines=6,
        width=80,
        height=30,
    )
    assert len(fitted.lines) < 6
    assert fitted.truncated is True
    assert fitted.lines[-1].endswith("…")


def test_a_box_too_short_for_even_one_line_still_draws_one() -> None:
    fitted = _fit("Blue Dream", fit="ellipsis", max_lines=3, width=80, height=4)
    assert len(fitted.lines) == 1


# ---------------------------------------------------------------------------
# Contain, both ways round
# ---------------------------------------------------------------------------


def test_an_image_wider_than_its_box_is_letterboxed_top_and_bottom() -> None:
    ink = _ink(
        logo_element(
            "logo",
            {"x_mm": 30.0, "y_mm": 2.0, "width_mm": 12.0, "height_mm": 12.0},
            asset=_png(64, 16),
        )
    )
    measurements = ink.measurements
    assert measurements["painted_width"] > measurements["painted_height"]
    assert measurements["painted_width"] == 96


def test_an_image_taller_than_its_box_is_pillarboxed_left_and_right() -> None:
    ink = _ink(
        logo_element(
            "logo",
            {"x_mm": 30.0, "y_mm": 2.0, "width_mm": 12.0, "height_mm": 12.0},
            asset=_png(16, 64),
        )
    )
    measurements = ink.measurements
    assert measurements["painted_height"] > measurements["painted_width"]


@pytest.mark.parametrize(
    "asset",
    [
        "data:image/png;base64,",
        "data:image/png;base64,not-base-64-at-all!!",
        "data:image/png;base64,QUJD",
    ],
    ids=["empty", "undecodable", "not-an-image"],
)
def test_an_inline_image_that_cannot_be_read_falls_back_to_its_frame(
    asset: str,
) -> None:
    ink = _ink(
        logo_element(
            "logo",
            {"x_mm": 30.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 10.0},
            asset=asset,
        )
    )
    assert ink.basis is InkBasis.FRAME
    assert ink.measurements["decoded"] is False


# ---------------------------------------------------------------------------
# Elements and answers outside the canonical set
# ---------------------------------------------------------------------------


def test_an_element_this_model_cannot_measure_stands_for_its_frame() -> None:
    """The Classic path's primitives still reach the same plan type, and one
    arriving here must read as unmeasured rather than as no ink at all."""
    frame = PixelFrame(left=10, top=10, right=60, bottom=40)
    ink = element_ink(
        TextLine(value="Blue Dream", x=10, y=10, size=20, font="rbm.ttf"),
        element_id="classic",
        kind="text",
        frame=frame,
        canvas_width=384,
        canvas_height=240,
        dpi=203,
        fonts=StubFonts(),
    )
    assert ink.basis is InkBasis.FRAME
    assert ink.bounds == frame


def test_an_element_that_reached_no_plan_has_no_ink_and_no_mask() -> None:
    ink = omitted_ink("element-breeder", "text")
    assert ink.basis is InkBasis.NONE
    assert ink.bounds is None
    assert ink.mask is None
    assert ink_pixels(ink) == 0
    assert occluded_pixels(ink, None) == 0


def test_nothing_overlaps_an_element_that_painted_nothing() -> None:
    painted = _ink(
        divider_element(
            "rule", {"x_mm": 2.0, "y_mm": 11.0, "width_mm": 43.0, "height_mm": 0.4}
        )
    )
    assert overlap_of(painted, omitted_ink("gone", "text")) is None
    assert overlap_of(omitted_ink("gone", "text"), painted) is None


def test_the_wire_form_of_ink_never_carries_the_bitmap() -> None:
    ink = _ink(
        qr_element(
            "code", {"x_mm": 30.0, "y_mm": 10.0, "width_mm": 14.0, "height_mm": 14.0}
        )
    )
    wire = ink.as_dict()
    assert set(wire) == {
        "element_id",
        "kind",
        "basis",
        "bounds",
        "mask_digest",
        "protected_area",
        "measurements",
    }
    assert wire["protected_area"] == wire["bounds"]


def test_a_value_of_nothing_but_spaces_draws_no_line_at_all() -> None:
    """The renderer wraps on words, and a string with none produces none --
    which is a different silence from a frame that could not be measured."""
    assert _fit("   ").lines == ()


def test_an_unmeasurable_element_in_a_frame_with_no_extent_inks_nothing() -> None:
    ink = _ink(
        logo_element(
            "logo",
            {"x_mm": 30.0, "y_mm": 2.0, "width_mm": 0.01, "height_mm": 10.0},
            asset="growspace.asset.missing.v1",
        )
    )
    assert ink.basis is InkBasis.FRAME
    assert ink_pixels(ink) == 0
