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

The same module owns the other direction — resolving a recipe *into* a target
growspace ([[Recipe Stamp]]) — because both directions share the one rule
about what a stored percent means, and splitting them would let the two halves
disagree about it. ``resolve_recipe_application`` answers what a stamp would
write; ``recipe_has_drifted`` asks the same question and compares the answer
against what is there, which is why no drift hash is ever stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, fields as dataclass_fields, replace
from typing import TYPE_CHECKING, Any, cast

from custom_components.growspace_manager.const import (
    IrrigationRecipeKind,
    ShotSizingMode,
)
from custom_components.growspace_manager.models.irrigation_recipe import (
    CropSteeringRecipe,
    RecipeProvenance,
    ScheduleRecipe,
)

from .shot_sizing import percent_to_seconds, seconds_to_percent

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import (
        IrrigationConfig,
        IrrigationStrategy,
    )
    from custom_components.growspace_manager.models.irrigation_recipe import (
        IrrigationRecipe,
    )
    from custom_components.growspace_manager.models.types import IrrigationScheduleItem

__all__ = [
    "CROP_STEERING_RECIPE_EDIT_FIELDS",
    "SCHEDULE_RECIPE_EDIT_FIELDS",
    "RecipeApplication",
    "RecipeApplyError",
    "RecipeCaptureError",
    "RecipeEditError",
    "RecipeKindMismatchError",
    "capture_crop_steering",
    "capture_provenance",
    "capture_schedule",
    "edit_recipe",
    "recipe_has_drifted",
    "resolve_recipe_application",
]


class RecipeCaptureError(ValueError):
    """A growspace whose settings cannot honestly become a recipe."""


class RecipeEditError(ValueError):
    """A payload that cannot become an edit to a stored recipe."""


class RecipeApplyError(ValueError):
    """A recipe that cannot honestly be applied to this growspace."""


class RecipeKindMismatchError(RecipeApplyError):
    """The recipe holds the half this growspace is not running.

    A crop-steering recipe carries setpoints only the VWC coordinator reads
    and a schedule recipe carries times only the time-based one reads, so
    applying either to the other half's growspace would write fields nothing
    acts on while leaving the running half untouched. Refused outright rather
    than half-applied (ADR-0045).
    """


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


# ---------------------------------------------------------------------------
# Editing a stored recipe
# ---------------------------------------------------------------------------

# The fields an edit may write, taken from the halves themselves so a new
# setpoint is editable the moment it is stored rather than the moment someone
# remembers to widen a hand-written list.
CROP_STEERING_RECIPE_EDIT_FIELDS: frozenset[str] = frozenset(
    f.name for f in dataclass_fields(CropSteeringRecipe)
)
SCHEDULE_RECIPE_EDIT_FIELDS: frozenset[str] = frozenset(
    f.name for f in dataclass_fields(ScheduleRecipe)
)


def edit_recipe(
    recipe: IrrigationRecipe,
    *,
    name: str | None = None,
    crop_steering: Mapping[str, Any] | None = None,
    schedule: Mapping[str, Any] | None = None,
) -> IrrigationRecipe:
    """Return ``recipe`` with a corrected name and/or corrected stored values.

    The counterpart to capture: capture asks a growspace what its settings are,
    this asks the grower what the recipe should have said. Both live here
    because both answer the same question about what a stored percent means —
    an edit sets a percent of substrate volume, never pump seconds, so unlike
    capture it has no plumbing to recover from and no refusal path.

    What an edit cannot touch is the point of the operation. ``id``, ``kind``,
    ``created_at`` and every [[Recipe Provenance]] field are absent from the
    signature rather than merely ignored: provenance records where the recipe
    came from, and rewriting it would turn a description of something that
    happened into a claim about something that did not. Switching ``kind``
    would be a capture, not an edit — a recipe carries exactly one half by
    design, and the other one does not exist to be filled in.

    Values are **sparse**: a field the mapping does not name keeps what it
    stores. That is what lets a card built against an older contract correct
    one shot size without silently resetting a setpoint it never knew about.

    Pure, and total in the sense that matters: every refusal is raised before
    anything is built, so a caller that stores the result stores either the
    whole edit or none of it.

    Raises:
        RecipeEditError: for a blank name, the half this recipe's ``kind`` is
            not, a half the recipe does not hold, or an unknown field name.
    """
    if crop_steering is not None:
        _refuse_wrong_half(recipe, IrrigationRecipeKind.CROP_STEERING, "crop_steering")
    if schedule is not None:
        _refuse_wrong_half(recipe, IrrigationRecipeKind.SCHEDULE, "schedule")

    changes: dict[str, Any] = {}

    if name is not None:
        stripped = name.strip()
        if not stripped:
            raise RecipeEditError("A recipe's name cannot be blank.")
        changes["name"] = stripped

    if crop_steering is not None:
        if recipe.crop_steering is None:
            raise RecipeEditError(
                f"Recipe '{recipe.id}' holds no crop_steering half to edit."
            )
        _refuse_unknown_fields(
            crop_steering, CROP_STEERING_RECIPE_EDIT_FIELDS, "crop_steering"
        )
        changes["crop_steering"] = replace(recipe.crop_steering, **dict(crop_steering))

    if schedule is not None:
        if recipe.schedule is None:
            raise RecipeEditError(
                f"Recipe '{recipe.id}' holds no schedule half to edit."
            )
        _refuse_unknown_fields(schedule, SCHEDULE_RECIPE_EDIT_FIELDS, "schedule")
        changes["schedule"] = replace(recipe.schedule, **dict(schedule))

    return replace(recipe, **changes)


def _refuse_wrong_half(
    recipe: IrrigationRecipe, required: IrrigationRecipeKind, label: str
) -> None:
    """Refuse an edit naming the half this recipe's kind is not."""
    if recipe.kind is not required:
        raise RecipeEditError(
            f"Recipe '{recipe.id}' is a {recipe.kind.value} recipe; it has no "
            f"{label} values to edit."
        )


def _refuse_unknown_fields(
    values: Mapping[str, Any], accepted: frozenset[str], label: str
) -> None:
    """Refuse an edit naming a field the half does not store."""
    unknown = sorted(set(values) - accepted)
    if unknown:
        raise RecipeEditError(
            f"{', '.join(unknown)} "
            f"{'are' if len(unknown) > 1 else 'is'} not part of a {label} recipe."
        )


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


@dataclass(frozen=True, slots=True)
class RecipeApplication:
    """What stamping one recipe into one growspace resolves to.

    ``values`` are ``IrrigationStrategy`` fields and ``config_values`` are
    ``IrrigationConfig`` fields, because a recipe's two halves live on two
    models: the crop-steering setpoints are strategy, the schedule times are
    config. Exactly one of the two is ever populated — the kinds are disjoint.

    ``media_warning`` is set when the recipe was authored in a different
    medium than the target's. The apply still proceeds and the values are
    **not** scaled: pot size normalises, media does not, and a coco→rockwool
    coefficient would dress up a guess as a conversion (ADR-0045).
    """

    values: dict[str, Any] = field(default_factory=dict)
    config_values: dict[str, Any] = field(default_factory=dict)
    media_warning: str | None = None


def resolve_recipe_application(
    recipe: IrrigationRecipe,
    *,
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    live_plant_count: int,
) -> RecipeApplication:
    """Resolve what applying ``recipe`` to this growspace would write.

    Pure: it computes and refuses, it never writes. The [[Strategy Stamp]]
    seam owns the writing, and ``recipe_has_drifted`` calls this same function
    to ask what *should* be there — which is why no drift hash is stored.

    Shot sizes arrive as a percent of substrate volume and are re-expressed in
    the target's own units: a Volume Mode growspace stores the percent and
    converts it live, while a Seconds Mode one needs the pump seconds that
    percent delivers through *its* flow rate, *its* pot volume and *its* live
    plant count. The percents are written in both modes, so switching the
    target to Volume Mode later still finds the recipe's dose.

    Raises:
        RecipeKindMismatchError: when the recipe holds the half the growspace
            is not running. Nothing is resolved, so nothing is written.
        RecipeApplyError: when a Seconds Mode target cannot be given seconds
            honestly, naming the missing prerequisite.
    """
    running = (
        IrrigationRecipeKind.CROP_STEERING
        if strategy.enabled
        else IrrigationRecipeKind.SCHEDULE
    )
    if recipe.kind is not running:
        raise RecipeKindMismatchError(
            f"Cannot apply the {recipe.kind.value} irrigation recipe "
            f"'{recipe.name}' to a growspace running {running.value} "
            "irrigation. A recipe carries exactly one half and is never "
            "half-applied."
        )

    values: dict[str, Any] = {}
    config_values: dict[str, Any] = {}
    if recipe.kind is IrrigationRecipeKind.CROP_STEERING:
        values = _crop_steering_values(
            recipe,
            strategy=strategy,
            config=config,
            live_plant_count=live_plant_count,
        )
    else:
        config_values = _schedule_values(recipe)

    return RecipeApplication(
        values=values,
        config_values=config_values,
        media_warning=_media_warning(recipe, strategy=strategy),
    )


def recipe_has_drifted(
    recipe: IrrigationRecipe,
    *,
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    live_plant_count: int,
) -> bool:
    """Return whether the growspace still holds what ``recipe`` would stamp.

    The whole of "has the grower tweaked since applying?", computed on read
    from data already loaded. Nothing is stored at stamp time to compare
    against, because recipes are held by reference: a hash written then would
    go stale the moment the recipe itself was edited (ADR-0045).

    A recipe that cannot be resolved at all — the growspace has since switched
    halves, or a Seconds Mode target lost the flow rate its seconds need — has
    drifted by the same definition: what is there is not what the recipe says.

    In Seconds Mode the compared seconds move with the live plant count, so
    gaining or losing a plant reads as drift. That is the honest answer rather
    than a false negative: the configured seconds no longer deliver the
    recipe's per-pot dose.
    """
    try:
        application = resolve_recipe_application(
            recipe,
            strategy=strategy,
            config=config,
            live_plant_count=live_plant_count,
        )
    except RecipeApplyError:
        return True

    return any(
        getattr(strategy, name) != value for name, value in application.values.items()
    ) or any(
        getattr(config, name) != value
        for name, value in application.config_values.items()
    )


def _crop_steering_values(
    recipe: IrrigationRecipe,
    *,
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    live_plant_count: int,
) -> dict[str, Any]:
    """Resolve the crop-steering half onto strategy field names."""
    half = recipe.crop_steering
    if half is None:
        raise RecipeApplyError(
            f"Irrigation recipe '{recipe.name}' is declared crop_steering but "
            "carries no crop-steering settings."
        )

    values: dict[str, Any] = {
        "lights_on_time": half.lights_on_time,
        "p0_duration_minutes": half.p0_duration_minutes,
        "p2_stop_before_lights_off_minutes": half.p2_stop_before_lights_off_minutes,
        "target_vwc_percent": half.target_vwc_percent,
        "maintenance_dryback_percent": half.maintenance_dryback_percent,
        "p1_shot_volume_percent": half.p1_shot_volume_percent,
        "p1_shot_interval_minutes": half.p1_shot_interval_minutes,
        "p2_shot_volume_percent": half.p2_shot_volume_percent,
        "p2_shot_interval_minutes": half.p2_shot_interval_minutes,
        "auto_light_tracking": half.auto_light_tracking,
        "dynamic_shot_enabled": half.dynamic_shot_enabled,
        "dynamic_aggressiveness": half.dynamic_aggressiveness,
        "dynamic_recovery": half.dynamic_recovery,
        "dynamic_shot_size_floor": half.dynamic_shot_size_floor,
        "dynamic_interval_ceiling": half.dynamic_interval_ceiling,
        "pore_ec_target_min": half.pore_ec_target_min,
        "pore_ec_target_max": half.pore_ec_target_max,
        "ec_modulation_enabled": half.ec_modulation_enabled,
    }
    if strategy.shot_sizing_mode is ShotSizingMode.SECONDS:
        values["p1_shot_duration_seconds"] = _resolve_seconds(
            half.p1_shot_volume_percent,
            phase="P1",
            recipe=recipe,
            strategy=strategy,
            config=config,
            live_plant_count=live_plant_count,
        )
        values["p2_shot_duration_seconds"] = _resolve_seconds(
            half.p2_shot_volume_percent,
            phase="P2",
            recipe=recipe,
            strategy=strategy,
            config=config,
            live_plant_count=live_plant_count,
        )
    return values


def _schedule_values(recipe: IrrigationRecipe) -> dict[str, Any]:
    """Resolve the schedule half onto irrigation config field names."""
    half = recipe.schedule
    if half is None:
        raise RecipeApplyError(
            f"Irrigation recipe '{recipe.name}' is declared schedule but "
            "carries no schedule settings."
        )

    return {
        # Detached copies: a later edit to the growspace's schedule must not
        # reach back into the by-reference recipe every program shares.
        "irrigation_times": [_copy_item(item) for item in half.irrigation_times],
        "drain_times": [_copy_item(item) for item in half.drain_times],
        "irrigation_duration": half.irrigation_duration,
        "drain_duration": half.drain_duration,
        "daily_volume_cap_liters": half.daily_volume_cap_liters,
        "max_cycles_per_day": half.max_cycles_per_day,
        "skip_during_dark": half.skip_during_dark,
    }


def _media_warning(
    recipe: IrrigationRecipe, *, strategy: IrrigationStrategy
) -> str | None:
    """Name both media when the recipe was authored in a different one."""
    authored = recipe.provenance.media_type
    target = strategy.substrate_profile.media_type
    if authored is target:
        return None
    return (
        f"Irrigation recipe '{recipe.name}' was authored in {authored.value} "
        f"and applied to a {target.value} growspace. Values are applied "
        "unscaled: pot size normalises across growspaces, media does not."
    )


def _resolve_seconds(
    percent: float,
    *,
    phase: str,
    recipe: IrrigationRecipe,
    strategy: IrrigationStrategy,
    config: IrrigationConfig,
    live_plant_count: int,
) -> int:
    """Return the pump seconds this growspace needs for a recipe's shot size."""
    missing = _missing_prerequisite(strategy, config, live_plant_count)
    if missing is not None:
        raise RecipeApplyError(
            f"Cannot apply irrigation recipe '{recipe.name}' to a growspace in "
            f"Seconds Shot Sizing Mode: {missing}. The recipe stores shot sizes "
            "as a percent of substrate volume, which cannot be turned into pump "
            "seconds without it."
        )
    seconds = percent_to_seconds(
        percent,
        liters_per_pot=strategy.substrate_profile.liters_per_pot,
        live_plant_count=live_plant_count,
        flow_rate_ml_per_sec=config.pump_flow_rate_ml_per_sec,
    )
    if seconds is None:
        raise RecipeApplyError(
            f"Cannot apply irrigation recipe '{recipe.name}': its {phase} shot "
            "size is not a positive percent of substrate volume, so it yields "
            "no pump duration."
        )
    return seconds
