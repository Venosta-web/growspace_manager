"""Test timeline spam filtering fix."""

import json
from datetime import timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from custom_components.growspace_manager.websocket import (
    WS_TYPE_GET_ALERTS,
    WS_TYPE_GET_LOG,
    async_register_websocket_api,
)
from homeassistant.core import HomeAssistant

WebSocketGenerator = Any


async def test_websocket_get_log_filters_new_spam_categories(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test get_log filters out 'alert' and 'environment' spam categories."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
        patch(
            "custom_components.growspace_manager.websocket.EventData"
        ) as mock_event_data,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session

        # Mock DB results with SPAM events
        mock_session.query.return_value.filter.return_value.first.return_value = (1,)

        # Mock event 1: alert (should be filtered)
        mock_event1 = MagicMock()
        mock_event1.event_id = 100
        mock_event1.time_fired_ts = 1672574400.0
        mock_data1 = MagicMock()
        mock_data1.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "alert",
                "sensor_type": "stress",
                "severity": 10.0,
                "start_time": "2023-01-01T12:00:00+00:00",
            }
        )

        # Mock event 2: environment (should be filtered)
        mock_event2 = MagicMock()
        mock_event2.event_id = 101
        mock_event2.time_fired_ts = 1672574410.0
        mock_data2 = MagicMock()
        mock_data2.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "environment",
                "sensor_type": "optimal",
                "severity": 10.0,
                "start_time": "2023-01-01T12:01:00+00:00",
            }
        )

        # Mock event 3: valid note (should passed)
        mock_event3 = MagicMock()
        mock_event3.event_id = 102
        mock_event3.time_fired_ts = 1672574420.0
        mock_data3 = MagicMock()
        mock_data3.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "note",
                "notes": "Test Note",
                "timestamp": "2023-01-01T12:02:00+00:00",
            }
        )

        # Mock event 4: training (should passed)
        mock_event4 = MagicMock()
        mock_event4.event_id = 103
        mock_event4.time_fired_ts = 1672574420.0
        mock_data4 = MagicMock()
        mock_data4.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "training",
                "timestamp": "2023-01-01T12:02:00+00:00",
            }
        )

        # Mock event 5: environmental_report (should passed - distinct from 'environment')
        mock_event5 = MagicMock()
        mock_event5.event_id = 104
        mock_event5.time_fired_ts = 1672574425.0
        mock_data5 = MagicMock()
        mock_data5.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "environmental_report",
                "sensor_type": "day_report",
                "start_time": "2023-01-01T12:03:00+00:00",
            }
        )

        # Order matches DB: typically newest first? No, logic depends on query order
        # But here we simulate what the query *would* return if filters failed,
        # OR we rely on Python-side filtering?
        # IMPORTANT: The websocket code does filtering in Python too!
        # `if exclude_categories and d.get("category") in exclude_categories: continue`
        # So even if DB returns them, Python should filter them.

        # Mock query chain - handle multiple .filter() calls
        q_base = mock_session.query.return_value.join.return_value
        # Make filter() return the same mock (q_base) to allow chaining multiple filters
        q_base.filter.return_value = q_base

        # Now set up the final part of the chain
        q_mock = q_base.order_by.return_value
        q_mock.limit.return_value = [
            (mock_event1, mock_data1),
            (mock_event2, mock_data2),
            (mock_event3, mock_data3),
            (mock_event4, mock_data4),
            (mock_event5, mock_data5),
        ]

        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_LOG, "growspace_id": "gs1"}
        )
        response = await client.receive_json()
        assert response["success"]

        # Since exclusions happen at SQL level (which we mocked to return everything),
        # python code DOES NOT filter them out again. So we get all 5.
        # To verify the fix, we must ensure that .filter() was called for "alert" and "environment",
        # BUT NOT for "environmental_report".
        results = response["result"]["gs1"]
        assert len(results) == 5

        # Verify .like() calls on EventData.shared_data
        # We look for calls that contain our spam cats in the pattern.

        like_calls = mock_event_data.shared_data.like.call_args_list
        found_alert_filter = False
        found_env_filter = False
        found_env_report_filter = False

        for call in like_calls:
            # call.args[0] is the pattern string e.g. '%"category":"alert"%'
            pattern = call.args[0]
            if '"category":"alert"' in pattern or '"category": "alert"' in pattern:
                found_alert_filter = True
            if (
                '"category":"environment"' in pattern
                or '"category": "environment"' in pattern
            ):
                found_env_filter = True
            if (
                '"category":"environmental_report"' in pattern
                or '"category": "environmental_report"' in pattern
            ):
                found_env_report_filter = True

        assert found_alert_filter, "Should check for 'alert' category using .like()"
        assert found_env_filter, "Should check for 'environment' category using .like()"
        assert not found_env_report_filter, (
            "Should NOT filter 'environmental_report' category"
        )


async def test_websocket_get_alerts_includes_new_cats(
    hass: HomeAssistant, hass_ws_client: WebSocketGenerator
) -> None:
    """Test get_alerts includes 'alert' and 'environment' categories."""
    async_register_websocket_api(hass)
    client = await hass_ws_client(hass)

    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_recorder,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope,
    ):
        mock_session = MagicMock()
        mock_scope.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = (1,)

        # Mock event: alert
        mock_event1 = MagicMock()
        mock_event1.event_id = 100
        mock_event1.time_fired_ts = 1672574400.0
        mock_data1 = MagicMock()
        mock_data1.shared_data = json.dumps(
            {
                "growspace_id": "gs1",
                "category": "alert",
                "sensor_type": "stress",
            }
        )

        q_mock = mock_session.query.return_value.join.return_value.filter.return_value.order_by.return_value
        q_mock.limit.return_value = [(mock_event1, mock_data1)]

        async def mock_executor(func, *args, **kwargs):
            return func(*args, **kwargs)

        mock_recorder.return_value.async_add_executor_job.side_effect = mock_executor

        await client.send_json(
            {"id": 1, "type": WS_TYPE_GET_ALERTS, "growspace_id": "gs1"}
        )
        response = await client.receive_json()
        assert response["success"]
        results = response["result"]["gs1"]
        assert len(results) == 1
        assert results[0]["category"] == "alert"
