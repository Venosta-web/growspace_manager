"""Mold risk evaluation strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..bayesian_data import PROB_MOLD_HUMIDIFIER_ON, PROB_MOLD_STAGNANT_AIR
from ..bayesian_evaluator import async_evaluate_mold_risk_trend
from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from ..bayesian_evaluator import ObservationList
    from ..models import EnvironmentState


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
        if state.humidity is None:
            return

        # Define thresholds based on growth stage
        # Seedlings and clones need high humidity (up to 90%)
        is_early_stage = (state.seedling_days > 0 or state.clone_days > 0) and (
            state.flower_days == 0
        )

        if is_early_stage:
            critical_humidity = 92.0
            high_humidity = 88.0
        elif state.flower_days > 0:
            # Late flower is more sensitive
            critical_humidity = 65.0 if state.flower_days > 42 else 75.0
            high_humidity = 60.0 if state.flower_days > 42 else 70.0
        else:
            # Veg stage
            critical_humidity = 85.0
            high_humidity = 80.0

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
        is_early_stage = (state.seedling_days > 0 or state.clone_days > 0) and (
            state.flower_days == 0
        )

        threshold = 0.0
        if is_early_stage:
            threshold = 90.0
        elif state.flower_days == 0:  # Veg
            threshold = 80.0
        else:  # Flower
            threshold = 70.0

        if state.humidity is None or state.humidity < threshold:
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
        is_early_stage = (state.seedling_days > 0 or state.clone_days > 0) and (
            state.flower_days == 0
        )

        is_risk = True
        if is_early_stage:
            if state.humidity is None or state.humidity < 90:
                is_risk = False
        elif state.flower_days == 0:  # Veg
            if state.humidity is None or state.humidity < 85:
                is_risk = False
        elif state.flower_days > 40:  # Late Flower
            if state.humidity is None or state.humidity < 60:
                is_risk = False
        elif state.humidity is None or state.humidity < 70:
            is_risk = False

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
            message = self.sensor._generate_notification_message(
                "High mold risk detected"
            )
            return (f"High Mold Risk in {name}", message)
        return None
