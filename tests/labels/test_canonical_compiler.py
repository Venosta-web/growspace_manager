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
    to_pixels,
    validate_document,
)
from custom_components.growspace_manager.labels.model import (
    Divider,
    FittedText,
    Logo,
    QrCode,
)

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
    assert (placed.x_start, placed.x_end) == (to_pixels(2.0, 203), to_pixels(42.0, 203))
    assert (placed.y_start, placed.y_end) == (to_pixels(9.0, 203), to_pixels(9.4, 203))


def test_a_qr_is_sized_by_its_frame_rather_than_by_a_module_count() -> None:
    """A saved frame is a promise about millimetres a module size cannot keep."""
    plant = LabelContentSnapshot(
        context=PrintContext.PLANT,
        subject="plant-1",
        as_of=AS_OF,
        values={"strain.name": "Blue Dream", "plant.link": "http://ha.test/plant/1"},
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
        "compiler.rotation_unsupported"
    ]
    assert compiled.outcomes[0].status == BLOCKED
    assert compiled.plan.elements == ()


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


def test_a_binding_its_context_does_not_support_is_an_error() -> None:
    """A strain has no instance to point at, and saying so is not the same as
    having nothing to print."""
    qr = {
        "id": "element-qr",
        "kind": "qr",
        "frame": {"x_mm": 36.0, "y_mm": 10.0, "width_mm": 10.0, "height_mm": 10.0},
        "rotation": 0,
        "content": {"binding": "plant.link", "parameters": {"target": "dashboard_url"}},
        "style": {"error_correction": "high", "quiet_zone_modules": 4},
    }
    compiled = compile_layout(_layout(qr), SNAPSHOT, NIIMBOT_B1_50X30)
    assert "content.unsupported_context" in [item.code for item in compiled.diagnostics]


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
