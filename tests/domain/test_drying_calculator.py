"""Tests for the drying calculator pure functions."""

import pytest

from custom_components.growspace_manager.drying_calculator import (
    CURE_READY_MOISTURE_THRESHOLD,
    TARGET_DRY_WEIGHT_RATIO,
    compute_days_to_target,
    compute_weight_lost_pct,
    is_cure_ready,
)
from custom_components.growspace_manager.models import MoistureEntry, WeightEntry


def test_constants_match_spec() -> None:
    """Thresholds match agreed scientific constants."""
    assert TARGET_DRY_WEIGHT_RATIO == 0.25
    assert CURE_READY_MOISTURE_THRESHOLD == 12.0


def test_weight_lost_pct_basic() -> None:
    """Weight lost is correct given initial wet weight and current weight."""
    # 150g current out of 200g wet → 25% lost
    assert compute_weight_lost_pct(wet_weight=200.0, current_weight=150.0) == pytest.approx(25.0)


def test_weight_lost_pct_no_wet_weight() -> None:
    """Returns None when initial wet weight is unknown."""
    assert compute_weight_lost_pct(wet_weight=None, current_weight=150.0) is None


def test_weight_lost_pct_zero_wet_weight() -> None:
    """Returns None when wet weight is zero to avoid division by zero."""
    assert compute_weight_lost_pct(wet_weight=0.0, current_weight=10.0) is None


def test_days_to_target_rolling_average() -> None:
    """Uses rolling average of all entries to project remaining days."""
    # Wet weight 400g → target 100g (25%)
    # Log: 400, 380, 360, 340 → avg daily loss = 20g, remaining = 340 - 100 = 240g → 12 days
    log = [
        WeightEntry(date="2026-05-12", weight_grams=400.0),
        WeightEntry(date="2026-05-13", weight_grams=380.0),
        WeightEntry(date="2026-05-14", weight_grams=360.0),
        WeightEntry(date="2026-05-15", weight_grams=340.0),
    ]
    result = compute_days_to_target(wet_weight=400.0, weight_log=log)
    assert result == pytest.approx(12.0)


def test_days_to_target_fewer_than_two_entries() -> None:
    """Returns None when log has fewer than 2 entries (no delta available)."""
    log = [WeightEntry(date="2026-05-15", weight_grams=300.0)]
    assert compute_days_to_target(wet_weight=400.0, weight_log=log) is None


def test_days_to_target_empty_log() -> None:
    """Returns None for empty log."""
    assert compute_days_to_target(wet_weight=400.0, weight_log=[]) is None


def test_days_to_target_no_weight_loss() -> None:
    """Returns None when average daily loss is zero (no progress)."""
    log = [
        WeightEntry(date="2026-05-14", weight_grams=300.0),
        WeightEntry(date="2026-05-15", weight_grams=300.0),
    ]
    assert compute_days_to_target(wet_weight=400.0, weight_log=log) is None


def test_days_to_target_already_at_target() -> None:
    """Returns 0 when current weight is already at or below target."""
    log = [
        WeightEntry(date="2026-05-14", weight_grams=110.0),
        WeightEntry(date="2026-05-15", weight_grams=100.0),
    ]
    result = compute_days_to_target(wet_weight=400.0, weight_log=log)
    assert result == pytest.approx(0.0)


def test_is_cure_ready_below_threshold() -> None:
    """Returns True when latest moisture is at or below threshold."""
    log = [
        MoistureEntry(date="2026-05-14", moisture_percent=14.0),
        MoistureEntry(date="2026-05-15", moisture_percent=11.5),
    ]
    assert is_cure_ready(log) is True


def test_is_cure_ready_at_threshold() -> None:
    """Returns True when moisture is exactly at threshold."""
    log = [MoistureEntry(date="2026-05-15", moisture_percent=12.0)]
    assert is_cure_ready(log) is True


def test_is_cure_ready_above_threshold() -> None:
    """Returns False when latest moisture is above threshold."""
    log = [MoistureEntry(date="2026-05-15", moisture_percent=13.0)]
    assert is_cure_ready(log) is False


def test_is_cure_ready_empty_log() -> None:
    """Returns False when no moisture readings exist."""
    assert is_cure_ready([]) is False
