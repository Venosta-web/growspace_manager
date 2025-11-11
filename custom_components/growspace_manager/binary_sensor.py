"""Environment monitoring with Bayesian sensors for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any
from datetime import date, datetime

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

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
        await self._async_update_probability()

    @callback
    def _handle_coordinator_update(self) -> None:
        """Handle coordinator update."""
        self.hass.async_create_task(self._async_update_probability())

    @callback
    def _async_sensor_changed(self, event) -> None:
        """Handle sensor state changes."""
        self.hass.async_create_task(self._async_update_probability())

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

    async def _async_update_probability(self) -> None:
        """Calculate Bayesian probability - implemented by subclasses."""
        raise NotImplementedError

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

    def __init__(self, coordinator, growspace_id, env_config) -> None:
        super().__init__(coordinator, growspace_id, env_config)
        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} Plants Under Stress"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_stress"
        self.prior = 0.15
        self.threshold = env_config.get("stress_threshold", 0.70)

    async def _async_update_probability(self) -> None:
        """Calculate stress probability using Bayesian inference."""
        temp = self._get_sensor_value(self.env_config["temperature_sensor"])
        humidity = self._get_sensor_value(self.env_config["humidity_sensor"])
        vpd = self._get_sensor_value(self.env_config["vpd_sensor"])
        co2 = self._get_sensor_value(self.env_config["co2_sensor"])
        stage_info = self._get_growth_stage_info()

        # Store current observations
        self._sensor_states = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "co2": co2,
            "veg_days": stage_info["veg_days"],
            "flower_days": stage_info["flower_days"],
        }

        # Calculate probability using Bayes theorem
        observations = []

        # Temperature observations
        if temp is not None:
            if temp is not None:
                # Extreme heat (severe stress)
                if temp > 32:
                    observations.append((0.98, 0.05))
                # High heat (moderate stress)
                elif temp > 30:
                    observations.append((0.85, 0.15))
                # Slightly warm (minor stress)
                elif temp > 28:
                    observations.append((0.65, 0.30))

                # Extreme cold (severe stress)
                elif temp < 15:
                    observations.append((0.95, 0.08))
                # Cold (moderate stress)
                elif temp < 18:
                    observations.append((0.80, 0.20))
        # VPD observations (stage-aware)
        if vpd is not None:
            veg_days = stage_info["veg_days"]
            flower_days = stage_info["flower_days"]

            if flower_days == 0 and veg_days < 14:
                if vpd < 0.3:  # Too humid
                    observations.append((0.85, 0.15))
                elif vpd < 0.4:  # Slightly low
                    observations.append((0.60, 0.30))
                elif vpd > 1.0:  # Too dry
                    observations.append((0.85, 0.15))
                elif vpd > 0.8:  # Slightly high
                    observations.append((0.60, 0.30))

            # Late Veg (14+ days) - Target: 0.8-1.2 kPa
            elif flower_days == 0 and veg_days >= 14:
                if vpd < 0.6:
                    observations.append((0.80, 0.18))
                elif vpd < 0.8:
                    observations.append((0.55, 0.35))
                elif vpd > 1.4:
                    observations.append((0.80, 0.18))
                elif vpd > 1.2:
                    observations.append((0.55, 0.35))

            # Early-Mid Flower (1-42 days) - Target: 1.0-1.5 kPa
            elif 0 < flower_days < 42:
                if vpd < 0.8:
                    observations.append((0.85, 0.15))
                elif vpd < 1.0:
                    observations.append((0.60, 0.30))
                elif vpd > 1.6:
                    observations.append((0.80, 0.20))
                elif vpd > 1.5:
                    observations.append((0.55, 0.35))

            # Late Flower (42+ days) - Target: 1.2-1.5 kPa (slightly drier)
            elif flower_days >= 42:
                if vpd < 1.0:
                    observations.append((0.90, 0.12))
                elif vpd < 1.2:
                    observations.append((0.65, 0.28))
                elif vpd > 1.6:
                    observations.append((0.75, 0.22))
                elif vpd > 1.5:
                    observations.append((0.50, 0.38))

        # Humidity observations
        if humidity is not None:
            if humidity < 35:
                observations.append((0.85, 0.20))  # Too dry
            elif humidity > 70:
                observations.append((0.90, 0.15))  # Too humid

        # CO2 observations
        if co2 is not None:
            if co2 < 400:
                observations.append((0.80, 0.25))  # Too low
            elif co2 > 1800:
                observations.append((0.75, 0.20))  # Too high

        self._probability = self._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()

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


class BayesianMoldRiskSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting mold risk in late flower."""

    def __init__(self, coordinator, growspace_id, env_config) -> None:
        super().__init__(coordinator, growspace_id, env_config)
        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} High Mold Risk"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_mold_risk"
        self.prior = 0.10
        self.threshold = env_config.get("mold_threshold", 0.75)

    async def _async_update_probability(self) -> None:
        """Calculate mold risk probability."""
        temp = self._get_sensor_value(self.env_config["temperature_sensor"])
        humidity = self._get_sensor_value(self.env_config["humidity_sensor"])
        vpd = self._get_sensor_value(self.env_config["vpd_sensor"])
        stage_info = self._get_growth_stage_info()
        flower_days = stage_info["flower_days"]

        # Check if fan is off (if configured)
        fan_entity = self.env_config.get("circulation_fan")
        fan_off = False
        if fan_entity:
            fan_state = self.hass.states.get(fan_entity)
            fan_off = fan_state and fan_state.state == "off"

        self._sensor_states = {
            "temperature": temp,
            "humidity": humidity,
            "vpd": vpd,
            "flower_days": flower_days,
            "fan_off": fan_off,
        }

        observations = []

        # Only relevant in late flower
        if flower_days >= 35:
            observations.append((0.99, 0.01))

            # High humidity
            if humidity is not None and humidity > 50:
                observations.append((0.95, 0.20))

            # Temperature in danger zone
            if temp is not None and 24 < temp < 28:
                observations.append((0.85, 0.30))

            # Low VPD
            if vpd is not None and vpd < 1.2:
                observations.append((0.90, 0.25))

            # Fan off
            if fan_off:
                observations.append((0.80, 0.15))

        self._probability = BayesianStressSensor._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()


class BayesianOptimalConditionsSensor(BayesianEnvironmentSensor):
    """Bayesian sensor for detecting optimal growing conditions."""

    def __init__(self, coordinator, growspace_id, env_config) -> None:
        super().__init__(coordinator, growspace_id, env_config)
        growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{growspace.name} Optimal Conditions"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_optimal"
        self.prior = 0.40
        self.threshold = 0.80

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

        self._probability = BayesianStressSensor._calculate_bayesian_probability(
            self.prior, observations
        )
        self.async_write_ha_state()
