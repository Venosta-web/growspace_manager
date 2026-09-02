"""Tests for the global Irrigation Recipe library (ADR-0045)."""

from unittest.mock import AsyncMock

import pytest

from custom_components.growspace_manager.const import (
    IrrigationRecipeKind,
    PlantStage,
    ShotSizingMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.domain.irrigation_recipe import (
    RecipeCaptureError,
    RecipeEditError,
)
from custom_components.growspace_manager.exceptions import (
    EntityNotFoundError,
    GrowspaceNotFoundError,
)
from custom_components.growspace_manager.managers.irrigation_recipe import (
    IrrigationRecipeLibrary,
)
from custom_components.growspace_manager.models import (
    Growspace,
    IrrigationRecipe,
    Plant,
    SubstrateProfile,
)


def _growspace(growspace_id: str, **overrides) -> Growspace:
    """Return a growspace whose irrigation is configured for Volume Mode."""
    growspace = Growspace(id=growspace_id, name=growspace_id.title())
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.COCO, liters_per_pot=6.0
    )
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.VOLUME
    growspace.irrigation_config.pump_flow_rate_ml_per_sec = 50.0
    for key, value in overrides.items():
        setattr(growspace, key, value)
    return growspace


def _plant(plant_id: str, growspace_id: str) -> Plant:
    """Return one live flowering plant in a growspace."""
    return Plant(
        plant_id=plant_id,
        growspace_id=growspace_id,
        stage=PlantStage.FLOWER.value,
        flower_start="2026-07-28",
    )


@pytest.fixture
def repository() -> GrowspaceRepository:
    """Repository holding two growspaces, one of them planted."""
    repo = GrowspaceRepository()
    repo.add_growspace(_growspace("tent_a"))
    repo.add_growspace(_growspace("tent_b"))
    repo.add_plant(_plant("p1", "tent_a"))
    repo.add_plant(_plant("p2", "tent_a"))
    return repo


@pytest.fixture
def save_callback() -> AsyncMock:
    """Mock the coordinator save callback."""
    return AsyncMock()


@pytest.fixture
def library(repository, save_callback) -> IrrigationRecipeLibrary:
    """A library over the shared repository."""
    return IrrigationRecipeLibrary(repository, save_callback)


@pytest.mark.asyncio
async def test_save_stores_kind_and_persists(library, save_callback) -> None:
    """A saved recipe is in the library, under its kind, and committed."""
    recipe = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )

    assert library.recipes[recipe.id] is recipe
    assert recipe.kind is IrrigationRecipeKind.CROP_STEERING
    assert recipe.crop_steering is not None
    assert recipe.schedule is None
    save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_schedule_recipe_carries_only_the_schedule_half(library) -> None:
    """The kinds are exclusive: one populated half, never both."""
    recipe = await library.async_save_from_growspace(
        "tent_a", "Veg timer", IrrigationRecipeKind.SCHEDULE
    )

    assert recipe.kind is IrrigationRecipeKind.SCHEDULE
    assert recipe.schedule is not None
    assert recipe.crop_steering is None


@pytest.mark.asyncio
async def test_recipes_are_global_across_growspaces(library) -> None:
    """Saved from one tent, listed from every other — that is the point."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )

    listed = library.get_serialization_data()["irrigation_recipes"]

    assert saved.id in listed
    assert listed[saved.id]["name"] == "Flower wk3"


@pytest.mark.asyncio
async def test_provenance_round_trips_through_storage(library) -> None:
    """Media, pot volume, flow rate, stage and week survive serialization."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )

    stored = library.get_serialization_data()["irrigation_recipes"][saved.id]
    reloaded = IrrigationRecipe.from_dict(stored)

    assert reloaded == saved
    assert reloaded.provenance.media_type is SubstrateMediaType.COCO
    assert reloaded.provenance.liters_per_pot == 6.0
    assert reloaded.provenance.pump_flow_rate_ml_per_sec == 50.0
    assert reloaded.provenance.stage == "flower"
    assert reloaded.provenance.week >= 1


@pytest.mark.asyncio
async def test_provenance_reports_no_cohort_for_an_empty_growspace(library) -> None:
    """An unplanted tent authors a recipe with no stage, not a fabricated one."""
    saved = await library.async_save_from_growspace(
        "tent_b", "Blank", IrrigationRecipeKind.CROP_STEERING
    )

    assert saved.provenance.stage is None
    assert saved.provenance.week == 0


@pytest.mark.asyncio
async def test_a_refused_save_stores_nothing(
    library, repository, save_callback
) -> None:
    """A Seconds Mode growspace missing its flow rate leaves no partial recipe."""
    growspace = repository.get_growspace("tent_a")
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.SECONDS
    growspace.irrigation_config.pump_flow_rate_ml_per_sec = 0.0

    with pytest.raises(RecipeCaptureError) as err:
        await library.async_save_from_growspace(
            "tent_a", "Doomed", IrrigationRecipeKind.CROP_STEERING
        )

    assert "no pump flow rate" in str(err.value)
    assert library.recipes == {}
    save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_seconds_mode_growspace_without_pot_volume_is_refused(
    library, repository
) -> None:
    """The other missing prerequisite is named just as specifically."""
    growspace = repository.get_growspace("tent_a")
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.SECONDS
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        liters_per_pot=0.0
    )

    with pytest.raises(RecipeCaptureError) as err:
        await library.async_save_from_growspace(
            "tent_a", "Doomed", IrrigationRecipeKind.CROP_STEERING
        )

    assert "no substrate volume per pot" in str(err.value)
    assert library.recipes == {}


@pytest.mark.asyncio
async def test_saving_over_an_existing_recipe_keeps_its_identity(library) -> None:
    """Re-saving under a known id overwrites in place, keeping created_at."""
    first = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )

    second = await library.async_save_from_growspace(
        "tent_a", "Flower wk4", IrrigationRecipeKind.SCHEDULE, recipe_id=first.id
    )

    assert second.id == first.id
    assert second.created_at == first.created_at
    assert second.name == "Flower wk4"
    assert len(library.recipes) == 1


@pytest.mark.asyncio
async def test_saving_from_an_unknown_growspace_is_refused(library) -> None:
    """No growspace, no capture."""
    with pytest.raises(GrowspaceNotFoundError):
        await library.async_save_from_growspace(
            "nope", "Ghost", IrrigationRecipeKind.CROP_STEERING
        )


@pytest.mark.asyncio
async def test_remove_deletes_and_persists(library, save_callback) -> None:
    """Removing drops the recipe and commits."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    save_callback.reset_mock()

    await library.async_remove_recipe(saved.id)

    assert library.recipes == {}
    save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_removing_an_unknown_recipe_is_a_typed_not_found(library) -> None:
    """A stale delete reports not-found rather than an internal error."""
    with pytest.raises(EntityNotFoundError):
        await library.async_remove_recipe("missing")


def test_load_data_replaces_the_library(library) -> None:
    """Startup load swaps the whole library in."""
    recipe = IrrigationRecipe(
        id="r1", name="Loaded", kind=IrrigationRecipeKind.SCHEDULE
    )

    library.load_data({"r1": recipe})

    assert library.recipes == {"r1": recipe}


# ---------------------------------------------------------------------------
# Editing a stored recipe (#109)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rename_needs_no_values(library, save_callback) -> None:
    """A rename is a whole edit on its own — no values to re-supply."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    before = saved.crop_steering
    save_callback.reset_mock()

    edited = await library.async_update_recipe(saved.id, name="Flower wk4")

    assert edited.name == "Flower wk4"
    assert edited.crop_steering == before
    save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_editing_values_is_sparse(library) -> None:
    """An unnamed field keeps what the recipe stores."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    assert saved.crop_steering is not None
    interval_before = saved.crop_steering.p1_shot_interval_minutes

    edited = await library.async_update_recipe(
        saved.id, crop_steering={"p1_shot_volume_percent": 7.5}
    )

    assert edited.crop_steering is not None
    assert edited.crop_steering.p1_shot_volume_percent == 7.5
    assert edited.crop_steering.p1_shot_interval_minutes == interval_before


@pytest.mark.asyncio
async def test_an_edit_keeps_identity_kind_and_provenance(library) -> None:
    """The edit reaches the name and the values, and nothing else."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    provenance_before = saved.provenance
    created_before = saved.created_at

    edited = await library.async_update_recipe(
        saved.id, name="Renamed", crop_steering={"target_vwc_percent": 61.0}
    )

    assert edited.id == saved.id
    assert edited.kind is IrrigationRecipeKind.CROP_STEERING
    assert edited.created_at == created_before
    assert edited.provenance == provenance_before


@pytest.mark.asyncio
async def test_an_edit_is_visible_through_the_stored_instance(library) -> None:
    """Editing mutates the library's own object, as get_recipe promises."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    held = library.get_recipe(saved.id)

    await library.async_update_recipe(saved.id, name="Renamed")

    assert held.name == "Renamed"
    assert library.recipes[saved.id] is held


@pytest.mark.asyncio
async def test_editing_the_wrong_half_is_refused_and_changes_nothing(
    library, save_callback
) -> None:
    """A crop-steering recipe has no schedule values to correct."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    save_callback.reset_mock()

    with pytest.raises(RecipeEditError):
        await library.async_update_recipe(
            saved.id, name="Renamed", schedule={"skip_during_dark": True}
        )

    assert saved.name == "Flower wk3"
    save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_unknown_field_is_refused_and_changes_nothing(
    library, save_callback
) -> None:
    """Naming a field the half does not store refuses the whole edit."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    assert saved.crop_steering is not None
    before = saved.crop_steering.target_vwc_percent
    save_callback.reset_mock()

    with pytest.raises(RecipeEditError, match="not part of a crop_steering recipe"):
        await library.async_update_recipe(
            saved.id,
            crop_steering={"target_vwc_percent": 61.0, "liters_per_pot": 9.0},
        )

    assert saved.crop_steering.target_vwc_percent == before
    save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_editing_an_unknown_recipe_is_a_typed_not_found(
    library, save_callback
) -> None:
    """A stale edit reports not-found and stores nothing."""
    with pytest.raises(EntityNotFoundError):
        await library.async_update_recipe("missing", name="Ghost")

    save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_edited_recipe_round_trips_through_storage(library) -> None:
    """The corrected values survive serialization like captured ones do."""
    saved = await library.async_save_from_growspace(
        "tent_a", "Veg timer", IrrigationRecipeKind.SCHEDULE
    )
    await library.async_update_recipe(
        saved.id, name="Veg timer v2", schedule={"max_cycles_per_day": 5}
    )

    stored = library.get_serialization_data()["irrigation_recipes"][saved.id]
    reloaded = IrrigationRecipe.from_dict(stored)

    assert reloaded.name == "Veg timer v2"
    assert reloaded.schedule is not None
    assert reloaded.schedule.max_cycles_per_day == 5
