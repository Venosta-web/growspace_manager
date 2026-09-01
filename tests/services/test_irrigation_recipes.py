"""Tests for the Irrigation Recipe service and WebSocket surface (ADR-0045)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_NAME,
    ATTR_RECIPE_ID,
    ATTR_RECIPE_KIND,
    DOMAIN,
    IrrigationRecipeKind,
    PlantStage,
    ShotSizingMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import (
    Growspace,
    Plant,
    SubstrateProfile,
)
from custom_components.growspace_manager.services.irrigation_recipes import (
    handle_remove_irrigation_recipe,
    handle_save_irrigation_recipe,
)
from custom_components.growspace_manager.websocket.irrigation import (
    websocket_get_irrigation_recipes,
    websocket_remove_irrigation_recipe,
    websocket_save_irrigation_recipe,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
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
