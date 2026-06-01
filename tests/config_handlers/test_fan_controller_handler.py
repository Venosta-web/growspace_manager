"""Tests for FanControllerHandler — sub-steps and save-and-continue."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.fan_controller_handler import (
    FanControllerHandler,
)
from custom_components.growspace_manager.const import FanRegulationMode
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace


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
    from custom_components.growspace_manager.models import CirculationFanConfig

    flow = _make_flow()
    handler = FanControllerHandler(flow)
    schema = handler.get_fan_controller_schema(CirculationFanConfig())

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert "enabled" in keys


def test_fan_controller_schema_contains_regulation_mode_field() -> None:
    """Base fan controller schema has a 'regulation_mode' select field."""
    from custom_components.growspace_manager.models import CirculationFanConfig

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
    from custom_components.growspace_manager.models import CirculationFanConfig

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
