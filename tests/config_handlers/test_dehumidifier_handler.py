"""Tests for DehumidifierHandler — schema structure and threshold persistence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.config_handlers import AbortFlow
from custom_components.growspace_manager.config_handlers.dehumidifier_handler import (
    DehumidifierHandler,
)
from custom_components.growspace_manager.const import (
    CONF_CONFIGURE_DEHUMIDIFIER,
    CONF_CONFIGURE_FAN_CONTROLLER,
    CONF_CONFIGURE_HUMIDIFIER,
    CONF_CONTROL_DEHUMIDIFIER,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_DEHUMIDIFIER_THRESHOLDS,
    DEHUMIDIFIER_STAGES,
)
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


@pytest.mark.asyncio
async def test_configure_dehumidifier_shows_form_when_no_input() -> None:
    """async_step_configure_dehumidifier shows the form when user_input is None."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)

    result = await handler.async_step_configure_dehumidifier(None)

    assert result["type"] == "form"
    assert result["step_id"] == "configure_dehumidifier"


@pytest.mark.asyncio
async def test_configure_dehumidifier_aborts_on_coordinator_failure() -> None:
    """AbortFlow from get_coordinator produces an abort result."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)

    with patch.object(handler, "get_coordinator", side_effect=AbortFlow("setup_error")):
        result = await handler.async_step_configure_dehumidifier(None)

    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_configure_dehumidifier_aborts_when_growspace_not_found() -> None:
    """A missing growspace produces a growspace_not_found abort."""
    flow = _make_flow()
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = None
    handler = DehumidifierHandler(flow)

    result = await handler.async_step_configure_dehumidifier(None)

    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_configure_dehumidifier_routes_to_advanced_bayesian_when_flag_set() -> (
    None
):
    """When configure_advanced is truthy the flow continues to advanced Bayesian step."""
    flow = _make_flow()
    flow.env_config_step1 = {"configure_advanced": True}
    handler = DehumidifierHandler(flow)

    user_input = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ("day", "night"):
            user_input[f"{stage}_{cycle}_on"] = 0.8
            user_input[f"{stage}_{cycle}_off"] = 0.6

    result = await handler.async_step_configure_dehumidifier(user_input)

    flow.async_step_configure_advanced_bayesian.assert_awaited_once()
    assert result["step_id"] == "configure_advanced_bayesian"
    assert "dehumidifier_thresholds" in flow.env_config_step1


# ---------------------------------------------------------------------------
# _add_dehumidifier_entity_selectors
# ---------------------------------------------------------------------------


def test_add_dehumidifier_entity_selectors_uses_entities_list_when_present() -> None:
    """CONF_DEHUMIDIFIER_ENTITIES is used as-is when present."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema_dict: dict = {}

    handler._add_dehumidifier_entity_selectors(
        schema_dict,
        {CONF_DEHUMIDIFIER_ENTITIES: ["switch.dehum_1"]},
    )

    keys = [k.schema if hasattr(k, "schema") else k for k in schema_dict]
    assert CONF_DEHUMIDIFIER_ENTITIES in keys


def test_add_dehumidifier_entity_selectors_falls_back_to_single_entity() -> None:
    """When CONF_DEHUMIDIFIER_ENTITIES is absent, CONF_DEHUMIDIFIER_ENTITY is wrapped in a list."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema_dict: dict = {}

    handler._add_dehumidifier_entity_selectors(
        schema_dict,
        {CONF_DEHUMIDIFIER_ENTITY: "switch.dehum_1"},
    )

    keys_with_desc = {k: v for k, v in schema_dict.items()}
    for k in keys_with_desc:
        key_name = k.schema if hasattr(k, "schema") else k
        if key_name == CONF_DEHUMIDIFIER_ENTITIES:
            desc = k.description or {}
            assert desc.get("suggested_value") == ["switch.dehum_1"]
            break
    else:
        pytest.fail("CONF_DEHUMIDIFIER_ENTITIES not found in schema_dict")


def test_add_dehumidifier_entity_selectors_uses_empty_list_when_no_entity() -> None:
    """With neither entities nor a single entity, suggested_value is an empty list."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema_dict: dict = {}

    handler._add_dehumidifier_entity_selectors(schema_dict, {})

    for k in schema_dict:
        key_name = k.schema if hasattr(k, "schema") else k
        if key_name == CONF_DEHUMIDIFIER_ENTITIES:
            desc = k.description or {}
            assert desc.get("suggested_value") == []
            break
    else:
        pytest.fail("CONF_DEHUMIDIFIER_ENTITIES not found in schema_dict")


# ---------------------------------------------------------------------------
# _add_dehumidifier_control_toggles
# ---------------------------------------------------------------------------


def _schema_defaults(schema_dict: dict) -> dict:
    """Extract {key_name: default_value} from a voluptuous schema dict."""
    result = {}
    for k in schema_dict:
        key_name = k.schema if hasattr(k, "schema") else k
        result[key_name] = k.default() if callable(k.default) else k.default
    return result


def test_add_dehumidifier_control_toggles_defaults_all_false_when_empty() -> None:
    """All toggles default to False when growspace_options is empty."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema_dict: dict = {}

    handler._add_dehumidifier_control_toggles(schema_dict, {})

    defaults = _schema_defaults(schema_dict)
    assert defaults[CONF_CONTROL_DEHUMIDIFIER] is False
    assert defaults[CONF_CONFIGURE_HUMIDIFIER] is False
    assert defaults[CONF_CONFIGURE_DEHUMIDIFIER] is False
    assert defaults[CONF_CONFIGURE_FAN_CONTROLLER] is False


def test_add_dehumidifier_control_toggles_configure_dehumidifier_true_when_thresholds_present() -> (
    None
):
    """CONF_CONFIGURE_DEHUMIDIFIER defaults to True when CONF_DEHUMIDIFIER_THRESHOLDS is set."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema_dict: dict = {}

    handler._add_dehumidifier_control_toggles(
        schema_dict, {CONF_DEHUMIDIFIER_THRESHOLDS: {"veg": {}}}
    )

    defaults = _schema_defaults(schema_dict)
    assert defaults[CONF_CONFIGURE_DEHUMIDIFIER] is True


def test_add_dehumidifier_control_toggles_fan_controller_uses_circulation_fan_config() -> (
    None
):
    """CONF_CONFIGURE_FAN_CONTROLLER mirrors circulation_fan_config enabled flag."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema_dict: dict = {}

    handler._add_dehumidifier_control_toggles(
        schema_dict, {"circulation_fan_config": {"enabled": True}}
    )

    defaults = _schema_defaults(schema_dict)
    assert defaults[CONF_CONFIGURE_FAN_CONTROLLER] is True


def test_add_dehumidifier_control_toggles_fan_controller_false_for_non_dict_fan_config() -> (
    None
):
    """A non-dict circulation_fan_config treats fan as not configured."""
    flow = _make_flow()
    handler = DehumidifierHandler(flow)
    schema_dict: dict = {}

    handler._add_dehumidifier_control_toggles(
        schema_dict, {"circulation_fan_config": "invalid"}
    )

    defaults = _schema_defaults(schema_dict)
    assert defaults[CONF_CONFIGURE_FAN_CONTROLLER] is False
