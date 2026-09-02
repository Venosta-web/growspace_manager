"""Irrigation Program rules — building a plan and finding a growspace's slot.

Pure over models and plain values: no ``hass``, no coordinator, no storage
(the [[Pump Cycle Gate]] / [[EC State]] mould). ``managers/irrigation_program.py``
owns storage and identity; this module owns what a slot *is* and which one a
growspace is currently in.

Three rules live here, and they are the whole module.

**A slot must be reachable.** [[Recipe Week Resolution]] answers ``(stage,
week)`` for a growspace through ``resolve_feed_stage_week`` — the same seam the
feed EC target uses, reused unchanged so one card never shows two different
weeks for one tent. That seam can only ever answer with a live stage and a
1-indexed week, so a slot keyed by anything else is dead on arrival and the
save is refused naming it. A silently unreachable slot would read as a plan the
grower had made and the system had quietly ignored.

**Resolution is exact, and anything else holds.** ``resolve_program_slot``
matches ``(stage, week)`` exactly or answers ``None``. That one answer covers
every ambiguous case [[Program Hold]] names — a week with no slot, a week past
the end of the plan, a growspace with no live plants at all — because carrying
the previous week's recipe forward into an undefined week would produce
actuation from the *absence* of data (ADR-0045).

**Holding is a reported state, not silence.** ``resolve_program_progression``
turns a resolved position into the one thing the layer will do about it —
nothing, recommend, or stamp — and names *why* whenever the answer is nothing.
It stays pure by taking the facts it judges rather than looking them up: which
recipe is applied, whether the growspace has drifted from it, whether the
slot's recipe can be applied at all. ``irrigation_program_progression.py``
gathers those facts and acts on the answer; keeping the rule here is what lets
the payload the grower reads and the stamp the tick writes be the same
decision rather than two that can disagree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.models.irrigation_program import ProgramSlot

from .ec_state import LIVE_STAGE_ORDER

if TYPE_CHECKING:
    from custom_components.growspace_manager.models.irrigation_program import (
        IrrigationProgram,
    )

__all__ = [
    "SLOT_FIELDS",
    "ProgramError",
    "ProgramHold",
    "ProgramProgression",
    "ProgramProgressionState",
    "build_program_slots",
    "resolve_program_progression",
    "resolve_program_slot",
]

# The keys one slot payload may carry. Named rather than derived so an unknown
# key is refused instead of silently dropped.
SLOT_FIELDS: frozenset[str] = frozenset({"stage", "week", "recipe_id"})


class ProgramError(ValueError):
    """A payload that cannot become an Irrigation Program."""


def build_program_slots(slots: Iterable[Mapping[str, Any]]) -> list[ProgramSlot]:
    """Validate raw slot payloads into a program's ordered slot list.

    Every refusal is raised before a single slot is built, so a caller that
    stores the result stores either the whole plan or none of it.

    The returned list is in run order — stage progression, then week — because
    a program is a plan for a run and reading it in insertion order would say
    nothing about when its parts apply.

    Raises:
        ProgramError: for an unknown key, a missing one, a stage
            [[Recipe Week Resolution]] can never answer with, a week below 1,
            a blank recipe id, or two slots claiming the same ``(stage, week)``.
    """
    built: list[ProgramSlot] = []
    seen: set[tuple[str, int]] = set()

    for index, raw in enumerate(slots):
        stage, week, recipe_id = _slot_values(raw, index)
        if (stage, week) in seen:
            raise ProgramError(
                f"Two slots claim {stage} week {week}. A program holds at most "
                "one recipe per stage and week."
            )
        seen.add((stage, week))
        built.append(ProgramSlot(stage=stage, week=week, recipe_id=recipe_id))

    built.sort(key=lambda slot: (LIVE_STAGE_ORDER[slot.stage], slot.week))
    return built


def resolve_program_slot(
    program: IrrigationProgram, *, stage: str | None, week: int
) -> ProgramSlot | None:
    """Return the slot a growspace at ``(stage, week)`` is in, or None.

    ``stage``/``week`` come from ``resolve_feed_stage_week`` and nowhere else.
    ``None`` is the [[Program Hold]] answer and covers every ambiguous case at
    once: a growspace with no live plants (``stage`` is ``None``), a week the
    plan does not define, and a week past the end of it. Matching is exact —
    the previous week's recipe is never carried forward, because that would
    mean actuating on the absence of an instruction rather than the presence
    of one.
    """
    if stage is None:
        return None
    return next(
        (slot for slot in program.slots if slot.stage == stage and slot.week == week),
        None,
    )


class ProgramHold(StrEnum):
    """Why an [[Irrigation Program]] has no unambiguous instruction right now.

    One rule with several causes, named separately only so the payload can say
    which one it hit — the behaviour is identical in every case: nothing is
    written. A cause that reads as a fault (``recipe_missing``) and one that
    reads as success (``program_complete``) must not both surface as a blank
    answer, or a grower cannot tell a finished run from a broken plan.
    """

    # ``resolve_feed_stage_week`` found no live stage: the growspace is empty,
    # or everything in it is drying or curing. There is no position to match.
    NO_POSITION = "no_position"
    # The plan defines nothing for this week, and defines something later.
    NO_SLOT = "no_slot"
    # Past the last slot in the plan. The run has outlived the program, which
    # is what finishing looks like rather than what breaking looks like.
    PROGRAM_COMPLETE = "program_complete"
    # The slot names a recipe the library no longer holds. Deleting a recipe
    # leaves empty slots rather than cascading, and an empty slot is a gap.
    RECIPE_MISSING = "recipe_missing"
    # Auto-advance only: the growspace no longer holds what its applied recipe
    # stamped. Overwriting a hand tweak would make hand-tuning worthless
    # whenever auto-advance is on, and the damage stays invisible until the
    # plants show it (ADR-0045).
    DRIFTED = "drifted"
    # The slot's recipe cannot be stamped into *this* growspace at all — it
    # holds the half the growspace is not running, or a Seconds Mode target
    # lacks the plumbing its percents need.
    NOT_APPLICABLE = "not_applicable"


class ProgramProgressionState(StrEnum):
    """What the program layer will do about a growspace's current position."""

    # The growspace already holds the slot's recipe. Nothing is due; a later
    # hand tweak is the grower's and is never stamped back over.
    UP_TO_DATE = "up_to_date"
    # A new week's recipe is ready and auto-advance is off, so the grower
    # applies it. Nothing is written until they do.
    AVAILABLE = "available"
    # Auto-advance is on and the stamp is owed. Transient: the next evaluation
    # writes it and the state settles to ``up_to_date``.
    DUE = "due"
    # [[Program Hold]] — nothing changes, and ``hold`` says why.
    HELD = "held"


@dataclass(frozen=True, slots=True)
class ProgramProgression:
    """The one decision the program layer makes about one growspace.

    ``detail`` is a grower-facing sentence written here rather than at each
    surface, so the payload, the log line and the notification say the same
    thing about the same hold.
    """

    state: ProgramProgressionState
    detail: str
    hold: ProgramHold | None = None


def resolve_program_progression(
    program: IrrigationProgram,
    *,
    stage: str | None,
    week: int,
    slot: ProgramSlot | None,
    slot_recipe_name: str | None,
    applied_recipe_id: str | None,
    applied_recipe_drifted: bool,
    apply_error: str | None,
    auto_advance: bool,
) -> ProgramProgression:
    """Decide what ``program`` does for a growspace at ``(stage, week)``.

    Pure: it decides, it never writes and never looks anything up. Every fact
    it judges arrives as an argument — ``slot`` from ``resolve_program_slot``,
    ``slot_recipe_name`` from the recipe library (``None`` when the slot names
    a recipe that has since been deleted), ``applied_recipe_drifted`` from
    ``recipe_has_drifted``, ``apply_error`` from a resolution that was
    attempted and refused. That is what lets the read path and the write path
    reach the same answer instead of two that can disagree.

    The order of the checks is the rule. A hold that describes the *plan* is
    reported before one that describes the growspace, because a grower fixing
    a gap in the plan and a grower undoing a tweak are different repairs and
    the first is the one the program layer knows about. Within that,
    ``up_to_date`` outranks every remaining cause: once the slot's recipe has
    been stamped there is nothing owed, and re-stamping it to "correct" a
    later hand tweak is precisely what [[Program Hold]] exists to prevent.
    """
    if stage is None or stage not in LIVE_STAGE_ORDER:
        return ProgramProgression(
            state=ProgramProgressionState.HELD,
            hold=ProgramHold.NO_POSITION,
            detail=(
                f"Irrigation program '{program.name}' is holding: the growspace "
                "has no live plants, so it is in no week of the plan."
            ),
        )

    if slot is None:
        if _is_past_program_end(program, stage=stage, week=week):
            return ProgramProgression(
                state=ProgramProgressionState.HELD,
                hold=ProgramHold.PROGRAM_COMPLETE,
                detail=(
                    f"Irrigation program '{program.name}' is complete: "
                    f"{stage} week {week} is past its last slot. Settings are "
                    "left exactly as they are."
                ),
            )
        return ProgramProgression(
            state=ProgramProgressionState.HELD,
            hold=ProgramHold.NO_SLOT,
            detail=(
                f"Irrigation program '{program.name}' defines no slot for "
                f"{stage} week {week}, so nothing changes."
            ),
        )

    if slot_recipe_name is None:
        return ProgramProgression(
            state=ProgramProgressionState.HELD,
            hold=ProgramHold.RECIPE_MISSING,
            detail=(
                f"Irrigation program '{program.name}' has a gap at {stage} "
                f"week {week}: the recipe it names no longer exists."
            ),
        )

    if slot.recipe_id == applied_recipe_id:
        return ProgramProgression(
            state=ProgramProgressionState.UP_TO_DATE,
            detail=(
                f"Irrigation recipe '{slot_recipe_name}' is the one this "
                f"growspace is running, as {stage} week {week} calls for."
            ),
        )

    if apply_error is not None:
        return ProgramProgression(
            state=ProgramProgressionState.HELD,
            hold=ProgramHold.NOT_APPLICABLE,
            detail=apply_error,
        )

    if not auto_advance:
        return ProgramProgression(
            state=ProgramProgressionState.AVAILABLE,
            detail=(
                f"{stage.capitalize()} week {week} calls for irrigation recipe "
                f"'{slot_recipe_name}'. Auto-advance is off, so nothing has "
                "been changed."
            ),
        )

    if applied_recipe_drifted:
        return ProgramProgression(
            state=ProgramProgressionState.HELD,
            hold=ProgramHold.DRIFTED,
            detail=(
                f"Irrigation program '{program.name}' is holding at {stage} "
                f"week {week}: this growspace's settings no longer match the "
                "recipe last applied to it, and auto-advance never overwrites "
                f"a hand tweak. Apply '{slot_recipe_name}' yourself to advance."
            ),
        )

    return ProgramProgression(
        state=ProgramProgressionState.DUE,
        detail=(
            f"{stage.capitalize()} week {week} calls for irrigation recipe "
            f"'{slot_recipe_name}', and auto-advance is on."
        ),
    )


def _is_past_program_end(program: IrrigationProgram, *, stage: str, week: int) -> bool:
    """Return whether ``(stage, week)`` lies beyond the plan's last slot.

    Slots are stored in run order, so the last one is the end of the plan. An
    empty program has no end to be past: it defines nothing anywhere, which is
    a gap rather than a finished run.
    """
    if not program.slots:
        return False
    last = program.slots[-1]
    return (LIVE_STAGE_ORDER[stage], week) > (LIVE_STAGE_ORDER[last.stage], last.week)


def _slot_values(raw: Mapping[str, Any], index: int) -> tuple[str, int, str]:
    """Validate one raw slot payload into its three checked values."""
    unknown = sorted(set(raw) - SLOT_FIELDS)
    if unknown:
        raise ProgramError(
            f"Slot {index} names {', '.join(unknown)}, which "
            f"{'are' if len(unknown) > 1 else 'is'} not part of a program slot."
        )
    missing = sorted(SLOT_FIELDS - set(raw))
    if missing:
        raise ProgramError(f"Slot {index} is missing {', '.join(missing)}.")

    stage = raw["stage"]
    if stage not in LIVE_STAGE_ORDER:
        raise ProgramError(
            f"Slot {index} is keyed by stage '{stage}', which a growspace's "
            "current stage is never resolved to. A slot must name one of: "
            f"{', '.join(LIVE_STAGE_ORDER)}."
        )

    try:
        week = int(raw["week"])
    except (TypeError, ValueError) as err:
        raise ProgramError(f"Slot {index} has a non-numeric week.") from err
    if week < 1:
        raise ProgramError(
            f"Slot {index} is keyed by week {week}. Weeks are 1-indexed, as "
            "``days_to_week`` counts them."
        )

    recipe_id = str(raw["recipe_id"]).strip()
    if not recipe_id:
        raise ProgramError(f"Slot {index} names no recipe.")

    return stage, week, recipe_id
