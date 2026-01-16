"""Base class for Bayesian Sensor Evaluator Strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..bayesian_evaluator import ObservationList, ReasonList
    from ..binary_sensor import BayesianEnvironmentSensor
    from ..models import EnvironmentState


class BayesianEvaluatorStrategy(ABC):
    """Abstract base class for Bayesian evaluation strategies."""

    def __init__(self, sensor: BayesianEnvironmentSensor) -> None:
        """Initialize the strategy with reference to the sensor."""
        self.sensor = sensor

    @abstractmethod
    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate the environment state and return observations and reasons.

        Returns:
            tuple[ObservationList, ReasonList]: (list of probabilities, list of reasons)
        """

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Return the title and message for a notification based on state change.

        Args:
            new_state_on: Whether the new state is ON (True) or OFF (False).

        Returns:
            tuple[str, str] | None: (Title, Message) or None if no notification.
        """
        return None
