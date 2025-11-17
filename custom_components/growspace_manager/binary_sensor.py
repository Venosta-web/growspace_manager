"""Bayesian binary sensors for environmental monitoring in Growspace Manager.

This file defines a set of binary sensors that use Bayesian inference to assess
various environmental conditions within a growspace, such as plant stress, mold
risk, and optimal conditions. It also includes a sensor to verify the light
cycle schedule.
"""

from __future__ import annotations

import logging
from typing import Any
from datetime import date, datetime, timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.recorder import get_instance as get_recorder_instance
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.components.recorder import history
from homeassistant.util.dt import utcnow


from .coordinator import GrowspaceCoordinator
from .const import DOMAIN, DEFAULT_BAYESIAN_PRIORS, DEFAULT_BAYESIAN_THRESHOLDS
from .models import EnvironmentState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager Bayesian binary sensors from a config entry.

    This function is called by Home Assistant to set up the platform. It
    iterates through the growspaces defined in the coordinator and creates the
    appropriate set of binary sensors for each one that has a valid environment
    configuration.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry.
        async_add_entities: A callback function for adding new entities.
    """
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    # Create Bayesian sensors for each growspace that has environment config
    for growspace_id, growspace in coordinator.growspaces.items():
        env_config = getattr(growspace, "environment_config", None)

        if env_config and _validate_env_config(env_config):
            entities.extend(
                [
                    BayesianStressSensor(coordinator, growspace_id, env_config),
                    BayesianMoldRiskSensor(coordinator, growspace_id, env_config),
                    BayesianOptimalConditionsSensor(
                        coordinator, growspace_id, env_config
                    ),
                ]
            )
            if growspace_id == "dry":
                entities.append(
                    BayesianDryingSensor(coordinator, growspace_id, env_config)
                )
            elif growspace_id == "cure":
                entities.append(
                    BayesianCuringSensor(coordinator, growspace_id, env_config)
                )
            if env_config.get("light_sensor"):
                entities.append(
                    LightCycleVerificationSensor(coordinator, growspace_id, env_config)
                )
            _LOGGER.info(
                "Created Bayesian environment sensors for growspace: %s", growspace.name
            )

    if entities:
        async_add_entities(entities)


def _validate_env_config(config: dict) -> bool:
    """Validate that the required environment sensor entities are configured.

    Args:
        config: The environment configuration dictionary for a growspace.

    Returns:
        True if all required sensor keys are present, False otherwise.
    """
    required = ["temperature_sensor", "humidity_sensor", "vpd_sensor"]
    return all(config.get(key) for key in required)


class BayesianEnvironmentSensor(BinarySensorEntity):
    """Base class for Bayesian environment monitoring binary sensors.

    This class provides the core functionality for calculating a Bayesian
    probability based on various environmental inputs. Subclasses implement the
    specific logic for different conditions (e.g., stress, mold risk).
    """

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: dict,
        sensor_type: str,
        name_suffix: str,
        prior_key: str,
        threshold_key: str,
    ) -> None:
        """Initialize the Bayesian environment sensor.

        Args:
            coordinator: The data update coordinator.
            growspace_id: The ID of the growspace being monitored.
            env_config: The environment sensor configuration for the growspace.
            sensor_type: The type of sensor (e.g., 'stress', 'mold_risk').
            name_suffix: The suffix to append to the growspace name for the entity name.
            prior_key: The key to look up the prior probability in the config.
            threshold_key: The key to look up the probability threshold in the config.
        """
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.env_config = env_config
        self._attr_should_poll = False

        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} {name_suffix}"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_{sensor_type}"

        self.prior = env_config.get(prior_key, DEFAULT_BAYESIAN_PRIORS.get(sensor_type))
        self.threshold = env_config.get(
            threshold_key, DEFAULT_BAYESIAN_THRESHOLDS.get(sensor_type)
        )

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

        # Track state of all relevant sensors
        self._sensor_states = {}
        self._reasons: list[tuple[float, str]] = []
        self._probability = 0.0
        self._last_notification_sent: datetime | None = None
        self._notification_cooldown = timedelta(minutes=5)  # Anti-spam cooldown

    def _get_base_environment_state(self) -> EnvironmentState:
        """Fetch sensor values and return a structured EnvironmentState object.

        This method gathers the current state of all relevant environmental sensors
        (temperature, humidity, VPD, etc.) and packages them into a dataclass
        for easier use in probability calculations.

        Returns:
            An EnvironmentState object populated with the latest sensor data.
        """
        temp = self._get_sensor_value(self.env_config.get("temperature_sensor"))
        humidity = self._get_sensor_value(self.env_config.get("humidity_sensor"))
        vpd = self._get_sensor_value(self.env_config.get("vpd_sensor"))
        co2 = self._get_sensor_value(self.env_config.get("co2_sensor"))
        stage_info = self._get_growth_stage_info()
        veg_days = stage_info["veg_days"]
        flower_days = stage_info["flower_days"]

        # Lights-Aware Logic
        light_sensor = self.env_config.get("light_sensor")
        is_lights_on = False
        if light_sensor:
            light_state = self.hass.states.get(light_sensor)
            if light_state:
                if light_state.domain == "sensor":
                    sensor_value = self._get_sensor_value(light_sensor)
                    is_lights_on = bool(sensor_value and sensor_value > 0)
                else:
                    is_lights_on = light_state.state == "on"

        fan_entity = self.env_config.get("circulation_fan")
        fan_off = bool(
            fan_entity
            and (fan_state := self.hass.states.get(fan_entity))
            and fan_state.state == "off"
        )

        self._sensor_states = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "co2": co2,
            "veg_days": veg_days,
            "flower_days": flower_days,
            "is_lights_on": is_lights_on,
            "fan_off": fan_off,
        }

        return EnvironmentState(
            temp=temp,
            humidity=humidity,
            vpd=vpd,
            co2=co2,
            veg_days=veg_days,
            flower_days=flower_days,
            is_lights_on=is_lights_on,
            fan_off=fan_off,
        )

    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        # Listen to coordinator updates
        self.coordinator.async_add_listener(self._handle_coordinator_update)

        # Track all environment sensor states
        sensors = [
            self.env_config.get("temperature_sensor"),
            self.env_config.get("humidity_sensor"),
            self.env_config.get("vpd_sensor"),
            self.env_config.get("co2_sensor"),
            self.env_config.get("circulation_fan"),
        ]

        # Filter out None values
        sensors = [s for s in sensors if s]

        # Set up state change tracking
        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                sensors,
                self._async_sensor_changed,
            )
        )

        # Initial update
        await self.async_update_and_notify()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updates from the data coordinator.

        This is triggered when plants or growspaces are added, removed, or updated,
        ensuring the sensor's calculations are based on the latest data.
        """
        self.hass.async_create_task(self.async_update_and_notify())

    @callback
    def _async_sensor_changed(self, event) -> None:
        """Handle state changes of the monitored environment sensors.

        Args:
            event: The state change event.
        """
        self.hass.async_create_task(self.async_update_and_notify())

    def _get_sensor_value(self, sensor_id: str | None) -> float | None:
        """Safely get the numeric value from a sensor's state.

        Args:
            sensor_id: The entity ID of the sensor.

        Returns:
            The sensor's state as a float, or None if it's unavailable or not numeric.
        """
        if not sensor_id:
            return None

        state = self.hass.states.get(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None

        try:
            return float(state.state)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _days_since(date_str: str) -> int:
        """Calculate the number of days since a given date string.

        Args:
            date_str: The date in 'YYYY-MM-DD' format.

        Returns:
            The number of days that have passed.
        """
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (AttributeError, TypeError, ValueError):
            return 0
        return (date.today() - dt).days

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get the current growth stage duration (veg and flower days) for the growspace.

        It takes the maximum day count among all plants in the growspace to represent
        the overall stage.

        Returns:
            A dictionary containing 'veg_days' and 'flower_days'.
        """
        plants = self.coordinator.get_growspace_plants(self.growspace_id)

        if not plants:
            return {"veg_days": 0, "flower_days": 0}

        max_veg = max(
            (self._days_since(p.veg_start) for p in plants if p.veg_start), default=0
        )
        max_flower = max(
            (self._days_since(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )

        return {
            "veg_days": max_veg,
            "flower_days": max_flower,
        }

    async def _async_analyze_sensor_trend(
        self, sensor_id: str, duration_minutes: int, threshold: float
    ) -> dict[str, Any]:
        """Analyze the trend of a sensor's history to detect rising or falling patterns.

        This method queries the Home Assistant recorder history for a sensor's
        recent states to determine its behavior over time.

        Args:
            sensor_id: The entity ID of the sensor to analyze.
            duration_minutes: The time window in minutes to look back.
            threshold: A value to check if the sensor has consistently crossed.

        Returns:
            A dictionary containing the 'trend' ('rising', 'falling', 'stable')
            and a boolean 'crossed_threshold'.
        """
        start_time = utcnow() - timedelta(minutes=duration_minutes)
        end_time = utcnow()

        try:
            history_list = await get_recorder_instance(
                self.hass
            ).async_add_executor_job(
                lambda: history.get_significant_states(
                    self.hass,
                    start_time,
                    end_time,
                    [sensor_id],
                    include_start_time_state=True,
                )
            )

            states = history_list.get(sensor_id, [])
            numeric_states = [
                (s.last_updated, float(s.state))
                for s in states
                if s.state not in [STATE_UNKNOWN, STATE_UNAVAILABLE]
                and s.state is not None
            ]

            if len(numeric_states) < 2:
                return {"trend": "stable", "crossed_threshold": False}

            # Trend calculation (simplified: change between first and last value)
            start_value = numeric_states[0][1]
            end_value = numeric_states[-1][1]
            change = end_value - start_value

            trend = "stable"
            if change > 0.01:  # Add a small tolerance
                trend = "rising"
            elif change < -0.01:
                trend = "falling"

            # Check if value was consistently above threshold
            crossed_threshold = all(value > threshold for _, value in numeric_states)

            return {"trend": trend, "crossed_threshold": crossed_threshold}

        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.error("Error analyzing sensor history for %s: %s", sensor_id, e)
            return {"trend": "unknown", "crossed_threshold": False}

    def _generate_notification_message(self, base_message: str) -> str:
        """Construct a detailed notification message from the list of reasons.

        The message is built by appending the most significant reasons until
        a character limit is reached, ensuring concise and informative alerts.

        Args:
            base_message: The initial part of the notification message.

        Returns:
            The formatted notification message string.
        """
        sorted_reasons = sorted(self._reasons, reverse=True)
        message = base_message

        for _, reason in sorted_reasons:
            if len(message) + len(reason) + 2 < 65:
                message += f", {reason}"
            else:
                break
        return message

    async def _send_notification(self, title: str, message: str) -> None:
        """Send a notification to the configured target for the growspace.

        This method includes an anti-spam cooldown to prevent flooding the user
        with notifications for flapping states. It also checks if notifications
        are globally enabled for the growspace.

        Args:
            title: The title of the notification.
            message: The body of the notification.
        """
        now = utcnow()
        if (
            self._last_notification_sent
            and (now - self._last_notification_sent) < self._notification_cooldown
        ):
            _LOGGER.debug(
                "Notification cooldown active for %s, skipping notification",
                self.growspace_id,
            )
            return  # Anti-spam: cooldown active

        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if not growspace or not growspace.notification_target:
            _LOGGER.debug(
                "No notification target configured for %s, skipping notification",
                self.growspace_id,
            )
            return  # No target configured

        # Check if notifications are enabled in coordinator
        if not self.coordinator.is_notifications_enabled(self.growspace_id):
            _LOGGER.debug(
                "Notifications disabled in coordinator for %s", self.growspace_id
            )
            return

        self._last_notification_sent = now

        # Get the service name (e.g., "mobile_app_my_phone")
        notification_service = growspace.notification_target.replace("notify.", "")

        try:
            await self.hass.services.async_call(
                "notify",
                notification_service,
                {
                    "message": message,
                    "title": title,
                },
                blocking=False,  # Don't wait for the service to complete
            )
            _LOGGER.info(
                "Notification sent to %s: %s - %s", notification_service, title, message
            )
        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.error(
                "Failed to send notification to %s: %s", notification_service, e
            )

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Return the title and message for a notification based on state change.

        This method is intended to be overridden by subclasses to provide custom
        notification content.

        Args:
            new_state_on: True if the sensor just turned on, False if it turned off.

        Returns:
            A tuple of (title, message), or None if no notification should be sent.
        """
        return None

    async def async_update_and_notify(self) -> None:
        """Update the sensor's probability and send a notification if the state changes."""
        old_state_on = self.is_on
        await self._async_update_probability()
        new_state_on = self.is_on

        if new_state_on != old_state_on:
            notification = self.get_notification_title_message(new_state_on)
            if notification:
                title, message = notification
                await self._send_notification(title, message)

    async def _async_update_probability(self) -> None:
        """Calculate the Bayesian probability based on environmental observations.

        This is the core method that needs to be implemented by each subclass
        to define its specific logic.
        """
        raise NotImplementedError

    @staticmethod
    def _calculate_bayesian_probability(
        prior: float, observations: list[tuple[float, float]]
    ) -> float:
        """Perform the Bayesian calculation.

        Args:
            prior: The prior probability of the condition being true (from 0.0 to 1.0).
            observations: A list of tuples, where each tuple contains
                          (probability_of_observation_if_true,
                           probability_of_observation_if_false).

        Returns:
            The posterior probability after considering all observations.
        """
        if not observations:
            return prior

        # Start with prior odds
        prob_true = prior
        prob_false = 1 - prior

        # Apply each observation using Bayes theorem
        for p_obs_given_true, p_obs_given_false in observations:
            # Update using likelihood ratio
            prob_true *= p_obs_given_true
            prob_false *= p_obs_given_false

        # Normalize to get probability
        total = prob_true + prob_false
        if total == 0:
            return prior

        return prob_true / total

    @property
    def is_on(self) -> bool:
        """Return true if the calculated probability exceeds the configured threshold."""
        return self._probability >= self.threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes for the entity.

        This includes the calculated probability, the threshold, the raw sensor
        observations, and a list of human-readable reasons for the current state.
        """
        return {
            "probability": round(self._probability, 3),
            "threshold": self.threshold,
            "observations": self._sensor_states,
            "reasons": [r[1] for r in sorted(self._reasons, reverse=True)],
        }


class BayesianStressSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting plant stress conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        """Initialize the plant stress sensor."""
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="stress",
            name_suffix="Plants Under Stress",
            prior_key="prior_stress",
            threshold_key="stress_threshold",
        )

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Generate a notification when the sensor turns on.

        Args:
            new_state_on: True if the sensor just turned on.

        Returns:
            A tuple of (title, message) if a notification should be sent.
        """
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"Plants Under Stress in {growspace.name}"
                message = self._generate_notification_message("High stress detected")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate the probability of plant stress based on environmental factors."""
        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        # 1. ASYNCHRONOUS TREND ANALYSIS (High Complexity/IO)
        trend_obs, trend_reasons = await self._async_evaluate_trend_analysis(state)
        observations.extend(trend_obs)
        self._reasons.extend(trend_reasons)

        # 2. DIRECT OBSERVATIONS
        # Grouping complex synchronous checks into focused helpers

        temp_obs, temp_reasons = self._evaluate_direct_temp_stress(state)
        observations.extend(temp_obs)
        self._reasons.extend(temp_reasons)

        hum_obs, hum_reasons = self._evaluate_direct_humidity_stress(state)
        observations.extend(hum_obs)
        self._reasons.extend(hum_reasons)

        vpd_obs, vpd_reasons = self._evaluate_direct_vpd_stress(state)
        observations.extend(vpd_obs)
        self._reasons.extend(vpd_reasons)

        co2_obs, co2_reasons = self._evaluate_direct_co2_stress(state)
        observations.extend(co2_obs)
        self._reasons.extend(co2_reasons)

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()

    # =========================================================================
    # NEW HELPER EVALUATION METHODS
    # =========================================================================

    async def _async_evaluate_trend_analysis(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate rising trends for temperature, humidity, and VPD from sensors/history."""
        observations = []
        reasons = []

        self._sensor_states["temperature_trend"] = "stable"
        self._sensor_states["humidity_trend"] = "stable"
        self._sensor_states["vpd_trend"] = "stable"

        for sensor_key, trend_key in [
            ("temperature", "temperature_trend"),
            ("humidity", "humidity_trend"),
            ("vpd", "vpd_trend"),
        ]:
            trend_sensor_id = self.env_config.get(f"{sensor_key}_trend_sensor")
            stats_sensor_id = self.env_config.get(f"{sensor_key}_stats_sensor")

            # --- External Trend Sensor Logic (If/Elif/Else Chain for Source) ---
            if trend_sensor_id:
                trend_state = self.hass.states.get(trend_sensor_id)
                if trend_state and trend_state.state == "on":  # Rising trend
                    self._sensor_states[trend_key] = "rising"
                    gradient = trend_state.attributes.get("gradient", 0)
                    prob = (
                        self.env_config.get("prob_trend_fast_rise", (0.95, 0.15))
                        if gradient > 0.1
                        else self.env_config.get("prob_trend_slow_rise", (0.75, 0.30))
                    )
                    observations.append(prob)
                    reason_suffix = " fast" if gradient > 0.1 else ""
                    reasons.append(
                        (prob[0], f"{sensor_key.capitalize()} rising{reason_suffix}")
                    )

            elif stats_sensor_id:
                stats_state = self.hass.states.get(stats_sensor_id)
                if (
                    stats_state
                    and (change := stats_state.attributes.get("change")) is not None
                ):
                    threshold = 0.2 if sensor_key == "vpd" else 1.0
                    if change > threshold:
                        self._sensor_states[trend_key] = "rising"
                        prob = (0.85, 0.25)
                        observations.append(prob)
                        reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

            else:  # Fallback to manual analysis (Requires await)
                duration = self.env_config.get(f"{sensor_key}_trend_duration", 30)
                threshold = self.env_config.get(f"{sensor_key}_trend_threshold", 26.0)
                sensitivity = self.env_config.get(
                    f"{sensor_key}_trend_sensitivity", 0.5
                )
                if self.env_config.get(f"{sensor_key}_sensor"):
                    analysis = await self._async_analyze_sensor_trend(
                        self.env_config[f"{sensor_key}_sensor"], duration, threshold
                    )
                    self._sensor_states[trend_key] = analysis["trend"]
                    if analysis["trend"] == "rising" and analysis["crossed_threshold"]:
                        p_true = 0.5 + (sensitivity * 0.45)
                        p_false = 0.5 - (sensitivity * 0.4)
                        prob = (p_true, p_false)
                        observations.append(prob)
                        reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

        return observations, reasons

    def _evaluate_direct_temp_stress(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate temperature against extreme/out-of-range stress thresholds."""
        observations = []
        reasons = []

        if state.temp is None:
            return observations, reasons

        temp = state.temp

        # 1: Night High Temp Check ---
        # This check is independent of the main stress cascade and was previously a separate 'if'.
        if not state.is_lights_on and temp > 24:
            prob = self.env_config.get("prob_night_temp_high", (0.80, 0.20))
            observations.append(prob)
            reasons.append((prob[0], f"Night Temp High ({temp})"))

        # 2: General Stress/Warm/Cold Checks ---
        # These checks cascade for priority, but are independent of the night check above.
        if temp > 32:
            prob = self.env_config.get("prob_temp_extreme_heat", (0.98, 0.05))
            observations.append(prob)
            reasons.append((prob[0], f"Extreme Heat ({temp})"))
        elif temp > 30:
            prob = self.env_config.get("prob_temp_high_heat", (0.85, 0.15))
            observations.append(prob)
            reasons.append((prob[0], f"High Heat ({temp})"))
        elif state.flower_days >= 42 and temp > 24:
            prob = (0.70, 0.30)
            observations.append(prob)
            reasons.append((prob[0], f"Temp Warm ({temp})"))
        elif temp > 28:
            prob = self.env_config.get("prob_temp_warm", (0.65, 0.30))
            observations.append(prob)
            reasons.append((prob[0], f"Temp Warm ({temp})"))
        elif temp < 15:
            prob = self.env_config.get("prob_temp_extreme_cold", (0.95, 0.08))
            observations.append(prob)
            reasons.append((prob[0], f"Extreme Cold ({temp})"))
        elif temp < 18:
            prob = self.env_config.get("prob_temp_cold", (0.80, 0.20))
            observations.append(prob)
            reasons.append((prob[0], f"Temp Cold ({temp})"))

        return observations, reasons

    def _evaluate_direct_humidity_stress(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate humidity against stage-dependent stress thresholds."""
        observations = []
        reasons = []

        if state.humidity is None:
            return observations, reasons

        hum = state.humidity

        # Universal low humidity check
        if hum < 35:
            prob = self.env_config.get("prob_humidity_too_dry", (0.85, 0.20))
            observations.append(prob)
            reasons.append((prob[0], f"Humidity Dry ({hum})"))

        # Stage-specific high humidity/out-of-range checks
        veg_early = state.flower_days == 0 and state.veg_days < 14
        veg_late = state.flower_days == 0 and state.veg_days >= 14
        flower_early = 0 < state.flower_days < 42
        flower_late = state.flower_days >= 42

        # Use elif for mutually exclusive stage checks
        if veg_early and hum > 80:
            prob = self.env_config.get("prob_humidity_high_veg_early", (0.80, 0.20))
            observations.append(prob)
            reasons.append((prob[0], f"Humidity High ({hum})"))
        elif veg_late and hum > 70:
            prob = self.env_config.get("prob_humidity_high_veg_late", (0.85, 0.15))
            observations.append(prob)
            reasons.append((prob[0], f"Humidity High ({hum})"))
        elif flower_early and (hum > 55 or hum < 45):
            prob = (0.75, 0.25)
            observations.append(prob)
            reasons.append((prob[0], f"Humidity out of range (45-55) ({hum})"))
        elif flower_late and (hum > 50 or hum < 40):
            prob = (0.85, 0.15)
            observations.append(prob)
            reasons.append((prob[0], f"Humidity out of range (40-50) ({hum})"))

        return observations, reasons

    def _determine_vpd_stage_thresholds(self, state: EnvironmentState) -> dict | None:
        """Determine the current stage and return the necessary thresholds."""
        vpd_thresholds = {
            "veg_early": {  # flower_days == 0 and veg_days < 14
                "day": {
                    "stress": (0.3, 1.0),
                    "mild": (0.4, 0.8),
                    "prob_keys": (
                        "prob_vpd_stress_veg_early",
                        "prob_vpd_mild_stress_veg_early",
                    ),
                    "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
                },
                "night": {
                    "stress": (0.3, 1.0),
                    "mild": (0.4, 0.8),
                    "prob_keys": (
                        "prob_vpd_stress_veg_early",
                        "prob_vpd_mild_stress_veg_early",
                    ),
                    "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
                },
            },
            "veg_late": {  # flower_days == 0 and veg_days >= 14
                "day": {
                    "stress": (0.6, 1.4),
                    "mild": (0.8, 1.2),
                    "prob_keys": (
                        "prob_vpd_stress_veg_late",
                        "prob_vpd_mild_stress_veg_late",
                    ),
                    "prob_defaults": ((0.80, 0.18), (0.55, 0.35)),
                },
                "night": {
                    "stress": (0.3, 1.0),
                    "mild": (0.5, 0.8),
                    "prob_keys": (
                        "prob_vpd_stress_veg_late",
                        "prob_vpd_mild_stress_veg_late",
                    ),
                    "prob_defaults": ((0.80, 0.18), (0.55, 0.35)),
                },
            },
            "flower_early": {  # 0 < flower_days < 42
                "day": {
                    "stress": (0.8, 1.6),
                    "mild": (1.0, 1.5),
                    "prob_keys": (
                        "prob_vpd_stress_flower_early",
                        "prob_vpd_mild_stress_flower_early",
                    ),
                    "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
                },
                "night": {
                    "stress": (0.5, 1.1),
                    "mild": (0.7, 1.0),
                    "prob_keys": (
                        "prob_vpd_stress_flower_early",
                        "prob_vpd_mild_stress_flower_early",
                    ),
                    "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
                },
            },
            "flower_late": {  # flower_days >= 42
                "day": {
                    "stress": (1.0, 1.6),
                    "mild": (1.2, 1.5),
                    "prob_keys": (
                        "prob_vpd_stress_flower_late",
                        "prob_vpd_mild_stress_flower_late",
                    ),
                    "prob_defaults": ((0.90, 0.12), (0.65, 0.28)),
                },
                "night": {
                    "stress": (0.6, 1.2),
                    "mild": (0.8, 1.1),
                    "prob_keys": (
                        "prob_vpd_stress_flower_late",
                        "prob_vpd_mild_stress_flower_late",
                    ),
                    "prob_defaults": ((0.90, 0.12), (0.65, 0.28)),
                },
            },
        }

        # Determine current growth stage
        stage_key = None
        if state.flower_days == 0 and state.veg_days < 14:
            stage_key = "veg_early"
        elif state.flower_days == 0 and state.veg_days >= 14:
            stage_key = "veg_late"
        elif 0 < state.flower_days < 42:
            stage_key = "flower_early"
        elif state.flower_days >= 42:
            stage_key = "flower_late"

        if stage_key:
            time_of_day = "day" if state.is_lights_on else "night"
            return vpd_thresholds[stage_key][time_of_day]

        return None

    def _evaluate_direct_vpd_stress(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate VPD against stage-dependent stress thresholds."""
        observations = []
        reasons = []

        if state.vpd is None:
            return observations, reasons

        thresholds = self._determine_vpd_stage_thresholds(state)

        if thresholds:
            stress_low, stress_high = thresholds["stress"]
            mild_low, mild_high = thresholds["mild"]
            prob_stress_key, prob_mild_key = thresholds["prob_keys"]
            prob_stress_default, prob_mild_default = thresholds["prob_defaults"]

            if state.vpd < stress_low or state.vpd > stress_high:
                prob = self.env_config.get(prob_stress_key, prob_stress_default)
                observations.append(prob)
                reasons.append((prob[0], f"VPD out of range ({state.vpd})"))
            elif state.vpd < mild_low or state.vpd > mild_high:
                prob = self.env_config.get(prob_mild_key, prob_mild_default)
                observations.append(prob)
                reasons.append((prob[0], f"VPD out of range ({state.vpd})"))

        return observations, reasons

    def _evaluate_direct_co2_stress(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate CO2 against low/high stress thresholds."""
        observations = []
        reasons = []

        if state.co2 is None:
            return observations, reasons

        co2 = state.co2

        # Universal CO2 stress checks (not stage-dependent in this sensor's logic)
        if co2 < 400:
            prob = (0.80, 0.25)
            observations.append(prob)
            reasons.append((prob[0], f"CO2 Low ({co2})"))
        elif co2 > 1600:
            prob = (0.95, 0.10)
            observations.append(prob)
            reasons.append((prob[0], f"CO2 High ({co2})"))

        return observations, reasons


class LightCycleVerificationSensor(BinarySensorEntity):
    """A binary sensor to verify if the light cycle matches the growspace stage.

    This sensor monitors the on/off duration of a light entity and compares it
    to the expected schedule (e.g., 18/6 for veg, 12/12 for flower). It will turn
    off if the light has been on or off for too long, indicating a potential
    timer malfunction.
    """

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: dict,
    ) -> None:
        """Initialize the light cycle verification sensor."""
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.env_config = env_config
        self._attr_should_poll = False

        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} Light Schedule Correct"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_light_schedule"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

        self.light_entity_id = self.env_config.get("light_sensor")
        self._is_correct = False
        self._last_checked: datetime | None = None
        self._time_in_current_state: timedelta = timedelta(0)

    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        self.coordinator.async_add_listener(self._handle_coordinator_update)
        if self.light_entity_id:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self.light_entity_id],
                    self._async_light_sensor_changed,
                )
            )
        await self.async_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updates from the data coordinator."""
        self.hass.async_create_task(self.async_update())

    @callback
    def _async_light_sensor_changed(self, event) -> None:
        """Handle state changes of the monitored light sensor.

        Args:
            event: The state change event.
        """
        self.hass.async_create_task(self.async_update())

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get the current growth stage duration for the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        if not plants:
            return {"veg_days": 0, "flower_days": 0}

        max_veg = max(
            (
                self.coordinator._calculate_days(p.veg_start)
                for p in plants
                if p.veg_start
            ),
            default=0,
        )
        max_flower = max(
            (
                self.coordinator._calculate_days(p.flower_start)
                for p in plants
                if p.flower_start
            ),
            default=0,
        )
        return {"veg_days": max_veg, "flower_days": max_flower}

    async def async_update(self) -> None:
        """Update the sensor's state based on the light's on/off duration."""
        if not self.light_entity_id:
            self._is_correct = False
            self.async_write_ha_state()
            return

        light_state = self.hass.states.get(self.light_entity_id)
        if not light_state or light_state.state in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
            self._is_correct = False
            self.async_write_ha_state()
            return

        is_light_on = light_state.state == "on"
        now = utcnow()
        time_since_last_changed = now - light_state.last_changed

        stage_info = self._get_growth_stage_info()
        is_flower_stage = stage_info["flower_days"] > 0

        # Determine the schedule duration based on the stage:
        #    Flower (12/12) is max 12h ON, 12h OFF.
        #    Veg (18/6) is max 18h ON, 6h OFF.
        max_on_duration_hours = 12 if is_flower_stage else 18
        max_off_duration_hours = 12 if is_flower_stage else 6

        # Select the correct time limit (ON or OFF duration)
        limit_hours = max_on_duration_hours if is_light_on else max_off_duration_hours

        # Apply the single check
        self._is_correct = time_since_last_changed <= timedelta(hours=limit_hours)

        self._time_in_current_state = time_since_last_changed
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return true if the light schedule appears to be correct."""
        return self._is_correct

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes for the entity."""
        stage_info = self._get_growth_stage_info()
        is_flower_stage = stage_info["flower_days"] > 0
        expected_schedule = "12/12" if is_flower_stage else "18/6"

        return {
            "expected_schedule": expected_schedule,
            "light_entity_id": self.light_entity_id,
            "time_in_current_state": str(self._time_in_current_state),
        }


class BayesianDryingSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting optimal drying conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        """Initialize the optimal drying sensor."""
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="drying",
            name_suffix="Optimal Drying",
            prior_key="prior_drying",
            threshold_key="drying_threshold",
        )

    async def _async_update_probability(self) -> None:
        """Calculate the probability of optimal drying conditions."""
        if self.growspace_id != "dry":
            self._probability = 0
            self.async_write_ha_state()
            return

        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        if state.temp is not None:
            if 15 <= state.temp <= 21:
                observations.append((0.95, 0.10))
            else:
                observations.append((0.10, 0.90))
                self._reasons.append((0.90, f"Temp out of range ({state.temp})"))

        if state.humidity is not None:
            if 45 <= state.humidity <= 55:
                observations.append((0.95, 0.10))
            else:
                observations.append((0.10, 0.90))
                self._reasons.append(
                    (0.90, f"Humidity out of range ({state.humidity})")
                )

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianCuringSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting optimal curing conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        """Initialize the optimal curing sensor."""
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="curing",
            name_suffix="Optimal Curing",
            prior_key="prior_curing",
            threshold_key="curing_threshold",
        )

    async def _async_update_probability(self) -> None:
        """Calculate the probability of optimal curing conditions."""
        if self.growspace_id != "cure":
            self._probability = 0
            self.async_write_ha_state()
            return

        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        if state.temp is not None:
            if 18 <= state.temp <= 21:
                observations.append((0.95, 0.10))
            else:
                observations.append((0.10, 0.90))
                self._reasons.append((0.90, f"Temp out of range ({state.temp})"))

        if state.humidity is not None:
            if 55 <= state.humidity <= 60:
                observations.append((0.95, 0.10))
            else:
                observations.append((0.10, 0.90))
                self._reasons.append(
                    (0.90, f"Humidity out of range ({state.humidity})")
                )

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianMoldRiskSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting high mold risk conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        """Initialize the mold risk sensor."""
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="mold_risk",
            name_suffix="High Mold Risk",
            prior_key="prior_mold_risk",
            threshold_key="mold_threshold",
        )

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Generate a notification when the sensor turns on.

        Args:
            new_state_on: True if the sensor just turned on.

        Returns:
            A tuple of (title, message) if a notification should be sent.
        """
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"High Mold Risk in {growspace.name}"
                message = self._generate_notification_message("High mold risk detected")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate the probability of mold risk, focusing on late flower conditions.

        This method gathers evidence from humidity, VPD, temperature, and fan
        status, particularly during the lights-off period in late flower, to
        assess the risk of mold or bud rot.
        """
        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        self._sensor_states["humidity_trend"] = "stable"
        self._sensor_states["vpd_trend"] = "stable"

        # --- Trend Analysis for Mold Risk ---
        # Rising humidity trend is a risk
        trend_sensor_id = self.env_config.get("humidity_trend_sensor")
        stats_sensor_id = self.env_config.get("humidity_stats_sensor")
        if trend_sensor_id:
            if (
                trend_state := self.hass.states.get(trend_sensor_id)
            ) and trend_state.state == "on":
                self._sensor_states["humidity_trend"] = "rising"
                prob = (0.90, 0.20)
                observations.append(prob)
                self._reasons.append((prob[0], "Humidity rising"))
        elif stats_sensor_id:
            if (
                (stats_state := self.hass.states.get(stats_sensor_id))
                and (change := stats_state.attributes.get("change")) is not None
                and change > 1.0
            ):
                self._sensor_states["humidity_trend"] = "rising"
                prob = (0.85, 0.25)
                observations.append(prob)
                self._reasons.append((prob[0], "Humidity rising"))

        # Falling VPD trend is a risk
        trend_sensor_id = self.env_config.get("vpd_trend_sensor")
        stats_sensor_id = self.env_config.get("vpd_stats_sensor")
        if trend_sensor_id:
            if (
                trend_state := self.hass.states.get(trend_sensor_id)
            ) and trend_state.state == "off":
                self._sensor_states["vpd_trend"] = "falling"
                prob = (0.90, 0.20)
                observations.append(prob)
                self._reasons.append((prob[0], "VPD falling"))
        elif stats_sensor_id:
            if (
                (stats_state := self.hass.states.get(stats_sensor_id))
                and (change := stats_state.attributes.get("change")) is not None
                and change < -0.1
            ):
                self._sensor_states["vpd_trend"] = "falling"
                prob = (0.85, 0.25)
                observations.append(prob)
                self._reasons.append((prob[0], "VPD falling"))

        # --- Direct Observations ---
        # Fallback manual trend analysis for mold risk
        for sensor_key in ["humidity", "vpd"]:
            if not self.env_config.get(
                f"{sensor_key}_trend_sensor"
            ) and not self.env_config.get(f"{sensor_key}_stats_sensor"):
                duration = self.env_config.get(f"{sensor_key}_trend_duration", 30)
                # For mold, a simple threshold isn't as useful as just detecting the trend direction
                # We pass a high threshold for humidity (rising) and low for VPD (falling)
                # to effectively just check direction
                threshold = 101 if sensor_key == "humidity" else -1
                sensitivity = self.env_config.get(
                    f"{sensor_key}_trend_sensitivity", 0.5
                )
                if self.env_config.get(f"{sensor_key}_sensor"):
                    analysis = await self._async_analyze_sensor_trend(
                        self.env_config[f"{sensor_key}_sensor"], duration, threshold
                    )
                    self._sensor_states[f"{sensor_key}_trend"] = analysis["trend"]
                    # Add observation if humidity is rising OR vpd is falling
                    if (sensor_key == "humidity" and analysis["trend"] == "rising") or (
                        sensor_key == "vpd" and analysis["trend"] == "falling"
                    ):
                        p_true = 0.5 + (sensitivity * 0.45)
                        p_false = 0.5 - (sensitivity * 0.4)
                        prob = (p_true, p_false)
                        observations.append(prob)
                        self._reasons.append(
                            (prob[0], f"{sensor_key.capitalize()} trend")
                        )

        if state.flower_days >= 35:
            prob = (0.99, 0.01)
            observations.append(prob)
            self._reasons.append((prob[0], "Late Flower"))

            if state.temp is not None and 16 < state.temp < 23:
                prob = self.env_config.get("prob_mold_temp_danger_zone", (0.85, 0.30))
                observations.append(prob)
                self._reasons.append((prob[0], f"Temp in danger zone ({state.temp})"))

            if not state.is_lights_on:
                prob = self.env_config.get("prob_mold_lights_off", (0.75, 0.30))
                observations.append(prob)
                self._reasons.append((prob[0], "Lights Off"))
                if state.humidity is not None and state.humidity > 50:
                    prob = self.env_config.get(
                        "prob_mold_humidity_high_night", (0.99, 0.10)
                    )
                    observations.append(prob)
                    self._reasons.append(
                        (prob[0], f"Night Humidity High ({state.humidity})")
                    )
                if state.vpd is not None and state.vpd < 1.3:
                    prob = self.env_config.get("prob_mold_vpd_low_night", (0.95, 0.20))
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Night VPD Low ({state.vpd})"))
            else:  # Daytime checks
                if state.humidity is not None and state.humidity > 55:
                    prob = self.env_config.get(
                        "prob_mold_humidity_high_day", (0.95, 0.20)
                    )
                    observations.append(prob)
                    self._reasons.append(
                        (prob[0], f"Day Humidity High ({state.humidity})")
                    )
                if state.vpd is not None and state.vpd < 1.2:
                    prob = self.env_config.get("prob_mold_vpd_low_day", (0.90, 0.25))
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Day VPD Low ({state.vpd})"))
            if state.fan_off:
                prob = self.env_config.get("prob_mold_fan_off", (0.80, 0.15))
                observations.append(prob)
                self._reasons.append((prob[0], "Circulation Fan Off"))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianOptimalConditionsSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting optimal growing conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        """Initialize the optimal conditions sensor."""
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="optimal",
            name_suffix="Optimal Conditions",
            prior_key="prior_optimal",
            threshold_key="optimal_threshold",
        )

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Generate a notification when the sensor turns off.

        Args:
            new_state_on: False if the sensor just turned off.

        Returns:
            A tuple of (title, message) if a notification should be sent.
        """
        if not new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"Optimal Conditions Lost in {growspace.name}"
                message = self._generate_notification_message("Optimal conditions lost")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate the probability that the environment is in an optimal state.

        This method checks if temperature, humidity, VPD, and CO2 are all within
        their ideal ranges for the current growth stage and time of day (lights on/off).
        """
        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        # 1. OPTIMAL TEMPERATURE
        temp_obs, temp_reasons = self._evaluate_optimal_temperature(state)
        observations.extend(temp_obs)
        self._reasons.extend(temp_reasons)

        # 2. OPTIMAL VPD
        vpd_obs, vpd_reasons = self._evaluate_optimal_vpd(state)
        observations.extend(vpd_obs)
        self._reasons.extend(vpd_reasons)

        # 3. OPTIMAL CO2 LEVELS
        co2_obs, co2_reasons = self._evaluate_optimal_co2(state)
        observations.extend(co2_obs)
        self._reasons.extend(co2_reasons)

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()

    # =========================================================================
    # HELPER EVALUATION METHODS
    # =========================================================================

    def _evaluate_optimal_temperature(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate temperature against optimal ranges for the current stage/light cycle."""
        observations = []
        reasons = []

        if state.temp is None:
            return observations, reasons

        # Constants (using snake_case per Pylint suggestion for local variables)
        prob_perfect = (0.95, 0.20)
        prob_good = (0.85, 0.30)
        prob_acceptable = (0.65, 0.45)
        prob_out_of_range = (0.20, 0.75)

        # Match against (is_lights_on, flower_days) for branching logic
        match (state.is_lights_on, state.flower_days):
            # Case A: Lights ON & Late Flower (Days >= 42)
            case True, days if days >= 42:
                if 18 <= state.temp <= 24:  # Perfect range for late flower
                    observations.append(prob_perfect)
                else:
                    observations.append(prob_out_of_range)
                    reasons.append(
                        (
                            prob_out_of_range[1],
                            f"Temp out of range Late Flower ({state.temp})",
                        )
                    )

            # Case B: Lights ON & Normal (Days < 42 or Veg)
            case True, _:
                if 24 <= state.temp <= 26:
                    observations.append(prob_perfect)
                elif 22 <= state.temp <= 28:
                    observations.append(prob_good)
                elif 20 <= state.temp <= 29:
                    observations.append(prob_acceptable)
                else:
                    observations.append(prob_out_of_range)
                    reasons.append(
                        (prob_out_of_range[1], f"Temp out of range ({state.temp})")
                    )

            # Case C: Lights OFF (Nighttime)
            case False, _:
                if 20 <= state.temp <= 23:
                    observations.append(prob_perfect)
                else:
                    observations.append(prob_out_of_range)
                    reasons.append(
                        (
                            prob_out_of_range[1],
                            f"Night temp out of range ({state.temp})",
                        )
                    )
        return observations, reasons

    def _evaluate_optimal_vpd(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate VPD against optimal ranges for the current stage/light cycle."""
        observations = []
        reasons = []

        if state.vpd is None:
            return observations, reasons

        vpd_optimal = False
        prob_vpd_out_of_range = (0.25, 0.70)

        # Define VPD stages: (veg_min, veg_max, flower_min, flower_max),
        # (P_low, P_high), (G_low, G_high), P_perf, P_good
        vpd_stages = {
            "DAY": [
                ((0, 14, 0, 0), (0.5, 0.7), (0.4, 0.8), (0.95, 0.18), (0.80, 0.28)),
                (
                    (14, float("inf"), 0, 0),
                    (0.9, 1.1),
                    (0.8, 1.2),
                    (0.95, 0.18),
                    (0.85, 0.25),
                ),
                (
                    (0, float("inf"), 1, 42),
                    (1.1, 1.4),
                    (1.0, 1.5),
                    (0.95, 0.18),
                    (0.85, 0.25),
                ),
                (
                    (0, float("inf"), 42, float("inf")),
                    (1.3, 1.5),
                    (1.2, 1.6),
                    (0.95, 0.15),
                    (0.85, 0.22),
                ),
            ],
            "NIGHT": [
                ((0, 14, 0, 0), (0.4, 0.8), (0.4, 0.8), (0.90, 0.20), (0.90, 0.20)),
                (
                    (14, float("inf"), 0, 0),
                    (0.6, 1.1),
                    (0.6, 1.1),
                    (0.90, 0.20),
                    (0.90, 0.20),
                ),
                (
                    (0, float("inf"), 1, 42),
                    (0.8, 1.2),
                    (0.8, 1.2),
                    (0.90, 0.20),
                    (0.90, 0.20),
                ),
                (
                    (0, float("inf"), 42, float("inf")),
                    (0.9, 1.2),
                    (0.9, 1.2),
                    (0.90, 0.20),
                    (0.90, 0.20),
                ),
            ],
        }

        stage_list = vpd_stages["DAY"] if state.is_lights_on else vpd_stages["NIGHT"]

        for (v_min, v_max, f_min, f_max), (p_low, p_high), (
            g_low,
            g_high,
        ), prob_perf, prob_good in stage_list:
            is_veg = state.flower_days == 0 and v_min <= state.veg_days < v_max
            is_flower = state.flower_days > 0 and f_min <= state.flower_days < f_max

            if is_veg or is_flower:
                # Check performance within the stage
                if p_low <= state.vpd <= p_high:  # Perfect Range
                    vpd_optimal = True
                    observations.append(prob_perf)
                elif g_low <= state.vpd <= g_high:  # Good/Acceptable Range
                    observations.append(prob_good)

                break  # Matched a stage, stop checking

        # If not optimal, reduce probability
        if not vpd_optimal:
            observations.append(prob_vpd_out_of_range)
            reasons.append(
                (prob_vpd_out_of_range[1], f"VPD out of range ({state.vpd})")
            )

        return observations, reasons

    def _evaluate_optimal_co2(
        self, state: EnvironmentState
    ) -> tuple[list[tuple[float, float]], list[tuple[float, str]]]:
        """Evaluate CO2 levels against optimal ranges for the current stage."""
        observations = []
        reasons = []

        if state.co2 is None:
            return observations, reasons

        # Constants (retrieved from surrounding context)
        prob_perfect = (0.95, 0.20)
        prob_good = (0.85, 0.30)
        prob_acceptable = (0.60, 0.45)
        prob_out_of_range = (0.20, 0.75)
        co2 = state.co2

        # Use match/case on the result of the stage check (True or False)
        match state.flower_days >= 42:
            case True:  # Late Flower Logic
                # Late flower prefers lower CO2
                if 400 <= co2 <= 800:
                    observations.append((0.90, 0.25))
                elif 800 < co2 <= 1200:
                    observations.append((0.4, 0.6))

            case False:  # Normal/Veg/Early Flower logic
                if 1000 <= co2 <= 1400:
                    observations.append(prob_perfect)
                elif 800 <= co2 <= 1500:
                    observations.append(prob_good)
                elif 400 <= co2 <= 600:
                    observations.append(prob_acceptable)
                else:
                    observations.append(prob_out_of_range)
                    reason_detail = "CO2 Low" if co2 < 400 else "CO2 High"
                    reasons.append((prob_out_of_range[1], f"{reason_detail} ({co2})"))
        return observations, reasons
