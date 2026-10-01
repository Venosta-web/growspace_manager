"""Zone membership, ownership and explicit command scope (issue #892)."""

from __future__ import annotations

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.growspace_manager.domain.irrigation_zone import (
    sync_implicit_zone_cells,
)
from custom_components.growspace_manager.domain.zone_edit import (
    MAX_PROBES_PER_QUANTITY,
    MAX_VALVES_PER_ZONE,
    MAX_ZONES_PER_GROWSPACE,
    edited_zones,
    probe_documents,
    resolve_zone,
    set_probes,
    validate_zones,
)
from custom_components.growspace_manager.exceptions import (
    EntityNotFoundError,
    EnvelopeExceededError,
    LayoutConflictError,
    ValidationChangeError,
    ZoneRequiredError,
)
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.models.irrigation_zone import IrrigationZone
from custom_components.growspace_manager.services.irrigation_change import (
    IrrigationChange,
    IrrigationChangeOperation,
    async_apply_irrigation_change,
)
from custom_components.growspace_manager.services.zone_management import (
    async_edit_zones,
)


@pytest.fixture
def growspace():
    return Growspace(id="tent", name="Tent", rows=2, plants_per_row=2)


def split(growspace):
    return edited_zones(
        growspace,
        "add",
        {
            "zone_id": "second",
            "name": "Blue",
            "cells": [[1, 2], [2, 2]],
            "valves": ["switch.blue"],
            "default_valves": ["switch.red"],
        },
    )


def test_split_transfers_cells_and_reveals_default(growspace):
    candidate = split(growspace)
    assert growspace.default_zone.name == ""
    assert candidate.default_zone.name == "Zone 1"
    assert candidate.default_zone.cells == [(1, 1), (2, 1)]
    assert resolve_zone(candidate, "second").cells == [(1, 2), (2, 2)]
    assert resolve_zone(growspace) is growspace.default_zone
    with pytest.raises(ZoneRequiredError):
        resolve_zone(candidate)
    with pytest.raises(EntityNotFoundError):
        resolve_zone(candidate, "absent")


def test_rename_reorder_assign_remove(growspace):
    candidate = split(growspace)
    candidate = edited_zones(
        candidate, "update", {"zone_id": "second", "name": "Indigo"}
    )
    candidate = edited_zones(candidate, "reorder", {"zone_ids": ["second", "default"]})
    assert [zone.name for zone in candidate.irrigation_zones] == ["Indigo", "Zone 1"]
    candidate = edited_zones(
        candidate, "assign", {"zone_id": "second", "cells": [[1, 2]]}
    )
    assert (2, 2) in candidate.default_zone.cells
    candidate = edited_zones(candidate, "remove", {"zone_id": "second"})
    assert len(candidate.irrigation_zones) == 1
    assert len(candidate.default_zone.cells) == 4


@pytest.mark.parametrize(
    ("operation", "values"),
    [
        ("remove", {"zone_id": "default"}),
        ("update", {"zone_id": "second", "name": "  "}),
        ("update", {"zone_id": "second", "valves": []}),
        ("update", {"zone_id": "second", "valves": ["switch.red"]}),
        ("assign", {"zone_id": "second", "cells": [[3, 1]]}),
        ("assign", {"zone_id": "second", "cells": [[1, 1], [1, 1]]}),
        ("assign", {"zone_id": "default", "cells": [[1, 1]]}),
        ("reorder", {"zone_ids": ["default", "default"]}),
        ("unknown", {"zone_id": "second"}),
    ],
)
def test_refused_edit_leaves_input_unchanged(growspace, operation, values):
    growspace = split(growspace)
    before = copy.deepcopy(growspace)
    with pytest.raises(ValidationChangeError):
        edited_zones(growspace, operation, values)
    assert growspace == before


def test_multiple_zones_need_valves_and_supply_cannot_be_a_valve(growspace):
    with pytest.raises(ValidationChangeError):
        edited_zones(
            growspace,
            "add",
            {
                "zone_id": "second",
                "name": "Blue",
                "cells": [[1, 2]],
                "valves": ["switch.blue"],
            },
        )
    growspace = split(growspace)
    growspace.irrigation_config.irrigation_pump_entity = "switch.blue"
    with pytest.raises(ValidationChangeError):
        validate_zones(growspace)


@pytest.mark.parametrize(
    "count", [MAX_ZONES_PER_GROWSPACE, MAX_ZONES_PER_GROWSPACE + 1]
)
def test_zone_limit(growspace, count):
    growspace.irrigation_zones = [IrrigationZone(id="default")] + [
        IrrigationZone(id=str(i)) for i in range(count - 1)
    ]
    if count == MAX_ZONES_PER_GROWSPACE:
        with pytest.raises(EnvelopeExceededError, match="zones_per_growspace.*6"):
            edited_zones(growspace, "add", {"zone_id": "extra"})
    else:
        with pytest.raises(EnvelopeExceededError, match="zones_per_growspace.*6"):
            validate_zones(growspace)


def test_valve_limit(growspace):
    growspace.default_zone.valves = [
        f"switch.valve_{i}" for i in range(MAX_VALVES_PER_ZONE + 1)
    ]
    with pytest.raises(EnvelopeExceededError, match="valves_per_zone.*8"):
        validate_zones(growspace)


def probes(quantity="moisture", count=4):
    return [
        {
            "entity_id": f"sensor.probe_{i}",
            "quantity": quantity,
            "role": "control" if i == 0 else "witness",
            "cell": [1, 1],
        }
        for i in range(count)
    ]


@pytest.mark.parametrize("quantity", ["moisture", "pore_ec", "bulk_ec", "temperature"])
def test_probe_inventory_roles_cells_and_limit(growspace, quantity):
    set_probes(growspace.default_zone, probes(quantity))
    assert len(probe_documents(growspace.default_zone)) == MAX_PROBES_PER_QUANTITY
    assert probe_documents(growspace.default_zone)[0]["role"] == "control"
    validate_zones(growspace)
    assert Growspace.from_dict(growspace.to_dict()) == growspace
    with pytest.raises(EnvelopeExceededError, match="probes_per_quantity.*4"):
        set_probes(growspace.default_zone, probes(quantity, 5))
    getattr(
        growspace.default_zone,
        {
            "moisture": "moisture_witness_sensors",
            "pore_ec": "pore_ec_sensors",
            "bulk_ec": "bulk_ec_sensors",
            "temperature": "substrate_temperature_sensors",
        }[quantity],
    ).append("sensor.extra")
    with pytest.raises(EnvelopeExceededError):
        validate_zones(growspace)


@pytest.mark.parametrize(
    "items",
    [
        [{"entity_id": "sensor.x", "quantity": "unknown", "role": "control"}],
        [{"entity_id": "sensor.x", "quantity": "moisture", "role": "witness"}],
        [
            {"entity_id": "sensor.x", "quantity": "moisture", "role": "control"},
            {"entity_id": "sensor.x", "quantity": "pore_ec", "role": "control"},
        ],
        [
            {"entity_id": "sensor.x", "quantity": "moisture", "role": "control"},
            {"entity_id": "sensor.y", "quantity": "moisture", "role": "unknown"},
        ],
    ],
)
def test_invalid_probe_inventory(growspace, items):
    with pytest.raises(ValidationChangeError):
        set_probes(growspace.default_zone, items)


def test_probe_placement_belongs_to_zone(growspace):
    growspace = split(growspace)
    set_probes(growspace.default_zone, probes())
    with pytest.raises(ValidationChangeError):
        edited_zones(
            growspace, "assign", {"zone_id": "second", "cells": [[1, 1], [1, 2]]}
        )


def test_resize_inherits_adjacent_boundary(growspace):
    growspace = split(growspace)
    growspace.rows = 3
    growspace.plants_per_row = 3
    sync_implicit_zone_cells(growspace)
    assert (3, 1) in growspace.default_zone.cells
    assert set(resolve_zone(growspace, "second").cells) == {
        (1, 2),
        (2, 2),
        (1, 3),
        (2, 3),
        (3, 2),
        (3, 3),
    }
    validate_zones(growspace)
    growspace.rows = 1
    sync_implicit_zone_cells(growspace)
    validate_zones(growspace)


def coordinator(growspace):
    return SimpleNamespace(
        growspaces={"tent": growspace},
        lock=asyncio.Lock(),
        cache=Mock(),
        async_commit=AsyncMock(),
        async_request_refresh=AsyncMock(),
        hass=Mock(),
    )


@pytest.mark.asyncio
async def test_commit_revision_conflict_rollback_and_noop(growspace):
    coord = coordinator(growspace)
    result = await async_edit_zones(
        coord,
        "tent",
        0,
        "add",
        {
            "name": "Blue",
            "cells": [[1, 2], [2, 2]],
            "valves": ["switch.blue"],
            "default_valves": ["switch.red"],
        },
    )
    assert result["layout_revision"] == 1
    assert result["zones"][0]["name"] == "Zone 1"
    assert len(result["zones"]) == 2
    before = copy.deepcopy(growspace)
    with pytest.raises(LayoutConflictError):
        await async_edit_zones(
            coord, "tent", 0, "update", {"zone_id": "default", "name": "Red"}
        )
    with pytest.raises(EntityNotFoundError):
        await async_edit_zones(coord, "absent", 1, "remove", {"zone_id": "default"})
    coord.async_commit.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await async_edit_zones(
            coord, "tent", 1, "update", {"zone_id": "default", "name": "Red"}
        )
    assert growspace == before
    coord.async_commit.reset_mock(side_effect=True)
    await async_edit_zones(
        coord, "tent", 1, "update", {"zone_id": "default", "name": "Zone 1"}
    )
    coord.async_commit.assert_not_called()


@pytest.mark.asyncio
async def test_settings_target_selected_zone_and_missing_zone_refused(growspace):
    growspace = split(growspace)
    coord = coordinator(growspace)
    change = IrrigationChange(
        IrrigationChangeOperation.SETTINGS, {"irrigation_duration": 12}
    )
    with pytest.raises(ZoneRequiredError):
        await async_apply_irrigation_change(coord, "tent", change)
    await async_apply_irrigation_change(coord, "tent", change, zone_id="second")
    assert resolve_zone(growspace, "second").irrigation_duration == 12
    assert growspace.default_zone.irrigation_duration is None
    coord.async_commit.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await async_apply_irrigation_change(
            coord,
            "tent",
            IrrigationChange(
                IrrigationChangeOperation.SETTINGS,
                {"zone_id": "second", "irrigation_duration": 20},
            ),
        )
    assert resolve_zone(growspace, "second").irrigation_duration == 12
    coord.async_commit.side_effect = None
    await async_apply_irrigation_change(
        coord,
        "tent",
        IrrigationChange(
            IrrigationChangeOperation.SETTINGS, {"max_cycle_seconds": 200}
        ),
    )
    assert growspace.irrigation_config.max_cycle_seconds == 200


@pytest.mark.asyncio
async def test_ha_and_websocket_edits_share_revision_guard(hass, growspace):
    from custom_components.growspace_manager.schemas import ZONE_EDIT_SCHEMAS
    from custom_components.growspace_manager.services.zone_management import (
        handle_edit_zone,
    )
    from custom_components.growspace_manager.websocket.zones import (
        COMMANDS,
        websocket_edit_zone,
    )
    from homeassistant.core import ServiceCall

    coord = coordinator(growspace)
    coord.hass = hass
    values = ZONE_EDIT_SCHEMAS["add_irrigation_zone"](
        {
            "growspace_id": "tent",
            "expected_layout_revision": 0,
            "name": "Blue",
            "cells": [[1, 2], [2, 2]],
            "valves": ["switch.blue"],
            "default_valves": ["switch.red"],
        }
    )
    result = await handle_edit_zone(
        hass,
        coord,
        ServiceCall(hass, "growspace_manager", "add_irrigation_zone", values),
    )
    second = result["zones"][1]["id"]
    update = next(c for c in COMMANDS if c.type.endswith("update_irrigation_zone"))
    msg = update.schema(
        {
            "id": 1,
            "type": update.type,
            "growspace_id": "tent",
            "expected_layout_revision": 1,
            "zone_id": second,
            "name": "Indigo",
        }
    )
    result = await websocket_edit_zone(hass, coord, msg)
    assert result["layout_revision"] == 2
    assert result["zones"][1]["name"] == "Indigo"
    with pytest.raises(LayoutConflictError):
        await websocket_edit_zone(hass, coord, msg)
    result = await async_edit_zones(coord, "tent", 2, "remove", {"zone_id": second})
    assert result["zones"][0]["name"] == ""
    assert len(result["zones"][0]["cells"]) == 4


@pytest.mark.asyncio
async def test_zone_strategy_phase_mode_clear_and_schedule(growspace):
    from custom_components.growspace_manager.const import SteeringMode
    from custom_components.growspace_manager.services.growspace_facade import (
        GrowspaceFacade,
    )

    growspace = split(growspace)
    coord = coordinator(growspace)
    facade = GrowspaceFacade(coord)
    zone = resolve_zone(growspace, "second")
    default_before = copy.deepcopy(growspace.default_zone)
    await facade.set_irrigation_strategy(
        "tent", {"zone_id": "second", "target_vwc_percent": 55}
    )
    await facade.set_steering_phase("tent", "p1", zone_id="second")
    await facade.apply_steering_mode("tent", SteeringMode.GENERATIVE, zone_id="second")
    assert zone.active_steering_phase == "p1"
    assert zone.strategy.declared_steering_mode == SteeringMode.GENERATIVE
    assert growspace.default_zone == default_before
    zone.irrigation_duration = 12
    with pytest.raises(ZoneRequiredError):
        await facade.add_irrigation_schedule_item("tent", "irrigation_times", "08:00")
    await facade.add_irrigation_schedule_item(
        "tent", "irrigation_times", "08:00", zone_id="second"
    )
    assert zone.irrigation_times == [{"time": "08:00:00", "duration": 12}]
    coord.async_commit.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await facade.remove_irrigation_schedule_item(
            "tent", "irrigation_times", "08:00", zone_id="second"
        )
    assert zone.irrigation_times == [{"time": "08:00:00", "duration": 12}]
    coord.async_commit.side_effect = None
    await facade.remove_irrigation_schedule_item(
        "tent", "irrigation_times", "08:00", zone_id="second"
    )
    assert zone.irrigation_times == []
    growspace.irrigation_config.irrigation_pump_entity = "switch.pump"
    await facade.clear_irrigation("tent", zone_id="second")
    assert growspace.irrigation_config.irrigation_pump_entity == "switch.pump"
    assert zone.irrigation_duration is None
    assert growspace.default_zone == default_before


@pytest.mark.asyncio
async def test_program_binding_scope_and_rollback(growspace):
    from custom_components.growspace_manager.services.growspace_facade import (
        GrowspaceFacade,
    )

    growspace = split(growspace)
    coord = coordinator(growspace)
    coord._program_library = Mock()
    facade = GrowspaceFacade(coord)
    with pytest.raises(ZoneRequiredError):
        await facade.assign_irrigation_program("tent", "program")
    await facade.assign_irrigation_program("tent", "program", zone_id="second")
    zone = resolve_zone(growspace, "second")
    assert zone.strategy.irrigation_program_id == "program"
    assert growspace.default_zone.strategy.irrigation_program_id is None
    coord.async_commit.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await facade.assign_irrigation_program("tent", None, zone_id="second")
    assert zone.strategy.irrigation_program_id == "program"


@pytest.mark.asyncio
async def test_environment_probe_scope_envelope_and_rollback(hass, growspace):
    from custom_components.growspace_manager.domain.environment_patch import (
        patch_from_service_call,
    )
    from custom_components.growspace_manager.services.environment_patch_commit import (
        async_commit_environment_patch,
    )

    growspace = split(growspace)
    coord = coordinator(growspace)
    coord.services = SimpleNamespace(save=AsyncMock(), request_refresh=AsyncMock())
    patch = patch_from_service_call({"soil_moisture_sensor": "sensor.blue"})
    with pytest.raises(ZoneRequiredError):
        await async_commit_environment_patch(hass, coord, growspace, patch)
    await async_commit_environment_patch(
        hass, coord, growspace, patch, zone_id="second"
    )
    assert resolve_zone(growspace, "second").soil_moisture_sensor == "sensor.blue"
    assert growspace.default_zone.soil_moisture_sensor is None
    before = copy.deepcopy(growspace)
    excessive = patch_from_service_call(
        {"pore_ec_sensors": [f"sensor.ec_{i}" for i in range(5)]}
    )
    with pytest.raises(EnvelopeExceededError):
        await async_commit_environment_patch(
            hass, coord, growspace, excessive, zone_id="second"
        )
    assert growspace == before
    coord.services.save.side_effect = OSError("disk full")
    with pytest.raises(OSError):
        await async_commit_environment_patch(
            hass,
            coord,
            growspace,
            patch_from_service_call({"soil_moisture_sensor": "sensor.new"}),
            zone_id="second",
        )
    assert growspace == before


def test_default_integrity_refusals_and_null_probe_metadata(growspace):
    growspace.irrigation_zones = []
    with pytest.raises(ValidationChangeError, match="implicit"):
        validate_zones(growspace)
    growspace.irrigation_zones = [
        IrrigationZone(id="default"),
        IrrigationZone(id="default"),
    ]
    with pytest.raises(ValidationChangeError, match="implicit"):
        validate_zones(growspace)
    growspace.irrigation_zones = [
        IrrigationZone(id="default"),
        IrrigationZone(id="x"),
        IrrigationZone(id="x"),
    ]
    with pytest.raises(ValidationChangeError, match="unique"):
        validate_zones(growspace)
    zone = IrrigationZone.from_dict(
        {
            "id": "default",
            "probe_cells": None,
            "probe_roles": None,
            "moisture_witness_sensors": None,
        }
    )
    assert probe_documents(zone) == []
    assert zone.probe_cells == zone.probe_roles == {}


@pytest.mark.asyncio
async def test_recipe_capture_and_application_select_a_zone(growspace):
    from custom_components.growspace_manager.const import IrrigationRecipeKind
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )
    from custom_components.growspace_manager.managers.irrigation_recipe import (
        IrrigationRecipeLibrary,
    )
    from custom_components.growspace_manager.services.growspace_facade import (
        GrowspaceFacade,
    )

    growspace = split(growspace)
    zone = resolve_zone(growspace, "second")
    zone.irrigation_duration = 15
    zone.irrigation_times = [{"time": "08:00:00", "duration": 15}]
    repo = GrowspaceRepository()
    repo.add_growspace(growspace)
    library = IrrigationRecipeLibrary(repo, AsyncMock())
    with pytest.raises(ZoneRequiredError):
        await library.async_save_from_growspace(
            "tent", "Blue schedule", IrrigationRecipeKind.SCHEDULE
        )
    recipe = await library.async_save_from_growspace(
        "tent", "Blue schedule", IrrigationRecipeKind.SCHEDULE, zone_id="second"
    )
    assert recipe.schedule.irrigation_duration == 15
    coord = coordinator(growspace)
    coord._recipe_library = library
    coord.services = SimpleNamespace(
        growspaces=SimpleNamespace(get_growspace_plants=Mock(return_value=[]))
    )
    zone.irrigation_duration = 20
    facade = GrowspaceFacade(coord)
    with pytest.raises(ZoneRequiredError):
        await facade.apply_irrigation_recipe("tent", recipe.id)
    await facade.apply_irrigation_recipe("tent", recipe.id, zone_id="second")
    assert zone.irrigation_duration == 15
    assert zone.strategy.applied_recipe.id == recipe.id
    assert growspace.default_zone.strategy.applied_recipe is None
    assert growspace.default_zone.irrigation_times == []


def test_single_zone_resize_removes_probe_placement_outside_grid(growspace):
    growspace.default_zone.probe_cells = {"sensor.probe": (2, 2)}
    growspace.rows = growspace.plants_per_row = 1
    sync_implicit_zone_cells(growspace)
    assert growspace.default_zone.probe_cells == {}


@pytest.mark.asyncio
async def test_zone_edit_refused_during_delivery(growspace):
    coord = coordinator(growspace)
    coord._subsystem_manager = SimpleNamespace(
        irrigation_coordinators={
            "tent": SimpleNamespace(active_events={"irrigation": {"duration": 30}})
        }
    )
    with pytest.raises(ValidationChangeError, match="active pump"):
        await async_edit_zones(
            coord, "tent", 0, "update", {"zone_id": "default", "name": "Red"}
        )
    assert growspace.layout_revision == 0
    coord.async_commit.assert_not_called()
    coord._subsystem_manager.irrigation_coordinators["tent"].active_events = {}
    await async_edit_zones(
        coord, "tent", 0, "update", {"zone_id": "default", "name": "Red"}
    )
    assert growspace.layout_revision == 1


@pytest.mark.asyncio
async def test_valve_cannot_be_owned_by_another_growspace(growspace):
    coord = coordinator(growspace)
    other = Growspace(id="other", name="Other")
    other.default_zone.valves = ["switch.valve"]
    coord.growspaces["other"] = other
    with pytest.raises(ValidationChangeError, match="exactly one zone"):
        await async_edit_zones(
            coord,
            "tent",
            0,
            "update",
            {"zone_id": "default", "valves": ["switch.valve"]},
        )
    assert growspace.default_zone.valves == []
    assert growspace.layout_revision == 0
    await async_edit_zones(
        coord, "tent", 0, "update", {"zone_id": "default", "valves": ["switch.unique"]}
    )
    assert growspace.default_zone.valves == ["switch.unique"]


def test_duplicate_probe_cannot_bypass_editor_through_legacy_lists(growspace):
    growspace.default_zone.soil_moisture_sensor = "sensor.same"
    growspace.default_zone.pore_ec_sensors = ["sensor.same"]
    with pytest.raises(ValidationChangeError, match="more than once"):
        validate_zones(growspace)


def test_edit_replaces_selected_zone_probe_inventory(growspace):
    growspace = split(growspace)
    candidate = edited_zones(
        growspace,
        "update",
        {
            "zone_id": "second",
            "probes": [
                {
                    "entity_id": "sensor.blue",
                    "quantity": "moisture",
                    "role": "control",
                    "cell": [1, 2],
                }
            ],
        },
    )
    assert probe_documents(resolve_zone(candidate, "second")) == [
        {
            "entity_id": "sensor.blue",
            "quantity": "moisture",
            "role": "control",
            "cell": (1, 2),
            "name": None,
        }
    ]
    assert probe_documents(growspace.default_zone) == []
    assert probe_documents(resolve_zone(growspace, "second")) == []


@pytest.mark.asyncio
async def test_remove_schedule_from_unknown_growspace_is_refused(growspace):
    from custom_components.growspace_manager.services.growspace_facade import (
        GrowspaceFacade,
    )
    from homeassistant.exceptions import ServiceValidationError

    facade = GrowspaceFacade(coordinator(growspace))
    with pytest.raises(ServiceValidationError, match="not found"):
        await facade.remove_irrigation_schedule_item(
            "absent", "irrigation_times", "08:00"
        )


def test_probe_name_survives_store_roundtrip(growspace):
    zone = growspace.default_zone
    from custom_components.growspace_manager.domain.zone_edit import set_probes
    from custom_components.growspace_manager.models.irrigation_zone import (
        IrrigationZone,
    )

    set_probes(
        zone,
        [
            {
                "entity_id": "sensor.blue",
                "quantity": "moisture",
                "role": "control",
                "cell": [1, 1],
                "name": "Representative plant",
            }
        ],
    )
    assert (
        probe_documents(IrrigationZone.from_dict(zone.to_dict()))[0]["name"]
        == "Representative plant"
    )
    set_probes(zone, [])
    assert not zone.probe_names
