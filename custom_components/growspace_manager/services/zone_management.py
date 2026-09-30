"""Revision-guarded zone commits shared by services and WebSocket commands."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from custom_components.growspace_manager.const import GrowspaceService
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.zone_edit import (
    edited_zones,
    probe_documents,
)
from custom_components.growspace_manager.events import (
    async_fire_plant_layout_changed_event,
)
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    LayoutConflictError,
    ValidationChangeError,
)
from custom_components.growspace_manager.schemas import ZONE_EDIT_SCHEMAS
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse

from ._definition import ServiceDefinition


async def async_edit_zones(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    expected_layout_revision: int,
    operation: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Validate, persist and publish once, rolling back an unsuccessful save."""
    async with coordinator.lock:
        growspace = coordinator.growspaces.get(growspace_id)
        if growspace is None:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
        if growspace.layout_revision != expected_layout_revision:
            raise LayoutConflictError(
                f"Expected layout revision {expected_layout_revision}, current {growspace.layout_revision}"
            )
        manager = getattr(coordinator, "_subsystem_manager", None)
        controller = (
            manager.irrigation_coordinators.get(growspace_id) if manager else None
        )
        if controller is not None and controller.active_events:
            raise ValidationChangeError(
                "Wait for the active pump cycle before editing zones"
            )
        if operation == "add":
            values = {**values, "zone_id": uuid4().hex[:8]}
        candidate = edited_zones(growspace, operation, values)
        owned_valves = {
            valve for zone in candidate.irrigation_zones for valve in zone.valves
        }
        for other_id, other in coordinator.growspaces.items():
            if other_id != growspace_id and any(
                valve in owned_valves
                for zone in other.irrigation_zones
                for valve in zone.valves
            ):
                raise ValidationChangeError(
                    "Each valve must belong to exactly one zone"
                )
        previous = growspace.irrigation_zones
        if candidate.irrigation_zones != previous:
            growspace.irrigation_zones = candidate.irrigation_zones
            growspace.layout_revision += 1
            coordinator.cache.invalidate(growspace_id)
            try:
                await coordinator.async_commit()
            except Exception:
                growspace.irrigation_zones = previous
                growspace.layout_revision = expected_layout_revision
                coordinator.cache.invalidate(growspace_id)
                raise
            async_fire_plant_layout_changed_event(
                coordinator.hass, growspace_id, growspace.layout_revision
            )
        result = {
            "growspace_id": growspace_id,
            "layout_revision": growspace.layout_revision,
            "zones": [
                {
                    "id": zone.id,
                    "name": zone.name if len(growspace.irrigation_zones) > 1 else "",
                    "order": index,
                    "cells": [list(cell) for cell in zone.cells],
                    "valves": zone.valves,
                    "probes": probe_documents(zone),
                }
                for index, zone in enumerate(growspace.irrigation_zones)
            ],
        }
    await coordinator.async_request_refresh()
    return result


async def handle_edit_zone(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, call: ServiceCall
) -> dict[str, Any]:
    """Adapt HA actions to the same zone commit as the WebSocket surface."""
    values = dict(call.data)
    growspace_id = values.pop("growspace_id")
    revision = values.pop("expected_layout_revision")
    operation = call.service.removesuffix("_irrigation_zone").removesuffix(
        "_irrigation_zones"
    )
    return await async_edit_zones(
        coordinator, growspace_id, revision, operation, values
    )


SERVICES = tuple(
    ServiceDefinition(
        GrowspaceService(name),
        handle_edit_zone,
        schema,
        supports_response=SupportsResponse.OPTIONAL,
    )
    for name, schema in ZONE_EDIT_SCHEMAS.items()
)
