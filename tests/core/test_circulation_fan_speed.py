"""Unit tests for the compute_fan_speed and compute_wind_offset pure functions."""

import pytest

from custom_components.growspace_manager.circulation_fan_coordinator import (
    compute_fan_speed,
    compute_wind_offset,
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


# ---------------------------------------------------------------------------
# compute_wind_offset
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amplitude_pct", "elapsed_seconds", "period_seconds", "expected"),
    [
        # At t=0: sin(0) = 0 → no offset regardless of amplitude
        (10, 0.0, 60, 0.0),
        # At quarter period: sin(π/2) = 1.0 → full positive amplitude
        (10, 15.0, 60, 10.0),
        # At half period: sin(π) ≈ 0
        (10, 30.0, 60, pytest.approx(0.0, abs=1e-9)),
        # At three-quarter period: sin(3π/2) = -1.0 → full negative amplitude
        (10, 45.0, 60, -10.0),
        # At full period: sin(2π) ≈ 0
        (10, 60.0, 60, pytest.approx(0.0, abs=1e-9)),
        # Amplitude scales linearly
        (20, 15.0, 60, 20.0),
        # Different period — quarter of 120s = 30s
        (10, 30.0, 120, 10.0),
    ],
)
def test_compute_wind_offset(
    amplitude_pct: int,
    elapsed_seconds: float,
    period_seconds: int,
    expected: float,
) -> None:
    """compute_wind_offset returns amplitude × sin(2π × elapsed / period)."""
    result = compute_wind_offset(amplitude_pct, elapsed_seconds, period_seconds)
    assert result == expected
