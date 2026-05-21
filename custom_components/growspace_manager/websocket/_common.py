"""Shared helpers for WebSocket handlers."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import homeassistant.util.dt as dt_util

from ..const import MERGE_ALERT_GAP_SECONDS

# Sentinel for invalid timestamps
_EPOCH_SENTINEL: datetime = datetime.min.replace(tzinfo=dt_util.UTC)


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
