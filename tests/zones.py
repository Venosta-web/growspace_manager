"""Put pre-zones settings onto a growspace's implicit Irrigation Zone in tests.

Tests were written when the strategy and the substrate probes sat on the
growspace. These say the same thing in one line each, through the same split
production uses (``domain/irrigation_zone.py``), so a fixture cannot put a
field on the wrong side.
"""

from __future__ import annotations

from typing import Any

from custom_components.growspace_manager.domain.irrigation_zone import (
    apply_effective_irrigation,
    effective_config,
)
from custom_components.growspace_manager.models import Growspace, IrrigationStrategy


def set_strategy(growspace: Growspace, strategy: IrrigationStrategy) -> None:
    """Give the growspace this strategy: steering to the zone, lights to it."""
    apply_effective_irrigation(growspace, effective_config(growspace), strategy)


def set_probes(growspace: Growspace, **probes: Any) -> Growspace:
    """Set the implicit zone's substrate probes; returns the growspace."""
    for name, value in probes.items():
        setattr(growspace.default_zone, name, value)
    return growspace


def zoned(
    growspace: Growspace,
    *,
    strategy: IrrigationStrategy | None = None,
    substrate_history: Any = None,
    **probes: Any,
) -> Growspace:
    """Return the growspace with a strategy, history or probes on its zone."""
    if strategy is not None:
        set_strategy(growspace, strategy)
    if substrate_history is not None:
        growspace.default_zone.substrate_history = substrate_history
    return set_probes(growspace, **probes)
