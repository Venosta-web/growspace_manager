"""Tests for the Irrigation Recipe service and WebSocket surface (ADR-0045)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_NAME,
    ATTR_RECIPE_ID,
    ATTR_RECIPE_KIND,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    IrrigationRecipeKind,
    PlantStage,
    ShotSizingMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.infiltration import InfiltrationState
from custom_components.growspace_manager.domain.irrigation_recipe import (
    RecipeKindMismatchError,
)
from custom_components.growspace_manager.domain.steering_phase import (
    SteeringPhaseMachine,
    SteeringTickInputs,
)
from custom_components.growspace_manager.exceptions import EntityNotFoundError
from custom_components.growspace_manager.models import (
    Growspace,
    Plant,
    SubstrateProfile,
)
from custom_components.growspace_manager.services.irrigation_recipes import (
    handle_apply_irrigation_recipe,
    handle_remove_irrigation_recipe,
    handle_save_irrigation_recipe,
    handle_update_irrigation_recipe,
)
from custom_components.growspace_manager.view_model_builder import ViewModelBuilder
from custom_components.growspace_manager.websocket.irrigation import (
    websocket_apply_irrigation_recipe,
    websocket_get_irrigation_recipes,
    websocket_remove_irrigation_recipe,
    websocket_save_irrigation_recipe,
    websocket_update_irrigation_recipe,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry


def _growspace(growspace_id: str) -> Growspace:
    """Return a Volume Mode growspace with usable plumbing."""
    growspace = Growspace(id=growspace_id, name=growspace_id.title())
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.COCO, liters_per_pot=6.0
    )
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.VOLUME
    growspace.irrigation_strategy.p1_shot_volume_percent = 3.0
    growspace.irrigation_config.pump_flow_rate_ml_per_sec = 50.0
    return growspace


@pytest.fixture
def coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """A coordinator holding two growspaces, one of them planted."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    coordinator.storage_manager.async_force_save = AsyncMock()
    coordinator.view_model_builder = MagicMock()
    coordinator.view_model_builder.build_data_property.return_value = {}
    coordinator._data_repository.add_growspace(_growspace("tent_a"))
    coordinator._data_repository.add_growspace(_growspace("tent_b"))
    coordinator._data_repository.add_plant(
        Plant(
            plant_id="p1",
            growspace_id="tent_a",
            stage=PlantStage.FLOWER.value,
            flower_start="2026-07-28",
        )
    )
    return coordinator


def _call(**data) -> MagicMock:
    """Return a service call carrying ``data``."""
    call = MagicMock()
    call.data = data
    return call


@pytest.mark.asyncio
async def test_save_service_stores_a_recipe(hass, coordinator) -> None:
    """The action captures the growspace into the global library."""
    await handle_save_irrigation_recipe(
        hass,
        coordinator,
        _call(
            **{
                ATTR_GROWSPACE_ID: "tent_a",
                ATTR_NAME: "Flower wk3",
                ATTR_RECIPE_KIND: IrrigationRecipeKind.CROP_STEERING.value,
            }
        ),
    )

    recipes = list(coordinator._recipe_library.recipes.values())
    assert [r.name for r in recipes] == ["Flower wk3"]
    assert recipes[0].crop_steering.p1_shot_volume_percent == 3.0


@pytest.mark.asyncio
async def test_remove_service_deletes_a_recipe(hass, coordinator) -> None:
    """The remove action mirrors the save action."""
    saved = await coordinator.services.config.save_irrigation_recipe(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )

    await handle_remove_irrigation_recipe(
        hass, coordinator, _call(**{ATTR_RECIPE_ID: saved.id})
    )

    assert coordinator._recipe_library.recipes == {}


@pytest.mark.asyncio
async def test_save_service_reports_a_refusal_to_the_grower(hass, coordinator) -> None:
    """A Seconds Mode growspace with no flow rate fails loudly, not silently."""
    growspace = coordinator.growspaces["tent_a"]
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.SECONDS
    growspace.irrigation_config.pump_flow_rate_ml_per_sec = 0.0

    with pytest.raises(ServiceValidationError, match="no pump flow rate"):
        await handle_save_irrigation_recipe(
            hass,
            coordinator,
            _call(
                **{
                    ATTR_GROWSPACE_ID: "tent_a",
                    ATTR_NAME: "Doomed",
                    ATTR_RECIPE_KIND: IrrigationRecipeKind.CROP_STEERING.value,
                }
            ),
        )

    assert coordinator._recipe_library.recipes == {}


@pytest.mark.asyncio
async def test_websocket_commands_save_list_and_remove(hass, coordinator) -> None:
    """The WS surface mirrors the actions, and listing is growspace-free."""
    saved = await websocket_save_irrigation_recipe(
        hass,
        coordinator,
        {
            "id": 1,
            "type": f"{DOMAIN}/save_irrigation_recipe",
            "growspace_id": "tent_a",
            "name": "Flower wk3",
            "kind": IrrigationRecipeKind.CROP_STEERING.value,
        },
    )

    listed = websocket_get_irrigation_recipes(
        hass, coordinator, {"id": 2, "type": f"{DOMAIN}/get_irrigation_recipes"}
    )
    assert list(listed) == [saved["id"]]
    assert listed[saved["id"]]["kind"] == "crop_steering"

    await websocket_remove_irrigation_recipe(
        hass,
        coordinator,
        {
            "id": 3,
            "type": f"{DOMAIN}/remove_irrigation_recipe",
            "recipe_id": saved["id"],
        },
    )
    assert (
        websocket_get_irrigation_recipes(
            hass, coordinator, {"id": 4, "type": f"{DOMAIN}/get_irrigation_recipes"}
        )
        == {}
    )


@pytest.mark.asyncio
async def test_a_recipe_saved_from_one_growspace_is_read_from_another(
    hass, coordinator
) -> None:
    """The library is global: the growspace payload of tent_b carries it too."""
    await coordinator.services.config.save_irrigation_recipe(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )

    from_b = websocket_get_irrigation_recipes(
        hass, coordinator, {"id": 1, "type": f"{DOMAIN}/get_irrigation_recipes"}
    )

    assert [r["name"] for r in from_b.values()] == ["Flower wk3"]


@pytest.mark.asyncio
async def test_recipes_survive_a_storage_round_trip(hass, coordinator) -> None:
    """A saved recipe reloads from the config document unchanged."""
    saved = await coordinator.services.config.save_irrigation_recipe(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )

    stored = coordinator.storage_manager._get_config_data()
    coordinator._recipe_library.load_data({})
    coordinator.storage_manager._load_config(stored)

    assert coordinator._recipe_library.recipes == {saved.id: saved}


# --- Applying a recipe: the Recipe Stamp ----------------------------------


def _steer(coordinator: GrowspaceCoordinator, *growspace_ids: str) -> None:
    """Put growspaces on crop steering, the half a steering recipe expects."""
    for growspace_id in growspace_ids:
        coordinator.growspaces[growspace_id].irrigation_strategy.enabled = True


async def _saved_steering_recipe(coordinator: GrowspaceCoordinator) -> str:
    """Save tent_a's crop-steering settings and return the recipe id."""
    recipe = await coordinator.services.config.save_irrigation_recipe(
        "tent_a", "Flower wk3", IrrigationRecipeKind.CROP_STEERING
    )
    return recipe.id


def _fired_shot_seconds(coordinator: GrowspaceCoordinator, growspace_id: str) -> int:
    """Return the pump seconds the real phase machine sizes a P1 shot at.

    The production path from the stamped fields to a duration — the shot is
    composed from ``p1_shot_volume_percent`` against this growspace's own
    plumbing, not from anything the recipe stored.
    """
    growspace = coordinator.growspaces[growspace_id]
    verdict = SteeringPhaseMachine(growspace_id).tick(
        SteeringTickInputs(
            now=dt_util.parse_datetime("2026-08-11T09:00:00+00:00"),
            vwc=40.0,
            strategy=growspace.irrigation_strategy,
            auto_advance_p2_to_p3=False,
            soil_trigger_percent=None,
            pump_flow_rate_ml_per_sec=(
                growspace.irrigation_config.pump_flow_rate_ml_per_sec
            ),
            pump_configured=True,
            day_hours=12,
            live_plant_count=4,
            last_shot=None,
            interval_factor=1.0,
            infiltration=InfiltrationState.UNKNOWN,
        )
    )
    assert verdict.fire is not None
    return verdict.fire.base_seconds


@pytest.mark.asyncio
async def test_a_growspace_starts_with_no_recipe_applied(coordinator) -> None:
    """Unset is a real third state, not an implicit default recipe."""
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy

    assert strategy.applied_recipe_id is None
    assert strategy.recipe_applied_at is None


@pytest.mark.asyncio
async def test_apply_service_stamps_and_records(hass, coordinator) -> None:
    """The action writes the values and records which recipe wrote them."""
    _steer(coordinator, "tent_a", "tent_b")
    recipe_id = await _saved_steering_recipe(coordinator)

    await handle_apply_irrigation_recipe(
        hass,
        coordinator,
        _call(**{ATTR_GROWSPACE_ID: "tent_b", ATTR_RECIPE_ID: recipe_id}),
    )

    strategy = coordinator.growspaces["tent_b"].irrigation_strategy
    assert strategy.p1_shot_volume_percent == 3.0
    assert strategy.applied_recipe_id == recipe_id
    assert strategy.recipe_applied_at is not None


@pytest.mark.asyncio
async def test_apply_resizes_the_shot_for_this_tents_plumbing(
    hass, coordinator
) -> None:
    """The portable percent survives; the pump seconds are re-derived.

    Driven through the real Steering Phase Machine rather than the conversion
    helper, because the whole claim is that the stamped fields — not the
    recipe — are what the shot is composed from.
    """
    _steer(coordinator, "tent_a", "tent_b")
    tent_b = coordinator.growspaces["tent_b"]
    tent_b.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.COCO, liters_per_pot=12.0
    )
    tent_b.irrigation_config.pump_flow_rate_ml_per_sec = 25.0
    recipe_id = await _saved_steering_recipe(coordinator)

    await websocket_apply_irrigation_recipe(
        hass,
        coordinator,
        {
            "id": 1,
            "type": f"{DOMAIN}/apply_irrigation_recipe",
            "growspace_id": "tent_b",
            "recipe_id": recipe_id,
        },
    )

    strategy_a = coordinator.growspaces["tent_a"].irrigation_strategy
    assert (
        tent_b.irrigation_strategy.p1_shot_volume_percent
        == strategy_a.p1_shot_volume_percent
    )
    # 3% of 6 L × 4 pots at 50 ml/s vs 3% of 12 L × 4 pots at 25 ml/s.
    assert _fired_shot_seconds(coordinator, "tent_a") == 14
    assert _fired_shot_seconds(coordinator, "tent_b") == 58


@pytest.mark.asyncio
async def test_re_applying_overwrites_hand_tweaks(hass, coordinator) -> None:
    """Applying always writes, so it doubles as "reset to this recipe"."""
    _steer(coordinator, "tent_a")
    recipe_id = await _saved_steering_recipe(coordinator)
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy

    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", recipe_id)
    strategy.p1_shot_volume_percent = 99.0
    strategy.p2_shot_interval_minutes = 99
    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", recipe_id)

    assert strategy.p1_shot_volume_percent == 3.0
    assert strategy.p2_shot_interval_minutes == 15


@pytest.mark.asyncio
async def test_wrong_kind_is_refused_and_changes_nothing(hass, coordinator) -> None:
    """A schedule recipe onto a crop-steering tent: typed refusal, no write."""
    schedule_recipe = await coordinator.services.config.save_irrigation_recipe(
        "tent_a", "Veg timer", IrrigationRecipeKind.SCHEDULE
    )
    _steer(coordinator, "tent_b")
    tent_b = coordinator.growspaces["tent_b"]
    tent_b.irrigation_config.max_cycles_per_day = 4

    with pytest.raises(RecipeKindMismatchError):
        await coordinator.services.growspaces.apply_irrigation_recipe(
            "tent_b", schedule_recipe.id
        )

    assert tent_b.irrigation_config.max_cycles_per_day == 4
    assert tent_b.irrigation_strategy.applied_recipe_id is None


@pytest.mark.asyncio
async def test_wrong_kind_the_other_way_round_is_refused(hass, coordinator) -> None:
    """And a crop-steering recipe onto a time-scheduled tent."""
    _steer(coordinator, "tent_a")
    recipe_id = await _saved_steering_recipe(coordinator)
    tent_b = coordinator.growspaces["tent_b"]

    with pytest.raises(RecipeKindMismatchError):
        await coordinator.services.growspaces.apply_irrigation_recipe(
            "tent_b", recipe_id
        )

    assert tent_b.irrigation_strategy.applied_recipe_id is None


@pytest.mark.asyncio
async def test_a_schedule_recipe_stamps_the_irrigation_config(
    hass, coordinator
) -> None:
    """The schedule half lands on the config the time-based coordinator reads."""
    tent_a = coordinator.growspaces["tent_a"]
    tent_a.irrigation_config.irrigation_times = [{"time": "07:30:00", "duration": 45}]
    tent_a.irrigation_config.max_cycles_per_day = 8
    saved = await coordinator.services.config.save_irrigation_recipe(
        "tent_a", "Veg timer", IrrigationRecipeKind.SCHEDULE
    )

    await coordinator.services.growspaces.apply_irrigation_recipe("tent_b", saved.id)

    config_b = coordinator.growspaces["tent_b"].irrigation_config
    assert config_b.irrigation_times == [{"time": "07:30:00", "duration": 45}]
    assert config_b.max_cycles_per_day == 8


@pytest.mark.asyncio
async def test_cross_media_apply_succeeds_unscaled_and_warns(hass, coordinator) -> None:
    """Pot size normalises across growspaces; media does not (ADR-0045)."""
    _steer(coordinator, "tent_a", "tent_b")
    recipe_id = await _saved_steering_recipe(coordinator)
    tent_b = coordinator.growspaces["tent_b"]
    tent_b.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL, liters_per_pot=6.0
    )

    result = await websocket_apply_irrigation_recipe(
        hass,
        coordinator,
        {
            "id": 1,
            "type": f"{DOMAIN}/apply_irrigation_recipe",
            "growspace_id": "tent_b",
            "recipe_id": recipe_id,
        },
    )

    assert result["applied_recipe_id"] == recipe_id
    assert "coco" in result["warning"]
    assert "rockwool" in result["warning"]
    assert tent_b.irrigation_strategy.p1_shot_volume_percent == 3.0


@pytest.mark.asyncio
async def test_apply_writes_one_logbook_entry_naming_recipe_and_media(
    hass, coordinator
) -> None:
    """One entry per apply, carrying both media so a mismatch is on the record."""
    _steer(coordinator, "tent_a", "tent_b")
    recipe_id = await _saved_steering_recipe(coordinator)
    coordinator.growspaces[
        "tent_b"
    ].irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.ROCKWOOL, liters_per_pot=6.0
    )
    entries = []
    hass.bus.async_listen(EVENT_GROWSPACE_LOG_ENTRY, entries.append)

    await coordinator.services.growspaces.apply_irrigation_recipe("tent_b", recipe_id)
    await hass.async_block_till_done()

    assert len(entries) == 1
    message = entries[0].data["message"]
    assert "Flower wk3" in message
    assert "coco" in message
    assert "rockwool" in message


@pytest.mark.asyncio
async def test_drift_is_derived_on_the_growspace_payload(hass, coordinator) -> None:
    """Whether the grower has tweaked since applying is a read, not stored state."""
    _steer(coordinator, "tent_a")
    recipe_id = await _saved_steering_recipe(coordinator)
    view_model = ViewModelBuilder(coordinator)

    assert (
        view_model.build_serialized_growspace("tent_a")["irrigation"][
            "applied_recipe_drifted"
        ]
        is None
    )

    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", recipe_id)
    coordinator.cache.invalidate("tent_a")
    assert (
        view_model.build_serialized_growspace("tent_a")["irrigation"][
            "applied_recipe_drifted"
        ]
        is False
    )

    coordinator.growspaces["tent_a"].irrigation_strategy.p1_shot_volume_percent = 9.0
    coordinator.cache.invalidate("tent_a")
    assert (
        view_model.build_serialized_growspace("tent_a")["irrigation"][
            "applied_recipe_drifted"
        ]
        is True
    )


@pytest.mark.asyncio
async def test_drift_reads_none_once_the_applied_recipe_is_deleted(
    hass, coordinator
) -> None:
    """Deleting leaves references dangling by design; the read degrades, not fails."""
    _steer(coordinator, "tent_a")
    recipe_id = await _saved_steering_recipe(coordinator)
    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", recipe_id)
    await coordinator.services.config.remove_irrigation_recipe(recipe_id)

    coordinator.cache.invalidate("tent_a")
    payload = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")

    assert payload["irrigation"]["applied_recipe_drifted"] is None
    assert payload["irrigation"]["irrigation_strategy"]["applied_recipe_id"] == (
        recipe_id
    )


@pytest.mark.asyncio
async def test_applying_an_unknown_recipe_is_not_found(hass, coordinator) -> None:
    """The not-found narrowing the card can act on, not a generic failure."""
    _steer(coordinator, "tent_a")

    with pytest.raises(EntityNotFoundError):
        await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", "nope")


# ---------------------------------------------------------------------------
# Editing a stored recipe (#109)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_update_service_renames_and_corrects_values(hass, coordinator) -> None:
    """The action edits the library in place, sparsely."""
    recipe_id = await _saved_steering_recipe(coordinator)

    await handle_update_irrigation_recipe(
        hass,
        coordinator,
        _call(
            recipe_id=recipe_id,
            name="Flower wk4",
            crop_steering={"p1_shot_volume_percent": 7.5},
        ),
    )

    recipe = coordinator.services.config.find_irrigation_recipe(recipe_id)
    assert recipe is not None
    assert recipe.name == "Flower wk4"
    assert recipe.crop_steering is not None
    assert recipe.crop_steering.p1_shot_volume_percent == 7.5


@pytest.mark.asyncio
async def test_update_service_reports_a_refusal_to_the_grower(
    hass, coordinator
) -> None:
    """The wrong half surfaces as a validation error, not an internal one."""
    recipe_id = await _saved_steering_recipe(coordinator)

    with pytest.raises(ServiceValidationError):
        await handle_update_irrigation_recipe(
            hass,
            coordinator,
            _call(recipe_id=recipe_id, schedule={"skip_during_dark": True}),
        )


@pytest.mark.asyncio
async def test_websocket_update_returns_the_edited_recipe(hass, coordinator) -> None:
    """The editor learns what the library now holds without re-reading it."""
    recipe_id = await _saved_steering_recipe(coordinator)

    edited = await websocket_update_irrigation_recipe(
        hass,
        coordinator,
        {"recipe_id": recipe_id, "name": "Flower wk4"},
    )

    assert edited["id"] == recipe_id
    assert edited["name"] == "Flower wk4"
    assert edited["kind"] == IrrigationRecipeKind.CROP_STEERING.value

    listed = websocket_get_irrigation_recipes(hass, coordinator, {})
    assert listed[recipe_id]["name"] == "Flower wk4"


@pytest.mark.asyncio
async def test_websocket_update_of_an_unknown_recipe_is_not_found(
    hass, coordinator
) -> None:
    """A stale edit narrows to not-found the card can act on."""
    with pytest.raises(EntityNotFoundError):
        await websocket_update_irrigation_recipe(
            hass, coordinator, {"recipe_id": "nope", "name": "Ghost"}
        )


@pytest.mark.asyncio
async def test_editing_a_recipe_changes_no_growspace(hass, coordinator) -> None:
    """Apply is a by-value stamp, so an edit reaches no irrigation field."""
    _steer(coordinator, "tent_a")
    recipe_id = await _saved_steering_recipe(coordinator)
    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", recipe_id)
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    before = strategy.p1_shot_volume_percent

    await coordinator.services.config.update_irrigation_recipe(
        recipe_id, crop_steering={"p1_shot_volume_percent": before + 5.0}
    )

    assert strategy.p1_shot_volume_percent == before


@pytest.mark.asyncio
async def test_editing_a_recipe_makes_its_carriers_read_as_drifted(
    hass, coordinator
) -> None:
    """The consequence a grower does see: the tent no longer holds what it says."""
    _steer(coordinator, "tent_a", "tent_b")
    recipe_id = await _saved_steering_recipe(coordinator)
    other = await coordinator.services.config.save_irrigation_recipe(
        "tent_b", "Other", IrrigationRecipeKind.CROP_STEERING
    )
    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", recipe_id)
    await coordinator.services.growspaces.apply_irrigation_recipe("tent_b", other.id)
    view_model = ViewModelBuilder(coordinator)

    await coordinator.services.config.update_irrigation_recipe(
        recipe_id, crop_steering={"target_vwc_percent": 61.0}
    )
    coordinator.cache.invalidate("tent_a")
    coordinator.cache.invalidate("tent_b")

    payload_a = view_model.build_serialized_growspace("tent_a")
    payload_b = view_model.build_serialized_growspace("tent_b")
    assert payload_a["irrigation"]["applied_recipe_drifted"] is True
    assert payload_b["irrigation"]["applied_recipe_drifted"] is False


@pytest.mark.asyncio
async def test_an_edited_recipe_survives_a_storage_round_trip(
    hass, coordinator
) -> None:
    """The correction is in the config document, not only in memory."""
    recipe_id = await _saved_steering_recipe(coordinator)
    await coordinator.services.config.update_irrigation_recipe(
        recipe_id, name="Flower wk4", crop_steering={"target_vwc_percent": 61.0}
    )

    stored = coordinator._recipe_library.get_serialization_data()["irrigation_recipes"][
        recipe_id
    ]

    assert stored["name"] == "Flower wk4"
    assert stored["crop_steering"]["target_vwc_percent"] == 61.0


@pytest.mark.asyncio
async def test_an_edited_recipe_is_read_from_every_growspace(hass, coordinator) -> None:
    """The library is global, and stays global after an edit."""
    recipe_id = await _saved_steering_recipe(coordinator)
    await coordinator.services.config.update_irrigation_recipe(
        recipe_id, name="Flower wk4"
    )

    view_model = ViewModelBuilder(coordinator)
    for growspace_id in ("tent_a", "tent_b"):
        coordinator.cache.invalidate(growspace_id)
        recipes = view_model.build_serialized_growspace(growspace_id)["irrigation"][
            "recipes"
        ]
        assert recipes[recipe_id]["name"] == "Flower wk4"
