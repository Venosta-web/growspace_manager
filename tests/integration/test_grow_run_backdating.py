"""Backdating a Grow Run from Unattributed Activity, end to end (#670)."""

from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from typing import Any
from unittest.mock import patch
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.const import (
    CONF_UNATTRIBUTED_RETENTION_DAYS,
    DOMAIN,
)
from custom_components.growspace_manager.domain.grow_run import GapReason, RunMetadata
from custom_components.growspace_manager.grow_run_store import GrowRunStore
from custom_components.growspace_manager.services.grow_runs import async_start_grow_run
from custom_components.growspace_manager.websocket._common import WS_MSG_USER
from custom_components.growspace_manager.websocket.grow_runs import (
    WS_TYPE_PREVIEW_GROW_RUN_START,
    WS_TYPE_START_GROW_RUN,
    websocket_preview_grow_run_start,
    websocket_start_grow_run,
)
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util
from tests.common import MockConfigEntry

from .test_grow_runs import _admin, _sensor, _tent

RETENTION_DAYS = 30
# Noon in the test instance's US/Pacific, well away from any midnight.
T0 = datetime.fromisoformat("2026-10-05T19:00:00+00:00")


@pytest.fixture
def mock_config_entry() -> MockConfigEntry:
    """The integration with a short retention, so it can be crossed in a test."""
    return MockConfigEntry(
        domain=DOMAIN,
        data={},
        options={CONF_UNATTRIBUTED_RETENTION_DAYS: RETENTION_DAYS},
        title="Growspace Manager",
        unique_id="growspace_manager_test",
    )


def _local_day(hass: HomeAssistant, moment: datetime) -> date:
    return moment.astimezone(ZoneInfo(hass.config.time_zone)).date()


def _midnight(hass: HomeAssistant, day: date) -> datetime:
    zone = ZoneInfo(hass.config.time_zone)
    return datetime.combine(day, time.min, tzinfo=zone).astimezone(dt_util.UTC)


async def _ws(client: Any, message: dict[str, Any]) -> Any:
    await client.send_json_auto_id(message)
    response = await client.receive_json()
    assert response["success"], response
    return response["result"]


# Days pass in these tests, and a WebSocket session does not survive its
# access token expiring; the handlers are driven directly, and one test below
# drives both commands through a real socket at the present time.


async def _preview(
    hass: HomeAssistant, coordinator: Any, growspace_id: str, started_on: date
) -> Any:
    return await websocket_preview_grow_run_start(
        hass, coordinator, {"growspace_id": growspace_id, "started_on": started_on}
    )


async def _start_on(
    hass: HomeAssistant,
    coordinator: Any,
    growspace_id: str,
    started_on: date,
    revision: int = 0,
) -> Any:
    return await websocket_start_grow_run(
        hass,
        coordinator,
        {
            "growspace_id": growspace_id,
            "expected_run_revision": revision,
            "started_on": started_on,
            WS_MSG_USER: await _admin(hass),
        },
    )


async def _next_day(coordinator: Any, freezer: FrozenDateTimeFactory) -> None:
    """A day passes and the periodic refresh notices it."""
    freezer.tick(timedelta(days=1))
    await coordinator.async_refresh()


async def _history(
    init_integration: MockConfigEntry, freezer: FrozenDateTimeFactory
) -> tuple[Any, str, list[str], str]:
    """Two Plants arrive on day 0; one leaves on day 2; day 3 is never observed.

    Returns the coordinator, the tent, its plants and the other growspace.
    """
    freezer.move_to(T0)
    coordinator, growspace_id, plant_ids = await _tent(init_integration)
    other = await coordinator.services.growspaces.add_growspace(name="Veg Tent")
    await _next_day(coordinator, freezer)  # day 1
    await _next_day(coordinator, freezer)  # day 2
    await coordinator.services.plants.update_plant(plant_ids[0], growspace_id=other.id)
    freezer.tick(timedelta(days=2))  # day 3 passes unobserved
    await coordinator.async_refresh()  # day 4
    return coordinator, growspace_id, plant_ids, other.id


async def test_run_free_activity_is_retained_across_a_restart(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, plant_ids, _ = await _history(init_integration, freezer)
    assert coordinator.grow_runs.retention_days == RETENTION_DAYS
    activity = coordinator.grow_runs.unattributed(growspace_id)
    assert activity.covered_since == T0
    *entries, moved = activity.facts
    assert sorted((f.plant_id, f.kind) for f in entries) == sorted(
        (plant_id, "entry") for plant_id in plant_ids
    )
    assert (moved.plant_id, moved.kind) == (plant_ids[0], "transplant")
    day0 = _local_day(hass, T0)
    assert [row.day for row in activity.days] == [
        day0 + timedelta(days=n) for n in (0, 1, 2, 4)
    ]
    assert activity.days[0].entries == 2
    assert activity.days[2].exits == 1

    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    assert reloaded.unattributed(growspace_id) == activity


async def test_a_grower_previews_then_starts_a_run_in_the_past(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    """Preview → confirm → the Run owns the claimed days, and nothing twice."""
    coordinator, growspace_id, (left, stayed), other_id = await _history(
        init_integration, freezer
    )
    day1 = _local_day(hass, T0) + timedelta(days=1)
    moved_at = T0 + timedelta(days=2)

    preview = (await _preview(hass, coordinator, growspace_id, day1))["preview"]
    assert preview["started_on"] == day1.isoformat()
    assert preview["started_at"] == _midnight(hass, day1).isoformat()
    assert preview["run_revision"] == 0
    assert preview["retention_days"] == RETENTION_DAYS
    assert preview["covered_since"] == T0.isoformat()
    assert preview["conflict"] is None
    assert preview["participant_count"] == 2
    assert {
        (row["plant_id"], row["closed_at"], row["name"])
        for row in preview["participations"]
    } == {
        (left, moved_at.isoformat(), "OG Kush"),
        (stayed, None, "OG Kush"),
    }
    assert [row["kind"] for row in preview["claimed_facts"]] == ["transplant"]
    assert [row["date"] for row in preview["claimed_days"]] == [
        (day1 + timedelta(days=n)).isoformat() for n in (0, 1, 3)
    ]
    day3 = day1 + timedelta(days=2)
    assert preview["gaps"] == [
        {
            "start": _midnight(hass, day3).isoformat(),
            "end": _midnight(hass, day3 + timedelta(days=1)).isoformat(),
            "reason": "not_observed",
        }
    ]

    result = await _start_on(hass, coordinator, growspace_id, day1)
    assert result["outcome"] == "started"
    assert result["run_revision"] == 1
    assert result["active_run"]["started_at"] == preview["started_at"]
    assert result["active_run"]["participant_count"] == 2

    run = coordinator.grow_runs.active_run(growspace_id)
    assert run is not None
    assert run.audit[0].at == dt_util.utcnow()
    assert run.backdate is not None
    assert [gap.reason for gap in run.backdate.gaps] == [GapReason.NOT_OBSERVED]
    assert [(f.plant_id, f.source_run_id) for f in run.movement_history] == [
        (left, run.run_id)
    ]
    assert len(run.daily_summaries) == 3

    remaining = coordinator.grow_runs.unattributed(growspace_id)
    assert remaining.covered_since is None
    assert {f.fact_id for f in remaining.facts}.isdisjoint(
        {f.fact_id for f in run.movement_history}
    )
    assert [row.day for row in remaining.days] == [_local_day(hass, T0)]

    await hass.async_block_till_done()
    sensor = _sensor(hass, growspace_id)
    assert sensor.attributes["duration_days"] == 3
    assert sensor.attributes["participant_count"] == 2

    # Once a Run is active, movement is the Run's, not the ledger's.
    await coordinator.services.plants.update_plant(stayed, growspace_id=other_id)
    assert len(coordinator.grow_runs.active_run(growspace_id).movement_history) == 2
    assert coordinator.grow_runs.unattributed(growspace_id) == remaining

    reloaded = GrowRunStore(hass, init_integration.entry_id)
    await reloaded.async_load()
    assert reloaded.active_run(growspace_id) == coordinator.grow_runs.active_run(
        growspace_id
    )
    assert reloaded.unattributed(growspace_id) == remaining


async def test_a_start_before_recording_began_shows_the_uncovered_stretch(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _, _ = await _history(init_integration, freezer)
    before = _local_day(hass, T0) - timedelta(days=3)
    preview = (await _preview(hass, coordinator, growspace_id, before))["preview"]
    assert preview["gaps"][0] == {
        "start": _midnight(hass, before).isoformat(),
        "end": T0.isoformat(),
        "reason": "before_recording",
    }
    assert preview["covered_from"] == T0.isoformat()
    result = await _start_on(hass, coordinator, growspace_id, before)
    assert result["outcome"] == "started"
    run = coordinator.grow_runs.active_run(growspace_id)
    assert run.started_at == _midnight(hass, before)
    assert min(row.opened_at for row in run.participations) == T0


async def test_history_older_than_retention_is_not_inferred(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _, _ = await _history(init_integration, freezer)
    too_old = _local_day(hass, dt_util.utcnow()) - timedelta(days=RETENTION_DAYS)

    conflict = (await _preview(hass, coordinator, growspace_id, too_old))["preview"][
        "conflict"
    ]
    assert conflict["code"] == "grow_run.beyond_retention"
    assert "Imported Run" in conflict["message"]
    assert (
        conflict["boundary"]
        == (dt_util.utcnow() - timedelta(days=RETENTION_DAYS)).isoformat()
    )

    result = await _start_on(hass, coordinator, growspace_id, too_old)
    assert result["refusal"]["code"] == "grow_run.beyond_retention"
    assert result["refusal"]["current_revision"] == 0
    assert coordinator.grow_runs.active_run(growspace_id) is None
    assert coordinator.grow_runs.unattributed(growspace_id).covered_since == T0


async def test_retention_forgets_old_activity_as_days_pass(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _, _ = await _history(init_integration, freezer)
    freezer.tick(timedelta(days=RETENTION_DAYS))
    await coordinator.async_refresh()
    activity = coordinator.grow_runs.unattributed(growspace_id)
    horizon = dt_util.utcnow() - timedelta(days=RETENTION_DAYS)
    assert activity.covered_since == horizon
    assert activity.facts == ()
    assert all(row.day >= _local_day(hass, horizon) for row in activity.days)


async def test_a_future_start_and_an_active_run_are_conflicting_boundaries(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _, _ = await _history(init_integration, freezer)
    today = _local_day(hass, dt_util.utcnow())

    tomorrow = today + timedelta(days=1)
    conflict = (await _preview(hass, coordinator, growspace_id, tomorrow))["preview"][
        "conflict"
    ]
    assert conflict["code"] == "grow_run.boundary_conflict"
    refused = await _start_on(hass, coordinator, growspace_id, tomorrow)
    assert refused["refusal"]["code"] == "grow_run.boundary_conflict"

    run, _ = await async_start_grow_run(
        hass,
        coordinator,
        growspace_id=growspace_id,
        expected_revision=0,
        metadata=RunMetadata(),
        user=await _admin(hass),
    )
    # A plain start closes coverage too: the Growspace is no longer Run-free.
    assert coordinator.grow_runs.unattributed(growspace_id).covered_since is None
    conflict = (await _preview(hass, coordinator, growspace_id, today))["preview"][
        "conflict"
    ]
    assert conflict["code"] == "grow_run.already_active"
    assert conflict["boundary"] == run.started_at.isoformat()
    refused = await _start_on(hass, coordinator, growspace_id, today, revision=1)
    assert refused["refusal"]["code"] == "grow_run.already_active"
    assert refused["refusal"]["active_run"]["run_id"] == run.run_id


async def test_a_stale_backdated_start_is_refused_with_the_current_revision(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _, _ = await _history(init_integration, freezer)
    result = await _start_on(
        hass, coordinator, growspace_id, _local_day(hass, T0), revision=4
    )
    assert result["refusal"]["code"] == "grow_run.revision_conflict"
    assert result["refusal"]["current_revision"] == 0


async def test_concurrent_backdated_starts_claim_the_activity_once(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _, _ = await _history(init_integration, freezer)
    admin = await _admin(hass)
    day1 = _local_day(hass, T0) + timedelta(days=1)

    async def start() -> Any:
        return await async_start_grow_run(
            hass,
            coordinator,
            growspace_id=growspace_id,
            expected_revision=0,
            metadata=RunMetadata(),
            user=admin,
            started_on=day1,
        )

    results = await asyncio.gather(start(), start(), return_exceptions=True)
    started = [r for r in results if not isinstance(r, BaseException)]
    refused = [r for r in results if isinstance(r, BaseException)]
    assert len(started) == 1
    assert [type(r).__name__ for r in refused] == ["RunRevisionConflict"]
    ledger = coordinator.grow_runs.ledger(growspace_id)
    assert (ledger.revision, len(ledger.runs)) == (1, 1)


async def test_a_failed_claim_write_leaves_the_activity_unclaimed(
    hass: HomeAssistant,
    freezer: FrozenDateTimeFactory,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _, _ = await _history(init_integration, freezer)
    before = coordinator.grow_runs.unattributed(growspace_id)
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
            started_on=_local_day(hass, T0),
        )
    assert coordinator.grow_runs.unattributed(growspace_id) == before
    assert coordinator.grow_runs.ledger(growspace_id).runs == ()


async def test_both_commands_travel_the_socket_with_a_date(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """``started_on`` is an ISO date on the wire; today is a valid backdate."""
    coordinator, growspace_id, plant_ids = await _tent(init_integration)
    today = _local_day(hass, dt_util.utcnow()).isoformat()
    client = await hass_ws_client(hass)
    preview = await _ws(
        client,
        {
            "type": WS_TYPE_PREVIEW_GROW_RUN_START,
            "growspace_id": growspace_id,
            "started_on": today,
        },
    )
    assert preview["outcome"] == "preview"
    assert preview["preview"]["participant_count"] == len(plant_ids)
    result = await _ws(
        client,
        {
            "type": WS_TYPE_START_GROW_RUN,
            "growspace_id": growspace_id,
            "expected_run_revision": 0,
            "started_on": today,
        },
    )
    assert result["outcome"] == "started"
    assert result["active_run"]["started_at"] == preview["preview"]["started_at"]
    await client.send_json_auto_id(
        {
            "type": WS_TYPE_PREVIEW_GROW_RUN_START,
            "growspace_id": growspace_id,
            "started_on": "yesterday",
        }
    )
    assert not (await client.receive_json())["success"]
    assert coordinator.grow_runs.active_run(growspace_id) is not None


async def test_an_unreadable_history_refuses_a_preview_and_records_nothing(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
) -> None:
    coordinator, growspace_id, _ = await _tent(init_integration)
    coordinator.grow_runs.unreadable = True
    with patch.object(coordinator.grow_runs._store, "async_save") as save:
        await coordinator.async_refresh()
    save.assert_not_called()
    result = await _preview(
        hass, coordinator, growspace_id, _local_day(hass, dt_util.utcnow())
    )
    assert result["refusal"]["code"] == "grow_run.store_unreadable"


async def test_an_unknown_growspace_cannot_be_previewed(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    client = await hass_ws_client(hass)
    await client.send_json_auto_id(
        {
            "type": WS_TYPE_PREVIEW_GROW_RUN_START,
            "growspace_id": "nowhere",
            "started_on": "2026-10-01",
        }
    )
    assert not (await client.receive_json())["success"]


async def test_a_failure_to_observe_never_fails_the_refresh(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    caplog: pytest.LogCaptureFixture,
) -> None:
    coordinator, _, _ = await _tent(init_integration)
    with patch.object(
        coordinator.grow_runs, "async_observe", side_effect=OSError("disk")
    ):
        await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert "Unattributed Activity coverage was not recorded" in caplog.text


# ---------------------------------------------------------------------------
# The store document
# ---------------------------------------------------------------------------


def _document(unattributed: Any) -> dict[str, Any]:
    return {"ledgers": {}, "unattributed": unattributed}


async def test_a_document_from_before_backdating_loads_with_no_coverage(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
) -> None:
    key = "growspace_manager.grow_runs_older"
    hass_storage[key] = {
        "version": 1,
        "minor_version": 1,
        "key": key,
        "data": {"ledgers": {}},
    }
    store = GrowRunStore(hass, "older")
    await store.async_load()
    assert not store.unreadable
    assert store.unattributed("tent").covered_since is None


@pytest.mark.parametrize(
    "unattributed",
    [
        [],
        {"tent": {"growspace_id": "other", "facts": [], "days": []}},
        {"tent": {"growspace_id": "tent", "facts": None, "days": []}},
    ],
)
async def test_a_malformed_ledger_makes_the_history_unreadable(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_storage: dict[str, Any],
    unattributed: Any,
) -> None:
    key = "growspace_manager.grow_runs_damaged"
    document = _document(unattributed)
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": document}
    store = GrowRunStore(hass, "damaged")
    await store.async_load()
    assert store.unreadable
    await store.async_observe(dt_util.utcnow(), {"tent": []})
    assert hass_storage[key]["data"] == document
