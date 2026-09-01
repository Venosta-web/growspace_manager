"""Irrigation configurations, tank states, and crop steering targets."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from custom_components.growspace_manager.const import (
    ShotSizingMode,
    SteeringMode,
    SubstrateMediaType,
)
import homeassistant.util.dt as dt_util

from .base import BaseModel, _sanitize_numeric_fields
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
    "SubstrateEvent",
    "SubstrateHistory",
    "SubstrateProfile",
    "TankWaterEvent",
    "TankWaterHistory",
]


@dataclass(slots=True)
class SubstrateProfile(BaseModel):
    """Per-growspace description of the growing medium.

    Holds the media type and the substrate volume per pot in liters. Combined
    with the live plant count it yields the total substrate volume that backs
    percent-of-volume shot sizing in Volume Mode (see ADR-0011). A profile is
    considered "set" once ``liters_per_pot`` is a positive number.
    """

    media_type: SubstrateMediaType = SubstrateMediaType.COCO
    liters_per_pot: float = 0.0

    @property
    def is_configured(self) -> bool:
        """Return True when the profile carries a usable per-pot volume."""
        return self.liters_per_pot > 0.0


# Legacy shared shot fields and the per-phase fields they seed on migration.
_LEGACY_SHOT_FIELD_MAP: dict[str, tuple[str, str]] = {
    "shot_duration_seconds": (
        "p1_shot_duration_seconds",
        "p2_shot_duration_seconds",
    ),
    "shot_interval_minutes": (
        "p1_shot_interval_minutes",
        "p2_shot_interval_minutes",
    ),
}


@dataclass(slots=True)
class IrrigationStrategy(BaseModel):
    """Configuration for VWC-based crop steering strategy.

    Shot duration and interval are configured per steering phase: P1 (ramp-up)
    and P2 (maintenance) each carry their own pair — the P1:P2 difference is a
    steering lever in its own right (fewer/larger shots = generative).
    """

    enabled: bool = False
    lights_on_time: str = "06:00:00"
    p0_duration_minutes: int = 60
    p2_stop_before_lights_off_minutes: int = 120
    target_vwc_percent: float = 55.0
    maintenance_dryback_percent: float = 2.0
    p1_shot_duration_seconds: int = 10
    p1_shot_interval_minutes: int = 15
    p2_shot_duration_seconds: int = 10
    p2_shot_interval_minutes: int = 15
    auto_light_tracking: bool = False
    detected_lights_on_time: str | None = None

    # Shot Sizing Mode (ADR-0011). SECONDS is the default first-class behavior;
    # VOLUME expresses shot sizes as a percent of substrate volume and is only
    # active when a substrate profile and pump flow rate are both configured.
    shot_sizing_mode: ShotSizingMode = ShotSizingMode.SECONDS
    substrate_profile: SubstrateProfile = field(default_factory=SubstrateProfile)
    # Per-phase shot sizes as a percent of total substrate volume (Volume Mode).
    p1_shot_volume_percent: float = 4.0
    p2_shot_volume_percent: float = 4.0

    # ── Adaptive Shot Control (ADR-0014) ────────────────────────────────────
    # Master toggle over the VWC feedback controller, which adapts both shot
    # size (VWC Feedback Scale Factor) and shot spacing (Interval Feedback Scale
    # Factor) from the substrate's response to the previous shot. Defaults True
    # to preserve the previously always-on size feedback; disabling it is the
    # new capability. Size and interval share the aggressiveness/recovery gains;
    # only the bounds differ (size floor < 1.0, interval ceiling > 1.0).
    dynamic_shot_enabled: bool = True
    dynamic_aggressiveness: float = 1.0
    dynamic_recovery: float = 0.1
    dynamic_shot_size_floor: float = 0.5
    dynamic_interval_ceiling: float = 1.5

    # ── Pore EC Target Band + EC Modulation ─────────────────────────────────
    # Explicit min/max pore-EC band (mS/cm) that EC Modulation steers toward.
    # DELIBERATELY DISTINCT from the per-stage *feed* EC ranges (ECTargetRange):
    # pore EC legitimately runs above feed EC when stacking, so the two must
    # never be conflated (CONTEXT.md "Pore EC Target Band"). Both None => no
    # band configured; combined with ``ec_modulation_enabled`` defaulting False,
    # existing stored configs deserialize unchanged (modulation off, factor 1.0).
    pore_ec_target_min: float | None = None
    pore_ec_target_max: float | None = None
    # Opt-in: when False (or the band/sensors are absent), EC Modulation is
    # inert and the modulation factor is exactly 1.0.
    ec_modulation_enabled: bool = False

    # ── Steering Mode (declared intent, ADR-0012) ───────────────────────────
    # The grower's declared steering intent. None means undeclared (never
    # stamped) — a real third state distinct from an explicit BALANCED, so
    # Intent Deviation reads null until the first stamp. The coordinator never
    # reads this; selecting a mode stamps preset values into the explicit
    # fields above. Existing stored configs deserialize with None unchanged.
    declared_steering_mode: SteeringMode | None = None

    # ── Recipe Stamp (ADR-0045) ─────────────────────────────────────────────
    # Which grower-authored [[Irrigation Recipe]] was last stamped into the
    # fields above, and when. Both None means "never applied" — a real third
    # state, exactly as ``declared_steering_mode`` is undeclared until its
    # first stamp. The coordinator never reads either: applying writes the
    # recipe's values into the explicit fields and these only record what did
    # it. No drift hash sits beside them, because recipes are held by
    # reference and "has the grower tweaked since?" is a live comparison
    # (``domain/irrigation_recipe.recipe_has_drifted``).
    applied_recipe_id: str | None = None
    recipe_applied_at: str | None = None

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Migrate legacy shared shot fields by seeding both phases.

        Stored configs predating the per-phase split carry only
        ``shot_duration_seconds`` / ``shot_interval_minutes``; those values seed
        both phases' fields so behavior is unchanged until a user edits one.
        Explicit per-phase values always win over the legacy keys.
        """
        data = data.copy()
        for legacy_key, phase_keys in _LEGACY_SHOT_FIELD_MAP.items():
            if legacy_key in data:
                legacy_value = data.pop(legacy_key)
                for phase_key in phase_keys:
                    data.setdefault(phase_key, legacy_value)
        return _sanitize_numeric_fields(cls, data)

    @classmethod
    def __post_serialize__(cls, d: dict[str, Any]) -> dict[str, Any]:
        """Mirror the P1 values onto the legacy keys.

        Keeps older readers (frontend card pending its per-phase update,
        rollbacks to earlier integration versions) working until they adopt
        the per-phase fields. Deserialization prefers the per-phase keys, so
        the mirror is lossless.
        """
        d["shot_duration_seconds"] = d["p1_shot_duration_seconds"]
        d["shot_interval_minutes"] = d["p1_shot_interval_minutes"]
        return d

    @property
    def shot_duration_seconds(self) -> int:
        """Deprecated alias for the shared shot duration; reads the P1 value."""
        return self.p1_shot_duration_seconds

    @shot_duration_seconds.setter
    def shot_duration_seconds(self, value: int) -> None:
        """Preserve legacy shared semantics by writing both phases."""
        self.p1_shot_duration_seconds = value
        self.p2_shot_duration_seconds = value

    @property
    def shot_interval_minutes(self) -> int:
        """Deprecated alias for the shared shot interval; reads the P1 value."""
        return self.p1_shot_interval_minutes

    @shot_interval_minutes.setter
    def shot_interval_minutes(self, value: int) -> None:
        """Preserve legacy shared semantics by writing both phases."""
        self.p1_shot_interval_minutes = value
        self.p2_shot_interval_minutes = value


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
class SubstrateEvent(BaseModel):
    """A single measured substrate dryback event.

    ``dryback`` is expressed in absolute VWC percentage points (peak - trough),
    never relative to the peak (see CONTEXT.md "Dryback").
    """

    event_type: str = "in_cycle"  # "overnight" | "in_cycle"
    peak_timestamp: str = ""
    trough_timestamp: str = ""
    peak_vwc: float = 0.0
    trough_vwc: float = 0.0
    dryback: float = 0.0


@dataclass(slots=True)
class SubstrateHistory(BaseModel):
    """Rolling history of measured substrate dryback events.

    Holds the persisted output of the SubstrateTracker plus the minimal pending
    state needed to resume an in-flight dryback window after a restart. A peak
    that is still awaiting its trough is stored in ``pending_*`` so a mid-night
    HA restart can pick the window back up rather than discarding it.
    """

    events: list[dict[str, Any]] = field(default_factory=list)

    # Pending overnight peak: settled VWC peak recorded after the day's last
    # shot, awaiting the next day's first-shot trough. Persists across restarts.
    pending_overnight_peak: float | None = None
    pending_overnight_peak_ts: str | None = None
    # Running minimum seen since the pending overnight peak (the trough so far).
    pending_overnight_trough: float | None = None
    pending_overnight_trough_ts: str | None = None

    # Pending in-cycle peak: settled VWC peak after a P2 shot, awaiting the next
    # P2 shot's pre-shot trough.
    pending_incycle_peak: float | None = None
    pending_incycle_peak_ts: str | None = None
    pending_incycle_trough: float | None = None
    pending_incycle_trough_ts: str | None = None

    # Lit-period maximum, the zero-shot-day fallback for the overnight peak.
    lit_period_max: float | None = None
    lit_period_max_ts: str | None = None

    # ISO date (local) of the day whose shots are currently being tracked, used
    # to detect day rollover for the lit-period-max reset.
    current_day: str | None = None
    # Whether any shot fired during current_day (drives the zero-shot fallback).
    shots_today: int = 0

    # ── Daily pore-EC trend state ───────────────────────────────────────────
    # Day-start (earliest) and latest averaged pore-EC readings for the current
    # local day, the inputs to the rising/stable/falling EC trend. Persisted so
    # a mid-day restart resumes the day's baseline rather than restarting it.
    # ``ec_trend_day`` guards the daily reset (mirrors ``current_day`` but is
    # driven by pore-EC readings, which may arrive independently of VWC).
    ec_trend_day: str | None = None
    ec_day_start_value: float | None = None
    ec_day_start_ts: str | None = None
    ec_latest_value: float | None = None
    ec_latest_ts: str | None = None


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
    # Legacy irrigation copy of the vegetative photoperiod. Boundary math uses
    # EnvironmentConfig via resolve_day_hours(), but keeping this default aligned
    # avoids two backend models assigning different meanings to an omitted value.
    veg_day_hours: int = 18
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
    phase_changed_at: str | None = None


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
    """Tracks crop steering metrics for a growspace.

    ``dryback_percent`` is expressed in absolute VWC percentage points
    (peak - trough), never relative to the peak.
    """

    score: float = 0.0
    dryback_percent: float = 0.0
    peak_vwc: float = 0.0
    trough_vwc: float = 0.0
    # Measured pore-EC trend: "rising"/"stable"/"falling" when sensors report,
    # else None (unavailable). ``ec_trend_available`` distinguishes a measured
    # "stable" from "no pore-EC sensors", so the card shows its unlock hint only
    # in the latter case. ``ec_day_start``/``ec_current`` are the trend inputs.
    ec_trend: str | None = None
    ec_trend_available: bool = False
    ec_day_start: float | None = None
    ec_current: float | None = None
    # Steering Mode readout (ADR-0012). ``measured_classification`` is the
    # score-derived bucket (a measurement); ``intent_deviation`` compares it
    # against the declared mode ("on_target"/"more_generative"/"more_vegetative",
    # None when undeclared or no current reading). The score itself never bends
    # toward the declared mode. The declared intent itself is NOT mirrored here:
    # its single source of truth is the ``declared_steering_mode`` strategy
    # field, which the view-model payload already carries (one datum, one key).
    measured_classification: str = "balanced"
    intent_deviation: str | None = None
    # The runoff fill contribution to the shared EC axis (ADR-0016), in
    # [-0.3, 0.3]. 0.0 when no sustained runoff delta or a pore-EC trend already
    # set the axis. Surfaced so the score's EC contribution is explainable.
    runoff_score: float = 0.0
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
