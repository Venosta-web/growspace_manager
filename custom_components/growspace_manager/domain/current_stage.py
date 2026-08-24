"""The read path's single answer to "what stage is this Plant in?".

[[Plant Lifecycle]] owns [[Current Stage]] and [[Current Stage Age]]. Stored
[[Stage History]] is authoritative; older Plants without history are
reconstructed by that module from the legacy lifecycle dates. Malformed present
history fails closed to [[Unknown Stage]] instead of activating a second stage
calculator.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date, datetime
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

from .plant_lifecycle import KNOWN_STAGES, PlantLifecycle

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Plant


def plant_lifecycle(plant: Plant, *, observed_on: date) -> PlantLifecycle:
    """Return the lifecycle parsed from history or reconstructed legacy dates."""
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
        try:
            explicit_stage = next(
                stage
                for stage in KNOWN_STAGES
                if stage.value == getattr(plant, "stage", None)
            )
        except StopIteration:
            pass
        else:
            created_at = getattr(plant, "created_at", None)
            started_on = (
                created_at
                if isinstance(created_at, (date, datetime, str)) and created_at
                else observed_on
            )
            raw_history = [
                {
                    "stage": explicit_stage.value,
                    "start": started_on,
                    "end": None,
                }
            ]
    return PlantLifecycle.from_data(
        raw_history,
        observed_on=observed_on,
        legacy_dates=legacy_dates,
    )


def resolve_stage_and_age(
    plant: Plant, *, observed_on: date | None = None
) -> tuple[str, int]:
    """Return the Plant's Current Stage and [[Current Stage Age]] together.

    One lifecycle parse answers both so the pair can never describe different
    stages (#635).

    Args:
        plant: The Plant to resolve.
        observed_on: The [[Observed Date]] the history is evaluated on; defaults
            to today in the Home Assistant timezone.

    Returns:
        The canonical stage string and whole days since the current interval
        started.
    """
    on_date = observed_on if observed_on is not None else dt_util.now().date()
    facts = plant_lifecycle(plant, observed_on=on_date).facts(on=on_date)
    return facts.current_stage.value, facts.current_stage_age or 0


def resolve_current_stage(plant: Plant, *, observed_on: date | None = None) -> str:
    """Return the Plant's Current Stage as the lifecycle module reports it.

    Args:
        plant: The Plant to resolve.
        observed_on: The [[Observed Date]] the history is evaluated on; defaults
            to today in the Home Assistant timezone.

    Returns:
        The canonical stage string, or ``unknown`` when lifecycle data is not
        trustworthy.
    """
    return resolve_stage_and_age(plant, observed_on=observed_on)[0]
