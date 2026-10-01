"""Irrigation Zones: who owns which irrigation field, and the one-way migration.

ADR-0057 splits what used to be one growspace-wide irrigation loop. An
[[Irrigation Zone]] owns its cells, valves, substrate probes, emitter flow
rate, schedule, steering strategy, phase and substrate history; the growspace
keeps the supply, the drain, the tanks and feed, the lights, the caps and the
safety policies. This module is where that line is drawn, once:

- **Ownership** is read off the models rather than listed by hand.
  :class:`IrrigationConfig` is :class:`GrowspaceIrrigationConfig` plus the
  zone's fields, and :class:`IrrigationStrategy` is :class:`SteeringStrategy`
  plus :class:`LightCycle`'s, so a field added to either half lands on the
  right side without anyone editing a list here.
- **Effective views** put the halves back together as the pre-zones shapes.
  The steering computations, the gates, recipes and the wire read those
  shapes, and nothing about them changed; :func:`apply_effective_irrigation`
  splits an edited view back onto its owners.
- **The migration** turns a version 1 growspace document into version 2, by
  moving the zone-owned fields into the implicit zone ``default`` and deleting
  the growspace-level copies (ADR-0063 item 2). It is pure and idempotent: the
  store's migrate function runs it and a document that already has zones
  passes through untouched.
- **The integrity check** says what is wrong with a stored growspace's zones,
  which is what holds its irrigation under ``zone_migration_invalid``
  (ADR-0063 item 6).
"""

from __future__ import annotations

from collections import Counter
import copy
from dataclasses import fields, replace
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.models.irrigation import (
    ZONE_CONFIG_FIELDS,
    GrowspaceIrrigationConfig,
    IrrigationConfig,
    IrrigationStrategy,
    LightCycle,
    SteeringStrategy,
    SubstrateProfile,
)
from custom_components.growspace_manager.models.irrigation_zone import (
    IMPLICIT_ZONE_ID,
    IrrigationZone,
    grid_cells,
)

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import Growspace

# The latched fault, and its Repairs issue, of a growspace whose stored zones
# are not a valid version 2 shape (ADR-0063 item 6).
ZONE_MIGRATION_INVALID = "zone_migration_invalid"

_GROWSPACE_CONFIG_FIELDS: tuple[str, ...] = tuple(
    f.name for f in fields(GrowspaceIrrigationConfig)
)
_STEERING_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(SteeringStrategy))
LIGHT_CYCLE_FIELDS: tuple[str, ...] = tuple(f.name for f in fields(LightCycle))
# The substrate probes, which left EnvironmentConfig for the zone.
ZONE_ENVIRONMENT_FIELDS: tuple[str, ...] = (
    "soil_moisture_sensor",
    "pore_ec_sensors",
    "bulk_ec_sensors",
    "substrate_temperature_sensors",
)
# Older spellings of a zone probe list that EnvironmentConfig used to migrate
# on load. Version 1 documents can still hold them.
_LEGACY_ENVIRONMENT_ALIASES: dict[str, str] = {
    "substrate_ec_sensor": "bulk_ec_sensors",
    "substrate_ec_sensors": "bulk_ec_sensors",
}
# Growspace-level keys that must not exist at all in a version 2 document.
_REMOVED_GROWSPACE_KEYS: tuple[str, ...] = ("irrigation_strategy", "substrate_history")

# A field added to IrrigationConfig's zone half without a home on the zone
# would be dropped by every split; fail every import instead.
if _homeless := set(ZONE_CONFIG_FIELDS + ZONE_ENVIRONMENT_FIELDS) - {
    f.name for f in fields(IrrigationZone)
}:
    raise RuntimeError(
        f"Zone-owned fields with no IrrigationZone field: {sorted(_homeless)}"
    )


def zone_of(growspace: Growspace, zone_id: str | None = None) -> IrrigationZone:
    """Return the named zone, or the implicit one when no name is given."""
    if zone_id is None:
        return growspace.default_zone
    for zone in growspace.irrigation_zones:
        if zone.id == zone_id:
            return zone
    raise KeyError(zone_id)


def _copy_setting(value: Any) -> Any:
    """Detach mutable settings without recursing through primitive values."""
    if type(value) in (str, int, float, bool, type(None)):
        return value
    if type(value) is SubstrateProfile:
        return replace(value)
    return copy.deepcopy(value)


def effective_config(
    growspace: Growspace, zone: IrrigationZone | None = None
) -> IrrigationConfig:
    """Return the growspace's and one zone's irrigation settings as one shape.

    A detached copy: writing to it changes nothing until it is handed to
    :func:`apply_effective_irrigation`.
    """
    zone = zone or growspace.default_zone
    values = {
        name: _copy_setting(getattr(growspace.irrigation_config, name))
        for name in _GROWSPACE_CONFIG_FIELDS
    }
    values.update(
        {name: _copy_setting(getattr(zone, name)) for name in ZONE_CONFIG_FIELDS}
    )
    return IrrigationConfig(**values)


def effective_strategy(
    growspace: Growspace, zone: IrrigationZone | None = None
) -> IrrigationStrategy:
    """Return one zone's steering strategy with the growspace's lights in it.

    A detached copy, as :func:`effective_config` is.
    """
    zone = zone or growspace.default_zone
    values = {
        name: _copy_setting(getattr(zone.strategy, name)) for name in _STEERING_FIELDS
    }
    values.update(
        {name: getattr(growspace.light_cycle, name) for name in LIGHT_CYCLE_FIELDS}
    )
    return IrrigationStrategy(**values)


def apply_effective_irrigation(
    growspace: Growspace,
    config: IrrigationConfig,
    strategy: IrrigationStrategy,
    zone: IrrigationZone | None = None,
) -> None:
    """Split an edited effective view back onto the growspace and the zone."""
    zone = zone or growspace.default_zone
    growspace.irrigation_config = GrowspaceIrrigationConfig(
        **{name: getattr(config, name) for name in _GROWSPACE_CONFIG_FIELDS}
    )
    for name in ZONE_CONFIG_FIELDS:
        setattr(zone, name, getattr(config, name))
    growspace.light_cycle = LightCycle(
        **{name: getattr(strategy, name) for name in LIGHT_CYCLE_FIELDS}
    )
    zone.strategy = SteeringStrategy(
        **{name: getattr(strategy, name) for name in _STEERING_FIELDS}
    )


def effective_environment_probes(
    growspace: Growspace, zone: IrrigationZone | None = None
) -> dict[str, Any]:
    """Return one zone's substrate probes under their pre-zones environment keys."""
    zone = zone or growspace.default_zone
    return {
        name: _copy_setting(getattr(zone, name)) for name in ZONE_ENVIRONMENT_FIELDS
    }


def sync_implicit_zone_cells(growspace: Growspace) -> None:
    """Clip removed cells and inherit each new cell's adjacent boundary owner."""
    target = set(grid_cells(growspace.rows, growspace.plants_per_row))
    if len(growspace.irrigation_zones) == 1:
        zone = growspace.irrigation_zones[0]
        zone.cells = sorted(target)
        zone.probe_cells = {
            entity: cell for entity, cell in zone.probe_cells.items() if cell in target
        }
        return
    owners = {cell: zone for zone in growspace.irrigation_zones for cell in zone.cells}
    old_rows = max((cell[0] for cell in owners), default=1)
    old_cols = max((cell[1] for cell in owners), default=1)
    for zone in growspace.irrigation_zones:
        zone.cells = sorted(set(zone.cells) & target)
        zone.probe_cells = {
            entity: cell for entity, cell in zone.probe_cells.items() if cell in target
        }
    for cell in sorted(target - owners.keys()):
        adjacent = (min(cell[0], old_rows), min(cell[1], old_cols))
        owners[adjacent].cells.append(cell)


def _grid_dimension(value: Any) -> int:
    """Read a stored grid dimension as ``Growspace`` does, 3 when unreadable."""
    try:
        return int(float(value))
    except ValueError, TypeError:
        return 3


def _as_probe_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    return [value] if value else []


def migrate_growspace_document(document: dict[str, Any]) -> dict[str, Any]:
    """Return a version 1 growspace document in its version 2, zoned shape.

    Every zone-owned field moves into the implicit zone ``default``, which owns
    every cell of the grid and has no valve, and the growspace-level copy is
    deleted, so each fact keeps one source. The lights move to ``light_cycle``.
    A Subarea's substrate temperature probes move out of its environment onto
    the Subarea itself, which the subarea editor round-trips; its other
    substrate probes are dropped, because a Subarea is air with no plants to
    water and nothing ever read or edited them.

    A document that already has zones is returned as a copy, unchanged.
    """
    migrated = copy.deepcopy(document)
    if "irrigation_zones" in migrated:
        return migrated

    config = migrated.get("irrigation_config")
    if not isinstance(config, dict):
        config = {}
    environment = migrated.get("environment_config")
    if not isinstance(environment, dict):
        environment = {}
    strategy = migrated.pop("irrigation_strategy", None)
    if not isinstance(strategy, dict):
        strategy = {}
    history = migrated.pop("substrate_history", None)

    rows = _grid_dimension(migrated.get("rows", 3))
    plants_per_row = _grid_dimension(migrated.get("plants_per_row", 3))
    zone: dict[str, Any] = {
        "id": IMPLICIT_ZONE_ID,
        "name": "",
        "cells": [list(cell) for cell in grid_cells(rows, plants_per_row)],
        "valves": [],
    }
    for name in ZONE_CONFIG_FIELDS:
        if name in config:
            zone[name] = config.pop(name)
    for name in ZONE_ENVIRONMENT_FIELDS:
        if name in environment:
            zone[name] = environment.pop(name)
    for legacy, name in _LEGACY_ENVIRONMENT_ALIASES.items():
        if legacy in environment:
            value = environment.pop(legacy)
            zone.setdefault(name, _as_probe_list(value))
    zone["strategy"] = {
        name: value
        for name, value in strategy.items()
        if name not in LIGHT_CYCLE_FIELDS
    }
    zone["substrate_history"] = history if isinstance(history, dict) else {}

    migrated["light_cycle"] = {
        name: strategy[name] for name in LIGHT_CYCLE_FIELDS if name in strategy
    }
    migrated["irrigation_zones"] = [zone]

    for subarea in migrated.get("subareas") or []:
        subarea_environment = (
            subarea.get("environment_config") if isinstance(subarea, dict) else None
        )
        if isinstance(subarea_environment, dict):
            temperature = subarea_environment.pop("substrate_temperature_sensors", None)
            subarea.setdefault(
                "substrate_temperature_sensors", _as_probe_list(temperature)
            )
            for name in (*ZONE_ENVIRONMENT_FIELDS, *_LEGACY_ENVIRONMENT_ALIASES):
                subarea_environment.pop(name, None)
    return migrated


def zone_integrity_problems(document: dict[str, Any]) -> list[str]:
    """Say what is wrong with one stored growspace's zones; empty when nothing.

    A growspace passes when it has zones, one of them the implicit
    ``default``, with unique ids; when every cell of its grid belongs to
    exactly one zone and no zone claims a cell outside it; and when no
    zone-owned field is left at the growspace level (ADR-0063 item 6).
    """
    zones = document.get("irrigation_zones")
    if not isinstance(zones, list) or not zones:
        return ["it has no irrigation zone"]
    problems: list[str] = []
    if not all(isinstance(zone, dict) for zone in zones):
        return ["a stored irrigation zone is not an object"]

    if not all(isinstance(zone.get("id"), str) for zone in zones):
        problems.append("a stored irrigation zone has an invalid id")
    ids = Counter(zone["id"] for zone in zones if isinstance(zone.get("id"), str))
    if IMPLICIT_ZONE_ID not in ids:
        problems.append(f"it has no implicit zone '{IMPLICIT_ZONE_ID}'")
    problems.extend(
        f"zone id '{zone_id}' is used {count} times"
        for zone_id, count in sorted(ids.items(), key=lambda item: str(item[0]))
        if count > 1
    )

    grid = set(
        grid_cells(
            _grid_dimension(document.get("rows", 3)),
            _grid_dimension(document.get("plants_per_row", 3)),
        )
    )
    owners: Counter[tuple[int, int]] = Counter()
    for zone in zones:
        cells = zone.get("cells")
        if not isinstance(cells, list):
            problems.append(f"zone '{zone.get('id')}' has an unreadable cell list")
            continue
        for cell in cells:
            try:
                row, col = cell
                owners[int(row), int(col)] += 1
            except TypeError, ValueError:
                problems.append(f"zone '{zone.get('id')}' has an unreadable cell")
    if missing := sorted(grid - set(owners)):
        problems.append(f"{len(missing)} cell(s) belong to no zone, first {missing[0]}")
    if shared := sorted(cell for cell, count in owners.items() if count > 1):
        problems.append(
            f"{len(shared)} cell(s) belong to more than one zone, first {shared[0]}"
        )
    if outside := sorted(set(owners) - grid):
        problems.append(
            f"{len(outside)} zone cell(s) lie outside the grid, first {outside[0]}"
        )

    config = document.get("irrigation_config")
    environment = document.get("environment_config")
    left_behind = sorted(
        [key for key in _REMOVED_GROWSPACE_KEYS if key in document]
        + [
            f"irrigation_config.{name}"
            for name in ZONE_CONFIG_FIELDS
            if isinstance(config, dict) and name in config
        ]
        + [
            f"environment_config.{name}"
            for name in (*ZONE_ENVIRONMENT_FIELDS, *_LEGACY_ENVIRONMENT_ALIASES)
            if isinstance(environment, dict) and name in environment
        ]
    )
    if left_behind:
        problems.append(
            "zone-owned settings are still stored on the growspace: "
            + ", ".join(left_behind)
        )
    return problems
