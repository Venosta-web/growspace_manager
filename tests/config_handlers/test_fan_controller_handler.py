"""Tests for FanControllerHandler — sub-steps and save-and-continue."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers import AbortFlow
from custom_components.growspace_manager.config_handlers.fan_controller_handler import (
    FanControllerHandler,
)
from custom_components.growspace_manager.const import FanRegulationMode
from custom_components.growspace_manager.models import (
    CirculationFanConfig,
    EnvironmentConfig,
    Growspace,
)


def _make_flow() -> MagicMock:
    growspace = Growspace(
        id="gs1",
        name="Test Tent",
        environment_config=EnvironmentConfig(),
    )
    coordinator = MagicMock()
    coordinator.services.growspaces.get_growspace.return_value = growspace

    config_entry = MagicMock()
    config_entry.runtime_data = coordinator

    flow = MagicMock()
    flow.hass = MagicMock()
    flow.config_entry = config_entry
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {}
    flow.fan_config_step1 = {}
    flow.async_show_form = MagicMock(
        side_effect=lambda **kw: {"type": "form", "step_id": kw.get("step_id")}
    )
    flow.async_abort = MagicMock(
        side_effect=lambda reason: {"type": "abort", "reason": reason}
    )
    flow.async_step_configure_sensor_placement = AsyncMock(
        return_value={"type": "form", "step_id": "configure_sensor_placement"}
    )
    return flow


# ---------------------------------------------------------------------------
# Schema field presence
# ---------------------------------------------------------------------------


def test_fan_controller_schema_contains_enabled_field() -> None:
    """Base fan controller schema has an 'enabled' boolean field."""
    flow = _make_flow()
    handler = FanControllerHandler(flow)
    schema = handler.get_fan_controller_schema(CirculationFanConfig())

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert "enabled" in keys


def test_fan_controller_schema_contains_regulation_mode_field() -> None:
    """Base fan controller schema has a 'regulation_mode' select field."""
    flow = _make_flow()
    handler = FanControllerHandler(flow)
    schema = handler.get_fan_controller_schema(CirculationFanConfig())

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert "regulation_mode" in keys


# ---------------------------------------------------------------------------
# Routing from base step
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fan_base_step_routes_to_vpd_schema() -> None:
    """Selecting VPD regulation mode advances to configure_fan_vpd step."""
    flow = _make_flow()
    flow.async_step_configure_fan_vpd = AsyncMock(
        return_value={"type": "form", "step_id": "configure_fan_vpd"}
    )
    handler = FanControllerHandler(flow)

    result = await handler.async_step_configure_fan_controller(
        user_input={
            "enabled": True,
            "regulation_mode": FanRegulationMode.VPD,
            "min_speed": 10,
            "max_speed": 90,
        }
    )

    assert result["step_id"] == "configure_fan_vpd"


@pytest.mark.asyncio
async def test_fan_base_step_rejects_invalid_speed_range() -> None:
    """min_speed >= max_speed returns an error form, not an abort."""

    flow = _make_flow()
    handler = FanControllerHandler(flow)

    result = await handler.async_step_configure_fan_controller(
        user_input={
            "enabled": True,
            "regulation_mode": FanRegulationMode.VPD,
            "min_speed": 80,
            "max_speed": 80,
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_fan_controller"


# ---------------------------------------------------------------------------
# _async_save_fan_config_and_continue
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_save_fan_config_persists_to_env_config_and_advances() -> None:
    """_async_save_fan_config_and_continue merges fan config into env_config_step1."""
    flow = _make_flow()
    flow.env_config_step1 = {}
    flow.fan_config_step1 = {
        "enabled": True,
        "regulation_mode": FanRegulationMode.VPD,
        "min_speed": 10,
        "max_speed": 90,
        "vpd_target": 1.2,
        "vpd_tolerance": 0.15,
        "wind_enabled": False,
    }
    growspace = Growspace(id="gs1", name="Tent", environment_config=EnvironmentConfig())
    handler = FanControllerHandler(flow)

    result = await handler._async_save_fan_config_and_continue(growspace)

    assert "circulation_fan_config" in flow.env_config_step1
    flow.async_step_configure_sensor_placement.assert_awaited_once()
    assert result["step_id"] == "configure_sensor_placement"


# ---------------------------------------------------------------------------
# Additional coverage tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step_method_name",
    [
        "async_step_configure_fan_controller",
        "async_step_configure_fan_vpd",
        "async_step_configure_fan_humidity",
        "async_step_configure_fan_temperature",
        "async_step_configure_fan_wind",
    ],
)
@pytest.mark.asyncio
async def test_steps_abort_when_coordinator_fails(step_method_name: str) -> None:
    """Config flow steps abort when get_coordinator raises AbortFlow."""
    flow = _make_flow()
    handler = FanControllerHandler(flow)
    handler.get_coordinator = MagicMock(side_effect=AbortFlow("setup_error"))

    method = getattr(handler, step_method_name)
    result = await method()

    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.parametrize(
    "step_method_name",
    [
        "async_step_configure_fan_controller",
        "async_step_configure_fan_vpd",
        "async_step_configure_fan_humidity",
        "async_step_configure_fan_temperature",
        "async_step_configure_fan_wind",
    ],
)
@pytest.mark.asyncio
async def test_steps_abort_when_growspace_missing(step_method_name: str) -> None:
    """Config flow steps abort when growspace is not found in coordinator."""
    flow = _make_flow()
    coordinator = flow.config_entry.runtime_data
    coordinator.services.growspaces.get_growspace.return_value = None

    handler = FanControllerHandler(flow)
    method = getattr(handler, step_method_name)
    result = await method()

    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.parametrize(
    ("step_method_name", "expected_step_id"),
    [
        ("async_step_configure_fan_controller", "configure_fan_controller"),
        ("async_step_configure_fan_vpd", "configure_fan_vpd"),
        ("async_step_configure_fan_humidity", "configure_fan_humidity"),
        ("async_step_configure_fan_temperature", "configure_fan_temperature"),
        ("async_step_configure_fan_wind", "configure_fan_wind"),
    ],
)
@pytest.mark.asyncio
async def test_steps_show_form_when_no_user_input(
    step_method_name: str, expected_step_id: str
) -> None:
    """Steps show form with correct step_id when user_input is None."""
    flow = _make_flow()
    handler = FanControllerHandler(flow)
    method = getattr(handler, step_method_name)

    result = await method(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == expected_step_id


@pytest.mark.parametrize(
    ("regulation_mode", "expected_step_call"),
    [
        (FanRegulationMode.VPD, "async_step_configure_fan_vpd"),
        (FanRegulationMode.HUMIDITY, "async_step_configure_fan_humidity"),
        (FanRegulationMode.TEMPERATURE, "async_step_configure_fan_temperature"),
    ],
)
@pytest.mark.asyncio
async def test_base_step_routes_based_on_regulation_mode(
    regulation_mode: FanRegulationMode, expected_step_call: str
) -> None:
    """Base step routes to correct sub-step based on selected regulation mode."""
    flow = _make_flow()

    setattr(flow, expected_step_call, AsyncMock(return_value={"type": "form", "step_id": expected_step_call}))

    handler = FanControllerHandler(flow)
    result = await handler.async_step_configure_fan_controller(
        user_input={
            "enabled": True,
            "regulation_mode": regulation_mode,
            "min_speed": 20,
            "max_speed": 80,
        }
    )

    getattr(flow, expected_step_call).assert_awaited_once()
    assert result["step_id"] == expected_step_call


@pytest.mark.parametrize(
    ("step_method_name", "step_user_input"),
    [
        ("async_step_configure_fan_vpd", {"vpd_target": 1.1, "vpd_tolerance": 0.1}),
        ("async_step_configure_fan_humidity", {"humidity_target": 55.0, "humidity_tolerance": 4.0}),
        ("async_step_configure_fan_temperature", {"temperature_target": 24.0, "temperature_tolerance": 1.5}),
    ],
)
@pytest.mark.parametrize(
    ("wind_enabled", "expected_next_step"),
    [
        (True, "async_step_configure_fan_wind"),
        (False, "async_step_configure_sensor_placement"),
    ],
)
@pytest.mark.asyncio
async def test_sub_steps_route_based_on_wind(
    step_method_name: str,
    step_user_input: dict[str, float],
    wind_enabled: bool,
    expected_next_step: str,
) -> None:
    """VPD, Humidity, and Temperature steps route to wind step or save based on wind_enabled."""
    flow = _make_flow()
    flow.fan_config_step1 = {"wind_enabled": wind_enabled}

    flow.async_step_configure_fan_wind = AsyncMock(return_value={"type": "form", "step_id": "configure_fan_wind"})
    flow.async_step_configure_sensor_placement = AsyncMock(return_value={"type": "form", "step_id": "configure_sensor_placement"})

    handler = FanControllerHandler(flow)
    method = getattr(handler, step_method_name)

    result = await method(user_input=step_user_input)

    assert result["step_id"] == expected_next_step.replace("async_step_", "")


@pytest.mark.asyncio
async def test_wind_step_saves_and_continues() -> None:
    """Wind step saves the configuration and transitions to the sensor placement step."""
    flow = _make_flow()
    flow.fan_config_step1 = {
        "enabled": True,
        "regulation_mode": FanRegulationMode.VPD,
        "min_speed": 10,
        "max_speed": 90,
    }

    handler = FanControllerHandler(flow)
    result = await handler.async_step_configure_fan_wind(
        user_input={
            "wind_period_seconds": 120,
            "wind_amplitude_pct": 15,
        }
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_sensor_placement"

    saved_fan_cfg = flow.env_config_step1["circulation_fan_config"]
    assert saved_fan_cfg["wind_period_seconds"] == 120
    assert saved_fan_cfg["wind_amplitude_pct"] == 15


@pytest.mark.asyncio
async def test_save_fan_config_uses_defaults() -> None:
    """_async_save_fan_config_and_continue uses fallback defaults when fields are missing."""
    flow = _make_flow()
    flow.fan_config_step1 = {}
    growspace = Growspace(id="gs1", name="Tent", environment_config=EnvironmentConfig())
    handler = FanControllerHandler(flow)

    await handler._async_save_fan_config_and_continue(growspace)

    saved_cfg = flow.env_config_step1["circulation_fan_config"]
    assert saved_cfg["enabled"] is False
    assert saved_cfg["regulation_mode"] == FanRegulationMode.VPD.value
    assert saved_cfg["min_speed"] == 0
    assert saved_cfg["max_speed"] == 100
    assert saved_cfg["humidity_target"] == 60.0
    assert saved_cfg["humidity_tolerance"] == 5.0
    assert saved_cfg["temperature_target"] == 25.0
    assert saved_cfg["temperature_tolerance"] == 2.0
    assert saved_cfg["vpd_target"] == 1.0
    assert saved_cfg["vpd_tolerance"] == 0.2
    assert saved_cfg["critical_temp_low"] is None
    assert saved_cfg["critical_temp_high"] is None
    assert saved_cfg["critical_temp_hysteresis"] == 1.0
    assert saved_cfg["wind_enabled"] is False
    assert saved_cfg["wind_period_seconds"] == 60
    assert saved_cfg["wind_amplitude_pct"] == 10


@pytest.mark.asyncio
async def test_fan_step_handles_missing_environment_config() -> None:
    """Step methods handle growspace environment_config being None."""
    flow = _make_flow()
    growspace = flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value
    growspace.environment_config = None

    handler = FanControllerHandler(flow)
    result = await handler.async_step_configure_fan_controller(user_input=None)

    assert result["type"] == "form"
    assert result["step_id"] == "configure_fan_controller"

