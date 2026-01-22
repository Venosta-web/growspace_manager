"""Serialization logic for Growspace Manager data structures."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.util import slugify

from .const import (
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_EXHAUST_ENTITY,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    DOMAIN,
    PlantStage,
)
from .models import Growspace, Plant

# Import centralized types for better type safety
from .utils import (
    calculate_days_since,
    calculate_plant_stage,
    days_to_week,
    format_date,
    generate_growspace_overview_unique_id,
)

_LOGGER = logging.getLogger(__name__)


class GrowspaceSerializer:
    """Serializer for Growspace data."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the serializer."""
        self.hass = hass

    def _ensure_int(self, value: Any) -> int:
        """Safely convert value to int, handling '30.0' strings."""
        try:
            return int(value)
        except (ValueError, TypeError):
            try:
                return int(float(value))
            except (ValueError, TypeError):
                return 0

    def deserialize_plants(self, raw_plants: dict[str, Any]) -> dict[str, Plant]:
        """Deserialize plants from raw data."""
        plants: dict[str, Plant] = {}
        for pid, pdata in raw_plants.items():
            try:
                if isinstance(pdata, dict):
                    # Sanitize integer fields
                    if "row" in pdata:
                        pdata["row"] = self._ensure_int(pdata["row"])
                    if "col" in pdata:
                        pdata["col"] = self._ensure_int(pdata["col"])

                    plants[pid] = Plant.from_dict(pdata)
                elif isinstance(pdata, Plant):
                    plants[pid] = pdata
                else:
                    self._raise_invalid_data_type(pid, pdata, "plant")
            except Exception:
                _LOGGER.exception("Failed to load plant %s", pid)
        return plants

    def deserialize_growspaces(
        self, raw_growspaces: dict[str, Any]
    ) -> dict[str, Growspace]:
        """Deserialize growspaces from raw data."""
        growspaces: dict[str, Growspace] = {}
        for gid, gdata in raw_growspaces.items():
            try:
                if isinstance(gdata, dict):
                    # Sanitize integer fields
                    for field in ["rows", "plants_per_row"]:
                        if field in gdata:
                            gdata[field] = self._ensure_int(gdata[field])

                    # Data Migration: Fix legacy irrigation schedule format
                    if "irrigation_config" in gdata:
                        gdata["irrigation_config"] = (
                            self._deserialize_irrigation_config(
                                gdata["irrigation_config"]
                            )
                        )

                    # Sanitize irrigation_strategy integers if present
                    self._sanitize_irrigation_strategy(gdata)

                    growspaces[gid] = Growspace.from_dict(gdata)
                elif isinstance(gdata, Growspace):
                    growspaces[gid] = gdata
                else:
                    self._raise_invalid_data_type(gid, gdata, "growspace")
            except Exception:
                _LOGGER.exception("Failed to load growspace %s", gid)
        return growspaces

    def _deserialize_irrigation_config(
        self, irr_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Deserialize and sanitize irrigation configuration."""
        # Sanitize config integers
        if "veg_day_hours" in irr_config:
            irr_config["veg_day_hours"] = self._ensure_int(irr_config["veg_day_hours"])

        for list_key in ["irrigation_times", "drain_times"]:
            if list_key in irr_config and isinstance(irr_config[list_key], list):
                new_list = []
                for item in irr_config[list_key]:
                    if isinstance(item, dict):
                        # Migrate 'time' -> 'start_time'
                        if "time" in item and "start_time" not in item:
                            item["start_time"] = item.pop("time")

                        # Migrate 'duration' -> 'duration_seconds'
                        if "duration" in item and "duration_seconds" not in item:
                            item["duration_seconds"] = self._ensure_int(
                                item.pop("duration")
                            )

                        # Ensure duration_seconds is int
                        if "duration_seconds" in item:
                            item["duration_seconds"] = self._ensure_int(
                                item["duration_seconds"]
                            )

                    new_list.append(item)
                irr_config[list_key] = new_list
        return irr_config

    def _sanitize_irrigation_strategy(self, gdata: dict[str, Any]) -> None:
        """Sanitize irrigation strategy integers."""
        if "irrigation_strategy" in gdata and isinstance(
            gdata["irrigation_strategy"], dict
        ):
            strat = gdata["irrigation_strategy"]
            int_fields = [
                "p0_duration_minutes",
                "p2_stop_before_lights_off_minutes",
                "shot_duration_seconds",
                "shot_interval_minutes",
            ]
            for f in int_fields:
                if f in strat:
                    strat[f] = self._ensure_int(strat[f])

    def _raise_invalid_data_type(
        self, item_id: str, item_data: Any, item_type: str
    ) -> None:
        """Raise TypeError for invalid data."""
        raise TypeError(
            f"Invalid data type for {item_type} {item_id}: {type(item_data)}"
        )

    def serialize_growspace(
        self,
        growspace: Growspace,
        plants: list[Plant],
        biological_metrics: dict[str, Any],
        max_veg_days: int = 0,
        max_flower_days: int = 0,
        max_dry_days: int = 0,
        max_cure_days: int = 0,
    ) -> dict[str, Any]:
        """Build the full JSON payload for a single growspace."""
        # Calculate weeks from days
        veg_week = days_to_week(max_veg_days)
        flower_week = days_to_week(max_flower_days)

        # Get irrigation settings
        # Explicit serialization to ensure all keys are present for frontend
        irrigation_config = growspace.irrigation_config
        irrigation_options = {
            "irrigation_pump_entity": irrigation_config.irrigation_pump_entity,
            "drain_pump_entity": irrigation_config.drain_pump_entity,
            "irrigation_duration": irrigation_config.irrigation_duration,
            "drain_duration": irrigation_config.drain_duration,
            "irrigation_times": irrigation_config.irrigation_times,
            "drain_times": irrigation_config.drain_times,
            "veg_day_hours": irrigation_config.veg_day_hours,
        }

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

        # Determine overview entity ID
        unique_id = generate_growspace_overview_unique_id(growspace.id)
        registry = er.async_get(self.hass)
        overview_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)

        # Fallback for special growspaces if standard lookup fails (legacy support)
        if not overview_entity_id:
            slug = slugify(growspace.name or growspace.id)
            overview_entity_id = f"sensor.{slug}"

        # Build complete dict
        data = {
            "growspace_id": growspace.id,
            "overview_entity_id": overview_entity_id,
            "name": growspace.name,
            "type": gs_type,
            "rows": growspace.rows,
            "plants_per_row": growspace.plants_per_row,
            "total_plants": len(plants),
            "notification_target": growspace.notification_target,
            "max_veg_days": max_veg_days,
            "max_flower_days": max_flower_days,
            "veg_week": veg_week,
            "flower_week": flower_week,
            "max_stage_summary": f"Veg: {max_veg_days}d (W{veg_week}), Flower: {max_flower_days}d (W{flower_week})",
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

            grid[position_key] = self.serialize_plant(plant, entity_id=entity_id)
        return grid

    def serialize_plant(
        self, plant: Plant, entity_id: str | None = None
    ) -> dict[str, Any]:
        """Serialize a single plant with all calculated fields."""
        if not entity_id:
            registry = er.async_get(self.hass)
            entity_id = registry.async_get_entity_id(
                "sensor", DOMAIN, f"{DOMAIN}_{plant.plant_id}"
            )

        return {
            "plant_id": plant.plant_id,
            "growspace_id": plant.growspace_id,  # Include for frontend cache updates
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
            "row": int(plant.row),
            "col": int(plant.col),
            "position": f"({int(plant.row)},{int(plant.col)})",
            "stage": calculate_plant_stage(plant),
            # Watering & Training
            "last_watered": format_date(plant.last_watered),
            "last_trained": format_date(plant.last_trained),
            "last_training_technique": plant.last_training_technique,
            "last_ipm": format_date(plant.last_ipm),
            "last_ipm_type": plant.last_ipm_type,
            "days_since_last_watering": plant.get_days_since_watering(),
        }

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

    def _parse_tank_level(self, state_value: str | None) -> float | None:
        """Parse tank level from sensor state.

        Handles formats like:
        - "50.0 %"
        - "50,0 %" (European format)
        - "50" (plain number)
        """
        if not state_value:
            return None
        try:
            # Remove % sign and whitespace
            cleaned = state_value.replace("%", "").strip()
            # Replace European comma with period
            cleaned = cleaned.replace(",", ".")
            return float(cleaned)
        except (ValueError, TypeError, AttributeError):
            # If it's already a number or conversion failed
            try:
                return float(state_value)
            except (ValueError, TypeError):
                return None

    def _get_environment_attributes(self, growspace: Growspace) -> dict[str, Any]:
        """Get environment-related attributes."""
        attributes: dict[str, Any] = {}
        if growspace.environment_config:
            env_config = growspace.environment_config

            # Dehumidifier
            dehumidifier_entity = env_config.dehumidifier_entity
            # Expose list
            attributes[CONF_DEHUMIDIFIER_ENTITIES] = env_config.dehumidifier_entities

            if dehumidifier_entity:
                state_obj = self.hass.states.get(dehumidifier_entity)
                attributes[CONF_DEHUMIDIFIER_ENTITY] = dehumidifier_entity
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
                    attributes["dehumidifier_control_enabled"] = (
                        env_config.control_dehumidifier
                    )
                    attributes["dehumidifier_thresholds"] = (
                        env_config.dehumidifier_thresholds
                    )

            # Exhaust Sensor
            exhaust_entity = env_config.exhaust_fan_entity
            attributes[CONF_EXHAUST_FAN_ENTITIES] = env_config.exhaust_fan_entities

            if exhaust_entity:
                state_obj = self.hass.states.get(exhaust_entity)
                attributes[CONF_EXHAUST_ENTITY] = exhaust_entity
                attributes["exhaust_state"] = state_obj.state if state_obj else None

            # Humidifier Sensor
            humidifier_entity = env_config.humidifier_entity
            attributes[CONF_HUMIDIFIER_ENTITIES] = env_config.humidifier_entities

            if humidifier_entity:
                state_obj = self.hass.states.get(humidifier_entity)
                attributes[CONF_HUMIDIFIER_ENTITY] = humidifier_entity
                attributes["humidifier_state"] = state_obj.state if state_obj else None

            # Circulation Fan
            circulation_fan_entity = env_config.circulation_fan_entity
            attributes[CONF_CIRCULATION_FAN_ENTITIES] = (
                env_config.circulation_fan_entities
            )

            if circulation_fan_entity:
                state_obj = self.hass.states.get(circulation_fan_entity)
                attributes[CONF_CIRCULATION_FAN_ENTITY] = circulation_fan_entity
                attributes["circulation_fan_state"] = (
                    state_obj.state if state_obj else None
                )

            # VPD Sensor
            vpd_entity = env_config.vpd_sensor
            if vpd_entity:
                state_obj = self.hass.states.get(vpd_entity)
                attributes[CONF_VPD_SENSOR] = vpd_entity
                attributes["vpd"] = state_obj.state if state_obj else None

            # Soil Moisture Sensor
            soil_moisture_entity = env_config.soil_moisture_sensor
            if soil_moisture_entity:
                state_obj = self.hass.states.get(soil_moisture_entity)
                attributes["soil_moisture_sensor"] = soil_moisture_entity
                attributes["soil_moisture_value"] = (
                    state_obj.state if state_obj else None
                )

            # Light Sensors
            attributes[CONF_LIGHT_SENSORS] = env_config.light_sensors

            # Map other simple keys
            keys_to_map = [
                CONF_TEMP_SENSOR,
                CONF_HUMIDITY_SENSOR,
                CONF_CO2_SENSOR,
                CONF_LIGHT_SENSOR,
            ]

            for key in keys_to_map:
                if val := getattr(env_config, key):
                    attributes[key] = val

            # Add light_sensors list specifically
            attributes["light_sensors"] = env_config.light_sensors

            # Circulation fan
            circulation_fan_entity = env_config.circulation_fan_entity
            attributes["circulation_fan_entities"] = env_config.circulation_fan_entities

            if circulation_fan_entity:
                state_obj = self.hass.states.get(circulation_fan_entity)
                attributes[CONF_CIRCULATION_FAN_ENTITY] = circulation_fan_entity
                attributes["circulation_fan_state"] = (
                    state_obj.state if state_obj else None
                )

            # Irrigation Tanks
            if env_config.irrigation_tanks:
                tanks_data = []
                for tank in env_config.irrigation_tanks:
                    state_obj = self.hass.states.get(tank.sensor_entity)
                    fill_level = (
                        self._parse_tank_level(state_obj.state) if state_obj else None
                    )
                    tanks_data.append(
                        {
                            "sensor_entity": tank.sensor_entity,
                            "name": tank.name,
                            "warning_level": tank.warning_level,
                            "fill_level": fill_level,
                            "is_warning": fill_level is not None
                            and fill_level <= tank.warning_level,
                        }
                    )
                attributes["irrigation_tanks"] = tanks_data
            else:
                attributes["irrigation_tanks"] = []

        return attributes
