"""Environment history and sensor coordinate WebSocket handlers."""

from __future__ import annotations

import bisect
from datetime import datetime, timedelta
import logging
from typing import Any

import voluptuous as vol

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.components import websocket_api
from homeassistant.components.recorder import (
    get_instance,
    history,
    statistics as recorder_stats,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import homeassistant.util.dt as dt_util

from ._common import _EPOCH_SENTINEL, _extract_ts

_LOGGER = logging.getLogger(__name__)

_SPARSE_ENTITY_THRESHOLD = 200

WS_TYPE_GET_HISTORY_STATS = f"{DOMAIN}/get_history_stats"
SCHEMA_WS_GET_HISTORY_STATS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_HISTORY_STATS,
        vol.Required("entity_ids"): [str],
        vol.Required("start_time"): str,
        vol.Optional("end_time"): str,
        vol.Optional("interval_minutes", default=5): int,
        vol.Optional("significant_changes_only", default=True): bool,
    }
)

WS_TYPE_UPDATE_SENSOR_COORDINATES = f"{DOMAIN}/update_sensor_coordinates"
SCHEMA_WS_UPDATE_SENSOR_COORDINATES = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_UPDATE_SENSOR_COORDINATES,
        vol.Required("growspace_id"): str,
        vol.Required("entity_id"): str,
        vol.Required("x"): int,
        vol.Required("y"): int,
        vol.Required("z"): int,
        vol.Optional("rotation"): int,
    }
)


async def _get_statistics_data(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_time: datetime,
    end_time: datetime,
    interval: int,
) -> dict[str, list[dict[str, Any]]] | None:
    """Fetch data using Recorder Statistics API (pre-aggregated hourly data)."""
    if interval >= 1440:
        period = "day"
    elif interval >= 60:
        period = "hour"
    else:
        return None

    try:
        if hasattr(recorder_stats, "async_statistics_during_period"):
            stats_data = await recorder_stats.async_statistics_during_period(
                hass,
                start_time,
                end_time,
                set(entity_ids),
                period,
                None,
                {"mean", "state"},
            )
        else:
            stats_data = await get_instance(hass).async_add_executor_job(
                recorder_stats.statistics_during_period,
                hass,
                start_time,
                end_time,
                set(entity_ids),
                period,
                None,
                {"mean", "state"},
            )

        if not stats_data:
            return None

        result: dict[str, list[dict[str, Any]]] = {}
        for entity_id in entity_ids:
            if entity_id in stats_data:
                points = stats_data[entity_id]
                result[entity_id] = []
                for p in points:
                    val = p.get("mean")
                    if val is None:
                        val = p.get("state")

                    if val is not None:
                        result[entity_id].append(
                            {
                                "s": str(val),
                                "lu": (
                                    dt_util.utc_from_timestamp(p["start"]).isoformat()
                                    if isinstance(p["start"], (int, float))
                                    else p["start"]
                                ),
                            }
                        )
            else:
                result[entity_id] = []

    except (
        AttributeError,
        KeyError,
        ValueError,
        ServiceValidationError,
        GrowspaceError,
        Exception,  # noqa: BLE001
    ):
        _LOGGER.debug("Statistics API failed, falling back to raw history")
        return None
    else:
        return result


def _downsample_entity_binary_search(
    states: list[Any],
    start_time: datetime,
    end_time: datetime,
    interval_delta: timedelta,
) -> list[dict[str, Any]]:
    """Downsample states using binary search with finger optimization."""
    downsampled = []
    current_time = start_time
    last_idx = 0

    while current_time <= end_time:
        idx = (
            bisect.bisect_right(states, current_time, key=_extract_ts, lo=last_idx) - 1
        )

        if idx >= 0:
            last_idx = idx
            s = states[idx]

            if _extract_ts(s) == _EPOCH_SENTINEL:
                current_time += interval_delta
                continue

            if isinstance(s, dict):
                state_val = s.get("state")
            else:
                state_val = s.state

            if state_val and state_val not in ("unknown", "unavailable"):
                downsampled.append(
                    {
                        "s": state_val,
                        "lu": current_time.isoformat(),
                    }
                )
        else:
            last_idx = 0

        current_time += interval_delta
    return downsampled


def _extract_fan_attrs(s: Any) -> dict[str, Any]:
    """Extract percentage attribute from a fan entity state for compact history."""
    if isinstance(s, dict):
        pct = (s.get("attributes") or {}).get("percentage")
    else:
        pct = (getattr(s, "attributes", None) or {}).get("percentage")
    return {"percentage": pct} if pct is not None else {}


async def _get_history_with_binary_search_downsample(
    hass: HomeAssistant,
    entity_ids: list[str],
    start_time: datetime,
    end_time: datetime,
    interval: int,
) -> dict[str, list[dict[str, Any]]]:
    """Fetch raw history and downsample using optimized binary search."""

    fan_ids = {eid for eid in entity_ids if eid.startswith("fan.")}
    other_ids = [eid for eid in entity_ids if eid not in fan_ids]

    def _get_history() -> dict[str, list[Any]]:
        result: dict[str, list[Any]] = {}
        if other_ids:
            result.update(
                history.get_significant_states(
                    hass,
                    start_time,
                    end_time,
                    other_ids,
                    significant_changes_only=True,
                    minimal_response=True,
                    no_attributes=True,
                )
            )
        if fan_ids:
            result.update(
                history.get_significant_states(
                    hass,
                    start_time,
                    end_time,
                    list(fan_ids),
                    significant_changes_only=True,
                    minimal_response=False,
                    no_attributes=False,
                )
            )
        return result

    history_data = await get_instance(hass).async_add_executor_job(_get_history)

    def _downsample_with_binary_search() -> dict[str, list[dict[str, Any]]]:
        result: dict[str, list[dict[str, Any]]] = {}
        interval_delta = timedelta(minutes=interval)

        for entity_id, states in history_data.items():
            is_fan = entity_id in fan_ids
            if not states:
                result[entity_id] = []
                continue

            if len(states) <= _SPARSE_ENTITY_THRESHOLD:
                passthrough: list[dict[str, Any]] = []
                for s in states:
                    ts = _extract_ts(s)
                    if ts == _EPOCH_SENTINEL:
                        continue
                    state_val = s.get("state") if isinstance(s, dict) else s.state
                    if state_val and state_val not in ("unknown", "unavailable"):
                        point: dict[str, Any] = {"s": state_val, "lu": ts.isoformat()}
                        if is_fan:
                            attrs = _extract_fan_attrs(s)
                            if attrs:
                                point["a"] = attrs
                        passthrough.append(point)
                result[entity_id] = passthrough
            else:
                result[entity_id] = _downsample_entity_binary_search(
                    states, start_time, end_time, interval_delta
                )

        return result

    return await hass.async_add_executor_job(_downsample_with_binary_search)  # type: ignore[no-any-return]


async def websocket_get_history_stats(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get history stats command with server-side optimization."""
    entity_ids = msg["entity_ids"]
    start_time_str = msg["start_time"]
    end_time_str = msg.get("end_time")
    interval = msg["interval_minutes"]

    start_time = dt_util.parse_datetime(start_time_str)
    end_time = (
        dt_util.parse_datetime(end_time_str) if end_time_str else dt_util.utcnow()
    )

    if not start_time:
        connection.send_error(msg["id"], "invalid_args", "Invalid start_time")
        return

    if not end_time:
        connection.send_error(msg["id"], "invalid_args", "Invalid end_time")
        return

    try:
        if interval >= 60:
            stats_result = await _get_statistics_data(
                hass, entity_ids, start_time, end_time, interval
            )
            if stats_result:
                connection.send_result(msg["id"], stats_result)
                return

        result = await _get_history_with_binary_search_downsample(
            hass, entity_ids, start_time, end_time, interval
        )
        connection.send_result(msg["id"], result)

    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_history_stats")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_update_sensor_coordinates(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle update sensor coordinates command."""
    growspace_id = msg["growspace_id"]
    entity_id = msg["entity_id"]
    x = msg["x"]
    y = msg["y"]
    z = msg["z"]
    rotation = msg.get("rotation")

    try:
        coordinator = GrowspaceCoordinator.get_for_service_call(hass, msg)
        growspace = coordinator.growspaces.get(growspace_id)

        if not growspace:
            connection.send_error(
                msg["id"], "not_found", f"Growspace {growspace_id} not found"
            )
            return

        if (
            not hasattr(growspace, "environment_config")
            or not growspace.environment_config
        ):
            connection.send_error(
                msg["id"],
                "invalid_state",
                "Grow space has no environment configuration",
            )
            return

        if not growspace.environment_config.sensor_coordinates:
            growspace.environment_config.sensor_coordinates = {}

        data = {"x": x, "y": y, "z": z}
        if rotation is not None:
            data["rotation"] = rotation

        growspace.environment_config.sensor_coordinates[entity_id] = data

        await coordinator.async_commit()
        await coordinator.async_request_refresh()

        connection.send_result(msg["id"])
    except ServiceValidationError as err:
        connection.send_error(msg["id"], "invalid_args", str(err))
    except Exception as err:
        _LOGGER.exception("Error handling websocket_update_sensor_coordinates")
        connection.send_error(msg["id"], "unknown_error", str(err))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_HISTORY_STATS, websocket_get_history_stats, SCHEMA_WS_GET_HISTORY_STATS, False),
    (WS_TYPE_UPDATE_SENSOR_COORDINATES, websocket_update_sensor_coordinates, SCHEMA_WS_UPDATE_SENSOR_COORDINATES, False),
]
