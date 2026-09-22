"""Tests for the Irrigation Program service and WebSocket surface (ADR-0045)."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_NAME,
    ATTR_PROGRAM_ID,
    ATTR_PROGRAM_SLOTS,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    IrrigationRecipeKind,
    PlantStage,
    ShotSizingMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.irrigation_program import ProgramError
from custom_components.growspace_manager.exceptions import (
    EntityNotFoundError,
    GrowspaceNotFoundError,
)
from custom_components.growspace_manager.models import (
    Growspace,
    Plant,
    SubstrateProfile,
)
from custom_components.growspace_manager.services.irrigation_programs import (
    handle_assign_irrigation_program,
    handle_remove_irrigation_program,
    handle_save_irrigation_program,
)
from custom_components.growspace_manager.view_model_builder import ViewModelBuilder
from custom_components.growspace_manager.websocket.irrigation import (
    websocket_assign_irrigation_program,
    websocket_get_irrigation_programs,
    websocket_remove_irrigation_program,
    websocket_save_irrigation_program,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry, async_capture_events, async_mock_service


def _growspace(growspace_id: str) -> Growspace:
    """Return a Volume Mode growspace with usable plumbing."""
    growspace = Growspace(id=growspace_id, name=growspace_id.title())
    growspace.irrigation_strategy.enabled = True
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.COCO, liters_per_pot=6.0
    )
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.VOLUME
    growspace.irrigation_strategy.p1_shot_volume_percent = 3.0
    growspace.irrigation_config.pump_flow_rate_ml_per_sec = 50.0
    return growspace


@pytest.fixture
def coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """A coordinator holding two growspaces, one of them in flower week 3."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    coordinator.storage_manager.async_force_save = AsyncMock()
    coordinator.view_model_builder = MagicMock()
    coordinator.view_model_builder.build_data_property.return_value = {}
    coordinator._data_repository.add_growspace(_growspace("tent_a"))
    coordinator._data_repository.add_growspace(_growspace("tent_b"))
    # 15 days into flower, which ``days_to_week`` calls week 3. Relative to
    # the test clock so the resolved position is the same on any run date.
    coordinator._data_repository.add_plant(
        Plant(
            plant_id="p1",
            growspace_id="tent_a",
            stage=PlantStage.FLOWER.value,
            flower_start=(dt_util.now().date() - timedelta(days=15)).isoformat(),
        )
    )
    return coordinator


def _call(**data) -> MagicMock:
    """Return a service call carrying ``data``."""
    call = MagicMock()
    call.data = data
    return call


def _slots(*slots: tuple[str, int, str]) -> list[dict]:
    """Return raw slot payloads for ``(stage, week, recipe_id)`` triples."""
    return [
        {"stage": stage, "week": week, "recipe_id": recipe_id}
        for stage, week, recipe_id in slots
    ]


async def _saved_recipe(coordinator: GrowspaceCoordinator, name: str) -> str:
    """Save tent_a's crop-steering settings as a recipe and return its id."""
    recipe = await coordinator.services.config.save_irrigation_recipe(
        "tent_a", name, IrrigationRecipeKind.CROP_STEERING
    )
    return recipe.id


# Where the feed seam puts tent_a: 15 days into flower is week 3.
CURRENT_STAGE, CURRENT_WEEK = "flower", 3


# ---------------------------------------------------------------------------
# The library: save, list, remove
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_service_stores_a_program(hass, coordinator) -> None:
    """The action stores the plan in the global library."""
    await handle_save_irrigation_program(
        hass,
        coordinator,
        _call(
            **{
                ATTR_NAME: "Full run",
                ATTR_PROGRAM_SLOTS: _slots(("veg", 1, "r1"), ("flower", 3, "r2")),
            }
        ),
    )

    programs = list(coordinator._program_library.programs.values())
    assert [p.name for p in programs] == ["Full run"]
    assert [(s.stage, s.week, s.recipe_id) for s in programs[0].slots] == [
        ("veg", 1, "r1"),
        ("flower", 3, "r2"),
    ]


@pytest.mark.asyncio
async def test_remove_service_deletes_a_program(hass, coordinator) -> None:
    """The remove action mirrors the save action."""
    saved = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("veg", 1, "r1"))
    )

    await handle_remove_irrigation_program(
        hass, coordinator, _call(**{ATTR_PROGRAM_ID: saved.id})
    )

    assert coordinator._program_library.programs == {}


@pytest.mark.asyncio
async def test_save_service_reports_a_refusal_to_the_grower(hass, coordinator) -> None:
    """An unreachable slot fails loudly rather than being stored dead."""
    with pytest.raises(ServiceValidationError, match="dry"):
        await handle_save_irrigation_program(
            hass,
            coordinator,
            _call(
                **{
                    ATTR_NAME: "Doomed",
                    ATTR_PROGRAM_SLOTS: _slots(("dry", 1, "r1")),
                }
            ),
        )

    assert coordinator._program_library.programs == {}


@pytest.mark.asyncio
async def test_websocket_commands_save_list_and_remove(hass, coordinator) -> None:
    """The WS surface mirrors the actions, and listing is growspace-free."""
    saved = await websocket_save_irrigation_program(
        hass,
        coordinator,
        {
            "id": 1,
            "type": f"{DOMAIN}/save_irrigation_program",
            "name": "Full run",
            "slots": _slots(("flower", 3, "r2"), ("veg", 1, "r1")),
        },
    )

    # Echoed back in run order, not the order the editor sent them.
    assert [(s["stage"], s["week"]) for s in saved["slots"]] == [
        ("veg", 1),
        ("flower", 3),
    ]

    listed = websocket_get_irrigation_programs(
        hass, coordinator, {"id": 2, "type": f"{DOMAIN}/get_irrigation_programs"}
    )
    assert list(listed) == [saved["id"]]
    assert listed[saved["id"]]["name"] == "Full run"

    await websocket_remove_irrigation_program(
        hass,
        coordinator,
        {
            "id": 3,
            "type": f"{DOMAIN}/remove_irrigation_program",
            "program_id": saved["id"],
        },
    )
    assert (
        websocket_get_irrigation_programs(
            hass, coordinator, {"id": 4, "type": f"{DOMAIN}/get_irrigation_programs"}
        )
        == {}
    )


@pytest.mark.asyncio
async def test_programs_survive_a_storage_round_trip(hass, coordinator) -> None:
    """A saved program reloads from the config document unchanged."""
    saved = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 2, "r1"))
    )

    stored = coordinator.storage_manager._get_config_data()
    coordinator._program_library.load_data({})
    coordinator.storage_manager._load_config(stored)

    assert coordinator._program_library.programs == {saved.id: saved}


# ---------------------------------------------------------------------------
# Recipes are held by reference
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_recipe_occupies_slots_in_several_programs(hass, coordinator) -> None:
    """Nothing is consumed by a program, so a recipe can be reused freely."""
    recipe_id = await _saved_recipe(coordinator, "Flower wk3")

    first = await coordinator.services.config.save_irrigation_program(
        "Plan A", _slots(("flower", 1, recipe_id))
    )
    second = await coordinator.services.config.save_irrigation_program(
        "Plan B", _slots(("flower", 2, recipe_id), ("veg", 1, recipe_id))
    )

    assert first.slots[0].recipe_id == recipe_id
    assert {slot.recipe_id for slot in second.slots} == {recipe_id}


@pytest.mark.asyncio
async def test_editing_a_recipe_is_visible_through_every_program(
    hass, coordinator
) -> None:
    """A program holds a reference, so one fix reaches every plan at once."""
    recipe_id = await _saved_recipe(coordinator, "Flower wk3")
    await coordinator.services.config.save_irrigation_program(
        "Plan A", _slots(("flower", 3, recipe_id))
    )
    await coordinator.services.config.save_irrigation_program(
        "Plan B", _slots(("flower", 3, recipe_id))
    )

    await coordinator.services.config.update_irrigation_recipe(
        recipe_id, crop_steering={"p1_shot_volume_percent": 7.5}
    )

    for program in coordinator._program_library.programs.values():
        slot = program.slots[0]
        resolved = coordinator.services.config.find_irrigation_recipe(slot.recipe_id)
        assert resolved.crop_steering.p1_shot_volume_percent == 7.5


# ---------------------------------------------------------------------------
# Binding a program to a growspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_a_growspace_starts_bound_to_nothing(coordinator) -> None:
    """Unbound is the starting state, not an implicit first program."""
    assert (
        coordinator.growspaces["tent_a"].irrigation_strategy.irrigation_program_id
        is None
    )


@pytest.mark.asyncio
async def test_assign_service_binds_and_unbinds(hass, coordinator) -> None:
    """Omitting the program id is the unbind, and it round-trips."""
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 3, "r1"))
    )
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy

    await handle_assign_irrigation_program(
        hass,
        coordinator,
        _call(**{ATTR_GROWSPACE_ID: "tent_a", ATTR_PROGRAM_ID: program.id}),
    )
    assert strategy.irrigation_program_id == program.id

    await handle_assign_irrigation_program(
        hass, coordinator, _call(**{ATTR_GROWSPACE_ID: "tent_a"})
    )
    assert strategy.irrigation_program_id is None


@pytest.mark.asyncio
async def test_assign_websocket_echoes_the_binding(hass, coordinator) -> None:
    """The WS command answers with what the growspace now holds."""
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 3, "r1"))
    )

    result = await websocket_assign_irrigation_program(
        hass,
        coordinator,
        {
            "id": 1,
            "type": f"{DOMAIN}/assign_irrigation_program",
            "growspace_id": "tent_a",
            "program_id": program.id,
        },
    )

    assert result == {
        "growspace_id": "tent_a",
        "irrigation_program_id": program.id,
    }

    cleared = await websocket_assign_irrigation_program(
        hass,
        coordinator,
        {
            "id": 2,
            "type": f"{DOMAIN}/assign_irrigation_program",
            "growspace_id": "tent_a",
            "program_id": None,
        },
    )
    assert cleared["irrigation_program_id"] is None


@pytest.mark.asyncio
async def test_assigning_writes_no_setpoint_and_fires_no_pump(
    hass, coordinator
) -> None:
    """Picking a program from a dropdown cannot move water (ADR-0045).

    The program's slot holds a recipe whose values differ from tent_b's, so a
    stamp would be visible; nothing about the strategy or the irrigation config
    may change except the binding itself.
    """
    recipe_id = await _saved_recipe(coordinator, "Flower wk3")
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 3, recipe_id))
    )
    growspace = coordinator.growspaces["tent_b"]
    growspace.irrigation_strategy.p1_shot_volume_percent = 9.0
    before_strategy = growspace.irrigation_strategy.to_dict()
    before_config = growspace.irrigation_config.to_dict()

    logbook = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    pump_calls = async_mock_service(hass, "switch", "turn_on")

    await coordinator.services.growspaces.assign_irrigation_program(
        "tent_b", program.id
    )

    after_strategy = growspace.irrigation_strategy.to_dict()
    assert after_strategy.pop("irrigation_program_id") == program.id
    before_strategy.pop("irrigation_program_id")
    assert after_strategy == before_strategy
    assert growspace.irrigation_config.to_dict() == before_config
    assert growspace.irrigation_strategy.applied_recipe_id is None
    assert logbook == []
    assert pump_calls == []


@pytest.mark.asyncio
async def test_assigning_an_unknown_program_is_refused(hass, coordinator) -> None:
    """A binding that names nothing would read as a lost write."""
    with pytest.raises(EntityNotFoundError):
        await coordinator.services.growspaces.assign_irrigation_program(
            "tent_a", "nope"
        )

    assert (
        coordinator.growspaces["tent_a"].irrigation_strategy.irrigation_program_id
        is None
    )


@pytest.mark.asyncio
async def test_assigning_to_an_unknown_growspace_is_refused(hass, coordinator) -> None:
    """The growspace narrowing the card can act on."""
    with pytest.raises(GrowspaceNotFoundError):
        await coordinator.services.growspaces.assign_irrigation_program("nope", None)


# ---------------------------------------------------------------------------
# Reading a bound growspace
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reads_the_current_slot_and_its_recipe(hass, coordinator) -> None:
    """The bound growspace reports where it is and what that slot holds."""
    recipe_id = await _saved_recipe(coordinator, "Flower wk3")
    program = await coordinator.services.config.save_irrigation_program(
        "Full run",
        _slots((CURRENT_STAGE, CURRENT_WEEK, recipe_id), ("veg", 1, recipe_id)),
    )
    await coordinator.services.growspaces.assign_irrigation_program(
        "tent_a", program.id
    )
    coordinator.cache.invalidate("tent_a")

    payload = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")
    reported = payload["irrigation"]["program"]

    assert reported["program_id"] == program.id
    assert reported["name"] == "Full run"
    assert reported["stage"] == CURRENT_STAGE
    assert reported["week"] == CURRENT_WEEK
    assert reported["slot"] == {
        "stage": CURRENT_STAGE,
        "week": CURRENT_WEEK,
        "recipe_id": recipe_id,
    }
    assert reported["recipe"]["id"] == recipe_id


@pytest.mark.asyncio
async def test_the_reported_week_is_the_feed_seam_s_own_answer(
    hass, coordinator
) -> None:
    """One week calculator: the program reports what the EC target reports."""
    from custom_components.growspace_manager.domain.ec_state import (
        resolve_feed_stage_week,
    )

    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 1, "r1"))
    )
    await coordinator.services.growspaces.assign_irrigation_program(
        "tent_a", program.id
    )
    coordinator.cache.invalidate("tent_a")

    payload = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")
    reported = payload["irrigation"]["program"]

    stage, week = resolve_feed_stage_week(
        coordinator.services.growspaces.get_growspace_plants("tent_a")
    )
    assert (reported["stage"], reported["week"]) == (stage, week)


@pytest.mark.asyncio
async def test_a_week_with_no_slot_reports_cleanly(hass, coordinator) -> None:
    """A gap in the plan is a hold, not an error that blanks the payload."""
    program = await coordinator.services.config.save_irrigation_program(
        "Veg only", _slots(("veg", 1, "r1"))
    )
    await coordinator.services.growspaces.assign_irrigation_program(
        "tent_a", program.id
    )
    coordinator.cache.invalidate("tent_a")

    reported = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")[
        "irrigation"
    ]["program"]

    assert reported["program_id"] == program.id
    assert reported["stage"] == "flower"
    assert reported["slot"] is None
    assert reported["recipe"] is None


@pytest.mark.asyncio
async def test_a_growspace_with_no_live_plants_reports_cleanly(
    hass, coordinator
) -> None:
    """No live cohort means no position to match, and that is a hold."""
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 1, "r1"))
    )
    await coordinator.services.growspaces.assign_irrigation_program(
        "tent_b", program.id
    )
    coordinator.cache.invalidate("tent_b")

    reported = ViewModelBuilder(coordinator).build_serialized_growspace("tent_b")[
        "irrigation"
    ]["program"]

    assert reported["stage"] is None
    assert reported["week"] == 0
    assert reported["slot"] is None
    assert reported["recipe"] is None


@pytest.mark.asyncio
async def test_a_slot_naming_a_deleted_recipe_reports_the_slot_without_it(
    hass, coordinator
) -> None:
    """Deleting a recipe empties slots rather than cascading (ADR-0045)."""
    recipe_id = await _saved_recipe(coordinator, "Flower wk3")
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots((CURRENT_STAGE, CURRENT_WEEK, recipe_id))
    )
    await coordinator.services.growspaces.assign_irrigation_program(
        "tent_a", program.id
    )

    await coordinator.services.config.remove_irrigation_recipe(recipe_id)
    coordinator.cache.invalidate("tent_a")

    reported = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")[
        "irrigation"
    ]["program"]

    assert reported["slot"]["recipe_id"] == recipe_id
    assert reported["recipe"] is None


@pytest.mark.asyncio
async def test_an_unbound_growspace_reports_no_program(hass, coordinator) -> None:
    """Nothing bound is null, distinct from bound-but-holding."""
    payload = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")

    assert payload["irrigation"]["program"] is None


@pytest.mark.asyncio
async def test_a_binding_naming_a_removed_program_reports_no_program(
    hass, coordinator
) -> None:
    """Removal leaves the id dangling; the read degrades rather than fails."""
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 1, "r1"))
    )
    await coordinator.services.growspaces.assign_irrigation_program(
        "tent_a", program.id
    )
    await coordinator.services.config.remove_irrigation_program(program.id)
    coordinator.cache.invalidate("tent_a")

    payload = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")

    assert payload["irrigation"]["program"] is None
    assert payload["irrigation"]["irrigation_strategy"]["irrigation_program_id"] == (
        program.id
    )


@pytest.mark.asyncio
async def test_the_bound_program_is_found_by_id_not_by_a_stage_scan(
    hass, coordinator
) -> None:
    """The ECRampCurve footgun, deliberately not repeated (ADR-0045).

    Two programs both define the growspace's current stage. Which one drives
    it must be the one its id names, never whichever the library iterates to
    first.
    """
    decoy = await coordinator.services.config.save_irrigation_program(
        "Decoy", _slots(("flower", 1, "decoy-recipe"))
    )
    chosen = await coordinator.services.config.save_irrigation_program(
        "Chosen", _slots(("flower", 1, "chosen-recipe"))
    )
    assert next(iter(coordinator._program_library.programs)) == decoy.id

    await coordinator.services.growspaces.assign_irrigation_program("tent_a", chosen.id)
    coordinator.cache.invalidate("tent_a")

    reported = ViewModelBuilder(coordinator).build_serialized_growspace("tent_a")[
        "irrigation"
    ]["program"]

    assert reported["program_id"] == chosen.id
    assert reported["name"] == "Chosen"


@pytest.mark.asyncio
async def test_the_library_rides_every_growspace_payload(hass, coordinator) -> None:
    """Global, so the card's editor seeds from the payload it already has."""
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(("flower", 1, "r1"))
    )
    coordinator.cache.invalidate("tent_b")

    payload = ViewModelBuilder(coordinator).build_serialized_growspace("tent_b")

    assert list(payload["irrigation"]["programs"]) == [program.id]


@pytest.mark.asyncio
async def test_a_program_error_is_raised_as_a_domain_refusal(coordinator) -> None:
    """The facade surfaces the domain's refusal rather than swallowing it."""
    with pytest.raises(ProgramError, match="1-indexed"):
        await coordinator.services.config.save_irrigation_program(
            "Bad", _slots(("veg", 0, "r1"))
        )
