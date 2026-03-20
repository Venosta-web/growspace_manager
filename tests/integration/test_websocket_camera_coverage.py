"""Coverage tests for websocket.py camera handlers.

Covers websocket_capture_snapshot (lines 998-1050) and
websocket_get_snapshots (lines 1069-1105).
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.websocket import (
    websocket_capture_snapshot,
    websocket_get_snapshots,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError


@pytest.fixture
def mock_connection():
    """Mock WebSocket connection."""
    conn = MagicMock()
    conn.send_result = MagicMock()
    conn.send_error = MagicMock()
    return conn


def _make_growspace(camera_entities: list[str] | None = None) -> MagicMock:
    """Create a mock growspace with optional camera entities."""
    gs = MagicMock()
    gs.name = "Test GS"
    gs.environment_config = MagicMock()
    gs.environment_config.camera_entities = camera_entities or []
    return gs


def _make_coordinator(growspace: MagicMock | None = None, gs_id: str = "gs1") -> MagicMock:
    """Create a mock coordinator with an optional growspace."""
    coord = MagicMock()
    coord.growspaces = {gs_id: growspace} if growspace else {}
    return coord


# =============================================================================
# websocket_capture_snapshot tests
# =============================================================================


async def test_capture_snapshot_coordinator_not_found(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Test capture_snapshot sends error when coordinator not found (lines 1002-1006)."""
    msg = {"id": 1, "growspace_id": "gs1"}

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        side_effect=ServiceValidationError("Not loaded"),
    ):
        await websocket_capture_snapshot(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(1, "not_loaded", "Not loaded")
    mock_connection.send_result.assert_not_called()


async def test_capture_snapshot_growspace_not_found(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Test capture_snapshot sends error when growspace not found (lines 1008-1013)."""
    msg = {"id": 1, "growspace_id": "nonexistent"}
    coord = _make_coordinator()  # no growspaces

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_capture_snapshot(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(
        1, "not_found", "Growspace 'nonexistent' not found"
    )


async def test_capture_snapshot_no_cameras(
    hass: HomeAssistant, mock_connection: MagicMock
) -> None:
    """Test capture_snapshot sends error when no cameras configured (lines 1015-1022)."""
    msg = {"id": 1, "growspace_id": "gs1"}
    gs = _make_growspace(camera_entities=[])  # no cameras
    coord = _make_coordinator(growspace=gs)

    with patch(
        "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
        return_value=coord,
    ):
        await websocket_capture_snapshot(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once_with(
        1, "no_cameras", "No cameras configured for growspace 'gs1'"
    )


async def test_capture_snapshot_success(
    hass: HomeAssistant, mock_connection: MagicMock, tmp_path: Path
) -> None:
    """Test capture_snapshot captures successfully and returns paths (lines 1024-1050)."""
    msg = {"id": 1, "growspace_id": "gs1"}
    gs = _make_growspace(camera_entities=["camera.tent_cam"])
    coord = _make_coordinator(growspace=gs)

    with (
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
            return_value=coord,
        ),
        patch.object(hass.config, "path", return_value=str(tmp_path)),
        patch(
            "homeassistant.core.ServiceRegistry.async_call",
            new_callable=AsyncMock,
        ),
    ):
        await websocket_capture_snapshot(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["growspace_id"] == "gs1"
    assert len(result["snapshots"]) == 1
    assert result["snapshots"][0].startswith("/local/growspace_manager/snapshots/gs1/")


async def test_capture_snapshot_camera_service_fails(
    hass: HomeAssistant, mock_connection: MagicMock, tmp_path: Path
) -> None:
    """Test capture_snapshot continues when camera service raises exception (lines 1045-1048)."""
    msg = {"id": 1, "growspace_id": "gs1"}
    gs = _make_growspace(camera_entities=["camera.broken", "camera.ok"])
    coord = _make_coordinator(growspace=gs)

    call_count = 0

    async def _side_effect(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise Exception("Camera error")  # noqa: TRY002

    with (
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
            return_value=coord,
        ),
        patch.object(hass.config, "path", return_value=str(tmp_path)),
        patch(
            "homeassistant.core.ServiceRegistry.async_call",
            side_effect=_side_effect,
        ),
    ):
        await websocket_capture_snapshot(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    # Only the successful camera contributes a path
    assert len(result["snapshots"]) == 1
    assert "camera_ok" in result["snapshots"][0]


async def test_capture_snapshot_multiple_cameras(
    hass: HomeAssistant, mock_connection: MagicMock, tmp_path: Path
) -> None:
    """Test capture_snapshot handles multiple cameras."""
    msg = {"id": 1, "growspace_id": "gs1"}
    gs = _make_growspace(camera_entities=["camera.cam_a", "camera.cam_b"])
    coord = _make_coordinator(growspace=gs)

    with (
        patch(
            "custom_components.growspace_manager.websocket.GrowspaceCoordinator.get_for_service_call",
            return_value=coord,
        ),
        patch.object(hass.config, "path", return_value=str(tmp_path)),
        patch(
            "homeassistant.core.ServiceRegistry.async_call",
            new_callable=AsyncMock,
        ),
    ):
        await websocket_capture_snapshot(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert len(result["snapshots"]) == 2


# =============================================================================
# websocket_get_snapshots tests
# =============================================================================


async def test_get_snapshots_directory_not_exists(
    hass: HomeAssistant, mock_connection: MagicMock, tmp_path: Path
) -> None:
    """Test get_snapshots returns empty when directory doesn't exist (lines 1078-1080)."""
    msg = {"id": 1, "growspace_id": "gs_no_dir"}

    with patch.object(hass.config, "path", return_value=str(tmp_path)):
        await websocket_get_snapshots(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once_with(
        1, {"snapshots": [], "total": 0}
    )


async def test_get_snapshots_with_files(
    hass: HomeAssistant, mock_connection: MagicMock, tmp_path: Path
) -> None:
    """Test get_snapshots lists existing snapshot files (lines 1082-1102)."""
    gs_id = "gs1"
    msg = {"id": 1, "growspace_id": gs_id}

    # Create snapshot directory with some jpg files
    snap_dir = tmp_path / "www" / "growspace_manager" / "snapshots" / gs_id
    snap_dir.mkdir(parents=True)
    (snap_dir / "20260112_120000_camera_cam.jpg").write_bytes(b"fake_jpg")
    (snap_dir / "20260112_120100_camera_cam.jpg").write_bytes(b"fake_jpg")

    with patch.object(hass.config, "path", return_value=str(tmp_path / "www")):
        await websocket_get_snapshots(hass, mock_connection, msg)

    mock_connection.send_result.assert_called_once()
    result = mock_connection.send_result.call_args[0][1]
    assert result["growspace_id"] == gs_id
    assert result["total"] == 2
    assert len(result["snapshots"]) == 2
    assert all(s["path"].startswith("/local/growspace_manager/snapshots/gs1/") for s in result["snapshots"])


async def test_get_snapshots_pagination(
    hass: HomeAssistant, mock_connection: MagicMock, tmp_path: Path
) -> None:
    """Test get_snapshots respects limit and offset parameters."""
    gs_id = "gs_page"
    msg = {"id": 1, "growspace_id": gs_id, "limit": 1, "offset": 1}

    snap_dir = tmp_path / "www" / "growspace_manager" / "snapshots" / gs_id
    snap_dir.mkdir(parents=True)
    for i in range(3):
        (snap_dir / f"2026011{i}_120000_cam.jpg").write_bytes(b"x")

    with patch.object(hass.config, "path", return_value=str(tmp_path / "www")):
        await websocket_get_snapshots(hass, mock_connection, msg)

    result = mock_connection.send_result.call_args[0][1]
    assert result["total"] == 3
    assert len(result["snapshots"]) == 1  # limited to 1


async def test_get_snapshots_exception(
    hass: HomeAssistant, mock_connection: MagicMock, tmp_path: Path
) -> None:
    """Test get_snapshots handles unexpected exceptions (lines 1103-1105)."""
    gs_id = "gs_err"
    msg = {"id": 1, "growspace_id": gs_id}

    # Create the directory so it exists, but make glob raise
    snap_dir = tmp_path / "www" / "growspace_manager" / "snapshots" / gs_id
    snap_dir.mkdir(parents=True)

    with (
        patch.object(hass.config, "path", return_value=str(tmp_path / "www")),
        patch("pathlib.Path.glob", side_effect=PermissionError("Access denied")),
    ):
        await websocket_get_snapshots(hass, mock_connection, msg)

    mock_connection.send_error.assert_called_once()
    error_args = mock_connection.send_error.call_args[0]
    assert error_args[0] == 1
    assert error_args[1] == "unknown_error"
