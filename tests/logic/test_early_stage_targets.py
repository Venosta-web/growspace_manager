from unittest.mock import MagicMock

from custom_components.growspace_manager.bayesian_data import (
    PROB_ACCEPTABLE,
    PROB_VPD_STRESS_OUT_OF_RANGE,
)
from custom_components.growspace_manager.bayesian_evaluator import (
    _determine_stage_key,
    evaluate_direct_humidity_stress,
    evaluate_direct_vpd_stress,
    evaluate_optimal_co2,
    evaluate_optimal_vpd,
)
from custom_components.growspace_manager.models import EnvironmentState


def test_determine_stage_key_early_stages() -> None:
    """Test that seedling and clone stages are correctly identified."""
    # Seedling
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=-1,
        seedling_days=5,
        clone_days=-1,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    assert _determine_stage_key(state) == "seedling"

    # Clone
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=-1,
        seedling_days=-1,
        clone_days=5,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    assert _determine_stage_key(state) == "clone"

    # Veg (should take precedence over seedling/clone if veg_days > 0)
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=1,
        seedling_days=14,
        clone_days=-1,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    assert _determine_stage_key(state) == "veg"


def test_evaluate_direct_vpd_stress_seedling() -> None:
    """Test VPD stress thresholds for seedling stage."""
    # Seedling Day: stress (0.3, 1.2). Mild (0.4, 1.0).
    # 0.2 is STRESS
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=-1,
        seedling_days=1,
        clone_days=-1,
        vpd=0.5,
        is_lights_on=True,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, reasons = evaluate_direct_vpd_stress(state, {})
    assert len(observations) == 1
    assert "VPD out of range" in reasons[0][1]
    # Prob for seedling acclimation day stress is (0.95, 0.05) - from bayesian_data.py
    assert observations[0] == (0.95, 0.05)

    # 0.2 is SAFE for seedling Day 1 (-0.1, 0.3)
    state.vpd = 0.2
    observations, _ = evaluate_direct_vpd_stress(state, {})
    assert len(observations) == 0


def test_evaluate_optimal_vpd_seedling() -> None:
    """Test optimal VPD ranges for seedling stage."""
    # Seedling Day Optimal: (0.4, 0.8)
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=-1,
        seedling_days=1,
        clone_days=-1,
        vpd=0.1,
        is_lights_on=True,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, _ = evaluate_optimal_vpd(state, {})
    assert len(observations) == 1
    # Perfect range for seedling acclimation is (0.98, 0.10) based on PROB_VPD_OPTIMAL_SEEDLING_ACCLIMATION
    assert observations[0] == (0.98, 0.10)

    # 1.0 is OUT OF RANGE for optimal
    state.vpd = 1.0
    observations, _ = evaluate_optimal_vpd(state, {})
    assert len(observations) == 1
    assert observations[0] == PROB_VPD_STRESS_OUT_OF_RANGE


def test_evaluate_direct_humidity_stress_seedling() -> None:
    """Test humidity stress limits for seedling stage."""
    # Seedling high limit is 90
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=-1,
        seedling_days=1,
        clone_days=-1,
        humidity=92,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(observations) == 1
    assert "Humidity out of range (<95 or >100) (92)" in reasons[0][1]

    # 97 is SAFE for seedling Day 1 (95, 100)
    state.humidity = 97
    observations, _ = evaluate_direct_humidity_stress(state, {})
    assert len(observations) == 0


def test_evaluate_direct_humidity_stress_interpolation_seedling_to_veg() -> None:
    """Test interpolation of humidity stress from seedling to veg."""
    # Seedling (standard) limit = 90. Veg limit = 80.
    # Transition Window = 3 days.
    # veg_days = 1.5 -> factor = 0.5.
    # hum_max = 90 + (80-90)*0.5 = 85.
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=1.5,
        seedling_days=8,  # Must be > 7 to be in seedling_standard
        clone_days=-1,
        humidity=86,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(observations) == 1
    assert "Humidity out of range (<0.0 or >85.0) (86)" in reasons[0][1]

    state.humidity = 84
    observations, _ = evaluate_direct_humidity_stress(state, {})
    assert len(observations) == 0


def test_evaluate_optimal_co2_early_stages() -> None:
    """Test CO2 evaluation for early stages."""
    # Seedling 600 ppm -> ACCEPTABLE
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=-1,
        seedling_days=5,
        clone_days=-1,
        co2=600,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, _ = evaluate_optimal_co2(state, {})
    assert len(observations) == 1
    assert observations[0] == PROB_ACCEPTABLE

    # Clone 1200 ppm -> PERFECT
    state = MagicMock(
        spec=EnvironmentState,
        flower_days=-1,
        veg_days=-1,
        seedling_days=-1,
        clone_days=5,
        co2=1200,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, _ = evaluate_optimal_co2(state, {})
    assert len(observations) == 1
    assert observations[0] == (0.95, 0.20)  # PROB_PERFECT
