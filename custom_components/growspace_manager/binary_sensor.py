"""Bayesian binary sensors for environmental monitoring in Growspace Manager.

This file defines a set of binary sensors that use Bayesian inference to assess
various environmental conditions within a growspace, such as plant stress, mold
risk, and optimal conditions. It also includes a sensor to verify the light
cycle schedule.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.dt import utcnow

from .bayesian_data import (
    CURING_THRESHOLDS,
    DRYING_THRESHOLDS,
    PROB_MOLD_HUMIDIFIER_ON,
    PROB_MOLD_STAGNANT_AIR,
    PROB_STRESS_SATURATION,
)
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
    DEFAULT_BAYESIAN_PRIORS,
    DEFAULT_BAYESIAN_THRESHOLDS,
    DEFAULT_FLOWER_DAY_HOURS,
    DEFAULT_VEG_DAY_HOURS,
    DOMAIN,
)
from .coordinator import GrowspaceCoordinator
from .models import EnvironmentState
from .trend_analyzer import TrendAnalyzer

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager Bayesian binary sensors from a config entry."""
    coordinator = config_entry.runtime_data.coordinator

    entities: list[BinarySensorEntity] = []

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
    """Validate that the required environment sensor entities are configured.

    VPD sensor can be either directly configured or calculated from temp and humidity.
    """
    has_temp = bool(config.get("temperature_sensor"))
    has_humidity = bool(config.get("humidity_sensor"))
    has_vpd = bool(config.get("vpd_sensor"))

    # Valid if we have temp, humidity, and either a VPD sensor or ability to calculate it
    return has_temp and has_humidity and (has_vpd or (has_temp and has_humidity))


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

        self._sensor_states: dict[str, Any] = {}
        self._reasons: ReasonList = []
        self._probability = 0.0
        self._last_light_state: bool | None = None

        self.trend_analyzer = TrendAnalyzer(self.coordinator.hass)
        self.notification_manager = self.coordinator.notification_manager

    def _get_base_environment_state(self) -> EnvironmentState:
        """Fetch sensor values and return a structured EnvironmentState object."""
        # Always fetch the latest config from the coordinator
        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if growspace and growspace.environment_config:
            self.env_config = growspace.environment_config

        temp = self._get_sensor_value(self.env_config.get("temperature_sensor"))
        humidity = self._get_sensor_value(self.env_config.get("humidity_sensor"))
        vpd = self._get_sensor_value(self.env_config.get("vpd_sensor"))
        co2 = self._get_sensor_value(self.env_config.get("co2_sensor"))
        stage_info = self._get_growth_stage_info()
        veg_days = stage_info["veg_days"]
        flower_days = stage_info["flower_days"]

        is_lights_on = self._determine_light_state()

        fan_entity = self.env_config.get("circulation_fan")
        fan_off = None
        if fan_entity:
            fan_state = self.hass.states.get(fan_entity)
            if fan_state and fan_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                fan_off = fan_state.state == "off"

        dehumidifier_entity = self.env_config.get("dehumidifier_entity")
        dehumidifier_on = None
        if dehumidifier_entity:
            dehum_state = self.hass.states.get(dehumidifier_entity)
            if dehum_state and dehum_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                dehumidifier_on = dehum_state.state == "on"

        exhaust_sensor = self.env_config.get("exhaust_sensor")
        exhaust_value = self._get_sensor_value(exhaust_sensor)

        humidifier_sensor = self.env_config.get("humidifier_sensor")
        humidifier_value = self._get_sensor_value(humidifier_sensor)

        self._sensor_states = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "co2": co2,
            "veg_days": veg_days,
            "flower_days": flower_days,
            "is_lights_on": is_lights_on,
            "fan_off": fan_off,
            "dehumidifier_on": dehumidifier_on,
            "exhaust_value": exhaust_value,
            "humidifier_value": humidifier_value,
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
            dehumidifier_on=dehumidifier_on,
            exhaust_value=exhaust_value,
            humidifier_value=humidifier_value,
        )

    def _determine_light_state(self) -> bool | None:
        """Determine the light state and trigger cooldown on switch."""
        light_sensor = self.env_config.get("light_sensor")
        current_lights_on = None

        if light_sensor:
            light_state = self.hass.states.get(light_sensor)
            if light_state:
                # Check for unavailable/unknown states first
                if light_state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                    return None

                if light_state.domain == "sensor":
                    sensor_value = self._get_sensor_value(light_sensor)
                    if sensor_value is not None:
                        current_lights_on = bool(sensor_value > 0)
                else:
                    current_lights_on = light_state.state == "on"

        # Check for state change to trigger notification cooldown
        if (
            self._last_light_state is not None
            and current_lights_on is not None
            and self._last_light_state != current_lights_on
        ):
            _LOGGER.debug(
                "Light switched in %s. Triggering notification cooldown",
                self.growspace_id,
            )
            self.notification_manager.trigger_cooldown(self.growspace_id)

        self._last_light_state = current_lights_on
        return current_lights_on

    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        self.coordinator.async_add_listener(self._handle_coordinator_update)

        sensors = [
            self.env_config.get("temperature_sensor"),
            self.env_config.get("humidity_sensor"),
            self.env_config.get("vpd_sensor"),
            self.env_config.get("co2_sensor"),
            self.env_config.get("circulation_fan"),
            self.env_config.get("dehumidifier_entity"),
            self.env_config.get("exhaust_sensor"),
            self.env_config.get("humidifier_sensor"),
        ]

        sensors_filtered: list[str] = [s for s in sensors if s]

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                sensors_filtered,
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
        try:
            return await self.trend_analyzer.async_analyze_sensor_trend(
                sensor_id, duration_minutes, threshold
            )
        except Exception:
            _LOGGER.exception("Error analyzing sensor history for %s", sensor_id)
            return {"trend": "unknown", "crossed_threshold": False}

    def _generate_notification_message(self, base_message: str) -> str:
        """Construct a detailed notification message from the list of reasons."""
        return self.notification_manager.generate_notification_message(
            base_message, self._reasons
        )

    async def _send_notification(self, title: str, message: str) -> None:
        """Send a notification to the configured target for the growspace."""
        try:
            await self.notification_manager.async_send_notification(
                self.growspace_id, title, message, self._sensor_states
            )
        except Exception:
            _LOGGER.exception("Failed to send notification to %s", self.growspace_id)

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

    def __init__(self, coordinator, growspace_id, env_config) -> None:
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

        # 3. ACTIVE DESICCATION (Dehumidifier running while dry/high VPD)
        if state.dehumidifier_on:
            is_dry = state.humidity is not None and state.humidity < 40
            is_high_vpd = state.vpd is not None and state.vpd > 1.5

            if is_dry or is_high_vpd:
                prob = (0.99, 0.01)
                observations.append(prob)
                reason = "Active Desiccation (Dehum ON + "
                if is_dry:
                    reason += f"Low Humidity {state.humidity}%)"
                else:
                    reason += f"High VPD {state.vpd}kPa)"
                self._reasons.append((prob[0], reason))

        # 4. ACTIVE SATURATION (Humidifier running while humid)
        if state.humidifier_value is not None and state.humidifier_value > 0:
            is_humid = False
            threshold = 0

            if state.flower_days == 0:  # Veg
                if state.humidity is not None and state.humidity > 75:
                    is_humid = True
                    threshold = 75
            elif state.humidity is not None and state.humidity > 60:
                is_humid = True
                threshold = 60

            if is_humid:
                observations.append(PROB_STRESS_SATURATION)
                self._reasons.append(
                    (
                        PROB_STRESS_SATURATION[0],
                        f"Active Saturation (Humidifier ON + High Humidity {state.humidity}% > {threshold}%)",
                    )
                )

        self._probability = self._calculate_bayesian_probability(
            float(self.prior or 0.5), observations
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

    def _get_current_stage_key(self, stage_info: dict[str, int]) -> str:
        """Determine the current stage key based on day counts."""

        flower_days = stage_info["flower_days"]

        if flower_days == 0:
            return "veg"
        if 0 < flower_days < 21:
            return "flower_early"
        if 21 <= flower_days < 42:
            return "flower_mid"
        if flower_days >= 42:
            return "flower_late"
        return "veg"

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
        stage_key = self._get_current_stage_key(stage_info)

        # Get configured day hours for the current stage
        if stage_key == "veg":
            day_hours = self.env_config.get("veg_day_hours", DEFAULT_VEG_DAY_HOURS)
        else:
            day_hours = self.env_config.get(
                f"{stage_key}_day_hours", DEFAULT_FLOWER_DAY_HOURS
            )

        # Determine the schedule duration based on the stage:
        max_on_duration_hours = day_hours
        max_off_duration_hours = 24 - day_hours

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
        stage_key = self._get_current_stage_key(stage_info)

        if stage_key == "veg":
            day_hours = self.env_config.get("veg_day_hours", DEFAULT_VEG_DAY_HOURS)
        else:
            day_hours = self.env_config.get(
                f"{stage_key}_day_hours", DEFAULT_FLOWER_DAY_HOURS
            )

        expected_schedule = f"{day_hours}/{24 - day_hours}"

        return {
            "expected_schedule": expected_schedule,
            "light_entity_id": self.light_entity_id,
            "time_in_current_state": str(self._time_in_current_state),
        }


class BayesianDryingSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting optimal drying conditions."""

    def __init__(self, coordinator, growspace_id, env_config) -> None:
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
            float(self.prior or 0.5), observations
        )
        self.async_write_ha_state()


class BayesianCuringSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting optimal curing conditions."""

    def __init__(self, coordinator, growspace_id, env_config) -> None:
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
            float(self.prior or 0.5), observations
        )
        self.async_write_ha_state()


class BayesianMoldRiskSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting high mold risk conditions."""

    def __init__(self, coordinator, growspace_id, env_config) -> None:
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
            self._evaluate_late_flower_mold_risk(state, observations)

        # Control Saturation: Dehumidifier running but humidity still high
        if state.dehumidifier_on and state.humidity is not None and state.humidity > 60:
            prob = (0.95, 0.1)
            observations.append(prob)
            self._reasons.append(
                (prob[0], f"Dehumidifier Ineffective (ON + Hum {state.humidity}%)")
            )

        self._probability = self._calculate_bayesian_probability(
            float(self.prior or 0.5), observations
        )
        self.async_write_ha_state()

    def _evaluate_late_flower_mold_risk(self, state, observations):
        """Evaluate mold risk factors specific to late flower stage."""
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
                prob = self.env_config.get("prob_mold_humidity_high_day", (0.95, 0.20))
                observations.append(prob)
                self._reasons.append((prob[0], f"Day Humidity High ({state.humidity})"))
            if state.vpd is not None and state.vpd < 0.9:
                prob = self.env_config.get("prob_mold_vpd_low_day", (0.90, 0.25))
                observations.append(prob)
                self._reasons.append((prob[0], f"Day VPD Low ({state.vpd})"))
        if state.fan_off:
            prob = self.env_config.get("prob_mold_fan_off", (0.80, 0.15))
            observations.append(prob)
            self._reasons.append((prob[0], "Circulation Fan Off"))

        # Stagnant Air: Low exhaust during late flower
        if state.exhaust_value is not None and state.exhaust_value < 7:
            observations.append(PROB_MOLD_STAGNANT_AIR)
            self._reasons.append(
                (
                    PROB_MOLD_STAGNANT_AIR[0],
                    f"Stagnant Air (Exhaust {state.exhaust_value}/10)",
                )
            )

        # Humidifier Risk: Humidifier running in late flower
        if state.humidifier_value is not None and state.humidifier_value > 0:
            observations.append(PROB_MOLD_HUMIDIFIER_ON)
            self._reasons.append(
                (PROB_MOLD_HUMIDIFIER_ON[0], "Humidifier ON in Late Flower")
            )


class BayesianOptimalConditionsSensor(BayesianEnvironmentSensor):
    """A Bayesian binary sensor for detecting optimal growing conditions."""

    def __init__(self, coordinator, growspace_id, env_config) -> None:
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

        # 4. SYSTEM STABILITY (Dehumidifier fighting)
        if state.dehumidifier_on:
            prob = (0.4, 0.7)
            observations.append(prob)
            self._reasons.append((prob[0], "System Fighting (Dehumidifier ON)"))

        self._probability = self._calculate_bayesian_probability(
            float(self.prior or 0.5), observations
        )
        self.async_write_ha_state()
