"""Finalizing a Grow Run end to end: WebSocket, store, restart, deletion (#673)."""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.const import (
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    PlantStage,
)
from custom_components.growspace_manager.domain.grow_run import (
    RunMetadata,
    RunRevisionConflict,
    RunStatus,
    export_run,
)
from custom_components.growspace_manager.grow_run_store import (
    EVENT_GROW_RUN_LIFECYCLE,
    GrowRunStore,
)
from custom_components.growspace_manager.services.grow_runs import (
    async_finalize_grow_run,
    async_start_grow_run,
)
from custom_components.growspace_manager.websocket.grow_runs import (
    WS_TYPE_COMPARE_GROW_RUNS,
    WS_TYPE_EXPORT_GROW_RUN,
    WS_TYPE_FINALIZE_GROW_RUN,
    WS_TYPE_GET_GROW_RUN,
    WS_TYPE_LIST_GROW_RUNS,
    WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
    WS_TYPE_UPDATE_GROW_RUN_METADATA,
)
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
import homeassistant.util.dt as dt_util
from tests.common import MockConfigEntry, async_capture_events
from tests.integration.test_grow_runs import (
    _admin,
    _complete_as_admin,
    _started,
    _tent,
    _ws,
)


async def _flowering_tent(init_integration: MockConfigEntry) -> tuple[Any, str, list]:
    """A growspace with two flowering Plants and an Active Run over them."""
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    plant_ids = [
        (
            await coordinator.services.plants.add_plant(
                growspace_id=growspace_id,
                strain="OG Kush",
                phenotype="Pheno #1",
                row=1,
                col=col,
                stage=PlantStage.FLOWER,
                flower_start=dt_util.utcnow(),
            )
        ).plant_id
        for col in (1, 2)
    ]
    return coordinator, growspace_id, plant_ids


async def _harvested_and_completed(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> tuple[Any, str, list[str], Any]:
    """p1 entered dry inside the Run and awaits its dry weight; the Run completed."""
    coordinator, growspace_id, plant_ids = await _flowering_tent(init_integration)
    run = await _started(hass, coordinator, growspace_id)
    await coordinator.services.plants.transition_plant_stage(
        plant_ids[0], PlantStage.DRY
    )
    await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    return coordinator, growspace_id, plant_ids, run


def _finalize_message(growspace_id: str, run_id: str, revision: int, ack: list):
    return {
        "type": WS_TYPE_FINALIZE_GROW_RUN,
        "growspace_id": growspace_id,
        "run_id": run_id,
        "expected_run_revision": revision,
        "acknowledged_warnings": ack,
    }


async def test_a_grower_finalizes_a_run_that_then_outlives_its_sources(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Preview → refused unacknowledged → complete → frozen after deletions."""
    coordinator, growspace_id, plant_ids, run = await _harvested_and_completed(
        hass, init_integration
    )
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    client = await hass_ws_client(hass)

    listed = await _ws(
        client, {"type": WS_TYPE_LIST_GROW_RUNS, "growspace_id": growspace_id}
    )
    assert listed["outcome"] == "listed"
    assert listed["run_revision"] == 2
    assert [(row["run_id"], row["status"]) for row in listed["runs"]] == [
        (run.run_id, "completed")
    ]

    # p1 still waits for its dry weight: the snapshot would freeze without it.
    preview = await _ws(
        client,
        {
            "type": WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
        },
    )
    assert preview["outcome"] == "preview"
    assert preview["preview"]["warnings"] == ["incomplete_snapshot"]
    snapshot = preview["preview"]["snapshot"]
    assert snapshot["metrics"][0]["value"] is None
    assert snapshot["metrics"][0]["missing"] == [
        {"kind": "dry_weight", "plant_id": plant_ids[0]}
    ]
    refused = await _ws(client, _finalize_message(growspace_id, run.run_id, 2, []))
    assert refused["refusal"]["code"] == "grow_run.acknowledgement_required"
    assert refused["refusal"]["current_revision"] == 2

    # The weight arrives while the Run is Completed; now nothing is missing.
    await coordinator.services.plants.update_harvest_metrics(
        plant_ids[0], dry_weight=42.5
    )
    preview = await _ws(
        client,
        {
            "type": WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
        },
    )
    assert preview["preview"]["warnings"] == []
    result = await _ws(client, _finalize_message(growspace_id, run.run_id, 2, []))
    assert result["outcome"] == "finalized"
    assert result["run_revision"] == 3
    assert result["run"]["status"] == "finalized"
    assert result["run"]["metrics_state"] == "frozen"
    exported = await _ws(
        client,
        {
            "type": WS_TYPE_EXPORT_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
        },
    )
    assert exported["outcome"] == "exported"
    assert exported["document"]["snapshot"] == result["snapshot"]
    frozen = result["snapshot"]
    assert frozen["complete"] is True
    assert frozen["growspace_name"] == "Run Tent"
    assert frozen["counts"]["participants"] == 2
    assert frozen["counts"]["harvest_source_plants"] == 1
    assert frozen["metrics"][0] == {
        "metric": "yield",
        "unit": "g",
        "definition_version": 1,
        "value": 42.5,
        "complete": True,
        "missing": [],
    }
    assert frozen["metrics"][1]["value"] == 42.5
    local_day = dt_util.now().date().isoformat()
    assert frozen["harvest_window"] == {"first": local_day, "last": local_day}
    assert {row["strain_name"] for row in frozen["participants"]} == {"OG Kush"}
    assert {row["phenotype_name"] for row in frozen["participants"]} == {"Pheno #1"}
    assert all(row["plant_name"] for row in frozen["participants"])
    assert [event.data["command"] for event in events] == ["finalize"]
    assert events[0].data["status"] == "finalized"

    # Sources change and disappear; the snapshot does not move.
    await coordinator.services.plants.update_harvest_metrics(
        plant_ids[0], dry_weight=999
    )
    # A Harvest Source Plant of a Finalized Run needs no outcome to go: the
    # Run's outcome is already frozen.
    await coordinator.services.plants.async_remove_plant(plant_ids[0])
    await coordinator.services.plants.async_remove_plant(plant_ids[1])
    await coordinator.services.growspaces.remove_growspace(growspace_id)
    assert growspace_id not in coordinator.growspaces
    assert (
        await _ws(
            client,
            {
                "type": WS_TYPE_EXPORT_GROW_RUN,
                "growspace_id": growspace_id,
                "run_id": run.run_id,
            },
        )
        == exported
    )

    details = await _ws(
        client,
        {
            "type": WS_TYPE_GET_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
        },
    )
    assert details["outcome"] == "found"
    assert details["run"]["snapshot"] == frozen
    assert details["run"]["harvest_outcomes"][0]["metrics"]["dry_weight"] == 42.5
    assert details["run"]["audit"][-1]["command"] == "finalize"

    # And it reads back the same after a restart.
    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    stored = reloaded.ledger(growspace_id).runs[0]
    assert stored.status is RunStatus.FINALIZED
    assert stored.snapshot is not None
    assert stored.snapshot.as_dict() == frozen
    assert export_run(reloaded.ledger(growspace_id), run.run_id) == exported["document"]


async def test_run_metadata_stays_editable_and_audited_after_finalization(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _, run = await _harvested_and_completed(
        hass, init_integration
    )
    finalized, revision = await async_finalize_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        run_id=run.run_id,
        expected_revision=2,
        acknowledged=["incomplete_snapshot"],
        user=await _admin(hass),
    )
    log = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    client = await hass_ws_client(hass)
    message = {
        "type": WS_TYPE_UPDATE_GROW_RUN_METADATA,
        "growspace_id": growspace_id,
        "run_id": run.run_id,
        "expected_run_revision": revision,
    }

    result = await _ws(
        client, {**message, "label": "Best run yet", "tags": ["organic", "indoor"]}
    )
    assert result["outcome"] == "updated"
    assert result["run_revision"] == revision + 1
    assert result["run"]["label"] == "Best run yet"
    assert result["run"]["status"] == "finalized"

    ledger = coordinator.grow_runs.ledger(growspace_id)
    edited = ledger.runs[0]
    assert edited.snapshot == finalized.snapshot
    assert edited.metadata.goals is None
    assert edited.audit[-1].changed_fields == ("label", "tags")
    assert log[-1].data["message"].startswith("Run #1 described by HA user ")

    # Naming only what is already there changes nothing and moves nothing.
    unchanged = await _ws(
        client,
        {**message, "expected_run_revision": revision + 1, "label": "Best run yet"},
    )
    assert unchanged["run_revision"] == revision + 1
    assert len(coordinator.grow_runs.ledger(growspace_id).runs[0].audit) == len(
        edited.audit
    )

    stale = await _ws(client, {**message, "notes": "late"})
    assert stale["refusal"]["code"] == "grow_run.revision_conflict"
    missing = await _ws(
        client,
        {**message, "expected_run_revision": revision + 1, "run_id": "nope"},
    )
    assert missing["refusal"]["code"] == "grow_run.not_found"


async def test_only_a_completed_run_can_be_previewed_for_finalization(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    run = await _started(hass, coordinator, growspace_id)
    client = await hass_ws_client(hass)
    message = {
        "type": WS_TYPE_PREVIEW_GROW_RUN_FINALIZATION,
        "growspace_id": growspace_id,
        "run_id": run.run_id,
    }
    active = await _ws(client, message)
    assert active["refusal"]["code"] == "grow_run.not_completed"
    assert active["refusal"]["active_run"]["run_id"] == run.run_id
    unknown = await _ws(client, {**message, "run_id": "nope"})
    assert unknown["refusal"]["code"] == "grow_run.not_found"
    refused = await _ws(client, _finalize_message(growspace_id, run.run_id, 1, []))
    assert refused["refusal"]["code"] == "grow_run.not_completed"


async def test_a_read_only_user_may_neither_finalize_nor_describe(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    hass_read_only_access_token: str,
) -> None:
    coordinator, growspace_id, _, run = await _harvested_and_completed(
        hass, init_integration
    )
    client = await hass_ws_client(hass, hass_read_only_access_token)
    finalize = await _ws(
        client,
        _finalize_message(growspace_id, run.run_id, 2, ["incomplete_snapshot"]),
    )
    assert finalize["refusal"]["code"] == "grow_run.not_authorized"
    assert finalize["refusal"]["message"] == (
        "Finalizing a Grow Run requires permission to control this growspace"
    )
    assert finalize["refusal"]["current_revision"] == 2
    describe = await _ws(
        client,
        {
            "type": WS_TYPE_UPDATE_GROW_RUN_METADATA,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
            "expected_run_revision": 2,
            "label": "Mine",
        },
    )
    assert describe["refusal"]["code"] == "grow_run.not_authorized"
    assert coordinator.grow_runs.ledger(growspace_id).runs[0].status is (
        RunStatus.COMPLETED
    )


@pytest.mark.parametrize(
    "message",
    [
        {
            "type": WS_TYPE_FINALIZE_GROW_RUN,
            "growspace_id": "g",
            "run_id": "r",
            "expected_run_revision": 0,
            "acknowledged_warnings": ["plants_present"],
        },
        {
            "type": WS_TYPE_UPDATE_GROW_RUN_METADATA,
            "growspace_id": "g",
            "run_id": "r",
            "expected_run_revision": 0,
            "tags": ["x"] * 21,
        },
        {"type": WS_TYPE_LIST_GROW_RUNS, "growspace_id": ""},
    ],
)
async def test_finalization_commands_validate_their_input(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    message: dict[str, Any],
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(message)
    assert not (await client.receive_json())["success"]


async def test_an_unreadable_history_lists_nothing_and_says_why(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    coordinator.grow_runs.unreadable = True
    client = await hass_ws_client(hass)
    result = await _ws(
        client, {"type": WS_TYPE_LIST_GROW_RUNS, "growspace_id": growspace_id}
    )
    assert result["refusal"]["code"] == "grow_run.store_unreadable"


async def test_a_failed_finalization_write_changes_nothing(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _, run = await _harvested_and_completed(
        hass, init_integration
    )
    events = async_capture_events(hass, EVENT_GROW_RUN_LIFECYCLE)
    with (
        patch.object(
            coordinator.grow_runs._store, "async_save", side_effect=OSError("disk")
        ),
        pytest.raises(OSError),
    ):
        await async_finalize_grow_run(
            hass,
            coordinator,
            growspace_id=growspace_id,
            run_id=run.run_id,
            expected_revision=2,
            acknowledged=["incomplete_snapshot"],
            user=await _admin(hass),
        )
    ledger = coordinator.grow_runs.ledger(growspace_id)
    assert ledger.revision == 2
    assert ledger.runs[0].status is RunStatus.COMPLETED
    assert events == []

    with pytest.raises(RunRevisionConflict):
        await async_finalize_grow_run(
            hass,
            coordinator,
            growspace_id=growspace_id,
            run_id=run.run_id,
            expected_revision=1,
            acknowledged=["incomplete_snapshot"],
            user=await _admin(hass),
        )


async def test_a_participant_is_named_as_its_entity_and_kept_after_deletion(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    """A grower's rename reaches the Run; the Plant's deletion does not erase it."""
    coordinator, growspace_id, plant_ids = await _flowering_tent(init_integration)
    run = await _started(hass, coordinator, growspace_id)
    registry = er.async_get(hass)
    entity_id = registry.async_get_entity_id(
        Platform.SENSOR, DOMAIN, f"{DOMAIN}_{plant_ids[1]}"
    )
    assert entity_id is not None
    registry.async_update_entity(entity_id, name="Mother Ann")
    await coordinator.async_commit()

    await coordinator.services.plants.async_remove_plant(plant_ids[1])
    await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    identities = {
        row.plant_id: row
        for row in coordinator.grow_runs.ledger(growspace_id)
        .runs[0]
        .participant_identities
    }
    assert identities[plant_ids[1]].plant_name == "Mother Ann"
    assert identities[plant_ids[1]].strain_name == "OG Kush"
    assert identities[plant_ids[0]].plant_name == "OG Kush (1,1)"


async def test_a_failed_identity_refresh_never_fails_the_cultivation_change(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    await _started(hass, coordinator, growspace_id)
    with patch.object(
        coordinator.grow_runs,
        "async_project_identities",
        side_effect=OSError("disk full"),
    ):
        await coordinator.services.plants.add_plant(
            growspace_id=growspace_id, strain="OG Kush", row=1, col=1
        )
    assert "Run Participant identities were not refreshed" in caplog.text


async def test_a_grower_compares_the_two_newest_finalized_runs(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Run #1 weighed in, Run #2 did not: the Yield row is missing, not zero (#675)."""
    coordinator, growspace_id, plant_ids, first = await _harvested_and_completed(
        hass, init_integration
    )
    await coordinator.services.plants.update_harvest_metrics(
        plant_ids[0], dry_weight=42.5
    )
    client = await hass_ws_client(hass)
    compare = {"type": WS_TYPE_COMPARE_GROW_RUNS, "growspace_id": growspace_id}

    # One Run, and not yet Finalized: nothing to compare, and the details
    # already show its Pending Yield.
    details = await _ws(
        client,
        {
            "type": WS_TYPE_GET_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": first.run_id,
        },
    )
    assert details["run"]["metrics_state"] == "pending"
    assert details["run"]["metrics"][0]["value"] == 42.5
    assert {row["plant_id"] for row in details["run"]["participant_identities"]} == (
        set(plant_ids)
    )
    refused = await _ws(client, compare)
    assert refused["refusal"]["code"] == "grow_run.insufficient_history"

    await _ws(client, _finalize_message(growspace_id, first.run_id, 2, []))
    second, revision = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=3,
        metadata=RunMetadata.create(label="Winter"),
        user=await _admin(hass),
    )
    await _complete_as_admin(
        hass, coordinator, growspace_id, second.run_id, revision=revision
    )
    await _ws(
        client,
        _finalize_message(
            growspace_id, second.run_id, revision + 1, ["incomplete_snapshot"]
        ),
    )

    result = await _ws(client, compare)
    assert result["outcome"] == "compared"
    assert [row["sequence_number"] for row in result["finalized"]] == [2, 1]
    comparison = result["comparison"]
    assert comparison["earlier"]["run"]["run_id"] == first.run_id
    assert comparison["later"]["run"]["run_id"] == second.run_id
    assert comparison["later"]["snapshot"]["counts"]["harvest_source_plants"] == 0
    yield_row = comparison["metrics"][0]
    assert yield_row["metric"] == "yield"
    assert yield_row["state"] == "missing"
    assert yield_row["direction"] is None
    assert yield_row["earlier"]["value"] == 42.5

    # Named explicitly, in either order, it is the same comparison.
    named = await _ws(client, {**compare, "run_ids": [second.run_id, first.run_id]})
    assert named["comparison"] == comparison
    same = await _ws(client, {**compare, "run_ids": [first.run_id, first.run_id]})
    assert same["refusal"]["code"] == "grow_run.same_run"


@pytest.mark.parametrize(
    "extra",
    [{"run_ids": ["only-one"]}, {"run_ids": ["a", "b", "c"]}, {"run_ids": ["", "b"]}],
)
async def test_a_comparison_names_exactly_two_runs(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    extra: dict[str, Any],
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {"type": WS_TYPE_COMPARE_GROW_RUNS, "growspace_id": "tent", **extra}
    )
    assert not (await client.receive_json())["success"]


async def test_an_unreadable_history_compares_nothing_and_says_why(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    coordinator.grow_runs.unreadable = True
    client = await hass_ws_client(hass)
    result = await _ws(
        client, {"type": WS_TYPE_COMPARE_GROW_RUNS, "growspace_id": growspace_id}
    )
    assert result["refusal"]["code"] == "grow_run.store_unreadable"


async def test_export_refuses_unfrozen_missing_and_unreadable_runs(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    client = await hass_ws_client(hass)
    message = {
        "type": WS_TYPE_EXPORT_GROW_RUN,
        "growspace_id": growspace_id,
        "run_id": run.run_id,
    }
    active = await _ws(client, message)
    assert active["refusal"]["code"] == "grow_run.not_finalized"
    assert active["refusal"]["active_run"]["run_id"] == run.run_id
    await _complete_as_admin(hass, coordinator, growspace_id, run.run_id, revision=1)
    completed = await _ws(client, message)
    assert completed["refusal"]["code"] == "grow_run.not_finalized"
    assert completed["refusal"]["current_revision"] == 2
    unknown = await _ws(client, {**message, "run_id": "missing"})
    assert unknown["refusal"]["code"] == "grow_run.not_found"
    coordinator.grow_runs.unreadable = True
    unreadable = await _ws(client, message)
    assert unreadable["refusal"]["code"] == "grow_run.store_unreadable"
    await client.send_json_auto_id({**message, "run_id": ""})
    assert not (await client.receive_json())["success"]
