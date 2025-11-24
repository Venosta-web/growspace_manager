"""Bayesian binary sensors for environmental monitoring in Growspace Manager.

This file defines a set of binary sensors that use Bayesian inference to assess
various environmental conditions within a growspace, such as plant stress, mold
risk, and optimal conditions. It also includes a sensor to verify the light
cycle schedule.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components import conversation
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.components.recorder import history
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.recorder import get_instance as get_recorder_instance
from homeassistant.util.dt import utcnow

from .bayesian_data import CURING_THRESHOLDS, DRYING_THRESHOLDS
from .bayesian_evaluator import (
    ReasonList,
    async_evaluate_mold_risk_trend,
    async_evaluate_stress_trend,
    evaluate_direct_co2_stress,
    evaluate_direct_humidity_stress,
    evaluate_direct_temp_stress,
    evaluate_direct_vpd_stress,
    evaluate_optimal_co2,
    evaluate_optimal_temperature,
    evaluate_optimal_vpd,
)
from .const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    CONF_NOTIFICATION_PERSONALITY,
    DEFAULT_BAYESIAN_PRIORS,
    DEFAULT_BAYESIAN_THRESHOLDS,
    DOMAIN,
)
from .coordinator import GrowspaceCoordinator
from .models import EnvironmentState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager Bayesian binary sensors from a config entry."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    # Create Bayesian sensors for each growspace that has environment config
    for growspace_id, growspace in coordinator.growspaces.items():
        env_config = getattr(growspace, "environment_config", None)

        if env_config and _validate_env_config(env_config):
            # --- MODIFIED LOGIC START ---

            if growspace_id == "dry":
                # For 'dry', only add Drying and Mold Risk sensors
                entities.extend(
                    [
                        BayesianDryingSensor(coordinator, growspace_id, env_config),
                        BayesianMoldRiskSensor(coordinator, growspace_id, env_config),
                    ]
                )
                _LOGGER.info(
                    "Created specific Drying and Mold sensors for growspace: %s",
                    growspace.name,
                )

            elif growspace_id == "cure":
                # For 'cure', only add Curing and Mold Risk sensors
                entities.extend(
                    [
                        BayesianCuringSensor(coordinator, growspace_id, env_config),
                        BayesianMoldRiskSensor(coordinator, growspace_id, env_config),
                    ]
                )
                _LOGGER.info(
                    "Created specific Curing and Mold sensors for growspace: %s",
                    growspace.name,
                )

            else:
                # For all other growspaces, add the standard set
                entities.extend(
                    [
                        BayesianStressSensor(coordinator, growspace_id, env_config),
                        BayesianMoldRiskSensor(coordinator, growspace_id, env_config),
                        BayesianOptimalConditionsSensor(
                            coordinator, growspace_id, env_config
                        ),
                    ]
                )
                _LOGGER.info(
                    "Created standard Bayesian environment sensors for growspace: %s",
                    growspace.name,
                )

            # This sensor applies to any growspace with a light sensor, regardless of type
            if env_config.get("light_sensor"):
                entities.append(
                    LightCycleVerificationSensor(coordinator, growspace_id, env_config)
                )

    if entities:
        async_add_entities(entities)


def _validate_env_config(config: dict) -> bool:
    """Validate that the required environment sensor entities are configured."""
    required = ["temperature_sensor", "humidity_sensor", "vpd_sensor"]
    return all(config.get(key) for key in required)


class BayesianEnvironmentSensor(BinarySensorEntity):
    """Base class for Bayesian environment monitoring binary sensors."""

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
        """Initialize the Bayesian environment sensor."""
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

        self._sensor_states = {}
        self._reasons: ReasonList = []
        self._probability = 0.0
        self._last_notification_sent: datetime | None = None
        self._notification_cooldown = timedelta(minutes=5)

    def _get_base_environment_state(self) -> EnvironmentState:
        """Fetch sensor values and return a structured EnvironmentState object."""
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
        self.coordinator.async_add_listener(self._handle_coordinator_update)

        sensors = [
            self.env_config.get("temperature_sensor"),
            self.env_config.get("humidity_sensor"),
            self.env_config.get("vpd_sensor"),
            self.env_config.get("co2_sensor"),
            self.env_config.get("circulation_fan"),
        ]

        sensors = [s for s in sensors if s]

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                sensors,
                self._async_sensor_changed,
            )
        )

        await self.async_update_and_notify()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updates from the data coordinator."""
        self.hass.async_create_task(self.async_update_and_notify())

    @callback
    def _async_sensor_changed(self, event) -> None:
        """Handle state changes of the monitored environment sensors."""
        self.hass.async_create_task(self.async_update_and_notify())

    def _get_sensor_value(self, sensor_id: str | None) -> float | None:
        """Safely get the numeric value from a sensor's state."""
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
        """Calculate the number of days since a given date string."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (AttributeError, TypeError, ValueError):
            return 0
        return (date.today() - dt).days

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get the current growth stage duration (veg and flower days) for the growspace."""
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
        """Analyze the trend of a sensor's history to detect rising or falling patterns."""
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
                if isinstance(s, State)
                and s.state not in [STATE_UNKNOWN, STATE_UNAVAILABLE]
                and s.state is not None
            ]

            if len(numeric_states) < 2:
                return {"trend": "stable", "crossed_threshold": False}

            # Trend calculation (simplified: change between first and last value)
            start_value = numeric_states[0][1]
            end_value = numeric_states[-1][1]
            change = end_value - start_value

            trend = "stable"
            if change > 0.01:
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
        """Construct a detailed notification message from the list of reasons."""
        sorted_reasons = sorted(self._reasons, reverse=True)
        message = base_message

        for _, reason in sorted_reasons:
            if len(message) + len(reason) + 2 < 65:
                message += f", {reason}"
            else:
                break
        return message

    async def _send_notification(self, title: str, message: str) -> None:
        """Send a notification to the configured target for the growspace."""
        now = utcnow()
        if (
            self._last_notification_sent
            and (now - self._last_notification_sent) < self._notification_cooldown
        ):
            _LOGGER.debug(
                "Notification cooldown active for %s, skipping notification",
                self.growspace_id,
            )
            return

        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if not growspace or not growspace.notification_target:
            _LOGGER.debug(
                "No notification target configured for %s, skipping notification",
                self.growspace_id,
            )
            return

        # Check if notifications are enabled in coordinator
        if not self.coordinator.is_notifications_enabled(self.growspace_id):
            _LOGGER.debug(
                "Notifications disabled in coordinator for %s", self.growspace_id
            )
            return

        self._last_notification_sent = now

        # AI Personality Injection
        final_message = message
        ai_settings = self.coordinator.options.get("ai_settings", {})

        if (
            ai_settings.get(CONF_AI_ENABLED)
            and ai_settings.get(CONF_ASSISTANT_ID)
        ):
            try:
                personality = ai_settings.get(CONF_NOTIFICATION_PERSONALITY, "Standard")
                agent_id = ai_settings.get(CONF_ASSISTANT_ID)

                # Format sensor readings for context
                readings = []
                for k, v in self._sensor_states.items():
                    if v is not None and not isinstance(v, bool):
                         readings.append(f"{k}: {v}")
                readings_str = ", ".join(readings)

                prompt = (
                    f"Rewrite this alert as a {personality}. Keep it under 1 sentence. "
                    f"Include specific sensor data if relevant. "
                    f"Original Alert: '{message}'. "
                    f"Current Readings: {readings_str}"
                )

                _LOGGER.debug("Sending prompt to LLM: %s", prompt)

                result = await conversation.async_process(
                    self.hass,
                    text=prompt,
                    conversation_id=None,
                    agent_id=agent_id
                )

                if (
                    result
                    and result.response
                    and result.response.speech
                    and result.response.speech.get("plain")
                ):
                    final_message = result.response.speech["plain"]["speech"]
                    _LOGGER.info("AI rewrote notification: %s", final_message)
                else:
                    _LOGGER.warning("LLM returned empty response, using default message.")

            except Exception as err:
                _LOGGER.error("Failed to process AI notification: %s", err)
                # Fallback to original message is automatic since final_message starts as message

        # Get the service name (e.g., "mobile_app_my_phone")
        notification_service = growspace.notification_target.replace("notify.", "")

        try:
            await self.hass.services.async_call(
                "notify",
                notification_service,
                {
                    "message": final_message,
                    "title": title,
                },
                blocking=False,
            )
            _LOGGER.info(
                "Notification sent to %s: %s - %s", notification_service, title, final_message
            )
        except (AttributeError, TypeError, ValueError) as e:
            _LOGGER.error(
                "Failed to send notification to %s: %s", notification_service, e
            )

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Return the title and message for a notification based on state change."""
        return None

    async def async_update_and_notify(self) -> None:
        """Update the sensor's probability and send a notification if the state changes."""
        old_state_on = self.is_on
        await self._async_update_probability()
        new_state_on = self.is_on

        if new_state_on != old_state_on:
            if notification := self.get_notification_title_message(new_state_on):
                title, message = notification
                await self._send_notification(title, message)

    async def _async_update_probability(self) -> None:
        """Calculate the Bayesian probability based on environmental observations."""
        raise NotImplementedError

    @staticmethod
    def _calculate_bayesian_probability(
        prior: float, observations: list[tuple[float, float]]
    ) -> float:
        """Perform the Bayesian calculation."""
        if not observations:
            return prior

        prob_true = prior
        prob_false = 1 - prior

        for p_obs_given_true, p_obs_given_false in observations:
            prob_true *= p_obs_given_true
            prob_false *= p_obs_given_false

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
        """Return the state attributes for the entity."""
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
        """Generate a notification when the sensor turns on."""
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

        # 1. ASYNCHRONOUS TREND ANALYSIS (Logic moved to bayesian_evaluator.py)
        trend_obs, trend_reasons, trend_states = await async_evaluate_stress_trend(
            self, state
        )
        observations.extend(trend_obs)
        self._reasons.extend(trend_reasons)
        self._sensor_states.update(trend_states)

        # 2. DIRECT OBSERVATIONS (Logic moved to bayesian_evaluator.py)

        temp_obs, temp_reasons = evaluate_direct_temp_stress(state, self.env_config)
        observations.extend(temp_obs)
        self._reasons.extend(temp_reasons)

        hum_obs, hum_reasons = evaluate_direct_humidity_stress(state, self.env_config)
        observations.extend(hum_obs)
        self._reasons.extend(hum_reasons)

        vpd_obs, vpd_reasons = evaluate_direct_vpd_stress(state, self.env_config)
        observations.extend(vpd_obs)
        self._reasons.extend(vpd_reasons)

        co2_obs, co2_reasons = evaluate_direct_co2_stress(state, self.env_config)
        observations.extend(co2_obs)
        self._reasons.extend(co2_reasons)

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class LightCycleVerificationSensor(BinarySensorEntity):
    """A binary sensor to verify if the light cycle matches the growspace stage."""

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
        """Handle state changes of the monitored light sensor."""
        self.hass.async_create_task(self.async_update())

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get the current growth stage duration for the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        if not plants:
            return {"veg_days": 0, "flower_days": 0}

        max_veg = max(
            (
                self.coordinator.calculate_days(p.veg_start)
                for p in plants
                if p.veg_start
            ),
            default=0,
        )
        max_flower = max(
            (
                self.coordinator.calculate_days(p.flower_start)
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

        # Use extracted data constant
        thresholds = DRYING_THRESHOLDS

        if state.temp is not None:
            low, high, prob_obs, prob_err = thresholds["temp"]
            if low <= state.temp <= high:
                observations.append(prob_obs)
            else:
                observations.append(prob_err)
                self._reasons.append((prob_err[1], f"Temp out of range ({state.temp})"))

        if state.humidity is not None:
            low, high, prob_obs, prob_err = thresholds["humidity"]
            if low <= state.humidity <= high:
                observations.append(prob_obs)
            else:
                observations.append(prob_err)
                self._reasons.append(
                    (prob_err[1], f"Humidity out of range ({state.humidity})")
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

        # Use extracted data constant
        thresholds = CURING_THRESHOLDS

        if state.temp is not None:
            low, high, prob_obs, prob_err = thresholds["temp"]
            if low <= state.temp <= high:
                observations.append(prob_obs)
            else:
                observations.append(prob_err)
                self._reasons.append((prob_err[1], f"Temp out of range ({state.temp})"))

        if state.humidity is not None:
            low, high, prob_obs, prob_err = thresholds["humidity"]
            if low <= state.humidity <= high:
                observations.append(prob_obs)
            else:
                observations.append(prob_err)
                self._reasons.append(
                    (prob_err[1], f"Humidity out of range ({state.humidity})")
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
        """Generate a notification when the sensor turns on."""
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"High Mold Risk in {growspace.name}"
                message = self._generate_notification_message("High mold risk detected")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate the probability of mold risk, focusing on late flower conditions."""
        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        # --- Trend Analysis for Mold Risk (Moved to bayesian_evaluator.py) ---
        trend_obs, trend_reasons, trend_states = await async_evaluate_mold_risk_trend(
            self, state
        )
        observations.extend(trend_obs)
        self._reasons.extend(trend_reasons)
        self._sensor_states.update(trend_states)

        if state.flower_days >= 35:
            prob = (0.80, 0.20)
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
                if state.humidity is not None and state.humidity > 60:
                    prob = self.env_config.get(
                        "prob_mold_humidity_high_night", (0.99, 0.10)
                    )
                    observations.append(prob)
                    self._reasons.append(
                        (prob[0], f"Night Humidity High ({state.humidity})")
                    )
                if state.vpd is not None and state.vpd < 0.8:
                    prob = self.env_config.get("prob_mold_vpd_low_night", (0.95, 0.20))
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Night VPD Low ({state.vpd})"))
            else:  # Daytime checks
                if state.humidity is not None and state.humidity > 60:
                    prob = self.env_config.get(
                        "prob_mold_humidity_high_day", (0.95, 0.20)
                    )
                    observations.append(prob)
                    self._reasons.append(
                        (prob[0], f"Day Humidity High ({state.humidity})")
                    )
                if state.vpd is not None and state.vpd < 0.9:
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
        """Generate a notification when the sensor turns off."""
        if not new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"Optimal Conditions Lost in {growspace.name}"
                message = self._generate_notification_message("Optimal conditions lost")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate the probability that the environment is in an optimal state."""
        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        # 1. OPTIMAL TEMPERATURE (Logic moved to bayesian_evaluator.py)
        temp_obs, temp_reasons = evaluate_optimal_temperature(state, self.env_config)
        observations.extend(temp_obs)
        self._reasons.extend(temp_reasons)

        # 2. OPTIMAL VPD (Logic moved to bayesian_evaluator.py)
        vpd_obs, vpd_reasons = evaluate_optimal_vpd(state, self.env_config)
        observations.extend(vpd_obs)
        self._reasons.extend(vpd_reasons)

        # 3. OPTIMAL CO2 LEVELS (Logic moved to bayesian_evaluator.py)
        co2_obs, co2_reasons = evaluate_optimal_co2(state, self.env_config)
        observations.extend(co2_obs)
        self._reasons.extend(co2_reasons)

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()
