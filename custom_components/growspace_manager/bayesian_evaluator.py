"""Bayesian evaluator module for Growspace Manager.

This module contains logic for evaluating environmental conditions using Bayesian inference,
including trend analysis and stress detection.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import logging
from typing import TYPE_CHECKING, Any

from homeassistant.core import State

from .bayesian_constants import (
    CO2_HIGH_THRESHOLD,
    CO2_LOW_THRESHOLD,
    DEFAULT_TREND_DURATION,
    DEFAULT_TREND_SENSITIVITY,
    DEFAULT_TREND_THRESHOLD_TEMP,
    FLOWER_LATE_MIN_DAYS,
    FLOWER_MID_MIN_DAYS,
    HUMIDIFIER_ACTIVE_THRESHOLD,
    HUMIDITY_ACTIVE_DESICCATION_THRESHOLD,
    HUMIDITY_CHANGE_THRESHOLD,
    HUMIDITY_SATURATION_FLOWER_THRESHOLD,
    HUMIDITY_SATURATION_VEG_THRESHOLD,
    HUMIDITY_TOO_DRY_THRESHOLD,
    MOLD_TREND_THRESHOLD_HUMIDITY,
    MOLD_TREND_THRESHOLD_VPD,
    PROB_ACTIVE_DESICCATION,
    PROB_ACTIVE_SATURATION,
    PROB_CO2_HIGH,
    PROB_CO2_LOW,
    PROB_HUMIDITY_TOO_DRY,
    PROB_NIGHT_TEMP_HIGH,
    PROB_TEMP_COLD,
    PROB_TEMP_EXTREME_COLD,
    PROB_TEMP_EXTREME_HEAT,
    PROB_TEMP_HIGH_HEAT,
    PROB_TEMP_WARM,
    PROB_TEMP_WARM_LATE_FLOWER,
    PROB_TREND_EXTERNAL,
    PROB_TREND_FAST_RISE,
    PROB_TREND_SLOW_RISE,
    PROB_TREND_STATS,
    SENSITIVITY_BASE_PROB,
    SENSITIVITY_FALSE_MULTIPLIER,
    SENSITIVITY_TRUE_MULTIPLIER,
    TEMP_COLD_THRESHOLD,
    TEMP_EXTREME_COLD_THRESHOLD,
    TEMP_EXTREME_HEAT_THRESHOLD,
    TEMP_HIGH_HEAT_THRESHOLD,
    TEMP_LATE_FLOWER_MAX,
    TEMP_LATE_FLOWER_MIN,
    TEMP_LIGHTS_OFF_PERFECT_MAX,
    TEMP_LIGHTS_OFF_PERFECT_MIN,
    TEMP_LIGHTS_ON_ACCEPTABLE_MAX,
    TEMP_LIGHTS_ON_ACCEPTABLE_MIN,
    TEMP_LIGHTS_ON_GOOD_MAX,
    TEMP_LIGHTS_ON_GOOD_MIN,
    TEMP_LIGHTS_ON_PERFECT_MAX,
    TEMP_LIGHTS_ON_PERFECT_MIN,
    TEMP_NIGHT_HIGH_THRESHOLD,
    TEMP_WARM_LATE_FLOWER_THRESHOLD,
    TEMP_WARM_THRESHOLD,
    TREND_FALLBACK_THRESHOLD,
    TREND_GRADIENT_FAST_THRESHOLD,
    TREND_SIGNIFICANCE_THRESHOLD,
    VPD_ACTIVE_DESICCATION_THRESHOLD,
    VPD_CHANGE_THRESHOLD,
    VPD_DANGER_ZONE_FLOWER,
    VPD_DANGER_ZONE_VEG,
)
from .bayesian_data import (
    PROB_ACCEPTABLE,
    PROB_GOOD,
    PROB_PERFECT,
    PROB_SOIL_MOISTURE_STRESS,
    PROB_STRESS_OUT_OF_RANGE,
    PROB_VPD_STRESS_OUT_OF_RANGE,
)
from .const import (
    CONF_PROB_TREND_FAST_RISE,
    CONF_PROB_TREND_SLOW_RISE,
    CONF_SENSOR_MAP,
    CONF_STATS_SENSOR_MAP,
    CONF_TREND_DURATION_MAP,
    CONF_TREND_SENSITIVITY_MAP,
    CONF_TREND_SENSOR_MAP,
    CONF_TREND_THRESHOLD_MAP,
)
from .domain.environmental_targets import StageEnvironmentalTargets
from .domain.moisture_band import effective_moisture_band
from .domain.stage import BayesianStage, StageClassification, StageDays, classify_stages
from .models import EnvironmentState

if TYPE_CHECKING:
    from .models import EnvironmentConfig

_LOGGER = logging.getLogger(__name__)

# Type aliases for readability
Obs = tuple[float, float]


def _classify(state: EnvironmentState) -> StageClassification:
    return classify_stages(
        StageDays(
            veg=state.veg_days,
            flower=state.flower_days,
            dry=state.dry_days,
            cure=state.cure_days,
            seedling=state.seedling_days,
            clone=state.clone_days,
            mother=state.mother_days,
        )
    )


Reason = tuple[float, str]
ObservationList = list[Obs]
ReasonList = list[Reason]


def _determine_stage_key(state: EnvironmentState) -> str:
    """Return the stage key for the current environment state."""
    # Post-harvest stages take highest priority
    if state.cure_days > 0:
        return BayesianStage.CURE
    if state.dry_days > 0:
        return BayesianStage.DRY

    # Mother plants — perpetual veg with own environmental targets
    if state.mother_days > 0:
        return BayesianStage.MOTHER

    # Flower takes precedence over standard vegetative stages
    if state.flower_days > 0:
        if state.flower_days >= FLOWER_LATE_MIN_DAYS:
            return BayesianStage.FLOWER_LATE
        if state.flower_days >= FLOWER_MID_MIN_DAYS:
            return BayesianStage.FLOWER_MID
        return BayesianStage.FLOWER_EARLY

    # Before flower
    if state.veg_days > 0:
        return BayesianStage.VEG
    if state.seedling_days > 0:
        return BayesianStage.SEEDLING
    if state.clone_days > 0:
        return BayesianStage.CLONE

    return BayesianStage.VEG


async def async_evaluate_stress_trend(
    env_config: EnvironmentConfig,
    get_state: Callable[[str], State | None],
    analyze_trend: Callable[[str, int, float], Awaitable[dict[str, Any]]],
    state: EnvironmentState,
) -> tuple[ObservationList, ReasonList, dict[str, str]]:
    """Evaluate rising trends for temperature, humidity, and VPD from sensors/history."""
    observations: ObservationList = []
    reasons: ReasonList = []
    trend_states: dict[str, str] = {}
    env_config_dict = env_config.to_dict()

    trend_states["temperature_trend"] = "stable"
    trend_states["humidity_trend"] = "stable"
    trend_states["vpd_trend"] = "stable"

    async def _evaluate_single(
        sensor_key: str, trend_key: str
    ) -> tuple[ObservationList, ReasonList, dict[str, str]]:
        local_obs: ObservationList = []
        local_reasons: ReasonList = []
        local_trends: dict[str, str] = {}

        trend_sensor_id = env_config_dict.get(CONF_TREND_SENSOR_MAP[sensor_key])
        stats_sensor_id = env_config_dict.get(CONF_STATS_SENSOR_MAP[sensor_key])

        # --- External Trend Sensor Logic ---
        if trend_sensor_id:
            trend_state: State | None = get_state(trend_sensor_id)
            if trend_state and trend_state.state == "on":  # Rising trend
                local_trends[trend_key] = "rising"
                gradient = trend_state.attributes.get("gradient", 0)
                prob = (
                    env_config.get(CONF_PROB_TREND_FAST_RISE, PROB_TREND_FAST_RISE)
                    if gradient > TREND_GRADIENT_FAST_THRESHOLD
                    else env_config.get(CONF_PROB_TREND_SLOW_RISE, PROB_TREND_SLOW_RISE)
                )
                local_obs.append(prob)
                reason_suffix = (
                    " fast" if gradient > TREND_GRADIENT_FAST_THRESHOLD else ""
                )
                local_reasons.append(
                    (prob[0], f"{sensor_key.capitalize()} rising{reason_suffix}")
                )

        elif stats_sensor_id:
            stats_state: State | None = get_state(stats_sensor_id)
            if (
                stats_state
                and (change := stats_state.attributes.get("change")) is not None
            ):
                threshold = (
                    TREND_SIGNIFICANCE_THRESHOLD
                    if sensor_key == "vpd"
                    else TREND_FALLBACK_THRESHOLD
                )
                if change > threshold:
                    local_trends[trend_key] = "rising"
                    prob = PROB_TREND_STATS
                    local_obs.append(prob)
                    local_reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

        else:  # Fallback to manual analysis (Requires await)
            duration = env_config_dict.get(
                CONF_TREND_DURATION_MAP[sensor_key], DEFAULT_TREND_DURATION
            )
            threshold = env_config_dict.get(
                CONF_TREND_THRESHOLD_MAP[sensor_key], DEFAULT_TREND_THRESHOLD_TEMP
            )
            sensitivity = env_config_dict.get(
                CONF_TREND_SENSITIVITY_MAP[sensor_key], DEFAULT_TREND_SENSITIVITY
            )
            sensor_id_key = CONF_SENSOR_MAP[sensor_key]
            if env_config_dict.get(sensor_id_key):
                analysis = await analyze_trend(
                    env_config_dict[sensor_id_key], duration, threshold
                )
                local_trends[trend_key] = analysis["trend"]
                if analysis["trend"] == "rising" and analysis["crossed_threshold"]:
                    p_true = SENSITIVITY_BASE_PROB + (
                        sensitivity * SENSITIVITY_TRUE_MULTIPLIER
                    )
                    p_false = SENSITIVITY_BASE_PROB - (
                        sensitivity * SENSITIVITY_FALSE_MULTIPLIER
                    )
                    prob = (p_true, p_false)
                    local_obs.append(prob)
                    local_reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

        return local_obs, local_reasons, local_trends

    # Use TaskGroup for structured concurrency and better error handling
    async with asyncio.TaskGroup() as tg:
        temp_task = tg.create_task(_evaluate_single("temperature", "temperature_trend"))
        hum_task = tg.create_task(_evaluate_single("humidity", "humidity_trend"))
        vpd_task = tg.create_task(_evaluate_single("vpd", "vpd_trend"))

    # Collect results after TaskGroup context exits
    results = [
        temp_task.result(),
        hum_task.result(),
        vpd_task.result(),
    ]

    for res_obs, res_reasons, res_trends in results:
        observations.extend(res_obs)
        reasons.extend(res_reasons)
        trend_states.update(res_trends)

    return observations, reasons, trend_states


async def _async_evaluate_external_mold_trend_sensor(
    get_state: Callable[[str], State | None],
    env_config: dict[str, Any],
    sensor_key: str,
    trend_key: str,
    observations: ObservationList,
    reasons: ReasonList,
    trend_states: dict[str, str],
    state: EnvironmentState,
) -> None:
    """Evaluate external trend sensors for mold risk (humidity and VPD)."""
    trend_sensor_id = env_config.get(CONF_TREND_SENSOR_MAP[sensor_key])
    stats_sensor_id = env_config.get(CONF_STATS_SENSOR_MAP[sensor_key])

    if trend_sensor_id:
        trend_state: State | None = get_state(trend_sensor_id)
        if trend_state and trend_state.state == (
            "on" if sensor_key == "humidity" else "off"
        ):
            # VPD Falling Trend Gating (External Sensor)
            if sensor_key == "vpd" and _is_vpd_trend_gated(state):
                return

            trend_states[trend_key] = (
                "rising" if sensor_key == "humidity" else "falling"
            )
            prob = PROB_TREND_EXTERNAL
            observations.append(prob)
            reasons.append(
                (
                    prob[0],
                    f"{sensor_key.capitalize()} {'rising' if sensor_key == 'humidity' else 'falling'}",
                )
            )
    elif stats_sensor_id:
        stats_state: State | None = get_state(stats_sensor_id)
        if stats_state and (change := stats_state.attributes.get("change")) is not None:
            if (sensor_key == "humidity" and change > HUMIDITY_CHANGE_THRESHOLD) or (
                sensor_key == "vpd" and change < VPD_CHANGE_THRESHOLD
            ):
                # VPD Falling Trend Gating (Stats Sensor)
                if sensor_key == "vpd" and _is_vpd_trend_gated(state):
                    return

                trend_states[trend_key] = (
                    "rising" if sensor_key == "humidity" else "falling"
                )
                prob = PROB_TREND_STATS
                observations.append(prob)
                reasons.append(
                    (
                        prob[0],
                        f"{sensor_key.capitalize()} {'rising' if sensor_key == 'humidity' else 'falling'}",
                    )
                )


def _is_vpd_trend_gated(state: EnvironmentState) -> bool:
    """Determine if a falling VPD trend should be ignored because current VPD is safe."""
    if state.vpd is None:
        return False
    # Danger Zone: Veg < VPD_DANGER_ZONE_VEG, Flower < VPD_DANGER_ZONE_FLOWER
    danger_zone = (
        VPD_DANGER_ZONE_VEG if state.flower_days < 0 else VPD_DANGER_ZONE_FLOWER
    )
    return state.vpd >= danger_zone


async def _async_evaluate_fallback_mold_trend_analysis(
    env_config: dict[str, Any],
    sensor_key: str,
    trend_key: str,
    observations: ObservationList,
    reasons: ReasonList,
    trend_states: dict[str, str],
    analyze_trend: Callable[[str, int, float], Awaitable[dict[str, Any]]],
    state: EnvironmentState,
) -> None:
    """Perform fallback manual trend analysis for mold risk."""
    if not env_config.get(CONF_TREND_SENSOR_MAP[sensor_key]) and not env_config.get(
        CONF_STATS_SENSOR_MAP[sensor_key]
    ):
        duration = env_config.get(
            CONF_TREND_DURATION_MAP[sensor_key], DEFAULT_TREND_DURATION
        )
        threshold = (
            MOLD_TREND_THRESHOLD_HUMIDITY
            if sensor_key == "humidity"
            else MOLD_TREND_THRESHOLD_VPD
        )
        sensitivity = env_config.get(
            CONF_TREND_SENSITIVITY_MAP[sensor_key], DEFAULT_TREND_SENSITIVITY
        )
        sensor_id_key = CONF_SENSOR_MAP[sensor_key]
        if env_config.get(sensor_id_key):
            analysis = await analyze_trend(
                env_config[sensor_id_key], duration, threshold
            )
            # Fallback analysis updates trend state
            trend_states[f"{sensor_key}_trend"] = analysis["trend"]

            # VPD Falling Trend Logic (Professional Gating)
            if sensor_key == "vpd" and analysis["trend"] == "falling":
                # Danger Zone: Veg < VPD_DANGER_ZONE_VEG, Flower < VPD_DANGER_ZONE_FLOWER
                danger_zone = (
                    VPD_DANGER_ZONE_VEG
                    if state.flower_days < 0
                    else VPD_DANGER_ZONE_FLOWER
                )

                # Only penalize if we are already approaching the danger zone
                if state.vpd is not None and state.vpd < danger_zone:
                    p_true = SENSITIVITY_BASE_PROB + (
                        sensitivity * SENSITIVITY_TRUE_MULTIPLIER
                    )
                    p_false = SENSITIVITY_BASE_PROB - (
                        sensitivity * SENSITIVITY_FALSE_MULTIPLIER
                    )
                    prob = (p_true, p_false)
                    observations.append(prob)
                    reasons.append(
                        (
                            prob[0],
                            f"{sensor_key.capitalize()} trend falling (Approaching {danger_zone}kPa)",
                        )
                    )


async def async_evaluate_mold_risk_trend(
    env_config: EnvironmentConfig,
    get_state: Callable[[str], State | None],
    analyze_trend: Callable[[str, int, float], Awaitable[dict[str, Any]]],
    state: EnvironmentState,
) -> tuple[ObservationList, ReasonList, dict[str, str]]:
    """Evaluate trends for humidity and VPD for mold risk."""
    observations: ObservationList = []
    reasons: ReasonList = []
    trend_states: dict[str, str] = {}
    env_config_dict = env_config.to_dict()

    trend_states["humidity_trend"] = "stable"
    trend_states["vpd_trend"] = "stable"

    async def _evaluate_single_mold(
        sensor_key: str, trend_key: str
    ) -> tuple[ObservationList, ReasonList, dict[str, str]]:
        local_obs: ObservationList = []
        local_reasons: ReasonList = []
        local_trends: dict[str, str] = {}

        # Humidity trend is tracked for UI but IGNORED for risk calculation
        # to prevent false positives in high-transpiration environments.
        # Only VPD trend contributes to risk probability.
        target_obs = local_obs
        target_reasons = local_reasons

        if sensor_key == "humidity":
            target_obs = []
            target_reasons = []

        await _async_evaluate_external_mold_trend_sensor(
            get_state,
            env_config_dict,
            sensor_key,
            trend_key,
            target_obs,
            target_reasons,
            local_trends,
            state,
        )
        await _async_evaluate_fallback_mold_trend_analysis(
            env_config_dict,
            sensor_key,
            trend_key,
            target_obs,
            target_reasons,
            local_trends,
            analyze_trend,
            state,
        )
        return local_obs, local_reasons, local_trends

    # Use TaskGroup for structured concurrency and better error handling
    results: list[tuple[ObservationList, ReasonList, dict[str, str]]] = []
    async with asyncio.TaskGroup() as tg:
        hum_task = tg.create_task(_evaluate_single_mold("humidity", "humidity_trend"))
        vpd_task = tg.create_task(_evaluate_single_mold("vpd", "vpd_trend"))

    # Collect results after TaskGroup context exits
    results = [
        hum_task.result(),
        vpd_task.result(),
    ]

    for res_obs, res_reasons, res_trends in results:
        observations.extend(res_obs)
        reasons.extend(res_reasons)
        trend_states.update(res_trends)

    return observations, reasons, trend_states


# =========================================================================
# STRESS SENSOR EVALUATION
# =========================================================================


def evaluate_direct_temp_stress(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate temperature against extreme/out-of-range stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.temp is None:
        return observations, reasons

    temp = state.temp

    # 1: Night High Temp Check (Independent IF)
    # Only check if we KNOW lights are off. If None (unknown), skip this check.
    if state.is_lights_on is False and temp > TEMP_NIGHT_HIGH_THRESHOLD:
        prob = env_config.get("prob_night_temp_high", PROB_NIGHT_TEMP_HIGH)
        observations.append(prob)
        reasons.append((prob[0], f"Night Temp High ({temp})"))

    # 2: General Stress/Warm/Cold Checks (Modernized with pattern matching)
    match temp:
        case t if t > TEMP_EXTREME_HEAT_THRESHOLD:
            prob = env_config.get("prob_temp_extreme_heat", PROB_TEMP_EXTREME_HEAT)
            observations.append(prob)
            reasons.append((prob[0], f"Extreme Heat ({temp})"))
        case t if t > TEMP_HIGH_HEAT_THRESHOLD:
            prob = env_config.get("prob_temp_high_heat", PROB_TEMP_HIGH_HEAT)
            observations.append(prob)
            reasons.append((prob[0], f"High Heat ({temp})"))
        case t if (
            state.flower_days >= FLOWER_LATE_MIN_DAYS
            and t > TEMP_WARM_LATE_FLOWER_THRESHOLD
        ):
            prob = PROB_TEMP_WARM_LATE_FLOWER
            observations.append(prob)
            reasons.append((prob[0], f"Temp Warm ({temp})"))
        case t if t > TEMP_WARM_THRESHOLD:
            prob = env_config.get("prob_temp_warm", PROB_TEMP_WARM)
            observations.append(prob)
            reasons.append((prob[0], f"Temp Warm ({temp})"))
        case t if t < TEMP_EXTREME_COLD_THRESHOLD:
            prob = env_config.get("prob_temp_extreme_cold", PROB_TEMP_EXTREME_COLD)
            observations.append(prob)
            reasons.append((prob[0], f"Extreme Cold ({temp})"))
        case t if t < TEMP_COLD_THRESHOLD:
            prob = env_config.get("prob_temp_cold", PROB_TEMP_COLD)
            observations.append(prob)
            reasons.append((prob[0], f"Temp Cold ({temp})"))

    return observations, reasons


def evaluate_direct_humidity_stress(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate humidity against stage-dependent stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.humidity is None:
        return observations, reasons

    hum = state.humidity

    # Universal low humidity check
    if hum < HUMIDITY_TOO_DRY_THRESHOLD:
        prob = env_config.get("prob_humidity_too_dry", PROB_HUMIDITY_TOO_DRY)
        observations.append(prob)
        reasons.append((prob[0], f"Humidity Dry ({hum})"))

    sc = _classify(state)
    if sc.stage_a == BayesianStage.EMPTY:
        return observations, reasons

    band = StageEnvironmentalTargets(sc.stage_a, sc.stage_b, sc.factor).humidity_band(
        env_config
    )

    if hum < band.low or hum > band.high:
        observations.append(band.prob)
        reasons.append(
            (
                band.prob[0],
                f"Humidity out of range (<{band.low} or >{band.high}) ({hum})",
            )
        )

    return observations, reasons


def evaluate_direct_vpd_stress(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate VPD against stage-dependent stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.vpd is None:
        return observations, reasons

    sc = _classify(state)
    if sc.stage_a == BayesianStage.EMPTY:
        return observations, reasons
    time_of_day = "night" if state.is_lights_on is False else "day"

    band = StageEnvironmentalTargets(sc.stage_a, sc.stage_b, sc.factor).vpd_stress_band(
        time_of_day, env_config
    )

    if state.vpd < band.stress_low or state.vpd > band.stress_high:
        observations.append(band.prob_stress)
        reasons.append((band.prob_stress[0], f"VPD out of range ({state.vpd})"))
    elif state.vpd < band.mild_low or state.vpd > band.mild_high:
        observations.append(band.prob_mild)
        reasons.append((band.prob_mild[0], f"VPD out of range ({state.vpd})"))

    return observations, reasons


def evaluate_direct_co2_stress(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate CO2 against low/high stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.co2 is None:
        return observations, reasons

    co2 = state.co2

    # Universal CO2 stress checks (not stage-dependent in this sensor's logic)
    if co2 < CO2_LOW_THRESHOLD:
        prob = PROB_CO2_LOW
        observations.append(prob)
        reasons.append((prob[0], f"CO2 Low ({co2})"))
    elif co2 > CO2_HIGH_THRESHOLD:
        prob = PROB_CO2_HIGH
        observations.append(prob)
        reasons.append((prob[0], f"CO2 High ({co2})"))

    return observations, reasons


def evaluate_soil_moisture_stress(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate soil moisture against stress thresholds."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.soil_moisture is None:
        return observations, reasons

    moisture = state.soil_moisture
    prob_stress = PROB_SOIL_MOISTURE_STRESS

    # Acceptable Moisture Band: the growspace's custom pair when it has one,
    # otherwise the inherited default. Boundaries are inclusive, so a reading
    # exactly on a bound adds no evidence.
    band = effective_moisture_band(
        env_config.get("soil_moisture_min"), env_config.get("soil_moisture_max")
    )
    classification = band.classify(moisture)

    if classification == "too_dry":
        observations.append(prob_stress)
        reasons.append(
            (prob_stress[0], f"Soil Moisture Low ({moisture}% < {band.minimum:g}%)")
        )
    elif classification == "too_wet":
        observations.append(prob_stress)
        reasons.append(
            (prob_stress[0], f"Soil Moisture High ({moisture}% > {band.maximum:g}%)")
        )

    return observations, reasons


def evaluate_substrate_temp_stress(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate substrate temperature against stress thresholds."""
    from .bayesian_constants import (  # noqa: PLC0415
        PROB_SUBSTRATE_TEMP_EXTREME,
        PROB_SUBSTRATE_TEMP_STRESS,
        SUBSTRATE_TEMP_OPTIMAL_MAX,
        SUBSTRATE_TEMP_OPTIMAL_MIN,
        SUBSTRATE_TEMP_STRESS_HIGH,
        SUBSTRATE_TEMP_STRESS_LOW,
    )

    observations: ObservationList = []
    reasons: ReasonList = []

    if state.substrate_temp is None:
        return observations, reasons

    temp = state.substrate_temp

    if temp < SUBSTRATE_TEMP_STRESS_LOW:
        observations.append(PROB_SUBSTRATE_TEMP_EXTREME)
        reasons.append(
            (
                PROB_SUBSTRATE_TEMP_EXTREME[0],
                f"Substrate temp critically low ({temp}°C)",
            )
        )
    elif temp < SUBSTRATE_TEMP_OPTIMAL_MIN:
        observations.append(PROB_SUBSTRATE_TEMP_STRESS)
        reasons.append(
            (PROB_SUBSTRATE_TEMP_STRESS[0], f"Substrate temp below optimal ({temp}°C)")
        )
    elif temp > SUBSTRATE_TEMP_STRESS_HIGH:
        observations.append(PROB_SUBSTRATE_TEMP_EXTREME)
        reasons.append(
            (
                PROB_SUBSTRATE_TEMP_EXTREME[0],
                f"Substrate temp critically high ({temp}°C)",
            )
        )
    elif temp > SUBSTRATE_TEMP_OPTIMAL_MAX:
        observations.append(PROB_SUBSTRATE_TEMP_STRESS)
        reasons.append(
            (PROB_SUBSTRATE_TEMP_STRESS[0], f"Substrate temp above optimal ({temp}°C)")
        )

    return observations, reasons


# =========================================================================
# OPTIMAL CONDITIONS SENSOR EVALUATION
# =========================================================================


def evaluate_optimal_temperature(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate temperature against optimal ranges for the current stage/light cycle."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.temp is None:
        return observations, reasons

    # Match against (is_lights_on, flower_days) for branching logic
    match (state.is_lights_on, state.flower_days):
        # Case A: Lights ON & Late Flower (Days >= FLOWER_LATE_MIN_DAYS)
        # Treat None (unknown) as Lights ON for fallback
        case (True | None, days) if days >= FLOWER_LATE_MIN_DAYS:
            _evaluate_optimal_temp_late_flower(state.temp, observations, reasons)

        # Case B: Lights ON & Normal (Days < 42 or Veg)
        # Treat None (unknown) as Lights ON for fallback
        case (True | None, _):
            _evaluate_optimal_temp_lights_on(state.temp, observations, reasons)

        # Case D: Lights OFF (Nighttime)
        case False, _:
            _evaluate_optimal_temp_lights_off(state.temp, observations, reasons)

    return observations, reasons


def _evaluate_optimal_temp_late_flower(
    temp: float, observations: ObservationList, reasons: ReasonList
) -> None:
    """Evaluate optimal temperature for late flower stage."""
    prob_out_of_range = PROB_STRESS_OUT_OF_RANGE
    if (
        TEMP_LATE_FLOWER_MIN <= temp <= TEMP_LATE_FLOWER_MAX
    ):  # Perfect range for late flower
        observations.append(PROB_PERFECT)
    else:
        observations.append(prob_out_of_range)
        reasons.append(
            (
                prob_out_of_range[1],
                f"Temp out of range Late Flower ({temp})",
            )
        )


def _evaluate_optimal_temp_lights_on(
    temp: float, observations: ObservationList, reasons: ReasonList
) -> None:
    """Evaluate optimal temperature for lights on (normal/veg)."""
    prob_out_of_range = PROB_STRESS_OUT_OF_RANGE
    if TEMP_LIGHTS_ON_PERFECT_MIN <= temp <= TEMP_LIGHTS_ON_PERFECT_MAX:
        observations.append(PROB_PERFECT)
    elif TEMP_LIGHTS_ON_GOOD_MIN <= temp <= TEMP_LIGHTS_ON_GOOD_MAX:
        observations.append(PROB_GOOD)
    elif TEMP_LIGHTS_ON_ACCEPTABLE_MIN <= temp <= TEMP_LIGHTS_ON_ACCEPTABLE_MAX:
        observations.append(PROB_ACCEPTABLE)
    else:
        observations.append(prob_out_of_range)
        reasons.append((prob_out_of_range[1], f"Temp out of range ({temp})"))


def _evaluate_optimal_temp_lights_off(
    temp: float, observations: ObservationList, reasons: ReasonList
) -> None:
    """Evaluate optimal temperature for lights off (night)."""
    prob_out_of_range = PROB_STRESS_OUT_OF_RANGE
    if TEMP_LIGHTS_OFF_PERFECT_MIN <= temp <= TEMP_LIGHTS_OFF_PERFECT_MAX:
        observations.append(PROB_PERFECT)
    else:
        observations.append(prob_out_of_range)
        reasons.append(
            (
                prob_out_of_range[1],
                f"Night temp out of range ({temp})",
            )
        )


def evaluate_optimal_vpd(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate VPD against optimal ranges for the current stage/light cycle."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.vpd is None:
        return observations, reasons

    vpd_optimal = False
    prob_vpd_out_of_range = PROB_VPD_STRESS_OUT_OF_RANGE

    sc = _classify(state)
    if sc.stage_a == BayesianStage.EMPTY:
        return observations, reasons
    time_of_day = "night" if state.is_lights_on is False else "day"
    vpd_overrides: dict[str, Any] = env_config.get("vpd_optimal_overrides", {})

    bands = StageEnvironmentalTargets(
        sc.stage_a, sc.stage_b, sc.factor
    ).vpd_optimal_band(time_of_day, vpd_overrides)

    for p_low, p_high, prob in bands:
        if p_low <= state.vpd <= p_high:
            vpd_optimal = True
            observations.append(prob)
            break

    # If no optimal range was met, reduce probability
    if not vpd_optimal:
        observations.append(prob_vpd_out_of_range)
        reasons.append((prob_vpd_out_of_range[1], f"VPD out of range ({state.vpd})"))

    return observations, reasons


def evaluate_optimal_co2(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate CO2 levels against optimal ranges for the current stage."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.co2 is None:
        return observations, reasons

    prob_out_of_range = PROB_STRESS_OUT_OF_RANGE
    co2 = state.co2
    co2_optimal = False

    sc = _classify(state)
    if sc.stage_a == BayesianStage.EMPTY:
        return observations, reasons
    stage_a, stage_b = sc.stage_a, sc.stage_b

    bands = StageEnvironmentalTargets(stage_a, stage_b, sc.factor).co2_optimal_band()

    for co2_low, co2_high, prob in bands:
        if co2_low <= co2 <= co2_high:
            co2_optimal = True
            observations.append(prob)
            break

    # If no optimal range was met, reduce probability
    # Note: Late flower stages don't penalize out-of-range CO2 (backward compatibility)
    if not co2_optimal:
        is_late_flower = BayesianStage.FLOWER_LATE in (stage_a, stage_b)
        if not is_late_flower:
            observations.append(prob_out_of_range)
            reason_detail = "CO2 Low" if co2 < CO2_LOW_THRESHOLD else "CO2 High"
            reasons.append((prob_out_of_range[1], f"{reason_detail} ({co2})"))

    return observations, reasons


def evaluate_active_desiccation(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate active desiccation (Dehumidifier ON + Low Humidity or High VPD)."""
    observations: ObservationList = []
    reasons: ReasonList = []

    if state.dehumidifier_on:
        # High probability of stress if dehumidifier is running while already dry
        if (
            state.humidity is not None
            and state.humidity < HUMIDITY_ACTIVE_DESICCATION_THRESHOLD
        ):
            prob = PROB_ACTIVE_DESICCATION
            observations.append(prob)
            reasons.append(
                (prob[0], "Active Desiccation (Dehumidifier on with low humidity)")
            )
        elif state.vpd is not None and state.vpd > VPD_ACTIVE_DESICCATION_THRESHOLD:
            prob = PROB_ACTIVE_DESICCATION
            observations.append(prob)
            reasons.append(
                (prob[0], "Active Desiccation (Dehumidifier on with high VPD)")
            )

    return observations, reasons


def evaluate_active_saturation(
    state: EnvironmentState, env_config: dict[str, Any]
) -> tuple[ObservationList, ReasonList]:
    """Evaluate active saturation (Humidifier ON + High Humidity)."""
    observations: ObservationList = []
    reasons: ReasonList = []

    # Check if humidifier is active (value > HUMIDIFIER_ACTIVE_THRESHOLD implies it's running/consuming power)
    if (
        state.humidifier_value is not None
        and state.humidifier_value > HUMIDIFIER_ACTIVE_THRESHOLD
    ):
        if state.humidity is None:
            return observations, reasons

        hum = state.humidity
        is_saturated = False

        veg = state.flower_days < 0
        flower = state.flower_days >= 0

        if (veg and hum > HUMIDITY_SATURATION_VEG_THRESHOLD) or (
            flower and hum > HUMIDITY_SATURATION_FLOWER_THRESHOLD
        ):
            is_saturated = True

        if is_saturated:
            prob = PROB_ACTIVE_SATURATION
            observations.append(prob)
            reasons.append(
                (prob[0], "Active Saturation (Humidifier on with high humidity)")
            )

    return observations, reasons
