"""Simple coverage tests for __init__.py."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from aiohttp import web

from custom_components.growspace_manager.const import ATTR_NOTES, DOMAIN
from custom_components.growspace_manager.views import StrainLibraryImageView
from custom_components.growspace_manager.websocket import (
    websocket_add_timeline_note,
    websocket_get_event_log,
    websocket_get_ipm_presets,
    websocket_get_nutrient_presets,
    websocket_get_strain_library,
    websocket_remove_timeline_event,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

# ========================================================================================
# StrainLibraryImageView Tests
# ========================================================================================


async def test_strain_library_image_view_errors(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Test StrainLibraryImageView error handling."""
    strain_lib = MagicMock()
    # Case 1: image_manager is None -> 404
    strain_lib.image_manager = None

    view = StrainLibraryImageView(hass, strain_lib)
    request = MagicMock(spec=web.Request)
    request.app = {"hass": hass}
    request.match_info = {"filename": "test.jpg"}

    response = await view.get(request, "test.jpg")
    assert response.status == 404

    # Case 2: Generic exception (e.g. resolve fails) -> 500
    # Simulate image_manager existing but raising scenarios
    strain_lib.image_manager = MagicMock()
    strain_lib.image_manager.storage_dir = tmp_path / "test"

    # We need to force an exception inside the try block
    # One way: patch Path.resolve to raise
    with patch("pathlib.Path.resolve", side_effect=Exception("Boom")):
        response = await view.get(request, "test.jpg")
        assert response.status == 500


async def test_strain_library_image_view_filesystem_errors(
    hass: HomeAssistant, tmp_path: Path
) -> None:
    """Test filesystem errors in image view."""
    strain_lib = MagicMock()
    strain_lib.image_manager = MagicMock()
    strain_lib.image_manager.storage_dir = tmp_path

    view = StrainLibraryImageView(hass, strain_lib)
    request = MagicMock(spec=web.Request)
    request.app = {"hass": hass}
    request.match_info = {"filename": "test.jpg"}

    # Test 1: File not found -> 404
    # Ensure file doesn't exist
    response = await view.get(request, "test.jpg")
    assert response.status == 404


# ========================================================================================
# WebSocket Simple Getters Tests (Error Handling)
# ========================================================================================


async def test_websocket_simple_getters_error_handling(hass: HomeAssistant) -> None:
    """Test error handling in simple websocket getters."""
    connection = MagicMock()
    msg = {"id": 1}

    # 1. websocket_get_strain_library
    # Case A: Strain library not in hass.data
    if DOMAIN in hass.data:
        del hass.data[DOMAIN]

    websocket_get_strain_library(hass, connection, msg)
    connection.send_error.assert_called_with(
        1, "not_loaded", "Growspace Manager strain library not loaded"
    )

    # Case B: Exception during get_all()
    hass.data[DOMAIN] = {}
    strain_lib = MagicMock()
    strain_lib.get_all.side_effect = Exception("Boom")
    hass.data[DOMAIN]["strain_library"] = strain_lib

    websocket_get_strain_library(hass, connection, msg)
    # Check that send_error was called (ignoring arguments from previous call)
    assert connection.send_error.call_count == 2

    # 2. websocket_get_nutrient_presets
    # Mock GrowspaceCoordinator.get_for_service_call to return our mock
    coordinator = MagicMock()
    coordinator.nutrient_manager = MagicMock()

    # Make get_serialization_data raise exception
    coordinator.nutrient_manager.get_serialization_data.side_effect = Exception(
        "Nutrient Fail"
    )

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        websocket_get_nutrient_presets(hass, connection, msg)
        assert connection.send_error.call_count == 3

    # 3. websocket_get_ipm_presets
    # Re-setup mock for second call
    coordinator.nutrient_manager.get_serialization_data.side_effect = Exception(
        "IPM Fail"
    )

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=coordinator,
    ):
        websocket_get_ipm_presets(hass, connection, msg)
        assert connection.send_error.call_count == 4


# ========================================================================================
# WebSocket Timeline Operations Tests (Error Handling)
# ========================================================================================


async def test_websocket_timeline_operations_errors(hass: HomeAssistant) -> None:
    """Test error handling in timeline operations."""
    connection = MagicMock()
    # 1. websocket_remove_timeline_event
    msg_remove = {"id": 1, "plant_id": "p1", "event_id": 123}

    # This uses recorder directly.
    # Mock get_instance to raise or fail.
    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=Exception("Recorder Fail"),
    ):
        await websocket_remove_timeline_event(hass, connection, msg_remove)
        connection.send_error.assert_called_with(1, "unknown_error", "Recorder Fail")

    # 2. websocket_add_timeline_note
    msg_note = {
        "id": 2,
        "plant_id": "p1",
        ATTR_NOTES: "text",
        "type": "add_timeline_note",
    }

    # Mock get_for_service_call and hass.data for strain lib
    mock_coordinator = MagicMock()
    mock_coordinator.plants = {
        "p1": MagicMock()
    }  # Ensure plant exists so it doesn't reload

    mock_strain_lib = MagicMock()
    hass.data[DOMAIN] = {"strain_library": mock_strain_lib}

    # IMPORTANT: We must patch get_for_service_call to return mock_coordinator
    # AND patch async_add_timeline_note in custom_components.growspace_manager because it's imported there

    with patch(
        "custom_components.growspace_manager.coordinator.GrowspaceCoordinator.get_for_service_call",
        return_value=mock_coordinator,
    ):
        # Case A: ServiceValidationError in services/plant helper
        # Patch where it is USED in __init__.py
        with patch(
            "custom_components.growspace_manager.websocket.async_add_timeline_note",
            side_effect=ServiceValidationError("Invalid"),
        ):
            await websocket_add_timeline_note(hass, connection, msg_note)
            connection.send_error.assert_called_with(2, "invalid_args", "Invalid")

        # Case B: Generic Exception
        with patch(
            "custom_components.growspace_manager.websocket.async_add_timeline_note",
            side_effect=Exception("General"),
        ):
            await websocket_add_timeline_note(hass, connection, msg_note)
            connection.send_error.assert_called_with(2, "unknown_error", "General")


# ========================================================================================
# WebSocket Event Log Complex Logic Test
# ========================================================================================


async def test_websocket_event_log_complex_logic(hass: HomeAssistant) -> None:
    """Test websocket_get_event_log complex filtering and limits."""
    connection = MagicMock()
    msg = {"id": 1, "growspace_id": "g1", "limit": 5}

    # Mock query chain
    # We patch session_scope in custom_components.growspace_manager
    # Note: custom_components.growspace_manager imports valid session_scope from recorder.util

    session_mock = MagicMock()
    query_mock = MagicMock()
    session_mock.query.return_value = query_mock
    query_mock.join.return_value = query_mock
    # Handle multiple filters
    query_mock.filter.return_value = query_mock
    query_mock.order_by.return_value = query_mock
    query_mock.limit.return_value = query_mock

    # Helper to create event mock
    def mk_event(eid, ts, shared):
        e = MagicMock()
        e.event_id = eid
        e.time_fired_ts = ts
        d = MagicMock() if shared is not None else None
        if d:
            d.shared_data = shared
        return (e, d)

    row1 = mk_event(
        1, 1000.0, json.dumps({"category": "irrigation", "growspace_id": "g1"})
    )
    row2 = mk_event(2, 2000.0, json.dumps({"category": "alert", "growspace_id": "g1"}))
    row3 = mk_event(3, 3000.0, "{bad json")
    row4 = mk_event(
        4, 4000.0, json.dumps({"category": "alert", "growspace_id": "other"})
    )
    row5 = mk_event(5, 5000.0, None)  # No data

    # IMPORTANT: __iter__ return value must be iterator
    query_mock.__iter__.return_value = iter([row1, row2, row3, row4, row5])

    # Context Manager for session_scope
    context_manager_mock = MagicMock()
    context_manager_mock.__enter__.return_value = session_mock

    with (
        patch(
            "custom_components.growspace_manager.websocket.session_scope",
            return_value=context_manager_mock,
        ),
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as get_instance_mock,
    ):
        # We need to mock async_add_executor_job to run the query function immediately
        # The integration code calls: await recorder.async_add_executor_job(_query_events)
        instance = get_instance_mock.return_value

        async def fake_executor(func, *args):
            return func(*args)

        instance.async_add_executor_job.side_effect = fake_executor

        await websocket_get_event_log(hass, connection, msg)

        # Verify result
        connection.send_result.assert_called()
        args = connection.send_result.call_args[0]
        result_data = args[1]

        assert "g1" in result_data
        events = result_data["g1"]
        # Expected: row1, row2. row3 bad json, row4 other id, row5 no data.
        assert len(events) == 2
        assert events[0]["event_id"] == 1
        assert events[1]["event_id"] == 2
