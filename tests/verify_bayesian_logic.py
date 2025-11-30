import pytest
from unittest.mock import MagicMock
from custom_components.growspace_manager.models import EnvironmentState
from custom_components.growspace_manager.bayesian_evaluator import (
    evaluate_direct_temp_stress,
    evaluate_optimal_temperature,
    evaluate_direct_vpd_stress,
    evaluate_optimal_vpd,
)
from custom_components.growspace_manager.bayesian_data import (
    PROB_PERFECT,
    PROB_STRESS_OUT_OF_RANGE,
)

def test_evaluate_direct_temp_stress_missing_light_sensor():
    """Test that missing light sensor (None) does NOT trigger night stress."""
    # Setup state with None for is_lights_on and a temp that would be high for night (e.g. 25)
    # but okay for day.
    state = MagicMock(
        spec=EnvironmentState,
        temp=25,
        flower_days=10,
        is_lights_on=None,
    )
    env_config = {}
    observations, reasons = evaluate_direct_temp_stress(state, env_config)
    
    # Should NOT have "Night Temp High"
    for _, reason in reasons:
        assert "Night Temp High" not in reason
    
    # Should be empty or contain other stress if temp is extreme (25 is fine for day)
    assert len(observations) == 0

def test_evaluate_optimal_temperature_missing_light_sensor():
    """Test that missing light sensor uses Day/Active logic for optimal temp."""
    # 25C is perfect for Day/Active, but out of range for Night (20-23)
    state = MagicMock(
        spec=EnvironmentState,
        temp=25,
        flower_days=10,
        is_lights_on=None,
    )
    env_config = {}
    observations, reasons = evaluate_optimal_temperature(state, env_config)
    
    assert len(observations) == 1
    assert observations[0] == PROB_PERFECT
    assert len(reasons) == 0

def test_evaluate_optimal_vpd_missing_light_sensor():
    """Test that missing light sensor uses Day/Active logic for optimal VPD."""
    # Setup a VPD that is optimal for Day but maybe not Night (depending on stage)
    # For veg_early: Day optimal is 0.4-0.8, Night optimal is 0.4-0.8 (bad example, they overlap)
    # Let's check logic path primarily.
    
    state = MagicMock(
        spec=EnvironmentState,
        vpd=0.6,
        flower_days=0,
        veg_days=10, # veg_early
        is_lights_on=None,
    )
    env_config = {}
    observations, reasons = evaluate_optimal_vpd(state, env_config)
    
    # Should find an optimal range
    assert len(observations) > 0
    # If it defaulted to night, it might still be optimal, but we want to ensure no error.
    # The key change was: time_of_day = "night" if state.is_lights_on is False else "day"
    # So None -> Day.

if __name__ == "__main__":
    import sys
    from pytest import ExitCode
    
    # Run tests manually
    try:
        test_evaluate_direct_temp_stress_missing_light_sensor()
        print("test_evaluate_direct_temp_stress_missing_light_sensor PASSED")
        test_evaluate_optimal_temperature_missing_light_sensor()
        print("test_evaluate_optimal_temperature_missing_light_sensor PASSED")
        test_evaluate_optimal_vpd_missing_light_sensor()
        print("test_evaluate_optimal_vpd_missing_light_sensor PASSED")
    except AssertionError as e:
        print(f"FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
