from unittest.mock import MagicMock

from custom_components.growspace_manager.bayesian_evaluator import (
    evaluate_direct_humidity_stress,
    evaluate_direct_vpd_stress,
)
from custom_components.growspace_manager.models import EnvironmentState
from custom_components.growspace_manager.utils import calculate_stage_transition


def test_seedling_acclimation_humidity_stress():
    """Test humidity stress during seedling acclimation (Day 1-3)."""
    # Day 1: Should require 95-100%
    state = MagicMock(
        spec=EnvironmentState,
        humidity=97,
        flower_days=0,
        veg_days=0,
        seedling_days=1,
        clone_days=0,
        dry_days=0,
        cure_days=0,
        mother_days=0,
    )
    obs, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(obs) == 0  # SAFE

    # Day 1: 90% should be STRESS (Out of range <95 or >100)
    state.humidity = 90
    obs, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(obs) == 1
    assert "Humidity out of range (<95 or >100)" in reasons[0][1]


def test_seedling_transition_humidity_stress():
    """Test humidity stress during transition (Day 5)."""
    # Day 5: Midpoint between 3 and 7.
    # Day 3: (95, 100)
    # Day 7: (0, 90) -> wait, seedling_standard limits are (0, 90) in evaluator logic
    # Factor at day 5 = (5-3)/4 = 0.5
    # low = 95 + (0-95)*0.5 = 47.5
    # high = 100 + (90-100)*0.5 = 95.0

    state = MagicMock(
        spec=EnvironmentState,
        humidity=70,
        flower_days=0,
        veg_days=0,
        seedling_days=5,
        clone_days=0,
        dry_days=0,
        cure_days=0,
        mother_days=0,
    )
    obs, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(obs) == 0  # 70 is between 47.5 and 95.0

    state.humidity = 40
    obs, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(obs) == 1
    assert "Humidity out of range (<47.5 or >95.0)" in reasons[0][1]


def test_clone_acclimation_vpd_stress():
    """Test VPD stress during clone acclimation (Day 2)."""
    # Day 2: Should require -0.1 to 0.3
    state = MagicMock(
        spec=EnvironmentState,
        vpd=0.1,
        flower_days=0,
        veg_days=0,
        seedling_days=0,
        clone_days=2,
        is_lights_on=True,
        dry_days=0,
        cure_days=0,
        mother_days=0,
    )
    obs, reasons = evaluate_direct_vpd_stress(state, {})
    assert len(obs) == 0  # SAFE

    # Day 2: 0.5 should be STRESS
    state.vpd = 0.5
    obs, reasons = evaluate_direct_vpd_stress(state, {})
    assert len(obs) == 1
    assert "VPD out of range" in reasons[0][1]
    # Check default prob for clone acclimation (0.98, 0.02)
    assert obs[0] == (0.98, 0.02)


def test_stage_transition_logic():
    """Verify the stage transition factors for acclimation."""
    # Day 1
    s, t, f = calculate_stage_transition(0, 0, 1, 0)
    assert s == "seedling"
    assert t == "seedling"
    assert f == 0.0

    # Day 3 (Edge of full acclimation)
    s, t, f = calculate_stage_transition(0, 0, 3, 0)
    assert s == "seedling"
    assert t == "seedling"
    assert f == 0.0

    # Day 5 (Midpoint)
    s, t, f = calculate_stage_transition(0, 0, 5, 0)
    assert s == "seedling"
    assert t == "seedling_standard"
    assert f == 0.5

    # Day 7 (End of transition)
    s, t, f = calculate_stage_transition(0, 0, 7, 0)
    assert s == "seedling"
    assert t == "seedling_standard"
    assert f == 1.0

    # Day 8 (Standard)
    s, t, f = calculate_stage_transition(0, 0, 8, 0)
    assert s == "seedling_standard"
    assert t == "seedling_standard"
    assert f == 0.0
