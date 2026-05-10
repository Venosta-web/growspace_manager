"""Curing evaluation strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.growspace_manager.bayesian_data import CURING_THRESHOLDS
from custom_components.growspace_manager.models import GrowspaceType

from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from custom_components.growspace_manager.bayesian_evaluator import (
        ObservationList,
        ReasonList,
    )
    from custom_components.growspace_manager.models import EnvironmentState


class CuringEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Strategy for evaluating curing conditions."""

    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate curing conditions."""
        # Skip if not a cure growspace
        growspace = self.sensor._get_growspace(self.sensor.growspace_id)
        if not growspace or growspace.growspace_type != GrowspaceType.CURE:
            return [], []

        if None in (state.temp, state.humidity):
            return [], []

        reasons: ReasonList = []
        all_observations: ObservationList = []

        # Unpack thresholds
        temp_min, temp_max, temp_prob_opt, temp_prob_out = CURING_THRESHOLDS["temp"]
        hum_min, hum_max, hum_prob_opt, hum_prob_out = CURING_THRESHOLDS["humidity"]

        # Temp check
        if state.temp is not None:
            if temp_min <= state.temp <= temp_max:
                all_observations.append(temp_prob_opt)
                reasons.append((temp_prob_opt[0], "Temp Optimal for Curing"))
            else:
                all_observations.append(temp_prob_out)
                reasons.append((temp_prob_out[0], "Temp out of range"))

        # Humidity check
        if state.humidity is not None:
            if hum_min <= state.humidity <= hum_max:
                all_observations.append(hum_prob_opt)
                reasons.append((hum_prob_opt[0], "Humidity Optimal for Curing"))
            else:
                all_observations.append(hum_prob_out)
                reasons.append((hum_prob_out[0], "Humidity out of range"))

        return all_observations, reasons
