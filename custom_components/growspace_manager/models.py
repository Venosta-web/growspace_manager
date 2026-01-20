"""Data models for the Growspace Manager integration."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import datetime
from enum import StrEnum
import logging
from typing import Any, Self, TypedDict, cast

from mashumaro.mixins.dict import DataClassDictMixin

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


DehumidifierThresholds = dict[str, dict[str, DehumidifierRange]]
BayesianOptions = dict[str, Any]
NutrientMap = dict[str, float]


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


@dataclass(slots=True)
class BaseModel(DataClassDictMixin):  # type: ignore[misc]
    """Base class providing generic serialization methods."""


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
    soil_moisture_sensor: str | None = None

    # Multi-device fields (NEW)
    light_sensors: list[str] = field(default_factory=list)
    exhaust_fan_entities: list[str] = field(default_factory=list)
    circulation_fan_entities: list[str] = field(default_factory=list)
    humidifier_entities: list[str] = field(default_factory=list)
    dehumidifier_entities: list[str] = field(default_factory=list)

    lst_offset: float = -2.0
    control_dehumidifier: bool = False
    dehumidifier_thresholds: DehumidifierThresholds = field(default_factory=dict)
    minimum_source_air_temperature: float = 18.0
    stress_threshold: float = 0.70
    mold_threshold: float = 0.75
    bayesian_options: BayesianOptions = field(default_factory=dict)

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
    def from_dict_custom(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary with catch-all support for bayesian_options and migration."""
        data = data.copy()

        # Migration: singular -> plural list
        migrations = {
            CONF_LIGHT_SENSOR: CONF_LIGHT_SENSORS,
            CONF_EXHAUST_FAN_ENTITY: CONF_EXHAUST_FAN_ENTITIES,
            CONF_CIRCULATION_FAN_ENTITY: CONF_CIRCULATION_FAN_ENTITIES,
            CONF_HUMIDIFIER_ENTITY: CONF_HUMIDIFIER_ENTITIES,
            CONF_DEHUMIDIFIER_ENTITY: CONF_DEHUMIDIFIER_ENTITIES,
        }
        for old_key, new_key in migrations.items():
            # If we have the old key but NOT the new key, migrate
            if old_key in data and new_key not in data:
                val = data.pop(old_key)
                # Ensure we handle potentially None values from old config
                if val:
                    data[new_key] = [val] if isinstance(val, str) else []
                else:
                    data[new_key] = []
            # If we have both (e.g. from transition period), prefer the new one but ensure old is cleaned up
            elif old_key in data:
                data.pop(old_key)

        # Custom logic to implement _CATCH_ALL_FIELD behavior
        # Keep known keys, move everything else to bayesian_options
        known_keys = {f.name for f in fields(cls)}

        # Prepare data copy
        data = data.copy()

        # Extract extras
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

        # Remove extras from main dict to rely solely on bayesian_options merging
        for k in extras:
            if k in data:
                del data[k]

        return cast(Self, cls.__mashumaro_from_dict__(data))  # type: ignore[no-any-return]


# Patch from_dict to use custom logic
EnvironmentConfig.__mashumaro_from_dict__ = EnvironmentConfig.from_dict
EnvironmentConfig.from_dict = EnvironmentConfig.from_dict_custom


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
    stage_history: list[StageHistoryItem] = field(default_factory=list)

    # Backward-compatible properties
    @property
    def strain(self) -> str:
        """Get strain name from genetics."""
        return self.genetics.strain_name

    @property
    def phenotype(self) -> str:
        """Get phenotype name from genetics."""
        return self.genetics.phenotype_name

    @classmethod
    def from_dict_custom(cls, data: dict[str, Any]) -> Self:
        """Create from dictionary with history and genetics migration."""
        # Migration: flat fields → PlantGenetics
        if "strain" in data and "genetics" not in data:
            data = data.copy()
            data["genetics"] = {
                "strain_name": data.pop("strain", ""),
                "phenotype_name": data.pop("phenotype", ""),
            }

        if "stage_history" not in data:
            data = data.copy() if "strain" not in data else data
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

        return cls.__mashumaro_from_dict__(data)

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


# Patch from_dict to use custom logic
Plant.__mashumaro_from_dict__ = Plant.from_dict
Plant.from_dict = Plant.from_dict_custom


@dataclass(slots=True)
class EnvironmentState:
    """Represents a snapshot of the current environment state in a growspace."""

    temp: float | None = None
    humidity: float | None = None
    vpd: float | None = None
    co2: float | None = None
    veg_days: int = 0
    flower_days: int = 0
    seedling_days: int = 0
    clone_days: int = 0
    is_lights_on: bool | None = None
    fan_off: bool | None = None
    humidifier_on: bool | None = None
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

    @classmethod
    def from_dict(cls, d: Mapping[Any, Any], **kwargs: Any) -> Self:
        """Create a NutrientPreset instance from a dictionary."""
        return cast(Self, super().from_dict(d))

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


@dataclass(slots=True)
class NutrientStock(BaseModel):
    """Tracks nutrient inventory levels."""

    nutrient_id: str
    name: str
    current_ml: float
    initial_ml: float
    last_updated: str = field(default_factory=lambda: datetime.now().isoformat())


@dataclass(slots=True)
class NutrientInventory(BaseModel):
    """Collection of nutrient stocks."""

    stocks: dict[str, NutrientStock] = field(default_factory=dict)
