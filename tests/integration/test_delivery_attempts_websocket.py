"""Reading one growspace's Delivery Attempts for one local day (#888, ADR-0066)."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock
from zoneinfo import ZoneInfo

from freezegun.api import FrozenDateTimeFactory
import pytest
from pytest_homeassistant_custom_component.typing import WebSocketGenerator

from custom_components.growspace_manager.delivery_attempt_store import (
    DeliveryAttemptStore,
    DeliveryRecordUnreadable,
)
from custom_components.growspace_manager.domain.delivery_attempt import (
    AttemptTrigger,
    DeliveryAttempt,
    TriggerEvidence,
    ValveReadback,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.websocket.irrigation import (
    WS_TYPE_GET_DELIVERY_ATTEMPTS,
    websocket_get_delivery_attempts,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry
from tests.conftest import _orig_set_default_time_zone

CONTRACT = Path(__file__).parents[1] / "fixtures" / "contract"
REGENERATE = (
    ".venv/bin/pytest tests/integration/test_delivery_attempts_websocket.py "
    "--regenerate-contract-fixture"
)
BERLIN = ZoneInfo("Europe/Berlin")
DAY = date(2026, 9, 28)
# Local midnight opening DAY in Berlin, summer time.
MIDNIGHT = datetime(2026, 9, 27, 22, 0, tzinfo=UTC)
PUMP = "switch.irrigation_pump"


@pytest.fixture
def berlin() -> Iterator[None]:
    """Run in a zone whose midnight is not UTC's, so the day bounds are local."""
    _orig_set_default_time_zone(BERLIN)
    try:
        yield
    finally:
        _orig_set_default_time_zone(dt_util.UTC)


def _requested(
    growspace_id: str,
    attempt_id: str,
    at: datetime,
    *,
    trigger: AttemptTrigger = AttemptTrigger.SCHEDULE,
    evidence: TriggerEvidence | None = None,
    planned_s: float = 60,
) -> DeliveryAttempt:
    return DeliveryAttempt.requested(
        attempt_id=attempt_id,
        growspace_id=growspace_id,
        output=PUMP,
        trigger=trigger,
        trigger_evidence=evidence
        or TriggerEvidence(slot=f"{at.astimezone(BERLIN):%H:%M:%S}"),
        planned_s=planned_s,
        flow_rate_ml_per_sec=12.5,
        requested_at=at,
    )


def _shot(growspace_id: str, attempt_id: str, at: datetime) -> DeliveryAttempt:
    """A scheduled shot that ran its minute and was read back OFF."""
    return (
        _requested(growspace_id, attempt_id, at)
        .commanded(at + timedelta(milliseconds=200))
        .confirmed_on(at + timedelta(seconds=1), at.astimezone(BERLIN).date())
        .closed(off_commanded_at=at + timedelta(seconds=61))
        .read_back_off(at + timedelta(seconds=62))
    )


def _suppressed(
    growspace_id: str, attempt_id: str, at: datetime, reason: str = "cap_cycles"
) -> DeliveryAttempt:
    return _requested(growspace_id, attempt_id, at).refused(reason)


def _day(growspace_id: str) -> list[DeliveryAttempt]:
    """One of each close, with every field the wire form can carry set somewhere."""
    at = MIDNIGHT + timedelta(hours=8)
    steering = (
        _requested(
            growspace_id,
            "attempt-steering",
            at,
            trigger=AttemptTrigger.STEERING,
            evidence=TriggerEvidence(
                phase="P1", vwc=48.5, base_s=40.0, vwc_factor=1.2, ec_factor=0.9
            ),
            planned_s=48,
        )
        .commanded(at + timedelta(milliseconds=150))
        .confirmed_on(at + timedelta(seconds=1), DAY)
        .closed(off_commanded_at=at + timedelta(seconds=50))
        .read_back_off(at + timedelta(seconds=51))
    )
    steering = replace(
        steering,
        valves=(
            ValveReadback(
                "switch.zone_valve",
                at,
                at + timedelta(milliseconds=100),
                at + timedelta(seconds=51),
                at + timedelta(seconds=52),
            ),
        ),
    )
    at = MIDNIGHT + timedelta(hours=10)
    suppressed = _suppressed(growspace_id, "attempt-suppressed", at)
    for hour in (1, 2):
        suppressed = suppressed.merged(
            _suppressed(growspace_id, f"merged-{hour}", at + timedelta(hours=hour))
        )
    at = MIDNIGHT + timedelta(hours=13)
    not_delivered = (
        _requested(
            growspace_id,
            "attempt-manual",
            at,
            trigger=AttemptTrigger.MANUAL,
            evidence=TriggerEvidence(user_id="user-abc123"),
        )
        .commanded(at + timedelta(milliseconds=100))
        .unconfirmed(
            off_commanded_at=at + timedelta(seconds=10), reason="on_unconfirmed"
        )
        .read_back_off(at + timedelta(seconds=11))
    )
    at = MIDNIGHT + timedelta(hours=14)
    aborted = (
        _requested(growspace_id, "attempt-aborted", at)
        .commanded(at + timedelta(milliseconds=100))
        .confirmed_on(at + timedelta(seconds=1), DAY)
        .closed(
            off_commanded_at=at + timedelta(seconds=20), abort_cause="emergency_stop"
        )
        .read_back_off(at + timedelta(seconds=21))
    )
    at = MIDNIGHT + timedelta(hours=15)
    interrupted = (
        _requested(growspace_id, "attempt-interrupted", at)
        .commanded(at + timedelta(milliseconds=100))
        .confirmed_on(at + timedelta(seconds=1), DAY)
        .interrupted(
            at + timedelta(minutes=5),
            off_commanded_at=at + timedelta(minutes=5),
            off_confirmed_at=at + timedelta(minutes=5, seconds=1),
        )
    )
    at = MIDNIGHT + timedelta(hours=16)
    drain = (
        _requested(
            growspace_id,
            "attempt-drain",
            at,
            trigger=AttemptTrigger.DRAIN,
            evidence=TriggerEvidence(slot="18:00:00"),
            planned_s=30,
        )
        .commanded(at + timedelta(milliseconds=100))
        .confirmed_on(at + timedelta(seconds=1), DAY)
        .closed(off_commanded_at=at + timedelta(seconds=31))
        .read_back_off(at + timedelta(seconds=32))
    )
    return [drain, interrupted, aborted, not_delivered, suppressed, steering]


def _coordinator(hass: HomeAssistant, growspace_id: str) -> MagicMock:
    coordinator = MagicMock()
    coordinator.growspaces = {growspace_id: MagicMock()}
    coordinator.deliveries = DeliveryAttemptStore(hass, "contract-entry")
    return coordinator


async def _wire_form(hass: HomeAssistant) -> dict[str, Any]:
    coordinator = _coordinator(hass, "gs-contract")
    deliveries = await coordinator.deliveries.async_load("gs-contract")
    deliveries.attempts = _day("gs-contract")
    return await websocket_get_delivery_attempts(
        hass,
        coordinator,
        {"growspace_id": "gs-contract", "date": DAY},
    )


@pytest.mark.usefixtures("berlin")
async def test_contract_fixture(
    hass: HomeAssistant, pytestconfig: pytest.Config
) -> None:
    """The day the card's timeline parses is exactly the committed fixture."""
    wire = await _wire_form(hass)
    path = CONTRACT / "delivery_attempts_day_v1.json"
    if pytestconfig.getoption("regenerate_contract_fixture"):
        path.write_text(f"{json.dumps(wire, indent=2, sort_keys=True)}\n")
    assert path.exists(), f"missing; regenerate with: {REGENERATE}"
    assert wire == json.loads(path.read_text()), (
        f"changed; review the diff, then regenerate with: {REGENERATE}"
    )


@pytest.mark.usefixtures("berlin")
async def test_the_fixture_sets_every_field_somewhere(hass: HomeAssistant) -> None:
    """A field null in every row is a field the card schema never sees typed."""
    wire = await _wire_form(hass)
    rows = wire["attempts"]

    assert all(value is not None for value in wire.values())
    assert not [key for key in rows[0] if all(row[key] is None for row in rows)]
    evidence = {key for row in rows for key in row["trigger_evidence"]}
    assert evidence == set(TriggerEvidence.__slots__)
    assert {row["outcome"] for row in rows} == {
        "completed",
        "suppressed",
        "not_delivered",
        "aborted",
        "interrupted",
    }
    assert {row["trigger"] for row in rows} == {t.value for t in AttemptTrigger}


@pytest.mark.usefixtures("berlin")
async def test_the_day_is_read_oldest_first_with_its_local_bounds(
    hass: HomeAssistant,
) -> None:
    wire = await _wire_form(hass)

    assert wire["date"] == "2026-09-28"
    assert wire["starts_at"] == "2026-09-28T00:00:00+02:00"
    assert wire["ends_at"] == "2026-09-29T00:00:00+02:00"
    assert [row["attempt_id"] for row in wire["attempts"]] == [
        "attempt-steering",
        "attempt-suppressed",
        "attempt-manual",
        "attempt-aborted",
        "attempt-interrupted",
        "attempt-drain",
    ]


@pytest.mark.usefixtures("berlin")
async def test_a_merged_suppression_carries_its_count_and_span(
    hass: HomeAssistant,
) -> None:
    wire = await _wire_form(hass)
    (row,) = [row for row in wire["attempts"] if row["outcome"] == "suppressed"]

    assert row["suppressed_count"] == 3
    assert row["reason"] == "cap_cycles"
    assert row["requested_at"] == "2026-09-28T08:00:00+00:00"
    assert row["last_requested_at"] == "2026-09-28T10:00:00+00:00"


async def test_an_unknown_growspace_is_not_found(hass: HomeAssistant) -> None:
    coordinator = _coordinator(hass, "gs-contract")

    with pytest.raises(GrowspaceNotFoundError, match="missing"):
        await websocket_get_delivery_attempts(
            hass, coordinator, {"growspace_id": "missing"}
        )


async def test_an_unreadable_record_is_refused_not_an_empty_day(
    hass: HomeAssistant,
) -> None:
    coordinator = _coordinator(hass, "gs-contract")
    deliveries = await coordinator.deliveries.async_load("gs-contract")
    deliveries.unreadable = True

    with pytest.raises(DeliveryRecordUnreadable, match="gs-contract"):
        await websocket_get_delivery_attempts(
            hass, coordinator, {"growspace_id": "gs-contract"}
        )


# --- Over the real WebSocket, against the set-up integration ---------------


async def _growspace(init_integration: MockConfigEntry) -> tuple[Any, str]:
    coordinator = init_integration.runtime_data
    growspace = await coordinator.services.growspaces.add_growspace(
        name="Attempt Tent", rows=1, plants_per_row=1
    )
    return coordinator, growspace.id


async def _read(client: Any, growspace_id: str, **extra: Any) -> dict[str, Any]:
    await client.send_json_auto_id(
        {
            "type": WS_TYPE_GET_DELIVERY_ATTEMPTS,
            "growspace_id": growspace_id,
            **extra,
        }
    )
    return await client.receive_json()


@pytest.mark.usefixtures("berlin")
async def test_an_empty_day_is_today_with_no_attempts(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """With no date the day is Home Assistant's local today, not UTC's."""
    _, growspace_id = await _growspace(init_integration)
    client = await hass_ws_client(hass)
    freezer.move_to(MIDNIGHT + timedelta(minutes=30))

    response = await _read(client, growspace_id)

    assert response["success"], response
    assert response["result"] == {
        "growspace_id": growspace_id,
        "date": "2026-09-28",
        "starts_at": "2026-09-28T00:00:00+02:00",
        "ends_at": "2026-09-29T00:00:00+02:00",
        "attempts": [],
    }


@pytest.mark.usefixtures("berlin")
async def test_merged_suppressions_are_one_row_on_the_wire(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    freezer: FrozenDateTimeFactory,
) -> None:
    """Suppressions recorded through the store read back as one counted row."""
    coordinator, growspace_id = await _growspace(init_integration)
    client = await hass_ws_client(hass)
    # After connecting: its access token was issued at the real time.
    freezer.move_to(MIDNIGHT + timedelta(hours=12))
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    deliveries.close(_shot(growspace_id, "shot", MIDNIGHT + timedelta(hours=6)))
    for minutes in (0, 15, 30):
        deliveries.suppress(
            _suppressed(
                growspace_id,
                f"refused-{minutes}",
                MIDNIGHT + timedelta(hours=9, minutes=minutes),
            )
        )
    deliveries.suppress(
        _suppressed(
            growspace_id, "held", MIDNIGHT + timedelta(hours=10), reason="operator"
        )
    )

    response = await _read(client, growspace_id, date="2026-09-28")

    assert response["success"], response
    rows = response["result"]["attempts"]
    assert [
        (row["attempt_id"], row["outcome"], row["suppressed_count"]) for row in rows
    ] == [
        ("shot", "completed", 0),
        ("refused-0", "suppressed", 3),
        ("held", "suppressed", 1),
    ]
    assert (
        rows[1]["last_requested_at"]
        == (MIDNIGHT + timedelta(hours=9, minutes=30)).isoformat()
    )


@pytest.mark.usefixtures("berlin")
async def test_local_midnight_divides_the_days(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """A second before Berlin's midnight is yesterday, though UTC says 21:59."""
    coordinator, growspace_id = await _growspace(init_integration)
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    deliveries.attempts = [
        _suppressed(growspace_id, "late", MIDNIGHT - timedelta(seconds=1), "hold"),
        _suppressed(growspace_id, "early", MIDNIGHT, "cap_cycles"),
    ]
    client = await hass_ws_client(hass)

    yesterday = await _read(client, growspace_id, date="2026-09-27")
    today = await _read(client, growspace_id, date="2026-09-28")

    assert [row["attempt_id"] for row in yesterday["result"]["attempts"]] == ["late"]
    assert [row["attempt_id"] for row in today["result"]["attempts"]] == ["early"]


@pytest.mark.usefixtures("berlin")
async def test_a_clock_change_day_is_twenty_five_hours(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    """Summer time ends on 25 October 2026 in Berlin."""
    _, growspace_id = await _growspace(init_integration)
    client = await hass_ws_client(hass)

    response = await _read(client, growspace_id, date="2026-10-25")

    result = response["result"]
    assert result["starts_at"] == "2026-10-25T00:00:00+02:00"
    assert result["ends_at"] == "2026-10-26T00:00:00+01:00"
    assert datetime.fromisoformat(result["ends_at"]) - datetime.fromisoformat(
        result["starts_at"]
    ) == timedelta(hours=25)


async def test_an_unreadable_record_answers_with_a_typed_error(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Nothing recorded and nothing known are different answers (ADR-0027)."""
    coordinator, growspace_id = await _growspace(init_integration)
    deliveries = await coordinator.deliveries.async_load(growspace_id)
    deliveries.unreadable = True
    client = await hass_ws_client(hass)

    response = await _read(client, growspace_id)

    assert not response["success"]
    assert response["error"]["code"] == "internal_error"
    assert "unreadable" in response["error"]["message"]
    assert "Error handling" not in caplog.text


async def test_an_unknown_growspace_answers_entity_not_found(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    client = await hass_ws_client(hass)

    response = await _read(client, "no-such-growspace")

    assert not response["success"]
    assert response["error"]["code"] == "entity_not_found"


async def test_a_malformed_date_is_refused_by_the_schema(
    hass: HomeAssistant,
    init_integration: MockConfigEntry,
    hass_ws_client: WebSocketGenerator,
) -> None:
    _, growspace_id = await _growspace(init_integration)
    client = await hass_ws_client(hass)

    response = await _read(client, growspace_id, date="28/09/2026")

    assert not response["success"]
    assert response["error"]["code"] == "invalid_format"
