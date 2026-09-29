"""Plant read adapter for [[Lifetime Stage Days]]."""

from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING

from .plant_lifecycle import LifetimeStageDays
from .plant_lifecycle_adapter import plant_lifecycle_from_plant

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
    lifecycle = plant_lifecycle_from_plant(plant, observed_on=observed_on)
    return lifecycle.facts(on=observed_on).lifetime_stage_days
