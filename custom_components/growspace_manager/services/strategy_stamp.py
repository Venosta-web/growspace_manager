"""Legacy effect writer retained only for automatic Program Progression.

Explicit Recipe Stamps and Steering Mode stamps use Irrigation Change.
Program Progression shares its read-only candidate validation, but temporarily
retains this writer's in-place mutation and pre-commit narration (ADR-0046).
It does not provide Irrigation Change's in-memory commit restoration.
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
    strategy fields a grower may tweak afterwards — and ``config_values`` the
    same for the setpoints that live on the growspace's ``IrrigationConfig``
    (a schedule recipe's times, durations and caps). ``records`` are the fields
    naming *which* source was stamped (the declared steering mode, the applied
    recipe and when it was applied); they are written to the same strategy but
    kept separate because they are provenance, never a setpoint the control
    loop reads. ``logbook_message`` is written only when the growspace has
    logbook entries enabled.
    """

    values: Mapping[str, Any]
    config_values: Mapping[str, Any] = field(default_factory=dict)
    records: Mapping[str, Any] = field(default_factory=dict)
    logbook_message: str | None = None

    def __post_init__(self) -> None:
        """Take immutable snapshots of the resolved mappings."""
        object.__setattr__(self, "values", MappingProxyType(dict(self.values)))
        object.__setattr__(
            self, "config_values", MappingProxyType(dict(self.config_values))
        )
        object.__setattr__(self, "records", MappingProxyType(dict(self.records)))


async def async_apply_strategy_stamp(
    coordinator: GrowspaceCoordinator,
    growspace_id: str,
    stamp: StrategyStamp,
) -> None:
    """Write one resolved stamp into a growspace's irrigation settings."""
    growspace = coordinator.growspaces.get(growspace_id)
    if not growspace:
        raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")

    strategy = growspace.irrigation_strategy
    for field_name, value in (*stamp.values.items(), *stamp.records.items()):
        setattr(strategy, field_name, value)
    for field_name, value in stamp.config_values.items():
        setattr(growspace.irrigation_config, field_name, value)

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
