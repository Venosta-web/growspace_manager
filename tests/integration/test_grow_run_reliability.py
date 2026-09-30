"""Safety Ledger activity is durable Run history (#918)."""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.coordinator import _safety_timestamp
from custom_components.growspace_manager.domain.grow_run import (
    WARNING_INCOMPLETE_SNAPSHOT,
    RunStoreUnreadable,
    SafetyFact,
    reliability_summary,
)
from custom_components.growspace_manager.grow_run_store import GrowRunStore
from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.services.grow_runs import (
    async_finalize_grow_run,
)
from custom_components.growspace_manager.websocket.grow_runs import WS_TYPE_GET_GROW_RUN
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util
from tests.common import MockConfigEntry
from tests.integration.test_grow_runs import (
    _admin,
    _complete_as_admin,
    _started,
    _tent,
    _ws,
)


async def test_home_assistant_start_is_durable_once_per_growspace(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator = init_integration.runtime_data
    starts = [
        row
        for row in coordinator.irrigation_safety.ledger
        if row["action"] == "ha_restart"
    ]
    assert {row["growspace_id"] for row in starts} == set(coordinator.growspaces)
    assert len({row["fact_id"] for row in starts}) == len(starts)
    assert not coordinator.irrigation_safety.pending_facts
    restarted = IrrigationSafetyStore(hass, init_integration.entry_id)
    await restarted.async_load()
    assert [
        row["fact_id"] for row in restarted.ledger if row["action"] == "ha_restart"
    ] == [row["fact_id"] for row in starts]


async def test_a_run_active_before_upgrade_has_partial_safety_coverage(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    store = coordinator.grow_runs
    ledger = store.ledger(growspace_id)
    async with store.lock:
        await store.async_commit(
            replace(
                ledger,
                runs=(replace(run, safety_coverage_started_at=None),),
            )
        )
    restarted = GrowRunStore(hass, init_integration.entry_id)
    await restarted.async_load()
    now = dt_util.utcnow() + timedelta(seconds=1)
    await restarted.async_begin_safety_coverage(now)
    updated = restarted.ledger(growspace_id).find(run.run_id)
    assert updated.safety_coverage_started_at == now
    assert reliability_summary(updated, "live")["complete"] is False

    restarted.unreadable = True
    with patch.object(restarted._store, "async_save", new_callable=AsyncMock) as save:
        await restarted.async_begin_safety_coverage(now + timedelta(seconds=1))
    save.assert_not_awaited()


def test_safety_projection_refuses_an_invalid_ledger_timestamp() -> None:
    with pytest.raises(ValueError, match="valid time"):
        _safety_timestamp("not a timestamp")


async def test_safety_events_project_once_and_freeze_after_restart(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    safety = coordinator.irrigation_safety
    fault = await safety.async_latch(
        growspace_id, "pump_stuck", "Pump stayed on", ("switch.pump",)
    )
    await safety.async_record_transition(growspace_id, "inhibited", "sensor_stale")
    await safety.async_acknowledge(growspace_id, "operator")
    assert not safety.pending_facts

    client = await hass_ws_client(hass)
    details = await _ws(
        client,
        {
            "type": WS_TYPE_GET_GROW_RUN,
            "growspace_id": growspace_id,
            "run_id": run.run_id,
        },
    )
    summary = details["run"]["reliability"]
    assert summary["state"] == "live"
    assert summary["definition_version"] == 1
    assert {
        key: summary["counts"][key] for key in ("acknowledge", "fault", "inhibit")
    } == {
        "acknowledge": 1,
        "fault": 1,
        "inhibit": 1,
    }
    assert summary["latest_fault"]["fault_id"] == fault.fault_id
    assert summary["latest_fault"]["acknowledged"] is True

    first = coordinator.grow_runs.ledger(growspace_id).active_run.safety_facts[0]
    await coordinator.grow_runs.async_project_safety(first)
    assert len(coordinator.grow_runs.ledger(growspace_id).active_run.safety_facts) == 3

    await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    finalized, _ = await async_finalize_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        run_id=run.run_id,
        expected_revision=2,
        acknowledged=[WARNING_INCOMPLETE_SNAPSHOT],
        user=await _admin(hass),
    )
    assert finalized.snapshot.reliability["state"] == "final"
    assert finalized.snapshot.reliability["counts"]["fault"] == 1

    restarted = GrowRunStore(hass, init_integration.entry_id)
    await restarted.async_load()
    frozen = restarted.ledger(growspace_id).find(run.run_id)
    assert frozen.snapshot.reliability == finalized.snapshot.reliability
    assert len(frozen.safety_facts) == 3
    restarted_safety = IrrigationSafetyStore(hass, init_integration.entry_id)
    await restarted_safety.async_load()
    assert not restarted_safety.pending_facts


async def test_safety_after_completion_is_unattributed(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    await coordinator.irrigation_safety.async_record_event(
        growspace_id, "unexpected_on"
    )
    activity = coordinator.grow_runs.unattributed(growspace_id)
    assert [fact.kind for fact in activity.safety_facts] == ["unexpected_on"]
    fact = activity.safety_facts[0]
    await coordinator.grow_runs.async_project_safety(
        SafetyFact(fact.fact_id, fact.growspace_id, fact.at, fact.kind)
    )
    assert coordinator.grow_runs.unattributed(growspace_id).safety_facts == (fact,)


async def test_failed_projection_replays_from_the_safety_outbox(
    hass: HomeAssistant, init_integration: MockConfigEntry
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration, plants=0)
    run = await _started(hass, coordinator, growspace_id)
    with patch.object(
        coordinator.grow_runs._store,
        "async_save",
        new_callable=AsyncMock,
        side_effect=OSError("Run store unavailable"),
    ):
        await coordinator.irrigation_safety.async_record_event(
            growspace_id, "unexpected_on", output="switch.pump"
        )
        with pytest.raises(RunStoreUnreadable, match="pending projection"):
            await _complete_as_admin(hass, coordinator, growspace_id, run.run_id)
    (pending,) = coordinator.irrigation_safety.pending_facts
    assert pending["action"] == "unexpected_on"
    assert not coordinator.grow_runs.ledger(growspace_id).find(run.run_id).safety_facts

    await coordinator.async_project_safety()
    await coordinator.async_project_safety()
    facts = coordinator.grow_runs.ledger(growspace_id).find(run.run_id).safety_facts
    assert len(facts) == 1
    assert facts[0].details["output"] == "switch.pump"
    assert not coordinator.irrigation_safety.pending_facts
