"""Unit tests for the exhaust fan demand pure functions."""

import pytest

from custom_components.growspace_manager.domain.fan_control import (
    compute_exhaust_demand,
    compute_inverted_fan_speed,
)

_BANDS = {
    "temperature_target": 25.0,
    "temperature_tolerance": 2.0,
    "humidity_target": 60.0,
    "humidity_tolerance": 5.0,
    "vpd_target": 1.0,
    "vpd_tolerance": 0.2,
    "min_speed": 10,
    "max_speed": 90,
}


@pytest.mark.parametrize(
    ("value", "target", "tolerance", "min_speed", "max_speed", "expected"),
    [
        # VPD below (target - tolerance) → too humid → exhaust hard → max_speed
        (0.5, 1.0, 0.2, 10, 90, 90),
        # VPD at exactly lower bound → max_speed
        (0.8, 1.0, 0.2, 10, 90, 90),
        # VPD above (target + tolerance) → dry enough → exhaust min → min_speed
        (1.5, 1.0, 0.2, 10, 90, 10),
        # VPD at exactly upper bound → min_speed
        (1.2, 1.0, 0.2, 10, 90, 10),
        # VPD at target midpoint → midpoint speed
        (1.0, 1.0, 0.2, 10, 90, 50),
        # ¼ of the way up the band → ¾ exhaust (inverted)
        (0.9, 1.0, 0.2, 0, 100, 75),
    ],
)
def test_compute_inverted_fan_speed(
    value: float,
    target: float,
    tolerance: float,
    min_speed: int,
    max_speed: int,
    expected: int,
) -> None:
    """Inverted mapping: lower VPD → higher exhaust speed."""
    assert (
        compute_inverted_fan_speed(value, target, tolerance, min_speed, max_speed)
        == expected
    )


def test_combined_demand_takes_the_highest_term() -> None:
    """Demand is the max of the temperature, humidity and inverted-VPD terms.

    Hot tent (temp above band → 90), comfortable humidity (at target → 50),
    dry VPD (above band → inverted min → 10): the temperature term wins.
    """
    assert compute_exhaust_demand(30.0, 60.0, 1.5, **_BANDS) == 90


def test_combined_demand_vpd_inversion_can_dominate() -> None:
    """A too-humid VPD (below target) drives demand even when temp/humidity are calm."""
    # temp at target → 50, humidity at target → 50, vpd well below band → 90
    assert compute_exhaust_demand(25.0, 60.0, 0.5, **_BANDS) == 90


def test_combined_demand_skips_missing_terms() -> None:
    """A None reading drops that term from the max; remaining terms still count."""
    # No temperature reading; humidity above band → 90 should still win
    assert compute_exhaust_demand(None, 70.0, 1.5, **_BANDS) == 90


def test_combined_demand_all_missing_returns_none() -> None:
    """No readings at all → no demand to compute."""
    assert compute_exhaust_demand(None, None, None, **_BANDS) is None
