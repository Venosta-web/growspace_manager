"""Domain logic layer - pure business logic with no external dependencies."""

from __future__ import annotations

from .date_logic import (
    calculate_days_since,
    format_date,
    get_days_since_ipm,
    get_days_since_training,
    get_days_since_watering,
)
from .grid_builder import build_position_grid
from .lifetime_stage_days import resolve_lifetime_stage_days
from .plant_lifecycle import (
    KNOWN_STAGES,
    TRANSITION_GRAPH,
    Applied,
    BandInterpolation,
    CompatibilityData,
    CultivationBand,
    CultivationBandId,
    DecisionStatus,
    LifecycleCorrection,
    LifecycleDecision,
    LifecycleFacts,
    LifecycleRepairEventDraft,
    LifecycleRepairWarning,
    LifecycleStage,
    LifetimeStageDays,
    NoChange,
    PlantLifecycle,
    Rejected,
    RepairWarningCode,
    StageHistory,
    StageInterval,
    cultivation_band_for,
)

__all__ = [
    "KNOWN_STAGES",
    "TRANSITION_GRAPH",
    "Applied",
    "BandInterpolation",
    "CompatibilityData",
    "CultivationBand",
    "CultivationBandId",
    "DecisionStatus",
    "LifecycleCorrection",
    "LifecycleDecision",
    "LifecycleFacts",
    "LifecycleRepairEventDraft",
    "LifecycleRepairWarning",
    "LifecycleStage",
    "LifetimeStageDays",
    "NoChange",
    "PlantLifecycle",
    "Rejected",
    "RepairWarningCode",
    "StageHistory",
    "StageInterval",
    "build_position_grid",
    "calculate_days_since",
    "cultivation_band_for",
    "format_date",
    "get_days_since_ipm",
    "get_days_since_training",
    "get_days_since_watering",
    "resolve_lifetime_stage_days",
]
