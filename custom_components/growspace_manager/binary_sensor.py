"""Bayesian binary sensors for environmental monitoring in Growspace Manager.

This file defines a set of binary sensors that use Bayesian inference to assess
various environmental conditions within a growspace, such as plant stress, mold
risk, and optimal conditions. It also includes a sensor to verify the light
cycle schedule.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, override

from homeassistant.components.binary_sensor import (
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.dt import utcnow

from . import GrowspaceConfigEntry
from .bayesian_evaluator import ReasonList
from .const import (
    ATTR_EXPECTED_SCHEDULE,
    ATTR_LIGHT_ENTITY_ID,
    ATTR_OBSERVATIONS,
    ATTR_PROBABILITY,
    ATTR_REASONS,
    ATTR_THRESHOLD,
    ATTR_TIME_IN_CURRENT_STATE,
    CONF_AI_AUTO_ALERTS,
    CONF_VEG_DAY_HOURS,
    DEFAULT_BAYESIAN_PRIORS,
    DEFAULT_BAYESIAN_THRESHOLDS,
    DEFAULT_FLOWER_DAY_HOURS,
    DEFAULT_VEG_DAY_HOURS,
    DOMAIN,
    STAGE_PHOTOPERIOD_KEYS,
    GrowspaceSensorType,
    PlantStage,
)
from .coordinator import GrowspaceCoordinator
from .exceptions import GrowspaceError
from .models import (
    EnvironmentConfig,
    EnvironmentState,
    Growspace,
    GrowspaceEvent,
    GrowspaceType,
    Plant,
)
from .notification_manager import NotificationManager
from .services.ai_assistant import GrowAssistant
from .strain_library import StrainLibrary
from .strategies.curing import CuringEvaluatorStrategy
from .strategies.drying import DryingEvaluatorStrategy
from .strategies.evaluator_strategy import BayesianEvaluatorStrategy
from .strategies.mold import MoldRiskEvaluatorStrategy
from .strategies.optimal import OptimalConditionsEvaluatorStrategy
from .strategies.stress import StressEvaluatorStrategy
from .trend_analyzer import TrendAnalyzer
from .utils import VPDCalculator, calculate_days_since, calculate_stage_transition

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GrowspaceBinarySensorDescription(BinarySensorEntityDescription):
    """Class describing Growspace binary sensors."""

    sensor_type: str
    prior_key: str
    threshold_key: str | None = None


SENSOR_TYPES: tuple[GrowspaceBinarySensorDescription, ...] = (
    GrowspaceBinarySensorDescription(
        key=GrowspaceSensorType.STRESS,
        translation_key=GrowspaceSensorType.STRESS,
        sensor_type=GrowspaceSensorType.STRESS,
        prior_key="prior_stress",
        threshold_key="threshold_stress",
    ),
    GrowspaceBinarySensorDescription(
        key=GrowspaceSensorType.MOLD,
        translation_key=GrowspaceSensorType.MOLD,
        sensor_type=GrowspaceSensorType.MOLD,
        prior_key="prior_mold_risk",
        threshold_key="threshold_mold",
    ),
    GrowspaceBinarySensorDescription(
        key=GrowspaceSensorType.OPTIMAL,
        translation_key=GrowspaceSensorType.OPTIMAL,
        sensor_type=GrowspaceSensorType.OPTIMAL,
        prior_key="prior_optimal",
        threshold_key="threshold_optimal",
    ),
    GrowspaceBinarySensorDescription(
        key=GrowspaceSensorType.DRYING,
        translation_key=GrowspaceSensorType.DRYING,
        sensor_type=GrowspaceSensorType.DRYING,
        prior_key="prior_drying",
        threshold_key="threshold_drying",
    ),
    GrowspaceBinarySensorDescription(
        key=GrowspaceSensorType.CURING,
        translation_key=GrowspaceSensorType.CURING,
        sensor_type=GrowspaceSensorType.CURING,
        prior_key="prior_curing",
        threshold_key="threshold_curing",
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

    async def _update_binary_sensors() -> None:
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
        entry.async_create_background_task(
            hass, _update_binary_sensors(), "update_binary_sensors"
        )

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
    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        return

    allowed_types = set()
    if growspace.growspace_type == GrowspaceType.DRY:
        allowed_types.add(GrowspaceSensorType.DRYING)
        allowed_types.add(GrowspaceSensorType.MOLD)
    elif growspace.growspace_type == GrowspaceType.CURE:
        allowed_types.add(GrowspaceSensorType.CURING)
        allowed_types.add(GrowspaceSensorType.MOLD)
    else:
        # Normal growspace
        allowed_types.add(GrowspaceSensorType.STRESS)
        allowed_types.add(GrowspaceSensorType.MOLD)
        allowed_types.add(GrowspaceSensorType.OPTIMAL)

    # 2. Iterate descriptions and add if allowed
    for description in SENSOR_TYPES:
        if description.sensor_type in allowed_types:
            key = f"{growspace_id}_{description.sensor_type}"
            if key not in initialized_sensors:
                strategy_class = _get_strategy_class(description.sensor_type)
                new_entities.append(
                    BayesianEnvironmentSensor(
                        coordinator=coordinator,
                        growspace_id=growspace_id,
                        env_config=env_config,
                        description=description,
                        strategy_class=strategy_class,
                        # Inject dependencies as callbacks
                        get_growspace=lambda gid: coordinator.growspaces.get(gid),
                        get_plants=coordinator.get_growspace_plants,
                        add_event=coordinator.add_event,
                        notification_manager=coordinator.notification_manager,
                        strain_library=coordinator.strain_library,
                        options=coordinator.options,
                    )
                )
                initialized_sensors.add(key)

    # 3. Light Cycle Verification (Special Case)
    if env_config.light_sensor:
        key = f"{growspace_id}_light_verification"
        if key not in initialized_sensors:
            new_entities.append(
                LightCycleVerificationSensor(
                    coordinator=coordinator,
                    growspace_id=growspace_id,
                    env_config=env_config,
                    # Inject dependencies
                    get_plants=coordinator.get_growspace_plants,
                    calculate_days=coordinator.calculate_days,
                )
            )
            initialized_sensors.add(key)


def _get_strategy_class(sensor_type: str) -> type[BayesianEvaluatorStrategy]:
    """Map sensor type to strategy class."""
    if sensor_type == GrowspaceSensorType.STRESS:
        return StressEvaluatorStrategy
    if sensor_type == GrowspaceSensorType.MOLD:
        return MoldRiskEvaluatorStrategy
    if sensor_type == GrowspaceSensorType.OPTIMAL:
        return OptimalConditionsEvaluatorStrategy
    if sensor_type == GrowspaceSensorType.DRYING:
        return DryingEvaluatorStrategy
    if sensor_type == GrowspaceSensorType.CURING:
        return CuringEvaluatorStrategy
    return StressEvaluatorStrategy  # Fallback


def _validate_env_config(config: EnvironmentConfig) -> bool:
    """Validate that the required environment sensor entities are configured."""
    has_temp = bool(config.temperature_sensor) or bool(config.temperature_sensors)
    has_humidity = bool(config.humidity_sensor) or bool(config.humidity_sensors)
    has_vpd = bool(config.vpd_sensor) or bool(config.vpd_sensors)

    # Valid if we have temp, humidity, and either a VPD sensor or ability to calculate it
    return has_temp and has_humidity and (has_vpd or (has_temp and has_humidity))


class BayesianEnvironmentSensor(
    CoordinatorEntity[GrowspaceCoordinator],
    BinarySensorEntity,
):
    """Base class for Bayesian environment monitoring binary sensors."""

    entity_description: GrowspaceBinarySensorDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        description: GrowspaceBinarySensorDescription,
        strategy_class: type[BayesianEvaluatorStrategy],
        get_growspace: Callable[[str], Growspace | None],
        get_plants: Callable[[str], list[Plant]],
        add_event: Callable[[str, GrowspaceEvent], None],
        notification_manager: NotificationManager | None,
        strain_library: StrainLibrary | None,
        options: dict[str, Any],
    ) -> None:
        """Initialize the Bayesian environment sensor."""
        super().__init__(coordinator)
        self.entity_description = description  # Set this first
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.env_config = env_config
        self.strategy = strategy_class(self)
        self._attr_should_poll = False

        # Store injected dependencies
        self._get_growspace = get_growspace
        self._get_plants = get_plants
        self._add_event = add_event
        self._strain_library = strain_library
        self._options = options

        growspace = get_growspace(growspace_id)
        if not growspace:
            raise ValueError(f"Growspace {growspace_id} not found")

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

        # TrendAnalyzer will be initialized in async_added_to_hass when self.hass is available
        self.trend_analyzer: TrendAnalyzer | None = None
        self.notification_manager = notification_manager

    @property
    def sensor_states(self) -> dict[str, Any]:
        """Return the observed sensor states."""
        return self._sensor_states

    @property
    def reasons(self) -> list[tuple[float, str]]:
        """Return the current reasons for the sensor state."""
        return self._reasons

    @property
    @override  # type: ignore[misc]
    def is_on(self) -> bool:
        """Return true if the sensor is on (probability > threshold)."""
        return self._probability >= self.threshold

    @property
    @override  # type: ignore[misc]
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
        growspace = self._get_growspace(self.growspace_id)
        if growspace and growspace.environment_config:
            self.env_config = growspace.environment_config

        # Aggregate sensors with fallback to singular if needed
        temp = self._get_aggregated_sensor_value(
            [
                s
                for s in (
                    self.env_config.temperature_sensor,
                    *self.env_config.temperature_sensors,
                )
                if s is not None
            ]
        )
        humidity = self._get_aggregated_sensor_value(
            [
                s
                for s in (
                    self.env_config.humidity_sensor,
                    *self.env_config.humidity_sensors,
                )
                if s is not None
            ]
        )
        vpd = self._get_aggregated_sensor_value(
            [
                s
                for s in (self.env_config.vpd_sensor, *self.env_config.vpd_sensors)
                if s is not None
            ]
        )

        # Fallback: Calculate VPD if sensor is missing but Temp/Hum are available
        active_lst_offset = self.env_config.lst_offset
        if growspace and growspace.growspace_type in (
            GrowspaceType.DRY,
            GrowspaceType.CURE,
        ):
            active_lst_offset = 0.0

        if vpd is None and temp is not None and humidity is not None:
            vpd = VPDCalculator.calculate_vpd_with_lst_offset(
                temp, humidity, active_lst_offset
            )

        co2 = self._get_sensor_value(self.env_config.co2_sensor)

        stage_info = self._get_growth_stage_info()
        veg_days = stage_info.get("veg_days", 0)
        flower_days = stage_info.get("flower_days", 0)
        seedling_days = stage_info.get("seedling_days", 0)
        clone_days = stage_info.get("clone_days", 0)

        is_lights_on = self._determine_light_state()

        fan_off = self._determine_fan_state()
        dehumidifier_on = self._determine_dehumidifier_state()
        exhaust_value = self._determine_exhaust_value()
        humidifier_value = self._determine_humidifier_value()

        soil_moisture_sensor = self.env_config.soil_moisture_sensor
        soil_moisture = self._get_sensor_value(soil_moisture_sensor)

        humidifier_on = self._determine_humidifier_state()

        # Substrate temperature (average of configured sensors)
        substrate_temp = self._get_aggregated_sensor_value(
            self.env_config.substrate_temperature_sensors
        )

        self._sensor_states = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "co2": co2,
            "soil_moisture": soil_moisture,
            "substrate_temp": substrate_temp,
            "lst_offset": active_lst_offset,
            "veg_days": veg_days,
            "flower_days": flower_days,
            "seedling_days": seedling_days,
            "clone_days": clone_days,
            "is_lights_on": is_lights_on,
            "fan_off": fan_off,
            "dehumidifier_on": dehumidifier_on,
            "exhaust_value": exhaust_value,
            "humidifier_value": humidifier_value,
            "humidifier_on": humidifier_on,
        }

        return EnvironmentState(
            temp=temp,
            humidity=humidity,
            vpd=vpd,
            co2=co2,
            veg_days=veg_days,
            flower_days=flower_days,
            seedling_days=seedling_days,
            clone_days=clone_days,
            is_lights_on=is_lights_on,
            fan_off=fan_off,
            dehumidifier_on=dehumidifier_on,
            exhaust_value=exhaust_value,
            humidifier_value=humidifier_value,
            humidifier_on=humidifier_on,
            soil_moisture=soil_moisture,
            substrate_temp=substrate_temp,
        )

    def _determine_light_state(self) -> bool | None:
        """Determine the light state (OR logic) and trigger cooldown on switch."""
        light_sensors = self.env_config.light_sensors
        if not light_sensors:
            return None

        any_on = False
        any_valid = False

        for sensor in light_sensors:
            is_on, valid = self._check_light_sensor(sensor)
            if valid:
                any_valid = True
                if is_on:
                    any_on = True

        current_lights_on = any_on if any_valid else None
        self._check_light_state_change(current_lights_on)
        self._last_light_state = current_lights_on
        return current_lights_on

    def _check_light_sensor(self, sensor_id: str) -> tuple[bool, bool]:
        """Check a single light sensor state and return (is_on, is_valid)."""
        state = self.hass.states.get(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return False, False

        if state.domain == "sensor":
            val = self._get_sensor_value(sensor_id)
            return val is not None and val > 0, val is not None

        return state.state == "on", True

    def _check_light_state_change(self, current_lights_on: bool | None) -> None:
        """Check for state change to trigger notification cooldown."""
        if (
            self._last_light_state is not None
            and current_lights_on is not None
            and self._last_light_state != current_lights_on
        ):
            _LOGGER.debug(
                "Light switched in %s. Triggering notification cooldown",
                self.growspace_id,
            )
            if self.notification_manager:
                self.notification_manager.trigger_cooldown(self.growspace_id)

    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        await super().async_added_to_hass()

        # Initialize TrendAnalyzer now that self.hass is available
        self.trend_analyzer = TrendAnalyzer(self.hass)

        # Register for batched notifications
        if self.notification_manager:
            self.notification_manager.attach_sensor(self.growspace_id, self)

        c = self.env_config
        sensors = [
            c.temperature_sensor,
            c.humidity_sensor,
            c.vpd_sensor,
            c.co2_sensor,
            c.soil_moisture_sensor,
        ]

        # Extend with multi-device lists
        sensors.extend(c.temperature_sensors)
        sensors.extend(c.humidity_sensors)
        sensors.extend(c.vpd_sensors)
        sensors.extend(c.light_sensors)
        sensors.extend(c.circulation_fan_entities)
        sensors.extend(c.dehumidifier_entities)
        sensors.extend(c.exhaust_fan_entities)
        sensors.extend(c.humidifier_entities)

        sensors_filtered: list[str] = [s for s in sensors if s]

        self.async_on_remove(
            async_track_state_change_event(
                self.hass,
                sensors_filtered,
                self._async_sensor_changed,
            )
        )

        # Schedule initial update
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self.async_update_and_notify(),
            f"initial_update_{self.entity_id or self.unique_id}",
        )

    async def async_will_remove_from_hass(self) -> None:
        """Unregister from batched notifications."""
        if self.notification_manager:
            self.notification_manager.detach_sensor(self.growspace_id, self)
        await super().async_will_remove_from_hass()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updates from the data coordinator."""
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self.async_update_and_notify(),
            f"coordinator_update_{self.entity_id or self.unique_id}",
        )

    @callback
    def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle state changes of the monitored environment sensors."""
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self.async_update_and_notify(),
            f"sensor_changed_{self.entity_id or self.unique_id}",
        )

    def _get_sensor_value(self, sensor_id: str | None) -> float | None:
        """Safely get the numeric value from a sensor's state."""
        if not sensor_id:
            return None

        state = self.hass.states.get(sensor_id)
        if not state or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN):
            return None

        try:
            return float(state.state)
        except ValueError, TypeError:
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

    @staticmethod
    def _days_since(date_str: str) -> int:
        """Calculate the number of days since a given date string."""
        return calculate_days_since(date_str)

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get the current growth stage duration for the growspace."""
        growspace = self._get_growspace(self.growspace_id)
        if growspace and growspace.growspace_type in (
            GrowspaceType.DRY,
            GrowspaceType.CURE,
        ):
            return {
                "veg_days": -1,
                "flower_days": -1,
                "seedling_days": -1,
                "clone_days": -1,
            }

        plants = self._get_plants(self.growspace_id)

        if not plants:
            return {
                "veg_days": -1,
                "flower_days": -1,
                "seedling_days": -1,
                "clone_days": -1,
            }

        max_veg = max(
            (
                self._days_since(p.veg_start)
                for p in plants
                if isinstance(p.veg_start, str)
            ),
            default=-1,
        )
        max_flower = max(
            (
                self._days_since(p.flower_start)
                for p in plants
                if isinstance(p.flower_start, str)
            ),
            default=-1,
        )
        max_seedling = max(
            (
                self._days_since(p.seedling_start)
                for p in plants
                if isinstance(p.seedling_start, str)
            ),
            default=-1,
        )
        max_clone = max(
            (
                self._days_since(p.clone_start)
                for p in plants
                if isinstance(p.clone_start, str)
            ),
            default=-1,
        )

        return {
            "veg_days": max_veg,
            "flower_days": max_flower,
            "seedling_days": max_seedling,
            "clone_days": max_clone,
        }

    async def async_analyze_sensor_trend(
        self, sensor_id: str, duration_minutes: int, threshold: float
    ) -> dict[str, Any]:
        """Analyze the trend of a sensor's history to detect rising or falling patterns."""
        if not self.trend_analyzer:
            _LOGGER.error(
                "TrendAnalyzer not initialized for %s. Entity may not be fully added to HA",
                self.entity_id,
            )
            return {"trend": "unknown", "crossed_threshold": False}

        try:
            return await self.trend_analyzer.async_analyze_sensor_trend(
                sensor_id, duration_minutes, threshold
            )
        except (
            AttributeError,
            KeyError,
            ValueError,
            ServiceValidationError,
            GrowspaceError,
        ):
            _LOGGER.exception("Error analyzing sensor history for %s", sensor_id)
            return {"trend": "unknown", "crossed_threshold": False}

    def generate_notification_message(self, base_message: str) -> str:
        """Construct a detailed notification message from the list of reasons."""
        if self.notification_manager:
            return self.notification_manager.generate_notification_message(
                base_message, self._reasons
            )
        return base_message

    async def _send_notification(self, title: str, message: str) -> None:
        """Send a notification to the configured target for the growspace."""
        try:
            # Check for AI Auto Alerts
            final_message = message
            ai_alerts_enabled = self._options.get(CONF_AI_AUTO_ALERTS, False)

            if (
                ai_alerts_enabled
                and self._probability >= self.threshold
                and self._strain_library
            ):
                try:
                    assistant = GrowAssistant(
                        self.hass, self.coordinator, self._strain_library
                    )
                    ai_message = await assistant.generate_alert_message(
                        self.growspace_id,
                        self.entity_description.sensor_type,
                        [r[1] for r in self._reasons],
                    )
                    final_message = f"{ai_message}\n\n(Original: {message})"
                except (
                    AttributeError,
                    KeyError,
                    ValueError,
                    ServiceValidationError,
                    GrowspaceError,
                    Exception,
                ):
                    _LOGGER.warning(
                        "Failed to generate AI alert, falling back to standard message"
                    )

            if self.notification_manager:
                await self.notification_manager.async_send_notification(
                    self.growspace_id, title, final_message, self._sensor_states
                )
        except (
            AttributeError,
            KeyError,
            ValueError,
            TypeError,
            ServiceValidationError,
            GrowspaceError,
            Exception,
        ):
            _LOGGER.exception("Failed to send notification to %s", self.growspace_id)

    def get_notification_title_message(
        self, new_state_on: bool
    ) -> tuple[str, str] | None:
        """Return the title and message for a notification based on state change."""
        return self.strategy.get_notification_title_message(new_state_on)

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
        """Update probability using the assigned strategy."""
        env_state = self._get_base_environment_state()
        all_observations, all_reasons = await self.strategy.async_evaluate(env_state)

        # Calculate final probability
        if not all_observations:
            self._probability = 0.0
        else:
            self._probability = self._calculate_bayesian_probability(
                self.prior, all_observations
            )
        self._reasons = all_reasons

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

            # Determine category
            category = "alert"
            if self.entity_description.sensor_type == GrowspaceSensorType.OPTIMAL:
                category = "environment"

            # Create the event object
            event = GrowspaceEvent(
                sensor_type=self.entity_description.sensor_type,
                growspace_id=self.growspace_id,
                start_time=self._event_start_time.isoformat(),
                end_time=end_time.isoformat(),
                duration_sec=int(duration),
                severity=self._event_max_prob,
                category=category,
                reasons=[r[1] for r in sorted(self._reasons, reverse=True)[:5]],
            )

            # Add event via injected callback
            self._add_event(self.growspace_id, event)

            # Reset event tracking
            self._event_start_time = None
            self._event_max_prob = 0.0

        # Update pending alert state on every probability update
        # (replaces direct async_schedule_notification call on state change)
        if (
            self.notification_manager
            and self.entity_description.sensor_type != GrowspaceSensorType.OPTIMAL
        ):
            self.notification_manager.update_pending_alert(self.growspace_id, self)

        self.async_write_ha_state()

    def _determine_fan_state(self) -> bool | None:
        """Determine if circulation fans are off (AND logic)."""
        fan_entities = self.env_config.circulation_fan_entities
        if not fan_entities:
            return None

        all_off = True
        any_valid = False
        for entity in fan_entities:
            state = self.hass.states.get(entity)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                any_valid = True
                if state.state != "off":
                    all_off = False

        return all_off if any_valid else None

    def _determine_dehumidifier_state(self) -> bool | None:
        """Determine if dehumidifier is on (OR logic)."""
        dehum_entities = self.env_config.dehumidifier_entities
        if not dehum_entities:
            return None

        any_on = False
        any_valid = False
        for entity in dehum_entities:
            state = self.hass.states.get(entity)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                any_valid = True
                if state.state == "on":
                    any_on = True

        return any_on if any_valid else None

    def _determine_exhaust_value(self) -> float | None:
        """Determine exhaust value (Max value)."""
        entities = self.env_config.exhaust_fan_entities
        return self._get_max_sensor_value(entities)

    def _determine_humidifier_value(self) -> float | None:
        """Determine humidifier value (Max value)."""
        entities = self.env_config.humidifier_entities
        return self._get_max_sensor_value(entities)

    def _determine_humidifier_state(self) -> bool | None:
        """Determine if humidifier is on (OR logic)."""
        entities = self.env_config.humidifier_entities
        if not entities:
            return None

        any_on = False
        any_valid = False
        for entity in entities:
            state = self.hass.states.get(entity)
            if state and state.state not in (STATE_UNAVAILABLE, STATE_UNKNOWN):
                any_valid = True
                if state.state == "on":
                    any_on = True

        return any_on if any_valid else None

    def _get_max_sensor_value(self, entities: list[str]) -> float | None:
        """Helper to get max value from list of entities."""
        if not entities:
            return None
        values = []
        for entity in entities:
            val = self._get_sensor_value(entity)
            if val is not None:
                values.append(val)
        return max(values) if values else None


class LightCycleVerificationSensor(
    CoordinatorEntity[GrowspaceCoordinator],
    BinarySensorEntity,
):
    """Binary sensor to verify if the light schedule matches the expected plan."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_translation_key = "light_verification"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        env_config: EnvironmentConfig,
        get_plants: Callable[[str], list[Plant]],
        calculate_days: Callable[[str], int],
    ) -> None:
        """Initialize."""
        super().__init__(coordinator)
        self.growspace_id = growspace_id
        self.env_config = env_config

        # Store injected dependencies
        self._get_plants = get_plants
        self._calculate_days = calculate_days

        growspace = coordinator.growspaces.get(growspace_id)
        name = growspace.name if growspace else growspace_id
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
        self.light_entity_id = (
            self.env_config.light_sensors[0] if self.env_config.light_sensors else None
        )
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

        env_config_dict = self.env_config.to_dict()
        conf_key = STAGE_PHOTOPERIOD_KEYS.get(stage_key, CONF_VEG_DAY_HOURS)
        default_hours = (
            DEFAULT_VEG_DAY_HOURS
            if stage_key == PlantStage.VEG
            else DEFAULT_FLOWER_DAY_HOURS
        )
        day_hours = env_config_dict.get(conf_key, default_hours)

        expected_schedule = f"{day_hours}/{24 - day_hours}"

        return {
            ATTR_EXPECTED_SCHEDULE: expected_schedule,
            ATTR_LIGHT_ENTITY_ID: self.light_entity_id,
            ATTR_TIME_IN_CURRENT_STATE: str(self._time_in_current_state),
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks."""
        await super().async_added_to_hass()
        # Track light sensors changes
        if self.env_config.light_sensors:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    self.env_config.light_sensors,
                    self._async_light_sensor_changed,
                )
            )
        await self.async_update()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle updates from the data coordinator."""
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self.async_update(),
            f"light_cycle_coordinator_update_{self.entity_id or self.unique_id}",
        )

    @callback
    def _handle_sensor_change(self, event: Event[EventStateChangedData]) -> None:
        """Handle light sensor change."""
        self._update_state()
        self.async_write_ha_state()

    def _update_state(self) -> None:
        """Verify light state against schedule."""
        # Simplified Logic
        light_sensors = self.env_config.light_sensors
        if light_sensors:
            # Just checking accessibility for now as per original code stub
            # In real impl, we'd check time vs state
            pass

        self._is_schedule_matched = True

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get the current growth stage duration for the growspace."""
        plants = self._get_plants(self.growspace_id)
        if not plants:
            return {
                "veg_days": 0,
                "flower_days": 0,
                "seedling_days": 0,
                "clone_days": 0,
            }

        max_veg = max(
            (
                self._calculate_days(p.veg_start)
                for p in plants
                if isinstance(p.veg_start, str)
            ),
            default=0,
        )
        max_flower = max(
            (self._calculate_days(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )
        return {"veg_days": max_veg, "flower_days": max_flower}

    def _get_current_stage_key(self, stage_info: dict[str, int]) -> str:
        _, stage_b, _ = calculate_stage_transition(
            stage_info.get("flower_days", -1),
            stage_info.get("veg_days", -1),
            stage_info.get("seedling_days", -1),
            stage_info.get("clone_days", -1),
            stage_info.get("dry_days", -1),
            stage_info.get("cure_days", -1),
            stage_info.get("mother_days", -1),
        )
        return stage_b

    @callback
    def _async_light_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        """Handle state changes of the monitored light sensor."""
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self.async_update(),
            f"light_sensor_changed_{self.entity_id or self.unique_id}",
        )

    async def async_update(self) -> None:
        """Update the sensor's state based on the light's on/off duration."""
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
        conf_key = STAGE_PHOTOPERIOD_KEYS.get(stage_key, CONF_VEG_DAY_HOURS)
        default_hours = (
            DEFAULT_VEG_DAY_HOURS
            if stage_key == PlantStage.VEG
            else DEFAULT_FLOWER_DAY_HOURS
        )
        day_hours = env_config_dict.get(conf_key, default_hours)

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
