"""Starting a Grow Run end to end: WebSocket, store, sensor, authority (#668)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.domain.grow_run import (
    PlantMovementFact,
    RunMetadata,
    RunRevisionConflict,
    RunStatus,
    RunStoreUnreadable,
)
from custom_components.growspace_manager.grow_run_store import (
    EVENT_GROW_RUN_LIFECYCLE,
    GrowRunStore,
)
from custom_components.growspace_manager.services.grow_runs import (
    active_run_unique_id,
    async_complete_grow_run,
    async_start_grow_run,
    preview_grow_run_completion,
    require_controller,
)
from custom_components.growspace_manager.websocket.grow_runs import (
    WS_TYPE_COMPLETE_GROW_RUN,
    WS_TYPE_GET_GROW_RUN,
    WS_TYPE_PREVIEW_GROW_RUN_COMPLETION,
    WS_TYPE_START_GROW_RUN,
)
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.helpers import entity_registry as er
from tests.common import MockConfigEntry, async_capture_events


async def _tent(
    init_integration: MockConfigEntry, plants: int = 2
) -> tuple[Any, str, list[str]]:
    """A growspace with ``plants`` plants in it."""
    coordinator = init_integration.runtime_data
    growspace = await coordinator.services.growspaces.add_growspace(
        name="Run Tent", rows=2, plants_per_row=2
    )
    plant_ids = [
        (
            await coordinator.services.plants.add_plant(
                growspace_id=growspace.id, strain="OG Kush", row=1, col=col
            )
        ).plant_id
        for col in range(1, plants + 1)
    ]
    await coordinator.async_refresh()
    return coordinator, growspace.id, plant_ids


def _sensor(hass: HomeAssistant, growspace_id: str) -> Any:
    entity_id = er.async_get(hass).async_get_entity_id(
        Platform.SENSOR, DOMAIN, active_run_unique_id(growspace_id)
    )
    assert entity_id is not None
    return hass.states.get(entity_id)


async def _token_for(hass: HomeAssistant, group_id: str) -> str:
    group = await hass.auth.async_get_group(group_id)
    user = MockUser(groups=[group]).add_to_hass(hass)
    refresh = await hass.auth.async_create_refresh_token(user, CLIENT_ID)
    return hass.auth.async_create_access_token(refresh)


async def _admin(hass: HomeAssistant) -> Any:
    group = await hass.auth.async_get_group(GROUP_ID_ADMIN)
    return MockUser(groups=[group]).add_to_hass(hass)


async def _start(client: Any, growspace_id: str, revision: int, **extra: Any) -> Any:
    await client.send_json_auto_id(
        {
            "type": WS_TYPE_START_GROW_RUN,
            "growspace_id": growspace_id,
            "expected_run_revision": revision,
            **extra,
        }
    )
    response = await client.receive_json()
    assert response["success"], response
    return response["result"]


async def test_a_grower_starts_a_run_and_sees_it_at_once(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Start → sensor → stale start refused with the current revision."""
    coordinator, growspace_id, plant_ids = await _tent(init_integration)
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    before = _sensor(hass, growspace_id)
    assert before.state == "none"
    assert before.attributes["run_revision"] == 0

    client = await hass_ws_client(hass)
    result = await _start(
        client, growspace_id, 0, label=" Autumn ", tags=["organic"], goals="Beat #3"
    )

    assert result["outcome"] == "started"
    assert result["run_revision"] == 1
    summary = result["active_run"]
    assert summary["sequence_number"] == 1
    assert summary["label"] == "Autumn"
    assert summary["participant_count"] == 2
    assert summary["timezone"] == hass.config.time_zone

    await hass.async_block_till_done()
    sensor = _sensor(hass, growspace_id)
    assert sensor.state == "1"
    assert sensor.attributes["run_id"] == summary["run_id"]
    assert sensor.attributes["participant_count"] == 2
    assert sensor.attributes["duration_days"] == 0
    assert sensor.attributes["run_revision"] == 1

    run = coordinator.grow_runs.active_run(growspace_id)
    assert sorted(p.plant_id for p in run.participations) == sorted(plant_ids)
    assert run.audit[0].actor_user_id is not None
    assert [e.data["command"] for e in events] == ["start"]

    stale = await _start(client, growspace_id, 0)
    assert stale["outcome"] == "refused"
    assert stale["refusal"]["code"] == "grow_run.revision_conflict"
    assert stale["refusal"]["current_revision"] == 1
    assert stale["refusal"]["active_run"]["run_id"] == summary["run_id"]

    second = await _start(client, growspace_id, 1)
    assert second["refusal"]["code"] == "grow_run.already_active"
    assert second["refusal"]["current_revision"] == 1


async def test_an_empty_growspace_starts_a_run_with_zero_participants(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    _, growspace_id, _ = await _tent(init_integration, plants=0)
    client = await hass_ws_client(hass)
    result = await _start(client, growspace_id, 0)
    assert result["active_run"]["participant_count"] == 0
    assert result["active_run"]["label"] is None


async def test_the_opening_baseline_records_conditions_and_outputs(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    growspace = coordinator.growspaces[growspace_id]
    growspace.irrigation_config.irrigation_pump_entity = "switch.run_tent_pump"
    hass.states.async_set("switch.run_tent_pump", "on")
    registry = er.async_get(hass)
    condition = registry.async_get_or_create(
        Platform.BINARY_SENSOR,
        DOMAIN,
        f"{DOMAIN}_{growspace_id}_mold_risk",
        config_entry=init_integration,
    )
    hass.states.async_set(condition.entity_id, "on")

    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )

    assert [(s.entity_id, s.key, s.state) for s in run.baseline.conditions] == [
        (condition.entity_id, "mold_risk", "on")
    ]
    assert [(s.entity_id, s.key, s.state) for s in run.baseline.equipment] == [
        ("switch.run_tent_pump", "switch", "on")
    ]


async def test_a_missing_output_is_recorded_as_unavailable(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    growspace = coordinator.growspaces[growspace_id]
    growspace.irrigation_config.irrigation_pump_entity = "switch.nowhere"
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    assert [(s.entity_id, s.state) for s in run.baseline.equipment] == [
        ("switch.nowhere", "unavailable")
    ]


async def test_plant_exit_reentry_and_removal_project_once_and_are_readable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Run intervals are half-open; a returning Plant remains one Participant."""
    coordinator, growspace_id, (plant_id,) = await _tent(init_integration, plants=1)
    other = await coordinator.services.growspaces.add_growspace(name="Other Tent")
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    await coordinator.services.plants.update_plant(plant_id, growspace_id=other.id)
    await coordinator.services.plants.update_plant(plant_id, growspace_id=growspace_id)
    await coordinator.services.plants.remove_plant(plant_id)

    projected = coordinator.grow_runs.active_run(growspace_id)
    assert projected is not None
    assert projected.participant_count == 1
    assert len(projected.participations) == 2
    assert all(row.closed_at is not None for row in projected.participations)
    assert all(row.opened_at <= row.closed_at for row in projected.participations)
    assert [row.kind for row in projected.movement_history] == [
        "transplant",
        "re_entry",
        "removal",
    ]
    assert len({row.fact_id for row in projected.movement_history}) == 3
    assert all(fact.projected for fact in coordinator.storage_manager.activity_facts)

    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_TYPE_GET_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
        }
    )
    response = await client.receive_json()
    assert response["success"]
    assert response["result"]["outcome"] == "found"
    assert len(response["result"]["run"]["participations"]) == 2
    assert len(response["result"]["run"]["movement_history"]) == 3
    await client.send_json_auto_id(
        {"type": WS_TYPE_GET_GROW_RUN, "growspace_id": growspace_id, "run_id": "absent"}
    )
    assert (await client.receive_json())["result"] == {"outcome": "not_found"}
    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    restored = reloaded.active_run(growspace_id)
    assert restored is not None
    assert len(restored.participations) == 2
    assert len(restored.movement_history) == 3
    plant_document = await coordinator.storage_manager.plants_store.async_load()
    assert len(plant_document["activity_facts"]) >= 3
    assert all(row["fact_id"] for row in plant_document["activity_facts"])


async def test_projection_retries_after_partial_commit_without_duplicates(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The Plant succeeds with a pending fact; replay is safe after an ACK loss."""
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    with pytest.raises(ValueError, match="references a missing Run"):
        await coordinator.grow_runs.async_project_movement(
            PlantMovementFact(
                fact_id="broken-reference",
                plant_id="p1",
                at=run.started_at,
                kind="removal",
                source_growspace_id=growspace_id,
                target_growspace_id=None,
                source_run_id="missing",
                target_run_id=None,
            )
        )
    with patch.object(
        coordinator.grow_runs, "async_project_movement", side_effect=OSError("disk")
    ):
        plant = await coordinator.services.plants.add_plant(
            growspace_id=growspace_id, strain="OG Kush"
        )
    pending = [
        fact
        for fact in coordinator.storage_manager.activity_facts
        if fact.plant_id == plant.plant_id
    ]
    assert len(pending) == 1 and not pending[0].projected
    assert coordinator.grow_runs.active_run(growspace_id).participant_count == 0

    with patch.object(
        coordinator.storage_manager,
        "async_mark_fact_projected",
        side_effect=OSError("ack lost"),
    ):
        await coordinator.async_project_pending_activity()
    assert coordinator.grow_runs.active_run(growspace_id).participant_count == 1
    assert not pending[0].projected
    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    assert len(reloaded.active_run(growspace_id).movement_history) == 1
    durable = await coordinator.storage_manager.plants_store.async_load()
    assert any(
        row["fact_id"] == pending[0].fact_id and not row["projected"]
        for row in durable["activity_facts"]
    )

    await coordinator.async_project_pending_activity()
    projected = coordinator.grow_runs.active_run(growspace_id)
    assert projected.participant_count == 1
    assert len(projected.participations) == 1
    assert len(projected.movement_history) == 1
    assert [
        fact.projected
        for fact in coordinator.storage_manager.activity_facts
        if fact.plant_id == plant.plant_id
    ] == [True]


async def test_failed_plant_write_does_not_announce_a_move_or_emit_a_fact(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A rejected move leaves the Plant and Activity outbox at their old image."""
    coordinator, growspace_id, (plant_id,) = await _tent(init_integration, plants=1)
    other = await coordinator.services.growspaces.add_growspace(name="Other Tent")
    await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    before = len(coordinator.storage_manager.activity_facts)
    with patch.object(
        coordinator.storage_manager.plants_store,
        "async_save",
        side_effect=OSError("plant disk full"),
    ):
        with pytest.raises(OSError, match="plant disk full"):
            await coordinator.services.plants.update_plant(
                plant_id, growspace_id=other.id
            )
    assert coordinator.plants[plant_id].growspace_id == growspace_id
    assert len(coordinator.storage_manager.activity_facts) == before
    assert coordinator.grow_runs.active_run(growspace_id).movement_history == ()


async def test_unreadable_run_history_does_not_block_plant_and_reconciles_later(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A Plant move survives Run-store repair and gains its original interval."""
    coordinator, growspace_id, (plant_id,) = await _tent(init_integration, plants=1)
    other = await coordinator.services.growspaces.add_growspace(name="Other Tent")
    await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    coordinator.grow_runs.unreadable = True
    await coordinator.services.plants.update_plant(plant_id, growspace_id=other.id)
    await coordinator.services.plants.update_plant(plant_id, growspace_id=growspace_id)
    pending = [
        fact
        for fact in coordinator.storage_manager.activity_facts
        if fact.plant_id == plant_id and not fact.projected
    ]
    assert len(pending) == 2
    assert pending[0].source_run_id is None
    assert pending[1].target_run_id is None
    coordinator.grow_runs.unreadable = False
    await coordinator.async_project_pending_activity()
    restored = coordinator.grow_runs.active_run(growspace_id)
    assert restored.participations[0].closed_at is not None
    assert len(restored.participations) == 2
    assert restored.participations[1].closed_at is None
    assert restored.movement_history[0].source_run_id == restored.run_id
    assert restored.movement_history[1].target_run_id == restored.run_id


async def test_staged_layout_move_projects_after_its_plant_snapshot(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """The layout transaction's separate save path also emits one movement."""
    coordinator, growspace_id, (plant_id,) = await _tent(init_integration, plants=1)
    await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    revision = coordinator.growspaces[growspace_id].layout_revision
    await coordinator.services.plants.set_plant_layout(
        growspace_id,
        revision,
        [{"plant_id": plant_id, "row": 2, "col": 2}],
    )
    run = coordinator.grow_runs.active_run(growspace_id)
    assert run.participant_count == 1
    assert [fact.kind for fact in run.movement_history] == ["move"]
    assert run.participations[0].closed_at is None


@pytest.mark.parametrize("operation", ["remove", "switch", "relocate"])
async def test_failed_batch_movement_restores_plants_and_outbox(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    operation: str,
) -> None:
    """A Plant-store failure never leaves a later save to invent a movement."""
    coordinator, growspace_id, plant_ids = await _tent(init_integration, plants=2)
    other = await coordinator.services.growspaces.add_growspace(
        name="Other Tent", rows=2, plants_per_row=2
    )
    coordinator.notification_state.sent[plant_ids[0]] = ["sent"]
    before = {
        plant_id: (
            coordinator.plants[plant_id].growspace_id,
            coordinator.plants[plant_id].row,
            coordinator.plants[plant_id].col,
        )
        for plant_id in plant_ids
    }
    fact_count = len(coordinator.storage_manager.activity_facts)
    revisions = {
        growspace_id: coordinator.growspaces[growspace_id].layout_revision,
        other.id: coordinator.growspaces[other.id].layout_revision,
    }
    if operation == "remove":
        mutation = coordinator.services.plants.remove_plant(plant_ids[0])
    elif operation == "switch":
        mutation = coordinator.services.plants.switch_plants(*plant_ids)
    else:
        mutation = coordinator.services.plants.relocate_to_growspace(
            other.id, [plant_ids[0]]
        )
    with patch.object(
        coordinator.storage_manager.plants_store,
        "async_save",
        side_effect=OSError("plant disk full"),
    ):
        with pytest.raises(OSError, match="plant disk full"):
            await mutation
    assert {
        plant_id: (
            coordinator.plants[plant_id].growspace_id,
            coordinator.plants[plant_id].row,
            coordinator.plants[plant_id].col,
        )
        for plant_id in plant_ids
    } == before
    assert len(coordinator.storage_manager.activity_facts) == fact_count
    assert coordinator.notification_state.sent[plant_ids[0]] == ["sent"]
    assert {
        growspace_id: coordinator.growspaces[growspace_id].layout_revision,
        other.id: coordinator.growspaces[other.id].layout_revision,
    } == revisions


# ---------------------------------------------------------------------------
# Run Lifecycle Authorization: a Growspace controller may start
# ---------------------------------------------------------------------------


async def test_an_ordinary_user_may_start_a_run(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    token = await _token_for(hass, GROUP_ID_USER)
    client = await hass_ws_client(hass, token)
    result = await _start(client, growspace_id, 0)
    assert result["outcome"] == "started"
    run = coordinator.grow_runs.active_run(growspace_id)
    user = await hass.auth.async_get_user(run.audit[0].actor_user_id)
    assert user is not None
    assert not user.is_admin


async def test_a_read_only_user_is_refused_with_the_current_revision(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    result = await _start(client, growspace_id, 0)
    assert result == {
        "outcome": "refused",
        "refusal": {
            "code": "grow_run.not_authorized",
            "message": "Starting a Grow Run requires permission to control "
            "this growspace",
            "current_revision": 0,
            "active_run": None,
        },
    }
    assert coordinator.grow_runs.active_run(growspace_id) is None


async def test_a_request_without_a_user_is_refused(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    _, growspace_id, _ = await _tent(init_integration)
    with pytest.raises(Exception, match="signed-in"):
        require_controller(hass, growspace_id, None)


async def test_without_a_registered_sensor_control_of_every_entity_decides(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_read_only_user: MockUser,
) -> None:
    group = await hass.auth.async_get_group(GROUP_ID_USER)
    grower = MockUser(groups=[group]).add_to_hass(hass)
    assert require_controller(hass, "not-yet-registered", grower) == grower.id
    with pytest.raises(Exception, match="permission"):
        require_controller(hass, "not-yet-registered", hass_read_only_user)


async def test_an_unknown_growspace_is_a_validation_failure(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_TYPE_START_GROW_RUN,
            "growspace_id": "nowhere",
            "expected_run_revision": 0,
        }
    )
    response = await client.receive_json()
    assert not response["success"]


# ---------------------------------------------------------------------------
# The store: atomic, write-through, fail closed
# ---------------------------------------------------------------------------


async def test_concurrent_starts_on_one_revision_start_exactly_one_run(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    admin = await _admin(hass)

    async def start() -> Any:
        return await async_start_grow_run(
            hass,
            coordinator,
            growspace_id=growspace_id,
            expected_revision=0,
            metadata=RunMetadata(),
            user=admin,
        )

    results = await asyncio.gather(start(), start(), return_exceptions=True)
    started = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(started) == 1
    assert [type(r).__name__ for r in refused] == ["RunRevisionConflict"]
    assert coordinator.grow_runs.ledger(growspace_id).revision == 1


async def test_a_started_run_survives_a_restart(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata.create(label="Autumn"),
        user=await _admin(hass),
    )
    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    assert not reloaded.unreadable
    assert reloaded.active_run(growspace_id) == run
    assert reloaded.ledger(growspace_id).next_sequence == 2


async def test_a_failed_write_changes_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    with (
        patch.object(
            coordinator.grow_runs._store, "async_save", side_effect=OSError("disk")
        ),
        pytest.raises(OSError),
    ):
        await async_start_grow_run(
            hass,
            coordinator,
            growspace_id=growspace_id,
            expected_revision=0,
            metadata=RunMetadata(),
            user=await _admin(hass),
        )
    ledger = coordinator.grow_runs.ledger(growspace_id)
    assert (ledger.revision, ledger.runs) == (0, ())
    assert events == []


@pytest.mark.parametrize(
    "document",
    [
        {"ledgers": []},
        {"ledgers": {"tent": {"growspace_id": "tent", "revision": "x"}}},
        {
            "ledgers": {
                "tent": {
                    "growspace_id": "other",
                    "revision": 0,
                    "next_sequence": 1,
                    "runs": [],
                }
            }
        },
    ],
)
async def test_an_unreadable_history_refuses_every_start_and_is_kept(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
    hass_ws_client: WebSocketGenerator,
    document: dict[str, Any],
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    key = f"growspace_manager.grow_runs_{init_integration.entry_id}"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": document}
    store = GrowRunStore(hass, init_integration.entry_id)
    await store.async_load()
    assert store.unreadable
    assert store.active_run(growspace_id) is None
    with pytest.raises(RunStoreUnreadable):
        await store.async_commit(store._ledgers.get("x"))  # type: ignore[arg-type]
    coordinator.grow_runs = store
    coordinator.async_update_listeners()
    await hass.async_block_till_done()

    client = await hass_ws_client(hass)
    result = await _start(client, growspace_id, 0)
    assert result["refusal"]["code"] == "grow_run.store_unreadable"
    assert result["refusal"]["current_revision"] is None
    assert hass_storage[key]["data"] == document
    assert _sensor(hass, growspace_id).state == "unavailable"


async def test_a_missing_file_is_an_empty_history(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    store = GrowRunStore(hass, "fresh")
    await store.async_load()
    assert not store.unreadable
    assert store.ledger("tent").revision == 0


async def test_a_file_that_exists_but_does_not_load_fails_closed(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    store = GrowRunStore(hass, "corrupt")
    with (
        patch.object(store._store, "async_load", return_value=None),
        patch(
            "custom_components.growspace_manager.grow_run_store.exists",
            return_value=True,
        ),
    ):
        await store.async_load()
    assert store.unreadable


async def test_the_logbook_describes_a_run_start(hass: HomeAssistant) -> None:
    from custom_components.growspace_manager import logbook

    described: dict[str, Any] = {}

    def capture(domain: str, event_type: str, describe: Any) -> None:
        described["describe"] = describe

    logbook.async_describe_events(hass, capture)
    event = Event(
        "x", {"category": "grow_run", "message": "Run #1 started by HA user u"}
    )
    assert described["describe"](event)["message"] == "Run #1 started by HA user u"
    assert described["describe"](Event("x", {"category": "grow_run"}))["message"] == (
        "Run changed"
    )


# ---------------------------------------------------------------------------
# Completing a Run (#671)
# ---------------------------------------------------------------------------

EVERY_WARNING = ["plants_present", "missing_outcomes", "attribution_gaps"]


async def _ws(client: Any, message: dict[str, Any]) -> Any:
    await client.send_json_auto_id(message)
    response = await client.receive_json()
    assert response["success"], response
    return response["result"]


async def _started(hass: HomeAssistant, coordinator: Any, growspace_id: str) -> Any:
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata.create(label="Autumn"),
        user=await _admin(hass),
    )
    return run


async def _complete_as_admin(
    hass: HomeAssistant,
    coordinator: Any,
    growspace_id: str,
    run_id: str,
    revision: int = 1,
    acknowledged: list[str] | None = None,
) -> Any:
    return await async_complete_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        run_id=run_id,
        expected_revision=revision,
        acknowledged=EVERY_WARNING if acknowledged is None else acknowledged,
        user=await _admin(hass),
    )


async def test_a_grower_previews_acknowledges_and_completes_a_run(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Preview → unacknowledged refusal → completion → sensor, event, logbook."""
    coordinator, growspace_id, plant_ids = await _tent(init_integration)
    client = await hass_ws_client(hass)
    started = await _start(client, growspace_id, 0, label="Autumn")
    run_id = started["active_run"]["run_id"]
    lifecycle = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    logbook = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

    preview = await _ws(
        client,
        {
            "type": WS_TYPE_PREVIEW_GROW_RUN_COMPLETION,
            "growspace_id": growspace_id,
            "retrospective_note": " Dense buds ",
        },
    )
    assert preview["outcome"] == "preview"
    body = preview["preview"]
    assert body["warnings"] == ["plants_present"]
    assert body["blockers"] == []
    assert body["retrospective_note"] == "Dense buds"
    assert sorted(row["plant_id"] for row in body["plants_present"]) == sorted(
        plant_ids
    )
    assert len(body["closing_participations"]) == 2
    assert body["run"]["run_id"] == run_id
    assert body["duration_days"] == 0

    unacknowledged = await _ws(
        client,
        {
            "type": WS_TYPE_COMPLETE_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run_id,
            "expected_run_revision": 1,
            "acknowledged_warnings": [],
        },
    )
    assert unacknowledged["outcome"] == "refused"
    assert unacknowledged["refusal"]["code"] == "grow_run.acknowledgement_required"
    assert unacknowledged["refusal"]["current_revision"] == 1
    assert coordinator.grow_runs.active_run(growspace_id) is not None

    completed = await _ws(
        client,
        {
            "type": WS_TYPE_COMPLETE_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run_id,
            "expected_run_revision": 1,
            "acknowledged_warnings": ["plants_present"],
            "retrospective_note": "Dense buds",
        },
    )
    assert completed["outcome"] == "completed"
    assert completed["run_revision"] == 2
    assert completed["run"]["status"] == "completed"
    assert completed["run"]["metrics_state"] == "pending"
    assert completed["run"]["completed_at"] is not None

    await hass.async_block_till_done()
    sensor = _sensor(hass, growspace_id)
    assert sensor.state == "none"
    assert sensor.attributes["run_id"] is None
    assert sensor.attributes["run_revision"] == 2

    run = coordinator.grow_runs.ledger(growspace_id).runs[0]
    assert run.status is RunStatus.COMPLETED
    assert run.metadata.notes == "Dense buds"
    assert all(row.closed_at == run.completed_at for row in run.participations)
    assert [(e.data["command"], e.data["status"]) for e in lifecycle] == [
        ("complete", "completed")
    ]
    assert lifecycle[0].data["revision"] == 2
    assert lifecycle[0].data["user_id"] == run.audit[-1].actor_user_id
    assert logbook[-1].data["message"].startswith("Run #1 completed by HA user ")

    details = await _ws(
        client,
        {"type": WS_TYPE_GET_GROW_RUN, "growspace_id": growspace_id, "run_id": run_id},
    )
    assert details["run"]["status"] == "completed"
    assert details["run"]["metrics_state"] == "pending"
    assert details["run"]["notes"] == "Dense buds"
    assert all(row["closed_at"] for row in details["run"]["participations"])

    none_left = await _ws(
        client,
        {"type": WS_TYPE_PREVIEW_GROW_RUN_COMPLETION, "growspace_id": growspace_id},
    )
    assert none_left["refusal"]["code"] == "grow_run.not_active"
    assert none_left["refusal"]["current_revision"] == 2

    again = await _start(client, growspace_id, 2)
    assert again["active_run"]["sequence_number"] == 2
    assert again["active_run"]["participant_count"] == 2


async def test_a_completion_keeps_the_note_it_was_not_given(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata.create(notes="Written while growing"),
        user=await _admin(hass),
    )
    preview = preview_grow_run_completion(hass, coordinator, growspace_id=growspace_id)
    assert preview.retrospective_note == "Written while growing"
    completed, _ = await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    assert completed.metadata.notes == "Written while growing"


async def test_irrigation_delivering_water_blocks_completion(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    irrigation = coordinator._subsystem_manager.irrigation_coordinators[growspace_id]
    irrigation._commanded_outputs.add("switch.run_tent_pump")
    client = await hass_ws_client(hass)

    preview = await _ws(
        client,
        {"type": WS_TYPE_PREVIEW_GROW_RUN_COMPLETION, "growspace_id": growspace_id},
    )
    assert preview["preview"]["blockers"] == ["grow_run.irrigation_delivering"]
    assert preview["preview"]["delivering_outputs"] == ["switch.run_tent_pump"]

    message = {
        "type": WS_TYPE_COMPLETE_GROW_RUN,
        "growspace_id": growspace_id,
        "run_id": run.run_id,
        "expected_run_revision": 1,
        "acknowledged_warnings": EVERY_WARNING,
    }
    refused = await _ws(client, message)
    assert refused["refusal"]["code"] == "grow_run.irrigation_delivering"
    assert "switch.run_tent_pump" in refused["refusal"]["message"]
    assert refused["refusal"]["active_run"]["run_id"] == run.run_id
    assert coordinator.grow_runs.active_run(growspace_id) is not None

    irrigation._commanded_outputs.clear()
    assert (await _ws(client, message))["outcome"] == "completed"


async def test_delivering_outputs_are_the_integrations_own_cycles_only(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """Commanded, OFF being retried, or interrupted and still ON; not a person's."""
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    irrigation = coordinator._subsystem_manager.irrigation_coordinators[growspace_id]
    assert irrigation.delivering_outputs() == ()
    assert coordinator.irrigation_delivering_outputs("nowhere") == ()

    irrigation._commanded_outputs.add("switch.b")
    irrigation._off_retries["switch.a"] = lambda: None
    irrigation._enforcing_off.add("switch.person")
    hass.states.async_set("switch.left_on", "on")
    hass.states.async_set("switch.read_off", "off")
    with patch.object(
        irrigation._reliability,
        "active_outputs",
        return_value=("switch.left_on", "switch.read_off", "switch.gone"),
    ):
        assert irrigation.delivering_outputs() == (
            "switch.a",
            "switch.b",
            "switch.left_on",
        )
        assert coordinator.irrigation_delivering_outputs(growspace_id) == (
            "switch.a",
            "switch.b",
            "switch.left_on",
        )
    irrigation._off_retries.clear()


async def test_concurrent_completions_on_one_revision_complete_once(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    run = await _started(hass, coordinator, growspace_id)
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)

    results = await asyncio.gather(
        _complete_as_admin(hass, coordinator, growspace_id, run.run_id),
        _complete_as_admin(hass, coordinator, growspace_id, run.run_id),
        return_exceptions=True,
    )
    assert [type(r).__name__ for r in results if isinstance(r, BaseException)] == [
        "RunRevisionConflict"
    ]
    assert coordinator.grow_runs.ledger(growspace_id).revision == 2
    await hass.async_block_till_done()
    assert [e.data["command"] for e in events] == ["complete"]


@pytest.mark.parametrize("plant_first", [True, False])
async def test_a_plant_moving_during_completion_lands_on_one_side_of_it(
    hass: HomeAssistant, init_integration: MockConfigEntry, plant_first: bool
) -> None:
    """The plant lock orders them: in the Run and closed, or after it entirely."""
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    add = coordinator.services.plants.add_plant(
        growspace_id=growspace_id, strain="OG Kush"
    )
    complete = _complete_as_admin(hass, coordinator, growspace_id, run.run_id)

    if plant_first:
        added, (finished, _) = await asyncio.gather(add, complete)
    else:
        (finished, _), added = await asyncio.gather(complete, add)
    stored = coordinator.grow_runs.ledger(growspace_id).runs[0]
    fact = next(
        f
        for f in coordinator.storage_manager.activity_facts
        if f.plant_id == added.plant_id
    )
    if plant_first:
        assert fact.target_run_id == run.run_id
        assert [(p.plant_id, p.closed_at) for p in stored.participations] == [
            (added.plant_id, finished.completed_at)
        ]
    else:
        assert fact.target_run_id is None
        assert stored.participations == ()


async def test_completion_projects_pending_movement_before_its_boundary(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A committed entry whose projection failed still joins the Run it entered."""
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    with patch.object(
        coordinator.grow_runs, "async_project_movement", side_effect=OSError("disk")
    ):
        plant = await coordinator.services.plants.add_plant(
            growspace_id=growspace_id, strain="OG Kush"
        )
    preview = preview_grow_run_completion(hass, coordinator, growspace_id=growspace_id)
    assert [gap.kind for gap in preview.attribution_gaps] == ["pending_fact"]

    finished, _ = await _complete_as_admin(
        hass, coordinator, growspace_id, run.run_id, acknowledged=["plants_present"]
    )
    assert [(p.plant_id, p.closed_at) for p in finished.participations] == [
        (plant.plant_id, finished.completed_at)
    ]


async def test_a_fact_projected_after_restart_respects_the_boundary(
    hass: HomeAssistant, init_integration: MockConfigEntry, freezer: Any
) -> None:
    """Projection still failing at completion: acknowledged, then healed later."""
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    freezer.tick(60)
    with patch.object(
        coordinator.grow_runs, "async_project_movement", side_effect=OSError("disk")
    ):
        plant = await coordinator.services.plants.add_plant(
            growspace_id=growspace_id, strain="OG Kush"
        )
        freezer.tick(60)
        with pytest.raises(Exception) as refused:
            await _complete_as_admin(
                hass,
                coordinator,
                growspace_id,
                run.run_id,
                acknowledged=["plants_present"],
            )
        assert refused.value.code == "grow_run.acknowledgement_required"
        finished, _ = await _complete_as_admin(
            hass, coordinator, growspace_id, run.run_id
        )
    assert finished.participations == ()

    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    assert reloaded.active_run(growspace_id) is None
    assert reloaded.ledger(growspace_id).runs[0] == finished
    coordinator.grow_runs = reloaded
    await coordinator.async_project_pending_activity()

    healed = reloaded.ledger(growspace_id).runs[0]
    assert healed.status is RunStatus.COMPLETED
    assert [(p.plant_id, p.closed_at) for p in healed.participations] == [
        (plant.plant_id, finished.completed_at)
    ]
    assert reloaded.ledger(growspace_id).revision == 2


async def test_a_movement_after_completion_is_unattributed(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, (plant_id,) = await _tent(init_integration, plants=1)
    run = await _started(hass, coordinator, growspace_id)
    finished, _ = await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    await coordinator.services.plants.remove_plant(plant_id)
    stored = coordinator.grow_runs.ledger(growspace_id).runs[0]
    assert stored == finished
    removal = coordinator.storage_manager.activity_facts[-1]
    assert (removal.kind, removal.source_run_id) == ("removal", None)


async def test_a_read_only_user_may_not_complete(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    run = await _started(hass, coordinator, growspace_id)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    result = await _ws(
        client,
        {
            "type": WS_TYPE_COMPLETE_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
            "expected_run_revision": 1,
            "acknowledged_warnings": EVERY_WARNING,
        },
    )
    assert result["refusal"]["code"] == "grow_run.not_authorized"
    assert result["refusal"]["message"] == (
        "Completing a Grow Run requires permission to control this growspace"
    )
    assert result["refusal"]["current_revision"] == 1
    assert result["refusal"]["active_run"]["run_id"] == run.run_id
    assert coordinator.grow_runs.active_run(growspace_id) is not None


async def test_an_ordinary_user_may_complete(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    client = await hass_ws_client(hass, await _token_for(hass, GROUP_ID_USER))
    result = await _ws(
        client,
        {
            "type": WS_TYPE_COMPLETE_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
            "expected_run_revision": 1,
            "acknowledged_warnings": [],
        },
    )
    assert result["outcome"] == "completed"


@pytest.mark.parametrize(
    "message",
    [
        {"type": WS_TYPE_PREVIEW_GROW_RUN_COMPLETION, "growspace_id": "nowhere"},
        {
            "type": WS_TYPE_COMPLETE_GROW_RUN,
            "growspace_id": "nowhere",
            "run_id": "r",
            "expected_run_revision": 0,
            "acknowledged_warnings": [],
        },
        {
            "type": WS_TYPE_COMPLETE_GROW_RUN,
            "growspace_id": "nowhere",
            "run_id": "r",
            "expected_run_revision": 0,
            "acknowledged_warnings": ["everything"],
        },
    ],
)
async def test_completion_commands_validate_their_input(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    message: dict[str, Any],
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(message)
    assert not (await client.receive_json())["success"]


async def test_a_failed_completion_write_changes_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    run = await _started(hass, coordinator, growspace_id)
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    with (
        patch.object(
            coordinator.grow_runs._store, "async_save", side_effect=OSError("disk")
        ),
        pytest.raises(OSError),
    ):
        await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    ledger = coordinator.grow_runs.ledger(growspace_id)
    assert ledger.revision == 1
    assert ledger.active_run == run
    assert events == []


async def test_a_stale_completion_is_refused_with_the_current_revision(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    with pytest.raises(RunRevisionConflict) as refused:
        await _complete_as_admin(hass, coordinator, growspace_id, run.run_id, 0)
    assert refused.value.current_revision == 1
