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
        env_config_dict = self.sensor.env_config.to_dict()

        # 1. Direct Sensor Evaluation (Temp, Hum, VPD, CO2)
        # We can use the helper functions from bayesian_evaluator
        checks = [
            evaluate_direct_temp_stress,
            evaluate_direct_humidity_stress,
            evaluate_direct_vpd_stress,
            evaluate_direct_co2_stress,
            evaluate_active_desiccation,
            evaluate_active_saturation,
            evaluate_soil_moisture_stress,
        ]

        for check_func in checks:
            obs, rsn = check_func(state, env_config_dict)
            all_observations.extend(obs)
            all_reasons.extend(rsn)

        # 2. Trends
        if self.sensor.env_config.temperature_sensor:
            # async_evaluate_stress_trend returns (obs, reasons, states)
            # The function expects sensor_instance because it calls `async_analyze_sensor_trend` on it
            # We pass self.sensor which is the BayesianEnvironmentSensor instance
            obs, rsn, _ = await async_evaluate_stress_trend(self.sensor, state)
            all_observations.extend(obs)
            all_reasons.extend(rsn)

        return all_observations, all_reasons

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Notify on rising edge of stress."""
        if new_state_on:
            growspace = self.sensor.coordinator.growspaces.get(self.sensor.growspace_id)
            name = growspace.name if growspace else self.sensor.growspace_id
            message = self.sensor.generate_notification_message(
                f"High stress conditions detected in {name}"
            )
            return (f"Plant Stress Alert: {name}", message)
        return None
