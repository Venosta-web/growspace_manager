"""Irrigation Recipe — a grower-authored, reusable irrigation snapshot.

One growspace's irrigation settings, saved into a global library and
applicable to any other growspace (CONTEXT.md "Irrigation Recipe", ADR-0045).

A recipe carries exactly **one** ``kind``. A grower runs crop steering or a
time schedule, never both, so a recipe holding both halves would always carry
one half of noise; the unused half is ``None`` and the payload shapes are
disjoint dataclasses rather than one wide struct.

What a recipe deliberately does **not** hold is as load-bearing as what it
does. The pump and drain-pump entity IDs, the tank entities, the active
steering phase and its change timestamp, and the detected lights-on time are
the *target* growspace's own hardware and live state — copying them across is
not portability but corruption. ``ec_target_ranges`` is feed EC, which must
never be conflated with the [[Pore EC Target Band]] the crop-steering half
does carry. ``enabled`` and ``declared_steering_mode`` are excluded too: the
first would let a recipe switch a subsystem on, and the second is the
provenance of a *different* source (ADR-0012's preset stamp), which applying a
recipe would otherwise silently overwrite.

Shot sizes are held as a percent of substrate volume and never as pump
seconds — see [[Substrate-Relative Shot Storage]] and
``domain/irrigation_recipe.py``, which owns the capture rules.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from custom_components.growspace_manager.const import (
    IrrigationRecipeKind,
    SubstrateMediaType,
)
import homeassistant.util.dt as dt_util

from .base import BaseModel
from .types import IrrigationScheduleItem

__all__ = [
    "AppliedRecipe",
    "CropSteeringRecipe",
    "IrrigationRecipe",
    "RecipeProvenance",
    "ScheduleRecipe",
]


@dataclass(slots=True)
class RecipeProvenance(BaseModel):
    """Where an [[Irrigation Recipe]] came from — descriptive, never authority.

    The authoring growspace's media, per-pot substrate volume and pump flow
    rate, plus the stage and week it was saved in. Provenance drives the
    card's media-mismatch warning and sorts the picker; it never gates an
    apply and never decides *when* a recipe runs (CONTEXT.md
    "[[Recipe Provenance]]").

    ``stage`` is ``None`` and ``week`` is ``0`` when the growspace held no live
    plants at save time — the same "no live cohort" answer
    ``resolve_feed_stage_week`` gives.
    """

    media_type: SubstrateMediaType = SubstrateMediaType.COCO
    liters_per_pot: float = 0.0
    pump_flow_rate_ml_per_sec: float = 0.0
    stage: str | None = None
    week: int = 0
    lights_on_time: str | None = None
    auto_light_tracking: bool | None = None
    drain_times: list[IrrigationScheduleItem] | None = None
    drain_duration: int | None = None
    daily_volume_cap_liters: float | None = None
    max_cycles_per_day: int | None = None
    skip_during_dark: bool | None = None


@dataclass(slots=True)
class CropSteeringRecipe(BaseModel):
    """The crop-steering half: the portable [[IrrigationStrategy]] setpoints.

    Field-for-field the strategy's grower-owned setpoints, except that the two
    shot sizes are percents of substrate volume rather than pump seconds, so
    the values survive a move to plumbing with a different flow rate.
    """

    p0_duration_minutes: int = 60
    p2_stop_before_lights_off_minutes: int = 120
    target_vwc_percent: float = 55.0
    maintenance_dryback_percent: float = 2.0
    p1_shot_volume_percent: float = 4.0
    p1_shot_interval_minutes: int = 15
    p2_shot_volume_percent: float = 4.0
    p2_shot_interval_minutes: int = 15
    dynamic_shot_enabled: bool = True
    dynamic_aggressiveness: float = 1.0
    dynamic_recovery: float = 0.1
    dynamic_shot_size_floor: float = 0.5
    dynamic_interval_ceiling: float = 1.5
    pore_ec_target_min: float | None = None
    pore_ec_target_max: float | None = None
    ec_modulation_enabled: bool = False


@dataclass(slots=True)
class ScheduleRecipe(BaseModel):
    """The time-schedule half: when the pumps fire and how much they may move.

    The zone schedule and duration. Shared drains, caps and dark gating are
    captured in RecipeProvenance and never written by a zone stamp.
    """

    irrigation_times: list[IrrigationScheduleItem] = field(default_factory=list)
    irrigation_duration: int | None = None


@dataclass(slots=True, kw_only=True)
class IrrigationRecipe(BaseModel):
    """One saved recipe in the global library.

    Exactly one of ``crop_steering`` / ``schedule`` is populated, matching
    ``kind``; the library refuses to store any other combination.
    """

    id: str
    name: str
    revision: int = 1
    kind: IrrigationRecipeKind
    provenance: RecipeProvenance = field(default_factory=RecipeProvenance)
    crop_steering: CropSteeringRecipe | None = None
    schedule: ScheduleRecipe | None = None
    created_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Move legacy growspace-owned values into descriptive provenance."""
        data = copy.deepcopy(data)
        provenance = data.setdefault("provenance", {})
        for label, names in (
            ("crop_steering", ("lights_on_time", "auto_light_tracking")),
            (
                "schedule",
                (
                    "drain_times",
                    "drain_duration",
                    "daily_volume_cap_liters",
                    "max_cycles_per_day",
                    "skip_during_dark",
                ),
            ),
        ):
            half = data.get(label) or {}
            for name in names:
                if name in half:
                    provenance[name] = half.pop(name)
        return data


@dataclass(slots=True)
class AppliedRecipe(BaseModel):
    """The zone-owned recipe values that a stamp actually applied (ADR-0065)."""

    id: str
    revision: int
    values: dict[str, Any]

    @classmethod
    def from_recipe(cls, recipe: IrrigationRecipe) -> AppliedRecipe:
        """Keep a detached copy in the recipe's portable units."""
        half = (
            recipe.crop_steering
            if recipe.crop_steering is not None
            else recipe.schedule
        )
        assert half is not None
        return cls(recipe.id, recipe.revision, copy.deepcopy(half.to_dict()))

    def as_recipe(self) -> IrrigationRecipe:
        """Reconstitute the stored half for the shared stamp resolver."""
        schedule = "irrigation_times" in self.values
        return IrrigationRecipe(
            id=self.id,
            name=self.id,
            revision=self.revision,
            kind=IrrigationRecipeKind.SCHEDULE
            if schedule
            else IrrigationRecipeKind.CROP_STEERING,
            schedule=ScheduleRecipe.from_dict(self.values) if schedule else None,
            crop_steering=None
            if schedule
            else CropSteeringRecipe.from_dict(self.values),
        )
