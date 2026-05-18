"""Stress evaluation strategy."""

from __future__ import annotations

from typing import TYPE_CHECKING

from custom_components.growspace_manager.bayesian_evaluator import (
    async_evaluate_stress_trend,
    evaluate_active_desiccation,
    evaluate_active_saturation,
    evaluate_direct_co2_stress,
    evaluate_direct_humidity_stress,
    evaluate_direct_temp_stress,
    evaluate_direct_vpd_stress,
    evaluate_soil_moisture_stress,
    evaluate_substrate_temp_stress,
)

from .evaluator_strategy import BayesianEvaluatorStrategy

if TYPE_CHECKING:
    from custom_components.growspace_manager.bayesian_evaluator import (
        ObservationList,
        ReasonList,
    )
    from custom_components.growspace_manager.models import EnvironmentState


class StressEvaluatorStrategy(BayesianEvaluatorStrategy):
    """Strategy for evaluating plant stress."""

    async def async_evaluate(
        self, state: EnvironmentState
    ) -> tuple[ObservationList, ReasonList]:
        """Evaluate stress conditions."""
        all_observations: ObservationList = []
        all_reasons: ReasonList = []
        env_config_dict = self.env_config.to_dict()

        checks = [
            evaluate_direct_temp_stress,
            evaluate_direct_humidity_stress,
            evaluate_direct_vpd_stress,
            evaluate_direct_co2_stress,
            evaluate_active_desiccation,
            evaluate_active_saturation,
            evaluate_soil_moisture_stress,
            evaluate_substrate_temp_stress,
        ]

        for check_func in checks:
            obs, rsn = check_func(state, env_config_dict)
            all_observations.extend(obs)
            all_reasons.extend(rsn)

        if self.env_config.temperature_sensor:
            obs, rsn, _ = await async_evaluate_stress_trend(
                self.env_config, self._get_state, self._analyze_trend, state
            )
            all_observations.extend(obs)
            all_reasons.extend(rsn)

        return all_observations, all_reasons

    def get_notification_title_message(
        self, new_state_on: bool, reasons: ReasonList
    ) -> tuple[str, str] | None:
        """Notify on rising edge of stress."""
        if new_state_on:
            growspace = self._get_growspace()
            name = growspace.name if growspace else "Unknown"
            message = self._get_notification_message(
                f"High stress conditions detected in {name}", reasons
            )
            return (f"Plant Stress Alert: {name}", message)
        return None
