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

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

if TYPE_CHECKING:
    from .models import ACInfinityGrowLight

_LOGGER = logging.getLogger(__name__)

# The AC Infinity Active Mode option that runs the onboard schedule autonomously.
_SCHEDULE_MODE = "Schedule"
# The on_power number takes an integer intensity in this range, not a percentage.
# This 1-10 scale mirrors the shipped ACInfinityDriver speed number (ADR-0022).
#
# Device-contract assumptions unverified on real hardware — confirm before
# trusting in production (see #517/#428). A mismatch degrades gracefully: the
# write format is independent of the read-back format, so the schedule is still
# correct; only the idempotency check silently fails, causing a redundant daily
# re-push, not a corrupt schedule.
#   - on_power number's min/max/step (the 1-10 scale above);
#   - sunrise onTimeSwitch is a switch.* reading back "on"/"off";
#   - sunrise onTime ramp is a number.* written in raw minutes (unscaled).
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


def ac_infinity_schedule_matches(
    hass: HomeAssistant,
    device: ACInfinityGrowLight,
    *,
    on_time: str,
    off_time: str,
    power: int,
    sunrise_enabled: bool = False,
    sunrise_minutes: int = 0,
) -> bool:
    """Return whether the port already holds the desired schedule.

    Lets the caller skip an unnecessary re-push. A missing or unparseable
    reading counts as a mismatch (push and converge) — ``ac_infinity`` is
    cloud-polled, so a just-written value that has not read back yet may cause a
    harmless extra push rather than a silently stale schedule.
    """
    expected = {
        device.mode_entity: _SCHEDULE_MODE,
        device.on_time_entity: on_time,
        device.off_time_entity: off_time,
    }
    for entity_id, want in expected.items():
        state = hass.states.get(entity_id)
        if state is None or state.state != want:
            return False

    power_state = hass.states.get(device.power_entity)
    if power_state is None:
        return False
    try:
        current = round(float(power_state.state))
    except TypeError, ValueError:
        return False
    if current != _scale_power_to_intensity(power):
        return False

    return _sunrise_matches(hass, device, sunrise_enabled, sunrise_minutes)


def _sunrise_matches(
    hass: HomeAssistant,
    device: ACInfinityGrowLight,
    sunrise_enabled: bool,
    sunrise_minutes: int,
) -> bool:
    """Return whether the port's sunrise setting matches the desired one."""
    if not device.sunrise_switch_entity:
        return True

    switch_state = hass.states.get(device.sunrise_switch_entity)
    if switch_state is None:
        return False
    if (switch_state.state == STATE_ON) != sunrise_enabled:
        return False

    if not sunrise_enabled or not device.sunrise_duration_entity:
        return True

    duration_state = hass.states.get(device.sunrise_duration_entity)
    if duration_state is None:
        return False
    try:
        return round(float(duration_state.state)) == sunrise_minutes
    except TypeError, ValueError:
        return False


async def push_ac_infinity_schedule(
    hass: HomeAssistant,
    device: ACInfinityGrowLight,
    *,
    on_time: str,
    off_time: str,
    power: int,
    sunrise_enabled: bool = False,
    sunrise_minutes: int = 0,
) -> None:
    """Write the onboard schedule (and native sunrise ramp) to one port."""
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
    await _push_sunrise(hass, device, sunrise_enabled, sunrise_minutes)


async def _push_sunrise(
    hass: HomeAssistant,
    device: ACInfinityGrowLight,
    sunrise_enabled: bool,
    sunrise_minutes: int,
) -> None:
    """Configure the native sunrise ramp, if the port exposes it."""
    if not device.sunrise_switch_entity:
        return
    if not sunrise_enabled:
        await _safe_call(
            hass,
            "switch",
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: device.sunrise_switch_entity},
        )
        return
    await _safe_call(
        hass,
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: device.sunrise_switch_entity},
    )
    if device.sunrise_duration_entity:
        await _safe_call(
            hass,
            "number",
            "set_value",
            {ATTR_ENTITY_ID: device.sunrise_duration_entity, "value": sunrise_minutes},
        )
