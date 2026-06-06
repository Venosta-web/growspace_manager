"""Tests for HumidifierHandler — schema structure and threshold persistence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.config_handlers import AbortFlow
from custom_components.growspace_manager.config_handlers.humidifier_handler import (
    HumidifierHandler,
)
from custom_components.growspace_manager.const import DEHUMIDIFIER_STAGES
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
    flow.async_show_form = MagicMock(
        side_effect=lambda **kw: {"type": "form", "step_id": kw.get("step_id")}
    )
    flow.async_abort = MagicMock(
        side_effect=lambda reason: {"type": "abort", "reason": reason}
    )
    flow.async_step_configure_advanced_bayesian = AsyncMock(
        return_value={"type": "form", "step_id": "configure_advanced_bayesian"}
    )
    flow.async_step_configure_sensor_placement = AsyncMock(
        return_value={"type": "form", "step_id": "configure_sensor_placement"}
    )
    return flow


# ---------------------------------------------------------------------------
# Schema structure
# ---------------------------------------------------------------------------


def test_humidifier_schema_contains_all_stage_threshold_fields() -> None:
    """Schema contains {stage}_{cycle}_on and {stage}_{cycle}_off for every stage."""
    flow = _make_flow()
    handler = HumidifierHandler(flow)
    schema = handler.get_humidifier_schema({})

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]

    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ("day", "night"):
            assert f"{stage}_{cycle}_on" in keys, f"Missing {stage}_{cycle}_on"
            assert f"{stage}_{cycle}_off" in keys, f"Missing {stage}_{cycle}_off"


def test_humidifier_schema_field_count_matches_stages() -> None:
    """Schema has exactly 2 fields (on/off) × 2 cycles × number of stages."""
    flow = _make_flow()
    handler = HumidifierHandler(flow)
    schema = handler.get_humidifier_schema({})

    expected_count = len(DEHUMIDIFIER_STAGES) * 2 * 2
    assert len(schema.schema) == expected_count


# ---------------------------------------------------------------------------
# User input processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_humidifier_saves_thresholds_and_advances() -> None:
    """Submitting threshold values saves them into env_config_step1 and advances."""
    flow = _make_flow()
    flow.env_config_step1 = {"configure_advanced": False}
    handler = HumidifierHandler(flow)

    user_input = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ("day", "night"):
            user_input[f"{stage}_{cycle}_on"] = 1.0
            user_input[f"{stage}_{cycle}_off"] = 0.8

    await handler.async_step_configure_humidifier(user_input)

    assert flow.async_step_configure_sensor_placement.await_count == 1
    saved = flow.env_config_step1
    assert "humidifier_thresholds" in saved
    assert "veg" in saved["humidifier_thresholds"]


@pytest.mark.asyncio
async def test_configure_humidifier_shows_form_when_no_input() -> None:
    """async_step_configure_humidifier shows the form when user_input is None."""
    flow = _make_flow()
    handler = HumidifierHandler(flow)

    result = await handler.async_step_configure_humidifier(None)

    assert result["type"] == "form"
    assert result["step_id"] == "configure_humidifier"


@pytest.mark.asyncio
async def test_configure_humidifier_aborts_on_coordinator_failure() -> None:
    """AbortFlow from get_coordinator produces an abort result."""
    flow = _make_flow()
    handler = HumidifierHandler(flow)

    with patch.object(handler, "get_coordinator", side_effect=AbortFlow("setup_error")):
        result = await handler.async_step_configure_humidifier(None)

    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_configure_humidifier_aborts_when_growspace_not_found() -> None:
    """A missing growspace produces a growspace_not_found abort."""
    flow = _make_flow()
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = None
    handler = HumidifierHandler(flow)

    result = await handler.async_step_configure_humidifier(None)

    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_configure_humidifier_routes_to_advanced_bayesian_when_flag_set() -> None:
    """When configure_advanced is truthy the flow continues to advanced Bayesian step."""
    flow = _make_flow()
    flow.env_config_step1 = {"configure_advanced": True}
    handler = HumidifierHandler(flow)

    user_input = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ("day", "night"):
            user_input[f"{stage}_{cycle}_on"] = 1.0
            user_input[f"{stage}_{cycle}_off"] = 0.8

    result = await handler.async_step_configure_humidifier(user_input)

    flow.async_step_configure_advanced_bayesian.assert_awaited_once()
    assert result["step_id"] == "configure_advanced_bayesian"
    assert "humidifier_thresholds" in flow.env_config_step1
