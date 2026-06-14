"""Stage-interpolated environmental target computation.

Single seam for all stage-dependent threshold and probability lookups:
VPD stress bands, optimal VPD bands, humidity bands, CO2 optimal bands,
and display-facing VPD targets. Callers pass a (stage_a, stage_b, factor)
triple from StageClassification and call the method they need.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from custom_components.growspace_manager.bayesian_constants import (
    HUMIDITY_ACCLIMATION_MAX,
    HUMIDITY_ACCLIMATION_MIN,
    HUMIDITY_FLOWER_LATE_MAX,
    HUMIDITY_FLOWER_LATE_MIN,
    HUMIDITY_FLOWER_MID_MAX,
    HUMIDITY_FLOWER_MID_MIN,
    HUMIDITY_HIGH_VEG_THRESHOLD,
    PROB_HUMIDITY_FLOWER_LATE_OUT_OF_RANGE,
    PROB_HUMIDITY_FLOWER_MID_OUT_OF_RANGE,
    PROB_HUMIDITY_HIGH_VEG,
)
from custom_components.growspace_manager.bayesian_data import (
    CO2_OPTIMAL_THRESHOLDS,
    PROB_PERFECT,
    VPD_OPTIMAL_THRESHOLDS,
    VPD_STRESS_THRESHOLDS,
)
from custom_components.growspace_manager.utils import interpolate_value

from .stage import BayesianStage

_ACCLIMATION_STAGES: frozenset[BayesianStage] = frozenset(
    {BayesianStage.SEEDLING, BayesianStage.CLONE}
)

_OVERRIDE_STAGE_MAP: dict[str, BayesianStage] = {
    "seedling": BayesianStage.SEEDLING_STANDARD,
    "clone": BayesianStage.CLONE_STANDARD,
    "mother": BayesianStage.MOTHER,
    "veg": BayesianStage.VEG,
    "flower_early": BayesianStage.FLOWER_EARLY,
    "flower_mid": BayesianStage.FLOWER_MID,
    "flower_late": BayesianStage.FLOWER_LATE,
    "dry": BayesianStage.DRY,
    "cure": BayesianStage.CURE,
}

_OVERRIDE_BAYESIAN_TO_KEY: dict[BayesianStage, str] = {
    v: k for k, v in _OVERRIDE_STAGE_MAP.items()
}


@dataclass(slots=True)
class VpdStressBand:
    """Interpolated VPD stress/mild thresholds with overridable probabilities."""

    stress_low: float
    stress_high: float
    mild_low: float
    mild_high: float
    prob_stress: tuple[float, float]
    prob_mild: tuple[float, float]


@dataclass(slots=True)
class HumidityBand:
    """Interpolated humidity threshold with stage-selected probability."""

    low: float
    high: float
    prob: tuple[float, float]


@dataclass(slots=True)
class VpdDisplayTargets:
    """Day and night VPD target / danger bounds for frontend display."""

    day_target_min: float
    day_target_max: float
    day_danger_min: float
    day_danger_max: float
    night_target_min: float
    night_target_max: float
    night_danger_min: float
    night_danger_max: float


def _hum_limits(stage: BayesianStage) -> tuple[float, float]:
    if stage in (BayesianStage.SEEDLING, BayesianStage.CLONE):
        return HUMIDITY_ACCLIMATION_MIN, HUMIDITY_ACCLIMATION_MAX
    if stage in (BayesianStage.SEEDLING_STANDARD, BayesianStage.CLONE_STANDARD):
        return 0, 90
    if stage == BayesianStage.VEG:
        return 0, HUMIDITY_HIGH_VEG_THRESHOLD
    if stage == BayesianStage.FLOWER_LATE:
        return HUMIDITY_FLOWER_LATE_MIN, HUMIDITY_FLOWER_LATE_MAX
    return HUMIDITY_FLOWER_MID_MIN, HUMIDITY_FLOWER_MID_MAX


def _get_optimal_limits(
    stage: BayesianStage,
    time_of_day: str,
    overrides: dict[str, Any],
) -> list[tuple[float, float, tuple[float, float]]]:
    """Return optimal VPD limits for stage, substituting any user override.

    Acclimation sub-stages (SEEDLING, CLONE) always use hardcoded defaults.
    """
    if stage not in _ACCLIMATION_STAGES:
        override_key = _OVERRIDE_BAYESIAN_TO_KEY.get(stage)
        if override_key and override_key in overrides:
            period = overrides[override_key].get(time_of_day, {})
            low = period.get("low")
            high = period.get("high")
            if low is not None and high is not None:
                return [(low, high, PROB_PERFECT)]
    return VPD_OPTIMAL_THRESHOLDS.get(stage, {}).get(time_of_day, [])


class StageEnvironmentalTargets:
    """Compute stage-interpolated environmental targets for one classification step.

    Accepts a (stage_a, stage_b, factor) triple from StageClassification.
    Each method corresponds to one evaluation site and preserves that site's
    exact lookup semantics — do not unify the two VPD methods.
    """

    __slots__ = ("_factor", "_stage_a", "_stage_b")

    def __init__(
        self,
        stage_a: BayesianStage,
        stage_b: BayesianStage,
        factor: float,
    ) -> None:
        """Initialise with stage_a, stage_b and the interpolation factor (0–1)."""
        self._stage_a = stage_a
        self._stage_b = stage_b
        self._factor = factor

    # ── Evaluator interface ──────────────────────────────────────────────────

    def vpd_stress_band(self, time_of_day: str, env_config: dict[str, Any]) -> VpdStressBand:
        """Return interpolated VPD stress/mild bands with per-env overridable probabilities.

        Uses direct subscript access — callers must ensure stage_a/stage_b are valid keys
        in VPD_STRESS_THRESHOLDS (mirrors evaluate_direct_vpd_stress contract).
        """
        thr_a = VPD_STRESS_THRESHOLDS[self._stage_a][time_of_day]
        thr_b = VPD_STRESS_THRESHOLDS[self._stage_b][time_of_day]

        stress_low = interpolate_value(thr_a["stress"][0], thr_b["stress"][0], self._factor)
        stress_high = interpolate_value(thr_a["stress"][1], thr_b["stress"][1], self._factor)
        mild_low = interpolate_value(thr_a["mild"][0], thr_b["mild"][0], self._factor)
        mild_high = interpolate_value(thr_a["mild"][1], thr_b["mild"][1], self._factor)

        selected_thr = thr_a if self._factor < 0.5 else thr_b
        prob_stress_key, prob_mild_key = selected_thr["prob_keys"]
        prob_stress_default, prob_mild_default = selected_thr["prob_defaults"]

        prob_stress = env_config.get(prob_stress_key, prob_stress_default)
        prob_mild = env_config.get(prob_mild_key, prob_mild_default)

        return VpdStressBand(stress_low, stress_high, mild_low, mild_high, prob_stress, prob_mild)

    def vpd_optimal_band(
        self, time_of_day: str, overrides: dict[str, Any]
    ) -> list[tuple[float, float, Any]]:
        """Return interpolated optimal VPD bands, applying per-growspace overrides."""
        limits_a = _get_optimal_limits(self._stage_a, time_of_day, overrides)
        limits_b = _get_optimal_limits(self._stage_b, time_of_day, overrides)

        result: list[tuple[float, float, Any]] = []
        for i in range(min(len(limits_a), len(limits_b))):
            p_low_a, p_high_a, prob_a = limits_a[i]
            p_low_b, p_high_b, prob_b = limits_b[i]
            p_low = interpolate_value(p_low_a, p_low_b, self._factor)
            p_high = interpolate_value(p_high_a, p_high_b, self._factor)
            prob = prob_a if self._factor < 0.5 else prob_b
            result.append((p_low, p_high, prob))
        return result

    def humidity_band(self, env_config: dict[str, Any]) -> HumidityBand:
        """Return interpolated humidity band with stage-selected probability."""
        low_a, high_a = _hum_limits(self._stage_a)
        low_b, high_b = _hum_limits(self._stage_b)
        low = interpolate_value(low_a, low_b, self._factor)
        high = interpolate_value(high_a, high_b, self._factor)

        if (
            self._stage_a in (BayesianStage.SEEDLING, BayesianStage.CLONE, BayesianStage.VEG)
            and self._factor < 0.5
        ):
            prob = env_config.get("prob_humidity_high_veg", PROB_HUMIDITY_HIGH_VEG)
        elif BayesianStage.FLOWER_LATE in (self._stage_a, self._stage_b) and self._factor > 0.5:
            prob = PROB_HUMIDITY_FLOWER_LATE_OUT_OF_RANGE
        else:
            prob = PROB_HUMIDITY_FLOWER_MID_OUT_OF_RANGE

        return HumidityBand(low, high, prob)

    def co2_optimal_band(self) -> list[tuple[float, float, Any]]:
        """Return interpolated optimal CO2 bands."""
        limits_a = CO2_OPTIMAL_THRESHOLDS.get(self._stage_a, [])
        limits_b = CO2_OPTIMAL_THRESHOLDS.get(self._stage_b, [])

        result: list[tuple[float, float, Any]] = []
        for i in range(min(len(limits_a), len(limits_b))):
            co2_low_a, co2_high_a, prob_a = limits_a[i]
            co2_low_b, co2_high_b, prob_b = limits_b[i]
            co2_low = interpolate_value(co2_low_a, co2_low_b, self._factor)
            co2_high = interpolate_value(co2_high_a, co2_high_b, self._factor)
            prob = prob_a if self._factor < 0.5 else prob_b
            result.append((co2_low, co2_high, prob))
        return result

    # ── Display interface ────────────────────────────────────────────────────

    def vpd_display_targets(self) -> VpdDisplayTargets:
        """Return day/night VPD display targets using .get fallbacks.

        Uses veg-stage fallback on missing keys — distinct from vpd_stress_band
        which uses direct subscript access and raises on a missing stage.
        """
        thr_a = VPD_STRESS_THRESHOLDS.get(self._stage_a, VPD_STRESS_THRESHOLDS[BayesianStage.VEG])
        thr_b = VPD_STRESS_THRESHOLDS.get(self._stage_b, VPD_STRESS_THRESHOLDS[BayesianStage.VEG])

        def _interp(
            data_a: dict[str, Any], data_b: dict[str, Any]
        ) -> tuple[float, float, float, float]:
            stress_a = data_a.get("stress", (0.8, 1.4))
            stress_b = data_b.get("stress", (0.8, 1.4))
            mild_a = data_a.get("mild", (1.0, 1.2))
            mild_b = data_b.get("mild", (1.0, 1.2))
            return (
                interpolate_value(stress_a[0], stress_b[0], self._factor),
                interpolate_value(stress_a[1], stress_b[1], self._factor),
                interpolate_value(mild_a[0], mild_b[0], self._factor),
                interpolate_value(mild_a[1], mild_b[1], self._factor),
            )

        d_danger_min, d_danger_max, d_target_min, d_target_max = _interp(
            thr_a["day"], thr_b["day"]
        )
        n_danger_min, n_danger_max, n_target_min, n_target_max = _interp(
            thr_a["night"], thr_b["night"]
        )

        return VpdDisplayTargets(
            day_target_min=d_target_min,
            day_target_max=d_target_max,
            day_danger_min=d_danger_min,
            day_danger_max=d_danger_max,
            night_target_min=n_target_min,
            night_target_max=n_target_max,
            night_danger_min=n_danger_min,
            night_danger_max=n_danger_max,
        )
