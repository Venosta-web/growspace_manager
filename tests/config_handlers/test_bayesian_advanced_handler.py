"""Tests for BayesianAdvancedHandler — schema generation, parsing, and persistence."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.bayesian_advanced_handler import (
    BayesianAdvancedHandler,
)
from custom_components.growspace_manager.const import CONF_PROB_TEMP_EXTREME_HEAT
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
    flow.async_step_configure_sensor_placement = AsyncMock(
        return_value={"type": "form", "step_id": "configure_sensor_placement"}
    )
    return flow


# ---------------------------------------------------------------------------
# get_advanced_bayesian_schema
# ---------------------------------------------------------------------------


def test_advanced_bayesian_schema_contains_prob_temp_extreme_heat() -> None:
    """Schema has the CONF_PROB_TEMP_EXTREME_HEAT field."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    schema = handler.get_advanced_bayesian_schema({})

    keys = [k.schema if hasattr(k, "schema") else k for k in schema.schema]
    assert CONF_PROB_TEMP_EXTREME_HEAT in keys


def test_advanced_bayesian_schema_field_defaults_encode_as_string_tuples() -> None:
    """Default values in the schema are string representations of tuples."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    schema = handler.get_advanced_bayesian_schema({})

    # Get the default for CONF_PROB_TEMP_EXTREME_HEAT
    for k in schema.schema:
        key_name = k.schema if hasattr(k, "schema") else k
        if key_name == CONF_PROB_TEMP_EXTREME_HEAT:
            default_val = k.default()
            assert isinstance(default_val, str)
            assert default_val.startswith("(")
            break


# ---------------------------------------------------------------------------
# parse_advanced_bayesian_input
# ---------------------------------------------------------------------------


def test_parse_valid_tuple_string() -> None:
    """Valid tuple strings are parsed to Python tuples."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    result = handler.parse_advanced_bayesian_input(
        {CONF_PROB_TEMP_EXTREME_HEAT: "(0.98, 0.05)"}
    )

    assert result[CONF_PROB_TEMP_EXTREME_HEAT] == (0.98, 0.05)


def test_parse_raises_value_error_for_non_tuple_string() -> None:
    """Non-tuple strings raise ValueError."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    with pytest.raises(ValueError):
        handler.parse_advanced_bayesian_input(
            {CONF_PROB_TEMP_EXTREME_HEAT: "not_a_tuple"}
        )


def test_parse_raises_value_error_for_missing_parentheses() -> None:
    """Strings not starting with '(' raise ValueError."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    with pytest.raises(ValueError):
        handler.parse_advanced_bayesian_input(
            {CONF_PROB_TEMP_EXTREME_HEAT: "0.98, 0.05"}
        )


# ---------------------------------------------------------------------------
# Sensor coordinate schema
# ---------------------------------------------------------------------------


def test_build_sensor_coordinate_schema_generates_xyz_fields() -> None:
    """_build_sensor_coordinate_schema produces x/y/z fields for each sensor."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(
        id="gs1",
        name="Tent",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 120.0, "length": 100.0, "height": 200.0, "unit": "cm"},
    )

    schema_dict = handler._build_sensor_coordinate_schema(
        sensors_to_configure=["sensor.temp_1"],
        sensors_allowed_outside=set(),
        growspace=growspace,
    )

    keys = [k.schema if hasattr(k, "schema") else k for k in schema_dict]
    assert "coord_sensor.temp_1_x" in keys
    assert "coord_sensor.temp_1_y" in keys
    assert "coord_sensor.temp_1_z" in keys


# ---------------------------------------------------------------------------
# Step persistence
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_advanced_bayesian_step_persists_parsed_input() -> None:
    """Submitting valid Bayesian input updates env_config_step1.bayesian_options."""
    flow = _make_flow()
    flow.env_config_step1 = {}
    handler = BayesianAdvancedHandler(flow)

    user_input = {CONF_PROB_TEMP_EXTREME_HEAT: "(0.98, 0.05)"}

    result = await handler.async_step_configure_advanced_bayesian(user_input)

    flow.async_step_configure_sensor_placement.assert_awaited_once()
    assert result["step_id"] == "configure_sensor_placement"
    bayesian_opts = flow.env_config_step1.get("bayesian_options", {})
    assert CONF_PROB_TEMP_EXTREME_HEAT in bayesian_opts
    assert bayesian_opts[CONF_PROB_TEMP_EXTREME_HEAT] == (0.98, 0.05)
