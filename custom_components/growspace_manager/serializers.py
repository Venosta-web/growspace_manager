"""Serializers for the Growspace Manager integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .bayesian_data import VPD_STRESS_THRESHOLDS
from .const import (
    DEFAULT_FLOWER_EARLY_DAYS,
    DEFAULT_VEG_EARLY_DAYS,
    DOMAIN,
    PlantStage,
)
from .models import Growspace, Plant
from .utils import (
    calculate_days_since,
    calculate_plant_stage,
    days_to_week,
    format_date,
)

_LOGGER = logging.getLogger(__name__)


class GrowspaceSerializer:
    """Serializer for Growspace data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the serializer."""
        self.hass = hass

    def serialize_growspace(
        self, growspace: Growspace, plants: list[Plant]
    ) -> dict[str, Any]:
        """Build the full JSON payload for a single growspace."""
        # Calculate max stage days
        max_veg = max(
            (calculate_days_since(p.veg_start) for p in plants if p.veg_start),
            default=0,
        )
        max_flower = max(
            (calculate_days_since(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )
        max_dry = max(
            (calculate_days_since(p.dry_start) for p in plants if p.dry_start),
            default=0,
        )
        max_cure = max(
            (calculate_days_since(p.cure_start) for p in plants if p.cure_start),
            default=0,
        )

        # Calculate weeks from days
        veg_week = days_to_week(max_veg)
        flower_week = days_to_week(max_flower)

        biological_metrics = self._get_biological_metrics(
            growspace, max_veg, max_flower, max_dry, max_cure
        )

        # Get irrigation settings
        irrigation_options = growspace.irrigation_config
        irrigation_strategy_dict = (
            growspace.irrigation_strategy.to_dict()
            if growspace.irrigation_strategy
            else None
        )

        # Create grid representation (Detailed rich grid)
        grid = self._generate_rich_plant_grid(growspace, plants)

        # Determine growspace type
        gs_type = "normal"
        if growspace.id in ("mother", "clone", "dry", "cure"):
            gs_type = growspace.id

        # Get air exchange recommendation
        air_exchange = (
            self.hass.data.get(DOMAIN, {})
            .get("air_exchange_recommendations", {})
            .get(growspace.id)
        )

        # Build complete dict
        data = {
            "growspace_id": growspace.id,
            "name": growspace.name,
            "type": gs_type,
            "rows": growspace.rows,
            "plants_per_row": growspace.plants_per_row,
            "total_plants": len(plants),
            "notification_target": growspace.notification_target,
            "max_veg_days": max_veg,
            "max_flower_days": max_flower,
            "veg_week": veg_week,
            "flower_week": flower_week,
            "max_stage_summary": f"Veg: {max_veg}d (W{veg_week}), Flower: {max_flower}d (W{flower_week})",
            "irrigation_config": irrigation_options,
            "irrigation_strategy": irrigation_strategy_dict,
            "grid": grid,
            "air_exchange": air_exchange,
            **biological_metrics,
        }

        # Add environment attributes
        data.update(self._get_environment_attributes(growspace))

        return data

    def _generate_rich_plant_grid(
        self, growspace: Growspace, plants: list[Plant]
    ) -> dict[str, dict[str, Any] | None]:
        """Generate the detailed plant grid representation."""
        registry = er.async_get(self.hass)
        grid: dict[str, dict[str, Any] | None] = {}
        for row in range(1, int(growspace.rows) + 1):
            for col in range(1, int(growspace.plants_per_row) + 1):
                grid[f"position_{row}_{col}"] = None

        # Fill grid with plants
        for plant in plants:
            row_i = int(plant.row)
            col_i = int(plant.col)
            position_key = f"position_{row_i}_{col_i}"

            # Look up safe entity_id
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{DOMAIN}_{plant.plant_id}"
            )

            grid[position_key] = {
                "plant_id": plant.plant_id,
                "entity_id": entity_id,  # Stable entity ID
                "strain": plant.strain,
                "phenotype": plant.phenotype,
                # Days in stage
                "seedling_days": self.calculate_days_in_stage(plant, "seedling"),
                "mother_days": self.calculate_days_in_stage(plant, "mother"),
                "clone_days": self.calculate_days_in_stage(plant, "clone"),
                "veg_days": self.calculate_days_in_stage(plant, "veg"),
                "flower_days": self.calculate_days_in_stage(plant, "flower"),
                "dry_days": self.calculate_days_in_stage(plant, "dry"),
                "cure_days": self.calculate_days_in_stage(plant, "cure"),
                # Start dates
                "seedling_start": format_date(plant.seedling_start),
                "mother_start": format_date(plant.mother_start),
                "clone_start": format_date(plant.clone_start),
                "veg_start": format_date(plant.veg_start),
                "flower_start": format_date(plant.flower_start),
                "dry_start": format_date(plant.dry_start),
                "cure_start": format_date(plant.cure_start),
                # Location & Stage
                "row": row_i,
                "col": col_i,
                "position": f"({row_i},{col_i})",
                "stage": calculate_plant_stage(plant),
            }
        return grid

    def calculate_days_in_stage(self, plant: Plant, stage: str) -> int:
        """Calculate how many days a plant has been in a specific growth stage."""
        start_date = getattr(plant, f"{stage}_start", None)

        end_date = None
        if stage in {PlantStage.SEEDLING, PlantStage.CLONE}:
            end_date = getattr(plant, "veg_start", None)
        elif stage == PlantStage.VEG:
            end_date = getattr(plant, "flower_start", None)
        elif stage == PlantStage.FLOWER:
            end_date = getattr(plant, "dry_start", None)
        elif stage == PlantStage.DRY:
            end_date = getattr(plant, "cure_start", None)

        return calculate_days_since(start_date, end_date)

    def _get_biological_metrics(
        self,
        growspace: Growspace,
        max_veg: int,
        max_flower: int,
        max_dry: int,
        max_cure: int,
    ) -> dict[str, Any]:
        """Calculate biological target metrics for the growspace."""
        granular_stage = self._determine_granular_stage(
            max_veg, max_flower, max_dry, max_cure
        )
        is_day = self._determine_is_day(growspace)
        day_key = "day" if is_day else "night"

        threshold_data = VPD_STRESS_THRESHOLDS.get(
            granular_stage, VPD_STRESS_THRESHOLDS["veg_early"]
        )
        cycle_data = threshold_data.get(day_key, threshold_data["day"])

        target_min, target_max = cycle_data.get("mild", (0.8, 1.2))
        danger_min, danger_max = cycle_data.get("stress", (0.6, 1.4))

        vpd_status = "unknown"
        vpd_sensor_id = growspace.environment_config.get("vpd_sensor")

        if vpd_sensor_id:
            current_vpd = self._get_sensor_value(vpd_sensor_id)
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
        }

    def _determine_granular_stage(
        self, max_veg: int, max_flower: int, max_dry: int, max_cure: int
    ) -> str:
        """Determine granular growth stage based on days."""
        if max_cure > 0:
            return "cure"
        if max_dry > 0:
            return "dry"
        if max_flower > 0:
            if max_flower <= DEFAULT_FLOWER_EARLY_DAYS:
                return "flower_early"
            if max_flower <= (DEFAULT_FLOWER_EARLY_DAYS + 21):
                return "flower_mid"
            return "flower_late"
        if max_veg > 0:
            if max_veg > 0 and max_veg <= DEFAULT_VEG_EARLY_DAYS:
                return "veg_early"
            return "veg_late"
        return "veg_early"

    def _determine_is_day(self, growspace: Growspace) -> bool:
        """Determine if it is currently day or night in the growspace."""
        light_sensor = growspace.environment_config.get("light_sensor")
        if light_sensor:
            light_state = self.hass.states.get(light_sensor)
            if light_state and light_state.state not in (
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            ):
                if light_state.state == STATE_ON:
                    return True
                if light_state.state == "off":
                    return False
                try:
                    return float(light_state.state) > 0
                except (ValueError, TypeError):
                    pass
        return True

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

    def _get_environment_attributes(self, growspace: Growspace) -> dict[str, Any]:
        """Get environment-related attributes."""
        attributes = {}
        if growspace.environment_config:
            env_config = growspace.environment_config

            # Dehumidifier
            dehumidifier_entity = env_config.get("dehumidifier_entity")
            if dehumidifier_entity:
                state_obj = self.hass.states.get(dehumidifier_entity)
                attributes["dehumidifier_entity"] = dehumidifier_entity
                attributes["dehumidifier_state"] = (
                    state_obj.state if state_obj else None
                )
                if state_obj:
                    attributes["dehumidifier_humidity"] = state_obj.attributes.get(
                        "humidity"
                    )
                    attributes["dehumidifier_current_humidity"] = (
                        state_obj.attributes.get("current_humidity")
                    )
                    attributes["dehumidifier_mode"] = state_obj.attributes.get("mode")
                    attributes["dehumidifier_control_enabled"] = env_config.get(
                        "control_dehumidifier", False
                    )

            # Exhaust Sensor
            exhaust_entity = env_config.get("exhaust_sensor")
            if exhaust_entity:
                state_obj = self.hass.states.get(exhaust_entity)
                attributes["exhaust_entity"] = exhaust_entity
                attributes["exhaust_state"] = state_obj.state if state_obj else None

            # Humidifier Sensor
            humidifier_entity = env_config.get("humidifier_sensor")
            if humidifier_entity:
                state_obj = self.hass.states.get(humidifier_entity)
                attributes["humidifier_entity"] = humidifier_entity
                attributes["humidifier_state"] = state_obj.state if state_obj else None

            # VPD Sensor
            vpd_entity = env_config.get("vpd_sensor")
            if vpd_entity:
                state_obj = self.hass.states.get(vpd_entity)
                attributes["vpd_sensor"] = vpd_entity
                attributes["vpd"] = state_obj.state if state_obj else None

            # Soil Moisture Sensor
            soil_moisture_entity = env_config.get("soil_moisture_sensor")
            if soil_moisture_entity:
                state_obj = self.hass.states.get(soil_moisture_entity)
                attributes["soil_moisture_sensor"] = soil_moisture_entity
                attributes["soil_moisture_value"] = (
                    state_obj.state if state_obj else None
                )

            # Map other simple keys that don't need state lookups or were already mapped
            keys_to_map = {
                "temperature_sensor": "temperature_sensor",
                "humidity_sensor": "humidity_sensor",
                "co2_sensor": "co2_sensor",
                "circulation_fan_entity": "circulation_fan_entity",
                "light_sensor": "light_sensor",
            }

            for config_key, output_key in keys_to_map.items():
                if val := env_config.get(config_key):
                    attributes[output_key] = val

        return attributes
