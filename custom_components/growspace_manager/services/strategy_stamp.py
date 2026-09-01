"""Strategy Stamp — the one write-and-record seam for preset stamps.

A stamp writes a flat mapping of resolved strategy fields into the ordinary
editable fields once, records what was stamped, and lets the coordinator read
nothing but those explicit fields afterwards (ADR-0012). Resolving the mapping
is the caller's business — a [[Steering Mode]] resolves it from the preset
table, other sources resolve it their own way — but everything downstream of
the mapping is identical, so it lives here rather than being copied per source:
write the values, record the provenance, write one logbook entry, invalidate
the cache, commit and refresh.

Stamps deliberately **always write**. Re-stamping the same source is a "reset
to these values", discarding hand tweaks, so this seam never diffs and never
skips.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
import homeassistant.util.dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator


@dataclass(frozen=True, slots=True)
class StrategyStamp:
    """One resolved stamp: the fields to write, the provenance, the log line.

    ``values`` are the setpoints the source resolved — the ordinary editable
    strategy fields a grower may tweak afterwards. ``records`` are the fields
    naming *which* source was stamped (the declared steering mode, and in time
    the applied recipe); they are written to the same strategy but kept
    separate because they are provenance, never a setpoint the control loop
    reads. ``logbook_message`` is written only when the growspace has logbook
    entries enabled.
    """

    values: Mapping[str, Any]
    records: Mapping[str, Any] = field(default_factory=dict)
    logbook_message: str | None = None

    def __post_init__(self) -> None:
        """Take immutable snapshots of the resolved mappings."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(self, "records", MappingProxyType(dict(self.records)))


async def async_apply_strategy_stamp(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    stamp: StrategyStamp,
) -> None:
    """Write one resolved stamp into a growspace's irrigation strategy."""
    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

    strategy = growspace.irrigation_strategy
    for field_name, value in (*stamp.values.items(), *stamp.records.items()):
        setattr(strategy, field_name, value)

    if stamp.logbook_message and growspace.irrigation_config.log_to_logbook:
        coordinator.hass.bus.async_fire(
            EVENT_GROWSPACE_LOG_ENTRY,
            {
                ATTR_GROWSPACE_ID: growspace_id,
                "message": stamp.logbook_message,
                "category": "irrigation",
                "timestamp": dt_util.now().isoformat(),
            },
        )

    coordinator.cache.invalidate(growspace_id)
    await coordinator.async_commit()
    await coordinator.async_request_refresh()
