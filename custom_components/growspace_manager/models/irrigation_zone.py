"""The Irrigation Zone: one steered cohort within a growspace (ADR-0057)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .base import BaseModel, _sanitize_numeric_fields
from .irrigation import SteeringStrategy, SubstrateHistory, normalize_schedule_items
from .types import IrrigationScheduleItem

__all__ = ["IMPLICIT_ZONE_ID", "IrrigationZone", "grid_cells"]

# The implicit zone every growspace starts with. Fixed rather than random, so
# the migration is idempotent and today's per-growspace entities keep their
# unique_ids as this zone's (ADR-0057 item 3).
IMPLICIT_ZONE_ID = "default"


def grid_cells(rows: int, plants_per_row: int) -> list[tuple[int, int]]:
    """Return every ``(row, col)`` cell of a grid, 1-based as plants are.

    Tolerates the numeric strings old stores held for either dimension, as the
    grid builder does.
    """
    return [
        (row, col)
        for row in range(1, max(int(rows), 0) + 1)
        for col in range(1, max(int(plants_per_row), 0) + 1)
    ]


@dataclass(slots=True)
class IrrigationZone(BaseModel):
    """The grid cells one valve set waters together and one loop steers.

    A zone owns its cells — and so the plants standing in them — its valves,
    its substrate probes, the flow rate through its emitters, its schedule,
    its steering strategy with its own phase, and its substrate history. The
    growspace keeps what the zones share: the pump, the drain, the tanks and
    feed, the lights, the daily caps and the safety policies.

    Nothing reads a zone's fields as the pre-zones shapes directly; the
    steering code and the wire read :func:`effective_config` and
    :func:`effective_strategy` in ``domain.irrigation_zone``, which put the
    growspace's half back in.
    """

    id: str
    name: str = ""
    # Every (row, col) this zone waters. Every cell of the grid belongs to
    # exactly one zone.
    cells: list[tuple[int, int]] = field(default_factory=list)
    # Valve outputs opened to water this zone. Empty for a lone implicit zone,
    # which the pump waters directly.
    valves: list[str] = field(default_factory=list)

    # Substrate probes.
    soil_moisture_sensor: str | None = None
    moisture_witness_sensors: list[str] = field(default_factory=list)
    pore_ec_sensors: list[str] = field(default_factory=list)
    bulk_ec_sensors: list[str] = field(default_factory=list)
    substrate_temperature_sensors: list[str] = field(default_factory=list)
    # Quantity comes from the probe's owning list. These maps only carry its
    # placement and role; they never duplicate the entity inventory.
    probe_cells: dict[str, tuple[int, int]] = field(default_factory=dict)
    probe_roles: dict[str, str] = field(default_factory=dict)
    probe_names: dict[str, str] = field(default_factory=dict)

    # What the pump delivers into this zone's emitters.
    pump_flow_rate_ml_per_sec: float = 0.0

    # Schedule and trigger.
    irrigation_times: list[IrrigationScheduleItem] = field(default_factory=list)
    irrigation_duration: int | None = None
    soil_trigger_percent: float | None = None
    min_interval_minutes: int = 5

    degraded_fallback: str = "hold"

    # Steering.
    strategy: SteeringStrategy = field(default_factory=SteeringStrategy)
    active_steering_phase: str = "p2"
    phase_changed_at: str | None = None
    substrate_history: SubstrateHistory = field(default_factory=SubstrateHistory)

    @classmethod
    def implicit(cls, rows: int, plants_per_row: int, **fields: Any) -> IrrigationZone:
        """Return the implicit zone owning every cell of a grid."""
        return cls(
            id=IMPLICIT_ZONE_ID, cells=grid_cells(rows, plants_per_row), **fields
        )

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Coerce null lists and legacy schedule items before deserializing."""
        data = _sanitize_numeric_fields(cls, data)
        for key in (
            "cells",
            "valves",
            "pore_ec_sensors",
            "moisture_witness_sensors",
            "bulk_ec_sensors",
            "substrate_temperature_sensors",
            "irrigation_times",
        ):
            if key in data and data[key] is None:
                data[key] = []
        if isinstance(data.get("irrigation_times"), list):
            data["irrigation_times"] = normalize_schedule_items(
                data["irrigation_times"]
            )
        for key in (
            "strategy",
            "substrate_history",
            "probe_cells",
            "probe_roles",
            "probe_names",
        ):
            if data.get(key) is None:
                data[key] = {}
        return data
