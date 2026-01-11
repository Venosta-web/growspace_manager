"""Data models for the Growspace Manager integration."""

from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from enum import StrEnum
from typing import (
    Any,
    Final,
    ReadOnly,
    Self,
    TypedDict,
    get_args,
    get_origin,
    get_type_hints,
)

from .const import PlantStage
from .utils import calculate_days_since, days_to_week

_LOGGER = logging.getLogger(__name__)


def _handle_nested_value(attr_type: Any, val: Any) -> Any:
    """Recursively handle nested BaseModel types based on type hints."""
    if val is None:
        return None

    origin = get_origin(attr_type) or attr_type

    # Case 1: Direct BaseModel subclass (or class with from_dict)
    if hasattr(attr_type, "from_dict") and isinstance(val, dict):
        return attr_type.from_dict(val)

    # Case 2: List of BaseModel subclasses
    if origin is list and (args := get_args(attr_type)):
        if hasattr(args[0], "from_dict") and isinstance(val, list):
            return [args[0].from_dict(i) if isinstance(i, dict) else i for i in val]

    # Case 3: Dict of BaseModel subclasses
    if origin is dict and (args := get_args(attr_type)) and len(args) > 1:
        if hasattr(args[1], "from_dict") and isinstance(val, dict):
            return {
                k: args[1].from_dict(v) if isinstance(v, dict) else v
                for k, v in val.items()
            }

    return val


class IrrigationScheduleItem(TypedDict):
    """Irrigation schedule item definition (immutable)."""

    start_time: ReadOnly[str]
    duration_seconds: ReadOnly[int]


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

    type: ReadOnly[str]
    date: ReadOnly[str]
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

    on: ReadOnly[float]
    off: ReadOnly[float]


type DehumidifierThresholds = dict[str, dict[str, DehumidifierRange]]
type BayesianOptions = dict[str, Any]
type NutrientMap = dict[str, float]


class NutrientEntry(TypedDict):
    """A single nutrient entry with concentration info (immutable)."""

    name: ReadOnly[str]
    dose_ml_l: ReadOnly[float]
    total_amount: ReadOnly[float]


class NutrientPresetItem(TypedDict):
    """A single nutrient in a preset recipe (immutable)."""

    name: ReadOnly[str]
    dose_ml_l: ReadOnly[float]  # ml per liter of solution


class StageHistoryItem(TypedDict):
    """Record of a plant's time in a specific stage."""

    stage: str
    start: str
    end: str | None


# Note: NutrientPreset is defined after BaseModel to inherit from it


@dataclass(slots=True)
class BaseModel:
    """Base class providing generic serialization methods."""

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary with automated nested handling and defaults."""
        data = data.copy()
        type_hints = get_type_hints(cls)
        defaults: dict[str, Any] | None = getattr(cls, "_DEFAULTS", None)

        if defaults:
            for key, value in defaults.items():
                if key not in data:
                    data[key] = value

        catch_all_field = getattr(cls, "_CATCH_ALL_FIELD", None)
        allowed_keys = {f.name for f in fields(cls)}

        filtered_data: dict[str, Any] = {}
        for key, val in data.items():
            if key in allowed_keys:
                attr_type = type_hints.get(key)
                filtered_data[key] = _handle_nested_value(attr_type, val)

        if catch_all_field:
            extras = {k: v for k, v in data.items() if k not in allowed_keys}
            existing_catch_all = filtered_data.get(catch_all_field)
            if not isinstance(existing_catch_all, dict):
                existing_catch_all = {}

            existing_catch_all.update(extras)
            filtered_data[catch_all_field] = existing_catch_all

        # Finally, filter filtered_data to ONLY allowed_keys before passing to constructor
        constructor_data = {k: v for k, v in filtered_data.items() if k in allowed_keys}
        return cls(**constructor_data)


@dataclass(slots=True, kw_only=True)
class BasePreset(BaseModel):
    """Base class providing generic preset attributes."""

    id: str
    name: str
    items: list[Any]
    stage: PlantStage | str | None = None
    min_days_in_stage: int | None = None
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())


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

    id: Final[str]
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


@dataclass(slots=True)
class Plant(BaseModel):
    """Represents a single plant."""

    plant_id: Final[str]
    growspace_id: Final[str]
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
    stage_history: list[StageHistoryItem] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary with history migration."""
        if "stage_history" not in data:
            data = data.copy()
            history = []

            # Collect all start dates
            starts = []
            for field_name in [
                "seedling_start",
                "mother_start",
                "clone_start",
                "veg_start",
                "flower_start",
                "dry_start",
                "cure_start",
            ]:
                if date_val := data.get(field_name):
                    stage_name = field_name.replace("_start", "")
                    starts.append((date_val, stage_name))

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

        # Workaround for 'super() arg not an instance' error during reloading/testing
        return BaseModel.from_dict.__func__(cls, data)

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

    _DEFAULTS = {"category": "alert"}


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary with backward compatibility for 'nutrients'."""
        if "nutrients" in data and "items" not in data:
            data = data.copy()
            data["items"] = data.pop("nutrients")
        # Workaround for 'super() arg not an instance' error during reloading/testing
        return BaseModel.from_dict.__func__(cls, data)

    def get_nutrient_map(self) -> NutrientMap:
        """Convert nutrients list to a dict[str, float] for watering services."""
        return {n["name"]: n["dose_ml_l"] for n in self.items}


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


@dataclass(slots=True, kw_only=True)
class IPMPreset(BasePreset):
    """A reusable IPM recipe with optional stage conditions."""

    type: IPMType | str
    items: list[IPMPresetItem]
