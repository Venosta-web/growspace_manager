"""Logbook and alert WebSocket handlers."""

from __future__ import annotations

import json
import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.db_schema import EventData, Events, EventTypes
from homeassistant.components.recorder.util import session_scope
from homeassistant.core import HomeAssistant
import homeassistant.util.dt as dt_util

from ..const import (
    ALERT_LOG_LOOKBACK_DAYS,
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    EVENT_LOG_LOOKBACK_DAYS,
)
from ._common import _merge_logbook_event

_LOGGER = logging.getLogger(__name__)

WS_TYPE_GET_LOG = f"{DOMAIN}/get_log"
SCHEMA_WS_GET_LOG = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_LOG,
        vol.Optional("growspace_id"): str,
        vol.Optional("plant_id"): str,
        vol.Optional("limit"): vol.Any(int, None),
    }
)

WS_TYPE_GET_ALERTS = f"{DOMAIN}/get_alerts"
SCHEMA_WS_GET_ALERTS = websocket_api.BASE_COMMAND_MESSAGE_SCHEMA.extend(
    {
        vol.Required("type"): WS_TYPE_GET_ALERTS,
        vol.Optional("growspace_id"): str,
        vol.Optional("plant_id"): str,
        vol.Optional("limit"): vol.Any(int, None),
    }
)


def _query_logbook_events_impl(
    hass: HomeAssistant,
    start_time: Any,
    end_time: Any,
    limit: int,
    growspace_id: str | None,
    plant_id: str | None = None,
    exclude_categories: set[str] | None = None,
    include_categories: set[str] | None = None,
    limit_multiplier: int = 2,
) -> list[dict[str, Any]]:
    """Execute the logbook query with filtering logic."""
    formatted: list[dict[str, Any]] = []
    count = 0

    with session_scope(hass=hass, read_only=True) as session:
        t_row = (
            session.query(EventTypes.event_type_id)
            .filter(EventTypes.event_type == EVENT_GROWSPACE_LOG_ENTRY)
            .first()
        )
        if not t_row:
            return []

        q = (
            session.query(Events, EventData)
            .join(EventData, Events.data_id == EventData.data_id, isouter=False)
            .filter(
                Events.event_type_id == t_row[0],
                Events.time_fired_ts >= start_time.timestamp(),
                Events.time_fired_ts <= end_time.timestamp(),
            )
        )

        if exclude_categories:
            for cat in exclude_categories:
                q = q.filter(
                    ~EventData.shared_data.like(f'%"category":"{cat}"%'),
                    ~EventData.shared_data.like(f'%"category": "{cat}"%'),
                )

        q = q.order_by(Events.time_fired_ts.desc())

        if limit:
            q = q.limit(limit * limit_multiplier)

        for e_row, d_row in q:
            if not d_row or not d_row.shared_data:
                continue
            try:
                d = json.loads(d_row.shared_data)
                if plant_id:
                    event_plant_id = d.get("plant_id")
                    if event_plant_id is not None and event_plant_id != plant_id:
                        continue
                    if (
                        event_plant_id is None
                        and growspace_id
                        and d.get("growspace_id") != growspace_id
                    ):
                        continue
                elif growspace_id and d.get("growspace_id") != growspace_id:
                    continue

                if include_categories and d.get("category") not in include_categories:
                    continue

                # Skip plain notification events fired by _fire_logbook_event()
                # (those only carry `message` and have no `sensor_type` or `notes`).
                # They belong in HA's native logbook, not in the growspace logbook UI.
                if "sensor_type" not in d and "notes" not in d:
                    continue

                if count >= limit:
                    break
                count += 1

                if "timestamp" not in d and e_row.time_fired_ts:
                    d["timestamp"] = dt_util.utc_from_timestamp(
                        e_row.time_fired_ts
                    ).isoformat()

                if not _merge_logbook_event(formatted, d, e_row):
                    d["event_id"] = e_row.event_id
                    formatted.append(d)

            except (json.JSONDecodeError, AttributeError):
                continue
    return formatted


async def websocket_get_event_log(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get event log command via Recorder.

    Excludes high-frequency environmental alerts (optimal, stress, mold).
    """
    growspace_id = msg.get("growspace_id")
    plant_id = msg.get("plant_id")
    limit = msg.get("limit", 50)
    spam_cats = {"optimal", "stress", "mold", "alert", "environment"}

    try:
        recorder = get_instance(hass)
        end_time = dt_util.utcnow()
        start_time = end_time - timedelta(days=EVENT_LOG_LOOKBACK_DAYS)

        evts = await recorder.async_add_executor_job(
            _query_logbook_events_impl,
            hass,
            start_time,
            end_time,
            limit,
            growspace_id,
            plant_id,
            spam_cats,
            None,
            2,
        )
        res = {}
        response_key = plant_id or growspace_id
        if response_key:
            res[response_key] = evts
        else:
            for v in evts:
                gid = v.get("growspace_id", "global")
                res.setdefault(gid, []).append(v)

        connection.send_result(msg["id"], res)

    except (ImportError, KeyError) as err:
        _LOGGER.warning("Recorder not available: %s", err)
        response_key = plant_id or growspace_id
        connection.send_result(msg["id"], {response_key: []} if response_key else {})
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_event_log")
        connection.send_error(msg["id"], "unknown_error", str(err))


async def websocket_get_alerts(
    hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]
) -> None:
    """Handle get alerts command via Recorder.

    ONLY includes high-frequency environmental alerts (optimal, stress, mold).
    """
    growspace_id = msg.get("growspace_id")
    plant_id = msg.get("plant_id")
    limit = msg.get("limit", 200)
    alert_cats = {"optimal", "stress", "mold", "alert", "environment"}

    try:
        recorder = get_instance(hass)
        end_time = dt_util.utcnow()
        start_time = end_time - timedelta(days=ALERT_LOG_LOOKBACK_DAYS)

        evts = await recorder.async_add_executor_job(
            _query_logbook_events_impl,
            hass,
            start_time,
            end_time,
            limit,
            growspace_id,
            plant_id,
            None,
            alert_cats,
            5,
        )
        res = {}
        response_key = plant_id or growspace_id
        if response_key:
            res[response_key] = evts
        else:
            for v in evts:
                gid = v.get("growspace_id", "global")
                res.setdefault(gid, []).append(v)

        connection.send_result(msg["id"], res)

    except (ImportError, KeyError) as err:
        _LOGGER.warning("Recorder not available: %s", err)
        response_key = plant_id or growspace_id
        connection.send_result(msg["id"], {response_key: []} if response_key else {})
    except Exception as err:
        _LOGGER.exception("Error handling websocket_get_alerts")
        connection.send_error(msg["id"], "unknown_error", str(err))


COMMANDS: list[tuple[str, Any, Any, bool]] = [
    (WS_TYPE_GET_LOG, websocket_get_event_log, SCHEMA_WS_GET_LOG, False),
    (WS_TYPE_GET_ALERTS, websocket_get_alerts, SCHEMA_WS_GET_ALERTS, False),
]
