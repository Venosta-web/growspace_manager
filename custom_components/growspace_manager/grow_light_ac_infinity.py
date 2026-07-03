"""AC Infinity grow-light configurator (ADR-0023/0024).

A grow light on an AC Infinity port is *configured*, not ticked: GSM writes the
device's onboard ``Schedule`` mode plus its on/off ``time`` entities and the
``on_power`` number, and the device then runs the cycle autonomously. This is a
deliberately separate surface from ``ActuatorDriver`` (ADR-0023) — schedule mode
and the ``time`` entities are unique to grow lights.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from .models import ACInfinityGrowLight

_LOGGER = logging.getLogger(__name__)

# The AC Infinity Active Mode option that runs the onboard schedule autonomously.
_SCHEDULE_MODE = "Schedule"
# The on_power number takes an integer intensity in this range, not a percentage.
# This 1-10 scale mirrors the shipped ACInfinityDriver speed number (ADR-0022);
# the schedule-mode on_power range is unverified on real hardware — confirm the
# number entity's min/max/step before trusting it in production (see #517/#428).
_INTENSITY_MIN = 1
_INTENSITY_MAX = 10


def _scale_power_to_intensity(power: int) -> int:
    """Map a 0–100 power onto the AC Infinity 1–10 intensity scale."""
    return max(_INTENSITY_MIN, min(_INTENSITY_MAX, round(power / 10)))


async def _safe_call(
    hass: HomeAssistant, domain: str, service: str, data: dict[str, object]
) -> None:
    """Call a service, logging device failures without raising."""
    try:
        await hass.services.async_call(domain, service, data, blocking=False)
    except HomeAssistantError, TimeoutError:
        _LOGGER.warning(
            "Failed to call %s.%s on %s",
            domain,
            service,
            data.get(ATTR_ENTITY_ID),
            exc_info=True,
        )


async def push_ac_infinity_schedule(
    hass: HomeAssistant,
    device: ACInfinityGrowLight,
    *,
    on_time: str,
    off_time: str,
    power: int,
) -> None:
    """Write the onboard schedule to one AC Infinity grow-light port."""
    await _safe_call(
        hass,
        "select",
        "select_option",
        {ATTR_ENTITY_ID: device.mode_entity, "option": _SCHEDULE_MODE},
    )
    await _safe_call(
        hass,
        "time",
        "set_value",
        {ATTR_ENTITY_ID: device.on_time_entity, "time": on_time},
    )
    await _safe_call(
        hass,
        "time",
        "set_value",
        {ATTR_ENTITY_ID: device.off_time_entity, "time": off_time},
    )
    await _safe_call(
        hass,
        "number",
        "set_value",
        {
            ATTR_ENTITY_ID: device.power_entity,
            "value": _scale_power_to_intensity(power),
        },
    )
