"""Irrigation Recipe capture — turning a growspace's settings into a recipe.

The one place a live growspace becomes a portable [[Irrigation Recipe]]. Pure
over models and plain numbers: no ``hass``, no coordinator, no storage (the
[[Pump Cycle Gate]] / [[EC State]] mould).

The whole module exists for one rule. A shot size in **pump seconds** is not a
portable quantity — ten seconds delivers whatever *that* growspace's plumbing
delivers — so [[Substrate-Relative Shot Storage]] says a recipe holds a percent
of substrate volume and nothing else. A growspace already running Volume Mode
has that percent; one running Seconds Mode does not, and its percent must be
recovered from the seconds through its own flow rate and pot volume. That
recovery is plant-count-independent (``seconds_to_percent`` divides the live
count back out), which is what lets the recipe be applied to a tent holding a
different number of plants.

When the recovery cannot be done honestly the save is **refused**, naming the
missing prerequisite. Storing a guess would mis-water every growspace the
recipe is later applied to, with correct-looking numbers on screen — the
failure ADR-0045 exists to prevent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from custom_components.growspace_manager.const import ShotSizingMode
from custom_components.growspace_manager.models.irrigation_recipe import (
    CropSteeringRecipe,
    RecipeProvenance,
    ScheduleRecipe,
)

from .shot_sizing import seconds_to_percent

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import (
        IrrigationConfig,
        IrrigationStrategy,
    )
    from custom_components.growspace_manager.models.types import IrrigationScheduleItem

__all__ = [
    "RecipeCaptureError",
    "capture_crop_steering",
    "capture_provenance",
    "capture_schedule",
]


class RecipeCaptureError(ValueError):
    """A growspace whose settings cannot honestly become a recipe."""


def capture_provenance(
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    *,
    stage: str | None,
    week: int,
) -> RecipeProvenance:
    """Stamp the authoring context onto a recipe.

    Descriptive only — it warns and sorts, it never gates (CONTEXT.md
    "[[Recipe Provenance]]"). ``stage``/``week`` come from
    ``resolve_feed_stage_week`` so one tent never reports two different weeks.
    """
    return RecipeProvenance(
        media_type=strategy.substrate_profile.media_type,
        liters_per_pot=strategy.substrate_profile.liters_per_pot,
        pump_flow_rate_ml_per_sec=config.pump_flow_rate_ml_per_sec,
        stage=stage,
        week=week,
    )


def capture_crop_steering(
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    *,
    live_plant_count: int,
) -> CropSteeringRecipe:
    """Capture the crop-steering setpoints, shot sizes substrate-relative.

    In Volume Mode the percents are already the stored truth and are copied
    verbatim. In Seconds Mode they are derived from the configured seconds
    against this growspace's flow rate and pot volume, and the capture is
    refused when a prerequisite for that derivation is missing.

    Raises:
        RecipeCaptureError: naming the missing prerequisite, when a Seconds
            Mode growspace has no pump flow rate, no per-pot substrate volume,
            or no live plants to divide back out.
    """
    if strategy.shot_sizing_mode is ShotSizingMode.VOLUME:
        p1_percent = strategy.p1_shot_volume_percent
        p2_percent = strategy.p2_shot_volume_percent
    else:
        p1_percent = _derive_percent(
            strategy.p1_shot_duration_seconds,
            strategy=strategy,
            config=config,
            live_plant_count=live_plant_count,
        )
        p2_percent = _derive_percent(
            strategy.p2_shot_duration_seconds,
            strategy=strategy,
            config=config,
            live_plant_count=live_plant_count,
        )

    return CropSteeringRecipe(
        lights_on_time=strategy.lights_on_time,
        p0_duration_minutes=strategy.p0_duration_minutes,
        p2_stop_before_lights_off_minutes=(strategy.p2_stop_before_lights_off_minutes),
        target_vwc_percent=strategy.target_vwc_percent,
        maintenance_dryback_percent=strategy.maintenance_dryback_percent,
        p1_shot_volume_percent=p1_percent,
        p1_shot_interval_minutes=strategy.p1_shot_interval_minutes,
        p2_shot_volume_percent=p2_percent,
        p2_shot_interval_minutes=strategy.p2_shot_interval_minutes,
        auto_light_tracking=strategy.auto_light_tracking,
        dynamic_shot_enabled=strategy.dynamic_shot_enabled,
        dynamic_aggressiveness=strategy.dynamic_aggressiveness,
        dynamic_recovery=strategy.dynamic_recovery,
        dynamic_shot_size_floor=strategy.dynamic_shot_size_floor,
        dynamic_interval_ceiling=strategy.dynamic_interval_ceiling,
        pore_ec_target_min=strategy.pore_ec_target_min,
        pore_ec_target_max=strategy.pore_ec_target_max,
        ec_modulation_enabled=strategy.ec_modulation_enabled,
    )


def capture_schedule(config: IrrigationConfig) -> ScheduleRecipe:
    """Capture the time-schedule half.

    A plain copy: schedule times carry no growspace-specific units, so nothing
    here needs converting. The pump entities that execute them stay behind.
    """
    return ScheduleRecipe(
        irrigation_times=[_copy_item(item) for item in config.irrigation_times],
        drain_times=[_copy_item(item) for item in config.drain_times],
        irrigation_duration=config.irrigation_duration,
        drain_duration=config.drain_duration,
        daily_volume_cap_liters=config.daily_volume_cap_liters,
        max_cycles_per_day=config.max_cycles_per_day,
        skip_during_dark=config.skip_during_dark,
    )


def _copy_item(item: IrrigationScheduleItem) -> IrrigationScheduleItem:
    """Return a detached copy so a later growspace edit cannot rewrite a recipe."""
    return cast("IrrigationScheduleItem", dict(item))


def _derive_percent(
    seconds: int,
    *,
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    live_plant_count: int,
) -> float:
    """Recover the per-pot percent a Seconds Mode growspace's shot delivers."""
    missing = _missing_prerequisite(strategy, config, live_plant_count)
    if missing is not None:
        raise RecipeCaptureError(
            "Cannot save an irrigation recipe from a growspace in Seconds Shot "
            f"Sizing Mode: {missing}. Shot sizes are stored as a percent of "
            "substrate volume, which cannot be derived without it."
        )
    percent = seconds_to_percent(
        seconds,
        liters_per_pot=strategy.substrate_profile.liters_per_pot,
        live_plant_count=live_plant_count,
        flow_rate_ml_per_sec=config.pump_flow_rate_ml_per_sec,
    )
    # _missing_prerequisite already rejected every input that returns None.
    assert percent is not None
    return percent


def _missing_prerequisite(
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    live_plant_count: int,
) -> str | None:
    """Name the first prerequisite the seconds → percent recovery lacks."""
    if config.pump_flow_rate_ml_per_sec <= 0.0:
        return "no pump flow rate is configured"
    if strategy.substrate_profile.liters_per_pot <= 0.0:
        return "no substrate volume per pot is configured"
    if live_plant_count <= 0:
        return "the growspace holds no live plants"
    return None
