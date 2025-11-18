from __future__ import annotations

import logging
from collections.abc import Awaitable
from typing import TYPE_CHECKING, Callable

from homeassistant.core import State

from .bayesian_data import (
    PROB_ACCEPTABLE,
    PROB_GOOD,
    PROB_PERFECT,
    PROB_STRESS_OUT_OF_RANGE,
    PROB_VPD_STRESS_OUT_OF_RANGE,
    VPD_OPTIMAL_THRESHOLDS,
    VPD_STRESS_THRESHOLDS,
)
from .models import EnvironmentState

if TYPE_CHECKING:
    from .binary_sensor import BayesianEnvironmentSensor

_LOGGER = logging.getLogger(__name__)

# Type aliases for readability
Obs = tuple[float, float]
Reason = tuple[float, str]
ObservationList = list[Obs]
ReasonList = list[Reason]

# =========================================================================
# HELPER: VPD STAGE THRESHOLD LOOKUP
# =========================================================================


def _determine_stage_key(state: EnvironmentState) -> str | None:
    """Determine the current grow stage key."""
    if state.flower_days == 0 and state.veg_days < 14:
        return "veg_early"
    if state.flower_days == 0 and state.veg_days >= 14:
        return "veg_late"
    if 0 < state.flower_days < 42:
        return "flower_early"
    if state.flower_days >= 42:
        return "flower_late"
    return None


# =========================================================================
# STRESS SENSOR EVALUATION
# =========================================================================


async def async_evaluate_stress_trend(
    sensor_instance: BayesianEnvironmentSensor, state: EnvironmentState
) -> tuple[ObservationList, ReasonList, dict[str, str]]:
    """Evaluate rising trends for temperature, humidity, and VPD from sensors/history."""
    observations: ObservationList = []
    reasons: ReasonList = []
    trend_states: dict[str, str] = {}
    env_config = sensor_instance.env_config

    trend_states["temperature_trend"] = "stable"
    trend_states["humidity_trend"] = "stable"
    trend_states["vpd_trend"] = "stable"

    # Define common variables and helpers outside the loop for cleaner logic
    analyze_trend: Callable[[str, int, float], Awaitable[dict]] = (
        sensor_instance._async_analyze_sensor_trend
    )

    # --- Trend Analysis Logic (Moved from BayesianStressSensor) ---
    for sensor_key, trend_key in [
        ("temperature", "temperature_trend"),
        ("humidity", "humidity_trend"),
        ("vpd", "vpd_trend"),
    ]:
        trend_sensor_id = env_config.get(f"{sensor_key}_trend_sensor")
        stats_sensor_id = env_config.get(f"{sensor_key}_stats_sensor")

        # --- External Trend Sensor Logic ---
        if trend_sensor_id:
            trend_state: State | None = sensor_instance.hass.states.get(trend_sensor_id)
            if trend_state and trend_state.state == "on":  # Rising trend
                trend_states[trend_key] = "rising"
                gradient = trend_state.attributes.get("gradient", 0)
                prob = (
                    env_config.get("prob_trend_fast_rise", (0.95, 0.15))
                    if gradient > 0.1
                    else env_config.get("prob_trend_slow_rise", (0.75, 0.30))
                )
                observations.append(prob)
                reason_suffix = " fast" if gradient > 0.1 else ""
                reasons.append(
                    (prob[0], f"{sensor_key.capitalize()} rising{reason_suffix}")
                )

        elif stats_sensor_id:
            stats_state: State | None = sensor_instance.hass.states.get(stats_sensor_id)
            if (
                stats_state
                and (change := stats_state.attributes.get("change")) is not None
            ):
                threshold = 0.2 if sensor_key == "vpd" else 1.0
                if change > threshold:
                    trend_states[trend_key] = "rising"
                    prob = (0.85, 0.25)
                    observations.append(prob)
                    reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

        else:  # Fallback to manual analysis (Requires await)
            duration = env_config.get(f"{sensor_key}_trend_duration", 30)
            threshold = env_config.get(f"{sensor_key}_trend_threshold", 26.0)
            sensitivity = env_config.get(f"{sensor_key}_trend_sensitivity", 0.5)
            if env_config.get(f"{sensor_key}_sensor"):
                analysis = await analyze_trend(
                    env_config[f"{sensor_key}_sensor"], duration, threshold
                )
                trend_states[trend_key] = analysis["trend"]
                if analysis["trend"] == "rising" and analysis["crossed_threshold"]:
                    p_true = 0.5 + (sensitivity * 0.45)
                    p_false = 0.5 - (sensitivity * 0.4)
                    prob = (p_true, p_false)
                    observations.append(prob)
                    reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

    return observations, reasons, trend_states


async def _async_evaluate_external_mold_trend_sensor(
    sensor_instance: BayesianEnvironmentSensor,
    env_config: dict,
    sensor_key: str,
    trend_key: str,
    observations: ObservationList,
    reasons: ReasonList,
    trend_states: dict[str, str],
) -> None:
    """Evaluate external trend sensors for mold risk (humidity and VPD)."""
    trend_sensor_id = env_config.get(f"{sensor_key}_trend_sensor")
    stats_sensor_id = env_config.get(f"{sensor_key}_stats_sensor")

    if trend_sensor_id:
        trend_state: State | None = sensor_instance.hass.states.get(trend_sensor_id)
        if trend_state and trend_state.state == ("on" if sensor_key == "humidity" else "off"):
            trend_states[trend_key] = "rising" if sensor_key == "humidity" else "falling"
            prob = (0.90, 0.20)
            observations.append(prob)
            reasons.append((prob[0], f"{sensor_key.capitalize()} {"rising" if sensor_key == "humidity" else "falling"}"))
    elif stats_sensor_id:
        stats_state: State | None = sensor_instance.hass.states.get(stats_sensor_id)
        if (
            stats_state
            and (change := stats_state.attributes.get("change")) is not None
        ):
            if (sensor_key == "humidity" and change > 1.0) or (
                sensor_key == "vpd" and change < -0.1
            ):
                trend_states[trend_key] = "rising" if sensor_key == "humidity" else "falling"
                prob = (0.85, 0.25)
                observations.append(prob)
                reasons.append((prob[0], f"{sensor_key.capitalize()} {"rising" if sensor_key == "humidity" else "falling"}"))


async def _async_evaluate_fallback_mold_trend_analysis(
    sensor_instance: BayesianEnvironmentSensor,
    env_config: dict,
    sensor_key: str,
    trend_key: str,
    observations: ObservationList,
    reasons: ReasonList,
    trend_states: dict[str, str],
    analyze_trend: Callable[[str, int, float], Awaitable[dict]],
) -> None:
    """Perform fallback manual trend analysis for mold risk."""
    if not env_config.get(f"{sensor_key}_trend_sensor") and not env_config.get(
        f"{sensor_key}_stats_sensor"
    ):
        duration = env_config.get(f"{sensor_key}_trend_duration", 30)
        threshold = 101 if sensor_key == "humidity" else -1
        sensitivity = env_config.get(f"{sensor_key}_trend_sensitivity", 0.5)
        if env_config.get(f"{sensor_key}_sensor"):
            analysis = await analyze_trend(
                env_config[f"{sensor_key}_sensor"], duration, threshold
            )
            trend_states[f"{sensor_key}_trend"] = analysis["trend"]
            if (sensor_key == "humidity" and analysis["trend"] == "rising") or (
                sensor_key == "vpd" and analysis["trend"] == "falling"
            ):
                p_true = 0.5 + (sensitivity * 0.45)
                p_false = 0.5 - (sensitivity * 0.4)
                prob = (p_true, p_false)
                observations.append(prob)
                reasons.append((prob[0], f"{sensor_key.capitalize()} trend"))


async def async_evaluate_mold_risk_trend(
    sensor_instance: BayesianEnvironmentSensor, state: EnvironmentState
) -> tuple[ObservationList, ReasonList, dict[str, str]]:
    """Evaluate trends for humidity and VPD for mold risk."""
    observations: ObservationList = []
    reasons: ReasonList = []
    trend_states: dict[str, str] = {}
    env_config = sensor_instance.env_config

    trend_states["humidity_trend"] = "stable"
    trend_states["vpd_trend"] = "stable"

    analyze_trend: Callable[[str, int, float], Awaitable[dict]] = (
        sensor_instance._async_analyze_sensor_trend
    )

    for sensor_key, trend_key in [
        ("humidity", "humidity_trend"),
        ("vpd", "vpd_trend"),
    ]:
        await _async_evaluate_external_mold_trend_sensor(
            sensor_instance, env_config, sensor_key, trend_key, observations, reasons, trend_states
        )
        await _async_evaluate_fallback_mold_trend_analysis(
            sensor_instance, env_config, sensor_key, trend_key, observations, reasons, trend_states, analyze_trend
        )

    return observations, reasons, trend_states


def evaluate_direct_temp_stress(
    state: EnvironmentState, env_config: dict
) -> tuple[ObservationList, ReasonList]:
    """Evaluate temperature against extreme/out-of-range stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.temp is None:
        return observations, reasons

    temp = state.temp

    # 1: Night High Temp Check (Independent IF)
    if not state.is_lights_on and temp > 24:
        prob = env_config.get("prob_night_temp_high", (0.80, 0.20))
        observations.append(prob)
        reasons.append((prob[0], f"Night Temp High ({temp})"))

    # 2: General Stress/Warm/Cold Checks (Cascaded IF/ELIF Chain)
    if temp > 32:
        prob = env_config.get("prob_temp_extreme_heat", (0.98, 0.05))
        observations.append(prob)
        reasons.append((prob[0], f"Extreme Heat ({temp})"))
    elif temp > 30:
        prob = env_config.get("prob_temp_high_heat", (0.85, 0.15))
        observations.append(prob)
        reasons.append((prob[0], f"High Heat ({temp})"))
    elif state.flower_days >= 42 and temp > 27:
        prob = (0.70, 0.30)
        observations.append(prob)
        reasons.append((prob[0], f"Temp Warm ({temp})"))
    elif temp > 28:
        prob = env_config.get("prob_temp_warm", (0.65, 0.30))
        observations.append(prob)
        reasons.append((prob[0], f"Temp Warm ({temp})"))
    elif temp < 15:
        prob = env_config.get("prob_temp_extreme_cold", (0.95, 0.08))
        observations.append(prob)
        reasons.append((prob[0], f"Extreme Cold ({temp})"))
    elif temp < 18:
        prob = env_config.get("prob_temp_cold", (0.80, 0.20))
        observations.append(prob)
        reasons.append((prob[0], f"Temp Cold ({temp})"))

    return observations, reasons


def evaluate_direct_humidity_stress(
    state: EnvironmentState, env_config: dict
) -> tuple[ObservationList, ReasonList]:
    """Evaluate humidity against stage-dependent stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.humidity is None:
        return observations, reasons

    hum = state.humidity

    # Universal low humidity check
    if hum < 35:
        prob = env_config.get("prob_humidity_too_dry", (0.85, 0.20))
        observations.append(prob)
        reasons.append((prob[0], f"Humidity Dry ({hum})"))

    # Stage-specific high humidity/out-of-range checks
    veg_early = state.flower_days == 0 and state.veg_days < 14
    veg_late = state.flower_days == 0 and state.veg_days >= 14
    flower_early = 0 < state.flower_days < 42
    flower_late = state.flower_days >= 42

    # Use elif for mutually exclusive stage checks
    if veg_early and hum > 80:
        prob = env_config.get("prob_humidity_high_veg_early", (0.80, 0.20))
        observations.append(prob)
        reasons.append((prob[0], f"Humidity High ({hum})"))
    elif veg_late and hum > 70:
        prob = env_config.get("prob_humidity_high_veg_late", (0.85, 0.15))
        observations.append(prob)
        reasons.append((prob[0], f"Humidity High ({hum})"))
    elif flower_early and (hum > 60 or hum < 45):
        prob = (0.75, 0.25)
        observations.append(prob)
        reasons.append((prob[0], f"Humidity out of range (<45 or >60) ({hum})"))
    elif flower_late and (hum > 60 or hum < 40):
        prob = (0.85, 0.15)
        observations.append(prob)
        reasons.append((prob[0], f"Humidity out of range (<40 or >60) ({hum})"))

    return observations, reasons


def evaluate_direct_vpd_stress(
    state: EnvironmentState, env_config: dict
) -> tuple[ObservationList, ReasonList]:
    """Evaluate VPD against stage-dependent stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.vpd is None:
        return observations, reasons

    # Determine stage thresholds using the data from bayesian_data.py
    stage_key = _determine_stage_key(state)

    if stage_key:
        time_of_day = "day" if state.is_lights_on else "night"
        thresholds = VPD_STRESS_THRESHOLDS[stage_key][time_of_day]

        stress_low, stress_high = thresholds["stress"]
        mild_low, mild_high = thresholds["mild"]
        prob_stress_key, prob_mild_key = thresholds["prob_keys"]
        prob_stress_default, prob_mild_default = thresholds["prob_defaults"]

        if state.vpd < stress_low or state.vpd > stress_high:
            prob = env_config.get(prob_stress_key, prob_stress_default)
            observations.append(prob)
            reasons.append((prob[0], f"VPD out of range ({state.vpd})"))
        elif state.vpd < mild_low or state.vpd > mild_high:
            prob = env_config.get(prob_mild_key, prob_mild_default)
            observations.append(prob)
            reasons.append((prob[0], f"VPD out of range ({state.vpd})"))

    return observations, reasons


def evaluate_direct_co2_stress(
    state: EnvironmentState, env_config: dict
) -> tuple[ObservationList, ReasonList]:
    """Evaluate CO2 against low/high stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.co2 is None:
        return observations, reasons

    co2 = state.co2

    # Universal CO2 stress checks (not stage-dependent in this sensor's logic)
    if co2 < 400:
        prob = (0.80, 0.25)
        observations.append(prob)
        reasons.append((prob[0], f"CO2 Low ({co2})"))
    elif co2 > 1600:
        prob = (0.95, 0.10)
        observations.append(prob)
        reasons.append((prob[0], f"CO2 High ({co2})"))

    return observations, reasons


# =========================================================================
# OPTIMAL CONDITIONS SENSOR EVALUATION
# =========================================================================


def evaluate_optimal_temperature(
    state: EnvironmentState, env_config: dict
) -> tuple[ObservationList, ReasonList]:
    """Evaluate temperature against optimal ranges for the current stage/light cycle."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.temp is None:
        return observations, reasons

    prob_out_of_range = PROB_STRESS_OUT_OF_RANGE  # Reuse stress probability

    # Match against (is_lights_on, flower_days) for branching logic
    match (state.is_lights_on, state.flower_days):
        # Case A: Lights ON & Late Flower (Days >= 42)
        case True, days if days >= 42:
            if 22 <= state.temp <= 26:  # Perfect range for late flower
                observations.append(PROB_PERFECT)
            else:
                observations.append(prob_out_of_range)
                reasons.append(
                    (
                        prob_out_of_range[1],
                        f"Temp out of range Late Flower ({state.temp})",
                    )
                )

        # Case B: Lights ON & Normal (Days < 42 or Veg)
        case True, _:
            if 24 <= state.temp <= 26:
                observations.append(PROB_PERFECT)
            elif 22 <= state.temp <= 28:
                observations.append(PROB_GOOD)
            elif 20 <= state.temp <= 29:
                observations.append(PROB_ACCEPTABLE)
            else:
                observations.append(prob_out_of_range)
                reasons.append(
                    (prob_out_of_range[1], f"Temp out of range ({state.temp})")
                )

        # Case C: Lights OFF (Nighttime)
        case False, _:
            if 20 <= state.temp <= 23:
                observations.append(PROB_PERFECT)
            else:
                observations.append(prob_out_of_range)
                reasons.append(
                    (
                        prob_out_of_range[1],
                        f"Night temp out of range ({state.temp})",
                    )
                )
    return observations, reasons


def evaluate_optimal_vpd(
    state: EnvironmentState, env_config: dict
) -> tuple[ObservationList, ReasonList]:
    """Evaluate VPD against optimal ranges for the current stage/light cycle."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.vpd is None:
        return observations, reasons

    vpd_optimal = False
    prob_vpd_out_of_range = PROB_VPD_STRESS_OUT_OF_RANGE  # Reuse stress probability

    stage_key = _determine_stage_key(state)

    if stage_key:
        time_of_day = "day" if state.is_lights_on else "night"

        # Look up optimal thresholds from the data constant
        stage_limits = VPD_OPTIMAL_THRESHOLDS.get(stage_key, {}).get(time_of_day, [])

        for p_low, p_high, prob in stage_limits:
            if p_low <= state.vpd <= p_high:
                vpd_optimal = True
                observations.append(prob)
                # Only log the best (first match) positive observation
                break

    # If no optimal range was met for the identified stage, reduce probability
    if not vpd_optimal:
        observations.append(prob_vpd_out_of_range)
        reasons.append((prob_vpd_out_of_range[1], f"VPD out of range ({state.vpd})"))

    return observations, reasons


def evaluate_optimal_co2(
    state: EnvironmentState, env_config: dict
) -> tuple[ObservationList, ReasonList]:
    """Evaluate CO2 levels against optimal ranges for the current stage."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.co2 is None:
        return observations, reasons

    prob_out_of_range = PROB_STRESS_OUT_OF_RANGE
    co2 = state.co2

    # Use match/case on the result of the stage check (True or False)
    match state.flower_days >= 42:
        case True:  # Late Flower Logic (Prefers lower CO2)
            if 400 <= co2 <= 800:
                observations.append((0.90, 0.25))
            elif 800 < co2 <= 1200:
                observations.append((0.4, 0.6))
            # Else: fall through (no observation is added if outside of these two ranges)

        case False:  # Normal/Veg/Early Flower logic
            if 1000 <= co2 <= 1400:
                observations.append(PROB_PERFECT)
            elif 800 <= co2 <= 1500:
                observations.append(PROB_GOOD)
            elif 400 <= co2 <= 600:
                observations.append(PROB_ACCEPTABLE)
            else:
                observations.append(prob_out_of_range)
                reason_detail = "CO2 Low" if co2 < 400 else "CO2 High"
                reasons.append((prob_out_of_range[1], f"{reason_detail} ({co2})"))
    return observations, reasons
