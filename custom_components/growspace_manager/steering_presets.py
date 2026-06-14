"""Steering Mode preset table and resolver (ADR-0012).

Selecting a [[Steering Mode]] stamps recommended setpoints into the ordinary
editable strategy fields once. The server owns this table; callers only name
the mode. ``resolve_steering_preset`` returns the flat mapping of strategy
field names -> values to write for a given (mode, media, sizing mode):

- Agronomic levers (dryback, p2-stop offset, pore-EC band) vary by media x mode.
- Volume Mode shot sizes (percent) + their intervals vary by media x mode.
- Seconds Mode shot durations + intervals vary by mode only (they are
  pump-dependent crude fallbacks, so media-keying would imply false precision).
- ``target_vwc_percent`` is deliberately never stamped (a substrate property,
  not a steering-direction lever).
- Only the active sizing mode's representation is stamped (seconds OR percent).
- ``soil`` is deliberately gentle and near mode-independent.
"""

from __future__ import annotations

from typing import Any

from .const import ShotSizingMode, SteeringMode, SubstrateMediaType

# Agronomic levers shared by both sizing modes, keyed by (media, mode).
# Values: maintenance_dryback_percent (absolute VWC points, the in-cycle P2
# trigger), p2_stop_before_lights_off_minutes, pore_ec_target_min/max (mS/cm).
_AGRONOMIC_PRESETS: dict[tuple[SubstrateMediaType, SteeringMode], dict[str, Any]] = {
    (SubstrateMediaType.COCO, SteeringMode.VEGETATIVE): {
        "maintenance_dryback_percent": 2.0,
        "p2_stop_before_lights_off_minutes": 60,
        "pore_ec_target_min": 2.5,
        "pore_ec_target_max": 4.0,
    },
    (SubstrateMediaType.COCO, SteeringMode.BALANCED): {
        "maintenance_dryback_percent": 3.0,
        "p2_stop_before_lights_off_minutes": 120,
        "pore_ec_target_min": 3.0,
        "pore_ec_target_max": 5.0,
    },
    (SubstrateMediaType.COCO, SteeringMode.GENERATIVE): {
        "maintenance_dryback_percent": 5.0,
        "p2_stop_before_lights_off_minutes": 210,
        "pore_ec_target_min": 4.0,
        "pore_ec_target_max": 6.5,
    },
    (SubstrateMediaType.ROCKWOOL, SteeringMode.VEGETATIVE): {
        "maintenance_dryback_percent": 1.5,
        "p2_stop_before_lights_off_minutes": 60,
        "pore_ec_target_min": 3.0,
        "pore_ec_target_max": 5.0,
    },
    (SubstrateMediaType.ROCKWOOL, SteeringMode.BALANCED): {
        "maintenance_dryback_percent": 2.5,
        "p2_stop_before_lights_off_minutes": 120,
        "pore_ec_target_min": 4.0,
        "pore_ec_target_max": 6.0,
    },
    (SubstrateMediaType.ROCKWOOL, SteeringMode.GENERATIVE): {
        "maintenance_dryback_percent": 4.0,
        "p2_stop_before_lights_off_minutes": 210,
        "pore_ec_target_min": 5.0,
        "pore_ec_target_max": 8.0,
    },
    (SubstrateMediaType.SOIL, SteeringMode.VEGETATIVE): {
        "maintenance_dryback_percent": 2.0,
        "p2_stop_before_lights_off_minutes": 60,
        "pore_ec_target_min": 1.5,
        "pore_ec_target_max": 3.0,
    },
    (SubstrateMediaType.SOIL, SteeringMode.BALANCED): {
        "maintenance_dryback_percent": 2.5,
        "p2_stop_before_lights_off_minutes": 90,
        "pore_ec_target_min": 2.0,
        "pore_ec_target_max": 3.5,
    },
    (SubstrateMediaType.SOIL, SteeringMode.GENERATIVE): {
        "maintenance_dryback_percent": 3.0,
        "p2_stop_before_lights_off_minutes": 120,
        "pore_ec_target_min": 2.5,
        "pore_ec_target_max": 4.0,
    },
}

# Volume Mode shot sizes (percent of substrate volume) + intervals, media x mode.
_VOLUME_SHOT_PRESETS: dict[tuple[SubstrateMediaType, SteeringMode], dict[str, Any]] = {
    (SubstrateMediaType.COCO, SteeringMode.VEGETATIVE): {
        "p1_shot_volume_percent": 2.0,
        "p1_shot_interval_minutes": 5,
        "p2_shot_volume_percent": 2.0,
        "p2_shot_interval_minutes": 20,
    },
    (SubstrateMediaType.COCO, SteeringMode.BALANCED): {
        "p1_shot_volume_percent": 3.0,
        "p1_shot_interval_minutes": 8,
        "p2_shot_volume_percent": 3.0,
        "p2_shot_interval_minutes": 35,
    },
    (SubstrateMediaType.COCO, SteeringMode.GENERATIVE): {
        "p1_shot_volume_percent": 4.0,
        "p1_shot_interval_minutes": 12,
        "p2_shot_volume_percent": 4.0,
        "p2_shot_interval_minutes": 60,
    },
    (SubstrateMediaType.ROCKWOOL, SteeringMode.VEGETATIVE): {
        "p1_shot_volume_percent": 2.0,
        "p1_shot_interval_minutes": 5,
        "p2_shot_volume_percent": 1.5,
        "p2_shot_interval_minutes": 15,
    },
    (SubstrateMediaType.ROCKWOOL, SteeringMode.BALANCED): {
        "p1_shot_volume_percent": 3.0,
        "p1_shot_interval_minutes": 8,
        "p2_shot_volume_percent": 2.5,
        "p2_shot_interval_minutes": 30,
    },
    (SubstrateMediaType.ROCKWOOL, SteeringMode.GENERATIVE): {
        "p1_shot_volume_percent": 4.0,
        "p1_shot_interval_minutes": 12,
        "p2_shot_volume_percent": 4.0,
        "p2_shot_interval_minutes": 55,
    },
    (SubstrateMediaType.SOIL, SteeringMode.VEGETATIVE): {
        "p1_shot_volume_percent": 2.0,
        "p1_shot_interval_minutes": 8,
        "p2_shot_volume_percent": 2.0,
        "p2_shot_interval_minutes": 30,
    },
    (SubstrateMediaType.SOIL, SteeringMode.BALANCED): {
        "p1_shot_volume_percent": 2.5,
        "p1_shot_interval_minutes": 10,
        "p2_shot_volume_percent": 2.5,
        "p2_shot_interval_minutes": 40,
    },
    (SubstrateMediaType.SOIL, SteeringMode.GENERATIVE): {
        "p1_shot_volume_percent": 3.0,
        "p1_shot_interval_minutes": 12,
        "p2_shot_volume_percent": 3.0,
        "p2_shot_interval_minutes": 50,
    },
}

# Seconds Mode shot durations + intervals, by mode only (media-independent).
_SECONDS_SHOT_PRESETS: dict[SteeringMode, dict[str, Any]] = {
    SteeringMode.VEGETATIVE: {
        "p1_shot_duration_seconds": 8,
        "p1_shot_interval_minutes": 5,
        "p2_shot_duration_seconds": 6,
        "p2_shot_interval_minutes": 20,
    },
    SteeringMode.BALANCED: {
        "p1_shot_duration_seconds": 10,
        "p1_shot_interval_minutes": 8,
        "p2_shot_duration_seconds": 8,
        "p2_shot_interval_minutes": 35,
    },
    SteeringMode.GENERATIVE: {
        "p1_shot_duration_seconds": 14,
        "p1_shot_interval_minutes": 12,
        "p2_shot_duration_seconds": 12,
        "p2_shot_interval_minutes": 60,
    },
}


def resolve_steering_preset(
    mode: SteeringMode,
    media_type: SubstrateMediaType,
    sizing_mode: ShotSizingMode,
) -> dict[str, Any]:
    """Return the flat strategy-field mapping to stamp for a steering mode.

    Merges the media x mode agronomic levers with the shot preset for the
    active sizing mode (percent fields in Volume Mode, seconds fields in
    Seconds Mode). ``target_vwc_percent`` is never included.
    """
    preset: dict[str, Any] = dict(_AGRONOMIC_PRESETS[(media_type, mode)])
    if sizing_mode == ShotSizingMode.VOLUME:
        preset.update(_VOLUME_SHOT_PRESETS[(media_type, mode)])
    else:
        preset.update(_SECONDS_SHOT_PRESETS[mode])
    return preset
