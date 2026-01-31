"""Tests for the utility functions in the Growspace Manager integration.

This file contains a suite of tests for the various helper and utility functions
defined in `custom_components/growspace_manager/utils.py`. It covers date
parsing, formatting, calculations, and grid generation logic.
"""

from datetime import date, datetime

from common import create_plant
import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.utils import (
    BayesianStage,
    VPDCalculator,
    calculate_days_since,
    calculate_plant_stage,
    calculate_stage_transition,
    days_to_week,
    find_first_free_position,
    format_date,
    generate_growspace_grid,
    generate_growspace_overview_unique_id,
    generate_vpd_sensor_unique_id,
    interpolate_value,
    parse_date_field,
    parse_date_field_v2,
)
from homeassistant.util.dt import as_local


# ----------------------------
# parse_date_field tests
# ----------------------------
@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        (None, None),
        (date(2025, 11, 3), as_local(datetime(2025, 11, 3, 0, 0))),
        (datetime(2025, 11, 3, 15, 30), as_local(datetime(2025, 11, 3, 15, 30))),
        ("2025-11-03", as_local(datetime(2025, 11, 3, 0, 0))),
        ("invalid-date", None),
        (12345, None),
    ],
)
def test_parse_date_field(input_value, expected) -> None:
    """Test the `parse_date_field` function with various input types.

    Args:
        input_value: The value to be parsed.
        expected: The expected `datetime` object or None.
    """
    assert parse_date_field(input_value) == expected


def test_parse_date_field_v2() -> None:
    """Test the `parse_date_field_v2` function (covers line 39)."""
    val = "2025-11-03"
    assert parse_date_field_v2(val) == as_local(datetime(2025, 11, 3, 0, 0))


# ----------------------------
# format_date tests
# ----------------------------
@pytest.mark.parametrize(
    ("input_value", "expected"),
    [
        (None, None),
        (date(2025, 11, 3), "2025-11-03"),
        (datetime(2025, 11, 3, 15, 30), "2025-11-03"),
        ("2025-11-03", "2025-11-03"),
        ("invalid-date", None),
        (12345, None),
    ],
)
def test_format_date(input_value, expected) -> None:
    """Test the `format_date` function to ensure correct string formatting.

    Args:
        input_value: The value to be formatted.
        expected: The expected ISO-formatted datetime string or None.
    """
    assert format_date(input_value) == expected


# ----------------------------
# calculate_days_since tests
# ----------------------------
def test_calculate_days_since() -> None:
    """Test the `calculate_days_since` function."""
    start = date(2025, 11, 1)
    end = date(2025, 11, 3)
    assert calculate_days_since(start, end) == 2

    # default end_date = today (we can't mock here, just check type)
    result = calculate_days_since(date(2025, 11, 1))
    assert isinstance(result, int)


# ----------------------------
# find_first_free_position tests
# ----------------------------
def test_find_first_free_position() -> None:
    """Test the `find_first_free_position` function in various scenarios."""
    growspace = Growspace(
        id="test",
        name="Test Growspace",
        rows=2,
        plants_per_row=2,
    )
    occupied = {(1, 1)}
    assert find_first_free_position(growspace, occupied) == (1, 2)

    occupied = {(1, 1), (1, 2), (2, 1)}
    assert find_first_free_position(growspace, occupied) == (2, 2)

    # all positions occupied: returns bottom-right
    occupied = {(1, 1), (1, 2), (2, 1), (2, 2)}
    assert find_first_free_position(growspace, occupied) == (2, 2)

    # Empty growspace: returns None, None (covers line 95)
    gs_empty = Growspace(id="none", name="None", rows=0, plants_per_row=0)
    assert find_first_free_position(gs_empty, set()) == (None, None)


# ----------------------------
# generate_growspace_grid tests
# ----------------------------
def test_generate_growspace_grid_basic() -> None:
    """Test the basic functionality of `generate_growspace_grid`."""
    plants = [
        create_plant(plant_id="p1", row=1, col=1, strain="A", growspace_id="g1"),
        create_plant(plant_id="p2", row=2, col=2, strain="B", growspace_id="g1"),
    ]
    grid = generate_growspace_grid(2, 2, plants)
    assert grid == [
        ["p1", None],
        [None, "p2"],
    ]


def test_generate_growspace_grid_empty() -> None:
    """Test that `generate_growspace_grid` creates an empty grid correctly."""
    grid = generate_growspace_grid(2, 2, [])
    assert grid == [
        [None, None],
        [None, None],
    ]


# ----------------------------
# days_to_week tests
# ----------------------------
@pytest.mark.parametrize(
    ("days", "expected"),
    [
        (0, 0),
        (-5, 0),
        (1, 1),
        (7, 1),
        (8, 2),
        (14, 2),
        (15, 3),
    ],
)
def test_days_to_week(days, expected) -> None:
    """Test the `days_to_week` function."""
    assert days_to_week(days) == expected


# ----------------------------
# calculate_plant_stage tests
# ----------------------------
def test_calculate_plant_stage() -> None:
    """Test the `calculate_plant_stage` function."""
    # 1. Special growspaces
    p = create_plant(plant_id="p1", growspace_id="mother", strain="A")
    assert calculate_plant_stage(p) == "mother"

    p = create_plant(plant_id="p1", growspace_id="clone", strain="A")
    assert calculate_plant_stage(p) == "clone"

    # 2. Date-based (mocking now is hard here without freezegun, so we use past dates)
    # Assuming today is after 2000-01-01
    p = create_plant(
        plant_id="p1", growspace_id="g1", strain="A", flower_start="2000-01-01"
    )
    assert calculate_plant_stage(p) == "flower"

    p = create_plant(
        plant_id="p1", growspace_id="g1", strain="A", veg_start="2000-01-01"
    )
    assert calculate_plant_stage(p) == "veg"

    # Priority check: flower > veg
    p = create_plant(
        plant_id="p1",
        growspace_id="g1",
        strain="A",
        veg_start="2000-01-01",
        flower_start="2000-02-01",
    )
    assert calculate_plant_stage(p) == "flower"

    # 3. Explicit stage
    p = create_plant(plant_id="p1", growspace_id="g1", strain="A", stage="dry")
    assert calculate_plant_stage(p) == "dry"

    # Default
    p = create_plant(plant_id="p1", growspace_id="g1", strain="A")
    assert calculate_plant_stage(p) == "seedling"

    # No growspace_id (covers line 227)
    p = create_plant(plant_id="p1", growspace_id=None, strain="A")
    assert calculate_plant_stage(p) == "seedling"


# ----------------------------
# VPDCalculator tests
# ----------------------------
def test_calculate_vpd() -> None:
    """Test the Simple VPD calculation."""
    # Standard values
    assert VPDCalculator.calculate_vpd(25.0, 60.0) == 1.26
    assert VPDCalculator.calculate_vpd(30.0, 50.0) == 2.12

    # Invalid inputs (covers line 151)
    assert VPDCalculator.calculate_vpd("25", 60.0) is None  # type: ignore[arg-type]
    assert VPDCalculator.calculate_vpd(25.0, "60") is None  # type: ignore[arg-type]


def test_calculate_vpd_with_lst_offset() -> None:
    """Test the VPD calculation with leaf temperature offset."""
    # Standard values
    # Air 25C, 60% RH, Leaf 23C (-2 offset)
    # Air SVP at 25C = 3.169 kPa
    # Air AVP at 60% = 1.901 kPa
    # Leaf SVP at 23C = 2.810 kPa
    # VPD = 2.810 - 1.901 = 0.91 kPa
    assert VPDCalculator.calculate_vpd_with_lst_offset(25.0, 60.0, -2.0) == 0.91

    # Invalid inputs (covers line 180)
    assert VPDCalculator.calculate_vpd_with_lst_offset("25", 60.0) is None  # type: ignore[arg-type]
    assert VPDCalculator.calculate_vpd_with_lst_offset(25.0, "60") is None  # type: ignore[arg-type]


def test_parse_date_field_with_tz() -> None:
    """Test parse_date_field with a timezone-aware datetime (covers line 48)."""
    dt = datetime(2025, 1, 1, tzinfo=datetime.now().astimezone().tzinfo)
    assert parse_date_field(dt) == dt


def test_calculate_days_since_invalid() -> None:
    """Test calculate_days_since with invalid inputs (covers line 71)."""
    assert calculate_days_since(None, "2025-01-01") == 0
    assert calculate_days_since("2025-01-01", "invalid") == 0


def test_generate_unique_ids() -> None:
    """Test unique ID generation functions (covers lines 274, 279)."""

    assert generate_vpd_sensor_unique_id("g1") == f"{DOMAIN}_g1_calculated_vpd"
    assert generate_growspace_overview_unique_id("g1") == f"{DOMAIN}_g1"


def test_interpolate_value() -> None:
    """Test the `interpolate_value` function (covers line 323)."""
    assert interpolate_value(10.0, 20.0, 0.5) == 15.0
    assert interpolate_value(10.0, 20.0, 0.0) == 10.0
    assert interpolate_value(10.0, 20.0, -1.0) == 10.0
    assert interpolate_value(10.0, 20.0, 1.0) == 20.0
    assert interpolate_value(10.0, 20.0, 2.0) == 20.0


def test_calculate_stage_transition() -> None:
    """Test calculate_stage_transition for all branches (covers 246-315)."""
    # 1. Flower branch
    # Early flower
    s1, s2, f = calculate_stage_transition(flower_days=10)
    assert s1 == BayesianStage.FLOWER_EARLY
    assert s2 == BayesianStage.FLOWER_EARLY
    assert f == 0.0

    # Transition to mid (window is 3, b1 is 21)
    s1, s2, f = calculate_stage_transition(flower_days=20)
    assert s1 == BayesianStage.FLOWER_EARLY
    assert s2 == BayesianStage.FLOWER_MID
    assert f == 0.67

    # Mid flower
    s1, s2, f = calculate_stage_transition(flower_days=25)
    assert s1 == BayesianStage.FLOWER_MID
    assert s2 == BayesianStage.FLOWER_MID
    assert f == 0.0

    # Transition to late (b2 is 42)
    s1, s2, f = calculate_stage_transition(flower_days=41)
    assert s1 == BayesianStage.FLOWER_MID
    assert s2 == BayesianStage.FLOWER_LATE
    assert f == 0.67

    # Late flower
    s1, s2, f = calculate_stage_transition(flower_days=50)
    assert s1 == BayesianStage.FLOWER_LATE
    assert s2 == BayesianStage.FLOWER_LATE
    assert f == 0.0

    # 2. Veg branch
    # Transition to veg (window is 3)
    s1, s2, f = calculate_stage_transition(veg_days=1)
    assert s1 == BayesianStage.SEEDLING_STANDARD
    assert s2 == BayesianStage.VEG
    assert f == 0.33

    # Stable veg
    s1, s2, f = calculate_stage_transition(veg_days=5)
    assert s1 == BayesianStage.VEG
    assert s2 == BayesianStage.VEG
    assert f == 0.0

    # 3. Seedling branch
    # Seedling acclimation (start is 3, end is 7)
    s1, s2, f = calculate_stage_transition(seedling_days=2)
    assert s1 == BayesianStage.SEEDLING
    assert s2 == BayesianStage.SEEDLING
    assert f == 0.0

    s1, s2, f = calculate_stage_transition(seedling_days=5)
    assert s1 == BayesianStage.SEEDLING
    assert s2 == BayesianStage.SEEDLING_STANDARD
    assert f == 0.5

    s1, s2, f = calculate_stage_transition(seedling_days=8)
    assert s1 == BayesianStage.SEEDLING_STANDARD
    assert s2 == BayesianStage.SEEDLING_STANDARD
    assert f == 0.0

    # 4. Clone branch
    # Clone acclimation start
    s1, s2, f = calculate_stage_transition(clone_days=2)
    assert s1 == BayesianStage.CLONE
    assert s2 == BayesianStage.CLONE
    assert f == 0.0

    # Clone mid-acclimation (acclimation is 3-7 days)
    # window = 7 - 3 = 4
    # clone_days = 5 -> (5 - 3) / 4 = 0.5
    s1, s2, f = calculate_stage_transition(clone_days=5)
    assert s1 == BayesianStage.CLONE
    assert s2 == BayesianStage.CLONE_STANDARD
    assert f == 0.5

    # Clone post-acclimation
    s1, s2, f = calculate_stage_transition(clone_days=8)
    assert s1 == BayesianStage.CLONE_STANDARD
    assert s2 == BayesianStage.CLONE_STANDARD
    assert f == 0.0

    # 5. Default branch
    s1, s2, f = calculate_stage_transition()
    assert s1 == BayesianStage.VEG
    assert s2 == BayesianStage.VEG
    assert f == 0.0
