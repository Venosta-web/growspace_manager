"""Unit tests for the actuator-driver abstraction (ADR-0022)."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.actuator_driver import (
    FanDriver,
    SwitchDriver,
    resolve_actuator_driver,
)
from homeassistant.const import ATTR_ENTITY_ID, STATE_OFF, STATE_ON
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
