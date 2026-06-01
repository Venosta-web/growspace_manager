"""Tests for EnvironmentSensorsHandler — schema fields and routing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.environment_sensors_handler import (
    EnvironmentSensorsHandler,
)
from custom_components.growspace_manager.const import (
    CONF_HUMIDITY_SENSOR,
    CONF_TEMP_SENSOR,
)
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace


def _make_flow(configure_dehumidifier: bool = False,
               configure_fan_controller: bool = False,
               configure_advanced: bool = False) -> MagicMock:
    """Build a minimal flow stub with a growspace and async step mocks."""
    growspace = Growspace(
        id="gs1",
        name="Test Tent",
        environment_config=EnvironmentConfig(),
    )
    coordinator = MagicMock()
    coordinator.services.growspaces.get_growspace.return_value = growspace
    coordinator.services.growspaces.get_sorted_growspace_options.return_value = [
        ("gs1", "Test Tent")
    ]

    config_entry = MagicMock()
    config_entry.runtime_data = coordinator

    flow = MagicMock()
    flow.hass = MagicMock()
    flow.config_entry = config_entry
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {}

    # Downstream async step mocks
    flow.async_step_configure_dehumidifier = AsyncMock(
        return_value={"type": "form", "step_id": "configure_dehumidifier"}
    )
    flow.async_step_configure_fan_controller = AsyncMock(
        return_value={"type": "form", "step_id": "configure_fan_controller"}
    )
    flow.async_step_configure_advanced_bayesian = AsyncMock(
        return_value={"type": "form", "step_id": "configure_advanced_bayesian"}
    )
    flow.async_step_configure_sensor_placement = AsyncMock(
        return_value={"type": "form", "step_id": "configure_sensor_placement"}
    )
    flow.async_show_form = MagicMock(side_effect=lambda **kw: {"type": "form", "step_id": kw.get("step_id")})
    flow.async_abort = MagicMock(side_effect=lambda reason: {"type": "abort", "reason": reason})

    return flow


# ---------------------------------------------------------------------------
# Schema field presence
# ---------------------------------------------------------------------------


def test_environment_schema_contains_temperature_sensors_field() -> None:
    """Schema contains temperature_sensors multi-entity selector."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    schema = handler.get_environment_schema_step1({})

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert f"{CONF_TEMP_SENSOR}s" in keys


def test_environment_schema_contains_humidity_sensors_field() -> None:
    """Schema contains humidity_sensors multi-entity selector."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    schema = handler.get_environment_schema_step1({})

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert f"{CONF_HUMIDITY_SENSOR}s" in keys


def test_environment_schema_contains_configure_dehumidifier_toggle() -> None:
    """Schema contains a configure_dehumidifier boolean toggle."""
    from custom_components.growspace_manager.const import CONF_CONFIGURE_DEHUMIDIFIER

    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    schema = handler.get_environment_schema_step1({})

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert CONF_CONFIGURE_DEHUMIDIFIER in keys


def test_environment_schema_contains_configure_fan_controller_toggle() -> None:
    """Schema contains a configure_fan_controller boolean toggle."""
    from custom_components.growspace_manager.const import CONF_CONFIGURE_FAN_CONTROLLER

    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    schema = handler.get_environment_schema_step1({})

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert CONF_CONFIGURE_FAN_CONTROLLER in keys


# ---------------------------------------------------------------------------
# _determine_next_step routing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_determine_next_step_routes_to_dehumidifier_when_checked() -> None:
    """configure_dehumidifier=True routes to flow.async_step_configure_dehumidifier."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = await handler._determine_next_step({"configure_dehumidifier": True})

    flow.async_step_configure_dehumidifier.assert_awaited_once()
    assert result["step_id"] == "configure_dehumidifier"


@pytest.mark.asyncio
async def test_determine_next_step_routes_to_fan_when_checked() -> None:
    """configure_fan_controller=True routes to flow.async_step_configure_fan_controller."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = await handler._determine_next_step({"configure_fan_controller": True})

    flow.async_step_configure_fan_controller.assert_awaited_once()
    assert result["step_id"] == "configure_fan_controller"


@pytest.mark.asyncio
async def test_determine_next_step_routes_to_advanced_bayesian_when_checked() -> None:
    """configure_advanced=True routes to flow.async_step_configure_advanced_bayesian."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = await handler._determine_next_step({"configure_advanced": True})

    flow.async_step_configure_advanced_bayesian.assert_awaited_once()
    assert result["step_id"] == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_determine_next_step_routes_to_sensor_placement_by_default() -> None:
    """No checkboxes checked → routes to sensor placement step."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = await handler._determine_next_step({})

    flow.async_step_configure_sensor_placement.assert_awaited_once()
    assert result["step_id"] == "configure_sensor_placement"
