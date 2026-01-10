"""Data models for the Growspace Manager integration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from typing import Any, Self, TypedDict

from .const import PlantStage
from .utils import calculate_days_since, days_to_week


class IrrigationScheduleItem(TypedDict):
    """Irrigation schedule item definition."""

    start_time: str
    duration_seconds: int
    # Add other keys as required by your logic


class DehumidifierRange(TypedDict):
    """Dehumidifier on/off range."""

    on: float
    off: float


type DehumidifierThresholds = dict[str, dict[str, DehumidifierRange]]
type BayesianOptions = dict[str, Any]
type NutrientMap = dict[str, float]


class NutrientEntry(TypedDict):
    """A single nutrient entry with concentration info."""

    name: str
    dose_ml_l: float
    total_amount: float


class NutrientPresetItem(TypedDict):
    """A single nutrient in a preset recipe."""

    name: str
    dose_ml_l: float  # ml per liter of solution


# Note: NutrientPreset is defined after BaseModel to inherit from it


@dataclass(slots=True)
class BaseModel:
    """Base class providing generic serialization methods."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary with optional migrations and nested handlers."""
        # Use a copy to avoid mutating the original
        data = data.copy()

        # Get configuration from class attributes
        migrations: dict[str, str] | None = getattr(cls, "_MIGRATIONS", None)
        nested_handlers: dict[str, Any] | None = getattr(cls, "_NESTED_HANDLERS", None)
        defaults: dict[str, Any] | None = getattr(cls, "_DEFAULTS", None)

        # Apply migrations
        if migrations:
            for old_key, new_key in migrations.items():
                if old_key in data and new_key not in data:
                    data[new_key] = data.pop(old_key)

        # Apply defaults
        if defaults:
            for key, value in defaults.items():
                if key not in data:
                    data[key] = value

        # Apply nested handlers
        if nested_handlers:
            for key, handler in nested_handlers.items():
                val = data.get(key)
                if val is not None and isinstance(val, dict):
                    data[key] = handler(val)

        # Filter fields
        catch_all_field = getattr(cls, "_CATCH_ALL_FIELD", None)
        allowed_keys = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_keys}

        if catch_all_field:
            extras = {k: v for k, v in data.items() if k not in allowed_keys}
            # Merge with existing data in the catch-all field if present
            existing_catch_all = filtered_data.get(catch_all_field, {})
            # Ensure it's a dict - if None or invalid type, start fresh
            if not isinstance(existing_catch_all, dict):
                existing_catch_all = {}
            existing_catch_all.update(extras)
            filtered_data[catch_all_field] = existing_catch_all

        return cls(**filtered_data)


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
class EnvironmentConfig(BaseModel):
    """Configuration for environment sensors and devices."""

    temperature_sensor: str | None = None
    humidity_sensor: str | None = None
    vpd_sensor: str | None = None
    co2_sensor: str | None = None
    light_sensor: str | None = None
    soil_moisture_sensor: str | None = None
    exhaust_fan_entity: str | None = None
    circulation_fan_entity: str | None = None
    humidifier_entity: str | None = None
    dehumidifier_entity: str | None = None
    lst_offset: float = -2.0
    control_dehumidifier: bool = False
    dehumidifier_thresholds: DehumidifierThresholds = field(default_factory=dict)
    minimum_source_air_temperature: float = 18.0
    stress_threshold: float = 0.70
    mold_threshold: float = 0.75
    bayesian_options: BayesianOptions = field(default_factory=dict)

    _CATCH_ALL_FIELD = "bayesian_options"

    _MIGRATIONS = {
        "exhaust_sensor": "exhaust_fan_entity",
        "humidifier_sensor": "humidifier_entity",
        "circulation_fan": "circulation_fan_entity",
        "exhaust_entity": "exhaust_fan_entity",
    }


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
    rows: int = 3
    plants_per_row: int = 3
    notification_target: str | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    device_id: str | None = None
    environment_config: EnvironmentConfig = field(default_factory=EnvironmentConfig)
    irrigation_config: IrrigationConfig = field(default_factory=IrrigationConfig)
    dehumidifier_config: dict[str, Any] = field(default_factory=dict)
    irrigation_strategy: IrrigationStrategy = field(default_factory=IrrigationStrategy)
    growspace_type: GrowspaceType = field(default=GrowspaceType.FLOWER)

    _MIGRATIONS = {"created": "created_at", "updated": "updated_at"}
    _NESTED_HANDLERS = {
        "irrigation_strategy": IrrigationStrategy.from_dict,
        "environment_config": EnvironmentConfig.from_dict,
        "irrigation_config": IrrigationConfig.from_dict,
    }


@dataclass(slots=True)
class Plant(BaseModel):
    """Represents a single plant."""

    plant_id: str
    growspace_id: str
    strain: str
    phenotype: str = ""
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

    _MIGRATIONS = {"created": "created_at", "updated": "updated_at"}

    def get_days_since_watering(self) -> int | None:
        """Calculate days since last watering.

        Returns:
            Number of days since last watered, or None if never watered.
        """
        if self.last_watered:
            return calculate_days_since(self.last_watered)
        return None

    def get_days_in_stage(self, stage_name: str) -> int:
        """Calculate days spent in a specific stage."""
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

    temp: float | None
    humidity: float | None
    vpd: float | None
    co2: float | None
    veg_days: int
    flower_days: int
    is_lights_on: bool | None
    fan_off: bool | None
    dehumidifier_on: bool | None = None
    exhaust_value: float | None = None
    humidifier_value: float | None = None
    soil_moisture: float | None = None


@dataclass(slots=True)
class GrowspaceEvent(BaseModel):
    """Represents a historical significant event in a growspace."""

    sensor_type: str
    growspace_id: str
    start_time: str
    end_time: str
    duration_sec: int
    severity: float
    category: str
    reasons: list[str] = field(default_factory=list)

    _MIGRATIONS = {"max_probability": "severity"}
    _DEFAULTS = {"category": "alert"}


@dataclass(slots=True)
class NutrientPreset(BaseModel):
    """A reusable nutrient recipe with optional stage conditions.

    Attributes:
        id: Unique identifier for the preset.
        name: Human-readable name for the preset (e.g., "Late Bloom Mix").
        nutrients: List of nutrients with their concentrations.
        stage: Optional plant stage this preset applies to.
        min_days_in_stage: Optional minimum days in stage before this preset applies.
        created_at: Timestamp when the preset was created.
    """

    id: str
    name: str
    nutrients: list[NutrientPresetItem]
    stage: PlantStage | str | None = None
    min_days_in_stage: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())

    def get_nutrient_map(self) -> NutrientMap:
        """Convert nutrients list to a dict[str, float] for watering services."""
        return {n["name"]: n["dose_ml_l"] for n in self.nutrients}


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


class IPMType(StrEnum):
    """Types of IPM applications."""

    FOLIAR = "foliar"
    DRENCH = "drench"
    SYSTEMIC = "systemic"
    OTHER = "other"


class IPMPresetItem(TypedDict):
    """A single item in an IPM preset recipe."""

    name: str
    dose_amount: float
    dose_unit: str  # e.g. "ml/L", "g/L", "tsp/gal"


@dataclass(slots=True)
class IPMPreset(BaseModel):
    """A reusable IPM recipe with optional stage conditions."""

    id: str
    name: str
    type: IPMType | str
    items: list[IPMPresetItem]
    stage: PlantStage | str | None = None
    min_days_in_stage: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
