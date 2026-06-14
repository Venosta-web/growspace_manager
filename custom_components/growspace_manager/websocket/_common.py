"""Shared helpers for WebSocket handlers."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime
from functools import wraps
import logging
from typing import Any

from custom_components.growspace_manager.const import MERGE_ALERT_GAP_SECONDS
from custom_components.growspace_manager.exceptions import GrowspaceError
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
import homeassistant.util.dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Sentinel for invalid timestamps
_EPOCH_SENTINEL: datetime = datetime.min.replace(tzinfo=dt_util.UTC)

_WSHandler = Callable[
    [HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], Awaitable[None]
]
_WSHandlerSync = Callable[[HomeAssistant, websocket_api.ActiveConnection, dict[str, Any]], None]

# (exception types to match, error code to send, whether to log a traceback,
# optional fixed message overriding str(err))
WSErrorMap = tuple[
    tuple[type[Exception] | tuple[type[Exception], ...], str, bool, str | None], ...
]

# Covers the common pattern: validation-shaped errors are reported as
# "validation_failed" without a traceback, everything else is logged and
# reported as "unknown_error".
DEFAULT_WS_ERROR_MAP: WSErrorMap = (
    ((ServiceValidationError, GrowspaceError, ValueError), "validation_failed", False, None),
    (Exception, "unknown_error", True, None),
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
            connection.send_error(msg["id"], code, message if message is not None else str(err))
            return
    raise err


def handle_ws_errors(error_map: WSErrorMap = DEFAULT_WS_ERROR_MAP) -> Callable[[_WSHandler], _WSHandler]:
    """Decorate an async WebSocket handler with standardized error reporting.

    On success the handler is responsible for calling
    ``connection.send_result``. On a raised exception, ``error_map`` is
    checked in order for the first matching exception type and the
    corresponding error code is sent via ``connection.send_error``.

    Mirrors ``services.utils.handle_service_errors`` for the WebSocket layer.
    """

    def decorator(func: _WSHandler) -> _WSHandler:
        @wraps(func)
        async def wrapper(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            try:
                await func(hass, connection, msg)
            except Exception as err:  # noqa: BLE001
                _send_ws_error(connection, msg, func.__name__, err, error_map)

        return wrapper

    return decorator


def handle_ws_errors_sync(
    error_map: WSErrorMap = DEFAULT_WS_ERROR_MAP,
) -> Callable[[_WSHandlerSync], _WSHandlerSync]:
    """Sync-callback variant of :func:`handle_ws_errors`."""

    def decorator(func: _WSHandlerSync) -> _WSHandlerSync:
        @wraps(func)
        def wrapper(
            hass: HomeAssistant,
            connection: websocket_api.ActiveConnection,
            msg: dict[str, Any],
        ) -> None:
            try:
                func(hass, connection, msg)
            except Exception as err:  # noqa: BLE001
                _send_ws_error(connection, msg, func.__name__, err, error_map)

        return wrapper

    return decorator


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
        except (ValueError, TypeError, KeyError):
            pass
    return False
