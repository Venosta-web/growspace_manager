from unittest.mock import MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager import DOMAIN, websocket_get_history_stats


@pytest.mark.asyncio
async def test_websocket_history_missing_last_updated(hass: HomeAssistant):
    """Test that websocket_get_history_stats handles dicts missing last_updated."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)

    # Simulate history data as dictionaries MISSING last_updated
    # This simulates what might happen if minimal_response=True omits it
    history_data = {
        "sensor.test": [
            {
                "state": "10",
                # "last_updated": start,  <-- MISSING
                "last_changed": start,
            }
        ]
    }

    with (
        patch(
            "homeassistant.components.recorder.history.get_significant_states",
            return_value=history_data,
        ),
        patch("custom_components.growspace_manager.get_instance") as mock_get_rec,
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

        await websocket_get_history_stats(hass, mock_connection, msg)

        # Verify success - we should get a result even if keys were missing (fallback)
        mock_connection.send_result.assert_called_once()
        result = mock_connection.send_result.call_args[0][1]
        assert "sensor.test" in result
