"""Tests for the pure Irrigation Program rules (ADR-0045)."""

import pytest

from custom_components.growspace_manager.domain.irrigation_program import (
    ProgramError,
    ProgramHold,
    ProgramProgression,
    ProgramProgressionState,
    build_program_slots,
    resolve_program_progression,
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


def _progression(
    program: IrrigationProgram,
    *,
    stage: str | None = "flower",
    week: int = 3,
    slot_recipe_name: str | None = "Week 3",
    applied_recipe_id: str | None = None,
    applied_recipe_drifted: bool = False,
    apply_error: str | None = None,
    auto_advance: bool = False,
) -> ProgramProgression:
    """Resolve the progression at ``(stage, week)``, defaulting the facts."""
    return resolve_program_progression(
        program,
        stage=stage,
        week=week,
        slot=resolve_program_slot(program, stage=stage, week=week),
        slot_recipe_name=slot_recipe_name,
        applied_recipe_id=applied_recipe_id,
        applied_recipe_drifted=applied_recipe_drifted,
        apply_error=apply_error,
        auto_advance=auto_advance,
    )


class TestResolveProgramProgression:
    """The [[Program Hold]] rule: one behaviour, causes told apart."""

    def test_a_new_week_is_due_under_auto_advance(self) -> None:
        """Auto-advance on, a slot to reach and nothing in the way: stamp it."""
        progression = _progression(_program(("flower", 3, "r3")), auto_advance=True)

        assert progression.state is ProgramProgressionState.DUE
        assert progression.hold is None

    def test_a_new_week_only_becomes_available_with_auto_advance_off(self) -> None:
        """The default: the payload recommends and the grower confirms."""
        progression = _progression(_program(("flower", 3, "r3")))

        assert progression.state is ProgramProgressionState.AVAILABLE
        assert progression.hold is None
        assert "Week 3" in progression.detail

    def test_a_slot_already_applied_is_up_to_date(self) -> None:
        """What makes an automatic stamp happen exactly once."""
        progression = _progression(
            _program(("flower", 3, "r3")), applied_recipe_id="r3", auto_advance=True
        )

        assert progression.state is ProgramProgressionState.UP_TO_DATE

    def test_a_hand_tweak_after_the_slot_was_applied_is_left_alone(self) -> None:
        """Drift on the week's own recipe is the grower's, never re-stamped."""
        progression = _progression(
            _program(("flower", 3, "r3")),
            applied_recipe_id="r3",
            applied_recipe_drifted=True,
            auto_advance=True,
        )

        assert progression.state is ProgramProgressionState.UP_TO_DATE

    def test_drift_holds_the_advance_and_says_so(self) -> None:
        """Auto-advance never overwrites hand-tuning (ADR-0045)."""
        progression = _progression(
            _program(("flower", 3, "r3")),
            applied_recipe_id="r1",
            applied_recipe_drifted=True,
            auto_advance=True,
        )

        assert progression.state is ProgramProgressionState.HELD
        assert progression.hold is ProgramHold.DRIFTED

    def test_drift_does_not_hold_when_auto_advance_is_off(self) -> None:
        """Nothing is being written, so there is nothing to protect."""
        progression = _progression(
            _program(("flower", 3, "r3")),
            applied_recipe_id="r1",
            applied_recipe_drifted=True,
        )

        assert progression.state is ProgramProgressionState.AVAILABLE

    @pytest.mark.parametrize("auto_advance", [True, False])
    def test_a_week_with_no_slot_holds(self, auto_advance: bool) -> None:
        """Identical under both settings: no instruction, so no change."""
        progression = _progression(
            _program(("flower", 1, "r1"), ("flower", 5, "r5")),
            slot_recipe_name=None,
            auto_advance=auto_advance,
        )

        assert progression.state is ProgramProgressionState.HELD
        assert progression.hold is ProgramHold.NO_SLOT

    def test_past_the_last_week_reports_the_program_complete(self) -> None:
        """A finished run must not read as a broken plan."""
        progression = _progression(
            _program(("flower", 1, "r1")), week=9, slot_recipe_name=None
        )

        assert progression.state is ProgramProgressionState.HELD
        assert progression.hold is ProgramHold.PROGRAM_COMPLETE
        assert "complete" in progression.detail

    def test_a_later_stage_is_also_past_the_end(self) -> None:
        """Run order, not week number alone, decides what "past" means."""
        progression = _progression(
            _program(("veg", 2, "r1")),
            stage="flower",
            week=1,
            slot_recipe_name=None,
        )

        assert progression.hold is ProgramHold.PROGRAM_COMPLETE

    def test_an_earlier_stage_is_a_gap_not_a_finished_run(self) -> None:
        """A flower-only plan has simply not started in veg."""
        progression = _progression(
            _program(("flower", 1, "r1")),
            stage="veg",
            week=1,
            slot_recipe_name=None,
        )

        assert progression.hold is ProgramHold.NO_SLOT

    def test_an_empty_plan_has_no_end_to_be_past(self) -> None:
        """It defines nothing anywhere, which is a gap."""
        progression = _progression(_program(), slot_recipe_name=None)

        assert progression.hold is ProgramHold.NO_SLOT

    def test_no_live_plants_gives_no_position(self) -> None:
        """``resolve_feed_stage_week`` answers (None, 0); that is its own hold."""
        progression = _progression(
            _program(("flower", 3, "r3")), stage=None, week=0, slot_recipe_name=None
        )

        assert progression.hold is ProgramHold.NO_POSITION

    @pytest.mark.parametrize("auto_advance", [True, False])
    def test_a_deleted_recipe_behaves_as_a_gap(self, auto_advance: bool) -> None:
        """Deleting a recipe leaves empty slots, and a gap never actuates."""
        progression = _progression(
            _program(("flower", 3, "r3")),
            slot_recipe_name=None,
            auto_advance=auto_advance,
        )

        assert progression.state is ProgramProgressionState.HELD
        assert progression.hold is ProgramHold.RECIPE_MISSING

    @pytest.mark.parametrize("auto_advance", [True, False])
    def test_a_recipe_that_cannot_be_stamped_holds_with_its_refusal(
        self, auto_advance: bool
    ) -> None:
        """A refusal is reported as the hold's detail, not raised at the tick."""
        progression = _progression(
            _program(("flower", 3, "r3")),
            apply_error="Cannot apply the schedule irrigation recipe 'Week 3'.",
            auto_advance=auto_advance,
        )

        assert progression.hold is ProgramHold.NOT_APPLICABLE
        assert progression.detail.startswith("Cannot apply")
