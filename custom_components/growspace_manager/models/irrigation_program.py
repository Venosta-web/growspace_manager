"""Irrigation Program — a whole-run plan of Irrigation Recipes.

An ordered plan assigning [[Irrigation Recipe]]s to ``(stage, week)`` slots
across a whole run, bound to a growspace by an explicit
``irrigation_program_id`` (CONTEXT.md "Irrigation Program", ADR-0045).

Two shapes are load-bearing here.

Recipes are held **by reference** — a slot stores a ``recipe_id`` and nothing
else. Fixing a bad shot size in one recipe therefore fixes it in every program
using it, and there is never a second copy to diverge from. The by-value
snapshot already exists on the growspace, written at the moment of the stamp,
which is exactly what leaves a program free to be a *plan* rather than a
record of what was done.

The plan is **whole-run** rather than per-stage. A program that defines only
flower slots already *is* a per-stage program, whereas a per-stage shape would
additionally need a rule for the veg→flower handoff.

A slot referencing a recipe the library no longer holds is not an error:
deleting a recipe leaves empty slots rather than cascading, and an empty slot
degrades to [[Program Hold]] — no instruction, so nothing can actuate.
``domain/irrigation_program.py`` owns what a slot means and which one a
growspace is in.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import homeassistant.util.dt as dt_util

from .base import BaseModel

__all__ = ["IrrigationProgram", "ProgramSlot"]


@dataclass(slots=True)
class ProgramSlot(BaseModel):
    """One ``(stage, week)`` position in a program and the recipe it holds.

    ``stage`` is one of the live stages [[Recipe Week Resolution]] can answer
    with and ``week`` is 1-indexed, matching ``days_to_week``. ``recipe_id``
    names a recipe in the global library; it is deliberately not resolved
    here, because a program holds recipes by reference.
    """

    stage: str
    week: int
    recipe_id: str


@dataclass(slots=True, kw_only=True)
class IrrigationProgram(BaseModel):
    """One saved program in the global library.

    ``slots`` are kept in run order — by stage progression, then by week — so
    the stored plan reads the way the run does. There is at most one slot per
    ``(stage, week)``; the library refuses a program carrying two.
    """

    id: str
    name: str
    slots: list[ProgramSlot] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())
