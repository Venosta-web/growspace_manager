"""Durable Delivery Attempts, one store per growspace (ADR-0055).

The daily cycle limit and volume cap are enforced on Dispensed Volume, the sum
of today's charges across a growspace's attempts (ADR-0054). Two writes reach
disk before the cycle proceeds. The first is before the ON command, once the
gate has passed, so a crash between command and confirmation still leaves an
open attempt behind. The second is at confirm-ON, which charges it, so a restart
mid-shot keeps the shot counted and no restart hands out a fresh daily
allowance (#787); a drain is written at both moments too, and never charged. Its close only tops the charge up, and a suppressed request
charges nothing, so both go through a batched save: a lost one costs at most a
top-up or a row of history.

An attempt still open when the file is first read belongs to a process that
stopped before closing it. The irrigation coordinator closes it
``interrupted`` once its pump reads ON or OFF (ADR-0055 item 9), and a lost
close is found open again at the next start.

Each growspace has a file of its own, so a shot rewrites one growspace's week
and not everyone's. A file that exists but cannot be read is never written
over. It holds that growspace's cycles as a fault until it is repaired or an
admin acknowledges it, because a cap whose history is unknown has to assume it
is spent.

The same file carries the growspace's calibration evidence, the Tank–Pump
Disagreement (ADR-0064 item 9). It is never enforced, so it never holds
anything either: a malformed record is started afresh rather than failed
closed, and it is saved in the batch like a close.
"""

from __future__ import annotations

import base64
from dataclasses import replace
from datetime import date, datetime
import json
import logging
from os.path import exists
from typing import Any
import zlib

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .domain.delivery_attempt import (
    DeliveryAttempt,
    DispensedVolume,
    attempts_between,
    dispensed_volume,
    retained,
    with_suppression,
)
from .domain.tank_pump_disagreement import TankPumpDisagreement

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
# Keep small histories human-readable; large ones preserve every field losslessly.
COMPACT_AFTER_BYTES = 64_000
MAX_EXPANDED_BYTES = 16_000_000

# Coalesces a close or a suppression into the next write, as Reliability
# Evidence does.
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
        self._encoded_rows: dict[str, tuple[DeliveryAttempt, bytes]] = {}
        self._compression_prefix: list[DeliveryAttempt] = []
        self._compressor = zlib.compressobj()
        self._compressed_prefix = self._compressor.compress(b"[")
        self._dispensed_cache: (
            tuple[date, tuple[DeliveryAttempt, ...], DispensedVolume] | None
        ) = None
        self.calibration = TankPumpDisagreement()
        self.unreadable = False
        self.unreadable_since: str | None = None
        self.loaded = False
        # Attempts a previous process left open, until this one closes them.
        self._left_open: set[str] = set()
        self._hass = hass
        self._key = f"growspace_manager.deliveries_{entry_id}_{growspace_id}"
        self._store: Store[dict[str, Any]] | None = (
            Store(hass, STORAGE_VERSION, self._key, serialize_in_event_loop=True)
            if hass is not None
            else None
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
            self.calibration = self._decode_calibration(data.get("calibration"))
            self._left_open = {
                attempt.attempt_id for attempt in self.attempts if attempt.is_open
            }
        except Exception:
            _LOGGER.exception(
                "Delivery Attempts of growspace %s are unreadable; its cycles are held",
                self.growspace_id,
            )
            self.attempts = []
            self._fail_closed()

    def _decode(self, data: Any) -> list[DeliveryAttempt]:
        """Validate the whole document before accepting any attempt in it."""
        if isinstance(data, dict) and "attempts_zlib" in data:
            data = {**data, "attempts": self._expand_attempts(data["attempts_zlib"])}
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

    def _decode_calibration(self, data: Any) -> TankPumpDisagreement:
        """Read the calibration evidence, or start it afresh; it holds nothing."""
        if data is None:
            return TankPumpDisagreement()
        try:
            return TankPumpDisagreement.from_dict(data)
        except TypeError, ValueError:
            _LOGGER.warning(
                "Calibration evidence of growspace %s is unreadable; it starts again",
                self.growspace_id,
            )
            return TankPumpDisagreement()

    def _fail_closed(self) -> None:
        self.unreadable = True
        self.unreadable_since = self.unreadable_since or dt_util.utcnow().isoformat()

    def dispensed(self) -> DispensedVolume:
        """Return today's Dispensed Volume, today being Home Assistant's local day."""
        today = dt_util.now().date()
        rows = tuple(self.attempts)
        cached = self._dispensed_cache
        # Attempts are immutable. Tuple equality catches replacements anywhere
        # in the public list, as well as appends, pruning and direct test seeds.
        if cached is None or cached[0] != today or cached[1] != rows:
            result = dispensed_volume(rows, today)
            self._dispensed_cache = (today, rows, result)
            return result
        return cached[2]

    def between(self, starts_at: datetime, ends_at: datetime) -> list[DeliveryAttempt]:
        """Return the attempts that touch ``[starts_at, ends_at)``, oldest first.

        A record that could not be read raises rather than answering with an
        empty day: nothing recorded and nothing known are different answers.
        """
        if self.unreadable:
            raise DeliveryRecordUnreadable(
                f"Delivery Attempts of growspace {self.growspace_id} are unreadable"
            )
        return attempts_between(self.attempts, starts_at, ends_at)

    @staticmethod
    def _expand_attempts(encoded: Any) -> Any:
        """Bound decompression before the ordinary whole-record validation."""
        if not isinstance(encoded, str):
            raise TypeError("compressed attempts are not text")
        packed = base64.b64decode(encoded, validate=True)
        decoder = zlib.decompressobj()
        raw = decoder.decompress(packed, MAX_EXPANDED_BYTES + 1)
        if len(raw) > MAX_EXPANDED_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError("compressed attempts are oversized or incomplete")
        return json.loads(raw)

    def _document(self) -> dict[str, Any]:
        """Write the same lossless rows, compacting a larger week's history.

        Immutable attempts let unchanged rows reuse their encoding. Old v1
        documents remain readable; the compressed payload has its own explicit
        key and is validated by the same decoder after expansion.
        """
        cache = {}
        rows = []
        for attempt in self.attempts:
            previous = self._encoded_rows.get(attempt.attempt_id)
            encoded = (
                previous[1]
                if previous is not None and previous[0] is attempt
                else json.dumps(attempt.as_dict(), separators=(",", ":")).encode()
            )
            cache[attempt.attempt_id] = (attempt, encoded)
            rows.append(encoded)
        self._encoded_rows = cache
        raw = b"[" + b",".join(rows) + b"]"
        document = {
            "growspace_id": self.growspace_id,
            "calibration": self.calibration.as_dict(),
        }
        if len(raw) > COMPACT_AFTER_BYTES:
            document["attempts_zlib"] = base64.b64encode(
                self._compact_rows(rows)
            ).decode("ascii")
        else:
            document["attempts"] = json.loads(raw)
        return document

    def _compact_rows(self, rows: list[bytes]) -> bytes:
        """Reuse a closed prefix; requests and charges change only its tail.

        A changed or pruned prefix resets the compressor. Copies finalize the
        document without mutating the reusable stream. This keeps repeated
        write-before-ON saves from recompressing the entire week on the loop.
        """
        length = len(self._compression_prefix)
        if self.attempts[:length] != self._compression_prefix:
            self._compression_prefix = []
            self._compressor = zlib.compressobj()
            self._compressed_prefix = self._compressor.compress(b"[")
            length = 0
        while length < len(self.attempts) and not self.attempts[length].is_open:
            part = (b"," if length else b"") + rows[length]
            self._compressed_prefix += self._compressor.compress(part)
            self._compression_prefix.append(self.attempts[length])
            length += 1
        compressor = self._compressor.copy()
        tail = b",".join(rows[length:])
        if tail and length:
            tail = b"," + tail
        return (
            self._compressed_prefix
            + compressor.compress(tail + b"]")
            + compressor.flush()
        )

    def _prune(self) -> None:
        self.attempts = retained(
            self.attempts, now=dt_util.utcnow(), today=dt_util.now().date()
        )

    async def async_request(self, attempt: DeliveryAttempt) -> None:
        """Record an attempt the gate passed, on disk before its ON command.

        A failed write, or a file that was never readable, raises and leaves
        the growspace held, and the pump is never commanded.
        """
        self._put(attempt)
        await self._async_write_through(
            f"Could not record the request of growspace {self.growspace_id}"
        )

    async def async_charge(self, attempt: DeliveryAttempt) -> None:
        """Charge an actuated attempt, and have it on disk before returning.

        A drain is written the same way and charges nothing. The charge is held
        in memory whatever happens next: the pump did confirm ON. A failed write, or a file that was never readable, raises
        and leaves the growspace held.
        """
        self._put(attempt)
        await self._async_write_through(
            f"Could not record the charge of growspace {self.growspace_id}"
        )

    def suppress(self, attempt: DeliveryAttempt) -> None:
        """Record a refused request, merged into its run, saved in the next batch."""
        self.attempts = with_suppression(self.attempts, attempt)
        self._delay_save()

    def close(self, closed: DeliveryAttempt) -> None:
        """Replace an open attempt with its close, saved in the next batch."""
        self._put(closed)
        self._delay_save()

    def set_calibration(self, calibration: TankPumpDisagreement) -> None:
        """Keep the calibration evidence, saved in the next batch when it moved."""
        if calibration == self.calibration:
            return
        self.calibration = calibration
        self._delay_save()

    def left_open(self, output: str | None = None) -> list[DeliveryAttempt]:
        """Return the attempts a previous process left open, of ``output`` if given.

        Only what was already open when the file was read counts. A cycle of
        this process is open too while it runs, and it is this process's.
        """
        return [
            attempt
            for attempt in self.attempts
            if attempt.attempt_id in self._left_open
            and (output is None or attempt.output == output)
        ]

    def record_interrupted_valve(
        self,
        output: str,
        commanded_at: datetime | None,
        confirmed_at: datetime | None,
    ) -> None:
        """Keep a recovered valve's readback without prematurely closing its supply."""
        for attempt in self.left_open():
            if any(valve.output == output for valve in attempt.valves):
                self._put(
                    replace(
                        attempt,
                        valves=tuple(
                            replace(
                                valve,
                                off_commanded_at=commanded_at,
                                off_confirmed_at=confirmed_at,
                            )
                            if valve.output == output
                            else valve
                            for valve in attempt.valves
                        ),
                    )
                )
                self._delay_save()

    def interrupt(
        self,
        output: str,
        found_at: datetime,
        *,
        off_commanded_at: datetime | None = None,
        off_confirmed_at: datetime | None = None,
    ) -> list[DeliveryAttempt]:
        """Close what a previous process left open on ``output`` as ``interrupted``.

        Saved in the next batch, like any close: one that is lost is found
        open, and closed, again at the next start.
        """
        closed = [
            attempt.interrupted(
                found_at,
                off_commanded_at=off_commanded_at,
                off_confirmed_at=off_confirmed_at,
            )
            for attempt in self.left_open(output)
        ]
        for attempt in closed:
            self._left_open.discard(attempt.attempt_id)
            self._put(attempt)
        if closed:
            self._delay_save()
        return closed

    def _put(self, attempt: DeliveryAttempt) -> None:
        """Replace the attempt of the same id, or add it as a new row."""
        for index, current in enumerate(self.attempts):
            if current.attempt_id == attempt.attempt_id:
                self.attempts[index] = attempt
                return
        self.attempts.append(attempt)

    async def _async_write_through(self, failure: str) -> None:
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
            raise DeliveryRecordUnreadable(failure) from err

    def _delay_save(self) -> None:
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
