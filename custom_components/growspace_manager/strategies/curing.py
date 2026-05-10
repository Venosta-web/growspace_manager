"""Curing evaluation strategy."""

from __future__ import annotations

from custom_components.growspace_manager.bayesian_data import CURING_THRESHOLDS
from custom_components.growspace_manager.models import GrowspaceType

from .post_harvest import PostHarvestEvaluatorStrategy


class CuringEvaluatorStrategy(PostHarvestEvaluatorStrategy):
    """Strategy for evaluating curing conditions."""

    @property
    def growspace_type(self) -> GrowspaceType:
        return GrowspaceType.CURE

    @property
    def thresholds(self) -> dict:
        return CURING_THRESHOLDS

    @property
    def label(self) -> str:
        return "Curing"
