"""One config entry's durable template library, on disk.

The key carries the config entry ID, which is the whole of the isolation: two
Growspace Manager entries are two `.storage` documents that cannot see each
other's templates, defaults, drafts or generation, however alike their contents
look. An identity from one entry is simply absent from the other.

A save writes the complete document, so a mutation is composed in memory and
committed once. Home Assistant's `Store` writes through a temporary file and
renames it, so a commit either lands whole or does not land -- there is no
arrangement in which a revision appears without the draft it consumed having
been cleared. Nothing here is debounced: a published revision that a restart
could lose would not be immutable, it would be likely.

Loading is strict in one direction only. A store written at a *newer* version
is refused and left untouched, because a best-effort read is how a newer store
quietly becomes a lossy older one. Home Assistant's own `Store` enforces that
on the envelope and says so in its own vocabulary; this translates it into the
library's, so a caller has one error to handle whether the newer number was on
the envelope or inside the document.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import UnsupportedStorageVersionError
from homeassistant.helpers.storage import Store

from .errors import IncompatibleTemplateStore
from .records import STORE_VERSION, LibraryState

_LOGGER = logging.getLogger(__name__)

#: The `.storage` key prefix. The config entry ID is appended, and it is a hex
#: string, so the result is a filename without needing to be escaped.
STORAGE_KEY_PREFIX = "growspace_manager.label_templates"


def storage_key(entry_id: str) -> str:
    """Return the `.storage` key one config entry's library is written to."""
    return f"{STORAGE_KEY_PREFIX}.{entry_id}"


class LabelTemplateStore:
    """Reads and writes one config entry's complete library document."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Bind this store to one config entry and nothing else."""
        self.entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, storage_key(entry_id)
        )

    async def async_load(self) -> LibraryState:
        """Read the committed library, or an empty one on a fresh install."""
        try:
            stored = await self._store.async_load()
        except UnsupportedStorageVersionError as err:
            raise IncompatibleTemplateStore(
                found=err.found_version, supported=STORE_VERSION
            ) from err
        return LibraryState.from_dict(stored)

    async def async_save(self, state: LibraryState) -> None:
        """Commit one complete library state."""
        await self._store.async_save(state.as_dict())

    async def async_remove(self) -> None:
        """Delete this entry's library document.

        For the enclosing Home Assistant data lifecycle -- removing the config
        entry -- and never as a template-management shortcut. Nothing in the
        lifecycle operations calls it.
        """
        await self._store.async_remove()
