"""Irrigation Program progression — carrying a growspace week to week.

The layer that turns a bound [[Irrigation Program]] from something you can
read into something that can act. ``domain/irrigation_program.py`` owns the
rule; this module gathers the facts that rule judges and does the one thing it
asks for.

Everything hangs off one function. ``resolve_program_position`` answers, for a
growspace, where it is in its plan and what the plan will do about it — and
both callers use that same answer. The view model serializes it onto
``irrigation.program``; the coordinator's tick acts on it. They cannot disagree
about whether a week is held, because there is only one place that decides.

The [[Program Hold]] is the whole point of the layer, so the failure mode is
worth stating plainly: whenever the program has no unambiguous instruction,
**nothing is written**. A week with no slot, a week past the end of the plan, a
slot naming a deleted recipe, a recipe that cannot be stamped into this
growspace at all, and — under auto-advance — a growspace whose fields have
drifted from its [[Recipe Stamp]] all resolve to the same behaviour: the tent
keeps doing what it was doing. What differs between them is only what the
payload says, so that a finished run never reads as a broken one.

Auto-advance is opt-in and off by default (``program_auto_advance``). With it
off this module writes nothing at all: it resolves the position, the payload
says a new week's recipe is available, and the grower applies it. With it on,
crossing into a week that has a slot stamps that slot's recipe **once** — the
next evaluation finds the growspace already holding it and does nothing, which
is also why a hand tweak made afterwards is never stamped back over.

A hold that blocks a stamp the grower opted into is the one case worth
interrupting them for, so those are notified as well as reported. The quiet
holds — no slot this week, program complete, no live plants — are payload-only:
a plan that skips weeks would otherwise notify on every one of them.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .domain.ec_state import resolve_feed_stage_week
from .domain.irrigation_program import (
    ProgramHold,
    ProgramProgression,
    ProgramProgressionState,
    resolve_program_progression,
    resolve_program_slot,
)
from .domain.irrigation_recipe import (
    RecipeApplication,
    RecipeApplyError,
    recipe_has_drifted,
    resolve_recipe_application,
)
from .domain.plant_metrics import count_live_plants
from .services.strategy_stamp import StrategyStamp, async_apply_strategy_stamp

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
    from .models import Growspace, Plant
    from .models.irrigation_program import IrrigationProgram, ProgramSlot
    from .models.irrigation_recipe import IrrigationRecipe

_LOGGER = logging.getLogger(__name__)

__all__ = [
    "IrrigationProgramProgression",
    "ProgramPosition",
    "resolve_program_position",
]

# The holds worth interrupting a grower for, and only while auto-advance is on:
# each one blocks a stamp they opted into, and each needs a decision only they
# can make — undo the tweak, restore the recipe, or switch the growspace to the
# half the recipe holds. With auto-advance off nothing was going to be written
# anyway, so the payload is the whole of what needs saying.
_ANNOUNCED_HOLDS = frozenset(
    {ProgramHold.DRIFTED, ProgramHold.RECIPE_MISSING, ProgramHold.NOT_APPLICABLE}
)


@dataclass(frozen=True, slots=True)
class ProgramPosition:
    """Where a growspace sits in its bound program, and what follows from it.

    ``application`` is what a stamp of ``recipe`` would write into *this*
    growspace, resolved once here rather than twice: the progression rule needs
    to know whether it can be resolved at all, and the stamp needs the values
    themselves. ``None`` when there is no slot recipe to resolve, or when
    resolving it was refused — in which case ``progression`` is a hold naming
    the refusal.
    """

    program: IrrigationProgram
    stage: str | None
    week: int
    slot: ProgramSlot | None
    recipe: IrrigationRecipe | None
    auto_advance: bool
    progression: ProgramProgression
    application: RecipeApplication | None


def resolve_program_position(
    coordinator: GrowspaceCoordinator,
    growspace: Growspace,
    plants: list[Plant],
) -> ProgramPosition | None:
    """Resolve a growspace's place in its bound program, or None if unbound.

    A read: it resolves and decides, it never writes. ``None`` means the
    question does not apply — nothing is bound, or the binding names a program
    the library no longer holds (removing a program leaves the id dangling by
    design, exactly as deleting a recipe does).

    The position comes from ``resolve_feed_stage_week``, the same seam the
    [[Active Feed EC Target]] uses, reused unchanged so one card never shows
    two different weeks for one tent ([[Recipe Week Resolution]]).
    """
    strategy = growspace.irrigation_strategy
    config = growspace.irrigation_config

    program_id = strategy.irrigation_program_id
    if program_id is None:
        return None
    program = coordinator.services.config.find_irrigation_program(program_id)
    if program is None:
        return None

    stage, week = resolve_feed_stage_week(plants)
    slot = resolve_program_slot(program, stage=stage, week=week)
    recipe = (
        coordinator.services.config.find_irrigation_recipe(slot.recipe_id)
        if slot is not None
        else None
    )
    live_plant_count = count_live_plants(plants)

    application: RecipeApplication | None = None
    apply_error: str | None = None
    if recipe is not None:
        try:
            application = resolve_recipe_application(
                recipe,
                strategy=strategy,
                config=config,
                live_plant_count=live_plant_count,
            )
        except RecipeApplyError as err:
            apply_error = str(err)

    progression = resolve_program_progression(
        program,
        stage=stage,
        week=week,
        slot=slot,
        slot_recipe_name=recipe.name if recipe is not None else None,
        applied_recipe_id=strategy.applied_recipe_id,
        applied_recipe_drifted=_applied_recipe_drifted(
            coordinator, growspace, live_plant_count=live_plant_count
        ),
        apply_error=apply_error,
        auto_advance=config.program_auto_advance,
    )

    return ProgramPosition(
        program=program,
        stage=stage,
        week=week,
        slot=slot,
        recipe=recipe,
        auto_advance=config.program_auto_advance,
        progression=progression,
        application=application,
    )


def _applied_recipe_drifted(
    coordinator: GrowspaceCoordinator,
    growspace: Growspace,
    *,
    live_plant_count: int,
) -> bool:
    """Return whether the growspace has been tweaked since its last stamp.

    ``False`` when there is nothing to compare against — no recipe was ever
    applied, or the applied recipe has since been deleted from the library.
    Both are *absence of evidence of a tweak*, not evidence of one, and the
    never-applied case has to read that way: a growspace bound to a program
    with auto-advance on and nothing yet stamped is exactly the case that
    should progress.
    """
    recipe_id = growspace.irrigation_strategy.applied_recipe_id
    if recipe_id is None:
        return False
    recipe = coordinator.services.config.find_irrigation_recipe(recipe_id)
    if recipe is None:
        return False
    return recipe_has_drifted(
        recipe,
        strategy=growspace.irrigation_strategy,
        config=growspace.irrigation_config,
        live_plant_count=live_plant_count,
    )


class IrrigationProgramProgression:
    """Runs the progression decision for every growspace, and acts on it.

    Held by the coordinator and driven from its refresh, plus once more the
    moment a program is assigned — because assigning while auto-advance is
    already on is that same consent expressed in advance, and waiting up to a
    refresh interval to honour it would look like the assignment was lost.

    The only state it keeps is which hold each growspace was last told about,
    so a hold that persists for weeks is announced once rather than on every
    refresh. It is deliberately in memory: re-announcing an unresolved hold
    after a restart is a far better failure than persisting a record whose only
    job is to stay quiet.
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Bind the seam to its coordinator."""
        self._coordinator = coordinator
        self._announced: dict[str, tuple[str | None, int, ProgramHold]] = {}

    async def async_evaluate_all(self) -> None:
        """Evaluate every growspace, letting no single one break the refresh.

        This runs inside the coordinator's periodic update, so a growspace with
        an impossible program must not take the whole payload down with it —
        the [[Program Hold]] promise is that the tent keeps doing what it was
        doing, and an exception escaping here would break far more than
        irrigation.
        """
        for growspace_id in self._coordinator.growspaces:
            try:
                await self.async_evaluate(growspace_id)
            except Exception:
                _LOGGER.exception(
                    "Irrigation program progression failed for growspace '%s'",
                    growspace_id,
                )

    async def async_evaluate(self, growspace_id: str) -> ProgramProgression | None:
        """Resolve one growspace's progression and carry it out.

        Returns the progression, or ``None`` when the growspace is unbound (or
        gone). The returned state is the one the rule reached *before* any
        stamp this call performed: a ``due`` answer means this call wrote the
        slot's recipe, after which the growspace is up to date.
        """
        growspace = self._coordinator.growspaces.get(growspace_id)
        if growspace is None:
            self._announced.pop(growspace_id, None)
            return None

        plants = self._coordinator.services.growspaces.get_growspace_plants(
            growspace_id
        )
        position = resolve_program_position(self._coordinator, growspace, plants)
        if position is None:
            self._announced.pop(growspace_id, None)
            return None

        progression = position.progression
        if progression.state is ProgramProgressionState.DUE:
            self._announced.pop(growspace_id, None)
            await self._async_stamp(growspace_id, position)
        elif (
            position.auto_advance
            and progression.state is ProgramProgressionState.HELD
            and progression.hold in _ANNOUNCED_HOLDS
        ):
            await self._async_announce(growspace_id, position)
        else:
            self._announced.pop(growspace_id, None)

        return progression

    async def _async_stamp(self, growspace_id: str, position: ProgramPosition) -> None:
        """Write the slot's recipe into the growspace, once, with one log line.

        The same [[Recipe Stamp]] a grower's explicit apply performs, through
        the same [[Strategy Stamp]] seam and recording the same provenance —
        the only difference is who asked. That provenance is what makes the
        stamp happen once: the next evaluation sees ``applied_recipe_id``
        already naming this slot's recipe and has nothing to do.
        """
        recipe = position.recipe
        application = position.application
        if recipe is None or application is None:  # pragma: no cover - rule invariant
            return

        await async_apply_strategy_stamp(
            self._coordinator,
            growspace_id,
            StrategyStamp(
                values=application.values,
                config_values=application.config_values,
                records={
                    "applied_recipe_id": recipe.id,
                    "recipe_applied_at": dt_util.utcnow().isoformat(),
                },
                logbook_message=(
                    f"Irrigation program '{position.program.name}' advanced to "
                    f"{position.stage} week {position.week}: applied recipe "
                    f"'{recipe.name}'"
                ),
            ),
        )
        if application.media_warning:
            _LOGGER.warning("%s", application.media_warning)
        _LOGGER.info(
            "Irrigation program '%s' advanced growspace '%s' to %s week %s "
            "(recipe '%s')",
            position.program.name,
            growspace_id,
            position.stage,
            position.week,
            recipe.name,
        )

    async def _async_announce(
        self, growspace_id: str, position: ProgramPosition
    ) -> None:
        """Tell the grower about a hold, once per distinct hold.

        Keyed by the position as well as the cause, so moving into a new week
        that holds for the same reason is a new thing to say — the grower needs
        to know the program is still stuck, and a week is a long enough silence
        that repeating it is not noise.
        """
        hold = position.progression.hold
        if hold is None:  # pragma: no cover - callers filter on hold
            return
        key = (position.stage, position.week, hold)
        if self._announced.get(growspace_id) == key:
            return
        self._announced[growspace_id] = key

        _LOGGER.info(
            "Irrigation program hold (%s) for growspace '%s': %s",
            hold.value,
            growspace_id,
            position.progression.detail,
        )
        await self._coordinator.services.notifications.manager.async_send_notification(
            growspace_id,
            "\U0001f6d1 Irrigation program on hold",
            position.progression.detail,
        )
