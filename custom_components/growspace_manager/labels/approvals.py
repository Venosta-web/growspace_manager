"""What an operator approved, held until they print it -- or until it lapses.

A print route refuses unless the raster it would produce now is the raster
the operator looked at, and that raster is a pure function of the layout, the
content snapshot, the profile and the density. The snapshot is the awkward
one: it carries the instant it was captured, the instant is part of the
Render Context, and every preview captures a new one. So "print what I
approved" cannot be re-derived from a second request -- a fresh capture would
be a fresh instant, a different raster identity, and a refusal every time.

The approved inputs are therefore **held here**, server-side, and a print
names them by an opaque ID. Nothing a client sends can substitute for them:
the client only ever presents the ID and the identity it approved, and the
route re-renders from what was held and compares.

The same holder keeps the calibration sheets that were really printed, for the
same reason in the other direction: a measurement may only be recorded against
the dependencies of a sheet that reached paper, so the sheet's dependencies
stay here rather than making a round trip through the card.

Nothing here is persisted. A restart forgets every approval, which is the
honest answer: the operator previews again, and a label that has sat
unprinted across a restart is exactly the one worth looking at twice.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from homeassistant.util.ulid import ulid_now

from ..const import DOMAIN
from .canonical.content import LabelContentSnapshot
from .canonical.profiles import CapabilityProfile
from .printing import CalibrationPrint, LayoutSource

#: How long an approval stays printable. Long enough to fetch a roll and walk
#: to the printer, short enough that nobody prints a morning's preview after
#: lunch without seeing it again.
APPROVAL_TTL = timedelta(minutes=15)

#: How many approvals one config entry keeps. Every preview mints one, so a
#: busy editor would otherwise grow this without bound; the oldest go first.
APPROVAL_LIMIT = 32

#: Where the holders live on `hass.data`, one per config entry.
_HOLDERS = "label_print_approvals"

#: The three things held, which are never interchangeable.
DRAFT_APPROVAL = "draft"
RECORD_APPROVAL = "record"
CALIBRATION_SHEET = "calibration_sheet"


@dataclass(frozen=True, slots=True)
class DraftApproval:
    """A draft preview an administrator may put on paper as a test print.

    It pins the draft *version* rather than its layout: the test print reads
    the draft again and refuses if it has moved, so the layout on paper is
    always the stored one and never a copy that outlived an edit.
    """

    draft_id: str
    template_id: str | None
    label_size_id: str
    draft_version: int
    content: LabelContentSnapshot
    profile: CapabilityProfile
    density: str
    raster_identity: str


@dataclass(frozen=True, slots=True)
class RecordApproval:
    """A published layout rendered for one real record, ready to print."""

    source: LayoutSource
    content: LabelContentSnapshot
    profile: CapabilityProfile
    density: str
    device_id: str
    raster_identity: str


@dataclass(frozen=True, slots=True)
class CalibrationSheet:
    """A calibration label that really reached paper, awaiting its numbers."""

    printed: CalibrationPrint
    profile: CapabilityProfile
    density: str
    device_id: str


@dataclass(frozen=True, slots=True)
class Held:
    """One held value, and when it stops being printable."""

    id: str
    kind: str
    value: Any
    expires_at: datetime


class ApprovalHolder:
    """One config entry's short-lived approvals, oldest evicted first."""

    def __init__(
        self, *, ttl: timedelta = APPROVAL_TTL, limit: int = APPROVAL_LIMIT
    ) -> None:
        """Start empty."""
        self._ttl = ttl
        self._limit = limit
        self._held: OrderedDict[str, Held] = OrderedDict()

    def hold(self, kind: str, value: Any, *, now: datetime | None = None) -> str:
        """Keep one value and return the ID that names it."""
        instant = now or dt_util.utcnow()
        self._expire(instant)
        held = Held(
            id=ulid_now(), kind=kind, value=value, expires_at=instant + self._ttl
        )
        self._held[held.id] = held
        while len(self._held) > self._limit:
            self._held.popitem(last=False)
        return held.id

    def get(self, held_id: str, kind: str, *, now: datetime | None = None) -> Any:
        """Return the value held under one ID, or `None` if it has lapsed.

        A kind that does not match is the same answer as an ID that was never
        issued: a calibration sheet cannot be printed as a label, and a label
        approval cannot have a measurement recorded against it.
        """
        self._expire(now or dt_util.utcnow())
        held = self._held.get(held_id)
        if held is None or held.kind != kind:
            return None
        return held.value

    def _expire(self, now: datetime) -> None:
        """Drop everything that has lapsed."""
        for held_id in [
            key for key, held in self._held.items() if held.expires_at <= now
        ]:
            del self._held[held_id]


def approval_holder(hass: HomeAssistant, entry_id: str) -> ApprovalHolder:
    """Return one config entry's holder, creating it the first time."""
    holders: dict[str, ApprovalHolder] = hass.data.setdefault(DOMAIN, {}).setdefault(
        _HOLDERS, {}
    )
    holder = holders.get(entry_id)
    if holder is None:
        holder = ApprovalHolder()
        holders[entry_id] = holder
    return holder
