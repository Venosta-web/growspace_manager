"""Growspace view model builder for frontend consumption."""

from __future__ import annotations

import contextlib
from datetime import datetime, timedelta
import logging
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
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
    CONF_HUMIDITY_SENSORS,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_TEMP_SENSOR,
    CONF_TEMP_SENSORS,
    CONF_VPD_SENSOR,
    CONF_VPD_SENSORS,
    DOMAIN,
)
from custom_components.growspace_manager.utils import days_to_week
from homeassistant.util import dt as dt_util

from .entity_queries import EntityQueries
from .plant_view_model import PlantViewModelBuilder

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Growspace, Plant
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_7_DAYS = timedelta(days=7)


def _compute_tank_water_summaries(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute compact 7-day water summaries from the full event list.

    Returns two compact structures suitable for entity attributes:
    - ``recent_refills``: up to 20 refill events within the last 7 days.
    - ``daily_7d``: per-day consumed/refilled totals for the last 7 days.
    """
    now = dt_util.utcnow()
    window_start = now - _7_DAYS

    refills: list[dict[str, Any]] = []
    daily: dict[str, dict[str, float]] = {}

    for ev in events:
        try:
            ts_str: str = ev["timestamp"]
            ts = datetime.fromisoformat(ts_str)
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=dt_util.UTC)
        except (KeyError, ValueError):
            continue

        if ts < window_start:
            continue

        date_key = ts.strftime("%Y-%m-%d")
        if date_key not in daily:
            daily[date_key] = {"consumed": 0.0, "refilled": 0.0}

        ev_type = ev.get("event_type", "")
        liters = float(ev.get("liters", 0.0))

        if ev_type == "consumption":
            daily[date_key]["consumed"] += liters
        elif ev_type == "refill":
            daily[date_key]["refilled"] += liters
            refills.append(ev)

    return {
        "recent_refills": refills[-20:],
        "daily_7d": [
            {
                "date": k,
                "consumed": round(v["consumed"], 3),
                "refilled": round(v["refilled"], 3),
            }
            for k, v in sorted(daily.items())
        ],
    }


class GrowspaceViewModelBuilder:
    """Builds rich growspace payloads for frontend consumption."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the growspace view model builder.

        Args:
            hass: Home Assistant instance.
        """
        self.hass = hass
        self.entity_queries = EntityQueries(hass)
        self.plant_builder = PlantViewModelBuilder(hass)

    def build(
        self,
        growspace: Growspace,
        plants: list[Plant],
        biological_metrics: dict[str, Any],
        max_veg_days: int = 0,
        max_flower_days: int = 0,
        max_dry_days: int = 0,
        max_cure_days: int = 0,
        active_events: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build complete growspace payload with all calculated fields.

        Args:
            growspace: The growspace to serialize.
            plants: List of plants in this growspace.
            biological_metrics: Pre-calculated metrics (strain analytics, etc.).
            max_veg_days: Maximum days any plant has been in veg.
            max_flower_days: Maximum days any plant has been in flower.
            max_dry_days: Maximum days any plant has been drying.
            max_cure_days: Maximum days any plant has been curing.
            active_events: Active irrigation/drainage events for animation.

        Returns:
            Dictionary containing all growspace data for frontend.
        """
        # Calculate weeks from days
        veg_week = days_to_week(max_veg_days)
        flower_week = days_to_week(max_flower_days)
        dry_week = days_to_week(max_dry_days)
        cure_week = days_to_week(max_cure_days)

        # Get irrigation settings
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

        # Create grid representation with entity data
        grid = self._build_rich_plant_grid(growspace, plants)

        # Determine growspace type
        gs_type = "normal"
        if growspace.id in ("mother", "clone", "dry", "cure"):
            gs_type = growspace.id

        # Get air exchange recommendation from coordinator data
        air_exchange = (
            self.hass.data.get(DOMAIN, {})
            .get("air_exchange_recommendations", {})
            .get(growspace.id)
        )

        # Look up overview entity ID
        overview_entity_id = self.entity_queries.lookup_overview_entity_id(growspace.id)

        # Build complete dict
        data = {
            "growspace_id": growspace.id,
            "overview_entity_id": overview_entity_id,
            "name": growspace.name,
            "type": gs_type,
            "rows": growspace.rows,
            "plants_per_row": growspace.plants_per_row,
            "total_plants": len(plants),
            "dimensions": growspace.dimensions,
            "notification_target": growspace.notification_target,
            "max_veg_days": max_veg_days,
            "max_flower_days": max_flower_days,
            "max_dry_days": max_dry_days,
            "max_cure_days": max_cure_days,
            "veg_week": veg_week,
            "flower_week": flower_week,
            "dry_week": dry_week,
            "cure_week": cure_week,
            "max_stage_summary": (
                f"Cure: {max_cure_days}d (W{cure_week})"
                if max_cure_days > 0
                else f"Dry: {max_dry_days}d (W{dry_week})"
                if max_dry_days > 0
                else f"Veg: {max_veg_days}d (W{veg_week}), Flower: {max_flower_days}d (W{flower_week})"
            ),
            "irrigation_config": irrigation_options,
            "irrigation_strategy": irrigation_strategy_dict,
            "drain_config": {
                "enabled": growspace.drain_config.enabled,
                "max_ec_delta": growspace.drain_config.max_ec_delta,
                "target_runoff_percent": growspace.drain_config.target_runoff_percent,
                "readings": [
                    {
                        "timestamp": r.timestamp,
                        "feed_ec": r.feed_ec,
                        "drain_ec": r.drain_ec,
                        "drain_volume_ml": r.drain_volume_ml,
                        "feed_volume_ml": r.feed_volume_ml,
                    }
                    for r in growspace.drain_config.readings
                ],
            }
            if getattr(growspace, "drain_config", None)
            else None,
            "energy_tracking": {
                "cycle_start_date": growspace.energy_tracking.cycle_start_date,
                "cycle_start_kwh": growspace.energy_tracking.cycle_start_kwh,
            }
            if getattr(growspace, "energy_tracking", None)
            else None,
            "water_usage": {
                "total_liters": growspace.water_usage.total_liters,
                "cycle_start_date": growspace.water_usage.cycle_start_date,
                "daily_readings": growspace.water_usage.daily_readings,
            }
            if getattr(growspace, "water_usage", None)
            else None,
            "grid": grid,
            "air_exchange": air_exchange,
            "sensor_types": self._get_sensor_types(growspace),
            **(biological_metrics or {}),
        }

        # Add environment attributes
        data.update(
            self._get_environment_attributes(growspace, active_events=active_events)
        )

        return data

    def _build_rich_plant_grid(
        self, growspace: Growspace, plants: list[Plant]
    ) -> dict[str, dict[str, Any] | None]:
        """Generate the detailed plant grid representation with entity data.

        Args:
            growspace: The growspace to build grid for.
            plants: List of plants in this growspace.

        Returns:
            Dictionary mapping position keys to rich plant data.
        """
        grid: dict[str, dict[str, Any] | None] = {}

        # Initialize all positions as empty
        for row in range(1, int(growspace.rows) + 1):
            for col in range(1, int(growspace.plants_per_row) + 1):
                grid[f"position_{row}_{col}"] = None

        # Fill grid with plant data
        for plant in plants:
            row_i = int(plant.row)
            col_i = int(plant.col)
            position_key = f"position_{row_i}_{col_i}"

            # Look up entity_id for this plant
            entity_id = self.entity_queries.lookup_plant_entity_id(plant.plant_id)

            # Build rich plant payload
            grid[position_key] = self.plant_builder.build(plant, entity_id=entity_id)

        return grid

    def _get_sensor_types(self, growspace: Growspace) -> dict[str, str]:
        """Map entity IDs to their sensor types for frontend heuristics.

        Args:
            growspace: The growspace to get sensor types for.

        Returns:
            Dictionary mapping entity IDs to sensor type strings.
        """
        sensor_types: dict[str, str] = {}
        if not growspace.environment_config:
            return sensor_types

        env = growspace.environment_config

        # Temperature
        for eid in env.temperature_sensors:
            sensor_types[eid] = "temperature"
        if env.temperature_sensor and env.temperature_sensor not in sensor_types:
            sensor_types[env.temperature_sensor] = "temperature"

        # Humidity
        for eid in env.humidity_sensors:
            sensor_types[eid] = "humidity"
        if env.humidity_sensor and env.humidity_sensor not in sensor_types:
            sensor_types[env.humidity_sensor] = "humidity"

        # VPD
        for eid in env.vpd_sensors:
            sensor_types[eid] = "vpd"
        if env.vpd_sensor and env.vpd_sensor not in sensor_types:
            sensor_types[env.vpd_sensor] = "vpd"

        # Light
        for eid in env.light_sensors:
            sensor_types[eid] = "light"

        # CO2
        if env.co2_sensor:
            sensor_types[env.co2_sensor] = "co2"

        # Soil Moisture
        if env.soil_moisture_sensor:
            sensor_types[env.soil_moisture_sensor] = "soil_moisture"

        # Actuators
        for eid in env.exhaust_fan_entities:
            sensor_types[eid] = "exhaust"
        for eid in env.circulation_fan_entities:
            sensor_types[eid] = "circulation"
        for eid in env.humidifier_entities:
            sensor_types[eid] = "humidifier"
        for eid in env.dehumidifier_entities:
            sensor_types[eid] = "dehumidifier"

        # Irrigation
        if growspace.irrigation_config:
            irr = growspace.irrigation_config
            if irr.irrigation_pump_entity:
                sensor_types[irr.irrigation_pump_entity] = "irrigation_pump"
            if irr.drain_pump_entity:
                sensor_types[irr.drain_pump_entity] = "drain_pump"

        # Irrigation Tanks
        if env.irrigation_tanks:
            for tank in env.irrigation_tanks:
                if tank.sensor_entity:
                    sensor_types[tank.sensor_entity] = "irrigation_tank"

        return sensor_types

    def _get_environment_attributes(
        self,
        growspace: Growspace,
        active_events: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Get environment-related attributes with current sensor states.

        Args:
            growspace: The growspace to get environment data for.
            active_events: Active irrigation/drainage events.

        Returns:
            Dictionary of environment attributes.
        """
        attributes: dict[str, Any] = {}
        if not growspace.environment_config:
            return attributes

        env_config = growspace.environment_config

        # Dehumidifier
        dehumidifier_entity = env_config.dehumidifier_entity
        attributes[CONF_DEHUMIDIFIER_ENTITIES] = env_config.dehumidifier_entities

        if dehumidifier_entity:
            state_obj = self.hass.states.get(dehumidifier_entity)
            attributes[CONF_DEHUMIDIFIER_ENTITY] = dehumidifier_entity
            attributes["dehumidifier_state"] = state_obj.state if state_obj else None
            if state_obj:
                attributes["dehumidifier_humidity"] = state_obj.attributes.get(
                    "humidity"
                )
                attributes["dehumidifier_current_humidity"] = state_obj.attributes.get(
                    "current_humidity"
                )
                attributes["dehumidifier_mode"] = state_obj.attributes.get("mode")
                attributes["dehumidifier_control_enabled"] = (
                    env_config.control_dehumidifier
                )
                attributes["dehumidifier_thresholds"] = (
                    env_config.dehumidifier_thresholds
                )

        # Exhaust Fan
        exhaust_entity = env_config.exhaust_fan_entity
        attributes[CONF_EXHAUST_FAN_ENTITIES] = env_config.exhaust_fan_entities

        if exhaust_entity:
            state_obj = self.hass.states.get(exhaust_entity)
            attributes[CONF_EXHAUST_ENTITY] = exhaust_entity
            attributes["exhaust_state"] = state_obj.state if state_obj else None

        # Humidifier
        humidifier_entity = env_config.humidifier_entity
        attributes[CONF_HUMIDIFIER_ENTITIES] = env_config.humidifier_entities
        attributes["humidifier_control_enabled"] = env_config.control_humidifier
        attributes["humidifier_thresholds"] = env_config.humidifier_thresholds

        if humidifier_entity:
            state_obj = self.hass.states.get(humidifier_entity)
            attributes[CONF_HUMIDIFIER_ENTITY] = humidifier_entity
            attributes["humidifier_state"] = state_obj.state if state_obj else None

        # Circulation Fan
        circulation_fan_entity = env_config.circulation_fan_entity
        attributes[CONF_CIRCULATION_FAN_ENTITIES] = env_config.circulation_fan_entities

        if circulation_fan_entity:
            state_obj = self.hass.states.get(circulation_fan_entity)
            attributes[CONF_CIRCULATION_FAN_ENTITY] = circulation_fan_entity
            attributes["circulation_fan_state"] = state_obj.state if state_obj else None

        # Temperature Sensor
        temp_entity = env_config.temperature_sensor
        if temp_entity:
            state_obj = self.hass.states.get(temp_entity)
            attributes["temperature"] = state_obj.state if state_obj else None

        # Humidity Sensor
        hum_entity = env_config.humidity_sensor
        if hum_entity:
            state_obj = self.hass.states.get(hum_entity)
            attributes["humidity"] = state_obj.state if state_obj else None

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
            attributes["soil_moisture_value"] = state_obj.state if state_obj else None

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

        # Add 3D Sensor coordinates and plural sensor lists
        attributes["sensor_coordinates"] = env_config.sensor_coordinates
        attributes[CONF_TEMP_SENSORS] = env_config.temperature_sensors
        attributes[CONF_HUMIDITY_SENSORS] = env_config.humidity_sensors
        attributes[CONF_VPD_SENSORS] = env_config.vpd_sensors

        # New sensor arrays and scalars
        attributes["substrate_temperature_sensors"] = (
            env_config.substrate_temperature_sensors
        )
        attributes["power_sensors"] = env_config.power_sensors
        attributes["energy_sensors"] = env_config.energy_sensors
        attributes["electricity_cost_per_kwh"] = env_config.electricity_cost_per_kwh
        attributes["camera_entities"] = env_config.camera_entities

        # EC / pH / flow sensors (used by frontend for capability detection)
        attributes["ph_sensors"] = env_config.ph_sensors
        attributes["feed_ec_sensors"] = env_config.feed_ec_sensors
        attributes["substrate_ec_sensors"] = env_config.substrate_ec_sensors
        attributes["runoff_ec_sensors"] = env_config.runoff_ec_sensors
        attributes["drain_volume_sensors"] = env_config.drain_volume_sensors
        attributes["irrigation_flow_sensors"] = env_config.irrigation_flow_sensors

        # Irrigation Pumps (States for change detection in 3D heatmap)
        if growspace.irrigation_config:
            irr_cfg = growspace.irrigation_config
            if irr_cfg.irrigation_pump_entity:
                state_obj = self.hass.states.get(irr_cfg.irrigation_pump_entity)
                attributes["irrigation_pump_state"] = (
                    state_obj.state if state_obj else None
                )
            if irr_cfg.drain_pump_entity:
                state_obj = self.hass.states.get(irr_cfg.drain_pump_entity)
                attributes["drain_pump_state"] = state_obj.state if state_obj else None

            # Active Events (Start Time + Duration for precise animation)
            attributes["active_events"] = active_events or {}

        # Irrigation Tanks
        if env_config.irrigation_tanks:
            tanks_data = []
            for tank in env_config.irrigation_tanks:
                state_obj = self.hass.states.get(tank.sensor_entity)
                fill_level = (
                    self.entity_queries.parse_tank_level(state_obj.state)
                    if state_obj
                    else None
                )

                # Query TankDepletionSensor for depletion data
                depletion_sensor_id = (
                    f"sensor.{growspace.id}_tank_depletion_{tank.name}"
                )
                depletion_state = self.hass.states.get(depletion_sensor_id)

                hours_remaining = None
                depletion_status = None

                if depletion_state and depletion_state.state not in (
                    "unknown",
                    "unavailable",
                ):
                    with contextlib.suppress(ValueError, TypeError):
                        hours_remaining = float(depletion_state.state)

                    # Get status from attributes
                    if depletion_state.attributes:
                        depletion_status = depletion_state.attributes.get("status")

                tanks_data.append(
                    {
                        "sensor_entity": tank.sensor_entity,
                        "name": tank.name,
                        "warning_level": tank.warning_level,
                        "volume_liters": tank.volume_liters,
                        "fill_level": fill_level,
                        "is_warning": fill_level is not None
                        and fill_level <= tank.warning_level,
                        "hours_remaining": hours_remaining,
                        "depletion_status": depletion_status,
                        "water_history": {
                            # Raw snapshots and events are limited to stay
                            # within HA's 16 384-byte entity-attribute limit.
                            # Compact pre-computed summaries cover the full 7d.
                            "snapshots": tank.water_history.snapshots[-24:],
                            "events": tank.water_history.events[-20:],
                            **_compute_tank_water_summaries(tank.water_history.events),
                        },
                    }
                )
            attributes["irrigation_tanks"] = tanks_data
        else:
            attributes["irrigation_tanks"] = []

        # Sensor Groups
        if env_config.sensor_groups:
            attributes["sensor_groups"] = [
                g.to_dict() for g in env_config.sensor_groups
            ]
        else:
            attributes["sensor_groups"] = []

        return attributes
