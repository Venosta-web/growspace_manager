"""Durable, bounded reliability measurements for each growspace.

The lifetime map is exact. Recent windows use minute buckets for the last day
and day buckets for the last month; day buckets are intentionally calendar UTC
days, so the 30-day view has day resolution.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from copy import deepcopy
from datetime import UTC, datetime, timedelta
import logging
import math
from os.path import exists
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


class ReliabilityStore:
    """Write each observation through before exposing it to diagnostics."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Create an entry-scoped atomic Home Assistant store."""
        self._hass = hass
        self._key = f"growspace_manager.reliability_{entry_id}"
        self._store: Store[dict[str, Any]] = Store(hass, 1, self._key)
        self._lock = asyncio.Lock()
        self._data: dict[str, dict[str, Any]] = {}
        self.unreadable = False

    async def async_load(self) -> None:
        """Restore a previous snapshot, rejecting invalid counter values."""
        try:
            data = await self._async_read()
            self._validate(data)
        except Exception:
            self.unreadable = True
            _LOGGER.exception("Reliability evidence is unreadable; keeping it intact")
            return
        self._data = data

    async def _async_read(self) -> dict[str, Any]:
        """Distinguish a missing record from a present but unreadable one."""
        data = await self._store.async_load()
        if data is None:
            path = self._hass.config.path(".storage", self._key)
            if await self._hass.async_add_executor_job(exists, path):
                raise ValueError("Existing reliability record could not be decoded")
            return {}
        return data

    @staticmethod
    def _validate(data: Any) -> None:
        """Reject malformed persisted observations before accepting any of them."""
        if not isinstance(data, dict):
            raise TypeError("Reliability record must be an object")
        for growspace_id, row in data.items():
            if not isinstance(growspace_id, str) or not isinstance(row, dict):
                raise TypeError("Invalid reliability growspace")
            if not isinstance(row.get("active", {}), dict):
                raise TypeError("Invalid active reliability records")
            if "last_fault_at" in row:
                if not isinstance(row["last_fault_at"], str):
                    raise TypeError("Invalid last fault timestamp")
                if datetime.fromisoformat(row["last_fault_at"]).tzinfo is None:
                    raise ValueError("Last fault timestamp lacks timezone")
            for section in ("lifetime", "minutes", "days"):
                values = row.get(section, {})
                if not isinstance(values, dict):
                    raise TypeError("Invalid reliability counters")
                groups = (values,) if section == "lifetime" else values.values()
                for group in groups:
                    if not isinstance(group, dict) or any(
                        not isinstance(key, str)
                        or type(value) not in (int, float)
                        or value < 0
                        or not math.isfinite(value)
                        for key, value in group.items()
                    ):
                        raise ValueError("Invalid reliability counter")

    @staticmethod
    def _prune(row: dict[str, Any], now: datetime) -> None:
        minute_limit = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        day_limit = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        row["minutes"] = {
            key: value
            for key, value in row.get("minutes", {}).items()
            if key >= minute_limit
        }
        row["days"] = {
            key: value for key, value in row.get("days", {}).items() if key >= day_limit
        }

    async def async_add(
        self,
        growspace_id: str,
        counter: str,
        amount: float = 1,
        *,
        at: datetime | None = None,
    ) -> None:
        """Count one effect; keep lifetime totals and finite recent buckets."""
        if self.unreadable:
            raise RuntimeError("Reliability evidence is unreadable")
        if (
            not counter
            or type(amount) not in (int, float)
            or amount < 0
            or not math.isfinite(amount)
        ):
            raise ValueError("Invalid reliability increment")
        now = (at or datetime.now(UTC)).astimezone(UTC)
        async with self._lock:
            previous = deepcopy(self._data.get(growspace_id))
            row = self._data.setdefault(
                growspace_id, {"lifetime": {}, "minutes": {}, "days": {}}
            )
            runtime_prefix = "runtime.automated_seconds."
            if counter.startswith(runtime_prefix) and counter not in row["lifetime"]:
                named = sum(
                    key.startswith(runtime_prefix) and key != runtime_prefix + "other"
                    for key in row["lifetime"]
                )
                if named >= 16:
                    counter = runtime_prefix + "other"
            self._prune(row, now)
            for section, bucket in (
                ("lifetime", None),
                ("minutes", now.strftime("%Y-%m-%dT%H:%M")),
                ("days", now.strftime("%Y-%m-%d")),
            ):
                group = (
                    row[section]
                    if bucket is None
                    else row[section].setdefault(bucket, {})
                )
                group[counter] = group.get(counter, 0) + amount
            if counter == "controller.fault_latched":
                row["last_fault_at"] = now.isoformat()
            try:
                await self._store.async_save(self._data)
            except Exception:
                if previous is None:
                    self._data.pop(growspace_id, None)
                else:
                    self._data[growspace_id] = previous
                raise

    async def async_set_active(
        self, growspace_id: str, output: str, active: bool
    ) -> None:
        """Persist the in-flight output marker for restart accounting."""
        if self.unreadable:
            raise RuntimeError("Reliability evidence is unreadable")
        async with self._lock:
            previous = deepcopy(self._data.get(growspace_id))
            row = self._data.setdefault(
                growspace_id, {"lifetime": {}, "minutes": {}, "days": {}}
            )
            markers = row.setdefault("active", {})
            if active:
                markers[output] = datetime.now(UTC).isoformat()
            else:
                markers.pop(output, None)
            try:
                await self._store.async_save(self._data)
            except Exception:
                if previous is None:
                    self._data.pop(growspace_id, None)
                else:
                    self._data[growspace_id] = previous
                raise

    def active_outputs(self, growspace_id: str) -> tuple[str, ...]:
        """Return output markers left by a prior runtime."""
        return tuple(self._data.get(growspace_id, {}).get("active", {}))

    def snapshot(
        self, growspace_id: str, *, at: datetime | None = None
    ) -> dict[str, Any]:
        """Return a stable public JSON shape, including zero-valued windows."""
        now = (at or datetime.now(UTC)).astimezone(UTC)
        row = self._data.get(growspace_id, {})
        minute_limit = (now - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M")
        day_limit = (now - timedelta(days=30)).strftime("%Y-%m-%d")
        windows: dict[str, dict[str, Any]] = {}
        for name, section, limit in (
            ("last_24h", "minutes", minute_limit),
            ("last_30d", "days", day_limit),
        ):
            totals: defaultdict[str, int | float] = defaultdict(int)
            for bucket, values in row.get(section, {}).items():
                if bucket >= limit:
                    for key, value in values.items():
                        totals[key] += value
            windows[name] = dict(sorted(totals.items()))
        last_fault = row.get("last_fault_at")
        days_since_last_fault = (
            max(0, (now - datetime.fromisoformat(last_fault)).days)
            if isinstance(last_fault, str)
            else None
        )
        lifetime: dict[str, Any] = dict(sorted(row.get("lifetime", {}).items()))
        for counters in (lifetime, *windows.values()):
            observed = counters.get("runtime.observed_minutes", 0)
            counters["runtime.automation_uptime_percent"] = (
                round(
                    100
                    * counters.get("runtime.automation_eligible_minutes", 0)
                    / observed,
                    2,
                )
                if observed
                else None
            )
        return {
            "schema_version": 1,
            "unreadable": self.unreadable,
            "growspace_id": growspace_id,
            "as_of": now.isoformat(),
            "lifetime": lifetime,
            "days_since_last_fault": days_since_last_fault,
            **windows,
        }
