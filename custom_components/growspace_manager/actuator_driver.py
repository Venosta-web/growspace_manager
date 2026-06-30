"""Actuator drivers — a uniform control surface over HA actuator entities.

GSM controls four kinds of actuator (exhaust fan, circulation fan, humidifier,
dehumidifier). Historically each dispatch site decided *how* to command a device
by sniffing the entity domain inline. This module hides that behind a single
``ActuatorDriver`` interface — ``set_speed`` / ``turn_on`` / ``turn_off`` /
``is_on`` — with one implementation per device kind, so the coordinators command
actuators uniformly instead of branching on the domain themselves (ADR-0022).

Speed is always expressed to a driver as a 0–100 percentage; each driver maps it
to its device's native control surface.
"""

from __future__ import annotations

import logging
from typing import Protocol

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

# On/off domains driven via turn_on/turn_off rather than by percentage.
_SWITCH_DOMAINS = ("switch", "input_boolean")


async def _safe_service_call(
    hass: HomeAssistant, domain: str, service: str, data: dict[str, object]
) -> None:
    """Call a Home Assistant service, logging device failures without raising."""
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


class ActuatorDriver(Protocol):
    """Uniform control surface over a single actuator.

    ``set_speed`` takes a 0–100 percentage; ``turn_on`` / ``turn_off`` are the
    binary path used by on/off controllers; ``is_on`` reports the current state.
    """

    async def set_speed(self, pct: int) -> None:
        """Drive the actuator to a 0–100 percentage demand."""
        ...

    async def turn_on(self) -> None:
        """Turn the actuator on."""
        ...

    async def turn_off(self) -> None:
        """Turn the actuator off."""
        ...

    def is_on(self) -> bool:
        """Return whether the actuator is currently on."""
        ...


class FanDriver:
    """Drives a ``fan.*`` entity by percentage."""

    def __init__(self, hass: HomeAssistant, entity_id: str) -> None:
        """Initialize the driver for a single ``fan.*`` entity."""
        self._hass = hass
        self._entity_id = entity_id

    async def set_speed(self, pct: int) -> None:
        """Set the fan to ``pct`` percent."""
        await _safe_service_call(
            self._hass,
            "fan",
            "set_percentage",
            {ATTR_ENTITY_ID: self._entity_id, "percentage": pct},
        )

    async def turn_on(self) -> None:
        """Turn the fan on."""
        await _safe_service_call(
            self._hass, "fan", SERVICE_TURN_ON, {ATTR_ENTITY_ID: self._entity_id}
        )

    async def turn_off(self) -> None:
        """Turn the fan off."""
        await _safe_service_call(
            self._hass, "fan", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: self._entity_id}
        )

    def is_on(self) -> bool:
        """Return whether the fan entity reports the ``on`` state."""
        state = self._hass.states.get(self._entity_id)
        return state is not None and state.state == STATE_ON


class SwitchDriver:
    """Drives an on/off entity (``switch.*`` / ``input_boolean.*``).

    ``set_speed`` turns the device on when the demand exceeds ``off_threshold``
    and off otherwise — exhaust uses the fan's ``min_speed`` as that threshold so
    a switch rests off at the floor speed and engages only above it.
    """

    def __init__(
        self, hass: HomeAssistant, entity_id: str, *, off_threshold: int = 0
    ) -> None:
        """Initialize the driver for a single on/off entity."""
        self._hass = hass
        self._entity_id = entity_id
        self._domain = entity_id.split(".", 1)[0]
        self._off_threshold = off_threshold

    async def set_speed(self, pct: int) -> None:
        """Turn on when ``pct`` exceeds the off threshold, otherwise off."""
        if pct > self._off_threshold:
            await self.turn_on()
        else:
            await self.turn_off()

    async def turn_on(self) -> None:
        """Turn the device on."""
        await _safe_service_call(
            self._hass,
            self._domain,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self._entity_id},
        )

    async def turn_off(self) -> None:
        """Turn the device off."""
        await _safe_service_call(
            self._hass,
            self._domain,
            SERVICE_TURN_OFF,
            {ATTR_ENTITY_ID: self._entity_id},
        )

    def is_on(self) -> bool:
        """Return whether the entity reports the ``on`` state."""
        state = self._hass.states.get(self._entity_id)
        return state is not None and state.state == STATE_ON


def resolve_actuator_driver(
    hass: HomeAssistant, entity_id: str, *, switch_off_threshold: int = 0
) -> ActuatorDriver | None:
    """Resolve a driver for ``entity_id`` by domain, or ``None`` if unsupported.

    ``switch_off_threshold`` is the demand above which an on/off device engages
    (exhaust passes its ``min_speed``); it is ignored for percentage fans.
    """
    domain = entity_id.split(".", 1)[0]
    if domain == "fan":
        return FanDriver(hass, entity_id)
    if domain in _SWITCH_DOMAINS:
        return SwitchDriver(hass, entity_id, off_threshold=switch_off_threshold)
    return None
