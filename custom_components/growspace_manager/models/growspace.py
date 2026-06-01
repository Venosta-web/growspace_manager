"""Growspace data models and environment configurations for the Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from enum import StrEnum
from typing import Any

from custom_components.growspace_manager.const import (
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_EXHAUST_FAN_ENTITY,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_TREND_TEMP_DURATION,
    CONF_TREND_TEMP_SENSITIVITY,
    CONF_TREND_TEMP_THRESHOLD,
    CONF_TREND_VPD_DURATION,
    CONF_TREND_VPD_SENSITIVITY,
    FanRegulationMode,
    PlantStage,
)
from custom_components.growspace_manager.integration_types import (
    BayesianOptions,
    DehumidifierThresholds,
)
import homeassistant.util.dt as dt_util

from .base import BaseModel, _sanitize_numeric_fields
from .irrigation import (
    DrainConfig,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationTank,
)

__all__ = [
    "CirculationFanConfig",
    "DLIState",
    "EnergyTracking",
    "EnvironmentConfig",
    "EnvironmentState",
    "Growspace",
    "GrowspaceEvent",
    "GrowspaceType",
    "SensorGroup",
    "Subarea",
    "VisionCheckupConfig",
    "VisionCheckupResult",
    "WaterUsageData",
]


class GrowspaceType(StrEnum):
    """Enumeration of growspace types."""

    FLOWER = "flower"
    VEG = "veg"
    MOTHER = "mother"
    DRY = "dry"
    CURE = "cure"
    CLONE = "clone"


@dataclass(slots=True)
class SensorGroup(BaseModel):
    """Configuration for a group of sensors at a specific coordinate."""

    id: str
    name: str
    x: float
    y: float
    z: float = 0.0
    temperature_sensors: list[str] = field(default_factory=list)
    humidity_sensors: list[str] = field(default_factory=list)
    vpd_sensors: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VisionCheckupResult(BaseModel):
    """Result of an AI vision checkup analysis."""

    timestamp: str
    growspace_id: str
    check_type: str  # "early", "mid", "late", "manual"
    snapshot_paths: list[str] = field(default_factory=list)
    analysis: str = ""
    issues_detected: list[str] = field(default_factory=list)
    severity: str = "none"  # "none", "low", "medium", "high", "critical"
    recommendations: list[str] = field(default_factory=list)


@dataclass(slots=True)
class VisionCheckupConfig(BaseModel):
    """Configuration for AI vision checkup scheduling."""

    enabled: bool = False
    early_check_offset_minutes: int = 60  # Minutes after lights on
    mid_check_hours: int = 6  # Hours into light cycle
    late_check_offset_minutes: int = 60  # Minutes before lights off
    history_limit: int = 10  # Max stored results per growspace


@dataclass(slots=True)
class CirculationFanConfig(BaseModel):
    """Configuration for the circulation fan controller."""

    enabled: bool = False
    regulation_mode: FanRegulationMode = FanRegulationMode.VPD
    min_speed: int = 0
    max_speed: int = 100
    humidity_target: float = 60.0
    humidity_tolerance: float = 5.0
    temperature_target: float = 25.0
    temperature_tolerance: float = 2.0
    vpd_target: float = 1.0
    vpd_tolerance: float = 0.2
    critical_temp_low: float | None = None
    critical_temp_high: float | None = None
    critical_temp_hysteresis: float = 1.0
    wind_enabled: bool = False
    wind_period_seconds: int = 60
    wind_amplitude_pct: int = 10


@dataclass(slots=True)
class EnvironmentConfig(BaseModel):
    """Configuration for environment sensors and devices."""

    temperature_sensor: str | None = None
    humidity_sensor: str | None = None
    vpd_sensor: str | None = None
    co2_sensor: str | None = None
    soil_moisture_sensor: str | None = None
    veg_day_hours: int = 18
    flower_day_hours: int = 12

    # Multi-device fields (NEW)
    temperature_sensors: list[str] = field(default_factory=list)
    humidity_sensors: list[str] = field(default_factory=list)
    vpd_sensors: list[str] = field(default_factory=list)
    light_sensors: list[str] = field(default_factory=list)
    exhaust_fan_entities: list[str] = field(default_factory=list)
    circulation_fan_entities: list[str] = field(default_factory=list)
    humidifier_entities: list[str] = field(default_factory=list)
    dehumidifier_entities: list[str] = field(default_factory=list)

    # 3D Sensor Configuration
    sensor_coordinates: dict[str, dict[str, float]] = field(default_factory=dict)
    sensor_groups: list[SensorGroup] = field(default_factory=list)

    substrate_temperature_sensors: list[str] = field(default_factory=list)
    camera_entities: list[str] = field(default_factory=list)
    lung_room_temp_sensors: list[str] = field(default_factory=list)
    snapshot_interval_hours: int = 24
    ph_sensors: list[str] = field(default_factory=list)
    feed_ec_sensors: list[str] = field(default_factory=list)
    substrate_ec_sensors: list[str] = field(default_factory=list)
    runoff_ec_sensors: list[str] = field(default_factory=list)
    drain_volume_sensors: list[str] = field(default_factory=list)
    irrigation_flow_sensors: list[str] = field(default_factory=list)
    power_sensors: list[str] = field(default_factory=list)
    energy_sensors: list[str] = field(default_factory=list)
    electricity_cost_per_kwh: float = 0.0
    dli_target_veg: float = 30.0
    dli_target_flower: float = 45.0

    lst_offset: float = -2.0
    control_dehumidifier: bool = False
    dehumidifier_thresholds: DehumidifierThresholds = field(default_factory=dict)
    control_humidifier: bool = False
    humidifier_thresholds: dict[str, Any] = field(default_factory=dict)
    minimum_source_air_temperature: float = 18.0
    stress_threshold: float = 0.70
    mold_threshold: float = 0.75
    bayesian_options: BayesianOptions = field(default_factory=dict)
    irrigation_tanks: list[IrrigationTank] = field(default_factory=list)
    vision_checkup_config: VisionCheckupConfig = field(
        default_factory=VisionCheckupConfig
    )
    circulation_fan_config: CirculationFanConfig = field(
        default_factory=CirculationFanConfig
    )

    def __post_init__(self) -> None:
        """Sync singular fields to plural lists for initialization support."""
        if self.temperature_sensor and not self.temperature_sensors:
            self.temperature_sensors = [self.temperature_sensor]
        if self.humidity_sensor and not self.humidity_sensors:
            self.humidity_sensors = [self.humidity_sensor]
        if self.vpd_sensor and not self.vpd_sensors:
            self.vpd_sensors = [self.vpd_sensor]

        # Sync plural -> singular for internal consistency
        if self.temperature_sensors and not self.temperature_sensor:
            self.temperature_sensor = self.temperature_sensors[0]
        if self.humidity_sensors and not self.humidity_sensor:
            self.humidity_sensor = self.humidity_sensors[0]
        if self.vpd_sensors and not self.vpd_sensor:
            self.vpd_sensor = self.vpd_sensors[0]

    # Backward-compatible properties
    @property
    def light_sensor(self) -> str | None:
        """Return first light sensor for backward compatibility."""
        return self.light_sensors[0] if self.light_sensors else None

    @property
    def exhaust_fan_entity(self) -> str | None:
        """Return first exhaust fan for backward compatibility."""
        return self.exhaust_fan_entities[0] if self.exhaust_fan_entities else None

    @property
    def circulation_fan_entity(self) -> str | None:
        """Return first circulation fan for backward compatibility."""
        return (
            self.circulation_fan_entities[0] if self.circulation_fan_entities else None
        )

    @property
    def humidifier_entity(self) -> str | None:
        """Return first humidifier for backward compatibility."""
        return self.humidifier_entities[0] if self.humidifier_entities else None

    @property
    def dehumidifier_entity(self) -> str | None:
        """Return first dehumidifier for backward compatibility."""
        return self.dehumidifier_entities[0] if self.dehumidifier_entities else None

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Mashumaro hook: transform data before deserialization."""
        data = _sanitize_numeric_fields(cls, data)

        # Coerce null list fields to [] so mashumaro doesn't reject them.
        _LIST_FIELDS = (
            "temperature_sensors",
            "humidity_sensors",
            "vpd_sensors",
            "light_sensors",
            "exhaust_fan_entities",
            "circulation_fan_entities",
            "humidifier_entities",
            "dehumidifier_entities",
            "sensor_groups",
            "substrate_temperature_sensors",
            "camera_entities",
            "lung_room_temp_sensors",
            "ph_sensors",
            "feed_ec_sensors",
            "substrate_ec_sensors",
            "runoff_ec_sensors",
            "drain_volume_sensors",
            "irrigation_flow_sensors",
            "power_sensors",
            "energy_sensors",
            "irrigation_tanks",
        )
        for _f in _LIST_FIELDS:
            if _f in data and data[_f] is None:
                data[_f] = []

        if data.get("circulation_fan_config") is None:
            data["circulation_fan_config"] = {}

        # Migration: singular -> plural list
        migrations = {
            CONF_LIGHT_SENSOR: CONF_LIGHT_SENSORS,
            CONF_EXHAUST_FAN_ENTITY: CONF_EXHAUST_FAN_ENTITIES,
            CONF_CIRCULATION_FAN_ENTITY: CONF_CIRCULATION_FAN_ENTITIES,
            CONF_HUMIDIFIER_ENTITY: CONF_HUMIDIFIER_ENTITIES,
            CONF_DEHUMIDIFIER_ENTITY: CONF_DEHUMIDIFIER_ENTITIES,
            "temperature_sensor": "temperature_sensors",
            "humidity_sensor": "humidity_sensors",
            "vpd_sensor": "vpd_sensors",
            "ph_sensor": "ph_sensors",
            "feed_ec_sensor": "feed_ec_sensors",
            "substrate_ec_sensor": "substrate_ec_sensors",
            "runoff_ec_sensor": "runoff_ec_sensors",
            "drain_volume_sensor": "drain_volume_sensors",
            "irrigation_flow_sensor": "irrigation_flow_sensors",
        }
        for old_key, new_key in migrations.items():
            # If we have the old key but NOT the new key, migrate
            if old_key in data and new_key not in data:
                val = data.get(old_key)
                # Ensure we handle potentially None values from old config
                if val:
                    data[new_key] = [val] if isinstance(val, str) else []
                else:
                    data[new_key] = []
                data.pop(old_key)

        # Migration: Trend keys (standardize naming)
        trend_migrations = {
            "vpd_trend_duration": CONF_TREND_VPD_DURATION,
            "temp_trend_duration": CONF_TREND_TEMP_DURATION,
            "vpd_trend_sensitivity": CONF_TREND_VPD_SENSITIVITY,
            "temp_trend_sensitivity": CONF_TREND_TEMP_SENSITIVITY,
            "temp_trend_threshold": CONF_TREND_TEMP_THRESHOLD,
        }
        for old_key, new_key in trend_migrations.items():
            if old_key in data and new_key not in data:
                data[new_key] = data.pop(old_key)

        # Migration: Stage names in threshold dicts (standardize flower stages)
        stage_migrations = {
            "early_flower": PlantStage.FLOWER_EARLY.value,
            "mid_flower": PlantStage.FLOWER_MID.value,
            "late_flower": PlantStage.FLOWER_LATE.value,
        }
        for dict_key in ["dehumidifier_thresholds", "humidifier_thresholds"]:
            if dict_key in data and isinstance(data[dict_key], dict):
                new_dict = {}
                for stage, thresholds in data[dict_key].items():
                    new_stage = stage_migrations.get(stage, stage)
                    new_dict[new_stage] = thresholds
                data[dict_key] = new_dict

        # Custom logic to implement _CATCH_ALL_FIELD behavior
        # Keep known keys, move everything else to bayesian_options
        known_keys = {fld.name for fld in fields(cls)}

        # Extract extras (unknown fields)
        extras = {k: v for k, v in data.items() if k not in known_keys}

        # If we have extras, put them into bayesian_options
        if extras:
            existing_opts = data.get("bayesian_options", {})
            if not isinstance(existing_opts, dict):
                existing_opts = {}
            else:
                existing_opts = existing_opts.copy()
            existing_opts.update(extras)
            data["bayesian_options"] = existing_opts

        # Remove extras from main dict
        for k in extras:
            if k in data:
                del data[k]

        return data


@dataclass(slots=True)
class DLIState(BaseModel):
    """Tracks daily DLI accumulation for a growspace."""

    accumulated_mol: float = 0.0
    last_reset: str = ""
    last_ppfd: float = 0.0
    last_sample_time: str = ""


@dataclass(slots=True)
class Subarea(BaseModel):
    """A named sub-zone within a growspace with its own environment sensors."""

    id: str
    name: str
    environment_config: EnvironmentConfig = field(default_factory=EnvironmentConfig)


@dataclass(slots=True)
class EnvironmentState:
    """Represents a snapshot of the current environment state in a growspace."""

    temp: float | None = None
    humidity: float | None = None
    vpd: float | None = None
    co2: float | None = None
    veg_days: int = -1
    flower_days: int = -1
    seedling_days: int = -1
    clone_days: int = -1
    dry_days: int = -1
    cure_days: int = -1
    mother_days: int = -1
    is_lights_on: bool | None = None
    fan_off: bool | None = None
    humidifier_on: bool | None = None
    dehumidifier_on: bool | None = None
    exhaust_value: float | None = None
    humidifier_value: float | None = None
    soil_moisture: float | None = None
    substrate_temp: float | None = None


@dataclass(slots=True)
class GrowspaceEvent(BaseModel):
    """Represents a historical significant event in a growspace."""

    sensor_type: str
    growspace_id: str
    start_time: str
    end_time: str
    duration_sec: int
    severity: float
    reasons: list[str] = field(default_factory=list)
    category: str = "alert"


@dataclass(slots=True)
class EnergyTracking(BaseModel):
    """Tracks cumulative energy usage per growspace."""

    cycle_start_kwh: float = 0.0
    cycle_start_date: str = ""
    last_kwh_reading: float = 0.0


@dataclass(slots=True)
class WaterUsageData(BaseModel):
    """Tracks cumulative water usage per growspace."""

    total_liters: float = 0.0
    cycle_start_date: str = ""
    daily_readings: list[dict[str, Any]] = field(default_factory=list)
    max_daily_readings: int = 365


@dataclass(slots=True)
class Growspace(BaseModel):
    """Represents a single growspace area."""

    id: str
    name: str
    dimensions: dict[str, float | str] = field(
        default_factory=lambda: {
            "width": 120,
            "depth": 120,
            "height": 200,
            "unit": "cm",
        }
    )
    rows: int = 3
    plants_per_row: int = 3
    notification_target: str | None = None
    created_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())
    device_id: str | None = None
    environment_config: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    irrigation_config: IrrigationConfig = field(default_factory=IrrigationConfig)
    dehumidifier_config: dict[str, Any] = field(default_factory=dict)
    humidifier_config: dict[str, Any] = field(default_factory=dict)
    irrigation_strategy: IrrigationStrategy = field(default_factory=IrrigationStrategy)
    growspace_type: GrowspaceType = field(default=GrowspaceType.FLOWER)
    drain_config: DrainConfig = field(default_factory=lambda: DrainConfig())
    energy_tracking: EnergyTracking = field(default_factory=lambda: EnergyTracking())
    water_usage: WaterUsageData = field(default_factory=lambda: WaterUsageData())
    vision_checkup_history: list[VisionCheckupResult] = field(default_factory=list)
    subareas: list[Subarea] = field(default_factory=list)

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Mashumaro hook: transform data before deserialization."""
        data = _sanitize_numeric_fields(cls, data)

        # Sanitize integer fields
        for field_name in ["rows", "plants_per_row"]:
            if field_name in data:
                try:
                    data[field_name] = int(float(data[field_name]))
                except (ValueError, TypeError):
                    data[field_name] = 3  # Safe default

        # Coerce null environment_config to empty dict so mashumaro uses field defaults.
        if data.get("environment_config") is None:
            data["environment_config"] = {}

        # Migration: Fix legacy irrigation schedule format
        if "irrigation_config" in data and isinstance(data["irrigation_config"], dict):
            irr_config = data["irrigation_config"].copy()

            # Sanitize veg_day_hours
            if "veg_day_hours" in irr_config:
                try:
                    irr_config["veg_day_hours"] = int(
                        float(irr_config["veg_day_hours"])
                    )
                except (ValueError, TypeError):
                    irr_config["veg_day_hours"] = 12

            # Migrate irrigation_times and drain_times
            for list_key in ["irrigation_times", "drain_times"]:
                if list_key in irr_config and isinstance(irr_config[list_key], list):
                    new_list = []
                    for item in irr_config[list_key]:
                        if isinstance(item, dict):
                            item = item.copy()
                            # Normalize to time/duration format (coordinator reads these keys).
                            # Migrate 'start_time' -> 'time'
                            if "start_time" in item and "time" not in item:
                                item["time"] = item.pop("start_time")
                            # Remove stale start_time if both keys exist
                            elif "start_time" in item and "time" in item:
                                del item["start_time"]

                            # Migrate 'duration_seconds' -> 'duration'
                            if "duration_seconds" in item and "duration" not in item:
                                try:
                                    item["duration"] = int(
                                        float(item.pop("duration_seconds"))
                                    )
                                except (ValueError, TypeError):
                                    item["duration"] = 60
                            # Remove stale duration_seconds if both keys exist
                            elif "duration_seconds" in item and "duration" in item:
                                del item["duration_seconds"]

                            # Ensure duration is int
                            if "duration" in item:
                                try:
                                    item["duration"] = int(float(item["duration"]))
                                except (ValueError, TypeError):
                                    item["duration"] = 60

                        new_list.append(item)
                    irr_config[list_key] = new_list

            data["irrigation_config"] = irr_config

        # Sanitize irrigation_strategy integers
        if "irrigation_strategy" in data and isinstance(
            data["irrigation_strategy"], dict
        ):
            strat = data["irrigation_strategy"].copy()
            int_fields = [
                "p0_duration_minutes",
                "p2_stop_before_lights_off_minutes",
                "shot_duration_seconds",
                "shot_interval_minutes",
            ]
            for f in int_fields:
                if f in strat:
                    try:
                        strat[f] = int(float(strat[f]))
                    except (ValueError, TypeError):
                        # Remove invalid value to let dataclass default take over
                        if f in strat:
                            del strat[f]
            data["irrigation_strategy"] = strat

        return data
