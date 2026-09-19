"""Tests for the standardized calibration label (hub issue #221).

The sheet has one job: be the thing a measurement can be attributed to. Every
test here is a property that job needs, and most of them are properties it
would be easy to lose by making the picture nicer.

The two that matter most are the ones about where the marks sit. Ink outside
the declared Printable Area is an error, so a sheet drawn to the stock's edges
would be the one print the safety policy refuses -- which would be the print
that diagnoses the printer. And ticks stepping 0.5 mm apart in one column
would merge into a smear at 203 dpi and measure nothing, so they are staggered
along the edge instead.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from itertools import pairwise

import pytest

from custom_components.growspace_manager.labels.calibration import (
    CALIBRATION_SOURCE,
    ELEMENT_PREFIX,
    MINIMUM_PRINTABLE_HEIGHT_MM,
    MINIMUM_PRINTABLE_WIDTH_MM,
    SHEET_VERSION,
    TICK_COUNT,
    TICK_PITCH_MM,
    CalibrationSheetUnavailable,
    calibration_content,
    calibration_layout,
)
from custom_components.growspace_manager.labels.canonical import (
    NIIMBOT_B1_50X30,
    ElementKind,
    FeedAxis,
    PrintContext,
    Severity,
    validate_document,
)
from custom_components.growspace_manager.labels.canonical.subjects import RECORD_SOURCE

from .support import compile_and_judge

PROFILE = NIIMBOT_B1_50X30
AS_OF = datetime(2026, 9, 19, 9, 30, tzinfo=UTC)


def _sheet(profile=PROFILE, density: str = "normal"):
    return calibration_layout(profile, density=density)


def _content(profile=PROFILE):
    return calibration_content(profile, as_of=AS_OF)


def _ids(layout, suffix: str) -> list[str]:
    return [
        element.id
        for element in layout.elements
        if element.id.startswith(f"{ELEMENT_PREFIX}.{suffix}")
    ]


# ---------------------------------------------------------------------------
# It is a real document, minus the one thing it honestly is not
# ---------------------------------------------------------------------------


def test_the_sheet_is_a_valid_v1_document_except_for_the_strain_it_is_not_about() -> (
    None
):
    """It is constructed rather than validated because a publishable layout
    needs a text element bound to `strain.name`, and a calibration label is
    not about a strain. Everything else about it is an ordinary document, and
    this is what says so: exactly one diagnostic, and that one."""
    validation = validate_document(_sheet().as_dict())
    assert [item.code for item in validation.diagnostics] == [
        "document.missing_required_strain_name"
    ]
    assert validation.layout is not None


def test_nothing_on_the_sheet_blocks_its_own_print() -> None:
    """The print that diagnoses an unproven printer cannot be the print the
    safety policy refuses."""
    compiled, report = compile_and_judge(_sheet(), _content(), PROFILE)
    everything = (*compiled.diagnostics, *report.diagnostics)
    assert [item.code for item in everything if item.severity is Severity.ERROR] == []


def test_the_edge_scales_reach_outside_the_safe_area_on_purpose() -> None:
    """A sheet that stayed inside the conservative inset would never probe the
    edges it exists to measure. The excursion is a warning, which is exactly
    the severity it should be."""
    _, report = compile_and_judge(_sheet(), _content(), PROFILE)
    excursions = [
        item
        for item in report.diagnostics
        if item.code == "profile.ink_outside_safe_area"
    ]
    assert excursions
    assert all(item.severity is Severity.WARNING for item in excursions)


# ---------------------------------------------------------------------------
# The marks
# ---------------------------------------------------------------------------


def test_every_edge_carries_its_own_scale() -> None:
    for edge in ("top", "right", "bottom", "left"):
        assert len(_ids(_sheet(), edge)) == TICK_COUNT


def test_no_mark_lands_outside_the_declared_printable_area() -> None:
    """Which is what makes the measurement meaningful: the sheet is drawn
    against what the profile claims, and what the operator reads is the
    difference between the claim and the paper."""
    area = PROFILE.printable_area
    for element in _sheet().elements:
        frame = element.frame
        assert frame.x_mm >= area.x_mm
        assert frame.y_mm >= area.y_mm
        assert frame.right_mm <= area.right_mm + 1e-9
        assert frame.bottom_mm <= area.bottom_mm + 1e-9


def test_adjacent_ticks_never_share_a_column_of_dots() -> None:
    """0.5 mm at 203 dpi is four dots. Stacked, the ticks would merge into a
    smear; staggered, each one is separately readable."""
    ticks = [
        element
        for element in _sheet().elements
        if element.id.startswith(f"{ELEMENT_PREFIX}.top.")
    ]
    ordered = sorted(ticks, key=lambda element: element.frame.y_mm)
    for earlier, later in pairwise(ordered):
        assert later.frame.x_mm >= earlier.frame.right_mm


def test_each_tick_steps_one_pitch_further_into_the_label() -> None:
    ticks = sorted(
        (
            element
            for element in _sheet().elements
            if element.id.startswith(f"{ELEMENT_PREFIX}.left.")
        ),
        key=lambda element: element.frame.x_mm,
    )
    area = PROFILE.printable_area
    for index, tick in enumerate(ticks):
        assert tick.frame.x_mm == pytest.approx(area.x_mm + index * TICK_PITCH_MM)


def test_the_feed_ruler_is_centred_on_the_printable_midpoint_and_runs_both_ways() -> (
    None
):
    """Feed alignment is signed, so a ruler that only ran one way could not
    express half the measurements an operator has to enter."""
    ticks = sorted(
        (
            element
            for element in _sheet().elements
            if element.id.startswith(f"{ELEMENT_PREFIX}.feed.")
        ),
        key=lambda element: element.frame.y_mm,
    )
    area = PROFILE.printable_area
    middle = ticks[len(ticks) // 2]
    centre = middle.frame.y_mm + middle.frame.height_mm / 2
    assert centre == pytest.approx(area.y_mm + area.height_mm / 2)
    assert ticks[0].frame.y_mm < centre < ticks[-1].frame.y_mm


def test_the_feed_ruler_follows_the_profile_axis_rather_than_the_longer_side() -> None:
    """Which way the roll is slit is a declared fact, not one the stock's
    dimensions imply."""
    across = replace(PROFILE, feed_axis=FeedAxis.X)
    down = _ids(_sheet(), "feed")
    sideways = _ids(_sheet(across), "feed")
    assert down == sideways

    vertical = [
        element
        for element in _sheet().elements
        if element.id.startswith(f"{ELEMENT_PREFIX}.feed.")
    ]
    horizontal = [
        element
        for element in _sheet(across).elements
        if element.id.startswith(f"{ELEMENT_PREFIX}.feed.")
    ]
    assert len({element.frame.x_mm for element in vertical}) == 1
    assert len({element.frame.y_mm for element in horizontal}) == 1


# ---------------------------------------------------------------------------
# It says what it is
# ---------------------------------------------------------------------------


def test_the_sheet_names_the_profile_it_came_out_of() -> None:
    literals = [
        element.content.literal
        for element in _sheet().elements
        if element.kind is ElementKind.TEXT
        and getattr(element.content, "literal", None) is not None
    ]
    assert PROFILE.id in literals
    assert any(str(PROFILE.dpi) in line for line in literals)
    assert any(str(PROFILE.orientation) in line for line in literals)
    assert any(f"feed {PROFILE.feed_axis}" in line for line in literals)


def test_the_sheet_names_the_density_it_was_printed_at() -> None:
    """Two sheets printed at different heat are two different pieces of paper,
    and a measurement has to be attributable to the one in the hand."""
    normal = _sheet(density="normal")
    high = _sheet(density="high")
    assert normal.digest != high.digest


def test_the_printed_text_is_ascii_so_no_glyph_can_block_the_print() -> None:
    """A glyph the printer's font does not carry is a hard error, and this is
    the print that has to work on a printer nobody has proven yet."""
    for element in _sheet().elements:
        literal = getattr(element.content, "literal", None)
        if literal is not None:
            assert literal.isascii(), literal


def test_the_date_comes_through_the_ordinary_binding() -> None:
    """Rather than through a second formatter living in the sheet."""
    bindings = {
        getattr(element.content, "binding", None) for element in _sheet().elements
    }
    assert "print.date" in bindings


# ---------------------------------------------------------------------------
# What it declares itself to be
# ---------------------------------------------------------------------------


def test_a_calibration_snapshot_is_never_mistaken_for_a_record() -> None:
    """The provenance check that refuses to production-print a fixture has to
    refuse this for the same reason and by the same route."""
    content = _content()
    assert content.source == CALIBRATION_SOURCE
    assert content.source != RECORD_SOURCE
    assert content.context is PrintContext.STRAIN
    assert content.subject == PROFILE.id


def test_the_minimum_area_covers_an_edge_scale_s_whole_run() -> None:
    """The minimum is derived rather than chosen, so moving a tick pitch or
    the stagger moves it too instead of leaving a constant behind that used
    to be right."""
    from custom_components.growspace_manager.labels.calibration import sheet

    run = sheet._SCALE_RUN_MM + sheet._INNER_INSET_MM
    assert run <= MINIMUM_PRINTABLE_WIDTH_MM
    assert run <= MINIMUM_PRINTABLE_HEIGHT_MM


def test_the_sheet_version_is_stable_and_stated() -> None:
    """It is a calibration dependency: a measurement read off one arrangement
    of ticks does not transfer to another."""
    assert SHEET_VERSION.startswith("growspace.label-calibration-sheet.")


# ---------------------------------------------------------------------------
# Where it does not fit
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("overrides", "detail"),
    [
        ({"printable_width_mm": 20.0}, "wide"),
        ({"printable_height_mm": 12.0}, "tall"),
    ],
)
def test_a_printable_area_too_small_for_the_standard_is_refused_by_name(
    overrides: dict[str, float], detail: str
) -> None:
    """Shrinking the standard to fit would produce a sheet that is no longer
    the thing a measurement can be attributed to, so each axis that does not
    fit is refused and says which one it was."""
    cramped = replace(PROFILE, **overrides)
    with pytest.raises(CalibrationSheetUnavailable) as refusal:
        calibration_layout(cramped)
    assert cramped.id in str(refusal.value)
    assert detail in str(refusal.value)
