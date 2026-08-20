"""Shared pure helpers for fan-speed control.

These functions hold the math used by both the circulation fan coordinator and
the exhaust fan coordinator. They are deliberately free of Home Assistant and
coordinator dependencies so they can be unit-tested in isolation and reused by
any controller that maps an environmental reading onto a fan speed.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from custom_components.growspace_manager.const import PlantStage

from .stage_calculator import determine_coordinator_stage

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant

# Per-stage VPD targets (day / night) for dynamic VPD mode.
# Values are midpoints of the tightest Bayesian optimal range for each stage.
FAN_VPD_STAGE_DEFAULTS: dict[PlantStage, dict[str, float]] = {
    PlantStage.SEEDLING: {"day": 0.60, "night": 0.60},
    PlantStage.CLONE: {"day": 0.50, "night": 0.50},
    PlantStage.MOTHER: {"day": 0.70, "night": 0.60},
    PlantStage.VEG: {"day": 0.70, "night": 0.60},
    PlantStage.FLOWER_EARLY: {"day": 1.15, "night": 1.00},
    PlantStage.FLOWER_MID: {"day": 1.20, "night": 1.00},
    PlantStage.FLOWER_LATE: {"day": 1.25, "night": 1.05},
    PlantStage.DRY: {"day": 0.95, "night": 0.95},
    PlantStage.CURE: {"day": 0.75, "night": 0.75},
}


def evaluate_temp_override(
    current_temp: float,
    critical_temp_low: float | None,
    critical_temp_high: float | None,
    hysteresis: float,
    override_active: bool,
    override_direction: str | None,
    vpd_speed: int,
    min_speed: int,
    max_speed: int,
) -> tuple[int, bool, str | None]:
    """Apply temperature safety override logic for VPD mode.

    Returns (final_speed, new_override_active, new_override_direction).
    Override direction is "high" or "low" when active, None otherwise.
    """
    if critical_temp_low is None and critical_temp_high is None:
        return vpd_speed, False, None

    if not override_active:
        if critical_temp_high is not None and current_temp > critical_temp_high:
            return max_speed, True, "high"
        if critical_temp_low is not None and current_temp < critical_temp_low:
            return min_speed, True, "low"
        return vpd_speed, False, None

    if override_direction == "high":
        if (
            critical_temp_high is not None
            and current_temp <= critical_temp_high - hysteresis
        ):
            return vpd_speed, False, None
        return max_speed, True, "high"

    # override_direction == "low"
    if critical_temp_low is not None and current_temp >= critical_temp_low + hysteresis:
        return vpd_speed, False, None
    return min_speed, True, "low"


def compute_wind_offset(
    amplitude_pct: int,
    elapsed_seconds: float,
    period_seconds: int,
) -> float:
    """Compute wind offset as amplitude × sin(2π × elapsed / period)."""
    return amplitude_pct * math.sin(2 * math.pi * elapsed_seconds / period_seconds)


def compute_fan_speed(
    value: float,
    target: float,
    tolerance: float,
    min_speed: int,
    max_speed: int,
) -> int:
    """Compute fan speed via linear mapping of value relative to target band.

    Below (target - tolerance): min_speed
    Above (target + tolerance): max_speed
    Inside the band: linearly interpolated
    """
    lower = target - tolerance
    upper = target + tolerance
    if value <= lower:
        return min_speed
    if value >= upper:
        return max_speed
    t = (value - lower) / (upper - lower)
    return round(min_speed + t * (max_speed - min_speed))


def compute_inverted_fan_speed(
    value: float,
    target: float,
    tolerance: float,
    min_speed: int,
    max_speed: int,
) -> int:
    """Compute an inverted fan speed: a lower value maps to a higher speed.

    Used for the VPD exhaust term, where a VPD *below* target means the tent is
    too humid and exhaust should ramp up:

    Below (target - tolerance): max_speed
    Above (target + tolerance): min_speed
    Inside the band: linearly interpolated from max_speed down to min_speed
    """
    return compute_fan_speed(value, target, tolerance, max_speed, min_speed)


def _source_air_blocks_cooling(
    tent_temperature: float,
    lung_room_temperature: float | None,
    minimum_source_air_temperature: float | None,
) -> bool:
    """Return True when incoming source air cannot cool the tent.

    Cooling is blocked when the source air is not cooler than the tent, or when
    it is below ``minimum_source_air_temperature``. With no source-air reading
    the gate is inert (returns False).
    """
    if lung_room_temperature is None:
        return False
    if (
        minimum_source_air_temperature is not None
        and lung_room_temperature < minimum_source_air_temperature
    ):
        return True
    return lung_room_temperature >= tent_temperature


def _source_air_blocks_moisture(
    current_vpd: float | None,
    lung_room_vpd: float | None,
    vpd_target: float,
) -> bool:
    """Return True when incoming source air would not dry the tent.

    Mirrors the air-exchange comparison the EnvironmentAnalyzer performs: source
    air helps only when its VPD is *closer* to target than the tent's current
    VPD. With no source-air reading — or no current tent VPD to compare against —
    the gate is inert (returns False).
    """
    if lung_room_vpd is None or current_vpd is None:
        return False
    return abs(lung_room_vpd - vpd_target) >= abs(current_vpd - vpd_target)


def compute_exhaust_demand(
    temperature: float | None,
    humidity: float | None,
    vpd: float | None,
    *,
    temperature_target: float,
    temperature_tolerance: float,
    humidity_target: float,
    humidity_tolerance: float,
    vpd_target: float,
    vpd_tolerance: float,
    min_speed: int,
    max_speed: int,
    lung_room_temperature: float | None = None,
    lung_room_vpd: float | None = None,
    minimum_source_air_temperature: float | None = None,
) -> int | None:
    """Combine the temperature, humidity and inverted-VPD terms into one speed.

    Each available reading is mapped to a demand term and the controller drives
    the fan to the highest of them:

    - temperature: hotter tent → more exhaust (direct mapping)
    - humidity: more humid tent → more exhaust (direct mapping)
    - VPD: inverted — more exhaust when VPD is *below* target (too humid)

    A ``None`` reading drops that term from the maximum. Returns ``None`` only
    when no reading is available at all; when readings exist but every term is
    gated, the result floors at ``min_speed``. The result is clamped to
    ``[min_speed, max_speed]``.

    The **source-air gate** suppresses a term when the air the fan would draw in
    cannot improve conditions (ADR 0018): the temperature term is dropped when
    the lung-room/source air is not cooler than the tent, or is below
    ``minimum_source_air_temperature``; the humidity and inverted-VPD terms are
    dropped when the source air is not drier than the tent (its VPD is no closer
    to ``vpd_target``). The gate is inert (every term ungated) when the
    corresponding lung-room reading is not supplied.
    """
    terms: list[int] = []
    if temperature is not None and not _source_air_blocks_cooling(
        temperature, lung_room_temperature, minimum_source_air_temperature
    ):
        terms.append(
            compute_fan_speed(
                temperature,
                temperature_target,
                temperature_tolerance,
                min_speed,
                max_speed,
            )
        )
    moisture_blocked = _source_air_blocks_moisture(vpd, lung_room_vpd, vpd_target)
    if humidity is not None and not moisture_blocked:
        terms.append(
            compute_fan_speed(
                humidity, humidity_target, humidity_tolerance, min_speed, max_speed
            )
        )
    if vpd is not None and not moisture_blocked:
        terms.append(
            compute_inverted_fan_speed(
                vpd, vpd_target, vpd_tolerance, min_speed, max_speed
            )
        )

    if not terms:
        if temperature is None and humidity is None and vpd is None:
            return None
        # Readings exist but every term was gated by the source-air filter:
        # this is a decision that exhaust won't help, so drive the fan down
        # rather than leaving a running device on.
        return min_speed

    return max(min_speed, min(max_speed, max(terms)))


def resolve_stage_vpd_target(
    plants: list[Plant],
    stage_vpd_overrides: dict[str, dict[str, float]],
    fallback_vpd_target: float,
    is_day: bool,
) -> float:
    """Resolve the effective VPD target from the active plant stage.

    Falls back to ``fallback_vpd_target`` when the growspace has no plants or
    the active stage is not present in the override map or the defaults.
    """
    if not plants:
        return fallback_vpd_target

    stage = determine_coordinator_stage(plants)
    day_key = "day" if is_day else "night"
    override = stage_vpd_overrides.get(stage.value)
    if override:
        return override[day_key]
    stage_entry = FAN_VPD_STAGE_DEFAULTS.get(stage)
    if stage_entry:
        return stage_entry[day_key]
    return fallback_vpd_target
