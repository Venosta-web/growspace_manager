"""Tests for Irrigation Recipe capture (ADR-0045)."""

import pytest

from custom_components.growspace_manager.const import (
    IrrigationRecipeKind,
    ShotSizingMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.domain.irrigation_recipe import (
    CROP_STEERING_RECIPE_EDIT_FIELDS,
    SCHEDULE_RECIPE_EDIT_FIELDS,
    RecipeApplyError,
    RecipeCaptureError,
    RecipeEditError,
    RecipeKindMismatchError,
    capture_crop_steering,
    capture_provenance,
    capture_schedule,
    edit_recipe,
    recipe_has_drifted,
    resolve_recipe_application,
)
from custom_components.growspace_manager.domain.shot_sizing import percent_to_seconds
from custom_components.growspace_manager.models import (
    ECTargetRange,
    IrrigationConfig,
    IrrigationStrategy,
    SubstrateProfile,
)
from custom_components.growspace_manager.models.irrigation_recipe import (
    CropSteeringRecipe,
    IrrigationRecipe,
    RecipeProvenance,
    ScheduleRecipe,
)
from custom_components.growspace_manager.schemas import (
    CROP_STEERING_RECIPE_VALUES_SCHEMA,
    SCHEDULE_RECIPE_VALUES_SCHEMA,
)


def _strategy(**overrides) -> IrrigationStrategy:
    """Return a strategy with a usable substrate profile."""
    strategy = IrrigationStrategy(
        substrate_profile=SubstrateProfile(
            media_type=SubstrateMediaType.COCO, liters_per_pot=6.0
        ),
    )
    for key, value in overrides.items():
        setattr(strategy, key, value)
    return strategy


def _config(**overrides) -> IrrigationConfig:
    """Return a config with a measured pump flow rate."""
    config = IrrigationConfig(pump_flow_rate_ml_per_sec=50.0)
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


# --- Volume Mode: the percent is already the stored truth ------------------


def test_volume_mode_stores_the_percent_values_directly() -> None:
    """Nothing is derived when the growspace already thinks in percent."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.VOLUME,
        p1_shot_volume_percent=3.5,
        p2_shot_volume_percent=6.25,
    )

    recipe = capture_crop_steering(strategy, _config(), live_plant_count=4)

    assert recipe.p1_shot_volume_percent == 3.5
    assert recipe.p2_shot_volume_percent == 6.25


def test_volume_mode_needs_no_live_plants() -> None:
    """An empty tent can still author a Volume Mode recipe."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.VOLUME, p1_shot_volume_percent=4.0
    )

    recipe = capture_crop_steering(strategy, _config(), live_plant_count=0)

    assert recipe.p1_shot_volume_percent == 4.0


# --- Seconds Mode: the percent is recovered --------------------------------


def test_seconds_mode_derives_the_percent_from_the_growspace_plumbing() -> None:
    """12s at 50 ml/s into 6 L pots is 600 ml, i.e. 10% of one pot."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.SECONDS,
        p1_shot_duration_seconds=12,
        p2_shot_duration_seconds=6,
    )

    recipe = capture_crop_steering(strategy, _config(), live_plant_count=1)

    assert recipe.p1_shot_volume_percent == pytest.approx(10.0)
    assert recipe.p2_shot_volume_percent == pytest.approx(5.0)


@pytest.mark.parametrize("live_plant_count", [1, 4, 12])
def test_derived_percent_is_computed_plant_count_independently(
    live_plant_count,
) -> None:
    """Two tents dosing the same per-pot percent recover that same percent.

    They need different seconds to do it — the forward conversion multiplies
    the live count in — so the inverse must divide it back out. Skipping that
    division would stamp the source tent's plant count into the stored value
    and mis-water every growspace the recipe is later applied to.
    """
    # 5% of a 6 L pot is 300 ml, an exact 6 s at 50 ml/s, so the round trip
    # is not blunted by the forward direction rounding to whole pump seconds.
    seconds = percent_to_seconds(
        5.0,
        liters_per_pot=6.0,
        live_plant_count=live_plant_count,
        flow_rate_ml_per_sec=50.0,
    )
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.SECONDS, p1_shot_duration_seconds=seconds
    )

    recipe = capture_crop_steering(
        strategy, _config(), live_plant_count=live_plant_count
    )

    assert recipe.p1_shot_volume_percent == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("strategy_kwargs", "config_kwargs", "live_plant_count", "expected_phrase"),
    [
        ({}, {"pump_flow_rate_ml_per_sec": 0.0}, 4, "no pump flow rate"),
        (
            {"substrate_profile": SubstrateProfile(liters_per_pot=0.0)},
            {},
            4,
            "no substrate volume per pot",
        ),
        ({}, {}, 0, "no live plants"),
    ],
)
def test_seconds_mode_refuses_and_names_the_missing_prerequisite(
    strategy_kwargs, config_kwargs, live_plant_count, expected_phrase
) -> None:
    """The refusal says which input is missing, not just that it failed."""
    strategy = _strategy(shot_sizing_mode=ShotSizingMode.SECONDS, **strategy_kwargs)

    with pytest.raises(RecipeCaptureError) as err:
        capture_crop_steering(
            strategy, _config(**config_kwargs), live_plant_count=live_plant_count
        )

    assert expected_phrase in str(err.value)


# --- What a recipe deliberately leaves behind ------------------------------


def test_crop_steering_recipe_excludes_hardware_live_state_and_feed_ec() -> None:
    """The named exclusions are structurally absent, not merely unset."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.VOLUME,
        detected_lights_on_time="05:12:00",
        enabled=True,
    )
    config = _config(
        irrigation_pump_entity="switch.pump",
        drain_pump_entity="switch.drain",
        active_steering_phase="p1",
        phase_changed_at="2026-08-11T09:00:00+00:00",
        ec_target_ranges=[ECTargetRange(stage="flower", feed_ec_min=1.0)],
    )

    stored = capture_crop_steering(strategy, config, live_plant_count=4).to_dict()

    for excluded in (
        "irrigation_pump_entity",
        "drain_pump_entity",
        "active_steering_phase",
        "phase_changed_at",
        "detected_lights_on_time",
        "ec_target_ranges",
        "enabled",
        "declared_steering_mode",
        "p1_shot_duration_seconds",
        "p2_shot_duration_seconds",
    ):
        assert excluded not in stored


def test_schedule_recipe_carries_the_times_and_leaves_the_pumps_behind() -> None:
    """The schedule half is when to fire, never what fires it."""
    config = _config(
        irrigation_times=[{"time": "08:00:00", "duration": 30}],
        drain_times=[{"time": "20:00:00", "duration": 10}],
        irrigation_duration=30,
        drain_duration=10,
        daily_volume_cap_liters=12.5,
        max_cycles_per_day=6,
        skip_during_dark=True,
        irrigation_pump_entity="switch.pump",
        ec_target_ranges=[ECTargetRange(stage="flower", feed_ec_min=1.0)],
    )

    recipe = capture_schedule(config)
    stored = recipe.to_dict()

    assert recipe.irrigation_times == [{"time": "08:00:00", "duration": 30}]
    assert recipe.daily_volume_cap_liters == 12.5
    assert recipe.max_cycles_per_day == 6
    assert recipe.skip_during_dark is True
    for excluded in ("irrigation_pump_entity", "drain_pump_entity", "ec_target_ranges"):
        assert excluded not in stored


def test_captured_schedule_times_do_not_alias_the_growspace() -> None:
    """A later edit to the growspace must not rewrite a saved recipe."""
    config = _config(irrigation_times=[{"time": "08:00:00", "duration": 30}])

    recipe = capture_schedule(config)
    config.irrigation_times[0]["duration"] = 999

    assert recipe.irrigation_times[0]["duration"] == 30


# --- Provenance -------------------------------------------------------------


def test_provenance_records_the_authoring_context() -> None:
    """Media, pot volume, flow rate and the week it was authored in."""
    strategy = _strategy(
        substrate_profile=SubstrateProfile(
            media_type=SubstrateMediaType.ROCKWOOL, liters_per_pot=3.0
        )
    )

    provenance = capture_provenance(strategy, _config(), stage="flower", week=3)

    assert provenance.media_type is SubstrateMediaType.ROCKWOOL
    assert provenance.liters_per_pot == 3.0
    assert provenance.pump_flow_rate_ml_per_sec == 50.0
    assert provenance.stage == "flower"
    assert provenance.week == 3


# --- Applying: the Recipe Stamp resolution --------------------------------


def _steering_recipe(**overrides) -> IrrigationRecipe:
    """Return a crop-steering recipe authored in coco."""
    half = CropSteeringRecipe(p1_shot_volume_percent=4.0, p2_shot_volume_percent=3.0)
    for key, value in overrides.pop("crop_steering", {}).items():
        setattr(half, key, value)
    recipe = IrrigationRecipe(
        id="recipe-1",
        name="Flower week 3",
        kind=IrrigationRecipeKind.CROP_STEERING,
        provenance=RecipeProvenance(
            media_type=SubstrateMediaType.COCO,
            liters_per_pot=6.0,
            pump_flow_rate_ml_per_sec=50.0,
        ),
        crop_steering=half,
    )
    for key, value in overrides.items():
        setattr(recipe, key, value)
    return recipe


def _schedule_recipe(**overrides) -> IrrigationRecipe:
    """Return a schedule recipe authored in coco."""
    recipe = IrrigationRecipe(
        id="recipe-2",
        name="Veg timer",
        kind=IrrigationRecipeKind.SCHEDULE,
        provenance=RecipeProvenance(media_type=SubstrateMediaType.COCO),
        schedule=ScheduleRecipe(
            irrigation_times=[{"time": "07:30:00", "duration": 45}],
            drain_times=[{"time": "19:30:00", "duration": 20}],
            irrigation_duration=45,
            drain_duration=20,
            daily_volume_cap_liters=14.0,
            max_cycles_per_day=8,
            skip_during_dark=True,
        ),
    )
    for key, value in overrides.items():
        setattr(recipe, key, value)
    return recipe


def test_volume_mode_target_takes_the_percent_and_converts_nothing() -> None:
    """A Volume Mode tent stores the dose; the composer converts it live."""
    strategy = _strategy(enabled=True, shot_sizing_mode=ShotSizingMode.VOLUME)

    application = resolve_recipe_application(
        _steering_recipe(), strategy=strategy, config=_config(), live_plant_count=4
    )

    assert application.values["p1_shot_volume_percent"] == 4.0
    assert application.values["p2_shot_volume_percent"] == 3.0
    assert "p1_shot_duration_seconds" not in application.values


def test_seconds_mode_target_gets_its_own_pump_seconds() -> None:
    """The percent is re-expressed in this tent's plumbing, not copied."""
    strategy = _strategy(enabled=True, shot_sizing_mode=ShotSizingMode.SECONDS)

    application = resolve_recipe_application(
        _steering_recipe(), strategy=strategy, config=_config(), live_plant_count=4
    )

    assert application.values["p1_shot_duration_seconds"] == percent_to_seconds(
        4.0, liters_per_pot=6.0, live_plant_count=4, flow_rate_ml_per_sec=50.0
    )
    # The portable percent is written too, so switching the tent to Volume
    # Mode later still finds the recipe's dose rather than a stale default.
    assert application.values["p1_shot_volume_percent"] == 4.0


def test_two_growspaces_get_different_seconds_for_one_percent() -> None:
    """Different plumbing and pot size is exactly what the percent survives."""
    recipe = _steering_recipe()
    small = _strategy(
        enabled=True,
        shot_sizing_mode=ShotSizingMode.SECONDS,
        substrate_profile=SubstrateProfile(
            media_type=SubstrateMediaType.COCO, liters_per_pot=6.0
        ),
    )
    large = _strategy(
        enabled=True,
        shot_sizing_mode=ShotSizingMode.SECONDS,
        substrate_profile=SubstrateProfile(
            media_type=SubstrateMediaType.COCO, liters_per_pot=12.0
        ),
    )

    small_values = resolve_recipe_application(
        recipe,
        strategy=small,
        config=_config(pump_flow_rate_ml_per_sec=50.0),
        live_plant_count=4,
    ).values
    large_values = resolve_recipe_application(
        recipe,
        strategy=large,
        config=_config(pump_flow_rate_ml_per_sec=25.0),
        live_plant_count=4,
    ).values

    assert (
        small_values["p1_shot_duration_seconds"]
        != large_values["p1_shot_duration_seconds"]
    )
    assert (
        small_values["p1_shot_volume_percent"]
        == large_values["p1_shot_volume_percent"]
        == 4.0
    )


def test_schedule_recipe_resolves_onto_the_irrigation_config() -> None:
    """The schedule half writes config fields, and no strategy field at all."""
    application = resolve_recipe_application(
        _schedule_recipe(),
        strategy=_strategy(enabled=False),
        config=_config(),
        live_plant_count=0,
    )

    assert application.values == {}
    assert application.config_values["irrigation_times"] == [
        {"time": "07:30:00", "duration": 45}
    ]
    assert application.config_values["max_cycles_per_day"] == 8
    assert application.config_values["skip_during_dark"] is True


def test_resolved_schedule_times_do_not_alias_the_recipe() -> None:
    """A later growspace edit must not reach back into the shared recipe."""
    recipe = _schedule_recipe()

    application = resolve_recipe_application(
        recipe,
        strategy=_strategy(enabled=False),
        config=_config(),
        live_plant_count=0,
    )
    application.config_values["irrigation_times"][0]["duration"] = 999

    assert recipe.schedule is not None
    assert recipe.schedule.irrigation_times[0]["duration"] == 45


def test_schedule_recipe_on_a_crop_steering_growspace_is_refused() -> None:
    """Wrong half: refused outright, and nothing is resolved to write."""
    with pytest.raises(RecipeKindMismatchError) as err:
        resolve_recipe_application(
            _schedule_recipe(),
            strategy=_strategy(enabled=True),
            config=_config(),
            live_plant_count=4,
        )

    assert "schedule" in str(err.value)
    assert "crop_steering" in str(err.value)


def test_crop_steering_recipe_on_a_scheduled_growspace_is_refused() -> None:
    """And the reverse, by the same one rule."""
    with pytest.raises(RecipeKindMismatchError):
        resolve_recipe_application(
            _steering_recipe(),
            strategy=_strategy(enabled=False),
            config=_config(),
            live_plant_count=4,
        )


@pytest.mark.parametrize(
    ("config_kwargs", "profile", "live_plant_count", "expected"),
    [
        ({"pump_flow_rate_ml_per_sec": 0.0}, None, 4, "no pump flow rate"),
        (
            {},
            SubstrateProfile(media_type=SubstrateMediaType.COCO, liters_per_pot=0.0),
            4,
            "no substrate volume per pot",
        ),
        ({}, None, 0, "no live plants"),
    ],
)
def test_seconds_mode_apply_refuses_and_names_the_missing_prerequisite(
    config_kwargs: dict, profile: SubstrateProfile | None, live_plant_count, expected
) -> None:
    """Seconds cannot be invented, so the apply says which input is absent."""
    strategy = _strategy(enabled=True, shot_sizing_mode=ShotSizingMode.SECONDS)
    if profile is not None:
        strategy.substrate_profile = profile

    with pytest.raises(RecipeApplyError) as err:
        resolve_recipe_application(
            _steering_recipe(),
            strategy=strategy,
            config=_config(**config_kwargs),
            live_plant_count=live_plant_count,
        )

    assert expected in str(err.value)


def test_seconds_mode_apply_refuses_a_zero_percent_shot() -> None:
    """A recipe that yields no pump duration is a refusal, not a zero write."""
    recipe = _steering_recipe(crop_steering={"p1_shot_volume_percent": 0.0})

    with pytest.raises(RecipeApplyError) as err:
        resolve_recipe_application(
            recipe,
            strategy=_strategy(enabled=True, shot_sizing_mode=ShotSizingMode.SECONDS),
            config=_config(),
            live_plant_count=4,
        )

    assert "P1" in str(err.value)


@pytest.mark.parametrize(
    ("kind", "field_name"),
    [
        (IrrigationRecipeKind.CROP_STEERING, "crop_steering"),
        (IrrigationRecipeKind.SCHEDULE, "schedule"),
    ],
)
def test_a_recipe_missing_its_declared_half_is_refused(kind, field_name) -> None:
    """A corrupt stored recipe refuses rather than stamping an empty half."""
    recipe = _steering_recipe() if field_name == "crop_steering" else _schedule_recipe()
    setattr(recipe, field_name, None)
    enabled = kind is IrrigationRecipeKind.CROP_STEERING

    with pytest.raises(RecipeApplyError):
        resolve_recipe_application(
            recipe,
            strategy=_strategy(enabled=enabled, shot_sizing_mode=ShotSizingMode.VOLUME),
            config=_config(),
            live_plant_count=4,
        )


# --- The media mismatch warns; it never scales and never refuses -----------


def test_matching_media_warns_about_nothing() -> None:
    """The ordinary case carries no warning to dismiss."""
    application = resolve_recipe_application(
        _steering_recipe(),
        strategy=_strategy(enabled=True, shot_sizing_mode=ShotSizingMode.VOLUME),
        config=_config(),
        live_plant_count=4,
    )

    assert application.media_warning is None


def test_cross_media_apply_warns_naming_both_and_scales_nothing() -> None:
    """Pot size normalises across growspaces; media does not (ADR-0045)."""
    strategy = _strategy(
        enabled=True,
        shot_sizing_mode=ShotSizingMode.VOLUME,
        substrate_profile=SubstrateProfile(
            media_type=SubstrateMediaType.ROCKWOOL, liters_per_pot=6.0
        ),
    )

    application = resolve_recipe_application(
        _steering_recipe(), strategy=strategy, config=_config(), live_plant_count=4
    )

    assert application.media_warning is not None
    assert "coco" in application.media_warning
    assert "rockwool" in application.media_warning
    assert application.values["p1_shot_volume_percent"] == 4.0


# --- Drift: computed on read, never stored --------------------------------


def test_a_freshly_stamped_growspace_has_not_drifted() -> None:
    """What the stamp would write is what is there."""
    strategy = _strategy(enabled=True, shot_sizing_mode=ShotSizingMode.VOLUME)
    recipe = _steering_recipe()
    application = resolve_recipe_application(
        recipe, strategy=strategy, config=_config(), live_plant_count=4
    )
    for name, value in application.values.items():
        setattr(strategy, name, value)

    assert not recipe_has_drifted(
        recipe, strategy=strategy, config=_config(), live_plant_count=4
    )


def test_one_hand_tweak_is_drift() -> None:
    """The whole question the card asks, answered from live fields."""
    strategy = _strategy(enabled=True, shot_sizing_mode=ShotSizingMode.VOLUME)
    recipe = _steering_recipe()
    application = resolve_recipe_application(
        recipe, strategy=strategy, config=_config(), live_plant_count=4
    )
    for name, value in application.values.items():
        setattr(strategy, name, value)
    strategy.p2_shot_interval_minutes += 5

    assert recipe_has_drifted(
        recipe, strategy=strategy, config=_config(), live_plant_count=4
    )


def test_schedule_drift_reads_the_irrigation_config() -> None:
    """The schedule half's drift lives on the config, not the strategy."""
    recipe = _schedule_recipe()
    strategy = _strategy(enabled=False)
    config = _config()
    application = resolve_recipe_application(
        recipe, strategy=strategy, config=config, live_plant_count=0
    )
    for name, value in application.config_values.items():
        setattr(config, name, value)
    assert not recipe_has_drifted(
        recipe, strategy=strategy, config=config, live_plant_count=0
    )

    config.max_cycles_per_day = 3

    assert recipe_has_drifted(
        recipe, strategy=strategy, config=config, live_plant_count=0
    )


def test_a_recipe_that_no_longer_resolves_counts_as_drifted() -> None:
    """Switching halves means what is there is not what the recipe says."""
    recipe = _steering_recipe()

    assert recipe_has_drifted(
        recipe,
        strategy=_strategy(enabled=False),
        config=_config(),
        live_plant_count=4,
    )


# --- Editing a stored recipe (#109) ----------------------------------------


def test_a_rename_leaves_the_values_alone() -> None:
    """Renaming is a whole edit; nothing else needs supplying."""
    recipe = _steering_recipe()

    edited = edit_recipe(recipe, name="Flower week 4")

    assert edited.name == "Flower week 4"
    assert edited.crop_steering == recipe.crop_steering


def test_a_name_is_stripped() -> None:
    """Surrounding whitespace is not part of what the grower typed."""
    assert edit_recipe(_steering_recipe(), name="  Flower  ").name == "Flower"


def test_a_blank_name_is_refused() -> None:
    """A nameless recipe cannot be picked out of a library."""
    with pytest.raises(RecipeEditError, match="cannot be blank"):
        edit_recipe(_steering_recipe(), name="   ")


def test_values_are_sparse() -> None:
    """A field the mapping does not name keeps what the recipe stores."""
    recipe = _steering_recipe()

    edited = edit_recipe(recipe, crop_steering={"p1_shot_volume_percent": 7.5})

    assert edited.crop_steering is not None
    assert edited.crop_steering.p1_shot_volume_percent == 7.5
    assert edited.crop_steering.p2_shot_volume_percent == 3.0


def test_the_schedule_half_edits_the_same_way() -> None:
    """Both halves are editable through the one entry point."""
    edited = edit_recipe(_schedule_recipe(), schedule={"skip_during_dark": False})

    assert edited.schedule is not None
    assert edited.schedule.skip_during_dark is False
    assert edited.schedule.max_cycles_per_day == 8


def test_identity_kind_created_at_and_provenance_are_untouched() -> None:
    """An edit reaches the name and the values, and nothing else."""
    recipe = _steering_recipe()

    edited = edit_recipe(
        recipe, name="Renamed", crop_steering={"target_vwc_percent": 61.0}
    )

    assert edited.id == recipe.id
    assert edited.kind is recipe.kind
    assert edited.created_at == recipe.created_at
    assert edited.provenance == recipe.provenance


def test_the_source_recipe_is_not_mutated() -> None:
    """Pure: the caller decides whether the edit is stored."""
    recipe = _steering_recipe()

    edit_recipe(recipe, name="Renamed", crop_steering={"target_vwc_percent": 61.0})

    assert recipe.name == "Flower week 3"
    assert recipe.crop_steering is not None
    assert recipe.crop_steering.target_vwc_percent != 61.0


def test_editing_the_half_the_kind_is_not_is_refused() -> None:
    """A crop-steering recipe has no schedule values to correct."""
    with pytest.raises(RecipeEditError, match="no schedule values"):
        edit_recipe(_steering_recipe(), schedule={"skip_during_dark": True})


def test_editing_the_other_half_the_other_way_round_is_refused() -> None:
    """And a schedule recipe has no setpoints."""
    with pytest.raises(RecipeEditError, match="no crop_steering values"):
        edit_recipe(_schedule_recipe(), crop_steering={"target_vwc_percent": 61.0})


def test_an_unknown_field_is_refused() -> None:
    """Naming a field the half does not store refuses the whole edit."""
    with pytest.raises(RecipeEditError, match="liters_per_pot is not part of"):
        edit_recipe(_steering_recipe(), crop_steering={"liters_per_pot": 9.0})


def test_provenance_is_not_reachable_as_a_value() -> None:
    """Provenance describes what happened; an edit cannot rewrite it."""
    with pytest.raises(RecipeEditError, match="media_type"):
        edit_recipe(_steering_recipe(), crop_steering={"media_type": "rockwool"})


def test_a_refused_edit_builds_nothing() -> None:
    """Every refusal is raised before the name is applied, not after."""
    recipe = _steering_recipe()

    with pytest.raises(RecipeEditError):
        edit_recipe(recipe, name="Renamed", crop_steering={"nope": 1})

    assert recipe.name == "Flower week 3"


@pytest.mark.parametrize(
    ("kind", "half", "values"),
    [
        (
            IrrigationRecipeKind.CROP_STEERING,
            "crop_steering",
            {"target_vwc_percent": 61.0},
        ),
        (IrrigationRecipeKind.SCHEDULE, "schedule", {"skip_during_dark": True}),
    ],
)
def test_a_recipe_missing_its_declared_half_cannot_be_edited(
    kind, half, values
) -> None:
    """A corrupt library entry refuses rather than growing a half from defaults.

    Both halves, because the guard is what stops a missing half being silently
    replaced by a dataclass full of defaults — a recipe that would then apply
    setpoints nobody authored.
    """
    recipe = IrrigationRecipe(id="recipe-3", name="Half-less", kind=kind)

    with pytest.raises(RecipeEditError, match=f"holds no {half} half"):
        edit_recipe(recipe, **{half: values})


def test_editing_no_field_at_all_is_a_no_op_copy() -> None:
    """The degenerate call is total, not an error."""
    recipe = _steering_recipe()

    assert edit_recipe(recipe) == recipe


def test_the_transport_schemas_accept_exactly_the_editable_fields() -> None:
    """The voluptuous surface and the editable field sets are one list.

    ``domain`` derives what an edit may write from the halves themselves,
    while ``schemas.py`` hand-lists the same names to give each one a type.
    A field in the dataclass but not the schema would be silently uneditable
    — the quietest possible failure — so the two are pinned together here.
    """
    for vol_schema, editable in (
        (CROP_STEERING_RECIPE_VALUES_SCHEMA, CROP_STEERING_RECIPE_EDIT_FIELDS),
        (SCHEDULE_RECIPE_VALUES_SCHEMA, SCHEDULE_RECIPE_EDIT_FIELDS),
    ):
        assert {str(key) for key in vol_schema.schema} == editable
