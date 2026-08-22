"""Unit tests for the evaluate_temp_override pure function."""

import pytest

from custom_components.growspace_manager.circulation_fan_coordinator import (
    evaluate_temp_override,
)


@pytest.mark.parametrize(
    (
        "current_temp",
        "low",
        "high",
        "hysteresis",
        "active",
        "direction",
        "vpd_speed",
        "min_speed",
        "max_speed",
        "expected_speed",
        "expected_active",
        "expected_direction",
    ),
    [
        # Both thresholds None → no override, VPD speed unchanged
        (25.0, None, None, 1.0, False, None, 50, 10, 90, 50, False, None),
        # Both None, override somehow active → cleared
        (35.0, None, None, 1.0, True, "high", 50, 10, 90, 50, False, None),
        # Not active, temp in safe zone → VPD speed unchanged
        (25.0, 15.0, 30.0, 2.0, False, None, 50, 10, 90, 50, False, None),
        # Not active, temp above high threshold → high override activates
        (32.0, 15.0, 30.0, 2.0, False, None, 50, 10, 90, 90, True, "high"),
        # Not active, temp below low threshold → low override activates
        (12.0, 15.0, 30.0, 2.0, False, None, 50, 10, 90, 10, True, "low"),
        # High override active, temp still above threshold → stays overriding
        (31.0, 15.0, 30.0, 2.0, True, "high", 50, 10, 90, 90, True, "high"),
        # High override active, temp between threshold and threshold-hysteresis → stays overriding
        (29.5, 15.0, 30.0, 2.0, True, "high", 50, 10, 90, 90, True, "high"),
        # High override active, temp exactly at threshold-hysteresis → deactivates
        (28.0, 15.0, 30.0, 2.0, True, "high", 50, 10, 90, 50, False, None),
        # High override active, temp below threshold-hysteresis → deactivates
        (27.0, 15.0, 30.0, 2.0, True, "high", 50, 10, 90, 50, False, None),
        # Low override active, temp still below threshold → stays overriding
        (14.0, 15.0, 30.0, 2.0, True, "low", 50, 10, 90, 10, True, "low"),
        # Low override active, temp between threshold and threshold+hysteresis → stays overriding
        (15.5, 15.0, 30.0, 2.0, True, "low", 50, 10, 90, 10, True, "low"),
        # Low override active, temp exactly at threshold+hysteresis → deactivates
        (17.0, 15.0, 30.0, 2.0, True, "low", 50, 10, 90, 50, False, None),
        # Low override active, temp above threshold+hysteresis → deactivates
        (18.0, 15.0, 30.0, 2.0, True, "low", 50, 10, 90, 50, False, None),
        # Only high threshold set, temp safe → VPD speed
        (25.0, None, 30.0, 2.0, False, None, 50, 10, 90, 50, False, None),
        # Only high threshold set, temp above → high override
        (32.0, None, 30.0, 2.0, False, None, 50, 10, 90, 90, True, "high"),
        # Only low threshold set, temp safe → VPD speed
        (25.0, 15.0, None, 2.0, False, None, 50, 10, 90, 50, False, None),
        # Only low threshold set, temp below → low override
        (12.0, 15.0, None, 2.0, False, None, 50, 10, 90, 10, True, "low"),
    ],
)
def test_evaluate_temp_override(
    current_temp: float,
    low: float | None,
    high: float | None,
    hysteresis: float,
    active: bool,
    direction: str | None,
    vpd_speed: int,
    min_speed: int,
    max_speed: int,
    expected_speed: int,
    expected_active: bool,
    expected_direction: str | None,
) -> None:
    """Test evaluate_temp_override for all boundary and state transitions."""
    speed, new_active, new_direction = evaluate_temp_override(
        current_temp,
        low,
        high,
        hysteresis,
        active,
        direction,
        vpd_speed,
        min_speed,
        max_speed,
    )
    assert speed == expected_speed
    assert new_active == expected_active
    assert new_direction == expected_direction
