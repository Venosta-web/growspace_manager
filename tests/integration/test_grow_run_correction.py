"""Reopening and discarding Grow Runs end to end: WebSocket, store, restart (#917)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.domain.grow_run import RunStatus
from custom_components.growspace_manager.grow_run_store import (
    EVENT_GROW_RUN_LIFECYCLE,
    GrowRunStore,
)
from custom_components.growspace_manager.services.grow_runs import (
    async_discard_grow_run,
)
from custom_components.growspace_manager.websocket.grow_runs import (
    WS_TYPE_DISCARD_GROW_RUN,
    WS_TYPE_FINALIZE_GROW_RUN,
    WS_TYPE_GET_GROW_RUN,
    WS_TYPE_LIST_GROW_RUNS,
    WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
    WS_TYPE_REOPEN_GROW_RUN,
)
from homeassistant.auth.const import GROUP_ID_USER
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry, async_capture_events
from tests.integration.test_grow_run_finalization import _harvested_and_completed
from tests.integration.test_grow_runs import (
    _admin,
    _sensor,
    _start,
    _tent,
    _token_for,
    _ws,
)


def _reopen(growspace_id: str, run_id: str, revision: int, reason: str) -> dict:
    return {
        "type": WS_TYPE_REOPEN_GROW_RUN,
        "growspace_id": growspace_id,
        "run_id": run_id,
        "expected_run_revision": revision,
        "reason": reason,
    }


def _discard(growspace_id: str, run_id: str, revision: int, **extra: Any) -> dict:
    return {
        "type": WS_TYPE_DISCARD_GROW_RUN,
        "growspace_id": growspace_id,
        "run_id": run_id,
        "expected_run_revision": revision,
        **extra,
    }


async def _finalized(
    hass: HomeAssistant, init_integration: MockConfigEntry, client: Any
) -> tuple[Any, str, list[str], str, dict]:
    """A Run finalized while p1 still waited for its dry weight."""
    coordinator, growspace_id, plant_ids, run = await _harvested_and_completed(
        hass, init_integration
    )
    finalized = await _ws(
        client,
        {
            "type": WS_TYPE_FINALIZE_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
            "expected_run_revision": 2,
            "acknowledged_warnings": ["incomplete_snapshot"],
        },
    )
    assert finalized["outcome"] == "finalized"
    return coordinator, growspace_id, plant_ids, run.run_id, finalized["snapshot"]


async def test_an_administrator_reopens_corrects_and_finalizes_a_run_again(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Finalized → reopened with a reason → corrected → finalized, both kept."""
    client = await hass_ws_client(hass)
    coordinator, growspace_id, plant_ids, run_id, first = await _finalized(
        hass, init_integration, client
    )
    assert first["complete"] is False
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    log = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

    # Frozen: a weight recorded now does not reach the Finalized Run.
    await coordinator.services.plants.update_harvest_metrics(
        plant_ids[0], dry_weight=42.5
    )
    frozen = coordinator.grow_runs.ledger(growspace_id).runs[0]
    assert frozen.harvest_outcomes[0].metrics["dry_weight"] is None

    reopened = await _ws(
        client, _reopen(growspace_id, run_id, 3, "  Dry weight came in late ")
    )
    assert reopened["outcome"] == "reopened"
    assert reopened["run_revision"] == 4
    assert reopened["run"]["status"] == "completed"
    assert reopened["run"]["metrics_state"] == "pending"
    assert [event.data["command"] for event in events] == ["reopen"]
    assert events[0].data["status"] == "completed"
    assert events[0].data["reason"] == "Dry weight came in late"
    assert log[-1].data["message"].endswith(": Dry weight came in late")
    assert log[-1].data["message"].startswith("Run #1 reopened by HA user ")

    # Reopening never resumes the Run: the boundary and intervals stay closed.
    run = coordinator.grow_runs.ledger(growspace_id).runs[0]
    assert run.completed_at == frozen.completed_at
    assert run.participations == frozen.participations

    # The correction reaches the preview, and the new snapshot is complete.
    preview = await _ws(
        client,
        {
            "type": WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
            "growspace_id": growspace_id,
            "run_id": run_id,
        },
    )
    assert preview["preview"]["warnings"] == []
    again = await _ws(
        client,
        {
            "type": WS_TYPE_FINALIZE_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run_id,
            "expected_run_revision": 4,
            "acknowledged_warnings": [],
        },
    )
    assert again["run_revision"] == 5
    assert again["snapshot"]["metrics"][0]["value"] == 42.5

    details = await _ws(
        client,
        {"type": WS_TYPE_GET_GROW_RUN, "growspace_id": growspace_id, "run_id": run_id},
    )
    assert details["run"]["snapshot"] == again["snapshot"]
    assert details["run"]["superseded_snapshots"] == [
        {"finalized_revision": 3, "superseded_revision": 4, "snapshot": first}
    ]
    reopen_entry = details["run"]["audit"][-2]
    assert reopen_entry["command"] == "reopen"
    assert reopen_entry["reason"] == "Dry weight came in late"
    assert (reopen_entry["prior_revision"], reopen_entry["resulting_revision"]) == (
        3,
        4,
    )
    assert reopen_entry["actor_user_id"]

    # Both snapshots survive a restart.
    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    stored = reloaded.ledger(growspace_id).runs[0]
    assert stored.status is RunStatus.FINALIZED
    assert stored.snapshot is not None
    assert stored.snapshot.as_dict() == again["snapshot"]
    assert [row.snapshot.as_dict() for row in stored.superseded_snapshots] == [first]


async def test_reopening_refuses_what_it_should_and_says_where_the_ledger_is(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    client = await hass_ws_client(hass)
    coordinator, growspace_id, _, run_id, _ = await _finalized(
        hass, init_integration, client
    )

    stale = await _ws(client, _reopen(growspace_id, run_id, 2, "Late weight"))
    assert stale["refusal"]["code"] == "grow_run.revision_conflict"
    assert stale["refusal"]["current_revision"] == 3
    blank = await _ws(client, _reopen(growspace_id, run_id, 3, "   "))
    assert blank["refusal"]["code"] == "grow_run.reason_required"
    missing = await _ws(client, _reopen(growspace_id, "nope", 3, "Late weight"))
    assert missing["refusal"]["code"] == "grow_run.not_found"
    assert coordinator.grow_runs.ledger(growspace_id).runs[0].status is (
        RunStatus.FINALIZED
    )

    await _ws(client, _reopen(growspace_id, run_id, 3, "Late weight"))
    twice = await _ws(client, _reopen(growspace_id, run_id, 4, "Late weight"))
    assert twice["refusal"]["code"] == "grow_run.not_finalized"


@pytest.mark.parametrize("group", ["user", "read_only"])
async def test_only_an_administrator_may_reopen(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
    group: str,
) -> None:
    admin = await hass_ws_client(hass)
    coordinator, growspace_id, _, run_id, _ = await _finalized(
        hass, init_integration, admin
    )
    token = (
        await _token_for(hass, GROUP_ID_USER)
        if group == "user"
        else hass_read_only_access_token
    )
    client = await hass_ws_client(hass, token)
    refused = await _ws(client, _reopen(growspace_id, run_id, 3, "Late weight"))
    assert refused["refusal"] == {
        "code": "grow_run.not_authorized",
        "message": "Reopening a Grow Run requires a Home Assistant administrator",
        "current_revision": 3,
        "active_run": None,
        "reasons": [],
    }
    assert coordinator.grow_runs.ledger(growspace_id).runs[0].status is (
        RunStatus.FINALIZED
    )


async def test_a_grower_backs_out_of_a_run_that_recorded_nothing(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Start → discard → as if it never started; its number stays spent."""
    coordinator, growspace_id, _ = await _tent(init_integration)
    covered_since = coordinator.grow_runs.unattributed(growspace_id).covered_since
    assert covered_since is not None
    # An ordinary user: backing out of a start is a controller's command.
    client = await hass_ws_client(hass, await _token_for(hass, GROUP_ID_USER))
    started = await _start(client, growspace_id, 0)
    run_id = started["active_run"]["run_id"]
    assert coordinator.grow_runs.unattributed(growspace_id).covered_since is None
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    log = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

    result = await _ws(
        client, _discard(growspace_id, run_id, 1, reason="Wrong growspace")
    )

    assert result == {
        "outcome": "discarded",
        "run_revision": 2,
        "run_id": run_id,
        "sequence_number": 1,
    }
    await hass.async_block_till_done()
    sensor = _sensor(hass, growspace_id)
    assert sensor.state == "none"
    assert sensor.attributes["run_revision"] == 2
    listed = await _ws(
        client, {"type": WS_TYPE_LIST_GROW_RUNS, "growspace_id": growspace_id}
    )
    assert listed["runs"] == []
    gone = await _ws(
        client,
        {"type": WS_TYPE_GET_GROW_RUN, "growspace_id": growspace_id, "run_id": run_id},
    )
    assert gone == {"outcome": "not_found"}
    assert events[0].data["command"] == "discard"
    assert events[0].data["status"] == "discarded"
    assert events[0].data["reason"] == "Wrong growspace"
    assert log[-1].data["message"].startswith("Run #1 discarded by HA user ")

    # Coverage resumes from where the start ended it, in the same write.
    activity = coordinator.grow_runs.unattributed(growspace_id)
    assert activity.covered_since == covered_since

    # The audit trail and the spent number survive a restart.
    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    ledger = reloaded.ledger(growspace_id)
    assert ledger.runs == ()
    (discarded,) = ledger.discarded
    assert [entry.command.value for entry in discarded.audit] == ["start", "discard"]
    assert discarded.audit[-1].reason == "Wrong growspace"
    assert reloaded.unattributed(growspace_id).covered_since == covered_since

    again = await _start(client, growspace_id, 2)
    assert again["active_run"]["sequence_number"] == 2


async def test_a_run_with_activity_refuses_a_discard_and_says_what_it_recorded(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=1)
    client = await hass_ws_client(hass)
    started = await _start(client, growspace_id, 0)
    run_id = started["active_run"]["run_id"]
    freezer.tick(60)
    await coordinator.services.plants.add_plant(
        growspace_id=growspace_id, strain="OG Kush", row=2, col=1
    )

    refused = await _ws(client, _discard(growspace_id, run_id, 1))

    assert refused["refusal"]["code"] == "grow_run.has_activity"
    assert refused["refusal"]["reasons"] == ["activity_facts", "participants_changed"]
    assert refused["refusal"]["active_run"]["run_id"] == run_id
    assert coordinator.grow_runs.active_run(growspace_id) is not None

    stale = await _ws(client, _discard(growspace_id, run_id, 0))
    assert stale["refusal"]["code"] == "grow_run.revision_conflict"


async def test_a_read_only_user_may_not_discard(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    started = await _start(await hass_ws_client(hass), growspace_id, 0)
    client = await hass_ws_client(hass, hass_read_only_access_token)
    refused = await _ws(
        client, _discard(growspace_id, started["active_run"]["run_id"], 1)
    )
    assert refused["refusal"]["code"] == "grow_run.not_authorized"
    assert refused["refusal"]["message"] == (
        "Discarding a Grow Run requires permission to control this growspace"
    )
    assert (
        refused["refusal"]["active_run"]["run_id"] == (started["active_run"]["run_id"])
    )


async def test_a_failed_discard_write_changes_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry, hass_ws_client: Any
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    started = await _start(await hass_ws_client(hass), growspace_id, 0)
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    with (
        patch.object(
            coordinator.grow_runs._store, "async_save", side_effect=OSError("disk")
        ),
        pytest.raises(OSError),
    ):
        await async_discard_grow_run(
            hass,
            coordinator,
            growspace_id=growspace_id,
            run_id=started["active_run"]["run_id"],
            expected_revision=1,
            reason=None,
            user=await _admin(hass),
        )
    ledger = coordinator.grow_runs.ledger(growspace_id)
    assert ledger.revision == 1
    assert ledger.active_run is not None
    assert ledger.discarded == ()
    assert coordinator.grow_runs.unattributed(growspace_id).covered_since is None
    assert events == []


@pytest.mark.parametrize(
    "message",
    [
        {
            "type": WS_TYPE_REOPEN_GROW_RUN,
            "growspace_id": "g",
            "run_id": "r",
            "expected_run_revision": 0,
        },
        _reopen("g", "r", 0, "x" * 2001),
        _discard("g", "r", -1),
        _discard("g", "", 0),
    ],
)
async def test_correction_commands_validate_their_input(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    message: dict[str, Any],
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(message)
    assert not (await client.receive_json())["success"]
