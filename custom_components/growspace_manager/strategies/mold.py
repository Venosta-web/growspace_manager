"""Mold risk evaluation strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..bayesian_data import PROB_MOLD_HUMIDIFIER_ON, PROB_MOLD_STAGNANT_AIR
from ..bayesian_evaluator import async_evaluate_mold_risk_trend
from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from ..bayesian_evaluator import ObservationList, ReasonList
    from ..models import EnvironmentState


class MoldRiskEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Strategy for evaluating mold risk."""

    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate mold risk conditions."""
        all_observations: ObservationList = []
        all_reasons: ReasonList = []

        if None in (state.temp, state.humidity):
            return [], []

        # 1. High Humidity (Stage-Aware)
        obs, rsn = self._evaluate_humidity_risk(state)
        if obs:
            all_observations.append(obs)
            all_reasons.append(rsn)

        # 2. Low Circulation
        # In Veg, only penalize fan off if humidity is already somewhat high
        if state.fan_off:
            is_risk = True
            if state.flower_days == 0 and (
                state.humidity is None or state.humidity < 80
            ):
                is_risk = False

            if is_risk:
                prob = (
                    PROB_MOLD_STAGNANT_AIR
                    if isinstance(PROB_MOLD_STAGNANT_AIR, tuple)
                    else (0.85, 0.15)
                )
                all_observations.append(prob)
                all_reasons.append((prob[0], "Circulation Fan Off"))

        # 3. Humidifier
        # Humidifier on is normal in Veg/Early Flower.
        # Only penalize if humidity is already near danger zones.
        if state.humidifier_value and state.humidifier_value > 0:
            is_risk = True
            if state.flower_days == 0:  # Veg
                if state.humidity is None or state.humidity < 85:
                    is_risk = False
            elif state.flower_days > 40:  # Late Flower
                if state.humidity is None or state.humidity < 60:
                    is_risk = False
            elif state.humidity is None or state.humidity < 70:
                is_risk = False

            if is_risk:
                prob = (
                    PROB_MOLD_HUMIDIFIER_ON
                    if isinstance(PROB_MOLD_HUMIDIFIER_ON, tuple)
                    else (0.95, 0.10)
                )
                all_observations.append(prob)
                all_reasons.append((prob[0], "Humidifier On"))

        # 4. Trends
        if self.sensor.env_config.humidity_sensor:
            obs_list, rsn_list, _ = await async_evaluate_mold_risk_trend(
                self.sensor, state
            )
            all_observations.extend(obs_list)
            all_reasons.extend(rsn_list)

        return all_observations, all_reasons

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

    def _evaluate_humidity_risk(
        self, state: EnvironmentState
    ) -> tuple[tuple[float, float], tuple[float, str]] | tuple[None, None]:
        """Evaluate humidity risk based on growth stage."""
        hum = state.humidity
        if hum is None:
            return None, None

        is_high_humidity = False

        if state.flower_days == 0:  # Veg
            # Powdery Mildew risk only at very high RH
            if hum > 85:
                is_high_humidity = True
        elif state.flower_days > 40:  # Late Flower
            # Botrytis risk
            if hum > 60:
                is_high_humidity = True
        elif hum > 70:  # Early/Mid Flower
            is_high_humidity = True

        if is_high_humidity:
            prob = (0.8, 0.2)
            return prob, (prob[0], f"High Humidity ({hum}%)")
        return None, None
