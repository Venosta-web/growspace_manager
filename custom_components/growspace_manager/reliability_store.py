"""Durable, bounded reliability measurements for each growspace.

The lifetime map is exact. Recent windows use minute buckets for the last day
and day buckets for the last month; day buckets are intentionally calendar UTC
days, so the 30-day view has day resolution.

Recording never waits on the disk. Effect shells call ``record`` from pump
fail-safe and emergency-stop paths, so a counter updates memory at once and a
coalesced save follows; Home Assistant's final write flushes a pending save on
shutdown. An in-flight marker is saved without the delay, because the restart
it exists to detect is the one that would lose a delayed write.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import logging
import math
from os.path import exists
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util.hass_dict import HassKey

_LOGGER = logging.getLogger(__name__)

# Coalesces the per-minute probe and a cycle's handful of counters into one
# write; at most this much evidence is lost to a crash (not to a clean stop).
SAVE_DELAY_SECONDS = 60

# Distinct suffixes kept per open counter family before further ones fold into
# ``<family>.other``, so a new reason code or actuator cannot grow storage.
MAX_KEYS_PER_FAMILY = 16

# Home Assistant starts already counted, per (entry, growspace), so a config
# entry reload is not counted as a start.
COUNTED_STARTS: HassKey[set[tuple[str, str]]] = HassKey(
    "growspace_manager_reliability_starts"
)


class ReliabilityCounter(StrEnum):
    """Every fixed counter key; the open families are built by the helpers below."""

    REQUESTED = "irrigation.requested"
    FIRED = "irrigation.fired"
    COMPLETED_VERIFIED = "irrigation.completed_verified"
    COMPLETED_UNVERIFIED = "irrigation.completed_unverified"
    COMMAND_FAILURE_ON = "irrigation.command_failure.on"
    COMMAND_FAILURE_OFF = "irrigation.command_failure.off"
    ON_UNCONFIRMED = "irrigation.readback.on_unconfirmed"
    OFF_UNCONFIRMED = "irrigation.readback.off_unconfirmed"
    UNEXPECTED_ON = "irrigation.readback.unexpected_on"
    SENSOR_UNAVAILABLE_MINUTES = "sensors.control_unavailable_minutes"
    SENSOR_STALE_EVENTS = "sensors.stale_events"
    SENSOR_IMPLAUSIBLE_READINGS = "sensors.implausible_readings"
    FAULT_LATCHED = "controller.fault_latched"
    FAULT_ACKNOWLEDGED = "controller.fault_acknowledged"
    EMERGENCY_STOP = "controller.emergency_stop"
    HA_START = "runtime.ha_start"
    HA_START_INFLIGHT = "runtime.ha_start_inflight"
    OBSERVED_MINUTES = "runtime.observed_minutes"
    AUTOMATION_ELIGIBLE_MINUTES = "runtime.automation_eligible_minutes"
    ESTIMATED_WATER_L = "runtime.estimated_water_l"


class AbortCause(StrEnum):
    """Why a cycle admitted by the gate did not run to its planned end."""

    CANCEL = "cancel"
    E_STOP = "e_stop"
    OVERRIDE = "override"
    ERROR = "error"
    WATCHDOG = "watchdog"


_SKIPPED = "irrigation.skipped."
_ABORTED = "irrigation.aborted."
_INHIBIT = "controller.inhibit."
_AUTOMATED_SECONDS = "runtime.automated_seconds."
_OPEN_FAMILIES = (_SKIPPED, _INHIBIT, _AUTOMATED_SECONDS)

# The key counters the diagnostic sensor carries as attributes; everything
# else is in diagnostics and the export.
SENSOR_COUNTERS = (
    ReliabilityCounter.REQUESTED,
    ReliabilityCounter.FIRED,
    ReliabilityCounter.COMPLETED_VERIFIED,
    ReliabilityCounter.COMPLETED_UNVERIFIED,
    ReliabilityCounter.FAULT_LATCHED,
    ReliabilityCounter.EMERGENCY_STOP,
    ReliabilityCounter.HA_START,
    ReliabilityCounter.HA_START_INFLIGHT,
)


def skipped(reason: str) -> str:
    """Return the counter of a cycle refused before it fired, by gate reason."""
    return _SKIPPED + reason


def aborted(cause: AbortCause) -> str:
    """Return the counter of an admitted cycle that did not run to its end."""
    return _ABORTED + cause


def inhibited(reason_code: str | None) -> str:
    """Return the counter of a controller entering ``inhibited``, by reason."""
    return _INHIBIT + (reason_code or "unknown")


def automated_seconds(entity_id: str) -> str:
    """Return the automated runtime counter of one actuator."""
    return _AUTOMATED_SECONDS + entity_id


def _empty_row() -> dict[str, Any]:
    return {"lifetime": {}, "minutes": {}, "days": {}}


class ReliabilityStore:
    """Count effects per growspace; keep lifetime totals and bounded windows."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Create an entry-scoped atomic Home Assistant store."""
        self._hass = hass
        self._entry_id = entry_id
        self._key = f"growspace_manager.reliability_{entry_id}"
        self._store: Store[dict[str, Any]] = Store(hass, 1, self._key)
        self._data: dict[str, dict[str, Any]] = {}
        self.unreadable = False

    async def async_load(self) -> None:
        """Restore a previous snapshot, rejecting invalid counter values.

        An unreadable record is logged here, once; every later write is a
        silent no-op so the file is left intact for inspection.
        """
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

    @callback
    def _schedule_save(self, delay: float = SAVE_DELAY_SECONDS) -> None:
        """Queue a write; Home Assistant never pushes an earlier one back."""
        self._store.async_delay_save(lambda: self._data, delay)

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

    @staticmethod
    def _bounded(lifetime: dict[str, Any], counter: str) -> str:
        """Fold a new key of a full open family into that family's ``other``."""
        if counter in lifetime:
            return counter
        for family in _OPEN_FAMILIES:
            if counter.startswith(family):
                other = family + "other"
                named = sum(key.startswith(family) and key != other for key in lifetime)
                return other if named >= MAX_KEYS_PER_FAMILY else counter
        return counter

    @callback
    def record(
        self,
        growspace_id: str,
        counter: str,
        amount: float = 1,
        *,
        at: datetime | None = None,
    ) -> None:
        """Count one effect now; the write to disk follows on its own."""
        if self.unreadable:
            return
        if (
            not counter
            or type(amount) not in (int, float)
            or not (math.isfinite(amount) and amount >= 0)
        ):
            _LOGGER.warning(
                "Ignoring invalid reliability increment %s=%s", counter, amount
            )
            return
        now = (at or datetime.now(UTC)).astimezone(UTC)
        row = self._data.setdefault(growspace_id, _empty_row())
        # Plain strings: an enum member as a key would reach the export as one.
        counter = self._bounded(row.setdefault("lifetime", {}), str(counter))
        self._prune(row, now)
        for section, bucket in (
            ("lifetime", None),
            ("minutes", now.strftime("%Y-%m-%dT%H:%M")),
            ("days", now.strftime("%Y-%m-%d")),
        ):
            group = (
                row[section] if bucket is None else row[section].setdefault(bucket, {})
            )
            group[counter] = group.get(counter, 0) + amount
        if counter == ReliabilityCounter.FAULT_LATCHED:
            row["last_fault_at"] = now.isoformat()
        self._schedule_save()

    @callback
    def mark_active(self, growspace_id: str, output: str) -> None:
        """Persist, without the save delay, that ``output`` is running a cycle."""
        if self.unreadable:
            return
        row = self._data.setdefault(growspace_id, _empty_row())
        row.setdefault("active", {})[output] = datetime.now(UTC).isoformat()
        self._schedule_save(0)

    @callback
    def clear_active(self, growspace_id: str, output: str) -> None:
        """Forget the in-flight marker of ``output`` once its cycle has closed."""
        if self.unreadable:
            return
        row = self._data.get(growspace_id)
        if row is not None and row.get("active", {}).pop(output, None) is not None:
            self._schedule_save()

    def active_outputs(self, growspace_id: str) -> tuple[str, ...]:
        """Return output markers left by a prior runtime."""
        return tuple(self._data.get(growspace_id, {}).get("active", {}))

    @callback
    def record_start(self, growspace_ids: Iterable[str]) -> None:
        """Count this Home Assistant start once per growspace.

        A marker still present means the previous process stopped mid-cycle;
        it is counted and cleared. Rows of growspaces that no longer exist are
        dropped here, so a removed growspace does not keep its storage.
        """
        if self.unreadable:
            return
        present = set(growspace_ids)
        for removed in set(self._data) - present:
            del self._data[removed]
        counted = self._hass.data.setdefault(COUNTED_STARTS, set())
        for growspace_id in present:
            start_key = (self._entry_id, growspace_id)
            if start_key in counted:
                continue
            counted.add(start_key)
            if self.active_outputs(growspace_id):
                self.record(growspace_id, ReliabilityCounter.HA_START_INFLIGHT)
                self._data[growspace_id]["active"] = {}
            self.record(growspace_id, ReliabilityCounter.HA_START)
        self._schedule_save()

    def snapshot(
        self, growspace_id: str, *, at: datetime | None = None
    ) -> dict[str, Any]:
        """Return the documented export shape, including zero-valued windows."""
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
            observed = counters.get(ReliabilityCounter.OBSERVED_MINUTES, 0)
            counters["runtime.automation_uptime_percent"] = (
                round(
                    100
                    * counters.get(ReliabilityCounter.AUTOMATION_ELIGIBLE_MINUTES, 0)
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

    def sensor_attributes(self, growspace_id: str) -> dict[str, Any]:
        """Return the key counters the diagnostic sensor shows, from one snapshot."""
        snapshot = self.snapshot(growspace_id)
        lifetime = snapshot["lifetime"]
        return {
            **{
                counter.replace(".", "_"): lifetime.get(counter, 0)
                for counter in SENSOR_COUNTERS
            },
            "days_since_last_fault": snapshot["days_since_last_fault"],
            "automation_uptime_percent_30d": snapshot["last_30d"][
                "runtime.automation_uptime_percent"
            ],
        }
