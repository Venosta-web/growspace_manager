"""One config entry's calibration history, on disk.

The same arrangement the template library uses, and for the same reasons. The
key carries the config entry ID, so two Growspace Manager entries keep two
histories that cannot see each other's printers. A save writes the complete
document, so an append lands whole or does not land -- and this document is an
audit record, so a debounced write that a restart could lose would make
"immutable" mean "probably".

Loading is strict in one direction: a store written at a newer version is
refused and left untouched. Home Assistant's own `Store` enforces that on the
envelope and says so in its vocabulary; this translates it into this route's.
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import UnsupportedStorageVersionError
from homeassistant.helpers.storage import Store

from .errors import IncompatibleCalibrationStore
from .records import STORE_VERSION, CalibrationLedgerState

#: The `.storage` key prefix. The config entry ID is appended, and it is a hex
#: string, so the result is a filename without needing to be escaped.
STORAGE_KEY_PREFIX = "growspace_manager.label_calibration"


def storage_key(entry_id: str) -> str:
    """Return the `.storage` key one config entry's history is written to."""
    return f"{STORAGE_KEY_PREFIX}.{entry_id}"


class CalibrationStore:
    """Reads and writes one config entry's complete calibration history."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Bind this store to one config entry and nothing else."""
        self.entry_id = entry_id
        self._store: Store[dict[str, Any]] = Store(
            hass, STORE_VERSION, storage_key(entry_id)
        )

    async def async_load(self) -> CalibrationLedgerState:
        """Read the committed history, or an empty one on a fresh install."""
        try:
            stored = await self._store.async_load()
        except UnsupportedStorageVersionError as err:
            raise IncompatibleCalibrationStore(
                found=err.found_version, supported=STORE_VERSION
            ) from err
        return CalibrationLedgerState.from_dict(stored)

    async def async_save(self, state: CalibrationLedgerState) -> None:
        """Commit one complete history."""
        await self._store.async_save(state.as_dict())

    async def async_remove(self) -> None:
        """Delete this entry's calibration document.

        For the enclosing Home Assistant data lifecycle -- removing the config
        entry -- and never as a way to correct a measurement. Nothing in this
        route calls it.
        """
        await self._store.async_remove()
