"""Tests for DehumidifierHandler — schema structure and threshold persistence."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.dehumidifier_handler import (
    DehumidifierHandler,
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


def test_dehumidifier_schema_contains_all_stage_threshold_fields() -> None:
    """Schema contains {stage}_{cycle}_on and {stage}_{cycle}_off for every stage."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema = handler.get_dehumidifier_schema({})

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]

    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ("day", "night"):
            assert f"{stage}_{cycle}_on" in keys, f"Missing {stage}_{cycle}_on"
            assert f"{stage}_{cycle}_off" in keys, f"Missing {stage}_{cycle}_off"


def test_dehumidifier_schema_field_count_matches_stages() -> None:
    """Schema has exactly 2 fields (on/off) × 2 cycles × number of stages."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema = handler.get_dehumidifier_schema({})

    expected_count = len(DEHUMIDIFIER_STAGES) * 2 * 2
    assert len(schema.schema) == expected_count


# ---------------------------------------------------------------------------
# User input processing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_dehumidifier_saves_thresholds_and_advances() -> None:
    """Submitting threshold values saves them into env_config_step1 and advances the flow."""
    flow = _make_flow()
    flow.env_config_step1 = {"configure_advanced": False}
    handler = DehumidifierHandler(flow)

    # Build a valid user_input with all required threshold fields
    user_input = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ("day", "night"):
            user_input[f"{stage}_{cycle}_on"] = 0.8
            user_input[f"{stage}_{cycle}_off"] = 0.6

    await handler.async_step_configure_dehumidifier(user_input)

    assert flow.async_step_configure_sensor_placement.await_count == 1
    saved = flow.env_config_step1
    assert "dehumidifier_thresholds" in saved
    # Verify at least one stage is populated
    assert "veg" in saved["dehumidifier_thresholds"]
