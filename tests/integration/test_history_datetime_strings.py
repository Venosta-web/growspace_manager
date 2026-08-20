"""Test for datetime string parsing in history stats."""

from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.websocket import websocket_get_history_stats
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util


@pytest.mark.asyncio
async def test_websocket_history_datetime_strings(hass: HomeAssistant):
    """Test that websocket_get_history_stats handles ISO datetime strings."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)

    # Simulate history data as dictionaries with ISO string timestamps
    # This is what the recorder returns in production
    history_data = {
        "sensor.test": [
            {
                "state": "10",
                "last_updated": start.isoformat(),
                "last_changed": start.isoformat(),
            },
            {
                "state": "20",
                "last_updated": (start + dt_util.dt.timedelta(minutes=10)).isoformat(),
                "last_changed": (start + dt_util.dt.timedelta(minutes=10)).isoformat(),
            },
        ]
    }

    with (
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value=history_data,
        ),
        patch(
            "custom_components.growspace_manager.websocket.environment.get_instance"
        ) as mock_get_rec,
    ):
        mock_get_rec.return_value.async_add_executor_job = hass.async_add_executor_job
        msg = {
            "id": 1,
            "type": f"{DOMAIN}/get_history_stats",
            "entity_ids": ["sensor.test"],
            "start_time": start.isoformat(),
            "end_time": (start + dt_util.dt.timedelta(minutes=30)).isoformat(),
            "interval_minutes": 15,
            "significant_changes_only": True,
        }

        result = await websocket_get_history_stats(hass, MagicMock(), msg)

        # Verify success - should parse ISO strings and not crash
        assert "sensor.test" in result
        stats = result["sensor.test"]
        assert len(stats) >= 1
        assert stats[0]["s"] == "10"
