"""Plant read adapter for [[Lifetime Stage Days]]."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from typing import TYPE_CHECKING

from .plant_lifecycle import KNOWN_STAGES, LifetimeStageDays, PlantLifecycle

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant


def resolve_lifetime_stage_days(
    plant: Plant, *, observed_on: date
) -> LifetimeStageDays:
    """Return cumulative stage days from one Plant Lifecycle facts snapshot.

    A stored Stage History is authoritative. Older Plants whose history is absent
    are reconstructed from their legacy lifecycle dates by ``PlantLifecycle``;
    malformed present history stays fail-closed and therefore reports zeroes.
    """
    stored_history = getattr(plant, "stage_history", None)
    raw_history: list[object] | None = (
        [dict(item) if isinstance(item, Mapping) else item for item in stored_history]
        if isinstance(stored_history, list) and stored_history
        else None
    )
    legacy_dates = {
        f"{stage.value}_start": getattr(plant, f"{stage.value}_start", None)
        for stage in KNOWN_STAGES
    }
    lifecycle = PlantLifecycle.from_data(
        raw_history,
        observed_on=observed_on,
        legacy_dates=legacy_dates,
    )
    return lifecycle.facts(on=observed_on).lifetime_stage_days
