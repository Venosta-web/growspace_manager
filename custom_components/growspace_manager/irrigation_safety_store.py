"""Write-through fault latches and bounded irrigation safety ledger."""

from __future__ import annotations

from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta
import logging
from os.path import exists
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.storage import Store
from homeassistant.util.dt import utcnow

from .const import EVENT_GROWSPACE_LOG_ENTRY
from .domain.irrigation_safety import FaultRecord, SafetyReason
from .domain.manual_override import MAX_OVERRIDE_DURATION, ManualOverride, Subsystem

_LOGGER = logging.getLogger(__name__)
_LEDGER_LIMIT = 500


class IrrigationSafetyStore:
    """Persist safety changes before reporting success to any caller."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Keep safety data separate from debounced configuration writes."""
        self._hass = hass
        self._key = f"growspace_manager.irrigation_safety_{entry_id}"
        self._store: Store[dict[str, Any]] = Store(hass, 1, self._key)
        self.faults: dict[str, FaultRecord] = {}
        self.emergency_stops: dict[str, FaultRecord] = {}
        self.controls: dict[str, dict[str, bool]] = {}
        # Manual Overrides (#793), per growspace and subsystem. An expired one
        # no longer holds anything even before its timer has removed it.
        self.overrides: dict[str, dict[Subsystem, ManualOverride]] = {}
        self._override_timers: dict[tuple[str, Subsystem], Callable[[], None]] = {}
        self._override_listeners: list[Callable[[str, Subsystem], None]] = []
        self._legacy_controls = False
        self.ledger: deque[dict[str, Any]] = deque(maxlen=_LEDGER_LIMIT)
        self.unreadable = False
        self._unreadable_since: str | None = None

    async def async_load(self) -> None:
        """Fail closed when existing safety data cannot be read or validated."""
        try:
            data = await self._store.async_load()
            if data is None:
                self._legacy_controls = True
                path = self._hass.config.path(".storage", self._key)
                self.unreadable = await self._hass.async_add_executor_job(exists, path)
                if self.unreadable:
                    self._unreadable_since = utcnow().isoformat()
                return
            self.faults, self.emergency_stops, self.ledger = self._decode(data)
            self.controls, self._legacy_controls = self._decode_controls(data)
            self.overrides = self._decode_overrides(data)
        except Exception:
            _LOGGER.exception("Irrigation safety record is unreadable; all cycles held")
            self.unreadable = True
            self._unreadable_since = utcnow().isoformat()
            self.faults.clear()
            self.emergency_stops.clear()
            self.controls.clear()
            self.overrides.clear()

    @staticmethod
    def _decode_overrides(
        data: dict[str, Any],
    ) -> dict[str, dict[Subsystem, ManualOverride]]:
        """Reject a malformed override: a person's hold must never silently lapse."""
        raw = data.get("overrides", {})
        if not isinstance(raw, dict):
            raise TypeError("safety overrides are invalid")
        overrides: dict[str, dict[Subsystem, ManualOverride]] = {}
        for growspace_id, by_subsystem in raw.items():
            if not isinstance(growspace_id, str) or not isinstance(by_subsystem, dict):
                raise TypeError("safety overrides are invalid")
            decoded = {}
            for key, record in by_subsystem.items():
                override = ManualOverride.from_dict(record)
                if key != override.subsystem.value:
                    raise ValueError("override filed under another subsystem")
                decoded[override.subsystem] = override
            overrides[growspace_id] = decoded
        return overrides

    @staticmethod
    def _decode_controls(
        data: dict[str, Any],
    ) -> tuple[dict[str, dict[str, bool]], bool]:
        """Reject malformed operator controls before any output can be enabled."""
        raw_controls = data.get("controls", {})
        if not isinstance(raw_controls, dict) or any(
            not isinstance(key, str)
            or not isinstance(value, dict)
            or type(value.get("automation")) is not bool
            or type(value.get("irrigation_armed")) is not bool
            for key, value in raw_controls.items()
        ):
            raise ValueError("safety controls are invalid")
        return raw_controls, "controls" not in data

    @staticmethod
    def _decode(
        data: Any,
    ) -> tuple[dict[str, FaultRecord], dict[str, FaultRecord], deque[dict[str, Any]]]:
        """Validate the entire document before accepting any of its latches."""
        if not isinstance(data, dict) or not isinstance(data.get("faults"), dict):
            raise TypeError("safety store has no fault map")
        stops = data.get("emergency_stops", {})
        if not isinstance(stops, dict):
            raise TypeError("safety store has no emergency stop map")
        ledger = data.get("ledger", [])
        if not isinstance(ledger, list) or any(
            not isinstance(row, dict) for row in ledger
        ):
            raise TypeError("safety ledger is invalid")
        if any(not isinstance(key, str) for key in (*data["faults"], *stops)):
            raise ValueError("invalid growspace ID in fault map")
        faults = {
            growspace_id: FaultRecord.from_dict(record)
            for growspace_id, record in data["faults"].items()
        }
        emergency_stops = {
            growspace_id: FaultRecord.from_dict(record, allow_empty_outputs=True)
            for growspace_id, record in stops.items()
        }
        return faults, emergency_stops, deque(ledger, maxlen=_LEDGER_LIMIT)

    def fault_for(
        self, growspace_id: str, outputs: tuple[str, ...]
    ) -> FaultRecord | None:
        """Return the latch, including a synthetic fail-closed corrupt-record latch."""
        if self.unreadable:
            return FaultRecord(
                "fault_record_unreadable",
                SafetyReason(
                    "fault_record_unreadable",
                    "Stored irrigation safety record could not be read",
                    self._unreadable_since or utcnow().isoformat(),
                ),
                outputs,
            )
        return self.faults.get(growspace_id)

    def emergency_stop_for(self, growspace_id: str) -> FaultRecord | None:
        """Return a durable operator stop without masking unreadable fault data."""
        return self.emergency_stops.get(growspace_id) if not self.unreadable else None

    def override_for(
        self, growspace_id: str, subsystem: Subsystem
    ) -> ManualOverride | None:
        """Return the Manual Override holding ``subsystem``, if it still holds."""
        override = self.overrides.get(growspace_id, {}).get(subsystem)
        return override if override is not None and override.active(utcnow()) else None

    def active_overrides(self, growspace_id: str) -> list[ManualOverride]:
        """Return every Manual Override still holding in ``growspace_id``."""
        return [
            override
            for subsystem in Subsystem
            if (override := self.override_for(growspace_id, subsystem)) is not None
        ]

    def commands_allowed(self, growspace_id: str, subsystem: Subsystem) -> bool:
        """Permit a controller's commands unless the operator or a person holds it."""
        return (
            self.automation_enabled(growspace_id)
            and self.override_for(growspace_id, subsystem) is None
        )

    def automation_enabled(self, growspace_id: str) -> bool:
        """Permit automatic output commands unless the operator has stopped them."""
        return (
            not self.unreadable
            and self.emergency_stop_for(growspace_id) is None
            and self.controls.get(growspace_id, {}).get("automation", True)
        )

    def irrigation_armed(self, growspace_id: str) -> bool:
        """New irrigation configurations require an explicit arm."""
        return self.automation_enabled(growspace_id) and self.controls.get(
            growspace_id, {}
        ).get("irrigation_armed", False)

    def irrigation_review_pending(self, growspace_id: str) -> bool:
        """Keep the migration repair until an operator touches the arm control."""
        for row in reversed(self.ledger):
            if row.get("growspace_id") != growspace_id:
                continue
            if row.get("action") == "irrigation_armed":
                return False
            if row.get("action") == "irrigation_armed_migration":
                return True
        return False

    def _log_control(self, growspace_id: str, action: str, user_id: str | None) -> None:
        actor = (
            f"HA user {user_id}"
            if user_id
            else "migration"
            if action == "irrigation armed"
            else "system"
        )
        self._log(growspace_id, f"Safety {action} by {actor}", user_id)

    def _log(self, growspace_id: str, message: str, user_id: str | None) -> None:
        self._hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                "growspace_id": growspace_id,
                "category": "alert",
                "message": message,
                "timestamp": utcnow().isoformat(),
                "user_id": user_id,
            },
        )

    async def _append(self, row: dict[str, Any]) -> None:
        """Write one ledger row through, failing closed if it cannot be saved."""
        if self.unreadable:
            raise RuntimeError("Irrigation safety record is unreadable")
        self.ledger.append({"at": utcnow().isoformat(), **row})
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise

    async def async_record_event(
        self, growspace_id: str, action: str, **fields: Any
    ) -> None:
        """Write an observed safety event, such as an Unexpected On, to the ledger."""
        await self._append({"growspace_id": growspace_id, "action": action, **fields})

    @callback
    def add_override_listener(
        self, listener: Callable[[str, Subsystem], None]
    ) -> Callable[[], None]:
        """Call ``listener`` whenever a Manual Override starts or ends."""
        self._override_listeners.append(listener)

        @callback
        def remove() -> None:
            if listener in self._override_listeners:
                self._override_listeners.remove(listener)

        return remove

    @callback
    def _notify_override(self, growspace_id: str, subsystem: Subsystem) -> None:
        for listener in list(self._override_listeners):
            listener(growspace_id, subsystem)

    async def async_set_override(
        self,
        growspace_id: str,
        subsystem: Subsystem,
        duration: timedelta,
        user_id: str | None,
        reason: str | None = None,
    ) -> ManualOverride:
        """Hand ``subsystem`` to a person for ``duration``, audited, then persist it.

        A second call replaces the first, so an override is extended or cut
        short by setting it again.
        """
        if not timedelta(0) < duration <= MAX_OVERRIDE_DURATION:
            raise ValueError("Override duration must be between 1 second and 24 hours")
        now = utcnow()
        override = ManualOverride(subsystem, now, now + duration, user_id, reason)
        if self.unreadable:
            raise RuntimeError("Irrigation safety record is unreadable")
        self.overrides.setdefault(growspace_id, {})[subsystem] = override
        await self._append(
            {
                "growspace_id": growspace_id,
                "action": "override_set",
                **override.as_dict(),
            }
        )
        self._schedule_expiry(growspace_id, override)
        actor = f"HA user {user_id}" if user_id else "system"
        self._log(
            growspace_id,
            f"Manual override of {subsystem} by {actor} until "
            f"{override.expires_at.isoformat()}" + (f": {reason}" if reason else ""),
            user_id,
        )
        self._notify_override(growspace_id, subsystem)
        return override

    async def async_clear_override(
        self,
        growspace_id: str,
        subsystem: Subsystem,
        user_id: str | None,
        *,
        expired: bool = False,
    ) -> None:
        """End a Manual Override, by a person or by its own expiry."""
        if self.unreadable:
            raise RuntimeError("Irrigation safety record is unreadable")
        override = self.overrides.get(growspace_id, {}).pop(subsystem, None)
        if override is None:
            raise ValueError(f"No manual override of {subsystem} is set")
        if not self.overrides[growspace_id]:
            del self.overrides[growspace_id]
        if cancel := self._override_timers.pop((growspace_id, subsystem), None):
            cancel()
        await self._append(
            {
                "growspace_id": growspace_id,
                "action": "override_expired" if expired else "override_cleared",
                "subsystem": subsystem.value,
                "user_id": user_id,
            }
        )
        self._log(
            growspace_id,
            f"Manual override of {subsystem} expired"
            if expired
            else f"Manual override of {subsystem} cleared by "
            + (f"HA user {user_id}" if user_id else "system"),
            user_id,
        )
        self._notify_override(growspace_id, subsystem)

    def _schedule_expiry(self, growspace_id: str, override: ManualOverride) -> None:
        key = (growspace_id, override.subsystem)
        if cancel := self._override_timers.pop(key, None):
            cancel()

        @callback
        def expire(_now: datetime) -> None:
            self._override_timers.pop(key, None)
            self._hass.async_create_task(
                self._async_expire(growspace_id, override),
                name=f"growspace_override_expiry_{growspace_id}_{override.subsystem}",
            )

        self._override_timers[key] = async_track_point_in_utc_time(
            self._hass, expire, override.expires_at
        )

    async def _async_expire(self, growspace_id: str, override: ManualOverride) -> None:
        """Remove an override its timer found expired, unless it was replaced."""
        if self.overrides.get(growspace_id, {}).get(override.subsystem) != override:
            return
        try:
            await self.async_clear_override(
                growspace_id, override.subsystem, None, expired=True
            )
        except Exception:
            # It has already stopped holding: override_for reads the clock.
            _LOGGER.exception(
                "Could not record the expiry of the %s override in %s",
                override.subsystem,
                growspace_id,
            )

    async def async_start_overrides(self) -> None:
        """Expire what ran out while stopped, and time the rest (after load)."""
        for growspace_id, by_subsystem in list(self.overrides.items()):
            for override in list(by_subsystem.values()):
                if override.active(utcnow()):
                    self._schedule_expiry(growspace_id, override)
                else:
                    await self._async_expire(growspace_id, override)

    @callback
    def async_stop_overrides(self) -> None:
        """Cancel the expiry timers; the overrides themselves stay persisted."""
        for cancel in self._override_timers.values():
            cancel()
        self._override_timers.clear()

    async def async_initialize_controls(self, growspaces: dict[str, Any]) -> list[str]:
        """Migrate existing irrigation once, before coordinators can command it."""
        if self.unreadable:
            return []
        migrated: list[str] = []
        changed = self._legacy_controls
        for growspace_id, growspace in growspaces.items():
            if growspace_id in self.controls:
                continue
            changed = True
            config = growspace.irrigation_config
            armed = self._legacy_controls and bool(
                config.irrigation_pump_entity or config.drain_pump_entity
            )
            self.controls[growspace_id] = {
                "automation": True,
                "irrigation_armed": armed,
            }
            if armed:
                migrated.append(growspace_id)
                self.ledger.append(
                    {
                        "at": utcnow().isoformat(),
                        "growspace_id": growspace_id,
                        "action": "irrigation_armed_migration",
                        "user_id": None,
                    }
                )
        self._legacy_controls = False
        if changed:
            await self._save()
        for growspace_id in migrated:
            self._log_control(growspace_id, "irrigation armed", None)
        return migrated

    async def async_set_control(
        self, growspace_id: str, key: str, enabled: bool, user_id: str | None
    ) -> None:
        """Persist an operator control and its actor before reporting success."""
        if self.unreadable:
            raise RuntimeError("Safety record is unreadable")
        if key not in ("automation", "irrigation_armed"):
            raise ValueError("Unknown safety control")
        previous = self.controls.get(growspace_id, {}).copy()
        if previous.get(key) == enabled and not (
            key == "irrigation_armed" and self.irrigation_review_pending(growspace_id)
        ):
            return
        self.controls[growspace_id] = {
            "automation": previous.get("automation", True),
            "irrigation_armed": previous.get("irrigation_armed", False),
            key: enabled,
        }
        self.ledger.append(
            {
                "at": utcnow().isoformat(),
                "growspace_id": growspace_id,
                "action": key,
                "enabled": enabled,
                "user_id": user_id,
            }
        )
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise
        self._log_control(
            growspace_id, f"{key} {'enabled' if enabled else 'disabled'}", user_id
        )

    async def async_latch_emergency_stop(
        self,
        growspace_id: str,
        detail: str,
        outputs: tuple[str, ...],
        user_id: str | None = None,
    ) -> FaultRecord:
        """Persist the stop that the operator control will invoke in issue #791."""
        if self.unreadable:
            raise RuntimeError("Irrigation safety record is unreadable")
        existing = self.emergency_stop_for(growspace_id)
        if existing is not None:
            return existing
        now = utcnow().isoformat()
        record = FaultRecord(
            uuid4().hex, SafetyReason("emergency_stop", detail, now), outputs
        )
        self.emergency_stops[growspace_id] = record
        self.ledger.append(
            {
                "at": now,
                "growspace_id": growspace_id,
                "action": "emergency_stop",
                "user_id": user_id,
                **record.as_dict(),
            }
        )
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise
        self._log_control(growspace_id, "emergency stop", user_id)
        return record

    async def async_reset_emergency_stop(self, growspace_id: str, user_id: str) -> None:
        """Clear a verified stop; caller checks all managed outputs first."""
        if self.unreadable:
            raise RuntimeError("Safety record is unreadable")
        record = self.emergency_stops.pop(growspace_id, None)
        if record is None:
            raise ValueError("No emergency stop is latched")
        self.ledger.append(
            {
                "at": utcnow().isoformat(),
                "growspace_id": growspace_id,
                "action": "reset_safety",
                "fault_id": record.fault_id,
                "user_id": user_id,
            }
        )
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise
        self._log_control(growspace_id, "emergency stop reset", user_id)

    async def async_latch(
        self, growspace_id: str, code: str, detail: str, outputs: tuple[str, ...]
    ) -> FaultRecord:
        """Latch a fault and persist its audit record immediately."""
        existing = self.fault_for(growspace_id, outputs)
        if existing is not None:
            new_outputs = tuple(dict.fromkeys((*existing.outputs, *outputs)))
            if not self.unreadable and new_outputs != existing.outputs:
                updated = FaultRecord(existing.fault_id, existing.reason, new_outputs)
                self.faults[growspace_id] = updated
                self.ledger.append(
                    {
                        "at": utcnow().isoformat(),
                        "growspace_id": growspace_id,
                        "action": "fault_output_added",
                        "fault_id": updated.fault_id,
                        "outputs": list(new_outputs),
                    }
                )
                try:
                    await self._save()
                except Exception:
                    self.unreadable = True
                    raise
                return updated
            return existing
        now = utcnow().isoformat()
        record = FaultRecord(uuid4().hex, SafetyReason(code, detail, now), outputs)
        self.faults[growspace_id] = record
        self.ledger.append(
            {
                "at": now,
                "growspace_id": growspace_id,
                "action": "fault",
                **record.as_dict(),
            }
        )
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise
        return record

    async def async_acknowledge(self, growspace_id: str, user_id: str) -> None:
        """Clear a checked latch and write the operator identity to the ledger."""
        record = self.faults.pop(growspace_id, None)
        was_unreadable = self.unreadable
        previous_ledger = deque(self.ledger, maxlen=_LEDGER_LIMIT)
        self.unreadable = False
        self.ledger.append(
            {
                "at": utcnow().isoformat(),
                "growspace_id": growspace_id,
                "action": "acknowledge",
                "fault_id": record.fault_id if record else "fault_record_unreadable",
                "user_id": user_id,
            }
        )
        try:
            await self._save()
        except Exception:
            if record is not None:
                self.faults[growspace_id] = record
            self.unreadable = was_unreadable
            self.ledger = previous_ledger
            raise

    async def async_record_not_delivered(
        self,
        growspace_id: str,
        output: str,
        reason_code: str,
        detail: str,
        *,
        consecutive: int,
        off_confirmed: bool,
    ) -> None:
        """Record a pump cycle that was failed closed instead of delivered."""
        if self.unreadable:
            raise RuntimeError("Irrigation safety record is unreadable")
        self.ledger.append(
            {
                "at": utcnow().isoformat(),
                "growspace_id": growspace_id,
                "action": "cycle_not_delivered",
                "output": output,
                "reason_code": reason_code,
                "detail": detail,
                "consecutive": consecutive,
                "off_confirmed": off_confirmed,
            }
        )
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise

    async def async_record_transition(
        self, growspace_id: str, state: str, reason_code: str | None = None
    ) -> bool:
        """Write one transition per distinct state and reason, bounded by the ring."""
        if self.unreadable:
            raise RuntimeError("Irrigation safety record is unreadable")
        for row in reversed(self.ledger):
            if (
                row.get("growspace_id") == growspace_id
                and row.get("action") == "transition"
            ):
                if row.get("state") == state and row.get("reason_code") == reason_code:
                    return False
                break
        self.ledger.append(
            {
                "at": utcnow().isoformat(),
                "growspace_id": growspace_id,
                "action": "transition",
                "state": state,
                "reason_code": reason_code,
            }
        )
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise
        return True

    async def _save(self) -> None:
        """Use HA's atomic storage writer without a debounce window."""
        await self._store.async_save(
            {
                "faults": {
                    key: record.as_dict() for key, record in self.faults.items()
                },
                "emergency_stops": {
                    key: record.as_dict()
                    for key, record in self.emergency_stops.items()
                },
                "controls": self.controls,
                "overrides": {
                    growspace_id: {
                        subsystem.value: override.as_dict()
                        for subsystem, override in by_subsystem.items()
                    }
                    for growspace_id, by_subsystem in self.overrides.items()
                },
                "ledger": list(self.ledger),
            }
        )
