"""Irrigation Program rules — building a plan and finding a growspace's slot.

Pure over models and plain values: no ``hass``, no coordinator, no storage
(the [[Pump Cycle Gate]] / [[EC State]] mould). ``managers/irrigation_program.py``
owns storage and identity; this module owns what a slot *is* and which one a
growspace is currently in.

Two rules live here, and they are the whole module.

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
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
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
    "build_program_slots",
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
