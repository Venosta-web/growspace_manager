"""Unit tests for the compute_fan_speed pure function."""

import pytest

from custom_components.growspace_manager.circulation_fan_coordinator import (
    compute_fan_speed,
)


@pytest.mark.parametrize(
    ("value", "target", "tolerance", "min_speed", "max_speed", "expected"),
    [
        # Below lower bound → min_speed
        (50.0, 60.0, 5.0, 10, 90, 10),
        # At exactly lower bound → min_speed
        (55.0, 60.0, 5.0, 10, 90, 10),
        # Above upper bound → max_speed
        (70.0, 60.0, 5.0, 10, 90, 90),
        # At exactly upper bound → max_speed
        (65.0, 60.0, 5.0, 10, 90, 90),
        # At midpoint → midpoint speed
        (60.0, 60.0, 5.0, 10, 90, 50),
        # ¼ of way through band → ¼ interpolated
        (57.5, 60.0, 5.0, 0, 100, 25),
        # ¾ of way through band → ¾ interpolated
        (62.5, 60.0, 5.0, 0, 100, 75),
        # Temperature mode — same math
        (22.0, 25.0, 2.0, 20, 80, 20),
        (28.0, 25.0, 2.0, 20, 80, 80),
        (25.0, 25.0, 2.0, 20, 80, 50),
    ],
)
def test_compute_fan_speed(
    value: float,
    target: float,
    tolerance: float,
    min_speed: int,
    max_speed: int,
    expected: int,
) -> None:
    """Test compute_fan_speed returns correct speed for all boundary and midpoint cases."""
    assert compute_fan_speed(value, target, tolerance, min_speed, max_speed) == expected
