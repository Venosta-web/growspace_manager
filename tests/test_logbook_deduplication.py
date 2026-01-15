"""Tests for logbook event deduplication/merging."""

import json
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.websocket import websocket_get_event_log


@pytest.mark.asyncio
async def test_websocket_event_log_merging(hass: HomeAssistant) -> None:
    """Test that consecutive identical alerts are merged."""
    connection = MagicMock()
    msg = {"id": 1, "limit": 10}

    # Setup mocks
    session_mock = MagicMock()
    query_mock = MagicMock()
    session_mock.query.return_value = query_mock
    query_mock.join.return_value = query_mock
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.limit.return_value = query_mock

    # Helper to create event mock
    def mk_event(eid, ts, start_iso, end_iso, severity, g_id="g1", s_type="mold"):
        e = MagicMock()
        e.event_id = eid
        e.time_fired_ts = ts
        d = MagicMock()
        d.shared_data = json.dumps(
            {
                "category": "alert",
                "growspace_id": g_id,
                "sensor_type": s_type,
                "severity": severity,
                "start_time": start_iso,
                "end_time": end_iso,
                "duration_sec": 60,
                "reasons": [f"Reason {eid}"],
            }
        )
        return (e, d)

    # We are querying DESC, so we see newest first.
    # Event A (newest): Ended at 18:35, started at 18:34
    # Event B: Ended at 18:32, started at 18:31 (mergeable with A, gap 2 min)
    # Event C: Ended at 18:25, started at 18:24 (mergeable with B, gap 6 min)
    # Event D: Ended at 18:10, started at 18:09 (NOT mergeable with C, gap 14 min)

    row1 = mk_event(
        1, 1736616900, "2026-01-11T18:34:00+00:00", "2026-01-11T18:35:00+00:00", 0.90
    )
    row2 = mk_event(
        2, 1736616720, "2026-01-11T18:31:00+00:00", "2026-01-11T18:32:00+00:00", 0.90
    )
    row3 = mk_event(
        3, 1736616300, "2026-01-11T18:24:00+00:00", "2026-01-11T18:25:00+00:00", 0.90
    )
    row4 = mk_event(
        4, 1736615400, "2026-01-11T18:09:00+00:00", "2026-01-11T18:10:00+00:00", 0.90
    )

    # Different severity - should NOT merge
    row5 = mk_event(
        5, 1736615300, "2026-01-11T18:07:00+00:00", "2026-01-11T18:08:00+00:00", 0.80
    )

    query_mock.__iter__.return_value = iter([row1, row2, row3, row4, row5])

    context_manager_mock = MagicMock()
    context_manager_mock.__enter__.return_value = session_mock

    with (
        patch(
            "custom_components.growspace_manager.websocket.session_scope",
            return_value=context_manager_mock,
        ),
        patch("custom_components.growspace_manager.websocket.get_instance") as get_instance_mock,
    ):
        instance = get_instance_mock.return_value

        async def fake_executor(func, *args):
            return func(*args)

        instance.async_add_executor_job.side_effect = fake_executor

        await websocket_get_event_log(hass, connection, msg)

        # Verify result
        connection.send_result.assert_called()
        result_data = connection.send_result.call_args[0][1]

        events = result_data["g1"]
        # Expected:
        # 1. Merged event (1+2+3): start 18:24, end 18:35, duration 180s
        # 2. Event D (4): start 18:09, end 18:10
        # 3. Event E (5): start 18:07, end 18:08 (diff severity)

        assert len(events) == 3

        # Newest (merged) first
        merged = events[0]
        assert merged["start_time"] == "2026-01-11T18:24:00+00:00"
        assert merged["end_time"] == "2026-01-11T18:35:00+00:00"
        assert merged["duration_sec"] == 180
        assert len(merged["reasons"]) == 3
        assert "Reason 1" in merged["reasons"]
        assert "Reason 3" in merged["reasons"]

        # Second one
        assert events[1]["event_id"] == 4
        # Third one
        assert events[2]["event_id"] == 5
        assert events[2]["severity"] == 0.80
