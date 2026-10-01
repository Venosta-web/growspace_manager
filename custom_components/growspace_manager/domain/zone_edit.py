"""Pure Irrigation Zone edits, membership and the supported scale envelope."""

from __future__ import annotations

from collections import Counter
import copy
from typing import Any

from custom_components.growspace_manager.exceptions import (
    EntityNotFoundError,
    EnvelopeExceededError,
    ValidationChangeError,
    ZoneRequiredError,
)
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.models.irrigation_zone import (
    IrrigationZone,
    grid_cells,
)

from .flow_meter import FlowMeterError, validate_meter_placements

MAX_ZONES_PER_GROWSPACE = 6
MAX_PROBES_PER_QUANTITY = 4
MAX_VALVES_PER_ZONE = 8

PROBE_FIELDS = {
    "moisture": "moisture_witness_sensors",
    "pore_ec": "pore_ec_sensors",
    "bulk_ec": "bulk_ec_sensors",
    "temperature": "substrate_temperature_sensors",
}


def resolve_zone(growspace: Growspace, zone_id: str | None = None) -> IrrigationZone:
    """Resolve an explicit zone, retaining the single-zone legacy signature."""
    if zone_id is None:
        if len(growspace.irrigation_zones) != 1:
            raise ZoneRequiredError(
                "zone_id is required when a growspace has multiple zones"
            )
        return growspace.irrigation_zones[0]
    for zone in growspace.irrigation_zones:
        if zone.id == zone_id:
            return zone
    raise EntityNotFoundError(f"Irrigation zone {zone_id} not found")


def probe_documents(zone: IrrigationZone) -> list[dict[str, Any]]:
    """Describe the inventory without storing a second copy of probe identities."""
    result = []
    for quantity, field in PROBE_FIELDS.items():
        entities = list(getattr(zone, field))
        if quantity == "moisture" and zone.soil_moisture_sensor:
            entities.insert(0, zone.soil_moisture_sensor)
        for index, entity_id in enumerate(entities):
            result.append(
                {
                    "entity_id": entity_id,
                    "quantity": quantity,
                    "role": zone.probe_roles.get(
                        entity_id, "control" if index == 0 else "witness"
                    ),
                    "cell": zone.probe_cells.get(entity_id),
                    "name": zone.probe_names.get(entity_id),
                }
            )
    return result


def set_probes(zone: IrrigationZone, probes: list[dict[str, Any]]) -> None:
    """Replace one zone's probe inventory, validating before mutation."""
    counts = Counter(probe["quantity"] for probe in probes)
    for quantity, count in counts.items():
        if quantity not in PROBE_FIELDS:
            raise ValidationChangeError(f"Unknown substrate quantity {quantity}")
        if count > MAX_PROBES_PER_QUANTITY:
            raise EnvelopeExceededError(
                f"probes_per_quantity ({quantity})", MAX_PROBES_PER_QUANTITY
            )
    entities = [probe["entity_id"] for probe in probes]
    if len(set(entities)) != len(entities):
        raise ValidationChangeError("A probe is assigned more than once")
    for quantity in counts:
        selected = [p for p in probes if p["quantity"] == quantity]
        if sum(p["role"] == "control" for p in selected) != 1:
            raise ValidationChangeError(f"{quantity} needs exactly one control probe")
    if any(p["role"] not in {"control", "witness"} for p in probes):
        raise ValidationChangeError("Probe role must be control or witness")
    zone.soil_moisture_sensor = None
    zone.probe_cells = {}
    zone.probe_roles = {}
    zone.probe_names = {}
    for field in PROBE_FIELDS.values():
        setattr(zone, field, [])
    for probe in probes:
        entity = probe["entity_id"]
        if probe["quantity"] == "moisture" and probe["role"] == "control":
            zone.soil_moisture_sensor = entity
        else:
            getattr(zone, PROBE_FIELDS[probe["quantity"]]).append(entity)
        zone.probe_roles[entity] = probe["role"]
        if probe.get("name") is not None:
            zone.probe_names[entity] = probe["name"]
        if probe.get("cell") is not None:
            zone.probe_cells[entity] = tuple(probe["cell"])


def validate_zones(growspace: Growspace) -> None:
    """Refuse edits outside the envelope or violating exclusive ownership."""
    zones = growspace.irrigation_zones
    try:
        validate_meter_placements(
            growspace.environment_config.flow_meters, {z.id for z in zones}
        )
    except FlowMeterError as err:
        raise ValidationChangeError(str(err)) from err
    if len(zones) > MAX_ZONES_PER_GROWSPACE:
        raise EnvelopeExceededError("zones_per_growspace", MAX_ZONES_PER_GROWSPACE)
    if not zones or sum(zone.id == "default" for zone in zones) != 1:
        raise ValidationChangeError("The implicit default zone must remain")
    if len({zone.id for zone in zones}) != len(zones):
        raise ValidationChangeError("Zone IDs must be unique")
    expected = set(grid_cells(growspace.rows, growspace.plants_per_row))
    cells = [cell for zone in zones for cell in zone.cells]
    if set(cells) != expected or len(cells) != len(expected):
        raise ValidationChangeError("Every grid cell must belong to exactly one zone")
    valves = []
    for zone in zones:
        if len(zone.valves) > MAX_VALVES_PER_ZONE:
            raise EnvelopeExceededError("valves_per_zone", MAX_VALVES_PER_ZONE)
        if len(zones) > 1 and not zone.valves:
            raise ValidationChangeError(
                "Every zone must own a valve when there are multiple zones"
            )
        valves.extend(zone.valves)
        documents = probe_documents(zone)
        if len({p["entity_id"] for p in documents}) != len(documents):
            raise ValidationChangeError("A probe is assigned more than once")
        counts = Counter(p["quantity"] for p in documents)
        for quantity, count in counts.items():
            if count > MAX_PROBES_PER_QUANTITY:
                raise EnvelopeExceededError(
                    f"probes_per_quantity ({quantity})", MAX_PROBES_PER_QUANTITY
                )
        if any(
            p["cell"] is not None and p["cell"] not in zone.cells for p in documents
        ):
            raise ValidationChangeError("A probe's cell must belong to its zone")
    if len(set(valves)) != len(valves):
        raise ValidationChangeError("Each valve must belong to exactly one zone")
    supply = growspace.irrigation_config.irrigation_pump_entity
    drain = growspace.irrigation_config.drain_pump_entity
    if supply in valves or drain in valves:
        raise ValidationChangeError(
            "A supply or drain output cannot also be a zone valve"
        )


def edited_zones(
    growspace: Growspace, operation: str, values: dict[str, Any]
) -> Growspace:
    """Return a detached, valid candidate for one revision-guarded edit."""
    candidate = copy.deepcopy(growspace)
    if operation == "add":
        if len(candidate.irrigation_zones) >= MAX_ZONES_PER_GROWSPACE:
            raise EnvelopeExceededError("zones_per_growspace", MAX_ZONES_PER_GROWSPACE)
        zone = IrrigationZone(id=values["zone_id"], name=values["name"])
        if "default_valves" in values:
            candidate.default_zone.valves = list(values["default_valves"])
        if not candidate.default_zone.name:
            candidate.default_zone.name = "Zone 1"
        candidate.irrigation_zones.append(zone)
    elif operation == "reorder":
        order = values["zone_ids"]
        if len(order) != len(set(order)) or set(order) != {
            z.id for z in candidate.irrigation_zones
        }:
            raise ValidationChangeError("Zone order must name every zone exactly once")
        by_id = {z.id: z for z in candidate.irrigation_zones}
        candidate.irrigation_zones = [by_id[zone_id] for zone_id in order]
        validate_zones(candidate)
        return candidate
    else:
        zone = resolve_zone(candidate, values["zone_id"])
        if operation == "remove":
            if zone.id == "default":
                raise ValidationChangeError("The implicit zone cannot be removed")
            candidate.irrigation_zones.remove(zone)
            candidate.default_zone.cells = sorted(
                candidate.default_zone.cells + zone.cells
            )
            validate_zones(candidate)
            return candidate
        if operation not in {"update", "assign"}:
            raise ValidationChangeError(f"Unknown zone edit {operation}")
    if "name" in values:
        if not values["name"].strip():
            raise ValidationChangeError("Zone name cannot be blank")
        zone.name = values["name"].strip()
    if "degraded_fallback" in values:
        if values["degraded_fallback"] not in {"hold", "replay"}:
            raise ValidationChangeError("degraded_fallback must be hold or replay")
        zone.degraded_fallback = values["degraded_fallback"]
    if "valves" in values:
        zone.valves = list(values["valves"])
    if "cells" in values:
        wanted = [tuple(cell) for cell in values["cells"]]
        # Cells released by this edit go to default; cells claimed by it are
        # taken from their former owner in the same transaction.
        released = set(zone.cells) - set(wanted)
        if zone.id != "default":
            candidate.default_zone.cells = sorted(
                set(candidate.default_zone.cells) | released
            )
        elif released:
            raise ValidationChangeError(
                "Assign default cells away by editing their destination zone"
            )
        for other in candidate.irrigation_zones:
            if other.id != zone.id:
                other.cells = [cell for cell in other.cells if cell not in wanted]
        zone.cells = wanted
    if "probes" in values:
        set_probes(zone, values["probes"])
    validate_zones(candidate)
    return candidate
