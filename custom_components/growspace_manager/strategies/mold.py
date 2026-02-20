"""Mold risk evaluation strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.growspace_manager.bayesian_data import (
    CRITICAL_HUMIDITY_THRESHOLDS,
    PROB_MOLD_HUMIDIFIER_ON,
    PROB_MOLD_STAGNANT_AIR,
)
from custom_components.growspace_manager.bayesian_evaluator import (
    async_evaluate_mold_risk_trend,
)
from custom_components.growspace_manager.utils import (
    calculate_stage_transition,
    interpolate_value,
)

from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from custom_components.growspace_manager.bayesian_evaluator import ObservationList
    from custom_components.growspace_manager.models import EnvironmentState


class MoldRiskEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Strategy for evaluating mold risk."""

    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, list[tuple[float, str]]]:
        """Evaluate mold risk based on environment state."""
        observations: ObservationList = []
        reasons: list[tuple[float, str]] = []

        if state.humidity is None:
            return observations, reasons

        # 1. Evaluate Humidity Risk
        self._evaluate_humidity_risk(state, observations, reasons)

        # 2. Evaluate Circulation Fan Risk
        self._evaluate_circulation_risk(state, observations, reasons)

        # 3. Evaluate Humidifier Risk
        self._evaluate_humidifier_risk(state, observations, reasons)

        # 4. Trends
        if self.sensor.env_config.humidity_sensor:
            obs_list, rsn_list, _ = await async_evaluate_mold_risk_trend(
                self.sensor, state
            )
            observations.extend(obs_list)
            reasons.extend(rsn_list)

        return observations, reasons

    def _evaluate_humidity_risk(
        self,
        state: EnvironmentState,
        observations: ObservationList,
        reasons: list[tuple[float, str]],
    ) -> None:
        """Evaluate mold risk based on humidity and growth stage."""

        # Use transition logic for smoother mold risk thresholds
        stage_a, stage_b, factor = calculate_stage_transition(
            state.flower_days, state.veg_days, state.seedling_days, state.clone_days
        )

        crit_a = CRITICAL_HUMIDITY_THRESHOLDS[stage_a]["critical"]
        crit_b = CRITICAL_HUMIDITY_THRESHOLDS[stage_b]["critical"]
        high_a = CRITICAL_HUMIDITY_THRESHOLDS[stage_a]["high"]
        high_b = CRITICAL_HUMIDITY_THRESHOLDS[stage_b]["high"]

        critical_humidity = interpolate_value(crit_a, crit_b, factor)
        high_humidity = interpolate_value(high_a, high_b, factor)

        is_early_stage = stage_a in (
            "seedling",
            "clone",
            "seedling_standard",
            "clone_standard",
        ) or stage_b in (
            "seedling",
            "clone",
            "seedling_standard",
            "clone_standard",
        )

        if not is_early_stage and state.humidity > 90.0:
            # Extra penalty for extremely high humidity in non-early stages
            observations.append((0.99, 0.01))
            reasons.append((0.95, f"Extreme humidity risk: {state.humidity}%"))
        elif state.humidity >= critical_humidity:
            observations.append((0.95, 0.05))
            reasons.append((0.9, f"Critical humidity: {state.humidity}%"))
        elif state.humidity >= high_humidity:
            observations.append((0.8, 0.2))
            reasons.append((0.7, f"High humidity: {state.humidity}%"))

    def _evaluate_circulation_risk(
        self,
        state: EnvironmentState,
        observations: ObservationList,
        reasons: list[tuple[float, str]],
    ) -> None:
        """Evaluate risk from low air circulation."""
        if not state.fan_off:
            return

        # Define thresholds based on growth stage
        stage_a, stage_b, factor = calculate_stage_transition(
            state.flower_days, state.veg_days, state.seedling_days, state.clone_days
        )

        # Use high humidity threshold as a safe point for air circulation
        thr_a = CRITICAL_HUMIDITY_THRESHOLDS[stage_a]["high"]
        thr_b = CRITICAL_HUMIDITY_THRESHOLDS[stage_b]["high"]
        threshold = interpolate_value(thr_a, thr_b, factor)

        if state.humidity < threshold:
            return

        prob = (
            PROB_MOLD_STAGNANT_AIR
            if isinstance(PROB_MOLD_STAGNANT_AIR, tuple)
            else (0.85, 0.15)
        )
        observations.append(prob)
        reasons.append((prob[0], f"Circulation Fan Off: Humidity is {state.humidity}%"))

    def _evaluate_humidifier_risk(
        self,
        state: EnvironmentState,
        observations: ObservationList,
        reasons: list[tuple[float, str]],
    ) -> None:
        """Evaluate risk from humidifier operation."""
        if not state.humidifier_on:
            return

        # Define thresholds based on growth stage
        stage_a, stage_b, factor = calculate_stage_transition(
            state.flower_days, state.veg_days, state.seedling_days, state.clone_days
        )

        # Use critical humidity threshold
        thr_a = CRITICAL_HUMIDITY_THRESHOLDS[stage_a]["critical"]
        thr_b = CRITICAL_HUMIDITY_THRESHOLDS[stage_b]["critical"]
        threshold = interpolate_value(thr_a, thr_b, factor)

        if state.humidity is None or state.humidity < threshold:
            is_risk = False
        else:
            is_risk = True

        if not is_risk:
            return

        prob = (
            PROB_MOLD_HUMIDIFIER_ON
            if isinstance(PROB_MOLD_HUMIDIFIER_ON, tuple)
            else (0.95, 0.10)
        )
        observations.append(prob)
        reasons.append((prob[0], f"Humidifier On: Humidity is {state.humidity}%"))

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Notify on rising edge of mold risk."""
        if new_state_on:
            growspace = self.sensor.coordinator.growspaces.get(self.sensor.growspace_id)
            if not growspace:
                return None
            name = growspace.name
            message = self.sensor.generate_notification_message(
                "High mold risk detected"
            )
            return (f"High Mold Risk in {name}", message)
        return None
