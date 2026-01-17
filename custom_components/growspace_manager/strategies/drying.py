"""Drying evaluation strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..bayesian_data import DRYING_THRESHOLDS
from ..const import PlantStage
from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from ..bayesian_evaluator import ObservationList, ReasonList
    from ..models import EnvironmentState


class DryingEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Strategy for evaluating drying conditions."""

    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate drying conditions."""
        # Skip if not a dry growspace
        if self.sensor.growspace_id != PlantStage.DRY:
            return [], []

        if None in (state.temp, state.humidity):
            return [], []

        reasons: ReasonList = []
        # Note: We return observations as a list of priors to apply?
        # The base logic in binary_sensor uses `_calculate_bayesian_probability(prior, observations)`.
        # Observations are usually (p_true, p_false).
        # In BayesianDryingSensor, it did custom calculation of "prob" updating it iteratively.
        # "prob = (prob * weight) / ..." -> This is the same formula as `_calculate_bayesian_probability`.
        # So we can just return the weights (p_true, p_false) as observations.

        all_observations: ObservationList = []

        # Unpack thresholds
        temp_min, temp_max, temp_prob_opt, temp_prob_out = DRYING_THRESHOLDS["temp"]
        hum_min, hum_max, hum_prob_opt, hum_prob_out = DRYING_THRESHOLDS["humidity"]

        # Temp check
        if state.temp is not None:
            if temp_min <= state.temp <= temp_max:
                all_observations.append(temp_prob_opt)
                reasons.append((temp_prob_opt[0], "Temp Optimal for Drying"))
            else:
                all_observations.append(temp_prob_out)
                reasons.append((temp_prob_out[0], "Temp out of range"))

        # Humidity check
        if state.humidity is not None:
            if hum_min <= state.humidity <= hum_max:
                all_observations.append(hum_prob_opt)
                reasons.append((hum_prob_opt[0], "Humidity Optimal for Drying"))
            else:
                all_observations.append(hum_prob_out)
                reasons.append((hum_prob_out[0], "Humidity out of range"))

        return all_observations, reasons
