"""Irrigation configurations, tank states, and crop steering targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import homeassistant.util.dt as dt_util

from .base import BaseModel
from .types import IrrigationScheduleItem

__all__ = [
    "CropSteeringState",
    "DrainConfig",
    "DrainReading",
    "ECRampCurve",
    "ECRampPoint",
    "ECTargetRange",
    "IrrigationConfig",
    "IrrigationStrategy",
    "IrrigationTank",
    "TankWaterEvent",
    "TankWaterHistory",
]


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
    auto_light_tracking: bool = False
    detected_lights_on_time: str | None = None


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
class ECTargetRange(BaseModel):
    """Per-stage feed EC target range for irrigation nutrient targeting."""

    stage: str
    feed_ec_min: float = 0.0
    feed_ec_max: float = 0.0


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
    soil_trigger_percent: float | None = None
    daily_volume_cap_liters: float | None = None
    max_cycles_per_day: int | None = None
    skip_during_dark: bool = False
    pause_on_low_tank: bool = True
    log_to_logbook: bool = True
    ec_target_ranges: list[ECTargetRange] = field(default_factory=list)
    auto_advance_p1_to_p2: bool = False
    auto_advance_p2_to_p3: bool = False
    halt_on_runoff_ec_threshold: float | None = None
    active_steering_phase: str = "p2"


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
class CropSteeringState(BaseModel):
    """Tracks crop steering metrics for a growspace."""

    score: float = 0.0
    dryback_percent: float = 0.0
    peak_vwc: float = 0.0
    trough_vwc: float = 0.0
    ec_trend: str = "stable"
    last_updated: str = ""


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
