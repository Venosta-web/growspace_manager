"""Centralized type definitions for Growspace Manager.

This module provides type aliases and TypedDict definitions used throughout the
Growspace Manager integration. Using centralized types improves type safety,
enables better IDE support, and makes refactoring easier.

Modern Python 3.13+ features:
- `type` keyword for type aliases
- Strict TypedDict definitions
- Union syntax with `|`
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, TypedDict

# =============================================================================
# Modern Python 3.13+ Type Aliases (using 'type' keyword)
# =============================================================================

# Date/Time Types
type DateInput = datetime | date | str | None

# Numeric Maps
type NutrientMap = dict[str, float]
# Note: DehumidifierRange is defined in models.py, but we can't reference it here
# due to circular import. Using Any for the nested dict values.
type DehumidifierThresholds = dict[str, dict[str, Any]]

# Generic fallback (to be gradually replaced with specific TypedDict)
type BayesianOptions = dict[str, Any]


# =============================================================================
# Plant-related TypedDict Definitions
# =============================================================================


class PlantGeneticsData(TypedDict, total=False):
    """Type definition for plant genetics data."""

    strain_id: int | None
    phenotype_id: int | None
    strain_name: str
    phenotype_name: str


class StageHistoryItemData(TypedDict):
    """Type definition for plant stage history."""

    stage: str
    start: str
    end: str | None


class PlantData(TypedDict, total=False):
    """Complete type definition for plant data dictionary.

    This replaces the old PlantDict = dict[str, Any] pattern.
    """

    # Required fields
    plant_id: str
    growspace_id: str

    # Core fields
    genetics: PlantGeneticsData
    row: int
    col: int
    stage: str
    type: str
    device_id: str | None

    # Stage start dates
    seedling_start: str | None
    mother_start: str | None
    clone_start: str | None
    veg_start: str | None
    flower_start: str | None
    dry_start: str | None
    cure_start: str | None

    # Metadata
    created_at: str | None
    updated_at: str | None
    transition_date: str | None

    # Tracking fields
    source_mother: str | None
    last_watered: str | None
    last_trained: str | None
    last_training_technique: str | None
    last_ipm: str | None
    last_ipm_type: str | None

    # History
    stage_history: list[StageHistoryItemData]

    # Backward compatibility (deprecated, use genetics)
    strain: str
    phenotype: str


# =============================================================================
# Growspace-related TypedDict Definitions
# =============================================================================


class EnvironmentConfigData(TypedDict, total=False):
    """Type definition for environment configuration."""

    temperature_sensor: str | None
    humidity_sensor: str | None
    vpd_sensor: str | None
    co2_sensor: str | None
    soil_moisture_sensor: str | None

    veg_day_hours: int
    flower_day_hours: int

    # Multi-device fields
    light_sensors: list[str]
    exhaust_fan_entities: list[str]
    circulation_fan_entities: list[str]
    humidifier_entities: list[str]
    dehumidifier_entities: list[str]

    # Control settings
    lst_offset: float
    control_dehumidifier: bool
    dehumidifier_thresholds: DehumidifierThresholds
    minimum_source_air_temperature: float
    stress_threshold: float
    mold_threshold: float
    bayesian_options: BayesianOptions


class IrrigationScheduleItemData(TypedDict, total=False):
    """Type definition for irrigation schedule items."""

    time: str
    duration: int
    start_time: str
    duration_seconds: int | float


class IrrigationConfigData(TypedDict, total=False):
    """Type definition for irrigation configuration."""

    irrigation_pump_entity: str | None
    drain_pump_entity: str | None
    irrigation_duration: int | None
    drain_duration: int | None
    irrigation_times: list[IrrigationScheduleItemData]
    drain_times: list[IrrigationScheduleItemData]
    veg_day_hours: int


class IrrigationStrategyData(TypedDict, total=False):
    """Type definition for VWC-based irrigation strategy."""

    enabled: bool
    lights_on_time: str
    p0_duration_minutes: int
    p2_stop_before_lights_off_minutes: int
    target_vwc_percent: float
    maintenance_dryback_percent: float
    shot_duration_seconds: int
    shot_interval_minutes: int


class GrowspaceData(TypedDict, total=False):
    """Complete type definition for growspace data dictionary.

    This replaces the old GrowspaceDict = dict[str, Any] pattern.
    """

    # Required fields
    id: str
    name: str

    # Grid layout
    rows: int
    plants_per_row: int

    # Configuration
    notification_target: str | None
    device_id: str | None
    growspace_type: str

    # Nested configs
    environment_config: EnvironmentConfigData
    irrigation_config: IrrigationConfigData
    dehumidifier_config: dict[str, Any]
    irrigation_strategy: IrrigationStrategyData

    # Metadata
    created_at: str


# =============================================================================
# Timeline & Event TypedDict Definitions
# =============================================================================


class TimelineEventMetadataData(TypedDict, total=False):
    """Type definition for timeline event metadata (sensor snapshots)."""

    temperature: float | None
    humidity: float | None
    vpd: float | None
    soil_moisture: float | None
    light_intensity: float | None
    ph: float | None
    ec: float | None
    amount_ml: float | None


class TimelineEventData(TypedDict, total=False):
    """Type definition for plant timeline events.

    This replaces untyped dict usage in timeline handling.
    """

    type: str
    date: str
    images: list[str]
    tags: list[str]
    metadata: TimelineEventMetadataData

    # Type-specific fields
    from_stage: str
    to_stage: str
    action: str
    details: str
    severity: str
    message: str
    text: str
    label: str


# =============================================================================
# Notification TypedDict Definitions
# =============================================================================


class NotificationData(TypedDict, total=False):
    """Type definition for notification data.

    This replaces NotificationDict = dict[str, Any].
    """

    growspace_id: str
    plant_id: str | None
    message: str
    title: str
    severity: str
    notification_type: str
    target: str | None
    timestamp: str


# =============================================================================
# Sensor & State TypedDict Definitions
# =============================================================================


class EnvironmentStateData(TypedDict, total=False):
    """Type definition for environment state snapshots."""

    temp: float | None
    humidity: float | None
    vpd: float | None
    co2: float | None
    veg_days: int
    flower_days: int
    seedling_days: int
    clone_days: int
    is_lights_on: bool | None
    fan_off: bool | None
    humidifier_on: bool | None
    dehumidifier_on: bool | None
    exhaust_value: float | None
    humidifier_value: float | None
    soil_moisture: float | None


class BayesianObservationData(TypedDict):
    """Type definition for Bayesian sensor observations."""

    observation: str
    likelihood_true: float
    likelihood_false: float


class BayesianResultData(TypedDict):
    """Type definition for Bayesian evaluation results."""

    probability: float
    threshold: float
    is_active: bool
    observations: list[BayesianObservationData]
    reasons: list[str]


# =============================================================================
# Service Call TypedDict Definitions
# =============================================================================


class AddPlantServiceData(TypedDict, total=False):
    """Type definition for add_plant service call data."""

    growspace_id: str
    strain: str
    phenotype: str
    row: int
    col: int
    stage: str
    transition_date: str | None


class UpdatePlantServiceData(TypedDict, total=False):
    """Type definition for update_plant service call data."""

    plant_id: str
    strain: str
    phenotype: str
    stage: str
    row: int
    col: int
    # Additional update fields can be added here


class WateringServiceData(TypedDict, total=False):
    """Type definition for watering service call data."""

    growspace_id: str
    plant_id: str | None
    amount: float
    amount_per_plant: float
    nutrients: NutrientMap
    ph: float | None
    ec: float | None
    preset_id: str | None


# =============================================================================
# Statistics & Analytics TypedDict Definitions
# =============================================================================


class PlantStatisticsData(TypedDict, total=False):
    """Type definition for plant statistics."""

    total_plants: int
    plants_by_stage: dict[str, int]
    plants_by_strain: dict[str, int]
    average_days_in_veg: float
    average_days_in_flower: float


class GrowspaceStatisticsData(TypedDict, total=False):
    """Type definition for growspace statistics."""

    total_growspaces: int
    total_plants: int
    active_plants: int
    plants_in_flower: int
    plants_in_veg: int
    utilization_percent: float


# =============================================================================
# Legacy Type Aliases (for backward compatibility during migration)
# =============================================================================

# These should be gradually removed as code is migrated to use the
# specific TypedDict classes above.

type PlantDict = dict[str, Any]  # TODO: Migrate to PlantData
type GrowspaceDict = dict[str, Any]  # TODO: Migrate to GrowspaceData
type NotificationDict = dict[str, Any]  # TODO: Migrate to NotificationData

# =============================================================================
# Type Guards (for runtime type checking)
# =============================================================================


def is_plant_data(data: dict[str, Any]) -> bool:
    """Type guard to check if dict matches PlantData structure.

    Args:
        data: Dictionary to check

    Returns:
        True if data has required plant fields
    """
    return "plant_id" in data and "growspace_id" in data


def is_growspace_data(data: dict[str, Any]) -> bool:
    """Type guard to check if dict matches GrowspaceData structure.

    Args:
        data: Dictionary to check

    Returns:
        True if data has required growspace fields
    """
    return "id" in data and "name" in data
