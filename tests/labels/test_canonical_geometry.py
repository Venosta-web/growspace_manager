"""Tests for the two rectangle types (hub issue #216).

Millimetres on the stock and device pixels on the raster are separate types
because conflating them is how a Printable Area ends up compared against a
frame nobody translated into it. There is not much behaviour here, and that is
the point: containment and intersection are questions, and a question that
answers "no" produces a diagnostic upstream rather than a corrected rectangle.
"""

from __future__ import annotations

from custom_components.growspace_manager.labels.canonical.geometry import (
    AreaMm,
    PixelFrame,
)

AREA = AreaMm(2.0, 1.0, 40.0, 20.0)
FRAME = PixelFrame(left=10, top=20, right=50, bottom=60)


# ---------------------------------------------------------------------------
# Millimetre regions
# ---------------------------------------------------------------------------


def test_a_region_knows_its_far_edges() -> None:
    assert (AREA.right_mm, AREA.bottom_mm) == (42.0, 21.0)


def test_an_inset_takes_the_same_margin_off_all_four_sides() -> None:
    inset = AREA.inset_by(1.5)
    assert inset.x_mm == 3.5
    assert inset.y_mm == 2.5
    assert inset.right_mm == 40.5
    assert inset.bottom_mm == 19.5


def test_an_inset_of_nothing_is_the_region_itself() -> None:
    assert AREA.inset_by(0.0) == AREA


def test_a_collapsed_inset_stays_centred_rather_than_inverting() -> None:
    collapsed = AREA.inset_by(30.0)
    assert (collapsed.width_mm, collapsed.height_mm) == (0.0, 0.0)
    assert collapsed.x_mm == 22.0
    assert collapsed.y_mm == 11.0


def test_a_region_serializes_for_the_wire() -> None:
    assert AREA.as_dict() == {
        "x_mm": 2.0,
        "y_mm": 1.0,
        "width_mm": 40.0,
        "height_mm": 20.0,
    }


# ---------------------------------------------------------------------------
# Pixel frames
# ---------------------------------------------------------------------------


def test_extent_is_the_difference_of_two_converted_edges() -> None:
    assert (FRAME.width, FRAME.height) == (40, 40)
    assert FRAME.is_empty is False


def test_a_frame_with_no_extent_is_empty() -> None:
    assert PixelFrame(10, 20, 10, 60).is_empty is True
    assert PixelFrame(10, 20, 50, 20).is_empty is True


def test_containment_admits_a_frame_sharing_an_edge() -> None:
    assert FRAME.contains(FRAME) is True
    assert FRAME.contains(PixelFrame(10, 20, 30, 40)) is True
    assert FRAME.contains(PixelFrame(9, 20, 30, 40)) is False
    assert FRAME.contains(PixelFrame(10, 20, 51, 40)) is False


def test_intersection_returns_the_shared_rectangle() -> None:
    assert FRAME.intersection(PixelFrame(30, 40, 90, 90)) == PixelFrame(
        left=30, top=40, right=50, bottom=60
    )


def test_frames_that_only_touch_do_not_intersect() -> None:
    """Edges are exclusive on the far side, so two frames meeting at one
    coordinate share no pixel -- which is what stops adjacent elements from
    reading as an overlap."""
    assert FRAME.intersection(PixelFrame(50, 20, 90, 60)) is None
    assert FRAME.intersection(PixelFrame(10, 60, 50, 90)) is None
    assert FRAME.intersection(PixelFrame(100, 100, 120, 120)) is None


def test_a_frame_serializes_with_its_extent_beside_its_edges() -> None:
    assert FRAME.as_dict() == {
        "left": 10,
        "top": 20,
        "right": 50,
        "bottom": 60,
        "width": 40,
        "height": 40,
    }
