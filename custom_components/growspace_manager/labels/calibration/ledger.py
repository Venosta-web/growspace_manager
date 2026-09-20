"""The ledger: what this installation has measured, and what that authorizes.

One config entry, one history, and two operations on it. `async_record`
appends a measurement; `async_status` answers whether the newest measurement
of one printer still applies. There is no third: nothing here edits, replaces
or removes a record, because a print that named a calibration has to keep
being able to name it.

Recording is an administrator's operation and the authority is asked at the
moment of the mutation rather than captured when the flow opened, the same way
the template library asks it. An append is composed in memory and written
once, under a lock, and the in-memory state is replaced only after the write
returns -- so a failed write leaves the history exactly as it was.

What this module does *not* own is the printing of the calibration label.
`printing.py` puts the sheet on paper and hands back the Render Result it came
from; this records what the operator read off it, against the identities that
result captured. Splitting them is what makes "the numbers describe the sheet
in your hand" a property rather than a hope: a measurement cannot be recorded
against dependencies nobody printed.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from ...const import DOMAIN
from ..canonical.fonts import FontLibrary, shipped_font_identity
from ..canonical.profiles import CapabilityProfile
from ..canonical.result import RenderContext
from ..library.actor import Actor
from .errors import IncompatibleCalibrationStore
from .records import (
    CalibrationDependencies,
    CalibrationLedgerState,
    CalibrationScope,
    LocalCalibration,
    MeasurementBounds,
    PlacementMeasurement,
    validate_measurement,
)
from .sheet import SHEET_VERSION
from .staleness import CalibrationStatus, evaluate
from .store import CalibrationStore

_LOGGER = logging.getLogger(__name__)

#: Where the open ledgers live on `hass.data`, one per config entry.
_LEDGERS = "label_calibration_ledgers"


class LocalCalibrationLedger:
    """One config entry's append-only record of what its printers measure."""

    def __init__(self, hass: HomeAssistant, entry_id: str) -> None:
        """Bind this ledger to one config entry."""
        self.hass = hass
        self.entry_id = entry_id
        self._store = CalibrationStore(hass, entry_id)
        self._state: CalibrationLedgerState | None = None
        self._lock = asyncio.Lock()

    async def async_load(self) -> CalibrationLedgerState:
        """Return the loaded history, reading it the first time."""
        if self._state is None:
            self._state = await self._store.async_load()
        return self._state

    async def async_record(
        self,
        actor: Actor,
        *,
        measurement: PlacementMeasurement,
        dependencies: CalibrationDependencies,
        sheet_raster_identity: str,
        printed_density: str,
        notes: str | None = None,
    ) -> LocalCalibration:
        """Append one measurement, and never touch the ones already there.

        The measurement is validated against the profile geometry its own
        dependencies carry -- not against whatever profile is selected now --
        so a record cannot be admitted by a profile it was not taken on.
        """
        recorded_by = actor.administrator()
        validate_measurement(
            measurement, MeasurementBounds.of_dependencies(dependencies)
        )
        record = LocalCalibration(
            id=ulid_now(),
            recorded_at=dt_util.utcnow().isoformat(),
            recorded_by=recorded_by,
            measurement=measurement,
            dependencies=dependencies,
            sheet_raster_identity=sheet_raster_identity,
            printed_density=printed_density,
            notes=notes,
        )
        async with self._lock:
            state = await self.async_load()
            appended = state.appended(record)
            await self._store.async_save(appended)
            self._state = appended
        _LOGGER.info(
            "Recorded a local label calibration for %s on %s",
            record.scope.device_id,
            record.scope.label_size_id,
        )
        return record

    async def async_status(
        self,
        *,
        required: CalibrationDependencies,
        now: Any | None = None,
    ) -> CalibrationStatus:
        """Judge this printer's newest measurement against what a print needs.

        The scope selects the candidate and the fingerprint judges it, which
        is why an unmeasured printer and a printer whose renderer changed come
        back as two different states rather than as one absent identity.
        """
        state = await self.async_load()
        return evaluate(
            state.newest(required.scope),
            required=required,
            now=now or dt_util.utcnow(),
        )

    async def async_history(
        self, scope: CalibrationScope
    ) -> tuple[LocalCalibration, ...]:
        """Every measurement of one printer, stock and mounting, oldest first."""
        state = await self.async_load()
        return state.within(scope)

    async def async_snapshot(self, actor: Actor) -> dict[str, Any]:
        """The whole history, for any authenticated user.

        Readable rather than privileged: what a printer was measured at
        explains why a print is refused, and hiding it from the person holding
        the refusal would make the refusal unexplainable.
        """
        actor.authenticated()
        state = await self.async_load()
        return {
            "entry_id": self.entry_id,
            "records": [record.summary() for record in state.records],
        }


def required_dependencies(
    profile: CapabilityProfile,
    fonts: FontLibrary,
    *,
    device_id: str,
    firmware: str | None = None,
) -> CalibrationDependencies:
    """What a print about to happen would need a calibration to have been of.

    Answerable before anything is rendered, which is what lets the resulting
    identity go *into* the Render Context rather than being compared against
    it afterwards.
    """
    return CalibrationDependencies.for_profile(
        profile,
        device_id=device_id,
        sheet_version=SHEET_VERSION,
        font_identity=shipped_font_identity(fonts),
        firmware=firmware,
    )


def recorded_dependencies(
    context: RenderContext,
    profile: CapabilityProfile,
    fonts: FontLibrary,
    *,
    device_id: str,
    firmware: str | None = None,
) -> CalibrationDependencies:
    """What the calibration label that was just printed actually depended on."""
    return CalibrationDependencies.from_render(
        context,
        profile,
        device_id=device_id,
        sheet_version=SHEET_VERSION,
        font_identity=shipped_font_identity(fonts),
        firmware=firmware,
    )


async def async_get_calibration_ledger(
    hass: HomeAssistant, entry_id: str
) -> LocalCalibrationLedger:
    """Return this config entry's ledger, opening it the first time.

    One instance per entry, because the lock that makes an append one commit
    only serializes the callers that share it.

    A store this integration cannot read comes back as a **contained** ledger
    rather than as an exception, the way the template library's does: setting
    up an entry must not fail because its calibration history was written by a
    newer version, and every call that needed to read it raises for itself.
    """
    ledgers: dict[str, LocalCalibrationLedger] = hass.data.setdefault(
        DOMAIN, {}
    ).setdefault(_LEDGERS, {})
    ledger = ledgers.get(entry_id)
    if ledger is None:
        ledger = LocalCalibrationLedger(hass, entry_id)
        ledgers[entry_id] = ledger
    try:
        await ledger.async_load()
    except IncompatibleCalibrationStore:
        _LOGGER.error(
            "The label calibration history of config entry %s was written by "
            "a newer Growspace Manager and has been left untouched; "
            "production label printing is unavailable for it",
            entry_id,
        )
    return ledger


def async_release_calibration_ledger(hass: HomeAssistant, entry_id: str) -> None:
    """Forget one config entry's ledger without touching what it stored."""
    ledgers = hass.data.get(DOMAIN, {}).get(_LEDGERS)
    if isinstance(ledgers, dict):
        ledgers.pop(entry_id, None)
