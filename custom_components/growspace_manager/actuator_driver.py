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

from collections.abc import Iterable
import logging
from typing import Protocol

from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError

_LOGGER = logging.getLogger(__name__)

# On/off domains driven via turn_on/turn_off rather than by percentage.
_SWITCH_DOMAINS = ("switch", "input_boolean")

# Domains a binary on/off controller drives via their own turn_on/turn_off
# service; any other domain falls back to the generic ``homeassistant`` service.
_ON_OFF_NATIVE_DOMAINS = ("switch", "humidifier", "fan", "input_boolean")

# AC Infinity Active Mode options (hardcoded English in the ac_infinity integration).
_AC_INFINITY_MODE_ON = "On"
_AC_INFINITY_MODE_OFF = "Off"
# AC Infinity ports take an integer intensity in this range, not a 0–100 percentage.
_AC_INFINITY_SPEED_MIN = 1
_AC_INFINITY_SPEED_MAX = 10


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


def _scale_percentage_to_intensity(pct: int) -> int:
    """Map a 0–100 percentage to the AC Infinity 1–10 intensity scale."""
    return max(_AC_INFINITY_SPEED_MIN, min(_AC_INFINITY_SPEED_MAX, round(pct / 10)))


class ACInfinityDriver:
    """Drives an AC Infinity port (mode ``select`` + speed ``number`` bundle).

    The ``ac_infinity`` integration exposes no ``fan`` entity, so GSM seizes a
    port by setting its Active Mode ``select`` to ``On`` and writing the speed
    ``number`` (mapping the 0–100 demand onto the device's 1–10 intensity), or to
    ``Off`` to release it. ``is_on`` reads the mode ``select`` — under cloud
    polling both the select and any power sensor lag equally, but the select's
    ``Off`` state is deterministic where a port's current-power is not (ADR-0022).
    """

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        mode_entity: str,
        speed_entity: str,
        on_speed: int = _AC_INFINITY_SPEED_MAX,
    ) -> None:
        """Initialize the driver for one AC Infinity port bundle."""
        self._hass = hass
        self._mode_entity = mode_entity
        self._speed_entity = speed_entity
        self._on_speed = on_speed

    async def set_speed(self, pct: int) -> None:
        """Turn the port off at zero demand, otherwise drive mode On + intensity."""
        if pct <= 0:
            await self._select_mode(_AC_INFINITY_MODE_OFF)
        else:
            await self._select_mode(_AC_INFINITY_MODE_ON)
            await self._set_intensity(_scale_percentage_to_intensity(pct))

    async def turn_on(self) -> None:
        """Set the port to On at the configured on-speed."""
        await self._select_mode(_AC_INFINITY_MODE_ON)
        await self._set_intensity(self._on_speed)

    async def turn_off(self) -> None:
        """Set the port's mode to Off."""
        await self._select_mode(_AC_INFINITY_MODE_OFF)

    def is_on(self) -> bool:
        """Return whether the port's mode is anything other than Off."""
        state = self._hass.states.get(self._mode_entity)
        return state is not None and state.state not in (
            _AC_INFINITY_MODE_OFF,
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        )

    async def _select_mode(self, option: str) -> None:
        await _safe_service_call(
            self._hass,
            "select",
            "select_option",
            {ATTR_ENTITY_ID: self._mode_entity, "option": option},
        )

    async def _set_intensity(self, value: int) -> None:
        await _safe_service_call(
            self._hass,
            "number",
            "set_value",
            {ATTR_ENTITY_ID: self._speed_entity, "value": value},
        )


class ACInfinityDeviceConfig(Protocol):
    """Structural type for a stored AC Infinity bundle (``models.ACInfinityDevice``)."""

    mode_entity: str
    speed_entity: str
    on_speed: int


def resolve_actuator_drivers(
    hass: HomeAssistant,
    entities: Iterable[str],
    ac_infinity_devices: Iterable[ACInfinityDeviceConfig] = (),
    *,
    switch_off_threshold: int = 0,
) -> list[ActuatorDriver]:
    """Resolve every configured actuator for one role into drivers.

    Merges the plain ``*_entities`` list (resolved by domain) with the parallel
    AC Infinity bundle list; unsupported plain domains are skipped.
    """
    drivers: list[ActuatorDriver] = []
    for entity_id in entities:
        driver = resolve_actuator_driver(
            hass, entity_id, switch_off_threshold=switch_off_threshold
        )
        if driver is not None:
            drivers.append(driver)
    drivers.extend(
        ACInfinityDriver(
            hass,
            mode_entity=device.mode_entity,
            speed_entity=device.speed_entity,
            on_speed=device.on_speed,
        )
        for device in ac_infinity_devices
    )
    return drivers


class GenericOnOffDriver:
    """Binary on/off driver for the VPD controllers (humidifier/dehumidifier).

    Drives ``switch``/``humidifier``/``fan``/``input_boolean`` via their own
    ``turn_on``/``turn_off`` service and any other domain via the generic
    ``homeassistant`` service — mirroring the controller's historical dispatch so
    a humidifier entity or a climate/remote device is still driven. ``set_speed``
    collapses to on (above ``off_threshold``) or off.
    """

    def __init__(
        self, hass: HomeAssistant, entity_id: str, *, off_threshold: int = 0
    ) -> None:
        """Initialize the driver, resolving the service domain for ``entity_id``."""
        self._hass = hass
        self._entity_id = entity_id
        domain = entity_id.split(".", 1)[0]
        self._domain = domain if domain in _ON_OFF_NATIVE_DOMAINS else "homeassistant"
        self._off_threshold = off_threshold

    async def set_speed(self, pct: int) -> None:
        """Turn on when ``pct`` exceeds the off threshold, otherwise off."""
        if pct > self._off_threshold:
            await self.turn_on()
        else:
            await self.turn_off()

    async def turn_on(self) -> None:
        """Turn the device on via its resolved service domain."""
        await _safe_service_call(
            self._hass,
            self._domain,
            SERVICE_TURN_ON,
            {ATTR_ENTITY_ID: self._entity_id},
        )

    async def turn_off(self) -> None:
        """Turn the device off via its resolved service domain."""
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


def resolve_on_off_drivers(
    hass: HomeAssistant,
    entities: Iterable[str],
    ac_infinity_devices: Iterable[ACInfinityDeviceConfig] = (),
) -> list[ActuatorDriver]:
    """Resolve binary on/off actuators (plain entities + AC Infinity bundles).

    Used by the VPD on/off controllers. Every plain entity becomes a
    ``GenericOnOffDriver`` (preserving the controller's own-domain/homeassistant
    dispatch); each AC Infinity bundle becomes an ``ACInfinityDriver``.
    """
    drivers: list[ActuatorDriver] = [
        GenericOnOffDriver(hass, entity_id) for entity_id in entities
    ]
    drivers.extend(
        ACInfinityDriver(
            hass,
            mode_entity=device.mode_entity,
            speed_entity=device.speed_entity,
            on_speed=device.on_speed,
        )
        for device in ac_infinity_devices
    )
    return drivers
