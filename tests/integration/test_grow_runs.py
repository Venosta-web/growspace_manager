"""Starting a Grow Run end to end: WebSocket, store, sensor, authority (#668)."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.domain.grow_run import (
    RunMetadata,
    RunStoreUnreadable,
)
from custom_components.growspace_manager.grow_run_store import (
    EVENT_GROW_RUN_LIFECYCLE,
    GrowRunStore,
)
from custom_components.growspace_manager.services.grow_runs import (
    active_run_unique_id,
    async_start_grow_run,
    require_controller,
)
from custom_components.growspace_manager.websocket.grow_runs import (
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
