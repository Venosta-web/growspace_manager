"""Environment monitoring with Bayesian sensors for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any
from datetime import date, datetime, timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.recorder import get_instance as get_recorder_instance
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.components.recorder import history
from homeassistant.util import utcnow



from .coordinator import GrowspaceCoordinator
from .const import DOMAIN, DEFAULT_BAYESIAN_PRIORS, DEFAULT_BAYESIAN_THRESHOLDS
from .models import EnvironmentState

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Bayesian environment monitoring sensors."""
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
    """Validate that required environment sensors are configured."""
    required = ["temperature_sensor", "humidity_sensor", "vpd_sensor"]
    return all(config.get(key) for key in required)


class BayesianEnvironmentSensor(BinarySensorEntity):
    """Base class for Bayesian environment sensors."""

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
        """Initialize the Bayesian sensor."""
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.env_config = env_config
        self._attr_should_poll = False

        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} {name_suffix}"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_{sensor_type}"

        self.prior = env_config.get(
            prior_key, DEFAULT_BAYESIAN_PRIORS.get(sensor_type)
        )
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
        """Fetch and return the base environment state."""
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
                    is_lights_on = bool(
                        self._get_sensor_value(light_sensor)
                        and self._get_sensor_value(light_sensor) > 0
                    )
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
        """When entity is added to hass."""
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
        """Handle coordinator update."""
        self.hass.async_create_task(self.async_update_and_notify())

    @callback
    def _async_sensor_changed(self, event) -> None:
        """Handle sensor state changes."""
        self.hass.async_create_task(self.async_update_and_notify())

    def _get_sensor_value(self, sensor_id: str) -> float | None:
        """Get numeric value from sensor state."""
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
        """Calculate days since date string (YYYY-MM-DD)."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return 0
        return (date.today() - dt).days

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get veg_days and flower_days from coordinator."""
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
        """Analyze the trend of a sensor over a given duration."""
        start_time = utcnow() - timedelta(minutes=duration_minutes)
        end_time = utcnow()

        try:
            history_list = await get_recorder_instance(self.hass).async_add_executor_job(
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

        except Exception as e:
            _LOGGER.error("Error analyzing sensor history for %s: %s", sensor_id, e)
            return {"trend": "unknown", "crossed_threshold": False}

    def _generate_notification_message(self, base_message: str) -> str:
        """Generate a notification message with reasons, respecting character limits."""
        sorted_reasons = sorted(self._reasons, reverse=True)
        message = base_message

        for _, reason in sorted_reasons:
            if len(message) + len(reason) + 2 < 65:
                message += f", {reason}"
            else:
                break
        return message

    async def _send_notification(self, title: str, message: str) -> None:
        """Send a notification if the target is configured and cooldown has passed."""
        now = utcnow()
        if self._last_notification_sent and (now - self._last_notification_sent) < self._notification_cooldown:
            return  # Anti-spam: cooldown active

        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if not growspace or not growspace.notification_target:
            return  # No target configured

        self._last_notification_sent = now
        # Get the service name (e.g., "mobile_app_my_phone")
        notification_service = growspace.notification_target.replace("notify.", "")
        
        await self.hass.services.async_call(
            "notify",
            notification_service, # Call the specific service
            {
                "message": message,
                "title": title,
                # No 'target' key needed here
            },
        )

    def get_notification_title_message(self, new_state_on: bool) -> tuple[str, str] | None:
        """Return the notification title and message, if any."""
        return None

    async def async_update_and_notify(self) -> None:
        """Update the sensor state and send a notification if the state changes."""
        old_state_on = self.is_on
        await self._async_update_probability()
        new_state_on = self.is_on

        if new_state_on != old_state_on:
            notification = self.get_notification_title_message(new_state_on)
            if notification:
                title, message = notification
                await self._send_notification(title, message)

    async def _async_update_probability(self) -> None:
        """Calculate Bayesian probability - implemented by subclasses."""
        raise NotImplementedError

    @staticmethod
    def _calculate_bayesian_probability(
        prior: float, observations: list[tuple[float, float]]
    ) -> float:
        """Calculate Bayesian probability from observations.

        Args:
            prior: Prior probability (0-1)
            observations: List of (prob_given_true, prob_given_false) tuples

        Returns:
            Posterior probability (0-1)
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
        """Return true if probability exceeds threshold."""
        return self._probability >= self.threshold

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return probability and observation details."""
        return {
            "probability": round(self._probability, 3),
            "threshold": self.threshold,
            "observations": self._sensor_states,
            "reasons": [r[1] for r in sorted(self._reasons, reverse=True)],
        }


class BayesianStressSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting plant stress conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="stress",
            name_suffix="Plants Under Stress",
            prior_key="prior_stress",
            threshold_key="stress_threshold",
        )

    def get_notification_title_message(self, new_state_on: bool) -> tuple[str, str] | None:
        """Return the notification title and message, if any."""
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"Plants Under Stress in {growspace.name}"
                message = self._generate_notification_message("High stress detected")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate stress probability using Bayesian inference."""
        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        self._sensor_states["temperature_trend"] = "stable"
        self._sensor_states["humidity_trend"] = "stable"
        self._sensor_states["vpd_trend"] = "stable"

        # --- Trend Analysis for Stress ---
        for sensor_key, trend_key in [
            ("temperature", "temperature_trend"),
            ("humidity", "humidity_trend"),
            ("vpd", "vpd_trend"),
        ]:
            trend_sensor_id = self.env_config.get(f"{sensor_key}_trend_sensor")
            stats_sensor_id = self.env_config.get(f"{sensor_key}_stats_sensor")

            if trend_sensor_id:
                trend_state = self.hass.states.get(trend_sensor_id)
                if trend_state and trend_state.state == "on":  # Rising trend
                    self._sensor_states[trend_key] = "rising"
                    gradient = trend_state.attributes.get("gradient", 0)
                    if gradient > 0.1:
                        prob = self.env_config.get("prob_trend_fast_rise", (0.95, 0.15))
                        observations.append(prob)
                        self._reasons.append((prob[0], f"{sensor_key.capitalize()} rising fast"))
                    else:
                        prob = self.env_config.get("prob_trend_slow_rise", (0.75, 0.30))
                        observations.append(prob)
                        self._reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

            elif stats_sensor_id:
                stats_state = self.hass.states.get(stats_sensor_id)
                if stats_state and (
                    change := stats_state.attributes.get("change")
                ) is not None:
                    threshold = 0.2 if sensor_key == "vpd" else 1.0
                    if change > threshold:
                        self._sensor_states[trend_key] = "rising"
                        prob = (0.85, 0.25)
                        observations.append(prob)
                        self._reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))

            else:  # Fallback to manual analysis
                duration = self.env_config.get(f"{sensor_key}_trend_duration", 30)
                threshold = self.env_config.get(f"{sensor_key}_trend_threshold", 26.0)
                sensitivity = self.env_config.get(f"{sensor_key}_trend_sensitivity", 0.5)
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
                        self._reasons.append((prob[0], f"{sensor_key.capitalize()} rising"))


        # --- Direct Observations ---
        if state.temp is not None:
            if not state.is_lights_on and state.temp > 24:
                prob = self.env_config.get("prob_night_temp_high", (0.80, 0.20))
                observations.append(prob)
                self._reasons.append((prob[0], f"Night Temp High ({state.temp})"))

            if state.temp > 32:
                prob = self.env_config.get("prob_temp_extreme_heat", (0.98, 0.05))
                observations.append(prob)
                self._reasons.append((prob[0], f"Extreme Heat ({state.temp})"))
            elif state.temp > 30:
                prob = self.env_config.get("prob_temp_high_heat", (0.85, 0.15))
                observations.append(prob)
                self._reasons.append((prob[0], f"High Heat ({state.temp})"))
            elif state.flower_days >= 42 and state.temp > 24:
                prob = (0.70, 0.30)
                observations.append(prob)
                self._reasons.append((prob[0], f"Temp Warm ({state.temp})"))
            elif state.temp > 28:
                prob = self.env_config.get("prob_temp_warm", (0.65, 0.30))
                observations.append(prob)
                self._reasons.append((prob[0], f"Temp Warm ({state.temp})"))
            elif state.temp < 15:
                prob = self.env_config.get("prob_temp_extreme_cold", (0.95, 0.08))
                observations.append(prob)
                self._reasons.append((prob[0], f"Extreme Cold ({state.temp})"))
            elif state.temp < 18:
                prob = self.env_config.get("prob_temp_cold", (0.80, 0.20))
                observations.append(prob)
                self._reasons.append((prob[0], f"Temp Cold ({state.temp})"))

        if state.humidity is not None:
            if state.humidity < 35:
                prob = self.env_config.get("prob_humidity_too_dry", (0.85, 0.20))
                observations.append(prob)
                self._reasons.append((prob[0], f"Humidity Dry ({state.humidity})"))
            if state.flower_days == 0 and state.veg_days < 14:
                if state.humidity > 80:
                    prob = self.env_config.get("prob_humidity_high_veg_early", (0.80, 0.20))
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Humidity High ({state.humidity})"))
            elif state.flower_days == 0 and state.veg_days >= 14:
                if state.humidity > 70:
                    prob = self.env_config.get("prob_humidity_high_veg_late", (0.85, 0.15))
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Humidity High ({state.humidity})"))
            elif 0 < state.flower_days < 42:  # Early Flower
                if state.humidity > 55 or state.humidity < 45:
                    prob = (0.75, 0.25)
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Humidity out of range ({state.humidity})"))
            elif state.flower_days >= 42:  # Late Flower
                if state.humidity > 50 or state.humidity < 40:
                    prob = (0.85, 0.15)
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Humidity out of range ({state.humidity})"))

        if state.vpd is not None:
            # Define VPD thresholds for each stage, day and night
            vpd_thresholds = {
                "veg_early": {
                    "day": {"stress": (0.3, 1.0), "mild": (0.4, 0.8), "prob_keys": ("prob_vpd_stress_veg_early", "prob_vpd_mild_stress_veg_early"), "prob_defaults": ((0.85, 0.15), (0.60, 0.30))},
                    "night": {"stress": (0.3, 1.0), "mild": (0.4, 0.8), "prob_keys": ("prob_vpd_stress_veg_early", "prob_vpd_mild_stress_veg_early"), "prob_defaults": ((0.85, 0.15), (0.60, 0.30))},
                },
                "veg_late": {
                    "day": {"stress": (0.6, 1.4), "mild": (0.8, 1.2), "prob_keys": ("prob_vpd_stress_veg_late", "prob_vpd_mild_stress_veg_late"), "prob_defaults": ((0.80, 0.18), (0.55, 0.35))},
                    "night": {"stress": (0.3, 1.0), "mild": (0.5, 0.8), "prob_keys": ("prob_vpd_stress_veg_late", "prob_vpd_mild_stress_veg_late"), "prob_defaults": ((0.80, 0.18), (0.55, 0.35))},
                },
                "flower_early": {
                    "day": {"stress": (0.8, 1.6), "mild": (1.0, 1.5), "prob_keys": ("prob_vpd_stress_flower_early", "prob_vpd_mild_stress_flower_early"), "prob_defaults": ((0.85, 0.15), (0.60, 0.30))},
                    "night": {"stress": (0.5, 1.1), "mild": (0.7, 1.0), "prob_keys": ("prob_vpd_stress_flower_early", "prob_vpd_mild_stress_flower_early"), "prob_defaults": ((0.85, 0.15), (0.60, 0.30))},
                },
                "flower_late": {
                    "day": {"stress": (1.0, 1.6), "mild": (1.2, 1.5), "prob_keys": ("prob_vpd_stress_flower_late", "prob_vpd_mild_stress_flower_late"), "prob_defaults": ((0.90, 0.12), (0.65, 0.28))},
                    "night": {"stress": (0.6, 1.2), "mild": (0.8, 1.1), "prob_keys": ("prob_vpd_stress_flower_late", "prob_vpd_mild_stress_flower_late"), "prob_defaults": ((0.90, 0.12), (0.65, 0.28))},
                },
            }

            # Determine current growth stage
            stage = None
            if state.flower_days == 0 and state.veg_days < 14:
                stage = "veg_early"
            elif state.flower_days == 0 and state.veg_days >= 14:
                stage = "veg_late"
            elif 0 < state.flower_days < 42:
                stage = "flower_early"
            elif state.flower_days >= 42:
                stage = "flower_late"

            if stage:
                time_of_day = "day" if state.is_lights_on else "night"
                thresholds = vpd_thresholds[stage][time_of_day]

                stress_low, stress_high = thresholds["stress"]
                mild_low, mild_high = thresholds["mild"]
                prob_stress_key, prob_mild_key = thresholds["prob_keys"]
                prob_stress_default, prob_mild_default = thresholds["prob_defaults"]

                if state.vpd < stress_low or state.vpd > stress_high:
                    prob = self.env_config.get(prob_stress_key, prob_stress_default)
                    observations.append(prob)
                    self._reasons.append((prob[0], f"VPD out of range ({state.vpd})"))
                elif state.vpd < mild_low or state.vpd > mild_high:
                    prob = self.env_config.get(prob_mild_key, prob_mild_default)
                    observations.append(prob)
                    self._reasons.append((prob[0], f"VPD out of range ({state.vpd})"))

        if state.co2 is not None:
            if state.co2 < 400:
                prob = (0.80, 0.25)
                observations.append(prob)
                self._reasons.append((prob[0], f"CO2 Low ({state.co2})"))
            elif state.co2 > 1800:
                prob = (0.75, 0.20)
                observations.append(prob)
                self._reasons.append((prob[0], f"CO2 High ({state.co2})"))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class LightCycleVerificationSensor(BinarySensorEntity):
    """Verifies the light cycle matches the growspace stage."""

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
        """When entity is added to hass."""
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
        """Handle coordinator update."""
        self.hass.async_create_task(self.async_update())

    @callback
    def _async_light_sensor_changed(self, event) -> None:
        """Handle light sensor state changes."""
        self.hass.async_create_task(self.async_update())

    def _get_growth_stage_info(self) -> dict[str, int]:
        """Get veg_days and flower_days from coordinator."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        if not plants:
            return {"veg_days": 0, "flower_days": 0}

        max_veg = max(
            (self.coordinator._calculate_days(p.veg_start) for p in plants if p.veg_start),
            default=0,
        )
        max_flower = max(
            (self.coordinator._calculate_days(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )
        return {"veg_days": max_veg, "flower_days": max_flower}

    async def async_update(self) -> None:
        """Update the sensor's state."""
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

        # Calculate time since last change
        time_since_last_changed = now - light_state.last_changed

        stage_info = self._get_growth_stage_info()
        is_flower_stage = stage_info["flower_days"] > 0

        expected_on_hours = 12 if is_flower_stage else 18
        expected_off_hours = 24 - expected_on_hours

        # Check correctness
        if is_light_on:
            if time_since_last_changed > timedelta(hours=expected_on_hours):
                self._is_correct = False # Light has been on for too long
            else:
                self._is_correct = True
        else: # Light is off
            if time_since_last_changed > timedelta(hours=expected_off_hours):
                self._is_correct = False # Light has been off for too long
            else:
                self._is_correct = True

        self._time_in_current_state = time_since_last_changed
        self.async_write_ha_state()

    @property
    def is_on(self) -> bool:
        """Return true if the light schedule is correct."""
        return self._is_correct

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return state attributes."""
        stage_info = self._get_growth_stage_info()
        is_flower_stage = stage_info["flower_days"] > 0
        expected_schedule = "12/12" if is_flower_stage else "18/6"

        return {
            "expected_schedule": expected_schedule,
            "light_entity_id": self.light_entity_id,
            "time_in_current_state": str(self._time_in_current_state),
        }


class BayesianDryingSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting optimal drying conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
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
        """Calculate optimal drying probability."""
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
                self._reasons.append((0.90, f"Humidity out of range ({state.humidity})"))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianCuringSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting optimal curing conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
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
        """Calculate optimal curing probability."""
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
                self._reasons.append((0.90, f"Humidity out of range ({state.humidity})"))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianMoldRiskSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting mold risk in late flower."""

    def __init__(self, coordinator, growspace_id, env_config):
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="mold_risk",
            name_suffix="High Mold Risk",
            prior_key="prior_mold_risk",
            threshold_key="mold_threshold",
        )

    def get_notification_title_message(self, new_state_on: bool) -> tuple[str, str] | None:
        """Return the notification title and message, if any."""
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"High Mold Risk in {growspace.name}"
                message = self._generate_notification_message("High mold risk detected")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate mold risk probability."""
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
            if (trend_state := self.hass.states.get(trend_sensor_id)) and trend_state.state == "on":
                self._sensor_states["humidity_trend"] = "rising"
                prob = (0.90, 0.20)
                observations.append(prob)
                self._reasons.append((prob[0], "Humidity rising"))
        elif stats_sensor_id:
            if (stats_state := self.hass.states.get(stats_sensor_id)) and (
                change := stats_state.attributes.get("change")
            ) is not None and change > 1.0:
                self._sensor_states["humidity_trend"] = "rising"
                prob = (0.85, 0.25)
                observations.append(prob)
                self._reasons.append((prob[0], "Humidity rising"))

        # Falling VPD trend is a risk
        trend_sensor_id = self.env_config.get("vpd_trend_sensor")
        stats_sensor_id = self.env_config.get("vpd_stats_sensor")
        if trend_sensor_id:
            if (trend_state := self.hass.states.get(trend_sensor_id)) and trend_state.state == "off":
                self._sensor_states["vpd_trend"] = "falling"
                prob = (0.90, 0.20)
                observations.append(prob)
                self._reasons.append((prob[0], "VPD falling"))
        elif stats_sensor_id:
            if (stats_state := self.hass.states.get(stats_sensor_id)) and (
                change := stats_state.attributes.get("change")
            ) is not None and change < -0.1:
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
                # We pass a high threshold for humidity (rising) and low for VPD (falling) to effectively just check direction
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
                    if (
                        sensor_key == "humidity" and analysis["trend"] == "rising"
                    ) or (sensor_key == "vpd" and analysis["trend"] == "falling"):
                        p_true = 0.5 + (sensitivity * 0.45)
                        p_false = 0.5 - (sensitivity * 0.4)
                        prob = (p_true, p_false)
                        observations.append(prob)
                        self._reasons.append((prob[0], f"{sensor_key.capitalize()} trend"))

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
                    self._reasons.append((prob[0], f"Night Humidity High ({state.humidity})"))
                if state.vpd is not None and state.vpd < 1.3:
                    prob = self.env_config.get("prob_mold_vpd_low_night", (0.95, 0.20))
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Night VPD Low ({state.vpd})"))
            else:  # Daytime checks
                if state.humidity is not None and state.humidity > 55:
                    prob = self.env_config.get("prob_mold_humidity_high_day", (0.95, 0.20))
                    observations.append(prob)
                    self._reasons.append((prob[0], f"Day Humidity High ({state.humidity})"))
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
    """Bayesian sensor for detecting optimal growing conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        super().__init__(
            coordinator,
            growspace_id,
            env_config,
            sensor_type="optimal",
            name_suffix="Optimal Conditions",
            prior_key="prior_optimal",
            threshold_key="optimal_threshold",
        )

    def get_notification_title_message(self, new_state_on: bool) -> tuple[str, str] | None:
        """Return the notification title and message, if any."""
        if not new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                title = f"Optimal Conditions Lost in {growspace.name}"
                message = self._generate_notification_message("Optimal conditions lost")
                return title, message
        return None

    async def _async_update_probability(self) -> None:
        """Calculate optimal conditions probability."""
        self._reasons = []
        state = self._get_base_environment_state()
        observations = []

        # Good temperature range
        # === OPTIMAL TEMPERATURE ===
        if state.temp is not None:
            if state.is_lights_on:
                # Late flower has different optimal temps
                if state.flower_days >= 42:
                    if 18 <= state.temp <= 24:  # Perfect range for late flower
                        observations.append((0.95, 0.20))
                    # Other temps in this stage are not considered optimal, so no obs.
                else:  # Normal logic for other stages
                    # Perfect range
                    if 24 <= state.temp <= 26:
                        observations.append((0.95, 0.20))
                    # Good range
                    elif 22 <= state.temp <= 28:
                        observations.append((0.85, 0.30))
                    # Acceptable range
                    elif 20 <= state.temp <= 29:
                        observations.append((0.65, 0.45))
                    # Outside optimal
                    else:
                        prob = (0.20, 0.75)
                        observations.append(prob)
                        self._reasons.append((prob[1], f"Temp out of range ({state.temp})"))
            else:  # Nighttime logic
                if 20 <= state.temp <= 23:
                    observations.append((0.95, 0.20))
                else:
                    prob = (0.20, 0.75)
                    observations.append(prob)
                    self._reasons.append((prob[1], f"Night temp out of range ({state.temp})"))

        # VPD in optimal range for stage
        if state.vpd is not None:
            vpd_optimal = False

            if state.is_lights_on:
                # Seedling/Clone/Early Veg: 0.4-0.8 kPa
                if state.flower_days == 0 and state.veg_days < 14:
                    if 0.5 <= state.vpd <= 0.7:  # Perfect
                        vpd_optimal = True
                        observations.append((0.95, 0.18))
                    elif 0.4 <= state.vpd <= 0.8:  # Good
                        observations.append((0.80, 0.28))

                # Late Veg: 0.8-1.2 kPa
                elif state.flower_days == 0 and state.veg_days >= 14:
                    if 0.9 <= state.vpd <= 1.1:  # Perfect
                        vpd_optimal = True
                        observations.append((0.95, 0.18))
                    elif 0.8 <= state.vpd <= 1.2:  # Good
                        observations.append((0.85, 0.25))

                # Early-Mid Flower: 1.0-1.5 kPa
                elif 0 < state.flower_days < 42:
                    if 1.1 <= state.vpd <= 1.4:  # Perfect
                        vpd_optimal = True
                        observations.append((0.95, 0.18))
                    elif 1.0 <= state.vpd <= 1.5:  # Good
                        observations.append((0.85, 0.25))

                # Late Flower: 1.2-1.5 kPa (drier to prevent mold)
                elif state.flower_days >= 42:
                    if 1.3 <= state.vpd <= 1.5:  # Perfect
                        vpd_optimal = True
                        observations.append((0.95, 0.15))
                    elif 1.2 <= state.vpd <= 1.6:  # Good
                        observations.append((0.85, 0.22))
            else:  # Nighttime logic
                # Seedling/Clone/Early Veg: 0.4-0.8 kPa
                if state.flower_days == 0 and state.veg_days < 14:
                    if 0.4 <= state.vpd <= 0.8:
                        vpd_optimal = True
                        observations.append((0.90, 0.20))
                # Late Veg: 0.6-1.1 kPa
                elif state.flower_days == 0 and state.veg_days >= 14:
                    if 0.6 <= state.vpd <= 1.1:
                        vpd_optimal = True
                        observations.append((0.90, 0.20))
                # Early-Mid Flower: 0.8 - 1.2 kPa
                elif 0 < state.flower_days < 42:
                    if 0.8 <= state.vpd <= 1.2:
                        vpd_optimal = True
                        observations.append((0.90, 0.20))
                # Late Flower: 0.9-1.2 kPa
                elif state.flower_days >= 42:
                    if 0.9 <= state.vpd <= 1.2:
                        vpd_optimal = True
                        observations.append((0.90, 0.20))


            # If not optimal, reduce probability
            if not vpd_optimal:
                prob = (0.25, 0.70)
                observations.append(prob)
                self._reasons.append((prob[1], f"VPD out of range ({state.vpd})"))

        # Good CO2 levels
        if state.co2 is not None:
            if state.flower_days >= 42:
                # Late flower prefers lower CO2
                if 400 <= state.co2 <= 800:
                    observations.append((0.90, 0.25))
                elif 800 < state.co2 <= 1200:
                    observations.append((0.4, 0.6))  # Slightly negative
                # Other ranges are not optimal, so no positive obs.
                # Let stress sensor handle out-of-bounds.
            else:
                # Enhanced CO2 (optimal for fast growth)
                if 1000 <= state.co2 <= 1400:
                    observations.append((0.95, 0.20))
                # Good elevated CO2
                elif 800 <= state.co2 <= 1500:
                    observations.append((0.85, 0.30))
                # Adequate ambient CO2
                elif 400 <= state.co2 <= 600:
                    observations.append((0.60, 0.45))
                # Outside optimal range
                else:
                    prob = (0.25, 0.70)
                    observations.append(prob)
                    if state.co2 < 400:
                        self._reasons.append((prob[1], f"CO2 Low ({state.co2})"))
                    else:
                        self._reasons.append((prob[1], f"CO2 High ({state.co2})"))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()
