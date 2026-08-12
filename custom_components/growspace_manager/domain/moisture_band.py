"""Acceptable Moisture Band — the one place the effective band is derived.

A growspace either inherits the legacy default band or carries a complete
custom pair on its :class:`EnvironmentConfig`. Both the Bayesian stress
evaluator and the outbound growspace payload resolve the band through
:func:`effective_moisture_band`, so the classification the card previews and
the classification Plant Stress applies can never drift apart.

Boundaries are inclusive: a reading exactly on the minimum or the maximum sits
*inside* the band and contributes no moisture-stress evidence.

Pure module: no hass, no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from custom_components.growspace_manager.bayesian_constants import (
    SOIL_MOISTURE_HIGH_THRESHOLD,
    SOIL_MOISTURE_LOW_THRESHOLD,
)

DEFAULT_MOISTURE_MIN = float(SOIL_MOISTURE_LOW_THRESHOLD)
DEFAULT_MOISTURE_MAX = float(SOIL_MOISTURE_HIGH_THRESHOLD)

MOISTURE_BAND_FLOOR = 0.0
MOISTURE_BAND_CEILING = 100.0

# Percentage is the only unit the band can be interpreted in. A sensor with no
# unit metadata keeps the legacy 0–100 assumption; anything else explicitly
# declares itself to be measuring something other than a moisture percentage.
PERCENTAGE_UNIT = "%"


@dataclass(frozen=True, slots=True)
class MoistureBand:
    """The band actually applied to a reading, and where it came from."""

    minimum: float
    maximum: float
    is_custom: bool

    def classify(self, reading: float) -> str:
        """Return ``"too_dry"``, ``"in_band"`` or ``"too_wet"``.

        Inclusive boundaries: a reading equal to either bound is in band.
        """
        if reading < self.minimum:
            return "too_dry"
        if reading > self.maximum:
            return "too_wet"
        return "in_band"

    def to_dict(self) -> dict[str, Any]:
        """Serialize for the growspace payload."""
        return {
            "min": self.minimum,
            "max": self.maximum,
            "is_custom": self.is_custom,
        }


DEFAULT_MOISTURE_BAND = MoistureBand(
    minimum=DEFAULT_MOISTURE_MIN,
    maximum=DEFAULT_MOISTURE_MAX,
    is_custom=False,
)


def effective_moisture_band(minimum: Any, maximum: Any) -> MoistureBand:
    """Resolve a stored override pair into the band to apply.

    Accepts the raw ``soil_moisture_min`` / ``soil_moisture_max`` values from
    either an :class:`EnvironmentConfig` or its ``to_dict()`` form. Anything
    that is not a complete, valid pair falls back to the default band — the
    Environment Patch builder rejects bad pairs at the write seam, so this
    tolerance only covers configs written before that seam existed.
    """
    if not is_valid_band(minimum, maximum):
        return DEFAULT_MOISTURE_BAND
    return MoistureBand(minimum=float(minimum), maximum=float(maximum), is_custom=True)


def is_valid_band(minimum: Any, maximum: Any) -> bool:
    """Return True when the pair is complete and satisfies 0 ≤ min < max ≤ 100."""
    low = _as_finite_float(minimum)
    high = _as_finite_float(maximum)
    if low is None or high is None:
        return False
    return MOISTURE_BAND_FLOOR <= low < high <= MOISTURE_BAND_CEILING


def is_percentage_unit(unit: str | None) -> bool:
    """Return True when a reading in ``unit`` can be read as a moisture percent.

    ``None`` (no unit metadata) is the legacy case and stays supported.
    """
    if unit is None:
        return True
    return unit.strip() == PERCENTAGE_UNIT


def _as_finite_float(value: Any) -> float | None:
    """Coerce to a finite float, or None when the value cannot be one."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) else None
