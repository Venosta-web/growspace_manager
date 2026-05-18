"""Base class for Bayesian Sensor Evaluator Strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.growspace_manager.bayesian_evaluator import (
        ObservationList,
        ReasonList,
    )
    from custom_components.growspace_manager.models import (
        EnvironmentConfig,
        EnvironmentState,
        Growspace,
    )
    from homeassistant.core import State


class BayesianEvaluatorStrategy(ABC):
    """Abstract base class for Bayesian evaluation strategies."""

    def __init__(
        self,
        env_config: EnvironmentConfig,
        analyze_trend: Callable[[str, int, float], Awaitable[dict[str, Any]]],
        get_state: Callable[[str], State | None],
        get_growspace: Callable[[], Growspace | None],
        get_notification_message: Callable[[str, ReasonList], str],
    ) -> None:
        """Initialize the strategy with injected dependencies."""
        self.env_config = env_config
        self._analyze_trend = analyze_trend
        self._get_state = get_state
        self._get_growspace = get_growspace
        self._get_notification_message = get_notification_message

    @abstractmethod
    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate the environment state and return observations and reasons."""

    def get_notification_title_message(
        self, new_state_on: bool, reasons: ReasonList
    ) -> tuple[str, str] | None:
        """Return the title and message for a notification based on state change."""
        return None
