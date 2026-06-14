"""Tests for Steering Mode preset resolution (the stamp value table)."""

from __future__ import annotations

from custom_components.growspace_manager.const import (
    ShotSizingMode,
    SteeringMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.steering_presets import resolve_steering_preset


def test_generative_coco_volume_mode_stamps_percent_and_agronomic_fields() -> None:
    """Generative coco in Volume Mode yields percent shot sizes + agronomic levers."""
    preset = resolve_steering_preset(
        SteeringMode.GENERATIVE, SubstrateMediaType.COCO, ShotSizingMode.VOLUME
    )

    assert preset["p1_shot_volume_percent"] == 4.0
    assert preset["p2_shot_volume_percent"] == 4.0
    assert preset["p2_shot_interval_minutes"] == 60
    assert preset["maintenance_dryback_percent"] == 5.0
    assert preset["p2_stop_before_lights_off_minutes"] == 210
    assert preset["pore_ec_target_min"] == 4.0
    assert preset["pore_ec_target_max"] == 6.5
    # Volume Mode must NOT stamp the seconds representation.
    assert "p1_shot_duration_seconds" not in preset
    assert "p2_shot_duration_seconds" not in preset


def test_seconds_mode_stamps_seconds_not_percent() -> None:
    """Seconds Mode writes the seconds shot fields and omits percent fields."""
    preset = resolve_steering_preset(
        SteeringMode.GENERATIVE, SubstrateMediaType.COCO, ShotSizingMode.SECONDS
    )

    assert preset["p1_shot_duration_seconds"] == 14
    assert preset["p2_shot_duration_seconds"] == 12
    assert preset["p2_shot_interval_minutes"] == 60
    assert "p1_shot_volume_percent" not in preset
    assert "p2_shot_volume_percent" not in preset


def test_seconds_shot_fields_are_media_independent() -> None:
    """Seconds shot durations depend on mode only, not media type."""
    coco = resolve_steering_preset(
        SteeringMode.VEGETATIVE, SubstrateMediaType.COCO, ShotSizingMode.SECONDS
    )
    rockwool = resolve_steering_preset(
        SteeringMode.VEGETATIVE, SubstrateMediaType.ROCKWOOL, ShotSizingMode.SECONDS
    )

    assert coco["p1_shot_duration_seconds"] == rockwool["p1_shot_duration_seconds"]
    assert coco["p2_shot_duration_seconds"] == rockwool["p2_shot_duration_seconds"]


def test_target_vwc_percent_is_never_stamped() -> None:
    """target_vwc_percent is a substrate property, never a stamp target."""
    for sizing in (ShotSizingMode.SECONDS, ShotSizingMode.VOLUME):
        preset = resolve_steering_preset(
            SteeringMode.GENERATIVE, SubstrateMediaType.ROCKWOOL, sizing
        )
        assert "target_vwc_percent" not in preset


def test_soil_presets_are_near_mode_independent() -> None:
    """Soil's dryback barely differs across modes (buffered medium)."""
    veg = resolve_steering_preset(
        SteeringMode.VEGETATIVE, SubstrateMediaType.SOIL, ShotSizingMode.VOLUME
    )
    gen = resolve_steering_preset(
        SteeringMode.GENERATIVE, SubstrateMediaType.SOIL, ShotSizingMode.VOLUME
    )

    # Soil generative dryback stays gentle, unlike coco/rockwool which ramp hard.
    assert (
        gen["maintenance_dryback_percent"] - veg["maintenance_dryback_percent"] <= 1.5
    )
