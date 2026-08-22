"""Environment analyzer for air exchange recommendations and biological metrics."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .domain.environmental_targets import StageEnvironmentalTargets
from .domain.stage import BayesianStage, StageDays, classify_stages
from .utils import VPDCalculator

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from .coordinator import GrowspaceCoordinator
    from .models import Growspace

_LOGGER = logging.getLogger(__name__)


class EnvironmentAnalyzer:
    """Analyzes environmental conditions, stage progression, and biological targets."""

    def __init__(self, hass: HomeAssistant, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the environment analyzer.

        Args:
            hass: The Home Assistant instance.
            coordinator: The GrowspaceCoordinator instance.
        """
        self.hass = hass
        self.coordinator = coordinator

    def calculate_biological_metrics(
        self,
        growspace: Growspace,
        days: StageDays,
    ) -> dict[str, Any]:
        """Calculate biological target metrics for the growspace.

        Returns a dict with vpd_status="unknown" and None targets when no plants
        are present (days is all -1 / EMPTY), so empty growspaces don't fire alerts.
        """
        classification = classify_stages(days)

        if classification.stage_a == BayesianStage.EMPTY:
            return {
                "granular_stage": BayesianStage.EMPTY,
                "is_day": self.determine_is_day(growspace),
                "vpd_target_min": None,
                "vpd_target_max": None,
                "vpd_danger_min": None,
                "vpd_danger_max": None,
                "vpd_status": "unknown",
                "day_vpd_target_min": None,
                "day_vpd_target_max": None,
                "day_vpd_danger_min": None,
                "day_vpd_danger_max": None,
                "night_vpd_target_min": None,
                "night_vpd_target_max": None,
                "night_vpd_danger_min": None,
                "night_vpd_danger_max": None,
                "transition_factor": 0.0,
                "transition_stages": (BayesianStage.EMPTY, BayesianStage.EMPTY),
            }

        granular_stage = classification.display_stage
        is_day = self.determine_is_day(growspace)

        stage_a = classification.stage_a
        stage_b = classification.stage_b
        factor = classification.factor

        display = StageEnvironmentalTargets(
            stage_a, stage_b, factor
        ).vpd_display_targets()
        d_danger_min = display.day_danger_min
        d_danger_max = display.day_danger_max
        d_target_min = display.day_target_min
        d_target_max = display.day_target_max
        n_danger_min = display.night_danger_min
        n_danger_max = display.night_danger_max
        n_target_min = display.night_target_min
        n_target_max = display.night_target_max

        # Determine current active targets based on is_day
        danger_min = d_danger_min if is_day else n_danger_min
        danger_max = d_danger_max if is_day else n_danger_max
        target_min = d_target_min if is_day else n_target_min
        target_max = d_target_max if is_day else n_target_max

        vpd_status = "unknown"
        env_config = growspace.environment_config
        vpd_sensors = env_config.vpd_sensors or (
            [env_config.vpd_sensor] if env_config.vpd_sensor else []
        )

        if vpd_sensors:
            current_vpd = self._get_aggregated_sensor_value(vpd_sensors)
            if current_vpd is not None:
                if current_vpd < danger_min or current_vpd > danger_max:
                    vpd_status = "danger"
                elif current_vpd < target_min or current_vpd > target_max:
                    vpd_status = "warning"
                else:
                    vpd_status = "optimal"

        return {
            "granular_stage": granular_stage,
            "is_day": is_day,
            "vpd_target_min": target_min,
            "vpd_target_max": target_max,
            "vpd_danger_min": danger_min,
            "vpd_danger_max": danger_max,
            "vpd_status": vpd_status,
            # Expose specific day/night targets for frontend graphs
            "day_vpd_target_min": d_target_min,
            "day_vpd_target_max": d_target_max,
            "day_vpd_danger_min": d_danger_min,
            "day_vpd_danger_max": d_danger_max,
            "night_vpd_target_min": n_target_min,
            "night_vpd_target_max": n_target_max,
            "night_vpd_danger_min": n_danger_min,
            "night_vpd_danger_max": n_danger_max,
            "transition_factor": factor,
            "transition_stages": (stage_a, stage_b),
        }

    def determine_is_day(self, growspace: Growspace) -> bool:
        """Determine if it is currently day or night in the growspace.

        Args:
            growspace: The growspace object.

        Returns:
            True if lights are on (day), False otherwise.
        """
        light_sensors = growspace.environment_config.light_sensors
        if not light_sensors:
            return True

        has_valid_state = False
        is_day = False

        for sensor in light_sensors:
            light_state = self.hass.states.get(sensor)
            if light_state and light_state.state not in (
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            ):
                if light_state.state == STATE_ON:
                    has_valid_state = True
                    is_day = True
                    break
                if light_state.state == STATE_OFF:
                    has_valid_state = True
                    # is_day remains False
                    break
                try:
                    if float(light_state.state) > 0:
                        has_valid_state = True
                        is_day = True
                        break
                    # If it parses but is 0, it's valid code (night)
                    has_valid_state = True
                except ValueError, TypeError:
                    pass

        if not has_valid_state:
            return True

        return is_day

    def _get_sensor_value(self, entity_id: str | None) -> float | None:
        """Safely get the numeric state of a sensor entity from Home Assistant.

        Args:
            entity_id: The entity ID to look up.

        Returns:
            The numeric state of the sensor, or None if unavailable or invalid.
        """
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state and state.state not in ["unknown", "unavailable"]:
            try:
                return float(state.state)
            except ValueError, TypeError:
                return None
        return None

    def _get_aggregated_sensor_value(self, sensor_ids: list[str]) -> float | None:
        """Get the average value from a list of sensor entity IDs."""
        if not sensor_ids:
            return None

        values = []
        for sensor_id in sensor_ids:
            val = self._get_sensor_value(sensor_id)
            if val is not None:
                values.append(val)

        if not values:
            return None

        return sum(values) / len(values)

    def _get_outside_conditions(
        self, global_settings: dict[str, Any]
    ) -> tuple[float | None, float | None, float | None]:
        """Get outside environmental conditions from weather entity.

        Args:
            global_settings: Global configuration settings.

        Returns:
            Tuple of (temperature, humidity, VPD).
        """
        outside_temp = None
        outside_humidity = None
        weather_entity_id = global_settings.get("weather_entity")

        if weather_entity_id:
            weather_state = self.hass.states.get(weather_entity_id)
            if weather_state and weather_state.attributes:
                outside_temp = weather_state.attributes.get("temperature")
                outside_humidity = weather_state.attributes.get("humidity")

        outside_vpd = (
            VPDCalculator.calculate_vpd(outside_temp, outside_humidity)
            if outside_temp is not None and outside_humidity is not None
            else None
        )

        return outside_temp, outside_humidity, outside_vpd

    def _get_lung_room_conditions(
        self, global_settings: dict[str, Any]
    ) -> tuple[float | None, float | None, float | None]:
        """Get lung room environmental conditions from sensors.

        Args:
            global_settings: Global configuration settings.

        Returns:
            Tuple of (temperature, humidity, VPD).
        """
        lung_room_temp = self._get_sensor_value(
            global_settings.get("lung_room_temp_sensor")
        )
        lung_room_humidity = self._get_sensor_value(
            global_settings.get("lung_room_humidity_sensor")
        )
        lung_room_vpd = (
            VPDCalculator.calculate_vpd(lung_room_temp, lung_room_humidity)
            if lung_room_temp is not None and lung_room_humidity is not None
            else None
        )

        return lung_room_temp, lung_room_humidity, lung_room_vpd

    def _calculate_recommendation(
        self,
        growspace_id: str,
        current_vpd: float | None,
        target_vpd: float | None,
        outside_temp: float | None,
        outside_vpd: float | None,
        lung_room_temp: float | None,
        lung_room_vpd: float | None,
    ) -> str:
        """Calculate the best air exchange recommendation for a growspace.

        Args:
            growspace_id: The ID of the growspace.
            current_vpd: Current VPD in the growspace.
            target_vpd: Target VPD for the growspace.
            outside_temp: Outside air temperature.
            outside_vpd: Outside air VPD.
            lung_room_temp: Lung room temperature.
            lung_room_vpd: Lung room VPD.

        Returns:
            The recommendation string: "Idle", "Open Window", or "Ventilate Lung Room".
        """
        if current_vpd is None or target_vpd is None:
            return "Idle"

        growspace = self.coordinator.growspaces.get(growspace_id)
        if not growspace:
            return "Idle"

        min_temp = growspace.environment_config.minimum_source_air_temperature
        current_diff = abs(current_vpd - target_vpd)
        best_option = "Idle"
        best_diff = current_diff

        # Evaluate outside air
        if (
            outside_vpd is not None
            and outside_temp is not None
            and outside_temp >= min_temp
        ):
            outside_diff = abs(outside_vpd - target_vpd)
            if outside_diff < best_diff:
                best_diff = outside_diff
                best_option = "Open Window"

        # Evaluate lung room air
        if (
            lung_room_vpd is not None
            and lung_room_temp is not None
            and lung_room_temp >= min_temp
        ):
            lung_room_diff = abs(lung_room_vpd - target_vpd)
            if lung_room_diff < best_diff:
                best_diff = lung_room_diff
                best_option = "Ventilate Lung Room"

        return best_option

    async def async_update_air_exchange_recommendations(self) -> None:
        """Calculate and store air exchange recommendations for each growspace.

        This method compares the environmental conditions of outside air and a
        'lung room' to the conditions in each growspace under stress, recommending
        the best source for air exchange to correct the environment.
        """
        recommendations = {}
        global_settings = self.coordinator.options.get("global_settings", {})

        # Get outside conditions
        outside_temp, _outside_humidity, outside_vpd = self._get_outside_conditions(
            global_settings
        )

        # Get lung room conditions
        lung_room_temp, _lung_room_humidity, lung_room_vpd = (
            self._get_lung_room_conditions(global_settings)
        )

        entity_registry = er.async_get(self.hass)
        for growspace_id, growspace in self.coordinator.growspaces.items():
            # Find the entity ID from the unique ID
            stress_sensor_unique_id = f"{DOMAIN}_{growspace_id}_stress"
            stress_sensor_entity_id = entity_registry.async_get_entity_id(
                "binary_sensor", DOMAIN, stress_sensor_unique_id
            )

            if not stress_sensor_entity_id:
                recommendations[growspace_id] = "Idle"  # Sensor not registered yet
                continue

            stress_state = self.hass.states.get(stress_sensor_entity_id)

            if not stress_state or stress_state.state != "on":
                recommendations[growspace_id] = "Idle"
                continue

            env_config = growspace.environment_config
            vpd_sensors = env_config.vpd_sensors or (
                [env_config.vpd_sensor] if env_config.vpd_sensor else []
            )
            current_vpd = self._get_aggregated_sensor_value(vpd_sensors)
            target_vpd = (
                self.coordinator.data.get("bayesian_sensors_reason", {})
                .get(growspace_id, {})
                .get("target_vpd")
            )

            recommendations[growspace_id] = self._calculate_recommendation(
                growspace_id,
                current_vpd,
                target_vpd,
                outside_temp,
                outside_vpd,
                lung_room_temp,
                lung_room_vpd,
            )

        data: dict[str, Any] = self.coordinator.data
        if "air_exchange_recommendations" not in data:
            data["air_exchange_recommendations"] = {}
        data["air_exchange_recommendations"].update(recommendations)
