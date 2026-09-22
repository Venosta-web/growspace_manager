"""Vision checkup and snapshot WebSocket handlers."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.presentation.vision import (
    async_serialize_vision_checkup,
    serialize_legacy_vision_result,
    serialize_vision_status,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
import homeassistant.util.dt as dt_util

from ._common import WSCommand

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_VISION_HISTORY = f"{DOMAIN}/get_vision_history"
SCHEMA_WS_GET_VISION_HISTORY = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_VISION_HISTORY,
        vol.Required("growspace_id"): str,
        vol.Optional("limit", default=10): vol.All(int, vol.Range(min=1, max=50)),
    }
)

WS_TYPE_GET_VISION_HISTORY_V2 = f"{DOMAIN}/get_vision_history_v2"
SCHEMA_WS_GET_VISION_HISTORY_V2 = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_VISION_HISTORY_V2,
        vol.Required("growspace_id"): str,
        vol.Optional("limit", default=10): vol.All(int, vol.Range(min=1, max=50)),
    }
)

WS_TYPE_GET_VISION_STATUS = f"{DOMAIN}/get_vision_status"
SCHEMA_WS_GET_VISION_STATUS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {vol.Required("type"): WS_TYPE_GET_VISION_STATUS}
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


def _get_growspace(coordinator: GrowspaceCoordinator, growspace_id: str) -> Any:
    """Resolve a growspace or raise the typed not-found error."""
    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        raise GrowspaceNotFoundError(f"Growspace '{growspace_id}' not found")
    return growspace


async def websocket_capture_snapshot(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle manual snapshot capture for a growspace."""
    growspace_id: str = msg["growspace_id"]
    growspace = _get_growspace(coordinator, growspace_id)

    camera_entities = growspace.environment_config.camera_entities
    if not camera_entities:
        raise ServiceValidationError(
            f"No cameras configured for growspace '{growspace_id}'"
        )

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
        except AttributeError, KeyError, ValueError, HomeAssistantError, Exception:
            _LOGGER.exception(
                "Failed to capture snapshot from camera %s", camera_entity_id
            )

    return {
        "growspace_id": growspace_id,
        "timestamp": timestamp,
        "snapshots": captured_paths,
    }


async def websocket_get_snapshots(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Handle listing snapshots for a growspace."""
    growspace_id: str = msg["growspace_id"]
    limit: int = msg.get("limit", 50)
    offset: int = msg.get("offset", 0)

    snapshot_dir = (
        Path(hass.config.path("www")) / "growspace_manager" / "snapshots" / growspace_id
    )

    if not snapshot_dir.exists():
        return {"growspace_id": growspace_id, "snapshots": [], "total": 0}

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

    return {"growspace_id": growspace_id, "snapshots": snapshots, "total": total}


async def websocket_get_vision_history(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return vision checkup history for a growspace."""
    growspace = _get_growspace(coordinator, msg["growspace_id"])
    limit: int = msg.get("limit", 10)

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

    return {"history": history, "total": len(growspace.vision_checkup_history)}


async def websocket_get_vision_status(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return the cached Growspace Vision service status."""
    return serialize_vision_status(coordinator.vision_connection.status)


async def websocket_get_vision_history_v2(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Return versioned Vision Checkups with a frozen attributed legacy tail."""
    growspace = _get_growspace(coordinator, msg["growspace_id"])
    limit: int = msg.get("limit", 10)
    store = hass.data.get(DOMAIN, {}).get("vision_evidence_store")
    v1: list[dict[str, Any]] = []
    v1_total = 0
    capture_total = 0
    if store is not None:
        media_dirs = hass.config.media_dirs
        media_source = "local" if "local" in media_dirs else next(iter(media_dirs))
        checkups = await store.async_get_checkups(msg["growspace_id"], limit=limit)
        v1 = [
            await async_serialize_vision_checkup(
                store, checkup, media_source=media_source
            )
            for checkup in checkups
        ]
        v1_total = await store.async_count_checkups(msg["growspace_id"])
        capture_total = await store.async_count_captures(msg["growspace_id"])
    legacy = [
        serialize_legacy_vision_result(item)
        for item in growspace.vision_checkup_history
    ]
    history = sorted(v1 + legacy, key=_vision_history_timestamp, reverse=True)[:limit]
    return {
        "history": history,
        "total": v1_total + len(legacy),
        "capture_total": capture_total,
    }


def _vision_history_timestamp(item: dict[str, Any]) -> str:
    """Return the chronology key shared only by the public union."""
    if item["result_schema"] == "legacy_cloud_v1":
        return str(item["timestamp"])
    return str(item["completed_at"] or item["started_at"])


async def websocket_update_vision_checkup_config(
    hass: HomeAssistant, coordinator: GrowspaceCoordinator, msg: dict[str, Any]
) -> dict[str, Any]:
    """Update vision checkup configuration for a growspace."""
    growspace = _get_growspace(coordinator, msg["growspace_id"])

    if not growspace.environment_config:
        raise ServiceValidationError(
            f"No environment config for growspace {msg['growspace_id']!r}"
        )

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

    return {"success": True}


COMMANDS: list[WSCommand] = [
    WSCommand(
        WS_TYPE_CAPTURE_SNAPSHOT, websocket_capture_snapshot, SCHEMA_WS_CAPTURE_SNAPSHOT
    ),
    WSCommand(WS_TYPE_GET_SNAPSHOTS, websocket_get_snapshots, SCHEMA_WS_GET_SNAPSHOTS),
    WSCommand(
        WS_TYPE_GET_VISION_STATUS,
        websocket_get_vision_status,
        SCHEMA_WS_GET_VISION_STATUS,
    ),
    WSCommand(
        WS_TYPE_GET_VISION_HISTORY_V2,
        websocket_get_vision_history_v2,
        SCHEMA_WS_GET_VISION_HISTORY_V2,
    ),
    WSCommand(
        WS_TYPE_GET_VISION_HISTORY,
        websocket_get_vision_history,
        SCHEMA_WS_GET_VISION_HISTORY,
    ),
    WSCommand(
        WS_TYPE_UPDATE_VISION_CHECKUP_CONFIG,
        websocket_update_vision_checkup_config,
        SCHEMA_WS_UPDATE_VISION_CHECKUP_CONFIG,
    ),
]
