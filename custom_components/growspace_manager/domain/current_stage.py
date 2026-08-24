"""The read path's single answer to "what stage is this Plant in?".

[[Plant Lifecycle]] owns [[Current Stage]], but three readers used to derive it
independently — the plant view model the card renders, the plant sensor's
`stage` attribute, and nutrient-preset stage matching. All of them read the
legacy `calculate_plant_stage` date heuristic (or the `plant.stage` shadow),
which scans the legacy `*_start` fields in reverse stage order and so reports a
*stale later* stage after a Reveg: `flower_start` is still set while the
Plant is back in veg, and flower is checked first. This module routes those
readers through the lifecycle instead, so they cannot disagree with it or with
each other (#634).

Resolution rule: stored [[Stage History]] wins whenever it parses. The legacy
heuristic survives only as the fallback for Plants that store no history at all
or whose history needs repair — so a Plant whose history was already consistent
displays exactly the stage it displayed before.

The stored `plant.stage` shadow is deliberately *not* handed to the lifecycle
here as the expected current stage. That comparison raises
`CURRENT_STAGE_MISMATCH` and fails history closed to [[Unknown Stage]], which
would silently drop the read path back onto the heuristic for precisely the
Plants this seam exists to fix. Validating that agreement belongs to the
mutation path, which repairs it; the read path reports what the lifecycle knows.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING

from custom_components.growspace_manager.utils import calculate_plant_stage
from homeassistant.util import dt as dt_util

from .date_logic import calculate_days_in_stage
from .plant_lifecycle import LifecycleStage, PlantLifecycle

if TYPE_CHECKING:
    from datetime import date

    from custom_components.growspace_manager.models import Plant


def stored_lifecycle(plant: Plant, *, observed_on: date) -> PlantLifecycle | None:
    """Return the lifecycle parsed from stored Stage History, None when absent.

    Absent history is not reconstructed from legacy dates here: reconstruction
    is the mutation path's one-time migration, and on the read path an absent
    history simply means the legacy heuristic still owns the answer.
    """
    stored_history = getattr(plant, "stage_history", None)
    if not isinstance(stored_history, list) or not stored_history:
        return None

    raw_history = [
        dict(item) if isinstance(item, Mapping) else item for item in stored_history
    ]
    return PlantLifecycle.from_history(raw_history, observed_on=observed_on)


def resolve_stage_and_age(
    plant: Plant, *, observed_on: date | None = None
) -> tuple[str, int]:
    """Return the Plant's Current Stage and [[Current Stage Age]] together.

    One history parse answers both, and both fall back together: a Plant read
    from the legacy heuristic must have its age measured the legacy way too, or
    the pair would describe two different stages (#635).

    Args:
        plant: The Plant to resolve.
        observed_on: The [[Observed Date]] the history is evaluated on; defaults
            to today in the Home Assistant timezone.

    Returns:
        The canonical stage string and whole days since the current interval
        started.
    """
    on_date = observed_on if observed_on is not None else dt_util.now().date()
    lifecycle = stored_lifecycle(plant, observed_on=on_date)
    if lifecycle is not None:
        facts = lifecycle.facts(on=on_date)
        if facts.current_stage is not LifecycleStage.UNKNOWN:
            return facts.current_stage.value, facts.current_stage_age or 0
    stage = calculate_plant_stage(plant)
    return stage, calculate_days_in_stage(plant, stage)


def resolve_current_stage(plant: Plant, *, observed_on: date | None = None) -> str:
    """Return the Plant's Current Stage as the lifecycle module reports it.

    Args:
        plant: The Plant to resolve.
        observed_on: The [[Observed Date]] the history is evaluated on; defaults
            to today in the Home Assistant timezone.

    Returns:
        The canonical stage string, falling back to the legacy date heuristic
        when no trustworthy Stage History is stored.
    """
    return resolve_stage_and_age(plant, observed_on=observed_on)[0]
