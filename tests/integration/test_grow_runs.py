"""Starting a Grow Run end to end: WebSocket, store, sensor, authority (#668)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import CLIENT_ID, MockUser
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.const import DOMAIN, PlantStage
from custom_components.growspace_manager.domain.grow_run import (
    PlantMovementFact,
    RunMetadata,
    RunStatus,
    RunStoreUnreadable,
)
from custom_components.growspace_manager.exceptions import ValidationChangeError
from custom_components.growspace_manager.grow_run_store import (
    EVENT_GROW_RUN_LIFECYCLE,
    GrowRunStore,
)
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.services.grow_runs import (
    active_run_unique_id,
    async_start_grow_run,
    require_controller,
)
from custom_components.growspace_manager.websocket.grow_runs import (
    WS_TYPE_GET_GROW_RUN,
    WS_TYPE_START_GROW_RUN,
)
from homeassistant.auth.const import GROUP_ID_ADMIN, GROUP_ID_USER
from homeassistant.const import Platform
from homeassistant.core import Event, HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import entity_registry as er
import homeassistant.util.dt as dt_util
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
        await coordinator._async_project_activity()
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

    await coordinator._async_project_activity()
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


async def test_staged_harvest_keeps_late_outcomes_on_source_run(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    plant = await coordinator.services.plants.add_plant(
        growspace_id=growspace_id,
        strain="OG Kush",
        row=1,
        col=1,
        stage=PlantStage.FLOWER,
        flower_start=dt_util.utcnow(),
    )
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    await coordinator.services.plants.transition_plant_stage(
        plant.plant_id, PlantStage.DRY
    )
    harvested = coordinator.plants[plant.plant_id]
    assert harvested.harvest_source_growspace_id == growspace_id
    assert harvested.harvest_source_run_id == run.run_id
    source = coordinator.grow_runs.ledger(growspace_id).runs[0]
    assert source.harvest_outcomes[0].state == "pending"
    assert source.harvest_outcomes[0].metrics["dry_weight"] is None

    # #671 will supply the completion command. The source identity and
    # projection must already work after its state change.
    async with coordinator.grow_runs.lock:
        ledger = coordinator.grow_runs.ledger(growspace_id)
        await coordinator.grow_runs.async_commit(
            replace(ledger, runs=(replace(ledger.runs[0], status=RunStatus.COMPLETED),))
        )
    assert coordinator.grow_runs.active_run(growspace_id) is None

    await coordinator.services.plants.update_harvest_metrics(
        plant.plant_id,
        wet_weight=120,
        dry_weight=30,
        trim_weight=5,
        thc_percentage=21,
        terpene_profile="myrcene",
    )
    source = coordinator.grow_runs.ledger(growspace_id).runs[0]
    assert source.harvest_outcomes[0].state == "recorded"
    assert source.harvest_outcomes[0].metrics["dry_weight"] == 30
    assert source.harvest_outcomes[0].metrics["terpene_profile"] == "myrcene"

    with pytest.raises(ServiceValidationError, match="Choose No Usable Yield"):
        await coordinator.services.plants.remove_plant(plant.plant_id)
    with patch.object(
        coordinator.grow_runs,
        "async_project_harvest_outcomes",
        side_effect=OSError("disk full"),
    ):
        with pytest.raises(ServiceValidationError, match="snapshot was not saved"):
            await coordinator.services.plants.remove_plant(
                plant.plant_id, harvest_outcome_choice="incomplete"
            )
    assert plant.plant_id in coordinator.plants
    await coordinator.services.plants.async_remove_plant(
        plant.plant_id, harvest_outcome_choice="incomplete"
    )
    source = coordinator.grow_runs.ledger(growspace_id).runs[0]
    assert source.harvest_outcomes[0].state == "incomplete"
    assert source.harvest_outcomes[0].metrics["dry_weight"] is None
    assert source.harvest_outcomes[0].strain == "OG Kush"
    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    assert (
        reloaded.ledger(growspace_id).runs[0].harvest_outcomes
        == source.harvest_outcomes
    )


async def test_no_active_run_is_explicitly_unattributed(
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    plant = await coordinator.services.plants.add_plant(
        growspace_id=growspace_id,
        strain="OG Kush",
        row=1,
        col=1,
        stage=PlantStage.FLOWER,
        flower_start=dt_util.utcnow(),
    )
    await coordinator.services.plants.transition_plant_stage(
        plant.plant_id, PlantStage.DRY
    )
    assert plant.harvest_source_growspace_id == growspace_id
    assert plant.harvest_source_run_id is None
    run, _ = await async_start_grow_run(
        coordinator.hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(coordinator.hass),
    )
    await coordinator.services.plants.update_harvest_metrics(
        plant.plant_id, dry_weight=20
    )
    assert plant.harvest_source_run_id is None
    assert run.harvest_outcomes == ()


async def test_lifecycle_editor_captures_source_and_raw_deletion_is_refused(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    plant = await coordinator.services.plants.add_plant(
        growspace_id=growspace_id,
        strain="OG Kush",
        row=1,
        col=1,
        stage=PlantStage.FLOWER,
        flower_start=dt_util.utcnow(),
    )
    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    await coordinator.services.plants.update_plant(plant.plant_id, stage="dry")
    assert plant.harvest_source_run_id == run.run_id
    assert (
        coordinator.grow_runs.ledger(growspace_id).runs[0].harvest_outcomes[0].plant_id
        == plant.plant_id
    )
    with pytest.raises(ValidationChangeError, match="explicit outcome"):
        await coordinator._plant_manager.remove_plant(plant.plant_id)
    assert plant.plant_id in coordinator.plants


async def test_zero_weight_at_dry_entry_and_invalid_outcome_are_refused(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    plant = await coordinator.services.plants.add_plant(
        growspace_id=growspace_id,
        strain="OG Kush",
        row=1,
        col=1,
        stage=PlantStage.FLOWER,
        flower_start=dt_util.utcnow(),
    )
    with pytest.raises(ServiceValidationError, match="no harvest source"):
        await coordinator.services.plants.set_harvest_outcome(
            plant.plant_id, "incomplete"
        )
    await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    with pytest.raises(ValidationChangeError, match="No Usable Yield"):
        await coordinator.services.plants.transition_plant(plant.plant_id, dry_weight=0)
    assert plant.harvest_source_run_id is None
    await coordinator.services.plants.transition_plant_stage(
        plant.plant_id, PlantStage.DRY
    )
    with pytest.raises(ServiceValidationError, match="Unknown harvest outcome"):
        await coordinator.services.plants.set_harvest_outcome(
            plant.plant_id, "recorded"
        )


async def test_failed_metric_save_restores_in_memory_values(
    init_integration: MockConfigEntry,
) -> None:
    coordinator, _, (plant_id,) = await _tent(init_integration, plants=1)
    plant = coordinator.plants[plant_id]
    original = plant.harvest_metrics.to_dict()
    with patch.object(
        coordinator._plant_manager, "update_plant", side_effect=OSError("disk full")
    ):
        with pytest.raises(OSError, match="disk full"):
            await coordinator.services.plants.update_harvest_metrics(
                plant_id, wet_weight=42, dry_weight=12
            )
    assert plant.harvest_metrics.to_dict() == original


async def test_missing_harvest_source_run_is_refused(
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    orphaned = Plant(
        plant_id="orphan",
        growspace_id="dry",
        harvest_source_growspace_id=growspace_id,
        harvest_source_run_id="missing",
    )
    with pytest.raises(ValueError, match="source Run missing is missing"):
        await coordinator.grow_runs.async_project_harvest_outcomes([orphaned])


async def test_no_usable_yield_requires_reason_and_records_zero(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    plant = await coordinator.services.plants.add_plant(
        growspace_id=growspace_id,
        strain="OG Kush",
        row=1,
        col=1,
        stage=PlantStage.FLOWER,
        flower_start=dt_util.utcnow(),
    )
    await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    await coordinator.services.plants.transition_plant_stage(
        plant.plant_id, PlantStage.DRY
    )
    with pytest.raises(ServiceValidationError, match="with a reason"):
        await coordinator.services.plants.update_harvest_metrics(
            plant.plant_id, dry_weight=0
        )
    with pytest.raises(ServiceValidationError, match="requires a reason"):
        await coordinator.services.plants.set_harvest_outcome(
            plant.plant_id, "no_usable_yield"
        )
    await coordinator.services.plants.set_harvest_outcome(
        plant.plant_id, "no_usable_yield", "  mold  "
    )
    outcome = coordinator.grow_runs.ledger(growspace_id).runs[0].harvest_outcomes[0]
    assert (outcome.state, outcome.reason, outcome.metrics["dry_weight"]) == (
        "no_usable_yield",
        "mold",
        0,
    )


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
    await coordinator._async_project_activity()
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
