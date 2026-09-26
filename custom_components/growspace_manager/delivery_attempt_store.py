"""Durable Delivery Attempts, one store per growspace (ADR-0055).

The daily cycle limit and volume cap are enforced on Dispensed Volume, the sum
of today's charges across a growspace's attempts (ADR-0054). An attempt is
charged the moment its pump confirms ON, and that write reaches disk before the
cycle proceeds, so a restart mid-shot keeps the shot counted and no restart
hands out a fresh daily allowance (#787). Its close only tops the charge up, so
it goes through a batched save: a lost close costs at most a top-up.

Each growspace has a file of its own, so a shot rewrites one growspace's week
and not everyone's. A file that exists but cannot be read is never written
over. It holds that growspace's cycles as a fault until it is repaired or an
admin acknowledges it, because a cap whose history is unknown has to assume it
is spent.
"""

from __future__ import annotations

import logging
from os.path import exists
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .domain.delivery_attempt import (
    DeliveryAttempt,
    DispensedVolume,
    dispensed_volume,
    retained,
)

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

# Coalesces a close into the next write, as Reliability Evidence does.
CLOSE_SAVE_DELAY_SECONDS = 60


class DeliveryRecordUnreadable(RuntimeError):
    """The growspace's Delivery Attempts could not be read or written."""


class GrowspaceDeliveries:
    """One growspace's Delivery Attempts, and the Dispensed Volume they add up to."""

    def __init__(
        self,
        growspace_id: str,
        *,
        hass: HomeAssistant | None = None,
        entry_id: str | None = None,
    ) -> None:
        """Persist under the entry and growspace, or keep memory only without hass."""
        self.growspace_id = growspace_id
        self.attempts: list[DeliveryAttempt] = []
        self.unreadable = False
        self.unreadable_since: str | None = None
        self.loaded = False
        self._hass = hass
        self._key = f"growspace_manager.deliveries_{entry_id}_{growspace_id}"
        self._store: Store[dict[str, Any]] | None = (
            Store(hass, STORAGE_VERSION, self._key) if hass is not None else None
        )

    async def async_load(self) -> None:
        """Read the attempts, or fail closed on a file that cannot be trusted."""
        self.loaded = True
        if self._store is None or self._hass is None:
            return
        try:
            data = await self._store.async_load()
            if data is None:
                path = self._hass.config.path(".storage", self._key)
                if await self._hass.async_add_executor_job(exists, path):
                    self._fail_closed()
                return
            self.attempts = self._decode(data)
        except Exception:
            _LOGGER.exception(
                "Delivery Attempts of growspace %s are unreadable; its cycles are held",
                self.growspace_id,
            )
            self.attempts = []
            self._fail_closed()

    def _decode(self, data: Any) -> list[DeliveryAttempt]:
        """Validate the whole document before accepting any attempt in it."""
        if (
            not isinstance(data, dict)
            or data.get("growspace_id") != self.growspace_id
            or not isinstance(data.get("attempts"), list)
        ):
            raise ValueError("delivery store is not this growspace's")
        attempts = [DeliveryAttempt.from_dict(row) for row in data["attempts"]]
        if any(attempt.growspace_id != self.growspace_id for attempt in attempts):
            raise ValueError("an attempt is filed under another growspace")
        if len({attempt.attempt_id for attempt in attempts}) != len(attempts):
            raise ValueError("an attempt is recorded twice")
        return attempts

    def _fail_closed(self) -> None:
        self.unreadable = True
        self.unreadable_since = self.unreadable_since or dt_util.utcnow().isoformat()

    def dispensed(self) -> DispensedVolume:
        """Return today's Dispensed Volume, today being Home Assistant's local day."""
        return dispensed_volume(self.attempts, dt_util.now().date())

    def _document(self) -> dict[str, Any]:
        return {
            "growspace_id": self.growspace_id,
            "attempts": [attempt.as_dict() for attempt in self.attempts],
        }

    def _prune(self) -> None:
        self.attempts = retained(
            self.attempts, now=dt_util.utcnow(), today=dt_util.now().date()
        )

    async def async_charge(self, attempt: DeliveryAttempt) -> None:
        """Charge an actuated attempt, and have it on disk before returning.

        The charge is held in memory whatever happens next: the pump did
        confirm ON. A failed write, or a file that was never readable, raises
        and leaves the growspace held.
        """
        self.attempts.append(attempt)
        if self._store is None:
            return
        if self.unreadable:
            raise DeliveryRecordUnreadable(
                f"Delivery Attempts of growspace {self.growspace_id} are unreadable"
            )
        self._prune()
        try:
            await self._store.async_save(self._document())
        except Exception as err:
            self._fail_closed()
            raise DeliveryRecordUnreadable(
                f"Could not record the charge of growspace {self.growspace_id}"
            ) from err

    def close(self, closed: DeliveryAttempt) -> None:
        """Replace an open attempt with its close, saved in the next batch."""
        self.attempts = [
            closed if attempt.attempt_id == closed.attempt_id else attempt
            for attempt in self.attempts
        ]
        if self._store is None or self.unreadable:
            return
        self._prune()
        self._store.async_delay_save(self._document, CLOSE_SAVE_DELAY_SECONDS)

    async def async_acknowledge(self) -> None:
        """Start the record again from what is known, on an admin's word.

        What could not be read is written over, as an acknowledged
        ``fault_record_unreadable`` is: the charges this process made are kept,
        and whatever else was charged today is given up.
        """
        if self._store is not None:
            self._prune()
            try:
                await self._store.async_save(self._document())
            except Exception as err:
                raise DeliveryRecordUnreadable(
                    f"Could not rewrite the delivery record of {self.growspace_id}"
                ) from err
        self.unreadable = False
        self.unreadable_since = None

    async def async_remove(self) -> None:
        """Delete the file of a growspace that no longer exists."""
        self.attempts = []
        if self._store is not None:
            await self._store.async_remove()


class DeliveryAttemptStore:
    """The entry's Delivery Attempts, loaded one growspace at a time."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Keep each growspace's attempts apart from every other store."""
        self._hass = hass
        self._entry_id = entry_id
        self._growspaces: dict[str, GrowspaceDeliveries] = {}

    async def async_load(self, growspace_id: str) -> GrowspaceDeliveries:
        """Return a growspace's attempts, read from disk the first time only.

        Loaded once per entry, so an irrigation coordinator rebuilt for the same
        growspace shares the attempts, and any close still waiting to be saved,
        with the one it replaces.
        """
        deliveries = self._growspaces.get(growspace_id)
        if deliveries is None:
            deliveries = GrowspaceDeliveries(
                growspace_id, hass=self._hass, entry_id=self._entry_id
            )
            self._growspaces[growspace_id] = deliveries
        if not deliveries.loaded:
            await deliveries.async_load()
        return deliveries

    async def async_remove(self, growspace_id: str) -> None:
        """Delete a removed growspace's attempts."""
        deliveries = self._growspaces.pop(growspace_id, None) or GrowspaceDeliveries(
            growspace_id, hass=self._hass, entry_id=self._entry_id
        )
        await deliveries.async_remove()
