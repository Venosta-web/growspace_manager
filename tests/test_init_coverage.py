"""Test init module coverage."""

import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from aiohttp import web
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager import (
    StrainLibraryImageView,
    websocket_get_event_log,
)

mock_logbook = MagicMock()
sys.modules["homeassistant.components.logbook"] = mock_logbook


async def test_strain_library_image_view(hass: HomeAssistant) -> None:
    """Test StrainLibraryImageView logic."""
    strain_lib = MagicMock()
    view = StrainLibraryImageView(hass, strain_lib)

    request = Mock(spec=web.Request)

    strain_lib.image_manager = None
    response = await view.get(request, "image.jpg")
    assert response.status == 404
    assert response.text == "Image manager not available"

    image_manager = MagicMock()
    strain_lib.image_manager = image_manager

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        image_manager.storage_dir = tmp_path
        (tmp_path / "test.jpg").touch()

        response = await view.get(request, "test.jpg")
        assert isinstance(response, web.FileResponse)

        response = await view.get(request, "missing.jpg")
        assert response.status == 404
        assert response.text == "Image not found"

        response = await view.get(request, "../outside.txt")
        assert response.status == 403
        assert response.text == "Access denied"


async def test_websocket_get_event_log_spam_limit(hass: HomeAssistant) -> None:
    """Test spam limit in websocket_get_event_log."""

    with (
        patch("custom_components.growspace_manager.get_instance") as mock_get_instance,
        patch(
            "custom_components.growspace_manager.session_scope"
        ) as mock_session_scope,
    ):
        mock_recorder = MagicMock()
        mock_get_instance.return_value = mock_recorder

        mock_session = MagicMock()
        mock_session_scope.return_value.__enter__.return_value = mock_session
        mock_session.query.return_value.filter.return_value.first.return_value = [1]

        spammy_events = []
        for i in range(250):
            event_row = MagicMock()
            event_row.event_id = i
            event_row.time_fired_ts = 1000 + i
            event_data_row = MagicMock()
            event_data_row.shared_data = (
                f'{{"category": "optimal", "growspace_id": "gs1", "notes": "spam {i}"}}'
            )
            spammy_events.append((event_row, event_data_row))

        mock_session.query.return_value.join.return_value.filter.return_value.order_by.return_value = spammy_events

        async def run_job(target, *args, **kwargs):
            return target(*args, **kwargs)

        mock_recorder.async_add_executor_job.side_effect = run_job

        connection = MagicMock()
        msg = {"id": 1, "growspace_id": "gs1", "limit": 1000}

        await websocket_get_event_log(hass, connection, msg)

        connection.send_result.assert_called_once()
        result = connection.send_result.call_args[0][1]
        events = result["gs1"]
        spammy_count = sum(1 for e in events if e["category"] == "optimal")
        assert spammy_count == 200
