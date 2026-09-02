"""Tests for the two-way Shot Size Conversion (percent ↔ pump seconds)."""

import pytest

from custom_components.growspace_manager.domain.shot_sizing import (
    dripper_flow_rate_ml_per_sec,
    percent_to_seconds,
    seconds_to_percent,
    shot_volume_ml,
)

# One reference growspace: 5 L pots, a 20 ml/s pump, 3 live plants.
LITERS = 5.0
FLOW = 20.0
COUNT = 3


def test_shot_volume_scales_with_live_plant_count() -> None:
    """Per-plant dosing: total volume is the per-pot dose times the count."""
    assert shot_volume_ml(
        4.0, liters_per_pot=LITERS, live_plant_count=COUNT
    ) == pytest.approx(600.0)
    assert shot_volume_ml(
        4.0, liters_per_pot=LITERS, live_plant_count=1
    ) == pytest.approx(200.0)


def test_percent_to_seconds_divides_volume_by_flow_rate() -> None:
    """600 ml at 20 ml/s is a 30 second shot."""
    assert (
        percent_to_seconds(
            4.0,
            liters_per_pot=LITERS,
            live_plant_count=COUNT,
            flow_rate_ml_per_sec=FLOW,
        )
        == 30
    )


def test_percent_to_seconds_floors_a_tiny_shot_at_one_second() -> None:
    """A positive but sub-second volume still fires for a second, never zero."""
    assert (
        percent_to_seconds(
            0.1,
            liters_per_pot=0.1,
            live_plant_count=1,
            flow_rate_ml_per_sec=1000.0,
        )
        == 1
    )


@pytest.mark.parametrize(
    ("percent", "live_plant_count", "flow_rate"),
    [
        pytest.param(4.0, 0, FLOW, id="zero_live_plants"),
        pytest.param(4.0, COUNT, 0.0, id="zero_flow_rate"),
        pytest.param(0.0, COUNT, FLOW, id="zero_percent"),
    ],
)
def test_percent_to_seconds_suspends_on_missing_prerequisites(
    percent: float, live_plant_count: int, flow_rate: float
) -> None:
    """Nothing to fire returns None, never a floored or fallback duration."""
    assert (
        percent_to_seconds(
            percent,
            liters_per_pot=LITERS,
            live_plant_count=live_plant_count,
            flow_rate_ml_per_sec=flow_rate,
        )
        is None
    )


def test_seconds_to_percent_recovers_the_per_pot_dose() -> None:
    """30 seconds at 20 ml/s across 3 × 5 L pots is a 4% per-pot shot."""
    assert seconds_to_percent(
        30,
        liters_per_pot=LITERS,
        live_plant_count=COUNT,
        flow_rate_ml_per_sec=FLOW,
    ) == pytest.approx(4.0)


def test_seconds_to_percent_is_plant_count_independent() -> None:
    """The same per-pot dose recovers the same percent at any plant count.

    Two growspaces dosing 4% need different seconds when they run different
    plant counts; dividing the count back out maps both to the one percent.
    Forgetting to would scale the recipe by the count.
    """
    seconds_for_three = percent_to_seconds(
        4.0, liters_per_pot=LITERS, live_plant_count=3, flow_rate_ml_per_sec=FLOW
    )
    seconds_for_eight = percent_to_seconds(
        4.0, liters_per_pot=LITERS, live_plant_count=8, flow_rate_ml_per_sec=FLOW
    )
    assert seconds_for_three is not None and seconds_for_eight is not None
    assert seconds_for_three != seconds_for_eight

    from_three = seconds_to_percent(
        seconds_for_three,
        liters_per_pot=LITERS,
        live_plant_count=3,
        flow_rate_ml_per_sec=FLOW,
    )
    from_eight = seconds_to_percent(
        seconds_for_eight,
        liters_per_pot=LITERS,
        live_plant_count=8,
        flow_rate_ml_per_sec=FLOW,
    )
    assert from_three == pytest.approx(from_eight)
    assert from_three == pytest.approx(4.0)


@pytest.mark.parametrize(
    ("percent", "liters_per_pot", "live_plant_count", "flow_rate"),
    [
        pytest.param(4.0, 5.0, 3, 20.0, id="reference"),
        pytest.param(2.5, 11.0, 7, 33.0, id="awkward_numbers"),
        pytest.param(1.0, 3.5, 1, 4.0, id="single_plant"),
        pytest.param(6.0, 20.0, 24, 250.0, id="large_room"),
    ],
)
def test_round_trip_returns_the_original_percent(
    percent: float, liters_per_pot: float, live_plant_count: int, flow_rate: float
) -> None:
    """percent → seconds → percent survives, within the one-second rounding."""
    seconds = percent_to_seconds(
        percent,
        liters_per_pot=liters_per_pot,
        live_plant_count=live_plant_count,
        flow_rate_ml_per_sec=flow_rate,
    )
    assert seconds is not None
    recovered = seconds_to_percent(
        seconds,
        liters_per_pot=liters_per_pot,
        live_plant_count=live_plant_count,
        flow_rate_ml_per_sec=flow_rate,
    )
    # Half a second of pump time is the worst the integer rounding can cost.
    tolerance = seconds_to_percent(
        0.5,
        liters_per_pot=liters_per_pot,
        live_plant_count=live_plant_count,
        flow_rate_ml_per_sec=flow_rate,
    )
    assert tolerance is not None
    assert recovered == pytest.approx(percent, abs=tolerance)


@pytest.mark.parametrize(
    ("liters_per_pot", "live_plant_count", "flow_rate"),
    [
        pytest.param(LITERS, 0, FLOW, id="zero_live_plants"),
        pytest.param(LITERS, COUNT, 0.0, id="zero_flow_rate"),
        pytest.param(0.0, COUNT, FLOW, id="unset_pot_volume"),
    ],
)
def test_seconds_to_percent_refuses_on_missing_prerequisites(
    liters_per_pot: float, live_plant_count: int, flow_rate: float
) -> None:
    """A percent that cannot be derived is None, never a guess."""
    assert (
        seconds_to_percent(
            30,
            liters_per_pot=liters_per_pot,
            live_plant_count=live_plant_count,
            flow_rate_ml_per_sec=flow_rate,
        )
        is None
    )


def test_dripper_throughput_converts_the_grower_facing_rating() -> None:
    """Four 2 L/h emitters deliver 8 L/h, which is 8000/3600 ml/s."""
    assert dripper_flow_rate_ml_per_sec(2.0, 4) == pytest.approx(8000.0 / 3600.0)


def test_dripper_throughput_of_no_emitters_is_no_flow() -> None:
    """An unwired line delivers nothing, which downstream reads as unset."""
    assert dripper_flow_rate_ml_per_sec(2.0, 0) == 0.0
