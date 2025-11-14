"""Environment monitoring with Bayesian sensors for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any
from datetime import date, datetime, timedelta

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.components.recorder import history
from homeassistant.util import utcnow


from .coordinator import GrowspaceCoordinator
from .const import DOMAIN

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
    ) -> None:
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.env_config = env_config
        self._attr_should_poll = False

        growspace = coordinator.growspaces[growspace_id]
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

        # Track state of all relevant sensors
        self._sensor_states = {}
        self._probability = 0.0
        self._last_notification_sent: datetime | None = None
        self._notification_cooldown = timedelta(minutes=5)  # Anti-spam cooldown

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
            history_list = await self.hass.async_add_executor_job(
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

    async def _send_notification(self, title: str, message: str) -> None:
        """Send a notification if the target is configured and cooldown has passed."""
        now = utcnow()
        if self._last_notification_sent and (now - self._last_notification_sent) < self._notification_cooldown:
            return  # Anti-spam: cooldown active

        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if not growspace or not growspace.notification_target:
            return  # No target configured

        self._last_notification_sent = now
        await self.hass.services.async_call(
            "notify",
            "send_message",
            {
                "message": message,
                "title": title,
                "target": growspace.notification_target,
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
        }


class BayesianStressSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting plant stress conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        super().__init__(coordinator, growspace_id, env_config)
        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} Plants Under Stress"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_stress"
        self.prior = 0.15
        self.threshold = env_config.get("stress_threshold", 0.70)

    def get_notification_title_message(self, new_state_on: bool) -> tuple[str, str] | None:
        """Return the notification title and message, if any."""
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                return "Plants Under Stress", f"High stress detected in {growspace.name}"
        return None

    async def _async_update_probability(self) -> None:
        """Calculate stress probability using Bayesian inference."""
        temp = self._get_sensor_value(self.env_config["temperature_sensor"])
        humidity = self._get_sensor_value(self.env_config["humidity_sensor"])
        vpd = self._get_sensor_value(self.env_config["vpd_sensor"])
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

        self._sensor_states = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "co2": co2,
            "veg_days": veg_days,
            "flower_days": flower_days,
            "is_lights_on": is_lights_on,
            "temperature_trend": "stable",
            "humidity_trend": "stable",
            "vpd_trend": "stable",
        }

        observations = []

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
                        observations.append(
                            self.env_config.get("prob_trend_fast_rise", (0.95, 0.15))
                        )
                    else:
                        observations.append(
                            self.env_config.get("prob_trend_slow_rise", (0.75, 0.30))
                        )
            elif stats_sensor_id:
                stats_state = self.hass.states.get(stats_sensor_id)
                if stats_state and (
                    change := stats_state.attributes.get("change")
                ) is not None:
                    threshold = 0.2 if sensor_key == "vpd" else 1.0
                    if change > threshold:
                        self._sensor_states[trend_key] = "rising"
                        observations.append((0.85, 0.25))
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
                        observations.append((p_true, p_false))

        # --- Direct Observations ---
        if temp is not None:
            if not is_lights_on and temp > 24:
                observations.append(
                    self.env_config.get("prob_night_temp_high", (0.80, 0.20))
                )
            if temp > 32:
                observations.append(
                    self.env_config.get("prob_temp_extreme_heat", (0.98, 0.05))
                )
            elif temp > 30:
                observations.append(
                    self.env_config.get("prob_temp_high_heat", (0.85, 0.15))
                )
            elif temp > 28:
                observations.append(
                    self.env_config.get("prob_temp_warm", (0.65, 0.30))
                )
            elif temp < 15:
                observations.append(
                    self.env_config.get("prob_temp_extreme_cold", (0.95, 0.08))
                )
            elif temp < 18:
                observations.append(
                    self.env_config.get("prob_temp_cold", (0.80, 0.20))
                )

        if humidity is not None:
            if humidity < 35:
                observations.append(
                    self.env_config.get("prob_humidity_too_dry", (0.85, 0.20))
                )
            if flower_days == 0 and veg_days < 14:
                if humidity > 80:
                    observations.append(self.env_config.get("prob_humidity_high_veg_early", (0.80, 0.20)))
            elif flower_days == 0 and veg_days >= 14:
                if humidity > 70:
                    observations.append(self.env_config.get("prob_humidity_high_veg_late", (0.85, 0.15)))
            elif flower_days > 0:
                if humidity > 60:
                    observations.append(
                        self.env_config.get(
                            "prob_humidity_too_humid_flower", (0.95, 0.10)
                        )
                    )
                elif humidity > 55:
                    observations.append(self.env_config.get("prob_humidity_high_flower", (0.75, 0.25)))

        if vpd is not None:
            if flower_days == 0 and veg_days < 14:
                if vpd < 0.3 or vpd > 1.0:
                    observations.append(self.env_config.get("prob_vpd_stress_veg_early", (0.85, 0.15)))
                elif vpd < 0.4 or vpd > 0.8:
                    observations.append(self.env_config.get("prob_vpd_mild_stress_veg_early", (0.60, 0.30)))
            elif flower_days == 0 and veg_days >= 14:
                if vpd < 0.6 or vpd > 1.4:
                    observations.append(self.env_config.get("prob_vpd_stress_veg_late", (0.80, 0.18)))
                elif vpd < 0.8 or vpd > 1.2:
                    observations.append(self.env_config.get("prob_vpd_mild_stress_veg_late", (0.55, 0.35)))
            elif 0 < flower_days < 42:
                if vpd < 0.8 or vpd > 1.6:
                    observations.append(self.env_config.get("prob_vpd_stress_flower_early", (0.85, 0.15)))
                elif vpd < 1.0 or vpd > 1.5:
                    observations.append(self.env_config.get("prob_vpd_mild_stress_flower_early", (0.60, 0.30)))
            elif flower_days >= 42:
                if vpd < 1.0 or vpd > 1.6:
                    observations.append(self.env_config.get("prob_vpd_stress_flower_late", (0.90, 0.12)))
                elif vpd < 1.2 or vpd > 1.5:
                    observations.append(self.env_config.get("prob_vpd_mild_stress_flower_late", (0.65, 0.28)))
        if co2 is not None:
            if co2 < 400:
                observations.append((0.80, 0.25))
            elif co2 > 1800:
                observations.append((0.75, 0.20))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianMoldRiskSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting mold risk in late flower."""

    def __init__(self, coordinator, growspace_id, env_config):
        super().__init__(coordinator, growspace_id, env_config)
        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} High Mold Risk"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_mold_risk"
        self.prior = 0.10
        self.threshold = env_config.get("mold_threshold", 0.75)

    def get_notification_title_message(self, new_state_on: bool) -> tuple[str, str] | None:
        """Return the notification title and message, if any."""
        if new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                return "High Mold Risk", f"High mold risk detected in {growspace.name}"
        return None

    async def _async_update_probability(self) -> None:
        """Calculate mold risk probability."""
        temp = self._get_sensor_value(self.env_config["temperature_sensor"])
        humidity = self._get_sensor_value(self.env_config["humidity_sensor"])
        vpd = self._get_sensor_value(self.env_config["vpd_sensor"])
        stage_info = self._get_growth_stage_info()
        flower_days = stage_info["flower_days"]

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
            "flower_days": flower_days,
            "is_lights_on": is_lights_on,
            "fan_off": fan_off,
            "humidity_trend": "stable",
            "vpd_trend": "stable",
        }

        observations = []

        # --- Trend Analysis for Mold Risk ---
        # Rising humidity trend is a risk
        trend_sensor_id = self.env_config.get("humidity_trend_sensor")
        stats_sensor_id = self.env_config.get("humidity_stats_sensor")
        if trend_sensor_id:
            if (trend_state := self.hass.states.get(trend_sensor_id)) and trend_state.state == "on":
                self._sensor_states["humidity_trend"] = "rising"
                observations.append((0.90, 0.20))
        elif stats_sensor_id:
            if (stats_state := self.hass.states.get(stats_sensor_id)) and (
                change := stats_state.attributes.get("change")
            ) is not None and change > 1.0:
                self._sensor_states["humidity_trend"] = "rising"
                observations.append((0.85, 0.25))

        # Falling VPD trend is a risk
        trend_sensor_id = self.env_config.get("vpd_trend_sensor")
        stats_sensor_id = self.env_config.get("vpd_stats_sensor")
        if trend_sensor_id:
            if (trend_state := self.hass.states.get(trend_sensor_id)) and trend_state.state == "off":
                self._sensor_states["vpd_trend"] = "falling"
                observations.append((0.90, 0.20))
        elif stats_sensor_id:
            if (stats_state := self.hass.states.get(stats_sensor_id)) and (
                change := stats_state.attributes.get("change")
            ) is not None and change < -0.1:
                self._sensor_states["vpd_trend"] = "falling"
                observations.append((0.85, 0.25))


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
                        observations.append((p_true, p_false))
        if flower_days >= 35:
            observations.append((0.99, 0.01))

            if temp is not None and 16 < temp < 23:
                observations.append(
                    self.env_config.get("prob_mold_temp_danger_zone", (0.85, 0.30))
                )

            if not is_lights_on:
                observations.append(
                    self.env_config.get("prob_mold_lights_off", (0.75, 0.30))
                )
                if humidity is not None and humidity > 50:
                    observations.append(
                        self.env_config.get(
                            "prob_mold_humidity_high_night", (0.99, 0.10)
                        )
                    )
                if vpd is not None and vpd < 1.3:
                    observations.append(
                        self.env_config.get("prob_mold_vpd_low_night", (0.95, 0.20))
                    )
            else:  # Daytime checks
                if humidity is not None and humidity > 55:
                    observations.append(self.env_config.get("prob_mold_humidity_high_day", (0.95, 0.20)))
                if vpd is not None and vpd < 1.2:
                    observations.append(self.env_config.get("prob_mold_vpd_low_day", (0.90, 0.25)))
            if fan_off:
                observations.append(self.env_config.get("prob_mold_fan_off", (0.80, 0.15)))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianOptimalConditionsSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting optimal growing conditions."""

    def __init__(self, coordinator, growspace_id, env_config):
        super().__init__(coordinator, growspace_id, env_config)
        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} Optimal Conditions"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_optimal"
        self.prior = 0.40
        self.threshold = 0.80

    def get_notification_title_message(self, new_state_on: bool) -> tuple[str, str] | None:
        """Return the notification title and message, if any."""
        if not new_state_on:
            growspace = self.coordinator.growspaces.get(self.growspace_id)
            if growspace:
                return "Optimal Conditions Lost", f"Optimal conditions lost in {growspace.name}"
        return None

    async def _async_update_probability(self) -> None:
        """Calculate optimal conditions probability."""
        temp = self._get_sensor_value(self.env_config["temperature_sensor"])
        vpd = self._get_sensor_value(self.env_config["vpd_sensor"])
        co2 = self._get_sensor_value(self.env_config["co2_sensor"])
        stage_info = self._get_growth_stage_info()

        self._sensor_states = {
            "temperature": temp,
            "vpd": vpd,
            "co2": co2,
            "veg_days": stage_info["veg_days"],
            "flower_days": stage_info["flower_days"],
        }

        observations = []

        # Good temperature range
        # === OPTIMAL TEMPERATURE ===
        if temp is not None:
            # Perfect range
            if 24 <= temp <= 26:
                observations.append((0.95, 0.20))
            # Good range
            elif 22 <= temp <= 28:
                observations.append((0.85, 0.30))
            # Acceptable range
            elif 20 <= temp <= 29:
                observations.append((0.65, 0.45))
            # Outside optimal
            else:
                observations.append((0.20, 0.75))

        # VPD in optimal range for stage
        if vpd is not None:
            veg_days = stage_info["veg_days"]
            flower_days = stage_info["flower_days"]

            vpd_optimal = False

            # Seedling/Clone/Early Veg: 0.4-0.8 kPa
            if flower_days == 0 and veg_days < 14:
                if 0.5 <= vpd <= 0.7:  # Perfect
                    vpd_optimal = True
                    observations.append((0.95, 0.18))
                elif 0.4 <= vpd <= 0.8:  # Good
                    observations.append((0.80, 0.28))

            # Late Veg: 0.8-1.2 kPa
            elif flower_days == 0 and veg_days >= 14:
                if 0.9 <= vpd <= 1.1:  # Perfect
                    vpd_optimal = True
                    observations.append((0.95, 0.18))
                elif 0.8 <= vpd <= 1.2:  # Good
                    observations.append((0.85, 0.25))

            # Early-Mid Flower: 1.0-1.5 kPa
            elif 0 < flower_days < 42:
                if 1.1 <= vpd <= 1.4:  # Perfect
                    vpd_optimal = True
                    observations.append((0.95, 0.18))
                elif 1.0 <= vpd <= 1.5:  # Good
                    observations.append((0.85, 0.25))

            # Late Flower: 1.2-1.5 kPa (drier to prevent mold)
            elif flower_days >= 42:
                if 1.3 <= vpd <= 1.5:  # Perfect
                    vpd_optimal = True
                    observations.append((0.95, 0.15))
                elif 1.2 <= vpd <= 1.6:  # Good
                    observations.append((0.85, 0.22))

            # If not optimal, reduce probability
            if not vpd_optimal:
                observations.append((0.25, 0.70))

        # Good CO2 levels
        if co2 is not None:
            # Enhanced CO2 (optimal for fast growth)
            if 1000 <= co2 <= 1400:
                observations.append((0.95, 0.20))
            # Good elevated CO2
            elif 800 <= co2 <= 1500:
                observations.append((0.85, 0.30))
            # Adequate ambient CO2
            elif 400 <= co2 <= 600:
                observations.append((0.60, 0.45))
            # Outside optimal range
            else:
                observations.append((0.25, 0.70))

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()
