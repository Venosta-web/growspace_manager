"""Drying evaluation strategy."""

from __future__ import annotations

from custom_components.growspace_manager.bayesian_data import DRYING_THRESHOLDS
from custom_components.growspace_manager.models import GrowspaceType

from .post_harvest import PostHarvestEvaluatorStrategy


class DryingEvaluatorStrategy(PostHarvestEvaluatorStrategy):
    """Strategy for evaluating drying conditions."""

    @property
    def growspace_type(self) -> GrowspaceType:
        return GrowspaceType.DRY

    @property
    def thresholds(self) -> dict:
        return DRYING_THRESHOLDS

    @property
    def label(self) -> str:
        return "Drying"
