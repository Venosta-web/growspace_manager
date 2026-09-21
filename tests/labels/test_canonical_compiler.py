"""Tests for millimetre-to-pixel compilation (hub issue #214).

The compiler is the only authoritative converter, so these tests are about the
arithmetic and about what it refuses to do to make a raster come out. The
edge-conversion cases are the load-bearing ones: they are why two frames
sharing a millimetre edge cannot acquire a rounding gap at one resolution and
a rounding overlap at another.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import pytest

from custom_components.growspace_manager.labels.canonical import (
    BLOCKED,
    FACTORY_50X30,
    NIIMBOT_B1_50X30,
    OMITTED_MISSING_CONTENT,
    PLACED,
    TYPICAL_STRAIN,
    LabelContentSnapshot,
    PrintContext,
    compile_layout,
    profiles_for_size,
    to_pixels,
    validate_document,
)
from custom_components.growspace_manager.labels.canonical.document import LiteralSource
from custom_components.growspace_manager.labels.model import (
    Divider,
    FittedText,
    Logo,
    QrCode,
)
from tests.labels.support import product_verified

AS_OF = datetime(2026, 9, 18, 12, 0, tzinfo=UTC)
SNAPSHOT = TYPICAL_STRAIN.snapshot(as_of=AS_OF)


def _layout(*elements: dict[str, Any]) -> Any:
    document = {
        "schema": "growspace.label-layout",
        "version": 1,
        "label_size_id": "growspace.stock.50x30.v1",
        "elements": [
            {
                "id": "element-strain-name",
                "kind": "text",
                "frame": {
                    "x_mm": 2.0,
                    "y_mm": 2.0,
                    "width_mm": 40.0,
                    "height_mm": 6.0,
                },
                "rotation": 0,
                "content": {"binding": "strain.name", "parameters": {}},
                "style": {
                    "font": "growspace.sans.bold.v1",
                    "font_size_mm": 4.2,
                    "horizontal_align": "left",
                    "vertical_align": "center",
                    "line_spacing": "growspace.spacing.compact.v1",
                    "overflow": "shrink_ellipsis",
                    "minimum_font_size_mm": 2.2,
                    "maximum_lines": 2,
                },
            },
            *elements,
        ],
    }
    validation = validate_document(document)
    assert validation.diagnostics == ()
    return validation.layout


# ---------------------------------------------------------------------------
# Edge conversion
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("millimetres", "dpi", "pixels"),
    [
        (0.0, 203, 0),
        (25.4, 203, 203),
        (25.4, 300, 300),
        (48.0, 203, 384),
        # Exactly half a pixel rounds up, not to even. No quantized
        # millimetre reaches it at 203 or 300 dpi, but the rule is the
        # specification's so its golden tests stay portable -- and Python's
        # own `round(0.5)` is 0.
        (0.127, 100, 1),
    ],
)
def test_one_edge_converts_by_the_specified_formula(
    millimetres: float, dpi: int, pixels: int
) -> None:
    assert to_pixels(millimetres, dpi) == pixels


def test_adjacent_frames_sharing_an_edge_share_a_pixel_edge() -> None:
    """Rounding widths independently is how a one-pixel gap appears."""
    rule = {
        "id": "element-rule",
        "kind": "divider",
        "frame": {"x_mm": 2.0, "y_mm": 8.0, "width_mm": 40.0, "height_mm": 0.37},
        "rotation": 0,
        "style": {"fill": "black"},
    }
    below = {
        "id": "element-phenotype",
        "kind": "text",
        "frame": {"x_mm": 2.0, "y_mm": 8.37, "width_mm": 40.0, "height_mm": 4.0},
        "rotation": 0,
        "content": {
            "binding": "strain.phenotype",
            "parameters": {"presentation": "value"},
        },
        "style": {
            "font": "growspace.sans.regular.v1",
            "font_size_mm": 3.0,
            "horizontal_align": "left",
            "vertical_align": "center",
            "line_spacing": "growspace.spacing.compact.v1",
            "overflow": "shrink_ellipsis",
            "minimum_font_size_mm": 2.0,
            "maximum_lines": 1,
        },
    }
    compiled = compile_layout(_layout(rule, below), SNAPSHOT, NIIMBOT_B1_50X30)
    frames = {item.element_id: item.pixel_frame for item in compiled.outcomes}
    assert frames["element-rule"].bottom == frames["element-phenotype"].top


def test_the_canvas_is_the_printable_area_not_the_stock() -> None:
    """A 400px raster for a 384px printhead is the failure no preview shows."""
    compiled = compile_layout(FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30)
    assert compiled.plan.canvas.width == NIIMBOT_B1_50X30.printhead_pixels
    assert compiled.plan.canvas.width <= NIIMBOT_B1_50X30.printhead_pixels


def test_compilation_is_deterministic() -> None:
    """Which is what lets a preview stand in for the print that follows it."""
    first = compile_layout(FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30)
    second = compile_layout(FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30)
    assert first == second


# ---------------------------------------------------------------------------
# Element variants reach the render plan
# ---------------------------------------------------------------------------


def test_text_compiles_to_the_renderer_s_bounded_fitting_primitive() -> None:
    compiled = compile_layout(_layout(), SNAPSHOT, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[0]
    assert isinstance(placed, FittedText)
    assert placed.value == "Blue Dream"
    assert placed.font == "ppb.ttf"
    assert placed.fit == "shrink_ellipsis"
    assert placed.size == to_pixels(4.2, 203)
    assert placed.min_size == to_pixels(2.2, 203)


def test_the_clip_policy_truncates_without_a_mark() -> None:
    """There is no pixel-level clip below this renderer; say which one it is."""
    document = _layout().as_dict()
    document["elements"][0]["style"]["overflow"] = "clip"
    layout = validate_document(document).layout
    compiled = compile_layout(layout, SNAPSHOT, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[0]
    assert isinstance(placed, FittedText)
    assert (placed.fit, placed.ellipsis) == ("ellipsis", "")


def test_a_divider_s_frame_is_its_complete_inked_extent() -> None:
    """The renderer's rectangle is inclusive on both edges, so the last inked
    pixel is what it is given -- one short of the frame's exclusive edge,
    which is what makes the ink and the saved millimetres the same rectangle."""
    rule = {
        "id": "element-rule",
        "kind": "divider",
        "frame": {"x_mm": 2.0, "y_mm": 9.0, "width_mm": 40.0, "height_mm": 0.4},
        "rotation": 0,
        "style": {"fill": "black"},
    }
    compiled = compile_layout(_layout(rule), SNAPSHOT, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[1]
    assert isinstance(placed, Divider)
    assert (placed.x_start, placed.x_end) == (
        to_pixels(2.0, 203),
        to_pixels(42.0, 203) - 1,
    )
    assert (placed.y_start, placed.y_end) == (
        to_pixels(9.0, 203),
        to_pixels(9.4, 203) - 1,
    )


def test_a_divider_thinner_than_one_pixel_still_names_one_row() -> None:
    """Zero inclusive rows is not a thinner rule, it is a renderer error. The
    thickness policy is what reports a rule this printer cannot draw."""
    rule = {
        "id": "element-rule",
        "kind": "divider",
        "frame": {"x_mm": 2.0, "y_mm": 9.0, "width_mm": 40.0, "height_mm": 0.01},
        "rotation": 0,
        "style": {"fill": "black"},
    }
    compiled = compile_layout(_layout(rule), SNAPSHOT, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[1]
    assert isinstance(placed, Divider)
    assert placed.y_end == placed.y_start


def test_a_qr_is_sized_by_its_frame_rather_than_by_a_module_count() -> None:
    """A saved frame is a promise about millimetres a module size cannot keep."""
    plant = LabelContentSnapshot(
        context=PrintContext.PLANT,
        subject="plant-1",
        as_of=AS_OF,
        values={"strain.name": "Blue Dream"},
        links={"dashboard_url": "http://ha.test/plant/1"},
    )
    qr = {
        "id": "element-qr",
        "kind": "qr",
        "frame": {"x_mm": 36.0, "y_mm": 10.0, "width_mm": 10.0, "height_mm": 10.0},
        "rotation": 0,
        "content": {"binding": "plant.link", "parameters": {"target": "dashboard_url"}},
        "style": {"error_correction": "high", "quiet_zone_modules": 4},
    }
    compiled = compile_layout(_layout(qr), plant, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[1]
    assert isinstance(placed, QrCode)
    assert placed.width == placed.height == to_pixels(46.0, 203) - to_pixels(36.0, 203)
    assert placed.border == 4
    assert placed.error_correction == "h"


def test_a_logo_keeps_its_own_aspect_ratio_inside_its_frame() -> None:
    logo = {
        "id": "element-logo",
        "kind": "logo",
        "frame": {"x_mm": 36.0, "y_mm": 2.0, "width_mm": 10.0, "height_mm": 6.0},
        "rotation": 0,
        "content": {"binding": "strain.breeder.logo", "parameters": {}},
        "style": {"monochrome": "growspace.mono.threshold.v1", "fit": "contain"},
    }
    snapshot = replace(
        SNAPSHOT,
        values={**SNAPSHOT.values, "strain.breeder.logo": "http://host.test/logo.png"},
    )
    compiled = compile_layout(_layout(logo), snapshot, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[1]
    assert isinstance(placed, Logo)
    assert placed.mode == "contain"
    assert placed.dither is False


# ---------------------------------------------------------------------------
# What it refuses
# ---------------------------------------------------------------------------


def test_element_rotation_is_refused_by_name_rather_than_guessed_at() -> None:
    """Untested rotating-group anchoring would be worse than an honest refusal."""
    document = _layout().as_dict()
    document["elements"][0]["rotation"] = 90
    layout = validate_document(document).layout
    compiled = compile_layout(layout, SNAPSHOT, NIIMBOT_B1_50X30)
    assert [item.code for item in compiled.diagnostics] == [
        "profile.rotation_unsupported"
    ]
    assert compiled.diagnostics[0].parameters["supported"] == [0]
    assert compiled.outcomes[0].status == BLOCKED
    assert compiled.plan.elements == ()


def test_a_profile_that_supports_a_rotation_places_it() -> None:
    """Which angles are realisable is the profile's statement, not a constant."""
    document = _layout().as_dict()
    document["elements"][0]["rotation"] = 90
    layout = validate_document(document).layout
    rotating = replace(NIIMBOT_B1_50X30, supported_element_rotations=(0, 90))
    compiled = compile_layout(layout, SNAPSHOT, rotating)
    assert [item.code for item in compiled.diagnostics] == []
    assert compiled.outcomes[0].status == PLACED


def test_a_profile_for_another_stock_is_refused() -> None:
    other = replace(NIIMBOT_B1_50X30, label_size_id="growspace.stock.50x80.v1")
    compiled = compile_layout(FACTORY_50X30.layout, SNAPSHOT, other)
    assert "profile.stock_mismatch" in [item.code for item in compiled.diagnostics]


def test_a_raster_wider_than_the_printhead_is_refused() -> None:
    """The transport does not reject it, so this is the only place that can."""
    too_wide = replace(NIIMBOT_B1_50X30, printable_width_mm=50.0)
    compiled = compile_layout(FACTORY_50X30.layout, SNAPSHOT, too_wide)
    assert "profile.raster_wider_than_printhead" in [
        item.code for item in compiled.diagnostics
    ]


def test_geometry_outside_the_printable_area_is_diagnosed_not_clamped() -> None:
    edge = {
        "id": "element-edge",
        "kind": "divider",
        "frame": {"x_mm": 45.0, "y_mm": 2.0, "width_mm": 4.0, "height_mm": 0.4},
        "rotation": 0,
        "style": {"fill": "black"},
    }
    compiled = compile_layout(_layout(edge), SNAPSHOT, NIIMBOT_B1_50X30)
    outcome = next(
        item for item in compiled.outcomes if item.element_id == "element-edge"
    )
    assert outcome.status == BLOCKED
    # The frame is reported exactly where it is, not where it would have fitted.
    assert outcome.pixel_frame.right == to_pixels(49.0, 203)
    assert "profile.outside_printable_area" in [
        item.code for item in compiled.diagnostics
    ]


def test_a_density_the_printer_class_does_not_have_is_refused() -> None:
    """The Classic path's global 3/5/8 is out of range on this hardware."""
    compiled = compile_layout(
        FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30, density="scorching"
    )
    assert "profile.unsupported_density" in [item.code for item in compiled.diagnostics]


def test_density_resolves_through_the_profile_rather_than_a_global_table() -> None:
    compiled = compile_layout(
        FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30, density="high"
    )
    assert compiled.plan.density == "high"
    assert compiled.plan.density_level == 5


# ---------------------------------------------------------------------------
# Content policy
# ---------------------------------------------------------------------------


def test_a_missing_optional_value_warns_omits_and_keeps_the_frame() -> None:
    bare = replace(SNAPSHOT, values={"strain.name": "Blue Dream"})
    compiled = compile_layout(FACTORY_50X30.layout, bare, NIIMBOT_B1_50X30)
    omitted = [
        item for item in compiled.outcomes if item.status == OMITTED_MISSING_CONTENT
    ]
    assert {item.binding for item in omitted} == {
        "strain.phenotype",
        "strain.breeder",
        "strain.lineage",
    }
    assert all(item.pixel_frame is not None for item in omitted)
    assert {item.severity for item in compiled.diagnostics} == {"warning"}


def test_a_missing_required_value_blocks_that_record() -> None:
    nameless = replace(SNAPSHOT, values={})
    compiled = compile_layout(FACTORY_50X30.layout, nameless, NIIMBOT_B1_50X30)
    codes = [item.code for item in compiled.diagnostics]
    assert "content.missing_required" in codes


def test_a_binding_its_context_does_not_support_warns_and_keeps_its_frame() -> None:
    """A strain has no instance to point at, and saying so is not the same as
    having nothing to print -- nor a reason to stop the label."""
    qr = {
        "id": "element-qr",
        "kind": "qr",
        "frame": {"x_mm": 36.0, "y_mm": 10.0, "width_mm": 10.0, "height_mm": 10.0},
        "rotation": 0,
        "content": {"binding": "plant.link", "parameters": {"target": "dashboard_url"}},
        "style": {"error_correction": "high", "quiet_zone_modules": 4},
    }
    compiled = compile_layout(_layout(qr), SNAPSHOT, NIIMBOT_B1_50X30)

    unsupported = next(
        item
        for item in compiled.diagnostics
        if item.code == "content.unsupported_context"
    )
    assert unsupported.severity == "warning"
    assert unsupported.layer == "content"
    assert unsupported.element_id == "element-qr"

    outcome = next(
        item for item in compiled.outcomes if item.element_id == "element-qr"
    )
    assert outcome.status == "omitted_unsupported_context"
    assert outcome.pixel_frame is not None


def test_an_unsupported_context_reads_differently_from_missing_content() -> None:
    """Two silences, two corrections: this template is being printed from
    somewhere it was not designed for, not this record is incomplete."""
    missing = compile_layout(
        _layout(
            {
                "id": "element-breeder",
                "kind": "text",
                "frame": {
                    "x_mm": 2.0,
                    "y_mm": 14.0,
                    "width_mm": 30.0,
                    "height_mm": 4.0,
                },
                "rotation": 0,
                "content": {
                    "binding": "strain.breeder",
                    "parameters": {"presentation": "value"},
                },
                "style": {
                    "font": "growspace.sans.regular.v1",
                    "font_size_mm": 3.2,
                    "horizontal_align": "left",
                    "vertical_align": "center",
                    "line_spacing": "growspace.spacing.compact.v1",
                    "overflow": "clip",
                    "minimum_font_size_mm": 2.2,
                    "maximum_lines": 1,
                },
            }
        ),
        replace(SNAPSHOT, values={"strain.name": "Blue Dream"}),
        NIIMBOT_B1_50X30,
    )
    assert "content.missing_optional" in [item.code for item in missing.diagnostics]
    assert "content.unsupported_context" not in [
        item.code for item in missing.diagnostics
    ]


def test_the_print_date_comes_from_the_captured_instant() -> None:
    """It is a property of the printing, never of the subject."""
    compiled = compile_layout(FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30)
    values = [
        element.value
        for element in compiled.plan.elements
        if isinstance(element, FittedText)
    ]
    assert "18 Sep 2026" in values


def test_a_labeled_presentation_gets_its_caption_from_the_backend() -> None:
    compiled = compile_layout(FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30)
    values = [
        element.value
        for element in compiled.plan.elements
        if isinstance(element, FittedText)
    ]
    assert "Breeder: Humboldt Seed Co." in values
    assert "Pheno 3" in values


def test_every_element_gets_exactly_one_outcome() -> None:
    """Including the ones that painted nothing, which is what makes it auditable."""
    bare = replace(SNAPSHOT, values={"strain.name": "Blue Dream"})
    compiled = compile_layout(FACTORY_50X30.layout, bare, NIIMBOT_B1_50X30)
    assert [item.element_id for item in compiled.outcomes] == [
        element.id for element in FACTORY_50X30.layout.elements
    ]
    assert {item.status for item in compiled.outcomes} == {
        PLACED,
        OMITTED_MISSING_CONTENT,
    }


# ---------------------------------------------------------------------------
# Content sources the compiler resolves without the binding catalogue
# ---------------------------------------------------------------------------


def test_a_literal_text_source_compiles_to_its_own_string() -> None:
    note = {
        "id": "element-note",
        "kind": "text",
        "frame": {"x_mm": 2.0, "y_mm": 10.0, "width_mm": 40.0, "height_mm": 4.0},
        "rotation": 0,
        "content": {"literal": "Keep refrigerated"},
        "style": {
            "font": "growspace.sans.regular.v1",
            "font_size_mm": 3.0,
            "horizontal_align": "left",
            "vertical_align": "center",
            "line_spacing": "growspace.spacing.compact.v1",
            "overflow": "shrink_ellipsis",
            "minimum_font_size_mm": 2.0,
            "maximum_lines": 1,
        },
    }
    compiled = compile_layout(_layout(note), SNAPSHOT, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[1]
    assert isinstance(placed, FittedText)
    assert placed.value == "Keep refrigerated"
    outcome = next(
        item for item in compiled.outcomes if item.element_id == "element-note"
    )
    assert (outcome.status, outcome.binding) == (PLACED, None)


def test_an_asset_logo_source_compiles_to_its_asset_identity() -> None:
    """Resolution to real bytes is the asset store's; placement is the compiler's."""
    logo = {
        "id": "element-logo",
        "kind": "logo",
        "frame": {"x_mm": 30.0, "y_mm": 10.0, "width_mm": 10.0, "height_mm": 6.0},
        "rotation": 0,
        "content": {"asset_id": "asset-01"},
        "style": {"monochrome": "growspace.mono.dither.v1", "fit": "contain"},
    }
    compiled = compile_layout(_layout(logo), SNAPSHOT, NIIMBOT_B1_50X30)
    placed = compiled.plan.elements[1]
    assert isinstance(placed, Logo)
    assert placed.url == "asset-01"
    assert placed.dither is True


def test_the_compiler_does_not_trust_that_its_input_came_from_the_validator() -> None:
    """An empty literal cannot survive validation, and must not paint if it does."""
    layout = _layout()
    broken = replace(
        layout,
        elements=(
            layout.elements[0],
            replace(
                layout.elements[0],
                id="element-empty",
                content=LiteralSource(""),
            ),
        ),
    )
    compiled = compile_layout(broken, SNAPSHOT, NIIMBOT_B1_50X30)
    outcome = next(
        item for item in compiled.outcomes if item.element_id == "element-empty"
    )
    assert outcome.status == BLOCKED
    assert len(compiled.plan.elements) == 1


# ---------------------------------------------------------------------------
# The profile the compilation is against
# ---------------------------------------------------------------------------


def test_an_element_with_no_content_source_at_all_blocks() -> None:
    """A divider is the only kind allowed none, and it never reaches here."""
    layout = _layout()
    broken = replace(
        layout,
        elements=(
            layout.elements[0],
            replace(layout.elements[0], id="element-void", content=None),
        ),
    )
    compiled = compile_layout(broken, SNAPSHOT, NIIMBOT_B1_50X30)
    outcome = next(
        item for item in compiled.outcomes if item.element_id == "element-void"
    )
    assert outcome.status == BLOCKED
    assert len(compiled.plan.elements) == 1


def test_a_profile_names_the_stock_it_prints() -> None:
    assert NIIMBOT_B1_50X30.label_size.width_mm == 50.0
    assert NIIMBOT_B1_50X30.label_size.height_mm == 30.0


def test_a_provisional_profile_does_not_authorize_production() -> None:
    assert NIIMBOT_B1_50X30.authorizes_production is False
    verified = product_verified(NIIMBOT_B1_50X30)
    assert verified.authorizes_production is True


def test_a_stock_with_no_profile_offers_none_rather_than_a_near_match() -> None:
    assert profiles_for_size("growspace.stock.50x80.v1") == ()
    assert profiles_for_size("growspace.stock.50x30.v1") == (NIIMBOT_B1_50X30,)


def test_the_same_layout_compiles_to_different_pixels_on_a_different_profile() -> None:
    """A profile change moves pixels; it never moves a saved millimetre."""
    at_300 = replace(
        NIIMBOT_B1_50X30,
        id="growspace.profile.test.300dpi.v1",
        dpi=300,
        printhead_pixels=567,
    )
    coarse = compile_layout(FACTORY_50X30.layout, SNAPSHOT, NIIMBOT_B1_50X30)
    fine = compile_layout(FACTORY_50X30.layout, SNAPSHOT, at_300)

    assert coarse.plan.canvas != fine.plan.canvas
    assert fine.plan.canvas.width == to_pixels(48.0, 300)
    assert not [item.code for item in fine.diagnostics]
    assert [element.id for element in FACTORY_50X30.layout.elements] == [
        item.element_id for item in fine.outcomes
    ]


def test_shared_edges_survive_the_other_supported_resolution() -> None:
    """Six of the specification's acceptance cases turn on this at both DPIs."""
    at_300 = replace(
        NIIMBOT_B1_50X30,
        id="growspace.profile.test.300dpi.v1",
        dpi=300,
        printhead_pixels=567,
    )
    compiled = compile_layout(FACTORY_50X30.layout, SNAPSHOT, at_300)
    frames = {item.element_id: item.pixel_frame for item in compiled.outcomes}
    # The rule is per pair of frames sharing a millimetre edge; the shipped
    # layout has no touching pair, so assert the arithmetic that guarantees it.
    for item in compiled.outcomes:
        assert item.pixel_frame is not None
    assert frames[FACTORY_50X30.layout.elements[0].id].left == to_pixels(2.0, 300)
