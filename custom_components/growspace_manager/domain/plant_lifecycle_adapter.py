"""Convert a stored Plant into the lifecycle domain's untrusted input."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING

from .plant_lifecycle import KNOWN_STAGES, LifecycleStage, PlantLifecycle

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant


def plant_lifecycle_from_plant(
    plant: Plant,
    *,
    observed_on: date,
    current_stage: LifecycleStage | None = None,
) -> PlantLifecycle:
    """Parse stored history, preserving malformed items for repair warnings."""
    stored_history = getattr(plant, "stage_history", None)
    raw_history: list[object] | None = (
        [dict(item) if isinstance(item, Mapping) else item for item in stored_history]
        if isinstance(stored_history, list) and stored_history
        else None
    )
    legacy_dates = {
        f"{stage.value}_start": (
            value
            if isinstance(
                value := getattr(plant, f"{stage.value}_start", None),
                (date, datetime, str),
            )
            else None
        )
        for stage in KNOWN_STAGES
    }
    if raw_history is None and not any(legacy_dates.values()):
        bootstrap_stage = current_stage or next(
            (
                stage
                for stage in KNOWN_STAGES
                if stage.value == getattr(plant, "stage", None)
            ),
            None,
        )
        if bootstrap_stage is not None:
            created_at = getattr(plant, "created_at", None)
            started_on = (
                created_at
                if isinstance(created_at, (date, datetime, str)) and created_at
                else observed_on
            )
            raw_history = [
                {"stage": bootstrap_stage.value, "start": started_on, "end": None}
            ]
    return PlantLifecycle.from_data(
        raw_history,
        observed_on=observed_on,
        legacy_dates=legacy_dates,
        current_stage=current_stage,
    )
