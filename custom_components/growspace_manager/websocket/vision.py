"""Vision checkup and snapshot WebSocket handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_VISION_HISTORY = f"{DOMAIN}/get_vision_history"
SCHEMA_WS_GET_VISION_HISTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_VISION_HISTORY,
        vol.Required("growspace_id"): str,
        vol.Optional("limit", default=10): vol.All(int, vol.Range(min=1, max=50)),
    }
)

WS_TYPE_UPDATE_VISION_CHECKUP_CONFIG = f"{DOMAIN}/update_vision_checkup_config"
SCHEMA_WS_UPDATE_VISION_CHECKUP_CONFIG = (
    websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
        {
            vol.Required("type"): WS_TYPE_UPDATE_VISION_CHECKUP_CONFIG,
            vol.Required("growspace_id"): str,
            vol.Optional("enabled"): bool,
            vol.Optional("early_check_offset_minutes"): vol.All(int, vol.Range(min=1)),
            vol.Optional("mid_check_hours"): vol.All(int, vol.Range(min=1)),
            vol.Optional("late_check_offset_minutes"): vol.All(int, vol.Range(min=1)),
        }
    )
)

WS_TYPE_CAPTURE_SNAPSHOT = f"{DOMAIN}/capture_snapshot"
SCHEMA_WS_CAPTURE_SNAPSHOT = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_CAPTURE_SNAPSHOT,
        vol.Required("growspace_id"): str,
    }
)

WS_TYPE_GET_SNAPSHOTS = f"{DOMAIN}/get_snapshots"
SCHEMA_WS_GET_SNAPSHOTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_SNAPSHOTS,
        vol.Required("growspace_id"): str,
        vol.Optional("limit"): int,
        vol.Optional("offset"): int,
    }
)


async def websocket_capture_snapshot(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle manual snapshot capture for a growspace."""
    growspace_id: str = msg["growspace_id"]

    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "not_loaded", str(err))
        return

    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        connection.send_error(
            msg["id"], "not_found", f"Growspace '{growspace_id}' not found"
        )
        return

    camera_entities = growspace.environment_config.camera_entities
    if not camera_entities:
        connection.send_error(
            msg["id"],
            "no_cameras",
            f"No cameras configured for growspace '{growspace_id}'",
        )
        return

    snapshot_dir = (
        Path(hass.config.path("www")) / "growspace_manager" / "snapshots" / growspace_id
    )
    snapshot_dir.mkdir(parents=True, exist_ok=True)

    timestamp = dt_util.now().strftime("%Y%m%d_%H%M%S")
    captured_paths: list[str] = []

    for camera_entity_id in camera_entities:
        safe_name = camera_entity_id.replace(".", "_").replace(" ", "_")
        filename = f"{timestamp}_{safe_name}.jpg"
        file_path = str(snapshot_dir / filename)

        try:
            await hass.services.async_call(
                "camera",
                "snapshot",
                {"entity_id": camera_entity_id, "filename": file_path},
                blocking=True,
            )
            public_path = (
                f"/local/growspace_manager/snapshots/{growspace_id}/{filename}"
            )
            captured_paths.append(public_path)
        except (AttributeError, KeyError, ValueError, HomeAssistantError, Exception):
            _LOGGER.exception(
                "Failed to capture snapshot from camera %s", camera_entity_id
            )

    connection.send_result(
        msg["id"],
        {
            "growspace_id": growspace_id,
            "timestamp": timestamp,
            "snapshots": captured_paths,
        },
    )


async def websocket_get_snapshots(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Handle listing snapshots for a growspace."""
    growspace_id: str = msg["growspace_id"]
    limit: int = msg.get("limit", 50)
    offset: int = msg.get("offset", 0)

    snapshot_dir = (
        Path(hass.config.path("www")) / "growspace_manager" / "snapshots" / growspace_id
    )

    try:
        if not snapshot_dir.exists():
            connection.send_result(msg["id"], {"snapshots": [], "total": 0})
            return

        all_files = sorted(
            snapshot_dir.glob("*.jpg"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        total = len(all_files)
        paged_files = all_files[offset : offset + limit]

        snapshots = [
            {
                "path": f"/local/growspace_manager/snapshots/{growspace_id}/{f.name}",
                "filename": f.name,
                "timestamp": f.name[:15],
            }
            for f in paged_files
        ]

        connection.send_result(
            msg["id"],
            {"growspace_id": growspace_id, "snapshots": snapshots, "total": total},
        )
    except Exception as err:
        _LOGGER.exception("Error listing snapshots for %s", growspace_id)
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_get_vision_history(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return vision checkup history for a growspace."""
    growspace_id: str = msg["growspace_id"]
    limit: int = msg.get("limit", 10)

    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "not_loaded", str(err))
        return

    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        connection.send_error(
            msg["id"], "not_found", f"Growspace {growspace_id} not found"
        )
        return

    history = [
        {
            "timestamp": r.timestamp,
            "check_type": r.check_type,
            "analysis": r.analysis,
            "issues_detected": r.issues_detected,
            "severity": r.severity,
            "recommendations": r.recommendations,
            "snapshot_paths": r.snapshot_paths,
        }
        for r in growspace.vision_checkup_history[:limit]
    ]

    connection.send_result(
        msg["id"],
        {"history": history, "total": len(growspace.vision_checkup_history)},
    )


async def websocket_update_vision_checkup_config(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Update vision checkup configuration for a growspace."""
    growspace_id: str = msg["growspace_id"]

    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "not_loaded", str(err))
        return

    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        connection.send_error(
            msg["id"], "not_found", f"Growspace {growspace_id!r} not found"
        )
        return

    if not growspace.environment_config:
        connection.send_error(
            msg["id"],
            "no_environment",
            f"No environment config for growspace {growspace_id!r}",
        )
        return

    vision_config = growspace.environment_config.vision_checkup_config
    if "enabled" in msg:
        vision_config.enabled = msg["enabled"]
    if "early_check_offset_minutes" in msg:
        vision_config.early_check_offset_minutes = msg["early_check_offset_minutes"]
    if "mid_check_hours" in msg:
        vision_config.mid_check_hours = msg["mid_check_hours"]
    if "late_check_offset_minutes" in msg:
        vision_config.late_check_offset_minutes = msg["late_check_offset_minutes"]

    await coordinator.async_commit()
    coordinator.vision_scheduler.schedule_all_growspaces()

    connection.send_result(msg["id"], {"success": True})


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_CAPTURE_SNAPSHOT, websocket_capture_snapshot, SCHEMA_WS_CAPTURE_SNAPSHOT, False),
    (WS_TYPE_GET_SNAPSHOTS, websocket_get_snapshots, SCHEMA_WS_GET_SNAPSHOTS, False),
    (WS_TYPE_GET_VISION_HISTORY, websocket_get_vision_history, SCHEMA_WS_GET_VISION_HISTORY, False),
    (WS_TYPE_UPDATE_VISION_CHECKUP_CONFIG, websocket_update_vision_checkup_config, SCHEMA_WS_UPDATE_VISION_CHECKUP_CONFIG, False),
]
