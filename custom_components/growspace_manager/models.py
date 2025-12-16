"""Data models for the Growspace Manager integration.

This file defines the dataclasses that represent the core objects used throughout
the integration, such as Growspace, Plant, and EnvironmentState. These models
provide a structured way to handle and pass around data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import datetime
from typing import TYPE_CHECKING, Any, TypedDict

from .const import PlantStage
from .utils import calculate_days_since, days_to_week

if TYPE_CHECKING:
    from .models import Growspace, days_to_week


type IrrigationScheduleItem = dict[str, Any]
type DehumidifierThresholds = dict[str, Any]
type BayesianOptions = dict[str, Any]


@dataclass(slots=True)
class BaseModel:
    """Base class providing generic serialization methods."""

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> Any:  # noqa: C901
        """Create from dictionary with optional migrations and nested handlers."""
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

        # specific hack for IrrigationStrategy which isn't always dict in some contexts?
        # Actually usually it is. But just in case.
        if nested_handlers:
            for key, handler in nested_handlers.items():
                if key in data and isinstance(data[key], dict):
                    data[key] = handler(data[key])
                elif key in data and data[key] is None:
                    # Handle None if handler allows it, or let it pass if field allows None
                    pass

        catch_all_field = getattr(cls, "_CATCH_ALL_FIELD", None)
        allowed_keys = {f.name for f in fields(cls)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_keys}

        if catch_all_field:
            extras = {k: v for k, v in data.items() if k not in allowed_keys}
            # Merge with existing data in the catch-all field if present
            existing_catch_all = filtered_data.get(catch_all_field, {})
            if existing_catch_all is None:
                existing_catch_all = {}
            if not isinstance(existing_catch_all, dict):
                existing_catch_all = {}  # Should not happen if typed correctly but safe

            existing_catch_all.update(extras)
            filtered_data[catch_all_field] = existing_catch_all

        return cls(**filtered_data)


@dataclass(slots=True)
class IrrigationStrategy(BaseModel):
    """Configuration for VWC-based crop steering strategy.

    Attributes:
        enabled: Whether VWC steering is enabled.
        lights_on_time: Time of day (HH:MM:SS) when lights turn on.
        p0_duration_minutes: Duration of P0 (Activation) phase.
        p2_stop_before_lights_off_minutes: Minutes before lights off to stop P2.
        target_vwc_percent: Target VWC percentage for P1/P2.
        maintenance_dryback_percent: Allowed dryback from target before re-watering in P2.
        shot_duration_seconds: Duration of each irrigation shot in seconds.
        shot_interval_minutes: Minutes between shots in P1.
    """

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
        "exhaust_entity": "exhaust_fan_entity",  # normalizing diverse naming
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


@dataclass(slots=True)
class Growspace(BaseModel):
    """Represents a single growspace area.

    Attributes:
        id: A unique identifier for the growspace.
        name: The display name of the growspace.
        rows: The number of rows in the growspace grid.
        plants_per_row: The number of plants per row in the grid.
        notification_target: The notification service to use for this growspace.
        created_at: The ISO-formatted date when the growspace was created.
        device_id: The Home Assistant device ID associated with this growspace.
        environment_config: A dictionary of environment sensor configurations.
        irrigation_config: A dictionary of basic pump configurations and schedules.
        dehumidifier_config: A dictionary of dehumidifier settings.
        irrigation_strategy: The VWC crop steering strategy configuration.
    """

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

    _MIGRATIONS = {"created": "created_at", "updated": "updated_at"}
    _NESTED_HANDLERS = {
        "irrigation_strategy": IrrigationStrategy.from_dict,
        "environment_config": EnvironmentConfig.from_dict,
        "irrigation_config": IrrigationConfig.from_dict,
    }


@dataclass(slots=True)
class Plant(BaseModel):
    """Represents a single plant.

    Attributes:
        plant_id: A unique identifier for the plant.
        growspace_id: The ID of the growspace this plant belongs to.
        strain: The strain name of the plant.
        phenotype: The phenotype of the strain.
        row: The row position of the plant in the growspace grid.
        col: The column position of the plant in the growspace grid.
        stage: The current growth stage of the plant.
        type: The type of plant (e.g., 'normal', 'clone', 'mother').
        device_id: The Home Assistant device ID associated with the plant.
        seedling_start: The ISO-formatted date the seedling stage started.
        mother_start: The ISO-formatted date the mother stage started.
        clone_start: The ISO-formatted date the clone stage started.
        veg_start: The ISO-formatted date the vegetative stage started.
        flower_start: The ISO-formatted date the flowering stage started.
        dry_start: The ISO-formatted date the drying stage started.
        cure_start: The ISO-formatted date the curing stage started.
        created_at: The ISO-formatted date the plant was created.
        updated_at: The ISO-formatted date the plant was last updated.
        transition_date: The date of the last stage transition.
        source_mother: The ID of the mother plant this plant was cloned from.
    """

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

    source_mother: str | None = None

    _MIGRATIONS = {"created": "created_at", "updated": "updated_at"}

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
    """Represents a snapshot of the current environment state in a growspace.

    This dataclass is used to pass around a consistent set of environmental
    readings for use in calculations, particularly for the Bayesian sensors.

    Attributes:
        temp: The current temperature.
        humidity: The current relative humidity.
        vpd: The current Vapor Pressure Deficit.
        co2: The current CO2 level.
        veg_days: The number of days the growspace has been in the vegetative stage.
        flower_days: The number of days the growspace has been in the flowering stage.
        is_lights_on: A boolean indicating if the lights are currently on.
        fan_off: A boolean indicating if the circulation fan is currently off.
    """

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
    """Represents a historical significant event in a growspace.

    Attributes:
        sensor_type: The type of sensor or source (e.g., 'mold_risk', 'irrigation').
        growspace_id: The ID of the growspace where the event occurred.
        start_time: The ISO-formatted start time of the event.
        end_time: The ISO-formatted end time of the event.
        duration_sec: The duration of the event in seconds.
        severity: The severity or intensity of the event (0.0 to 1.0).
        category: The category of the event (e.g., 'alert', 'irrigation').
        reasons: A list of contributing factors or details.
    """

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


class GrowspaceCoordinatorData(TypedDict):
    """Data contract for the Growspace Coordinator.

    This ensures strict typing for the data exposed to the frontend.
    """

    growspaces: dict[str, Growspace]
    plants: dict[str, Plant]
    notifications_sent: dict[str, dict[str, dict[str, bool]]]
    notifications_enabled: dict[str, bool]
    _version: str
    serialized_growspaces: dict[str, dict[str, Any]]
    air_exchange_recommendations: dict[str, str]
