"""Persistent storage for Growspace Manager AI conversation threads."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.helpers.storage import Store

_LOGGER = logging.getLogger(__name__)


class ConversationStore:
    """Stores and retrieves conversation threads keyed by growspace ID.

    The frontend enforces thread eviction (MAX_PINNED_THREADS / MAX_RECENT_THREADS)
    before calling save_threads, so this class is a thin persistence layer only.

    Storage format::

        {
            "threads_by_growspace": {
                "<growspace_id>": [<thread>, ...]
            }
        }
    """

    def __init__(self, store: Store) -> None:
        """Initialise with a pre-constructed HA Store."""
        self._store = store
        self._data: dict[str, list[dict[str, Any]]] = {}

    async def async_load(self) -> None:
        """Load persisted threads into memory."""
        raw = await self._store.async_load() or {}
        self._data = raw.get("threads_by_growspace", {})
        _LOGGER.debug(
            "Loaded conversation threads for %d growspace(s)", len(self._data)
        )

    def get_threads(self, growspace_id: str) -> list[dict[str, Any]]:
        """Return the thread list for *growspace_id* (empty list if none)."""
        return list(self._data.get(growspace_id, []))

    async def save_threads(
        self, growspace_id: str, threads: list[dict[str, Any]]
    ) -> None:
        """Replace the thread list for *growspace_id* and persist to disk."""
        self._data[growspace_id] = threads
        await self._store.async_save({"threads_by_growspace": self._data})
        _LOGGER.debug(
            "Saved %d conversation thread(s) for growspace %s",
            len(threads),
            growspace_id,
        )
