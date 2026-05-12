"""Test init module coverage."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from aiohttp import web
import pytest
from tests.common import MockConfigEntry

from custom_components.growspace_manager import (
    async_reload_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.growspace_manager.const import (
    ATTR_IMAGES,
    ATTR_NOTES,
    ATTR_PLANT_ID,
    DOMAIN,
)
from custom_components.growspace_manager.views import StrainLibraryImageView
from custom_components.growspace_manager.websocket import (
    _downsample_entity_binary_search,
    websocket_add_timeline_note,
    websocket_get_event_log,
    websocket_get_growspace_data,
    websocket_get_history_stats,
    websocket_get_ipm_presets,
    websocket_get_nutrient_presets,
    websocket_remove_timeline_event,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

# --- Websocket Tests ---


async def test_websocket_commands_errors(hass: HomeAssistant) -> None:
    """Test websocket command error handling."""
    connection = MagicMock()
    msg = {"id": 1, "type": "test"}

    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("Coord Fail"),
    ):
        websocket_get_nutrient_presets(hass, connection, msg)
        connection.send_error.assert_called_with(1, "unknown_error", "Coord Fail")

    connection.reset_mock()
    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("Coord Fail"),
    ):
        websocket_get_ipm_presets(hass, connection, msg)
        connection.send_error.assert_called_with(1, "unknown_error", "Coord Fail")


async def test_websocket_add_timeline_note(hass: HomeAssistant) -> None:
    """Test add timeline note websocket command."""
    connection = MagicMock()
    msg = {
        "id": 1,
        ATTR_PLANT_ID: "plant1",
        ATTR_NOTES: "test",
        ATTR_IMAGES: ["base64..."],
    }

    mock_coordinator = MagicMock()
    mock_add_note = AsyncMock()
    mock_coordinator.services.add_timeline_note = mock_add_note

    mock_strain_lib = MagicMock()
    hass.data[DOMAIN] = {"strain_library": mock_strain_lib}

    with (
        patch(
            "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
            return_value=mock_coordinator,
        ),
    ):
        await websocket_add_timeline_note(hass, connection, msg)
        connection.send_result.assert_called_with(1)

        mock_add_note.side_effect = Exception("Boom")
        msg["id"] = 3
        await websocket_add_timeline_note(hass, connection, msg)
        connection.send_error.assert_called_with(3, "unknown_error", "Boom")


async def test_websocket_remove_timeline_event(hass: HomeAssistant) -> None:
    """Test remove timeline event logic."""
    connection = MagicMock()
    msg = {"id": 1, "event_id": "evt1"}

    with patch(
        "custom_components.growspace_manager.websocket.get_instance"
    ) as mock_get_instance:
        mock_recorder = MagicMock()
        mock_get_instance.return_value = mock_recorder

        async def async_run_job(job, *args):
            return job(*args) if callable(job) else None

        mock_recorder.async_add_executor_job.side_effect = async_run_job

        with patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_scope:
            mock_session = MagicMock()
            mock_scope.return_value.__enter__.return_value = mock_session
            mock_session.query.return_value.filter.return_value = (
                mock_session  # chaining
            )

            await websocket_remove_timeline_event(hass, connection, msg)
            connection.send_result.assert_called_with(1)
            mock_session.delete.assert_called_once()


# --- Unload Entry Tests ---


async def test_async_unload_entry(hass: HomeAssistant) -> None:
    """Test unloading."""
    entry = MagicMock()
    entry.entry_id = "test"
    entry.runtime_data = MagicMock()

    mock_strain_lib = AsyncMock()
    hass.data[DOMAIN] = {"strain_library": mock_strain_lib}

    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry) is True
        mock_strain_lib.async_close.assert_called_once()
        assert "strain_library" not in hass.data[DOMAIN]

    # Reset for Failure Test
    mock_strain_lib.reset_mock()
    hass.data[DOMAIN] = {"strain_library": mock_strain_lib}

    # Test Failure
    with patch.object(
        hass.config_entries, "async_unload_platforms", return_value=False
    ):
        assert await async_unload_entry(hass, entry) is False
        # Verify NO strain library cleanup
        mock_strain_lib.async_close.assert_not_called()


# --- Async Reload Test ---


async def test_async_reload_entry(hass: HomeAssistant) -> None:
    """Test reloading entry."""
    entry = MagicMock()
    entry.entry_id = "test"

    with patch.object(
        hass.config_entries, "async_reload", new_callable=AsyncMock
    ) as mock_reload:
        await async_reload_entry(hass, entry)
        mock_reload.assert_called_once_with("test")


# --- Websocket Get Growspace Data Test ---


async def test_websocket_get_growspace_data_errors(hass: HomeAssistant) -> None:
    """Test websocket get growspace data errors."""

    connection = MagicMock()
    msg = {"id": 1, "growspace_id": "gs1"}

    # 1. ServiceValidationError
    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        side_effect=ServiceValidationError("Invalid"),
    ):
        await websocket_get_growspace_data(hass, connection, msg)
        connection.send_error.assert_called_with(1, "not_loaded", "Growspace Manager integration not loaded")

    # 2. General Exception
    connection.reset_mock()
    with patch(
        "custom_components.growspace_manager.GrowspaceCoordinator.get_for_service_call",
        side_effect=Exception("Boom"),
    ):
        await websocket_get_growspace_data(hass, connection, msg)
        connection.send_error.assert_called_with(1, "unknown_error", "Boom")


# --- Pending Growspace Failure Test ---


async def test_async_setup_entry_pending_growspace_failure(hass: HomeAssistant) -> None:
    """Test logic when pending growspace creation fails."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "pending_growspace": {"name": "Test Room", "rows": 1, "plants_per_row": 1}
        },
        options={},
    )
    entry.add_to_hass(hass)

    # Store Mock Setup to handle Generics Store[...]
    mock_store_instance = MagicMock()
    mock_store_instance.async_load = AsyncMock(return_value={})

    # The class mock needs to return a mock when __getitem__ is called
    mock_store_cls = MagicMock()
    # Store[...] -> returns child mock. We want that child mock to return instance when called.
    mock_store_cls.__getitem__.return_value.return_value = mock_store_instance
    # Fallback for non-generic usage
    mock_store_cls.return_value = mock_store_instance

    mock_coordinator = MagicMock()
    mock_coordinator.async_load = AsyncMock()
    mock_coordinator.async_initialize_sub_coordinators = AsyncMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()

    # Public properties for services
    type(mock_coordinator).growspace_service = property(
        lambda self: self.growspace_manager
    )

    mock_coordinator.growspace_manager = MagicMock()
    mock_coordinator.growspace_manager.add_growspace = AsyncMock(
        side_effect=RuntimeError("Creation failed")
    )

    mock_strain_lib = MagicMock()
    mock_strain_lib.async_setup = AsyncMock()

    hass.data[DOMAIN] = {}
    hass.http = MagicMock()  # Mock HTTP component
    hass.http.async_register_static_paths = AsyncMock()

    with (
        patch("custom_components.growspace_manager.Store", mock_store_cls),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=mock_strain_lib,
        ),
        patch(
            "custom_components.growspace_manager.coordinator.GrowspaceCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.service_registration.register_services",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.async_create_issue"
        ) as mock_create_issue,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
    ):
        assert await async_setup_entry(hass, entry) is True

        mock_create_issue.assert_called_once()


# --- Websocket Get Event Log Coverage ---


async def test_websocket_get_event_log_coverage(hass: HomeAssistant) -> None:
    """Test get_event_log coverage for limits and error paths."""
    connection = MagicMock()
    msg = {"id": 1, "growspace_id": "gs1", "limit": 10}

    # 1. Test Event Type Not Found
    with (
        patch(
            "custom_components.growspace_manager.websocket.get_instance"
        ) as mock_get_instance,
        patch(
            "custom_components.growspace_manager.websocket.session_scope"
        ) as mock_session_scope,
    ):
        mock_recorder = MagicMock()
        mock_get_instance.return_value = mock_recorder

        # Mock executor job to run the inner function immediately
        async def async_run_job(job, *args):
            return job(*args)

        mock_recorder.async_add_executor_job.side_effect = async_run_job

        mock_session = MagicMock()
        mock_session_scope.return_value.__enter__.return_value = mock_session

        # Query for event_type returns None
        mock_session.query.return_value.filter.return_value.first.return_value = None

        await websocket_get_event_log(hass, connection, msg)

        # Should return empty result for growspace
        connection.send_result.assert_called_with(1, {"gs1": []})

    # 2. Test Recorder Import/Key Error
    connection.reset_mock()
    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=ImportError,
    ):
        await websocket_get_event_log(hass, connection, msg)
        connection.send_result.assert_called_with(1, {"gs1": []})

    # 3. Test General Exception
    connection.reset_mock()
    with patch(
        "custom_components.growspace_manager.websocket.get_instance",
        side_effect=ValueError("Boom"),
    ):
        await websocket_get_event_log(hass, connection, msg)
        connection.send_error.assert_called_with(1, "unknown_error", "Boom")


async def test_websocket_history_stats_coverage(hass: HomeAssistant) -> None:
    """Test attributes of history stats not covered by main tests."""
    connection = MagicMock()
    # Invalid start time
    msg_invalid = {
        "id": 1,
        "entity_ids": ["sensor.test"],
        "start_time": "invalid",
        "interval_minutes": 5,
        "type": "custom_components.growspace_manager/get_history_stats",
    }

    await websocket_get_history_stats(hass, connection, msg_invalid)
    connection.send_error.assert_called_with(1, "invalid_args", "Invalid start_time")

    # Verify fallback when interval is small (handled by logic, but ensuring stats API skipped)
    msg_short = {
        "id": 2,
        "entity_ids": ["sensor.test"],
        "start_time": "2023-01-01T12:00:00Z",
        "end_time": "2023-01-01T13:00:00Z",
        "interval_minutes": 5,  # < 60, skips stats API
        "type": "custom_components.growspace_manager/get_history_stats",
    }

    with (
        patch(
            "custom_components.growspace_manager.websocket._get_statistics_data"
        ) as mock_stats,
        patch(
            "custom_components.growspace_manager.websocket._get_history_with_binary_search_downsample"
        ) as mock_downsample,
    ):
        mock_downsample.return_value = {"sensor.test": []}
        await websocket_get_history_stats(hass, connection, msg_short)

        mock_stats.assert_not_called()
        mock_downsample.assert_called_once()
        connection.send_result.assert_called_with(2, {"sensor.test": []})

    # Verify exception handling
    connection.reset_mock()
    # Verify exception handling
    connection.reset_mock()
    # Patch something inside the try block (e.g. _get_statistics_data, but we need to ensure it's called)
    # Or properly patch _get_statistics_data to raise
    with patch(
        "custom_components.growspace_manager.websocket._get_statistics_data",
        side_effect=ValueError("Boom"),
    ):
        # Ensure we use a large interval so _get_statistics_data is called
        msg_long = msg_short.copy()
        msg_long["interval_minutes"] = 120
        await websocket_get_history_stats(hass, connection, msg_long)
        connection.send_error.assert_called_with(2, "unknown_error", "Boom")


def test_downsample_binary_search_logic() -> None:
    """Directly test the binary search downsample logic for edge cases."""

    start = datetime(2023, 1, 1, 12, 0, 0, tzinfo=UTC)
    interval = timedelta(minutes=10)
    end = start + timedelta(minutes=30)

    # State with valid and invalid timestamps
    s1 = Mock(state="10", last_updated=start)
    s2 = Mock(
        state="unknown", last_updated=start + timedelta(minutes=5)
    )  # Should be skipped by value
    s4 = Mock(state="30", last_updated=start + timedelta(minutes=20))
    # Note: Binary search requires sorted input. Sentinel logic assumes valid sorted order.

    states = [s1, s2, s4]

    result = _downsample_entity_binary_search(states, start, end, interval)

    # Should find s1 (at 12:00), skip s2 (12:05 unknown), skip s3 (bad ts), find s4 (12:20)
    # 12:00 -> s1
    # 12:10 -> s1 (closest previous) is technically s2 but it's unknown?
    # Actually bisect_right finds the insertion point.
    # Logic: bisect_right finds first element > current_time. idx - 1 is the element <= current_time.

    # Trace:
    # T=12:00: bisect > finding s1 (equal). idx might be s1 or s2 depending on strictness.
    # T=12:10: bisect > s2 (12:05). s2 is unknown. Loop continues? No, logic grabs s[idx].
    # If s[idx] is unknown/invalid, it just appends it?
    # Code: if state_val and state_val not in ("unknown", ...): append
    # So s2 is skipped.

    # Expected:
    # 12:00 -> s1 ('10')
    # 12:10 -> s2 (unknown) -> skipped
    # 12:20 -> s4 ('30')
    # 12:30 -> s4 ('30')

    assert len(result) >= 1
    assert result[0]["s"] == "10"
    assert result[-1]["s"] == "30"


@pytest.mark.asyncio
async def test_image_view_security(hass: HomeAssistant, tmp_path: Path) -> None:
    """Test security checks in StrainLibraryImageView."""
    strain_lib = MagicMock()
    image_manager = MagicMock()
    strain_lib.image_manager = image_manager
    image_manager.storage_dir = tmp_path

    view = StrainLibraryImageView(hass, strain_lib)
    request = Mock(spec=web.Request)

    # Test Directory Traversal
    response = await view.get(request, "../../../etc/passwd")
    assert response.status == 403
    assert response.text == "Access denied"

    # Test file validation exception (e.g. resolve fails)
    with patch("pathlib.Path.resolve", side_effect=Exception("Perm Error")):
        response = await view.get(request, "valid.jpg")
        assert response.status == 500
