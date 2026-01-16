"""Optimal conditions evaluation strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..bayesian_evaluator import (
    evaluate_optimal_co2,
    evaluate_optimal_temperature,
    evaluate_optimal_vpd,
)
from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from ..bayesian_evaluator import ObservationList, ReasonList
    from ..models import EnvironmentState


class OptimalConditionsEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Strategy for evaluating optimal conditions."""

    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate optimal conditions."""
        all_observations: ObservationList = []
        all_reasons: ReasonList = []

        if None in (state.temp, state.humidity, state.vpd):
            return [], []

        env_config_dict = self.sensor.env_config.to_dict()

        for check_func in [
            evaluate_optimal_temperature,
            evaluate_optimal_vpd,
            evaluate_optimal_co2,
        ]:
            obs, rsn = check_func(state, env_config_dict)
            all_observations.extend(obs)
            all_reasons.extend(rsn)

        return all_observations, all_reasons

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Notify when conditions DROP out of optimal (falling edge)."""
        if not new_state_on:
            growspace = self.sensor.coordinator.growspaces.get(self.sensor.growspace_id)
            name = growspace.name if growspace else self.sensor.growspace_id
            message = self.sensor._generate_notification_message(
                "Conditions no longer optimal"
            )
            return (f"Optimal Conditions Lost: {name}", message)
        return None
