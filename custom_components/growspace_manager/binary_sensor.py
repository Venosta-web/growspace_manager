"""Bayesian binary sensors for environmental monitoring in Growspace Manager.

This file defines a set of binary sensors that use Bayesian inference to assess
various environmental conditions within a growspace, such as plant stress, mold
risk, and optimal conditions. It also includes a sensor to verify the light
cycle schedule.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util.dt import utcnow

from . import GrowspaceConfigEntry
from .bayesian_data import (
    CURING_THRESHOLDS,
    DRYING_THRESHOLDS,
    PROB_MOLD_HUMIDIFIER_ON,
    PROB_MOLD_STAGNANT_AIR,
)
from .bayesian_evaluator import (
    ObservationList,
    ReasonList,
    async_evaluate_mold_risk_trend,
    async_evaluate_stress_trend,
    evaluate_active_desiccation,
    evaluate_active_saturation,
    evaluate_direct_co2_stress,
    evaluate_direct_humidity_stress,
    evaluate_direct_temp_stress,
    evaluate_direct_vpd_stress,
    evaluate_optimal_co2,
    evaluate_optimal_temperature,
    evaluate_optimal_vpd,
    evaluate_soil_moisture_stress,
)
from .const import (
    ATTR_EXPECTED_SCHEDULE,
    ATTR_LIGHT_ENTITY_ID,
    ATTR_OBSERVATIONS,
    ATTR_PROBABILITY,
    ATTR_REASONS,
    ATTR_THRESHOLD,
    ATTR_TIME_IN_CURRENT_STATE,
    DEFAULT_BAYESIAN_PRIORS,
    DEFAULT_BAYESIAN_THRESHOLDS,
    DOMAIN,
    METRIC_CURING,
    METRIC_DRYING,
    METRIC_OPTIMAL,
    METRIC_STRESS,
    PlantStage,
)
from .coordinator import GrowspaceCoordinator
from .models import EnvironmentConfig, EnvironmentState, GrowspaceEvent
from .trend_analyzer import TrendAnalyzer

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GrowspaceBinarySensorDescription(BinarySensorEntityDescription):
    """Class describing Growspace binary sensors."""

    sensor_type: str
    name_suffix: str
    prior_key: str | None = None
    threshold_key: str | None = None


SENSOR_TYPES: tuple[GrowspaceBinarySensorDescription, ...] = (
    GrowspaceBinarySensorDescription(
        key=METRIC_STRESS,
        sensor_type=METRIC_STRESS,
        name_suffix="Stress",
        prior_key="prior_stress",
        threshold_key="threshold_stress",
        icon="mdi:alert-circle",
    ),
    GrowspaceBinarySensorDescription(
        key="mold",
        sensor_type="mold",
        name_suffix="Mold Risk",
        prior_key="prior_mold_risk",
        threshold_key="threshold_mold",
        icon="mdi:bacteria",
    ),
    GrowspaceBinarySensorDescription(
        key=METRIC_OPTIMAL,
        sensor_type=METRIC_OPTIMAL,
        name_suffix="Optimal Conditions",
        prior_key="prior_optimal",
        threshold_key="threshold_optimal",
        icon="mdi:check-circle",
    ),
    GrowspaceBinarySensorDescription(
        key=METRIC_DRYING,
        sensor_type=METRIC_DRYING,
        name_suffix="Drying",
        prior_key="prior_drying",
        threshold_key="threshold_drying",
        icon="mdi:weather-windy",
    ),
    GrowspaceBinarySensorDescription(
        key=METRIC_CURING,
        sensor_type=METRIC_CURING,
        name_suffix="Curing",
        prior_key="prior_curing",
        threshold_key="threshold_curing",
        icon="mdi:glass-jar",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrowspaceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager Bayesian binary sensors from a config entry."""
    coordinator = entry.runtime_data
    initialized_sensors: set[str] = set()

    async def _update_binary_sensors():
        """Check for new growspaces with environment config and add sensors."""
        new_entities: list[BinarySensorEntity] = []

        for growspace_id, growspace in coordinator.growspaces.items():
            env_config = getattr(growspace, "environment_config", None)

            # Ensure env_config is an EnvironmentConfig object and valid
            if (
                env_config
                and isinstance(env_config, EnvironmentConfig)
                and _validate_env_config(env_config)
            ):
                _process_growspace_sensors(
                    coordinator,
                    growspace_id,
                    env_config,
                    initialized_sensors,
                    new_entities,
                )

        if new_entities:
            async_add_entities(new_entities)

    # Initial load
    await _update_binary_sensors()

    # Listen for future updates - wrap async callback in sync wrapper
    def _schedule_update() -> None:
        """Sync wrapper to schedule the async update."""
        hass.async_create_task(_update_binary_sensors())

    entry.async_on_unload(coordinator.async_add_listener(_schedule_update))


def _process_growspace_sensors(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    env_config: EnvironmentConfig,
    initialized_sensors: set[str],
    new_entities: list[BinarySensorEntity],
) -> None:
    """Process and add sensors for a single growspace using definitions."""

    # 1. Determine which sensor types are valid for this growspace
    allowed_types = set()
    if growspace_id == "dry":
        allowed_types.add(METRIC_DRYING)
        allowed_types.add("mold")
    elif growspace_id == "cure":
        allowed_types.add(METRIC_CURING)
        allowed_types.add("mold")
    else:
        # Normal growspace
        allowed_types.add(METRIC_STRESS)
        allowed_types.add("mold")
        allowed_types.add(METRIC_OPTIMAL)

    # 2. Iterate descriptions and add if allowed
    for description in SENSOR_TYPES:
        if description.sensor_type in allowed_types:
            key = f"{growspace_id}_{description.sensor_type}"
            if key not in initialized_sensors:
                # Factory logic to pick correct class
                # This part is a bit messy without a registry, but keeps it explicit
                sensor_class = _get_sensor_class(description.sensor_type)
                new_entities.append(
                    sensor_class(coordinator, growspace_id, env_config, description)
                )
                initialized_sensors.add(key)

    # 3. Light Cycle Verification (Special Case)
    if env_config.light_sensor:
        key = f"{growspace_id}_light_verification"
        if key not in initialized_sensors:
            new_entities.append(
                LightCycleVerificationSensor(coordinator, growspace_id, env_config)
            )
            initialized_sensors.add(key)


def _get_sensor_class(sensor_type: str) -> type[BayesianEnvironmentSensor]:
    """Map sensor type to class."""
    if sensor_type == METRIC_STRESS:
        return BayesianStressSensor
    elif sensor_type == "mold":
        return BayesianMoldRiskSensor
    elif sensor_type == METRIC_OPTIMAL:
        return BayesianOptimalConditionsSensor
    elif sensor_type == METRIC_DRYING:
        return BayesianDryingSensor
    elif sensor_type == METRIC_CURING:
        return BayesianCuringSensor
    return BayesianEnvironmentSensor  # Fallback


def _validate_env_config(config: EnvironmentConfig) -> bool:
    """Validate that the required environment sensor entities are configured."""
    has_temp = bool(config.temperature_sensor)
    has_humidity = bool(config.humidity_sensor)
    has_vpd = bool(config.vpd_sensor)

    # Valid if we have temp, humidity, and either a VPD sensor or ability to calculate it
    return has_temp and has_humidity and (has_vpd or (has_temp and has_humidity))


class BayesianEnvironmentSensor(BinarySensorEntity):
    """Base class for Bayesian environment monitoring binary sensors."""

    entity_description: GrowspaceBinarySensorDescription

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        description: GrowspaceBinarySensorDescription,
    ) -> None:
        """Initialize the Bayesian environment sensor."""
        self.entity_description = description  # Set this first
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.env_config = env_config
        self._attr_should_poll = False

        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} {description.name_suffix}"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_{description.sensor_type}"

        # Access bayesian_options from EnvironmentConfig object
        bayesian_options = env_config.bayesian_options or {}

        # Safe defaults if keys are missing
        self.prior = DEFAULT_BAYESIAN_PRIORS.get(description.sensor_type, 0.5)
        self.threshold = DEFAULT_BAYESIAN_THRESHOLDS.get(description.sensor_type, 0.8)

        # Override if specific key exists in config options
        if description.prior_key and description.prior_key in bayesian_options:
            self.prior = bayesian_options[description.prior_key]

        if description.threshold_key and description.threshold_key in bayesian_options:
            self.threshold = bayesian_options[description.threshold_key]

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

        self._sensor_states: dict[str, Any] = {}
        self._reasons: ReasonList = []
        self._probability = 0.0
        self._event_start_time: datetime | None = None
        self._event_max_prob: float = 0.0
        self._last_light_state: bool | None = None

        self.trend_analyzer = TrendAnalyzer(self.coordinator.hass)
        self.notification_manager = self.coordinator.notification_manager

    @property
    def is_on(self) -> bool:
        """Return true if the sensor is on (probability > threshold)."""
        return self._probability >= self.threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        attrs = {
            ATTR_PROBABILITY: round(self._probability, 2),
            ATTR_THRESHOLD: self.threshold,
            ATTR_REASONS: [r[1] for r in sorted(self._reasons, reverse=True)[:5]],
            ATTR_OBSERVATIONS: self._sensor_states,
        }
        if self._event_start_time:
            attrs[ATTR_TIME_IN_CURRENT_STATE] = (
                utcnow() - self._event_start_time
            ).total_seconds()
        return attrs

    def _get_base_environment_state(self) -> EnvironmentState:
        """Fetch sensor values and return a structured EnvironmentState object."""
        # Always fetch the latest config from the coordinator
        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if growspace and growspace.environment_config:
            self.env_config = growspace.environment_config

        # With strict typing, access attributes directly from dataclass
        temp = self._get_sensor_value(self.env_config.temperature_sensor)
        humidity = self._get_sensor_value(self.env_config.humidity_sensor)
        vpd = self._get_sensor_value(self.env_config.vpd_sensor)
        co2 = self._get_sensor_value(self.env_config.co2_sensor)

        stage_info = self._get_growth_stage_info()
        veg_days = stage_info["veg_days"]
        flower_days = stage_info["flower_days"]

        is_lights_on = self._determine_light_state()

        fan_entity = self.env_config.circulation_fan_entity
        fan_off = None
        if fan_entity:
            fan_state = self.hass.states.get(fan_entity)
            if fan_state and fan_state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                fan_off = fan_state.state == "off"

        dehumidifier_entity = self.env_config.dehumidifier_entity
        dehumidifier_on = None
        if dehumidifier_entity:
            dehum_state = self.hass.states.get(dehumidifier_entity)
            if dehum_state and dehum_state.state not in (
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            ):
                dehumidifier_on = dehum_state.state == "on"

        exhaust_sensor = self.env_config.exhaust_fan_entity
        exhaust_value = self._get_sensor_value(exhaust_sensor)

        humidifier_sensor = self.env_config.humidifier_entity
        humidifier_value = self._get_sensor_value(humidifier_sensor)

        soil_moisture_sensor = self.env_config.soil_moisture_sensor
        soil_moisture = self._get_sensor_value(soil_moisture_sensor)

        self._sensor_states = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "co2": co2,
            "soil_moisture": soil_moisture,
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
            soil_moisture=soil_moisture,
        )

    def _determine_light_state(self) -> bool | None:
        """Determine the light state and trigger cooldown on switch."""
        light_sensor = self.env_config.light_sensor
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

        c = self.env_config
        sensors = [
            c.temperature_sensor,
            c.humidity_sensor,
            c.vpd_sensor,
            c.co2_sensor,
            c.circulation_fan_entity,
            c.dehumidifier_entity,
            c.exhaust_fan_entity,
            c.humidifier_entity,
            c.soil_moisture_sensor,
        ]

        sensors_filtered: list[str] = [s for s in sensors if s]

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                sensors_filtered,
                self._async_sensor_changed,
            )
        )

        # Schedule initial update
        self.hass.async_create_task(self.async_update_and_notify())

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
        if self.growspace_id in ("dry", "cure"):
            return {"veg_days": 0, "flower_days": 0}

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

    async def async_analyze_sensor_trend(
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

    def _calculate_bayesian_probability(
        self, start_prob: float, observations: list[tuple[float, float]]
    ) -> float:
        """Update probability using Bayesian inference from a list of observations (p_true, p_false)."""
        if not observations:
            return start_prob

        # Working with odds to avoid floating point underflows/issues with 0/1
        # P = O / (1 + O)
        # O = P / (1 - P)

        # Clamp start_prob to avoid div by zero
        start_prob = max(0.001, min(0.999, start_prob))

        prior_odds = start_prob / (1 - start_prob)
        posterior_odds = prior_odds

        for p_true, p_false in observations:
            # Likelihood ratio = P(E|H) / P(E|~H)
            p_true = max(0.001, min(0.999, p_true))
            p_false = max(0.001, min(0.999, p_false))

            likelihood_ratio = p_true / p_false
            posterior_odds *= likelihood_ratio

        return posterior_odds / (1 + posterior_odds)

    async def _async_update_probability(self) -> None:
        """Update probability - should be implemented by subclasses."""
        raise NotImplementedError

    async def async_update_and_notify(self) -> None:
        """Update the sensor's probability and send a notification if the state changes."""
        old_state_on = self.is_on
        await self._async_update_probability()
        new_state_on = self.is_on

        # Event Capture Logic
        if new_state_on:
            self._event_max_prob = max(self._event_max_prob, self._probability)

        # Detect Rising Edge (Start of Event)
        if new_state_on and not old_state_on:
            self._event_start_time = utcnow()
            self._event_max_prob = self._probability

        # Detect Falling Edge (End of Event)
        elif not new_state_on and old_state_on and self._event_start_time:
            end_time = utcnow()
            duration = (end_time - self._event_start_time).total_seconds()

            # Create the event object
            event = GrowspaceEvent(
                sensor_type=self.entity_description.sensor_type,
                growspace_id=self.growspace_id,
                start_time=self._event_start_time.isoformat(),
                end_time=end_time.isoformat(),
                duration_sec=int(duration),
                severity=self._event_max_prob,
                category="alert",
                reasons=[r[1] for r in sorted(self._reasons, reverse=True)[:5]],
            )

            # Add to coordinator
            self.coordinator.add_event(self.growspace_id, event)

            # Reset event tracking
            self._event_start_time = None
            self._event_max_prob = 0.0

        if new_state_on != old_state_on:
            notification_data = self.get_notification_title_message(new_state_on)
            if notification_data:
                await self._send_notification(*notification_data)

        self.async_write_ha_state()


class BayesianStressSensor(BayesianEnvironmentSensor):
    """Sensor that calculates the probability of plant stress."""

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        description: GrowspaceBinarySensorDescription,
    ) -> None:
        """Initialize the plant stress sensor."""
        super().__init__(coordinator, growspace_id, env_config, description)

    async def _async_update_probability(self) -> None:
        """Calculate the probability of stress based on Bayesian inference."""
        env_state = self._get_base_environment_state()

        if None in (env_state.temp, env_state.humidity, env_state.vpd, env_state.co2):
            self._probability = 0.0
            self._reasons = []
            return

        env_config_dict = self.env_config.to_dict()
        all_observations: ObservationList = []
        all_reasons: ReasonList = []

        # 1. Active Desiccation (Critical)
        obs, rsn = evaluate_active_desiccation(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        # 2. Active Saturation (Critical)
        obs, rsn = evaluate_active_saturation(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        # 3. Direct Stress Checks
        obs, rsn = evaluate_direct_temp_stress(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        obs, rsn = evaluate_direct_humidity_stress(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        obs, rsn = evaluate_direct_vpd_stress(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        obs, rsn = evaluate_direct_co2_stress(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        obs, rsn = evaluate_soil_moisture_stress(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        # 4. Trends
        if self.env_config.temperature_sensor:
            # async_evaluate_stress_trend returns (obs, reasons, states)
            obs, rsn, _ = await async_evaluate_stress_trend(self, env_state)
            all_observations.extend(obs)
            all_reasons.extend(rsn)

        # Calculate final probability
        self._probability = self._calculate_bayesian_probability(
            self.prior, all_observations
        )
        self._reasons = all_reasons

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Notify on rising edge of stress."""
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            name = growspace.name if growspace else self.growspace_id
            message = self._generate_notification_message(
                f"High stress conditions detected in {name}"
            )
            return (f"Plant Stress Alert: {name}", message)
        return None


class BayesianMoldRiskSensor(BayesianEnvironmentSensor):
    """Sensor that calculates the probability of mold growth."""

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        description: GrowspaceBinarySensorDescription,
    ) -> None:
        """Initialize the mold risk sensor."""
        super().__init__(coordinator, growspace_id, env_config, description)

    async def _async_update_probability(self) -> None:
        """Calculate the probability of mold risk."""
        env_state = self._get_base_environment_state()

        if None in (env_state.temp, env_state.humidity):
            self._probability = 0.0
            self._reasons = []
            return

        prob = self.prior

        if self.env_config.humidity_sensor:
            obs, rsn, _ = await async_evaluate_mold_risk_trend(self, env_state)
            # Obs is a list of tuples, handle it
            if obs:
                # Add observation to manual calc?
                # Wait, async_evaluate_mold_risk_trend returns observations list.
                # But logic aboves uses implicit prob update.
                # We should convert existing logic to observations list or convert trend to old style?
                # Better to convert WHOLE function to observations style.
                pass

        # Refactoring Mold Sensor to use ObservationList
        all_observations: ObservationList = []
        all_reasons: ReasonList = []

        # 1. High Humidity
        if env_state.humidity > 70 or (
            env_state.flower_days > 40 and env_state.humidity > 60
        ):
            prob = (0.8, 0.2)
            all_observations.append(prob)
            all_reasons.append((prob[0], "High Humidity"))

        # 2. Low Circulation
        if env_state.fan_off:
            prob = (
                PROB_MOLD_STAGNANT_AIR
                if isinstance(PROB_MOLD_STAGNANT_AIR, tuple)
                else (0.9, 0.1)
            )  # Fallback
            all_observations.append(prob)
            all_reasons.append((prob[0], "Circulation Fan Off"))

        # 3. Humidifier
        if env_state.humidifier_value and env_state.humidifier_value > 0:
            prob = (
                PROB_MOLD_HUMIDIFIER_ON
                if isinstance(PROB_MOLD_HUMIDIFIER_ON, tuple)
                else (0.8, 0.2)
            )
            all_observations.append(prob)
            all_reasons.append((prob[0], "Humidifier On"))

        # 4. Trends
        if self.env_config.humidity_sensor:
            obs, rsn, _ = await async_evaluate_mold_risk_trend(self, env_state)
            all_observations.extend(obs)
            all_reasons.extend(rsn)

        self._probability = self._calculate_bayesian_probability(
            self.prior, all_observations
        )
        self._reasons = all_reasons

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Notify on rising edge of mold risk."""
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if not growspace:
                return None
            name = growspace.name
            message = self._generate_notification_message("High mold risk detected")
            return (f"High Mold Risk in {name}", message)
        return None


class BayesianOptimalConditionsSensor(BayesianEnvironmentSensor):
    """Sensor that calculates probability of optimal VPD/Temp/CO2."""

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        description: GrowspaceBinarySensorDescription,
    ) -> None:
        """Initialize the optimal conditions sensor."""
        super().__init__(coordinator, growspace_id, env_config, description)

    async def _async_update_probability(self) -> None:
        """Calculate probability of optimal conditions."""
        env_state = self._get_base_environment_state()

        if None in (env_state.temp, env_state.humidity, env_state.vpd):
            self._probability = 0.0
            self._reasons = []
            return

        all_observations: ObservationList = []
        all_reasons: ReasonList = []
        env_config_dict = self.env_config.to_dict()

        obs, rsn = evaluate_optimal_temperature(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        obs, rsn = evaluate_optimal_vpd(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        obs, rsn = evaluate_optimal_co2(env_state, env_config_dict)
        all_observations.extend(obs)
        all_reasons.extend(rsn)

        self._probability = self._calculate_bayesian_probability(
            self.prior, all_observations
        )
        self._reasons = all_reasons

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Notify when conditions DROP out of optimal (falling edge)."""
        if not new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            name = growspace.name if growspace else self.growspace_id
            message = self._generate_notification_message(
                "Conditions no longer optimal"
            )
            return (f"Optimal Conditions Lost: {name}", message)
        return None


class BayesianDryingSensor(BayesianEnvironmentSensor):
    """Sensor for monitoring drying conditions (Temp ~60F, Hum ~60%)."""

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        description: GrowspaceBinarySensorDescription,
    ) -> None:
        """Initialize the optimal drying sensor."""
        super().__init__(coordinator, growspace_id, env_config, description)

    async def _async_update_probability(self) -> None:
        """Calculate probability of optimal drying conditions."""
        # Skip if not a dry growspace
        if self.growspace_id != PlantStage.DRY:
            self._probability = 0
            self._reasons = []
            self.async_write_ha_state()
            return

        env_state = self._get_base_environment_state()

        if None in (env_state.temp, env_state.humidity):
            self._probability = 0.0
            self._reasons = []
            return

        reasons: ReasonList = []
        prob = self.prior

        # Unpack thresholds: (min, max, prob_optimal, prob_out_of_range)
        temp_min, temp_max, temp_prob_opt, temp_prob_out = DRYING_THRESHOLDS["temp"]
        hum_min, hum_max, hum_prob_opt, hum_prob_out = DRYING_THRESHOLDS["humidity"]

        # Temp check
        if temp_min <= env_state.temp <= temp_max:
            weight = temp_prob_opt[0]  # P(obs|true)
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Temp Optimal for Drying"))
        else:
            weight = temp_prob_out[0]  # P(obs|false)
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Temp out of range"))

        # Humidity check
        if hum_min <= env_state.humidity <= hum_max:
            weight = hum_prob_opt[0]
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Humidity Optimal for Drying"))
        else:
            weight = hum_prob_out[0]
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Humidity out of range"))

        self._probability = prob
        self._reasons = reasons


class BayesianCuringSensor(BayesianEnvironmentSensor):
    """Sensor for monitoring curing conditions."""

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        description: GrowspaceBinarySensorDescription,
    ) -> None:
        """Initialize the optimal curing sensor."""
        super().__init__(coordinator, growspace_id, env_config, description)

    async def _async_update_probability(self) -> None:
        """Calculate probability of optimal curing conditions."""
        # Skip if not a cure growspace
        if self.growspace_id != PlantStage.CURE:
            self._probability = 0
            self._reasons = []
            self.async_write_ha_state()
            return

        env_state = self._get_base_environment_state()

        if None in (env_state.temp, env_state.humidity):
            self._probability = 0.0
            self._reasons = []
            return

        reasons: ReasonList = []
        prob = self.prior

        # Unpack thresholds: (min, max, prob_optimal, prob_out_of_range)
        temp_min, temp_max, temp_prob_opt, temp_prob_out = CURING_THRESHOLDS["temp"]
        hum_min, hum_max, hum_prob_opt, hum_prob_out = CURING_THRESHOLDS["humidity"]

        # Temp check
        if temp_min <= env_state.temp <= temp_max:
            weight = temp_prob_opt[0]  # P(obs|true)
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Temp Optimal for Curing"))
        else:
            weight = temp_prob_out[0]  # P(obs|false)
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Temp out of range"))

        # Humidity check
        if hum_min <= env_state.humidity <= hum_max:
            weight = hum_prob_opt[0]
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Humidity Optimal for Curing"))
        else:
            weight = hum_prob_out[0]
            prob = (prob * weight) / ((prob * weight) + ((1 - prob) * (1 - weight)))
            reasons.append((weight, "Humidity out of range"))

        self._probability = prob
        self._reasons = reasons


class LightCycleVerificationSensor(BinarySensorEntity):
    """Binary sensor to verify if the light schedule matches the expected plan."""

    _attr_should_poll = False
    _attr_icon = "mdi:lightbulb-clock"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
    ) -> None:
        """Initialize."""
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.env_config = env_config

        growspace = coordinator.growspaces.get(growspace_id)
        name = growspace.name if growspace else growspace_id
        self._attr_name = f"{name} Light Cycle Verified"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_light_verification"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )
        self._is_schedule_matched = True
        self._is_correct = True  # Alias for test compatibility
        self._expected_schedule = "18/6"
        self.light_entity_id = env_config.light_sensor
        self._time_in_current_state = timedelta(0)

    @property
    def is_on(self) -> bool:
        """Return True if the detected light state matches the expected schedule."""
        return self._is_correct

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        # Compute expected_schedule dynamically based on current stage
        stage_info = self._get_growth_stage_info()
        stage_key = self._get_current_stage_key(stage_info)

        DEFAULT_VEG_DAY_HOURS = 18
        DEFAULT_FLOWER_DAY_HOURS = 12

        env_config_dict = self.env_config.to_dict()
        if stage_key == PlantStage.VEG:
            day_hours = env_config_dict.get("veg_day_hours", DEFAULT_VEG_DAY_HOURS)
        else:
            day_hours = env_config_dict.get(
                f"{stage_key}_day_hours", DEFAULT_FLOWER_DAY_HOURS
            )

        expected_schedule = f"{day_hours}/{24 - day_hours}"

        return {
            ATTR_EXPECTED_SCHEDULE: expected_schedule,
            ATTR_LIGHT_ENTITY_ID: self.light_entity_id,
            ATTR_TIME_IN_CURRENT_STATE: str(self._time_in_current_state),
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        self.coordinator.async_add_listener(self._handle_coordinator_update)
        # Track light sensor changes
        if self.env_config.light_sensor:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    [self.env_config.light_sensor],
                    self._async_light_sensor_changed,
                )
            )
        await self.async_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updates from the data coordinator."""
        self.hass.async_create_task(self.async_update())

    @callback
    def _handle_sensor_change(self, event) -> None:
        """Handle light sensor change."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Verify light state against schedule."""
        # Simplified Logic
        if self.env_config.light_sensor:
            light_state = self.hass.states.get(self.env_config.light_sensor)
            if light_state and light_state.state != STATE_UNAVAILABLE:
                # In a real implementation we would check time of day vs schedule
                pass

        self._is_schedule_matched = True

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
            return PlantStage.VEG
        if 0 < flower_days < 21:
            return "flower_early"
        if 21 <= flower_days < 42:
            return "flower_mid"
        if flower_days >= 42:
            return "flower_late"
        return PlantStage.VEG

    @callback
    def _async_light_sensor_changed(self, event) -> None:
        """Handle state changes of the monitored light sensor."""
        self.hass.async_create_task(self.async_update())

    async def async_update(self) -> None:
        """Update the sensor's state based on the light's on/off duration."""
        DEFAULT_VEG_DAY_HOURS = 18
        DEFAULT_FLOWER_DAY_HOURS = 12

        # Check if light entity is configured (use instance attribute first, then env_config)
        light_entity = self.light_entity_id or self.env_config.light_sensor
        if not light_entity:
            self._is_schedule_matched = False
            self._is_correct = False
            self.async_write_ha_state()
            return

        light_state = self.hass.states.get(light_entity)
        if not light_state or light_state.state in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
            self._is_schedule_matched = False
            self._is_correct = False
            self.async_write_ha_state()
            return

        is_light_on = light_state.state == "on"
        now = utcnow()
        time_since_last_changed = now - light_state.last_changed

        stage_info = self._get_growth_stage_info()
        stage_key = self._get_current_stage_key(stage_info)

        # Get configured day hours for the current stage
        env_config_dict = self.env_config.to_dict()
        if stage_key == PlantStage.VEG:
            day_hours = env_config_dict.get("veg_day_hours", DEFAULT_VEG_DAY_HOURS)
        else:
            day_hours = env_config_dict.get(
                f"{stage_key}_day_hours", DEFAULT_FLOWER_DAY_HOURS
            )

        # Determine the schedule duration based on the stage
        max_on_duration_hours = day_hours
        max_off_duration_hours = 24 - day_hours

        limit_hours = max_on_duration_hours if is_light_on else max_off_duration_hours

        # Apply the single check
        is_correct = time_since_last_changed <= timedelta(hours=limit_hours)
        self._is_schedule_matched = is_correct
        self._is_correct = is_correct

        self._time_in_current_state = time_since_last_changed
        self._expected_schedule = f"{day_hours}/{24 - day_hours}"
        self.async_write_ha_state()
