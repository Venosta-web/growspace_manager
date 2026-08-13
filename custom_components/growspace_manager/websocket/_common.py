"""Shared helpers for WebSocket handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime
from functools import wraps
import logging
from typing import Any

from custom_components.growspace_manager.const import MERGE_ALERT_GAP_SECONDS
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import (
    CoordinatorNotReadyError,
    EntityNotFoundError,
    GrowspaceError,
    LayoutConflictError,
    RateLimitedError,
)
from custom_components.growspace_manager.services.utils import (
    WS_ERR_CONFLICT,
    WS_ERR_COORDINATOR_NOT_READY,
    WS_ERR_ENTITY_NOT_FOUND,
    WS_ERR_INTERNAL_ERROR,
    WS_ERR_RATE_LIMITED,
    WS_ERR_VALIDATION_FAILED,
)
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Sentinel for invalid timestamps
_EPOCH_SENTINEL: datetime = datetime.min.replace(tzinfo=dt_util.UTC)

_WSHandler = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Awaitable[None]
]
_WSHandlerSync = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], None
]

# Payload-returning handlers (ADR-0027): the WS Command Lifecycle owns the
# connection; a handler computes a payload (or None) and raises typed
# exceptions for errors.
WSPayloadHandler = Callable[
    [HomeAssistant, GrowspaceCoordinator, dict[str, Any]], Awaitable[Any]
]
WSPayloadHandlerSync = Callable[
    [HomeAssistant, GrowspaceCoordinator, dict[str, Any]], Any
]

# (exception types to match, error code to send, whether to log a traceback,
# optional fixed message overriding str(err))
WSErrorMap = tuple[
    tuple[type[Exception] | tuple[type[Exception], ...], str, bool, str | None], ...
]

# The Typed Error Codes vocabulary shared with the card (ADR-0005, completed
# by ADR-0027). The card's errors.ts types exactly this set and coerces any
# other code to internal_error, so ad-hoc codes are self-defeating.
DEFAULT_WS_ERROR_MAP: WSErrorMap = (
    (LayoutConflictError, WS_ERR_CONFLICT, False, None),
    (EntityNotFoundError, WS_ERR_ENTITY_NOT_FOUND, False, None),
    (CoordinatorNotReadyError, WS_ERR_COORDINATOR_NOT_READY, False, None),
    (RateLimitedError, WS_ERR_RATE_LIMITED, False, None),
    (
        (ServiceValidationError, GrowspaceError, ValueError),
        WS_ERR_VALIDATION_FAILED,
        False,
        None,
    ),
    (Exception, WS_ERR_INTERNAL_ERROR, True, None),
)


def _send_ws_error(
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    func_name: str,
    err: Exception,
    error_map: WSErrorMap,
) -> None:
    """Send the error response for ``err`` per ``error_map``, or re-raise if unmatched."""
    for exc_types, code, should_log, message in error_map:
        if isinstance(err, exc_types):
            if should_log:
                _LOGGER.exception("Error handling %s", func_name)
            connection.send_error(
                msg["id"], code, message if message is not None else str(err)
            )
            return
    raise err


@dataclass(frozen=True, slots=True)
class WSCommand:
    """One declarative WS command row (ADR-0027, [[WSCommand]]).

    ``resolve="targeted"`` locates the coordinator from ids in the message via
    ``get_for_service_call``; ``"any"`` uses ``get_any`` (global commands).
    ``sync=True`` registers a ``@callback`` wrapper for cheap reads.
    ``error_map`` overrides the default Typed Error Codes table for modules
    with a genuinely different message policy.
    """

    type: str
    handler: Any
    schema: Any
    resolve: str = "targeted"
    sync: bool = False
    error_map: WSErrorMap | None = None


def _resolve_coordinator(
    hass: HomeAssistant, msg: dict[str, Any], mode: str
) -> GrowspaceCoordinator:
    """Locate the coordinator for a command per its declared resolve mode."""
    if mode == "any":
        return GrowspaceCoordinator.get_any(hass)
    return GrowspaceCoordinator.get_for_service_call(hass, msg)


def register_ws_command(hass: HomeAssistant, command: WSCommand) -> None:
    """Register one command behind the WS Command Lifecycle (ADR-0027).

    The wrapper owns resolve → execute → ``send_result`` → error mapping;
    the handler is a payload-returning function that never sees the
    connection. Its return value is sent as the result payload (``None``
    for mutations).
    """
    error_map = command.error_map or DEFAULT_WS_ERROR_MAP

    if command.sync:

        @callback
        @wraps(command.handler)
        def sync_wrapper(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            try:
                coordinator = _resolve_coordinator(hass, msg, command.resolve)
                payload = command.handler(hass, coordinator, msg)
                connection.send_result(msg["id"], payload)
            except Exception as err:  # noqa: BLE001
                _send_ws_error(
                    connection, msg, command.handler.__name__, err, error_map
                )

        websocket_api.async_register_command(
            hass, command.type, sync_wrapper, command.schema
        )
        return

    @wraps(command.handler)
    async def async_wrapper(
        hass: HomeAssistant,
        connection: websocket_api.ActiveConnection,
        msg: dict[str, Any],
    ) -> None:
        try:
            coordinator = _resolve_coordinator(hass, msg, command.resolve)
            payload = await command.handler(hass, coordinator, msg)
            connection.send_result(msg["id"], payload)
        except Exception as err:  # noqa: BLE001
            _send_ws_error(connection, msg, command.handler.__name__, err, error_map)

    websocket_api.async_register_command(
        hass, command.type, websocket_api.async_response(async_wrapper), command.schema
    )


def _extract_ts(state_obj: Any) -> datetime:
    """Extract timestamp from state object or dict."""
    if isinstance(state_obj, dict):
        ts_raw = state_obj.get("last_updated", state_obj.get("last_changed"))
    else:
        ts_raw = state_obj.last_updated

    if ts_raw is None:
        return _EPOCH_SENTINEL
    if isinstance(ts_raw, str):
        parsed = dt_util.parse_datetime(ts_raw)
        return parsed or _EPOCH_SENTINEL  # type: ignore[no-any-return]
    if isinstance(ts_raw, datetime):
        return ts_raw
    return _EPOCH_SENTINEL


def _merge_logbook_event(
    formatted_events_list: list[dict[str, Any]],
    data_dict: dict[str, Any],
    evt_row: Any,
) -> bool:
    """Try to merge an event into the last one if they are similar alerts."""
    if not formatted_events_list:
        return False

    last_evt = formatted_events_list[-1]
    if (
        data_dict.get("category") == "alert"
        and last_evt.get("category") == "alert"
        and data_dict.get("growspace_id") == last_evt.get("growspace_id")
        and data_dict.get("sensor_type") == last_evt.get("sensor_type")
        and "severity" in data_dict
        and "severity" in last_evt
        and round(float(data_dict["severity"]), 2)
        == round(float(last_evt["severity"]), 2)
    ):
        try:
            l_start_iso = last_evt.get("start_time")
            d_end_iso = data_dict.get("end_time")

            if l_start_iso and d_end_iso:
                l_dt = datetime.fromisoformat(l_start_iso)
                d_dt = datetime.fromisoformat(d_end_iso)
                gap_sec = (l_dt - d_dt).total_seconds()

                if 0 <= gap_sec <= MERGE_ALERT_GAP_SECONDS:
                    last_evt["start_time"] = data_dict["start_time"]
                    last_evt["duration_sec"] = last_evt.get(
                        "duration_sec", 0
                    ) + data_dict.get("duration_sec", 0)

                    if "reasons" in data_dict and "reasons" in last_evt:
                        comb = list(
                            dict.fromkeys(last_evt["reasons"] + data_dict["reasons"])
                        )
                        last_evt["reasons"] = comb[:5]
                    return True  # type: ignore[no-any-return]
        except ValueError, TypeError, KeyError:
            pass
    return False
