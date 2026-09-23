"""Write-through fault latches and bounded irrigation safety ledger."""

from __future__ import annotations

from collections import deque
import logging
from os.path import exists
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util.dt import utcnow

from .domain.irrigation_safety import FaultRecord, SafetyReason

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
        self.ledger: deque[dict[str, Any]] = deque(maxlen=_LEDGER_LIMIT)
        self.unreadable = False
        self._unreadable_since: str | None = None

    async def async_load(self) -> None:
        """Fail closed when existing safety data cannot be read or validated."""
        try:
            data = await self._store.async_load()
            if data is None:
                path = self._hass.config.path(".storage", self._key)
                self.unreadable = await self._hass.async_add_executor_job(exists, path)
                if self.unreadable:
                    self._unreadable_since = utcnow().isoformat()
                return
            self.faults, self.emergency_stops, self.ledger = self._decode(data)
        except Exception:
            _LOGGER.exception("Irrigation safety record is unreadable; all cycles held")
            self.unreadable = True
            self._unreadable_since = utcnow().isoformat()
            self.faults.clear()
            self.emergency_stops.clear()

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

    async def async_latch_emergency_stop(
        self, growspace_id: str, detail: str, outputs: tuple[str, ...]
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
                **record.as_dict(),
            }
        )
        try:
            await self._save()
        except Exception:
            self.unreadable = True
            raise
        return record

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
                "ledger": list(self.ledger),
            }
        )
