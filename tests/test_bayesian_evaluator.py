from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.bayesian_data import (
    PROB_ACCEPTABLE,
    PROB_GOOD,
    PROB_PERFECT,
    PROB_STRESS_OUT_OF_RANGE,
)
from custom_components.growspace_manager.bayesian_evaluator import (
    _async_evaluate_external_mold_trend_sensor,
    _async_evaluate_fallback_mold_trend_analysis,
    _determine_stage_key,
    async_evaluate_stress_trend,
    evaluate_direct_humidity_stress,
    evaluate_direct_temp_stress,
    evaluate_direct_vpd_stress,
    evaluate_optimal_co2,
    evaluate_optimal_temperature,
    evaluate_optimal_vpd,
)
from custom_components.growspace_manager.models import EnvironmentState


@pytest.mark.asyncio
async def test_async_evaluate_fallback_mold_trend_analysis_rising() -> None:
    """Test fallback mold trend analysis for rising humidity."""
    sensor_instance = MagicMock()
    env_config = {
        "humidity_sensor": "sensor.humidity",
        "humidity_trend_sensitivity": 0.5,
    }
    observations = []
    reasons = []
    trend_states = {}
    analyze_trend = AsyncMock(return_value={"trend": "rising"})

    await _async_evaluate_fallback_mold_trend_analysis(
        sensor_instance,
        env_config,
        "humidity",
        "humidity_trend",
        observations,
        reasons,
        trend_states,
        analyze_trend,
    )

    assert len(observations) == 1
    assert len(reasons) == 1
    assert trend_states["humidity_trend"] == "rising"
    assert reasons[0][1] == "Humidity trend"
    # p_true = 0.5 + (0.5 * 0.45) = 0.725
    assert observations[0][0] == pytest.approx(0.725)
    # p_false = 0.5 - (0.5 * 0.4) = 0.3
    assert observations[0][1] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_async_evaluate_fallback_mold_trend_analysis_falling() -> None:
    """Test fallback mold trend analysis for falling VPD."""
    sensor_instance = MagicMock()
    env_config = {
        "vpd_sensor": "sensor.vpd",
        "vpd_trend_sensitivity": 0.5,
    }
    observations = []
    reasons = []
    trend_states = {}
    analyze_trend = AsyncMock(return_value={"trend": "falling"})

    await _async_evaluate_fallback_mold_trend_analysis(
        sensor_instance,
        env_config,
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        analyze_trend,
    )

    assert len(observations) == 1
    assert len(reasons) == 1
    assert trend_states["vpd_trend"] == "falling"
    assert reasons[0][1] == "Vpd trend"
    # p_true = 0.5 + (0.5 * 0.45) = 0.725
    assert observations[0][0] == pytest.approx(0.725)
    # p_false = 0.5 - (0.5 * 0.4) = 0.3
    assert observations[0][1] == pytest.approx(0.3)


def test_evaluate_direct_temp_stress_no_temp() -> None:
    """Test evaluate_direct_temp_stress when temperature is None."""
    state = MagicMock(spec=EnvironmentState, temp=None)
    env_config = {}
    observations, reasons = evaluate_direct_temp_stress(state, env_config)
    assert observations == []
    assert reasons == []


@pytest.mark.parametrize(
    "temp, flower_days, is_lights_on, expected_reason, expected_prob",
    [
        (33, 10, True, "Extreme Heat", (0.98, 0.05)),
        (31, 10, True, "High Heat", (0.85, 0.15)),
        (28, 50, True, "Temp Warm", (0.70, 0.30)),
        (29, 10, True, "Temp Warm", (0.65, 0.30)),
        (14, 10, True, "Extreme Cold", (0.95, 0.08)),
        (17, 10, True, "Temp Cold", (0.80, 0.20)),
        (25, 10, False, "Night Temp High", (0.80, 0.20)),
    ],
)
def test_evaluate_direct_temp_stress_branches(
    temp, flower_days, is_lights_on, expected_reason, expected_prob
) -> None:
    """Test all branches of evaluate_direct_temp_stress."""
    state = MagicMock(
        spec=EnvironmentState,
        temp=temp,
        flower_days=flower_days,
        is_lights_on=is_lights_on,
    )
    env_config = {}
    observations, reasons = evaluate_direct_temp_stress(state, env_config)
    assert len(observations) == 1
    assert len(reasons) == 1
    assert expected_reason in reasons[0][1]
    assert observations[0] == expected_prob


def test_evaluate_direct_humidity_stress_no_humidity() -> None:
    """Test evaluate_direct_humidity_stress when humidity is None."""
    state = MagicMock(spec=EnvironmentState, humidity=None)
    env_config = {}
    observations, reasons = evaluate_direct_humidity_stress(state, env_config)
    assert observations == []
    assert reasons == []


def test_evaluate_direct_humidity_stress_veg_early_high_humidity() -> None:
    """Test evaluate_direct_humidity_stress for veg_early and high humidity."""
    state = MagicMock(spec=EnvironmentState, humidity=85, flower_days=0, veg_days=7)
    env_config = {}
    observations, reasons = evaluate_direct_humidity_stress(state, env_config)
    assert len(observations) == 1
    assert len(reasons) == 1
    assert "Humidity High (85)" in reasons[0][1]
    assert observations[0] == (0.80, 0.20)


def test_evaluate_direct_vpd_stress_no_vpd() -> None:
    """Test evaluate_direct_vpd_stress when VPD is None."""
    state = MagicMock(spec=EnvironmentState, vpd=None)
    env_config = {}
    observations, reasons = evaluate_direct_vpd_stress(state, env_config)
    assert observations == []
    assert reasons == []


def test_evaluate_optimal_temperature_no_temp() -> None:
    """Test evaluate_optimal_temperature when temperature is None."""
    state = MagicMock(spec=EnvironmentState, temp=None)
    env_config = {}
    observations, reasons = evaluate_optimal_temperature(state, env_config)
    assert observations == []
    assert reasons == []


def test_evaluate_optimal_co2_no_co2() -> None:
    """Test evaluate_optimal_co2 when CO2 is None."""
    state = MagicMock(spec=EnvironmentState, co2=None)
    env_config = {}
    observations, reasons = evaluate_optimal_co2(state, env_config)
    assert observations == []
    assert reasons == []


@pytest.mark.parametrize(
    "co2, flower_days, expected_prob, expected_reason_substring",
    [
        # Late Flower Logic (flower_days >= 42)
        (600, 45, (0.90, 0.25), None),  # 400-800 range
        (1000, 45, (0.4, 0.6), None),  # 800-1200 range
        (300, 45, [], None),  # outside range low, no observation
        (1300, 45, [], None),  # outside range high, no observation
        # Normal/Veg/Early Flower logic (flower_days < 42)
        (1200, 10, PROB_PERFECT, None),  # 1000-1400 range
        (900, 10, PROB_GOOD, None),  # 800-1500 range
        (500, 10, PROB_ACCEPTABLE, None),  # 400-600 range
        (300, 10, PROB_STRESS_OUT_OF_RANGE, "CO2 Low"),  # out of range low
        (1600, 10, PROB_STRESS_OUT_OF_RANGE, "CO2 High"),  # out of range high
    ],
)
def test_evaluate_optimal_co2_branches(
    co2, flower_days, expected_prob, expected_reason_substring
) -> None:
    """Test all branches of evaluate_optimal_co2."""
    state = MagicMock(
        spec=EnvironmentState,
        co2=co2,
        flower_days=flower_days,
    )
    env_config = {}
    observations, reasons = evaluate_optimal_co2(state, env_config)

    if expected_prob == []:
        assert observations == []
    else:
        assert len(observations) == 1
        assert observations[0] == expected_prob

    if expected_reason_substring:
        assert len(reasons) == 1
        assert expected_reason_substring in reasons[0][1]
    else:
        assert len(reasons) == 0


def test_evaluate_optimal_vpd_no_vpd() -> None:
    """Test evaluate_optimal_vpd when VPD is None."""
    state = MagicMock(spec=EnvironmentState, vpd=None)
    env_config = {}
    observations, reasons = evaluate_optimal_vpd(state, env_config)
    assert observations == []
    assert reasons == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sensor_key, trend_state_value, stats_change_value, expected_trend, expected_prob, expected_reason",
    [
        # Test trend_sensor_id branch
        ("humidity", "on", None, "rising", (0.90, 0.20), "Humidity rising"),
        ("vpd", "off", None, "falling", (0.90, 0.20), "Vpd falling"),
        # Test stats_sensor_id branch
        ("humidity", None, 1.1, "rising", (0.85, 0.25), "Humidity rising"),
        ("vpd", None, -0.2, "falling", (0.85, 0.25), "Vpd falling"),
    ],
)
async def test_async_evaluate_external_mold_trend_sensor(
    sensor_key,
    trend_state_value,
    stats_change_value,
    expected_trend,
    expected_prob,
    expected_reason,
) -> None:
    """Test _async_evaluate_external_mold_trend_sensor for all scenarios."""
    sensor_instance = MagicMock()
    sensor_instance.hass = MagicMock()

    env_config = {
        f"{sensor_key}_trend_sensor": f"sensor.{sensor_key}_trend",
        f"{sensor_key}_stats_sensor": f"sensor.{sensor_key}_stats",
    }
    observations = []
    reasons = []
    trend_states = {}

    if trend_state_value:
        trend_state = MagicMock(state=trend_state_value)
        sensor_instance.hass.states.get.return_value = trend_state
    elif stats_change_value:
        # Make trend_sensor_id None to test the stats_sensor_id branch
        env_config[f"{sensor_key}_trend_sensor"] = None
        stats_state = MagicMock(attributes={"change": stats_change_value})
        sensor_instance.hass.states.get.return_value = stats_state

    await _async_evaluate_external_mold_trend_sensor(
        sensor_instance,
        env_config,
        sensor_key,
        f"{sensor_key}_trend",
        observations,
        reasons,
        trend_states,
    )

    assert len(observations) == 1
    assert len(reasons) == 1
    assert trend_states[f"{sensor_key}_trend"] == expected_trend
    assert observations[0] == expected_prob
    assert reasons[0][1] == expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "test_sensor_key, use_trend_sensor, use_stats_sensor, trend_state_value, gradient, stats_change, manual_analysis_result, expected_trend, expected_prob, expected_reason",
    [
        # Trend Sensor Logic
        (
            "temperature",
            True,
            False,
            "on",
            0.2,
            None,
            None,
            "rising",
            (0.95, 0.15),
            "Temperature rising fast",
        ),
        (
            "humidity",
            True,
            False,
            "on",
            0.05,
            None,
            None,
            "rising",
            (0.75, 0.30),
            "Humidity rising",
        ),
        # Stats Sensor Logic
        (
            "vpd",
            False,
            True,
            None,
            None,
            0.3,
            None,
            "rising",
            (0.85, 0.25),
            "Vpd rising",
        ),
        (
            "temperature",
            False,
            True,
            None,
            None,
            1.1,
            None,
            "rising",
            (0.85, 0.25),
            "Temperature rising",
        ),
        # Fallback Manual Analysis Logic
        (
            "humidity",
            False,
            False,
            None,
            None,
            None,
            {"trend": "rising", "crossed_threshold": True},
            "rising",
            (0.725, 0.3),
            "Humidity rising",
        ),
    ],
)
async def test_async_evaluate_stress_trend(
    test_sensor_key,
    use_trend_sensor,
    use_stats_sensor,
    trend_state_value,
    gradient,
    stats_change,
    manual_analysis_result,
    expected_trend,
    expected_prob,
    expected_reason,
) -> None:
    """Test all branches of async_evaluate_stress_trend."""
    sensor_instance = MagicMock()
    sensor_instance.hass = MagicMock()

    async def side_effect(sensor_id, duration, threshold):
        if manual_analysis_result and sensor_id == f"sensor.{test_sensor_key}":
            return manual_analysis_result
        return {"trend": "stable", "crossed_threshold": False}

    sensor_instance.async_analyze_sensor_trend = AsyncMock(side_effect=side_effect)

    env_config = {
        "prob_trend_fast_rise": (0.95, 0.15),
        "prob_trend_slow_rise": (0.75, 0.30),
    }
    for key in ["temperature", "humidity", "vpd"]:
        env_config[f"{key}_trend_sensor"] = (
            f"sensor.{key}_trend"
            if use_trend_sensor and key == test_sensor_key
            else None
        )
        env_config[f"{key}_stats_sensor"] = (
            f"sensor.{key}_stats"
            if use_stats_sensor and key == test_sensor_key
            else None
        )
        env_config[f"{key}_sensor"] = (
            f"sensor.{key}"
            if not (use_trend_sensor or use_stats_sensor) and key == test_sensor_key
            else None
        )
        env_config[f"{key}_trend_sensitivity"] = 0.5

    sensor_instance.env_config = env_config
    state = MagicMock()

    if use_trend_sensor:
        trend_state = MagicMock(
            state=trend_state_value, attributes={"gradient": gradient}
        )
        sensor_instance.hass.states.get.return_value = trend_state
    elif use_stats_sensor:
        stats_state = MagicMock(attributes={"change": stats_change})
        sensor_instance.hass.states.get.return_value = stats_state

    observations, reasons, trend_states = await async_evaluate_stress_trend(
        sensor_instance, state
    )

    for key in ["temperature", "humidity", "vpd"]:
        if key == test_sensor_key:
            assert trend_states[f"{key}_trend"] == expected_trend
        else:
            assert trend_states[f"{key}_trend"] == "stable"

    assert len(observations) == 1
    assert len(reasons) == 1
    assert reasons[0][1] == expected_reason


def test_determine_stage_key_none() -> None:
    """Test _determine_stage_key when no stage key is determined."""
    state = MagicMock(spec=EnvironmentState, flower_days=-1, veg_days=0)
    result = _determine_stage_key(state)
    assert result is None


@pytest.mark.parametrize(
    "temp, flower_days, is_lights_on, expected_prob, expected_reason_substring",
    [
        # Case A: Lights ON & Late Flower (Days >= 42)
        (24, 45, True, PROB_PERFECT, None),  # PROB_PERFECT
        # Case B: Lights ON & Normal (Days < 42 or Veg)
        (25, 10, True, PROB_PERFECT, None),  # PROB_PERFECT
        (27, 10, True, PROB_GOOD, None),  # PROB_GOOD
        (21, 10, True, PROB_ACCEPTABLE, None),  # PROB_ACCEPTABLE
        (
            19,
            10,
            True,
            PROB_STRESS_OUT_OF_RANGE,
            "Temp out of range",
        ),  # out of range low
        (
            30,
            10,
            True,
            PROB_STRESS_OUT_OF_RANGE,
            "Temp out of range",
        ),  # out of range high
        # Case C: Lights OFF (Nighttime)
        (21, 10, False, PROB_PERFECT, None),  # PROB_PERFECT
        (
            18,
            10,
            False,
            PROB_STRESS_OUT_OF_RANGE,
            "Night temp out of range",
        ),  # out of range low
        (
            25,
            10,
            False,
            PROB_STRESS_OUT_OF_RANGE,
            "Night temp out of range",
        ),  # out of range high
    ],
)
def test_evaluate_optimal_temperature_all_branches(
    temp, flower_days, is_lights_on, expected_prob, expected_reason_substring
) -> None:
    """Test all branches of evaluate_optimal_temperature."""
    state = MagicMock(
        spec=EnvironmentState,
        temp=temp,
        flower_days=flower_days,
        is_lights_on=is_lights_on,
    )
    env_config = {}
    observations, reasons = evaluate_optimal_temperature(state, env_config)

    assert len(observations) == 1
    assert observations[0] == expected_prob

    if expected_reason_substring:
        assert len(reasons) == 1
        assert expected_reason_substring in reasons[0][1]
    else:
        assert len(reasons) == 0
