"""Base class for post-harvest (drying/curing) evaluation strategies."""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from custom_components.growspace_manager.bayesian_evaluator import (
        ObservationList,
        ReasonList,
    )
    from custom_components.growspace_manager.models import (
        EnvironmentState,
        GrowspaceType,
    )


class PostHarvestEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Base strategy for post-harvest (drying/curing) condition evaluation."""

    @property
    @abstractmethod
    def growspace_type(self) -> GrowspaceType:
        """The growspace type this strategy applies to."""

    @property
    @abstractmethod
    def thresholds(self) -> dict:
        """The threshold constants for this strategy."""

    @property
    @abstractmethod
    def label(self) -> str:
        """Human-readable label used in reason strings (e.g. 'Drying', 'Curing')."""

    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate post-harvest conditions."""
        growspace = self._get_growspace()
        if not growspace or growspace.growspace_type != self.growspace_type:
            return [], []

        if None in (state.temp, state.humidity):
            return [], []

        reasons: ReasonList = []
        all_observations: ObservationList = []

        temp_min, temp_max, temp_prob_opt, temp_prob_out = self.thresholds["temp"]
        hum_min, hum_max, hum_prob_opt, hum_prob_out = self.thresholds["humidity"]

        if state.temp is not None:
            if temp_min <= state.temp <= temp_max:
                all_observations.append(temp_prob_opt)
                reasons.append((temp_prob_opt[0], f"Temp Optimal for {self.label}"))
            else:
                all_observations.append(temp_prob_out)
                reasons.append((temp_prob_out[0], "Temp out of range"))

        if state.humidity is not None:
            if hum_min <= state.humidity <= hum_max:
                all_observations.append(hum_prob_opt)
                reasons.append((hum_prob_opt[0], f"Humidity Optimal for {self.label}"))
            else:
                all_observations.append(hum_prob_out)
                reasons.append((hum_prob_out[0], "Humidity out of range"))

        return all_observations, reasons
