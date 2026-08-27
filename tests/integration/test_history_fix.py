from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.websocket import websocket_get_history_stats
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


@pytest.mark.asyncio
async def test_websocket_history_handles_dicts(hass: HomeAssistant):
    """Test that websocket_get_history_stats handles dictionary states (minimal_response)."""
    mock_connection = MagicMock()
    mock_connection.send_result = MagicMock()
    mock_connection.send_error = MagicMock()

    start = dt_util.utcnow().replace(minute=0, second=0, microsecond=0)

    # Simulate history data as dictionaries, which minimal_response=True returns
    history_data = {
        "sensor.test": [
            {"state": "10", "last_updated": start, "last_changed": start},
            {
                "state": "20",
                "last_updated": start + dt_util.dt.timedelta(minutes=10),
                "last_changed": start + dt_util.dt.timedelta(minutes=10),
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

        # If it fails with AttributeError, send_result won't be called (validation)
        # or it will raise uncaught exception depending on test harness.
        # But our code catches Exception and sends error usually?
        # Wait, the logs showed "Error handling websocket_get_history_stats" AND Traceback.
        # It catches Exception but logs exception.

        # In the test, if it catches/logs, we verify send_result was called for SUCCESS,
        # or ensure send_error was NOT called for "AttributeError".

        # If the code uses try/except generic, it will catch it and send_error.
        # We want to verify it SUCCEEDS.

        assert "sensor.test" in result
        assert len(result["sensor.test"]) > 0
