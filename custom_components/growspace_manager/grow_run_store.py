"""Write-through persistence of every Growspace's Run Ledger (#668).

Grow Runs are domain records, not entities (ADR-0035), and their history must
survive restarts, Recorder purges and source deletion (ADR-0033/0034). They
therefore live in a store of their own, apart from the debounced configuration
writes: a lifecycle command is decided, persisted and only then published, and
the lock around those three steps is what makes zero-or-one Active Run a rule
rather than a race.

A file that exists but cannot be read is never written over. Every command is
refused until someone repairs it, because the alternative -- starting afresh --
would reissue Sequence Numbers and silently erase the history it failed to read.
"""

from __future__ import annotations

import asyncio
import logging
from os.path import exists
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY
from .domain.grow_run import GrowRun, RunLedger, RunStoreUnreadable

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1

#: The Grow Run Lifecycle Event: one per committed lifecycle command.
EVENT_GROW_RUN_LIFECYCLE = f"{DOMAIN}_grow_run_lifecycle"

#: The logbook category a lifecycle command is written under.
CATEGORY_GROW_RUN = "grow_run"


class GrowRunStore:
    """Hold each Growspace's Run Ledger and commit changes to it atomically."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Keep Run history separate from the debounced configuration store."""
        self._hass = hass
        self._key = f"growspace_manager.grow_runs_{entry_id}"
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, self._key)
        self._ledgers: dict[str, RunLedger] = {}
        self.lock = asyncio.Lock()
        self.unreadable = False

    async def async_load(self) -> None:
        """Read every ledger, or fail closed on a file that cannot be trusted."""
        try:
            data = await self._store.async_load()
            if data is None:
                path = self._hass.config.path(".storage", self._key)
                self.unreadable = await self._hass.async_add_executor_job(exists, path)
                return
            self._ledgers = self._decode(data)
        except Exception:
            _LOGGER.exception("Grow Run history is unreadable; every Run command held")
            self.unreadable = True
            self._ledgers = {}

    @staticmethod
    def _decode(data: Any) -> dict[str, RunLedger]:
        """Validate the whole document before accepting any ledger in it."""
        if not isinstance(data, dict) or not isinstance(data.get("ledgers"), dict):
            raise TypeError("Grow Run store has no ledger map")
        ledgers: dict[str, RunLedger] = {}
        for growspace_id, raw in data["ledgers"].items():
            ledger = RunLedger.from_dict(raw)
            if ledger.growspace_id != growspace_id:
                raise ValueError("a ledger is filed under another Growspace")
            ledgers[growspace_id] = ledger
        return ledgers

    def ledger(self, growspace_id: str) -> RunLedger:
        """Return a Growspace's ledger; one that never started a Run is empty."""
        if self.unreadable:
            raise RunStoreUnreadable(
                "Grow Run history could not be read; no Run command is accepted "
                "until it is repaired",
                current_revision=None,
            )
        return self._ledgers.get(growspace_id) or RunLedger(growspace_id)

    def active_run(self, growspace_id: str) -> GrowRun | None:
        """The Growspace's Active Run, or None -- also when the store is unreadable."""
        if self.unreadable:
            return None
        return self.ledger(growspace_id).active_run

    async def async_commit(self, ledger: RunLedger) -> None:
        """Persist one ledger before anything can report it.

        Must be called holding :attr:`lock`. A failed write leaves the
        in-memory ledger exactly as it was, so nothing unsaved is ever visible.
        """
        if self.unreadable:
            raise RunStoreUnreadable(
                "Grow Run history could not be read", current_revision=None
            )
        staged = {**self._ledgers, ledger.growspace_id: ledger}
        await self._store.async_save(
            {"ledgers": {key: value.as_dict() for key, value in staged.items()}}
        )
        self._ledgers = staged

    def announce_start(self, run: GrowRun, user_id: str | None) -> None:
        """Emit the lifecycle event and the logbook line for a committed start."""
        actor = f"HA user {user_id}" if user_id else "the system"
        self._hass.bus.async_fire(
            EVENT_GROW_RUN_LIFECYCLE,
            {
                "growspace_id": run.growspace_id,
                "run_id": run.run_id,
                "sequence_number": run.sequence_number,
                "command": "start",
                "revision": run.audit[-1].resulting_revision,
            },
        )
        self._hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                "growspace_id": run.growspace_id,
                "category": CATEGORY_GROW_RUN,
                "message": f"Run #{run.sequence_number} started by {actor}",
                "timestamp": run.started_at.isoformat(),
                "user_id": user_id,
            },
        )
