"""Data models for the Growspace Manager integration."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from enum import StrEnum
import logging
from typing import Any, TypedDict

from mashumaro.mixins.dict import DataClassDictMixin

import homeassistant.util.dt as dt_util

from .const import (
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
    PlantStage,
)
from .domain.stage import STAGE_REGISTRY

# Import type aliases from centralized types module
from .integration_types import BayesianOptions, DehumidifierThresholds, NutrientMap
from .utils import calculate_days_since, days_to_week

_LOGGER = logging.getLogger(__name__)


class IrrigationScheduleItem(TypedDict, total=False):
    """Irrigation schedule item definition (immutable)."""

    time: str
    duration: int
    start_time: str
    duration_seconds: int | float


class TimelineEventMetadata(TypedDict, total=False):
    """Metadata for timeline events (sensor snapshots and action data)."""

    temperature: float | None
    humidity: float | None
    vpd: float | None
    soil_moisture: float | None
    light_intensity: float | None
    ph: float | None
    ec: float | None
    amount_ml: float | None


class PlantTimelineEvent(TypedDict, total=False):
    """Represents a rich timeline event for a plant."""

    type: str
    date: str
    images: list[str]
    tags: list[str]
    metadata: TimelineEventMetadata
    # Type specific fields
    from_stage: str
    to_stage: str
    action: str
    details: str
    severity: str
    message: str
    text: str
    label: str


class DehumidifierRange(TypedDict):
    """Dehumidifier on/off range (immutable)."""

    on: float
    off: float


class NutrientEntry(TypedDict):
    """Nutrient entry in the inventory."""

    name: str
    npk: str
    manufacturer: str
    description: str
    notes: str


class NutrientPresetItem(TypedDict):
    """A single nutrient in a preset recipe (immutable)."""

    name: str
    dose_ml_l: float  # ml per liter of solution


class NutrientPresetDict(TypedDict):
    """Nutrient preset definition."""

    name: str
    nutrients: NutrientMap
    ec_target: float
    ph_target: float
    description: str


class IPMPresetDict(TypedDict):
    """IPM preset definition."""

    name: str
    note: str
    description: str
    end: str | None


class StageHistoryItem(TypedDict):
    """Stage history record."""

    stage: str
    start: str
    end: str | None


def _sanitize_numeric_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Coerce None and float values to proper types for int fields before deserialization.

    With `from __future__ import annotations`, field types are stored as strings,
    so we compare against 'float'/'int' string literals rather than actual types.
    Avoids super() which is broken inside @dataclass(slots=True) classmethods.
    """
    data = data.copy()
    for f in fields(cls):
        if f.name in data:
            val = data[f.name]
            if val is None:
                if f.type in ("float", "int"):
                    if f.default is not MISSING:
                        data[f.name] = f.default
                    else:
                        data[f.name] = 0.0 if f.type == "float" else 0
            elif f.type == "int" and isinstance(val, (float, str)):
                try:
                    data[f.name] = int(float(val))
                except (ValueError, TypeError):
                    # On conversion error, fall back to the field's default or 0.
                    if f.default is not MISSING:
                        data[f.name] = f.default
                    else:
                        data[f.name] = 0
    return data


@dataclass(slots=True)
class BaseModel(DataClassDictMixin):
    """Base class providing generic serialization methods."""

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Generic pre-deserialization to handle None values for numeric fields."""
        return _sanitize_numeric_fields(cls, data)


@dataclass(slots=True, kw_only=True)
class BasePreset(BaseModel):
    """Base class providing generic preset attributes."""

    id: str
    name: str
    items: list[Any]
    stage: PlantStage | str | None = None
    min_days_in_stage: int | None = None
    created_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())


@dataclass(slots=True)
class IrrigationStrategy(BaseModel):
    """Configuration for VWC-based crop steering strategy."""

    enabled: bool = False
    lights_on_time: str = "06:00:00"
    p0_duration_minutes: int = 60
    p2_stop_before_lights_off_minutes: int = 120
    target_vwc_percent: float = 55.0
    maintenance_dryback_percent: float = 2.0
    shot_duration_seconds: int = 10
    shot_interval_minutes: int = 15


@dataclass(slots=True)
class TankWaterEvent(BaseModel):
    """A single water event derived from tank level change."""

    timestamp: str = ""
    liters: float = 0.0
    pct_delta: float = 0.0  # positive = refill, negative = consumption
    event_type: str = "consumption"  # "consumption" | "refill"


@dataclass(slots=True)
class TankWaterHistory(BaseModel):
    """Rolling 7-day history of tank level snapshots and water events."""

    # Raw level readings: [{"timestamp": ISO, "level_pct": float}]
    snapshots: list[dict[str, Any]] = field(default_factory=list)
    # Derived consumption / refill events
    events: list[dict[str, Any]] = field(default_factory=list)


@dataclass(slots=True)
class IrrigationTank(BaseModel):
    """Configuration for an irrigation tank."""

    sensor_entity: str
    name: str = "Tank"
    warning_level: float = 30.0  # Percentage threshold for warnings and prediction
    enable_prediction: bool = True  # Enable depletion prediction
    enable_lights_bias: bool = False  # Segregate rates by lights on/off
    enable_vpd_weighting: bool = False  # Apply VPD-based multiplier
    volume_liters: float | None = None
    last_recorded_level: float | None = None
    peak_level: float | None = None
    water_history: TankWaterHistory = field(default_factory=TankWaterHistory)


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
            # If we have both (e.g. from transition period), prefer the new one
            elif old_key in data:
                data.pop(old_key)

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
class IrrigationConfig(BaseModel):
    """Configuration for irrigation and drain pumps and schedules."""

    irrigation_pump_entity: str | None = None
    drain_pump_entity: str | None = None
    irrigation_duration: int | None = None
    drain_duration: int | None = None
    irrigation_times: list[IrrigationScheduleItem] = field(default_factory=list)
    drain_times: list[IrrigationScheduleItem] = field(default_factory=list)
    veg_day_hours: int = 12
    pump_flow_rate_ml_per_sec: float = 0.0


@dataclass(slots=True)
class DLIState(BaseModel):
    """Tracks daily DLI accumulation for a growspace."""

    accumulated_mol: float = 0.0
    last_reset: str = ""
    last_ppfd: float = 0.0
    last_sample_time: str = ""


@dataclass(slots=True)
class DrainReading(BaseModel):
    """A single drain/runoff measurement."""

    timestamp: str = ""
    feed_ec: float = 0.0
    drain_ec: float = 0.0
    drain_volume_ml: float | None = None
    feed_volume_ml: float | None = None


@dataclass(slots=True)
class DrainConfig(BaseModel):
    """Drain EC monitoring configuration per growspace."""

    enabled: bool = False
    max_ec_delta: float = 0.7
    target_runoff_percent: float = 20.0
    readings: list[DrainReading] = field(default_factory=list)
    max_readings: int = 100


@dataclass(slots=True)
class Subarea(BaseModel):
    """A named sub-zone within a growspace with its own environment sensors."""

    id: str
    name: str
    environment_config: EnvironmentConfig = field(default_factory=EnvironmentConfig)


@dataclass(slots=True)
class CropSteeringState(BaseModel):
    """Tracks crop steering metrics for a growspace."""

    score: float = 0.0
    dryback_percent: float = 0.0
    peak_vwc: float = 0.0
    trough_vwc: float = 0.0
    ec_trend: str = "stable"
    last_updated: str = ""


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
class ECRampPoint(BaseModel):
    """A single point on an EC ramp curve."""

    week: int = 1
    ec_min: float = 0.0
    ec_max: float = 0.0


@dataclass(slots=True)
class ECRampCurve(BaseModel):
    """EC target curve for a growth stage."""

    id: str = ""
    name: str = ""
    stage: str = ""
    points: list[ECRampPoint] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())


@dataclass(slots=True)
class SeedBatch(BaseModel):
    """A batch of seeds tracked in the genetics inventory."""

    batch_id: str = ""
    strain_name: str = ""
    breeder: str = ""
    quantity: int = 0
    acquisition_date: str = ""  # ISO date YYYY-MM-DD
    generation: str = ""  # e.g. F1, S1, BX1
    lineage: str = ""
    parent_1_strain: str | None = None
    parent_1_phenotype: str | None = None
    parent_2_strain: str | None = None
    parent_2_phenotype: str | None = None
    notes: str = ""


@dataclass(slots=True)
class PollinationEvent(BaseModel):
    """Records a pollination between two plants."""

    event_id: str = ""
    date: str = ""  # ISO date YYYY-MM-DD
    donor_plant_id: str = ""
    receiver_plant_id: str = ""
    notes: str = ""
    result_seed_batch_id: str | None = None


class GrowspaceType(StrEnum):
    """Enumeration of growspace types."""

    FLOWER = "flower"
    VEG = "veg"
    MOTHER = "mother"
    DRY = "dry"
    CURE = "cure"
    CLONE = "clone"


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


@dataclass(slots=True)
class PlantGenetics(BaseModel):
    """Immutable genetics reference for a plant."""

    strain_id: int | None = None
    phenotype_id: int | None = None
    strain_name: str = ""  # Cached for display/search
    phenotype_name: str = ""

    @property
    def key(self) -> str:
        """Unique key for strain+phenotype combo."""
        return (
            f"{self.strain_name}_{self.phenotype_name}"
            if self.phenotype_name
            else self.strain_name
        )


@dataclass(slots=True)
class PhenotypeScore(BaseModel):
    """Fused phenotype-selection rubric scored on a 1–10 scale.

    Replaces the legacy PlantScores model, merging its fields with the
    genetics-tracking rubric.  Old field names are migrated in
    Plant.__pre_deserialize__.
    """

    # Rubric fields (1-10, None = not yet scored)
    vigor: int | None = None
    internodal_spacing: int | None = None  # replaces legacy 'structure'
    terpene_intensity: int | None = None  # replaces legacy 'aroma'
    resin: int | None = None
    mold_resistance: int | None = None  # replaces legacy 'pest_resistance'
    yield_potential: int | None = None

    # Meta
    keeper: bool = False
    notes: str = ""
    updated_at: str | None = None

    @property
    def total_score(self) -> float | None:
        """Average of all rubric fields that have been set."""
        scored = [
            v
            for v in (
                self.vigor,
                self.internodal_spacing,
                self.terpene_intensity,
                self.resin,
                self.mold_resistance,
                self.yield_potential,
            )
            if v is not None
        ]
        if not scored:
            return None
        return sum(scored) / len(scored)


@dataclass(slots=True)
class HarvestMetrics(BaseModel):
    """Quantitative yield and quality data recorded at harvest."""

    wet_weight: float | None = None
    dry_weight: float | None = None
    trim_weight: float | None = None
    thc_percentage: float | None = None
    cbd_percentage: float | None = None
    terpene_profile: str | None = None


@dataclass(slots=True)
class Plant(BaseModel):
    """Represents a single plant."""

    plant_id: str
    growspace_id: str
    genetics: PlantGenetics = field(default_factory=PlantGenetics)
    row: int = 1
    col: int = 1
    stage: PlantStage | str = ""
    type: str = "normal"
    device_id: str | None = None
    seedling_start: str | None = None
    mother_start: str | None = None
    clone_start: str | None = None
    veg_start: str | None = None
    flower_start: str | None = None
    dry_start: str | None = None
    cure_start: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    transition_date: str | None = None
    source_mother: str | None = None
    last_watered: str | None = None
    last_trained: str | None = None
    last_training_technique: str | None = None
    last_ipm: str | None = None
    last_ipm_type: str | None = None
    phi_clearance_date: str | None = None
    stage_history: list[StageHistoryItem] = field(default_factory=list)
    phenotype_score: PhenotypeScore = field(default_factory=PhenotypeScore)
    harvest_metrics: HarvestMetrics = field(default_factory=HarvestMetrics)

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Mashumaro hook: transform data before deserialization."""
        data = _sanitize_numeric_fields(cls, data)

        # Sanitize integer fields - handle "30.0" strings
        for field_name in ["row", "col"]:
            if field_name in data:
                try:
                    data[field_name] = int(float(data[field_name]))
                except (ValueError, TypeError):
                    data[field_name] = 1  # Safe default

        # Migration: old 'scores' dict → new 'phenotype_score' with renamed fields.
        # If phenotype_score is already present (new format), discard stale scores key.
        if "scores" in data and "phenotype_score" not in data:
            old: dict[str, Any] = data.pop("scores") or {}
            data["phenotype_score"] = {
                "vigor": old.get("vigor"),
                "internodal_spacing": old.get("structure"),
                "terpene_intensity": old.get("aroma"),
                "resin": old.get("resin"),
                "mold_resistance": old.get("pest_resistance"),
            }
        elif "scores" in data:
            data.pop("scores")

        # Migration: flat fields → PlantGenetics
        if "strain" in data and "genetics" not in data:
            data["genetics"] = {
                "strain_name": data.pop("strain", ""),
                "phenotype_name": data.pop("phenotype", ""),
            }

        # Migration: build stage_history from start dates if not present
        if "stage_history" not in data:
            history = []

            # Collect all start dates using registry
            starts = []
            for stage_def in STAGE_REGISTRY.values():
                field_name = stage_def.start_field
                if date_val := data.get(field_name):
                    starts.append((date_val, stage_def.id.value))

            # Sort by date
            starts.sort(key=lambda x: x[0])

            # Build history segments
            for i, (start_date, stage) in enumerate(starts):
                end_date = None
                if i + 1 < len(starts):
                    end_date = starts[i + 1][0]

                history.append(
                    StageHistoryItem(stage=stage, start=start_date, end=end_date)
                )

            data["stage_history"] = history

        return data

    # Backward-compatible properties
    @property
    def strain(self) -> str:
        """Get strain name from genetics."""
        return self.genetics.strain_name

    @property
    def phenotype(self) -> str:
        """Get phenotype name from genetics."""
        return self.genetics.phenotype_name

    def get_days_since_watering(self) -> int | None:
        """Calculate days since last watering.

        Returns:
            Number of days since last watered, or None if never watered.
        """
        if self.last_watered:
            return calculate_days_since(self.last_watered)
        return None

    def get_days_in_stage(self, stage_name: str) -> int:
        """Calculate days spent in a specific stage using history."""
        total_days = 0
        found_in_history = False

        # 1. Calculate from history
        if self.stage_history:
            for item in self.stage_history:
                if item["stage"] == stage_name:
                    found_in_history = True
                    total_days += calculate_days_since(item["start"], item.get("end"))

            if found_in_history:
                return total_days

        # 2. Fallback to legacy start date attributes
        start_date_attr = f"{stage_name}_start"
        if hasattr(self, start_date_attr):
            start_date = getattr(self, start_date_attr)
            if start_date:
                return calculate_days_since(start_date)

        return 0

    def get_week_in_stage(self, stage_name: str) -> int:
        """Calculate the week number in a specific stage."""
        days = self.get_days_in_stage(stage_name)
        return days_to_week(days)


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


@dataclass(slots=True, kw_only=True)
class NutrientPreset(BasePreset):
    """A reusable nutrient recipe with optional stage conditions.

    Attributes:
        id: Unique identifier for the preset.
        name: Human-readable name for the preset (e.g., "Late Bloom Mix").
        items: List of nutrients (NutrientPresetItem).
        stage: Optional plant stage this preset applies to.
        min_days_in_stage: Optional minimum days in stage before this preset applies.
        created_at: Timestamp when the preset was created.
    """

    items: list[NutrientPresetItem]

    @property
    def nutrients(self) -> list[NutrientPresetItem]:
        """Alias for items for backward compatibility."""
        return self.items

    @nutrients.setter
    def nutrients(self, value: list[NutrientPresetItem]) -> None:
        self.items = value

    def get_nutrient_map(self) -> NutrientMap:
        """Convert nutrients list to a dict[str, float] for watering services."""
        return {n["name"]: n["dose_ml_l"] for n in self.items}


# Patch from_dict to use custom logic


class GrowspaceCoordinatorData(TypedDict):
    """Data contract for the Growspace Coordinator."""

    growspaces: dict[str, Growspace]
    plants: dict[str, Plant]
    nutrient_presets: dict[str, NutrientPreset]
    notifications_sent: dict[str, dict[str, dict[str, bool]]]
    notifications_enabled: dict[str, bool]
    _version: str
    serialized_growspaces: dict[str, dict[str, Any]]
    air_exchange_recommendations: dict[str, str]
    ipm_presets: dict[str, IPMPreset]
    nutrient_inventory: NutrientInventory


class IPMType(StrEnum):
    """Types of IPM applications."""

    FOLIAR = "foliar"
    DRENCH = "drench"
    SYSTEMIC = "systemic"
    OTHER = "other"


class IPMPresetItem(TypedDict, total=False):
    """A single item in an IPM preset recipe."""

    name: str  # type: ignore[assignment]
    dose_amount: float  # type: ignore[assignment]
    dose_unit: str  # type: ignore[assignment]
    phi_days: int  # Pre-harvest interval in days, default 0


@dataclass(slots=True, kw_only=True)
class IPMPreset(BasePreset):
    """A reusable IPM recipe with optional stage conditions."""

    type: IPMType | str
    items: list[IPMPresetItem]


@dataclass(slots=True)
class NutrientStock(BaseModel):
    """Tracks nutrient inventory levels."""

    nutrient_id: str
    name: str
    current_ml: float
    initial_ml: float
    last_updated: str = field(default_factory=lambda: dt_util.utcnow().isoformat())


@dataclass(slots=True)
class NutrientInventory(BaseModel):
    """Collection of nutrient stocks."""

    stocks: dict[str, NutrientStock] = field(default_factory=dict)
