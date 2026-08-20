"""TypedDict definitions and helper structures for the Growspace Manager."""

from __future__ import annotations

from typing import NotRequired, TypedDict

from custom_components.growspace_manager.integration_types import NutrientMap

__all__ = [
    "DehumidifierRange",
    "IPMPresetDict",
    "IrrigationScheduleItem",
    "NutrientEntry",
    "NutrientPresetDict",
    "NutrientPresetItem",
    "PlantTimelineEvent",
    "StageHistoryItem",
    "TimelineEventMetadata",
]


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

    nutrient_id: NotRequired[str]
    dose_ml_l: float  # ml per liter of solution
    name: NotRequired[str]


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
