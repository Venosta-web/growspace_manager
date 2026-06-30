"""Unit tests for the actuator-driver abstraction (ADR-0022)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.actuator_driver import (
    ACInfinityDriver,
    FanDriver,
    GenericOnOffDriver,
    SwitchDriver,
    resolve_actuator_driver,
    resolve_actuator_drivers,
    resolve_on_off_drivers,
)
from custom_components.growspace_manager.models import ACInfinityDevice
from homeassistant.const import (
    ATTR_ENTITY_ID,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_hass() -> MagicMock:
    """Return a mock HomeAssistant with an async service caller."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    return hass


def _state(value: str) -> MagicMock:
    """Build a mock entity state carrying ``value``."""
    state = MagicMock()
    state.state = value
    return state


async def test_fan_driver_set_speed_calls_set_percentage(mock_hass: MagicMock) -> None:
    """FanDriver.set_speed issues fan.set_percentage with the demand."""
    await FanDriver(mock_hass, "fan.exhaust").set_speed(90)
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan",
        "set_percentage",
        {ATTR_ENTITY_ID: "fan.exhaust", "percentage": 90},
        blocking=False,
    )


@pytest.mark.parametrize(
    ("method", "service"),
    [("turn_on", "turn_on"), ("turn_off", "turn_off")],
)
async def test_fan_driver_binary_calls(
    mock_hass: MagicMock, method: str, service: str
) -> None:
    """FanDriver.turn_on/turn_off issue the matching fan service."""
    await getattr(FanDriver(mock_hass, "fan.exhaust"), method)()
    mock_hass.services.async_call.assert_awaited_once_with(
        "fan", service, {ATTR_ENTITY_ID: "fan.exhaust"}, blocking=False
    )


@pytest.mark.parametrize("driver_cls", [FanDriver, SwitchDriver])
@pytest.mark.parametrize(
    ("value", "expected"),
    [(STATE_ON, True), (STATE_OFF, False)],
)
async def test_driver_is_on_reflects_state(
    mock_hass: MagicMock, driver_cls: type, value: str, expected: bool
) -> None:
    """is_on reflects the entity state for every driver kind."""
    mock_hass.states.get.return_value = _state(value)
    assert driver_cls(mock_hass, "domain.entity").is_on() is expected


@pytest.mark.parametrize("driver_cls", [FanDriver, SwitchDriver])
async def test_driver_is_on_missing_state(
    mock_hass: MagicMock, driver_cls: type
) -> None:
    """is_on is False when the entity has no state."""
    mock_hass.states.get.return_value = None
    assert driver_cls(mock_hass, "domain.entity").is_on() is False


@pytest.mark.parametrize(
    ("pct", "service"),
    [(11, "turn_on"), (10, "turn_off"), (0, "turn_off")],
)
async def test_switch_driver_set_speed_threshold(
    mock_hass: MagicMock, pct: int, service: str
) -> None:
    """SwitchDriver engages only when demand exceeds the off threshold."""
    await SwitchDriver(mock_hass, "switch.exhaust", off_threshold=10).set_speed(pct)
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch", service, {ATTR_ENTITY_ID: "switch.exhaust"}, blocking=False
    )


async def test_switch_driver_uses_entity_domain(mock_hass: MagicMock) -> None:
    """SwitchDriver dispatches to the entity's own domain (e.g. input_boolean)."""
    await SwitchDriver(mock_hass, "input_boolean.damper").turn_on()
    mock_hass.services.async_call.assert_awaited_once_with(
        "input_boolean",
        "turn_on",
        {ATTR_ENTITY_ID: "input_boolean.damper"},
        blocking=False,
    )


async def test_switch_driver_default_threshold_is_zero(mock_hass: MagicMock) -> None:
    """With the default threshold any positive demand turns the device on."""
    await SwitchDriver(mock_hass, "switch.damper").set_speed(1)
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_on", {ATTR_ENTITY_ID: "switch.damper"}, blocking=False
    )


@pytest.mark.parametrize(
    ("entity_id", "expected_type"),
    [
        ("fan.exhaust", FanDriver),
        ("switch.exhaust", SwitchDriver),
        ("input_boolean.damper", SwitchDriver),
    ],
)
async def test_resolve_actuator_driver_supported(
    mock_hass: MagicMock, entity_id: str, expected_type: type
) -> None:
    """The resolver returns the right driver for supported domains."""
    assert isinstance(resolve_actuator_driver(mock_hass, entity_id), expected_type)


async def test_resolve_actuator_driver_unsupported(mock_hass: MagicMock) -> None:
    """The resolver returns None for unsupported domains."""
    assert resolve_actuator_driver(mock_hass, "light.grow") is None


async def test_resolve_passes_switch_off_threshold(mock_hass: MagicMock) -> None:
    """The resolver threshold reaches the switch driver's engage point."""
    driver = resolve_actuator_driver(
        mock_hass, "switch.exhaust", switch_off_threshold=20
    )
    await driver.set_speed(20)
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch", "turn_off", {ATTR_ENTITY_ID: "switch.exhaust"}, blocking=False
    )


@pytest.mark.parametrize("error", [HomeAssistantError("boom"), TimeoutError()])
async def test_safe_service_call_swallows_device_errors(
    mock_hass: MagicMock, error: Exception
) -> None:
    """A failing device call is logged, not raised, so one device can't break the tick."""
    mock_hass.services.async_call.side_effect = error
    await FanDriver(mock_hass, "fan.exhaust").set_speed(50)
    mock_hass.services.async_call.assert_awaited_once()


# ---------------------------------------------------------------------------
# ACInfinityDriver
# ---------------------------------------------------------------------------


def _ac_driver(mock_hass: MagicMock, on_speed: int = 10) -> ACInfinityDriver:
    """Build an ACInfinityDriver over a standard mode+speed bundle."""
    return ACInfinityDriver(
        mock_hass,
        mode_entity="select.port_mode",
        speed_entity="number.port_speed",
        on_speed=on_speed,
    )


async def test_ac_infinity_set_speed_drives_mode_and_intensity(
    mock_hass: MagicMock,
) -> None:
    """A positive demand sets mode On and writes the scaled 1-10 intensity."""
    await _ac_driver(mock_hass).set_speed(60)
    mock_hass.services.async_call.assert_any_await(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.port_mode", "option": "On"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.port_speed", "value": 6},
        blocking=False,
    )
    assert mock_hass.services.async_call.await_count == 2


@pytest.mark.parametrize(
    ("pct", "intensity"),
    [(5, 1), (60, 6), (95, 10), (100, 10)],
)
async def test_ac_infinity_intensity_scaling(
    mock_hass: MagicMock, pct: int, intensity: int
) -> None:
    """0-100 demand maps onto the clamped 1-10 intensity scale."""
    await _ac_driver(mock_hass).set_speed(pct)
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.port_speed", "value": intensity},
        blocking=False,
    )


async def test_ac_infinity_set_speed_zero_turns_off(mock_hass: MagicMock) -> None:
    """Zero demand sets mode Off and never touches the intensity number."""
    await _ac_driver(mock_hass).set_speed(0)
    mock_hass.services.async_call.assert_awaited_once_with(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.port_mode", "option": "Off"},
        blocking=False,
    )


async def test_ac_infinity_turn_on_uses_on_speed(mock_hass: MagicMock) -> None:
    """turn_on sets mode On and writes the configured on-speed."""
    await _ac_driver(mock_hass, on_speed=7).turn_on()
    mock_hass.services.async_call.assert_any_await(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.port_mode", "option": "On"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.port_speed", "value": 7},
        blocking=False,
    )


async def test_ac_infinity_turn_off_sets_mode_off(mock_hass: MagicMock) -> None:
    """turn_off sets the mode select to Off."""
    await _ac_driver(mock_hass).turn_off()
    mock_hass.services.async_call.assert_awaited_once_with(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.port_mode", "option": "Off"},
        blocking=False,
    )


@pytest.mark.parametrize(
    ("mode", "expected"),
    [
        ("On", True),
        ("Auto", True),
        ("VPD", True),
        ("Off", False),
        (STATE_UNAVAILABLE, False),
        (STATE_UNKNOWN, False),
    ],
)
async def test_ac_infinity_is_on_reads_mode_select(
    mock_hass: MagicMock, mode: str, expected: bool
) -> None:
    """is_on is True whenever the mode select is anything other than Off."""
    mock_hass.states.get.return_value = _state(mode)
    assert _ac_driver(mock_hass).is_on() is expected


async def test_ac_infinity_is_on_missing_state(mock_hass: MagicMock) -> None:
    """is_on is False when the mode select has no state."""
    mock_hass.states.get.return_value = None
    assert _ac_driver(mock_hass).is_on() is False


# ---------------------------------------------------------------------------
# resolve_actuator_drivers (plain + AC Infinity merge)
# ---------------------------------------------------------------------------


async def test_resolve_actuator_drivers_merges_and_skips_unsupported(
    mock_hass: MagicMock,
) -> None:
    """The aggregator yields a driver per plain entity and AC Infinity bundle."""
    drivers = resolve_actuator_drivers(
        mock_hass,
        ["fan.exhaust", "switch.damper", "light.unsupported"],
        [ACInfinityDevice(mode_entity="select.m", speed_entity="number.s")],
    )
    assert [type(d) for d in drivers] == [FanDriver, SwitchDriver, ACInfinityDriver]


async def test_resolve_actuator_drivers_empty(mock_hass: MagicMock) -> None:
    """No configured actuators yields no drivers."""
    assert resolve_actuator_drivers(mock_hass, [], []) == []


# ---------------------------------------------------------------------------
# GenericOnOffDriver (binary on/off controllers)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("entity_id", "domain"),
    [
        ("switch.humidifier", "switch"),
        ("humidifier.unit", "humidifier"),
        ("fan.inline", "fan"),
        ("input_boolean.mister", "input_boolean"),
        ("climate.tent", "homeassistant"),
        ("remote.plug", "homeassistant"),
    ],
)
async def test_generic_on_off_driver_domain_routing(
    mock_hass: MagicMock, entity_id: str, domain: str
) -> None:
    """Native domains drive themselves; everything else falls back to homeassistant."""
    await GenericOnOffDriver(mock_hass, entity_id).turn_on()
    mock_hass.services.async_call.assert_awaited_once_with(
        domain, "turn_on", {ATTR_ENTITY_ID: entity_id}, blocking=False
    )


async def test_generic_on_off_driver_turn_off(mock_hass: MagicMock) -> None:
    """turn_off issues the off service on the resolved domain."""
    await GenericOnOffDriver(mock_hass, "climate.tent").turn_off()
    mock_hass.services.async_call.assert_awaited_once_with(
        "homeassistant", "turn_off", {ATTR_ENTITY_ID: "climate.tent"}, blocking=False
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [(STATE_ON, True), (STATE_OFF, False)],
)
async def test_generic_on_off_driver_is_on(
    mock_hass: MagicMock, value: str, expected: bool
) -> None:
    """is_on reflects the entity state."""
    mock_hass.states.get.return_value = _state(value)
    assert GenericOnOffDriver(mock_hass, "switch.x").is_on() is expected


async def test_resolve_on_off_drivers_merges_entities_and_bundles(
    mock_hass: MagicMock,
) -> None:
    """Every plain entity becomes a GenericOnOffDriver; bundles become AC Infinity."""
    drivers = resolve_on_off_drivers(
        mock_hass,
        ["switch.humidifier", "climate.tent"],
        [ACInfinityDevice(mode_entity="select.m", speed_entity="number.s")],
    )
    assert [type(d) for d in drivers] == [
        GenericOnOffDriver,
        GenericOnOffDriver,
        ACInfinityDriver,
    ]


async def test_resolve_on_off_drivers_empty(mock_hass: MagicMock) -> None:
    """No configured actuators yields no drivers."""
    assert resolve_on_off_drivers(mock_hass, []) == []


@pytest.mark.parametrize(
    ("pct", "service"),
    [(1, "turn_on"), (0, "turn_off")],
)
async def test_generic_on_off_driver_set_speed(
    mock_hass: MagicMock, pct: int, service: str
) -> None:
    """GenericOnOffDriver.set_speed collapses demand to on (>0) or off."""
    await GenericOnOffDriver(mock_hass, "switch.x").set_speed(pct)
    mock_hass.services.async_call.assert_awaited_once_with(
        "switch", service, {ATTR_ENTITY_ID: "switch.x"}, blocking=False
    )
