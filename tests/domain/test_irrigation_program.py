"""Tests for the pure Irrigation Program rules (ADR-0045)."""

import pytest

from custom_components.growspace_manager.domain.irrigation_program import (
    ProgramError,
    build_program_slots,
    resolve_program_slot,
)
from custom_components.growspace_manager.models import IrrigationProgram, ProgramSlot


def _program(*slots: tuple[str, int, str]) -> IrrigationProgram:
    """Return a program holding the given ``(stage, week, recipe_id)`` slots."""
    return IrrigationProgram(
        id="prog-1",
        name="Full run",
        slots=build_program_slots(
            [
                {"stage": stage, "week": week, "recipe_id": recipe_id}
                for stage, week, recipe_id in slots
            ]
        ),
    )


class TestBuildProgramSlots:
    """Turning raw slot payloads into a validated, ordered plan."""

    def test_orders_slots_by_stage_progression_then_week(self) -> None:
        """A plan reads in run order regardless of the order it arrived in."""
        slots = build_program_slots(
            [
                {"stage": "flower", "week": 3, "recipe_id": "r3"},
                {"stage": "veg", "week": 2, "recipe_id": "r2"},
                {"stage": "flower", "week": 1, "recipe_id": "r1"},
                {"stage": "seedling", "week": 1, "recipe_id": "r0"},
            ]
        )

        assert [(slot.stage, slot.week) for slot in slots] == [
            ("seedling", 1),
            ("veg", 2),
            ("flower", 1),
            ("flower", 3),
        ]

    def test_accepts_an_empty_plan(self) -> None:
        """A program a grower has emptied is a program, not a refusal."""
        assert build_program_slots([]) == []

    def test_coerces_a_numeric_week(self) -> None:
        """A week arriving as a string from the wire is still a week."""
        (slot,) = build_program_slots(
            [{"stage": "veg", "week": "2", "recipe_id": "r1"}]
        )

        assert slot == ProgramSlot(stage="veg", week=2, recipe_id="r1")

    def test_refuses_a_stage_no_growspace_resolves_to(self) -> None:
        """A slot that could never match is refused, not stored dead."""
        with pytest.raises(ProgramError, match="dry"):
            build_program_slots([{"stage": "dry", "week": 1, "recipe_id": "r1"}])

    def test_refuses_a_week_below_one(self) -> None:
        """Weeks are 1-indexed, as ``days_to_week`` counts them."""
        with pytest.raises(ProgramError, match="1-indexed"):
            build_program_slots([{"stage": "veg", "week": 0, "recipe_id": "r1"}])

    def test_refuses_a_non_numeric_week(self) -> None:
        """A week that is not a number names no position at all."""
        with pytest.raises(ProgramError, match="non-numeric"):
            build_program_slots([{"stage": "veg", "week": "wk2", "recipe_id": "r1"}])

    def test_refuses_two_slots_claiming_one_position(self) -> None:
        """Last-wins would silently drop half of what the grower authored."""
        with pytest.raises(ProgramError, match="Two slots claim"):
            build_program_slots(
                [
                    {"stage": "veg", "week": 1, "recipe_id": "r1"},
                    {"stage": "veg", "week": 1, "recipe_id": "r2"},
                ]
            )

    def test_refuses_a_blank_recipe_id(self) -> None:
        """A slot naming no recipe is an empty slot pretending to be full."""
        with pytest.raises(ProgramError, match="names no recipe"):
            build_program_slots([{"stage": "veg", "week": 1, "recipe_id": "  "}])

    def test_refuses_an_unknown_key(self) -> None:
        """An unknown key is a caller error, never silently dropped."""
        with pytest.raises(ProgramError, match="duration"):
            build_program_slots(
                [{"stage": "veg", "week": 1, "recipe_id": "r1", "duration": 5}]
            )

    def test_refuses_a_missing_key(self) -> None:
        """A slot is all three of its parts or none of them."""
        with pytest.raises(ProgramError, match="recipe_id"):
            build_program_slots([{"stage": "veg", "week": 1}])

    def test_refuses_before_building_anything(self) -> None:
        """A refusal on a later slot leaves no earlier slot half-built."""
        with pytest.raises(ProgramError):
            build_program_slots(
                [
                    {"stage": "veg", "week": 1, "recipe_id": "r1"},
                    {"stage": "cure", "week": 1, "recipe_id": "r2"},
                ]
            )


class TestResolveProgramSlot:
    """Finding the slot a growspace is currently in — and holding otherwise."""

    def test_matches_the_exact_stage_and_week(self) -> None:
        """The plan's answer for a defined position is that position's slot."""
        program = _program(("veg", 1, "r1"), ("flower", 2, "r2"))

        slot = resolve_program_slot(program, stage="flower", week=2)

        assert slot == ProgramSlot(stage="flower", week=2, recipe_id="r2")

    def test_holds_on_an_undefined_week(self) -> None:
        """A gap in the plan is no instruction, so nothing changes."""
        program = _program(("flower", 1, "r1"), ("flower", 3, "r2"))

        assert resolve_program_slot(program, stage="flower", week=2) is None

    def test_holds_past_the_end_of_the_plan(self) -> None:
        """The last week is never carried forward into an undefined one."""
        program = _program(("flower", 1, "r1"), ("flower", 3, "r2"))

        assert resolve_program_slot(program, stage="flower", week=9) is None

    def test_holds_on_a_stage_the_plan_does_not_cover(self) -> None:
        """A flower-only plan is a per-stage plan; veg simply holds."""
        program = _program(("flower", 1, "r1"))

        assert resolve_program_slot(program, stage="veg", week=1) is None

    def test_holds_when_no_live_plants_give_a_position(self) -> None:
        """``resolve_feed_stage_week`` answers (None, 0); that is a hold."""
        program = _program(("flower", 1, "r1"))

        assert resolve_program_slot(program, stage=None, week=0) is None

    def test_holds_on_an_empty_program(self) -> None:
        """An emptied plan resolves to nothing rather than raising."""
        assert resolve_program_slot(_program(), stage="flower", week=1) is None
