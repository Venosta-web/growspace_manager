"""Serializers for the Growspace Manager integration."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_LIGHT_SENSOR,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    DOMAIN,
    PlantStage,
)
from homeassistant.util import slugify
from .environment_analyzer import EnvironmentAnalyzer
from .models import Growspace, Plant
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
        # We can't easily inject coordinator here because serializer is often initialized
        # by the coordinator itself or before it.
        # But EnvironmentAnalyzer requires a coordinator.
        # This is a circular dependency risk or just initialization order issue.
        # However, EnvironmentAnalyzer only needs coordinator for recommendations in the OLD code.
        # But my NEW calculate_biological_metrics code in EnvironmentAnalyzer
        # DOES NOT use self.coordinator. It takes growspace as argument.
        # So I can initialize it with None for coordinator if I only use that method?
        # Or better, the Serializer shouldn't own the Analyzer, the *Coordinator* should.
        # BUT the serializer methods take `growspace` and `plants`.

        # Let's instantiate it with just hass for now, but EnvironmentAnalyzer constructor
        # expects coordinator.
        # Let's check EnvironmentAnalyzer.__init__ signature again.
        # def __init__(self, hass: HomeAssistant, coordinator: GrowspaceCoordinator) -> None:

        # If I change the Serializer to accept an analyzer instance?
        # Or if I just instantiate it?

        # Ideally, `GrowspaceCoordinator` holds `self.serializer` AND `self.environment_analyzer`.
        # And when it calls `self.serializer.serialize_growspace(...)`, it could pass the analyzer?
        # Or `GrowspaceSerializer` could use `EnvironmentAnalyzer` as a helper.

        # Given the constraint of minimal changes to architecture:
        # I will instantiate EnvironmentAnalyzer with None for coordinator if possible, or Mock?
        # No, that's hacky.

        # Better approach: Pass the analyzer logic as a dependency or static method?
        # The new methods I added to EnvironmentAnalyzer DO NOT depend on `self.coordinator`.
        # `calculate_biological_metrics`, `determine_granular_stage`, `determine_is_day`
        # only use `growspace` or pure logic.

        # So I can make them static? Or just separate them?
        # No, `determine_is_day` uses `self.hass`.

        # So I need `hass`.
        # I will modify Serializer init to take an optional analyzer or just create one with None coordinator
        # if the coordinator isn't used for those specific methods.
        # But strictly speaking, type checking will fail if I pass None.
        pass

    def serialize_growspace(
        self, growspace: Growspace, plants: list[Plant], analyzer: EnvironmentAnalyzer
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

        # DELEGATE TO ANALYZER
        biological_metrics = analyzer.calculate_biological_metrics(
            growspace, max_veg, max_flower, max_dry, max_cure
        )

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
        # Logic duplicated/simplified from coordinator._guess_overview_entity_id
        # Ideally we use the registry lookup
        unique_id = generate_growspace_overview_unique_id(growspace.id)
        registry = er.async_get(self.hass)
        overview_entity_id = registry.async_get_entity_id("sensor", DOMAIN, unique_id)

        # Fallback for special growspaces if standard lookup fails (legacy support)
        if not overview_entity_id:
            # Just provide a best guess formatted ID which frontend might use OR null
            # If null, frontend GrowspaceAdapter will handle it (loading/unknown)
            # But let's try to match the slug pattern
            from homeassistant.util import slugify

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

        row_i = int(plant.row)
        col_i = int(plant.col)

        return {
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

    def _get_environment_attributes(self, growspace: Growspace) -> dict[str, Any]:  # noqa: C901
        """Get environment-related attributes."""
        attributes = {}
        if growspace.environment_config:
            env_config = growspace.environment_config

            # Dehumidifier
            dehumidifier_entity = env_config.dehumidifier_entity
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

            # Exhaust Sensor
            exhaust_entity = env_config.exhaust_fan_entity
            if exhaust_entity:
                state_obj = self.hass.states.get(exhaust_entity)
                attributes["exhaust_entity"] = exhaust_entity
                attributes["exhaust_state"] = state_obj.state if state_obj else None

            # Humidifier Sensor
            humidifier_entity = env_config.humidifier_entity
            if humidifier_entity:
                state_obj = self.hass.states.get(humidifier_entity)
                attributes["humidifier_entity"] = humidifier_entity
                attributes["humidifier_state"] = state_obj.state if state_obj else None

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

            # Circulation fan
            circulation_fan_entity = env_config.circulation_fan_entity
            if circulation_fan_entity:
                state_obj = self.hass.states.get(circulation_fan_entity)
                attributes[CONF_CIRCULATION_FAN_ENTITY] = circulation_fan_entity
                attributes["circulation_fan_state"] = (
                    state_obj.state if state_obj else None
                )

        return attributes
