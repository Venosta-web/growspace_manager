"""Data models for the Growspace Manager integration.

This package splits models into domain-specific sub-modules for maintainability.
All public types are re-exported here for backward-compatible imports.
"""

from custom_components.growspace_manager.const import PlantStage

from .base import BaseModel, BasePreset, _sanitize_numeric_fields
from .contract import GrowspaceCoordinatorData
from .genetics import PollinationEvent, SeedBatch
from .growspace import (
    ACInfinityDevice,
    ACInfinityGrowLight,
    CirculationFanConfig,
    DLIState,
    EnergyTracking,
    EnvironmentConfig,
    EnvironmentState,
    ExhaustFanConfig,
    GrowLightConfig,
    Growspace,
    GrowspaceEvent,
    GrowspaceType,
    SensorGroup,
    Subarea,
    VisionCheckupConfig,
    VisionCheckupResult,
    WaterUsageData,
)
from .ipm import IPMPreset, IPMPresetItem, IPMType
from .irrigation import (
    CropSteeringState,
    DrainConfig,
    DrainReading,
    ECRampCurve,
    ECRampPoint,
    ECTargetRange,
    IrrigationConfig,
    IrrigationStrategy,
    IrrigationTank,
    SubstrateEvent,
    SubstrateHistory,
    SubstrateProfile,
    TankWaterEvent,
    TankWaterHistory,
)
from .nutrient import NutrientInventory, NutrientPreset, NutrientStock
from .plant import (
    DryingData,
    HarvestMetrics,
    MoistureEntry,
    PhenotypeScore,
    Plant,
    PlantGenetics,
    WeightEntry,
)
from .types import (
    DehumidifierRange,
    IPMPresetDict,
    IrrigationScheduleItem,
    NutrientEntry,
    NutrientPresetDict,
    NutrientPresetItem,
    PlantTimelineEvent,
    StageHistoryItem,
    TimelineEventMetadata,
)

# Explicit __all__ list for documentation and IDE support
__all__ = [
    "ACInfinityDevice",
    "ACInfinityGrowLight",
    # base
    "BaseModel",
    "BasePreset",
    "CirculationFanConfig",
    "CropSteeringState",
    "DLIState",
    "DehumidifierRange",
    "DrainConfig",
    "DrainReading",
    "DryingData",
    "ECRampCurve",
    "ECRampPoint",
    "ECTargetRange",
    "EnergyTracking",
    "EnvironmentConfig",
    "EnvironmentState",
    "ExhaustFanConfig",
    "GrowLightConfig",
    "Growspace",
    # contract
    "GrowspaceCoordinatorData",
    "GrowspaceEvent",
    # growspace
    "GrowspaceType",
    "HarvestMetrics",
    "IPMPreset",
    "IPMPresetDict",
    "IPMPresetItem",
    # ipm
    "IPMType",
    "IrrigationConfig",
    # types
    "IrrigationScheduleItem",
    # irrigation
    "IrrigationStrategy",
    "IrrigationTank",
    "MoistureEntry",
    "NutrientEntry",
    "NutrientInventory",
    # nutrient
    "NutrientPreset",
    "NutrientPresetDict",
    "NutrientPresetItem",
    "NutrientStock",
    "PhenotypeScore",
    "Plant",
    # plant
    "PlantGenetics",
    "PlantStage",
    "PlantTimelineEvent",
    "PollinationEvent",
    # genetics
    "SeedBatch",
    "SensorGroup",
    "StageHistoryItem",
    "Subarea",
    "SubstrateEvent",
    "SubstrateHistory",
    "SubstrateProfile",
    "TankWaterEvent",
    "TankWaterHistory",
    "TimelineEventMetadata",
    "VisionCheckupConfig",
    "VisionCheckupResult",
    "WaterUsageData",
    "WeightEntry",
    "_sanitize_numeric_fields",
]
