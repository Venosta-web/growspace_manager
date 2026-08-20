from typing import Any
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
    _sensor_instance = MagicMock()
    env_config: dict[str, Any] = {
        "humidity_sensor": "sensor.humidity",
        "humidity_trend_sensitivity": 0.5,
    }
    observations: list[tuple[float, float]] = []
    reasons: list[tuple[float, str]] = []
    trend_states: dict[str, str] = {}
    analyze_trend = AsyncMock(return_value={"trend": "rising"})

    # Create mock state with unsafe humidity (above safe_limit of 65 for Veg)
    state = MagicMock(spec=EnvironmentState, flower_days=-1, humidity=68)

    await _async_evaluate_fallback_mold_trend_analysis(
        env_config,
        "humidity",
        "humidity_trend",
        observations,
        reasons,
        trend_states,
        analyze_trend,
        state,
    )

    # Humidity trend is now ignored for risk probability (only tracked for UI)
    assert len(observations) == 0
    assert len(reasons) == 0
    assert trend_states["humidity_trend"] == "rising"
    # assert reasons[0][1] == "Humidity trend"
    # p_true = 0.5 + (0.5 * 0.45) = 0.725
    # assert observations[0][0] == pytest.approx(0.725)
    # p_false = 0.5 - (0.5 * 0.4) = 0.3
    # assert observations[0][1] == pytest.approx(0.3)


@pytest.mark.asyncio
async def test_async_evaluate_fallback_mold_trend_analysis_falling() -> None:
    """Test fallback mold trend analysis for falling VPD."""
    env_config: dict[str, Any] = {
        "vpd_sensor": "sensor.vpd",
        "vpd_trend_sensitivity": 0.5,
    }
    observations: list[tuple[float, float]] = []
    reasons: list[tuple[float, str]] = []
    trend_states: dict[str, str] = {}
    analyze_trend = AsyncMock(return_value={"trend": "falling"})

    # Create mock state (VPD trends are not gated)
    state = MagicMock(spec=EnvironmentState, flower_days=-1, humidity=50, vpd=0.4)

    await _async_evaluate_fallback_mold_trend_analysis(
        env_config,
        "vpd",
        "vpd_trend",
        observations,
        reasons,
        trend_states,
        analyze_trend,
        state,
    )

    assert len(observations) == 1
    assert len(reasons) == 1
    assert trend_states["vpd_trend"] == "falling"
    assert reasons[0][1] == "Vpd trend falling (Approaching 0.5kPa)"
    # p_true = 0.5 + (0.5 * 0.45) = 0.725
    assert observations[0][0] == pytest.approx(0.725)
    # p_false = 0.5 - (0.5 * 0.4) = 0.3
    assert observations[0][1] == pytest.approx(0.3)


def test_evaluate_direct_temp_stress_no_temp() -> None:
    """Test evaluate_direct_temp_stress when temperature is None."""
    state = MagicMock(spec=EnvironmentState, temp=None)
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_direct_temp_stress(state, env_config)
    assert observations == []
    assert reasons == []


@pytest.mark.parametrize(
    ("temp", "flower_days", "is_lights_on", "expected_reason", "expected_prob"),
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
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_direct_temp_stress(state, env_config)
    assert len(observations) == 1
    assert len(reasons) == 1
    assert expected_reason in reasons[0][1]
    assert observations[0] == expected_prob


def test_evaluate_direct_humidity_stress_no_humidity() -> None:
    """Test evaluate_direct_humidity_stress when humidity is None."""
    state = MagicMock(spec=EnvironmentState, humidity=None)
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_direct_humidity_stress(state, env_config)
    assert observations == []
    assert reasons == []


def test_evaluate_direct_humidity_stress_veg_early_high_humidity() -> None:
    """Test evaluate_direct_humidity_stress for veg_early and high humidity."""
    state = MagicMock(
        spec=EnvironmentState,
        humidity=85,
        flower_days=-1,
        veg_days=7,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_direct_humidity_stress(state, env_config)
    assert len(observations) == 1
    assert len(reasons) == 1
    assert "Humidity out of range (<0 or >80) (85)" in reasons[0][1]
    assert observations[0] == (0.80, 0.20)


def test_evaluate_direct_vpd_stress_no_vpd() -> None:
    """Test evaluate_direct_vpd_stress when VPD is None."""
    state = MagicMock(spec=EnvironmentState, vpd=None)
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_direct_vpd_stress(state, env_config)
    assert observations == []
    assert reasons == []


def test_evaluate_optimal_temperature_no_temp() -> None:
    """Test evaluate_optimal_temperature when temperature is None."""
    state = MagicMock(spec=EnvironmentState, temp=None)
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_optimal_temperature(state, env_config)
    assert observations == []
    assert reasons == []


def test_evaluate_optimal_co2_no_co2() -> None:
    """Test evaluate_optimal_co2 when CO2 is None."""
    state = MagicMock(spec=EnvironmentState, co2=None)
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_optimal_co2(state, env_config)
    assert observations == []
    assert reasons == []


@pytest.mark.parametrize(
    ("co2", "flower_days", "expected_prob", "expected_reason_substring"),
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
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
        veg_days=-1,
        seedling_days=-1,
        clone_days=-1,
    )
    env_config: dict[str, Any] = {}
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
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_optimal_vpd(state, env_config)
    assert observations == []
    assert reasons == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "sensor_key",
        "trend_state_value",
        "stats_change_value",
        "expected_trend",
        "expected_prob",
        "expected_reason",
    ),
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
    env_config: dict[str, Any] = {
        f"{sensor_key}_trend_sensor": f"sensor.{sensor_key}_trend",
        f"{sensor_key}_stats_sensor": f"sensor.{sensor_key}_stats",
    }
    observations: list[tuple[float, float]] = []
    reasons: list[tuple[float, str]] = []
    trend_states: dict[str, str] = {}

    get_state = MagicMock(return_value=None)
    if trend_state_value:
        trend_state = MagicMock(state=trend_state_value)
        get_state = MagicMock(return_value=trend_state)
    elif stats_change_value:
        env_config[f"{sensor_key}_trend_sensor"] = None
        stats_state = MagicMock(attributes={"change": stats_change_value})
        get_state = MagicMock(return_value=stats_state)

    # Create mock state with values that bypass danger zone gating
    state = MagicMock(spec=EnvironmentState, flower_days=-1, vpd=0.4, humidity=85)

    await _async_evaluate_external_mold_trend_sensor(
        get_state,
        env_config,
        sensor_key,
        f"{sensor_key}_trend",
        observations,
        reasons,
        trend_states,
        state,
    )

    assert len(observations) == 1
    assert len(reasons) == 1
    assert trend_states[f"{sensor_key}_trend"] == expected_trend
    assert observations[0] == expected_prob
    assert reasons[0][1] == expected_reason


@pytest.mark.asyncio
@pytest.mark.parametrize(
    (
        "test_sensor_key",
        "use_trend_sensor",
        "use_stats_sensor",
        "trend_state_value",
        "gradient",
        "stats_change",
        "manual_analysis_result",
        "expected_trend",
        "expected_prob",
        "expected_reason",
    ),
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
    async def side_effect(sensor_id, duration, threshold):
        if manual_analysis_result and sensor_id == f"sensor.{test_sensor_key}":
            return manual_analysis_result
        return {"trend": "stable", "crossed_threshold": False}

    analyze_trend_fn = AsyncMock(side_effect=side_effect)

    env_config_dict: dict[str, Any] = {
        "prob_trend_fast_rise": (0.95, 0.15),
        "prob_trend_slow_rise": (0.75, 0.30),
    }
    for key in ["temperature", "humidity", "vpd"]:
        env_config_dict[f"{key}_trend_sensor"] = (
            f"sensor.{key}_trend"
            if use_trend_sensor and key == test_sensor_key
            else None
        )
        env_config_dict[f"{key}_stats_sensor"] = (
            f"sensor.{key}_stats"
            if use_stats_sensor and key == test_sensor_key
            else None
        )
        env_config_dict[f"{key}_sensor"] = (
            f"sensor.{key}"
            if not (use_trend_sensor or use_stats_sensor) and key == test_sensor_key
            else None
        )
        env_config_dict[f"{key}_trend_sensitivity"] = 0.5

    mock_env_config = MagicMock()
    mock_env_config.to_dict.return_value = env_config_dict
    state = MagicMock()

    get_state = MagicMock(return_value=None)
    if use_trend_sensor:
        trend_state = MagicMock(
            state=trend_state_value, attributes={"gradient": gradient}
        )
        get_state = MagicMock(return_value=trend_state)
    elif use_stats_sensor:
        stats_state = MagicMock(attributes={"change": stats_change})
        get_state = MagicMock(return_value=stats_state)

    observations, reasons, trend_states = await async_evaluate_stress_trend(
        mock_env_config, get_state, analyze_trend_fn, state
    )

    for key in ["temperature", "humidity", "vpd"]:
        if key == test_sensor_key:
            assert trend_states[f"{key}_trend"] == expected_trend
        else:
            assert trend_states[f"{key}_trend"] == "stable"

    assert len(observations) == 1
    assert len(reasons) == 1
    assert reasons[0][1] == expected_reason


@pytest.mark.parametrize(
    (
        "temp",
        "flower_days",
        "is_lights_on",
        "expected_prob",
        "expected_reason_substring",
    ),
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
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_optimal_temperature(state, env_config)

    assert len(observations) == 1
    assert observations[0] == expected_prob

    if expected_reason_substring:
        assert len(reasons) == 1
        assert expected_reason_substring in reasons[0][1]
    else:
        assert len(reasons) == 0


@pytest.mark.asyncio
async def test_async_evaluate_fallback_mold_trend_analysis_veg_safe_zone() -> None:
    """Test that rising humidity in Veg safe zone does not trigger alert."""
    env_config: dict[str, Any] = {
        "humidity_sensor": "sensor.humidity",
        "humidity_trend_sensitivity": 0.5,
    }
    observations: list[tuple[float, float]] = []
    reasons: list[tuple[float, str]] = []
    trend_states: dict[str, str] = {}
    analyze_trend = AsyncMock(return_value={"trend": "rising"})

    # Create mock state with Veg stage and humidity in safe zone (< 65)
    state = MagicMock(spec=EnvironmentState, flower_days=-1, humidity=61)

    await _async_evaluate_fallback_mold_trend_analysis(
        env_config,
        "humidity",
        "humidity_trend",
        observations,
        reasons,
        trend_states,
        analyze_trend,
        state,
    )

    # No observation should be added because humidity is in safe zone
    assert len(observations) == 0
    assert len(reasons) == 0
    assert trend_states["humidity_trend"] == "rising"


@pytest.mark.asyncio
async def test_async_evaluate_fallback_mold_trend_analysis_late_flower_unsafe() -> None:
    """Test that rising humidity in Late Flower unsafe zone triggers alert."""
    env_config: dict[str, Any] = {
        "humidity_sensor": "sensor.humidity",
        "humidity_trend_sensitivity": 0.5,
    }
    observations: list[tuple[float, float]] = []
    reasons: list[tuple[float, str]] = []
    trend_states: dict[str, str] = {}
    analyze_trend = AsyncMock(return_value={"trend": "rising"})

    # Create mock state with Late Flower stage and humidity approaching danger zone (> 55)
    state = MagicMock(spec=EnvironmentState, flower_days=45, humidity=58)

    await _async_evaluate_fallback_mold_trend_analysis(
        env_config,
        "humidity",
        "humidity_trend",
        observations,
        reasons,
        trend_states,
        analyze_trend,
        state,
    )

    # Observation should be added because humidity is approaching danger zone
    # Observation should NOT be added (humidity trends ignored for risk)
    assert len(observations) == 0
    assert len(reasons) == 0
    assert trend_states["humidity_trend"] == "rising"
    # assert reasons[0][1] == "Humidity trend"
    # p_true = 0.5 + (0.5 * 0.45) = 0.725
    # assert observations[0][0] == pytest.approx(0.725)
    # p_false = 0.5 - (0.5 * 0.4) = 0.3
    # assert observations[0][1] == pytest.approx(0.3)


@pytest.mark.parametrize(
    ("flower_days", "vpd", "expected_status", "expected_limit"),
    [
        (
            19,
            0.82,
            "stress",
            0.83,
        ),  # Early->Mid transition (factor 0.33), stress_low=0.83
        (19, 1.02, "mild", 1.03),  # Early->Mid transition (factor 0.33), mild_low=1.03
        (
            40,
            0.92,
            "stress",
            0.93,
        ),  # Mid->Late transition (factor 0.33), stress_low=0.93
        (40, 1.12, "mild", 1.13),  # Mid->Late transition (factor 0.33), mild_low=1.13
    ],
)
def test_evaluate_direct_vpd_stress_interpolation(
    flower_days, vpd, expected_status, expected_limit
) -> None:
    """Test evaluate_direct_vpd_stress interpolation between flower stages."""
    state = MagicMock(
        spec=EnvironmentState,
        vpd=vpd,
        flower_days=flower_days,
        is_lights_on=True,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
        veg_days=-1,
        seedling_days=-1,
        clone_days=-1,
    )
    env_config: dict[str, Any] = {}
    observations, reasons = evaluate_direct_vpd_stress(state, env_config)

    assert len(observations) == 1
    # Check if we got the expected status in the reason
    assert "VPD out of range" in reasons[0][1]

    # Verify probability corresponds to the expected status
    # Factor is 0.33, so it should use probabilities from stage_a
    # For 19: stage_a is early. For 40: stage_a is mid.
    if flower_days == 19:
        expected_prob = (0.85, 0.15) if expected_status == "stress" else (0.60, 0.30)
    else:
        expected_prob = (0.88, 0.14) if expected_status == "stress" else (0.62, 0.29)

    assert observations[0] == expected_prob


def test_evaluate_direct_humidity_stress_interpolation() -> None:
    """Test evaluate_direct_humidity_stress interpolation between veg and flower_early."""
    # Transition Veg -> Early Flower (factor 0.0 since days=0 is strictly veg)
    # Wait, if days=1, factor = (1 - 0) / 3? No, b1=21 in const.py but 7 in environment_analyzer?
    # Actually, calculate_stage_transition(state.flower_days)
    # If flower_days=1, factor = (1 - (21-3)) / 3 is negative? No, it returns 0.0.

    # Transition Early -> Mid: b1=21, window=3.
    # days=20 -> factor = (20 - 18) / 3 = 0.67
    # stage_a=early, stage_b=mid
    # Early limits: (45, 60) (since we default early to mid constants)
    # Mid limits: (45, 60)
    # Late limits: (40, 60)

    # Transition Mid -> Late: b2=42, window=3.
    # days=40 -> factor = (40 - 39) / 3 = 0.33
    # stage_a=mid, stage_b=late
    # low_a=45, low_b=40 -> low = 45 + (40-45)*0.33 = 43.35

    state = MagicMock(
        spec=EnvironmentState,
        humidity=43.5,
        flower_days=40,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
        veg_days=-1,
        seedling_days=-1,
        clone_days=-1,
    )
    observations, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(observations) == 0

    state.humidity = 43.0
    observations, reasons = evaluate_direct_humidity_stress(state, {})
    # 43.0 is < 43.35, so it should be STRESS.
    assert len(observations) == 1
    assert "Humidity out of range (<43.35 or >60.0) (43.0)" in reasons[0][1]


@pytest.mark.parametrize(
    ("flower_days", "veg_days", "seedling_days", "clone_days", "expected_key"),
    [
        (50, 0, 0, 0, "flower_late"),
        (25, 0, 0, 0, "flower_mid"),
        (8, 0, 0, 0, "flower_early"),
        (5, 0, 0, 0, "flower_early"),
        (0, 7, 0, 0, "veg"),
        (0, 0, 5, 0, "seedling"),
        (0, 0, 0, 3, "clone"),
        (0, 0, 0, 0, "veg"),
        # Add missing stages
        (0, 0, 0, 0, "mother"),
        (0, 0, 0, 0, "dry"),
        (0, 0, 0, 0, "cure"),
    ],
)
def test_determine_stage_key(
    flower_days, veg_days, seedling_days, clone_days, expected_key
) -> None:
    """Test _determine_stage_key for all growth stages."""

    state = MagicMock(
        spec=EnvironmentState,
        flower_days=flower_days,
        veg_days=veg_days,
        seedling_days=seedling_days,
        clone_days=clone_days,
        dry_days=5 if expected_key == "dry" else -1,
        cure_days=5 if expected_key == "cure" else -1,
        mother_days=5 if expected_key == "mother" else -1,
    )
    assert _determine_stage_key(state) == expected_key


def test_evaluate_direct_humidity_stress_mid_to_late_transition() -> None:
    """Test evaluate_direct_humidity_stress for mid to late flower transition."""
    # Flower days = 41 (b2=42, window=3). factor = (41-39)/3 = 0.67 (> 0.5)
    # stage_a = Mid, stage_b = Late.
    state = MagicMock(
        spec=EnvironmentState,
        humidity=65,
        flower_days=41,
        veg_days=-1,
        seedling_days=-1,
        clone_days=-1,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, reasons = evaluate_direct_humidity_stress(state, {})
    assert len(observations) == 1
    assert observations[0] == (0.85, 0.15)  # PROB_HUMIDITY_FLOWER_LATE_OUT_OF_RANGE
    assert "Humidity out of range" in reasons[0][1]


def test_evaluate_optimal_co2_seedling_clone_ranges() -> None:
    """Test evaluate_optimal_co2 for seedling/clone specific ranges."""
    # Seedling stage (seedling_days > 0, flower_days = 0)
    state = MagicMock(
        spec=EnvironmentState,
        seedling_days=5,
        flower_days=-1,
        veg_days=-1,
        clone_days=-1,
        co2=900,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )
    observations, reasons = evaluate_optimal_co2(state, {})
    assert len(observations) == 1
    assert observations[0] == PROB_GOOD

    # Out of range low
    state.co2 = 300
    observations, reasons = evaluate_optimal_co2(state, {})
    assert len(observations) == 1
    assert observations[0] == PROB_STRESS_OUT_OF_RANGE
    assert "CO2 Low" in reasons[0][1]

    # Out of range high
    state.co2 = 1700
    observations, reasons = evaluate_optimal_co2(state, {})
    assert len(observations) == 1
    assert observations[0] == PROB_STRESS_OUT_OF_RANGE
    assert "CO2 High" in reasons[0][1]
