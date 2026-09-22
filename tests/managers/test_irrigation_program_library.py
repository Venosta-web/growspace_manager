"""Tests for the global Irrigation Program library (ADR-0045)."""

from unittest.mock import AsyncMock

import pytest

from custom_components.growspace_manager.domain.irrigation_program import ProgramError
from custom_components.growspace_manager.exceptions import EntityNotFoundError
from custom_components.growspace_manager.managers.irrigation_program import (
    IrrigationProgramLibrary,
)
from custom_components.growspace_manager.models import IrrigationProgram, ProgramSlot


@pytest.fixture
def save_callback() -> AsyncMock:
    """Mock the coordinator save callback."""
    return AsyncMock()


@pytest.fixture
def library(save_callback) -> IrrigationProgramLibrary:
    """An empty program library."""
    return IrrigationProgramLibrary(save_callback)


def _slots(*slots: tuple[str, int, str]) -> list[dict]:
    """Return raw slot payloads for ``(stage, week, recipe_id)`` triples."""
    return [
        {"stage": stage, "week": week, "recipe_id": recipe_id}
        for stage, week, recipe_id in slots
    ]


@pytest.mark.asyncio
async def test_saves_a_program_and_persists_it(library, save_callback) -> None:
    """A saved program lands in the library and is committed once."""
    program = await library.async_save_program(
        "Full run", _slots(("veg", 1, "r1"), ("flower", 1, "r2"))
    )

    assert library.programs == {program.id: program}
    assert program.name == "Full run"
    assert program.slots == [
        ProgramSlot(stage="veg", week=1, recipe_id="r1"),
        ProgramSlot(stage="flower", week=1, recipe_id="r2"),
    ]
    save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_same_recipe_may_occupy_slots_in_several_programs(library) -> None:
    """Recipes are held by reference, so nothing is consumed by a program."""
    first = await library.async_save_program("Veg plan", _slots(("veg", 1, "shared")))
    second = await library.async_save_program(
        "Flower plan", _slots(("flower", 1, "shared"), ("flower", 2, "shared"))
    )

    assert first.slots[0].recipe_id == "shared"
    assert [slot.recipe_id for slot in second.slots] == ["shared", "shared"]


@pytest.mark.asyncio
async def test_saves_a_slot_naming_an_absent_recipe(library) -> None:
    """A dangling reference is a Program Hold, never a storage error.

    Recipes are deleted independently of the programs referencing them, so
    refusing here would make re-saving an untouched program fail because of a
    deletion elsewhere in it.
    """
    program = await library.async_save_program("Plan", _slots(("veg", 1, "gone")))

    assert program.slots[0].recipe_id == "gone"


@pytest.mark.asyncio
async def test_overwriting_replaces_the_plan_and_keeps_the_creation_time(
    library,
) -> None:
    """An ordered plan is edited as a whole, not merged into."""
    original = await library.async_save_program(
        "Full run", _slots(("veg", 1, "r1"), ("flower", 1, "r2"))
    )

    edited = await library.async_save_program(
        "Full run v2", _slots(("flower", 1, "r9")), program_id=original.id
    )

    assert edited.id == original.id
    assert edited.created_at == original.created_at
    assert edited.name == "Full run v2"
    assert edited.slots == [ProgramSlot(stage="flower", week=1, recipe_id="r9")]
    assert library.programs == {original.id: edited}


@pytest.mark.asyncio
async def test_refuses_a_blank_name(library, save_callback) -> None:
    """A nameless plan cannot be picked out of a library."""
    with pytest.raises(ProgramError, match="cannot be blank"):
        await library.async_save_program("   ", _slots(("veg", 1, "r1")))

    assert library.programs == {}
    save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_refused_save_leaves_the_library_untouched(library) -> None:
    """Validation happens in full before anything is stored."""
    original = await library.async_save_program("Plan", _slots(("veg", 1, "r1")))

    with pytest.raises(ProgramError):
        await library.async_save_program(
            "Plan", _slots(("dry", 1, "r2")), program_id=original.id
        )

    assert library.programs == {original.id: original}


@pytest.mark.asyncio
async def test_get_program_hands_out_the_stored_instance(library) -> None:
    """A program is held by reference wherever it is used."""
    program = await library.async_save_program("Plan", _slots(("veg", 1, "r1")))

    assert library.get_program(program.id) is program


def test_get_program_refuses_an_unknown_id(library) -> None:
    """The strict lookup names the id it could not find."""
    with pytest.raises(EntityNotFoundError, match="nope"):
        library.get_program("nope")


@pytest.mark.asyncio
async def test_removes_a_program(library, save_callback) -> None:
    """Removal drops the program and commits."""
    program = await library.async_save_program("Plan", _slots(("veg", 1, "r1")))
    save_callback.reset_mock()

    await library.async_remove_program(program.id)

    assert library.programs == {}
    save_callback.assert_awaited_once()


@pytest.mark.asyncio
async def test_removing_an_unknown_program_is_refused(library, save_callback) -> None:
    """Nothing is committed for a removal that removed nothing."""
    with pytest.raises(EntityNotFoundError):
        await library.async_remove_program("nope")

    save_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_serializes_under_the_stored_key_and_round_trips(library) -> None:
    """The library rides the config document beside the recipes."""
    program = await library.async_save_program("Plan", _slots(("flower", 2, "r1")))

    data = library.get_serialization_data()

    assert set(data) == {"irrigation_programs"}
    restored = {
        pid: IrrigationProgram.from_dict(raw)
        for pid, raw in data["irrigation_programs"].items()
    }
    assert restored == {program.id: program}


def test_load_data_replaces_the_library(library) -> None:
    """StorageManager hands the whole library over on load."""
    stored = {"p1": IrrigationProgram(id="p1", name="Loaded")}

    library.load_data(stored)

    assert library.programs is stored
