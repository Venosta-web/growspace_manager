"""Tests for BayesianAdvancedHandler — schema generation, parsing, and persistence."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.config_handlers import AbortFlow
from custom_components.growspace_manager.config_handlers.bayesian_advanced_handler import (
    BayesianAdvancedHandler,
)
from custom_components.growspace_manager.const import CONF_PROB_TEMP_EXTREME_HEAT
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationConfig,
)


def _make_flow(growspace: Growspace | None = None) -> MagicMock:
    if growspace is None:
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
    flow.async_step_save_and_finish = AsyncMock(
        return_value={"type": "create_entry"}
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


@pytest.mark.asyncio
async def test_advanced_bayesian_step_shows_form_when_no_input() -> None:
    """async_step_configure_advanced_bayesian shows form when user_input is None."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    result = await handler.async_step_configure_advanced_bayesian(None)

    assert result["type"] == "form"
    assert result["step_id"] == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_advanced_bayesian_step_aborts_when_coordinator_unavailable() -> None:
    """async_step_configure_advanced_bayesian aborts when get_coordinator raises AbortFlow."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    with patch.object(handler, "get_coordinator", side_effect=AbortFlow("setup_error")):
        result = await handler.async_step_configure_advanced_bayesian(None)

    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_advanced_bayesian_step_aborts_when_growspace_not_found() -> None:
    """async_step_configure_advanced_bayesian aborts when growspace is None."""
    flow = _make_flow()
    coordinator = flow.config_entry.runtime_data
    coordinator.services.growspaces.get_growspace.return_value = None
    handler = BayesianAdvancedHandler(flow)

    result = await handler.async_step_configure_advanced_bayesian(None)

    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_advanced_bayesian_step_shows_error_form_on_invalid_parse() -> None:
    """Invalid tuple input shows form with invalid_tuple_format error."""
    flow = _make_flow()
    flow.env_config_step1 = {}
    handler = BayesianAdvancedHandler(flow)

    result = await handler.async_step_configure_advanced_bayesian(
        {CONF_PROB_TEMP_EXTREME_HEAT: "not_a_tuple"}
    )

    assert result["type"] == "form"
    assert result["step_id"] == "configure_advanced_bayesian"
    call_kwargs = flow.async_show_form.call_args.kwargs
    assert call_kwargs.get("errors") == {"base": "invalid_tuple_format"}


@pytest.mark.asyncio
async def test_advanced_bayesian_step_resets_non_dict_bayesian_opts() -> None:
    """When bayesian_options in env_config is not a dict it is replaced with a fresh dict."""
    flow = _make_flow()
    flow.env_config_step1 = {"bayesian_options": "stale_string"}
    handler = BayesianAdvancedHandler(flow)

    await handler.async_step_configure_advanced_bayesian(
        {CONF_PROB_TEMP_EXTREME_HEAT: "(0.98, 0.05)"}
    )

    bayesian_opts = flow.env_config_step1.get("bayesian_options", {})
    assert isinstance(bayesian_opts, dict)
    assert bayesian_opts[CONF_PROB_TEMP_EXTREME_HEAT] == (0.98, 0.05)


# ---------------------------------------------------------------------------
# parse_advanced_bayesian_input — non-string and non-tuple branches
# ---------------------------------------------------------------------------


def test_parse_passthrough_non_string_value() -> None:
    """Non-string values are passed through unchanged."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    result = handler.parse_advanced_bayesian_input({CONF_PROB_TEMP_EXTREME_HEAT: (0.9, 0.1)})

    assert result[CONF_PROB_TEMP_EXTREME_HEAT] == (0.9, 0.1)


def test_parse_raises_type_error_when_literal_eval_not_tuple() -> None:
    """A valid Python literal that is not a tuple raises TypeError."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    with pytest.raises(TypeError):
        handler.parse_advanced_bayesian_input({CONF_PROB_TEMP_EXTREME_HEAT: "([1, 2])"})


# ---------------------------------------------------------------------------
# async_step_configure_sensor_placement
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_sensor_placement_aborts_when_coordinator_unavailable() -> None:
    """async_step_configure_sensor_placement aborts on AbortFlow from get_coordinator."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)

    with patch.object(handler, "get_coordinator", side_effect=AbortFlow("setup_error")):
        result = await handler.async_step_configure_sensor_placement(None)

    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_sensor_placement_aborts_when_growspace_not_found() -> None:
    """async_step_configure_sensor_placement aborts when growspace is None."""
    flow = _make_flow()
    coordinator = flow.config_entry.runtime_data
    coordinator.services.growspaces.get_growspace.return_value = None
    handler = BayesianAdvancedHandler(flow)

    result = await handler.async_step_configure_sensor_placement(None)

    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_sensor_placement_skips_to_finish_when_no_sensors() -> None:
    """With no configured sensors the step jumps straight to save_and_finish."""
    flow = _make_flow()
    flow.env_config_step1 = {}
    handler = BayesianAdvancedHandler(flow)

    result = await handler.async_step_configure_sensor_placement(None)

    flow.async_step_save_and_finish.assert_awaited_once()
    assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_sensor_placement_shows_form_when_sensors_present() -> None:
    """With sensors configured and no user_input, the form is shown."""
    flow = _make_flow()
    flow.env_config_step1 = {"temperature_sensors": ["sensor.temp_1"]}
    handler = BayesianAdvancedHandler(flow)

    result = await handler.async_step_configure_sensor_placement(None)

    assert result["type"] == "form"
    assert result["step_id"] == "configure_sensor_placement"


@pytest.mark.asyncio
async def test_sensor_placement_saves_coordinates_on_submit() -> None:
    """Submitting coordinate user_input stores sensor_coordinates and finishes."""
    flow = _make_flow()
    flow.env_config_step1 = {"temperature_sensors": ["sensor.temp_1"]}
    handler = BayesianAdvancedHandler(flow)

    user_input = {
        "coord_sensor.temp_1_x": 60.0,
        "coord_sensor.temp_1_y": 50.0,
        "coord_sensor.temp_1_z": 100.0,
    }

    result = await handler.async_step_configure_sensor_placement(user_input)

    flow.async_step_save_and_finish.assert_awaited_once()
    assert result["type"] == "create_entry"
    coords = flow.env_config_step1.get("sensor_coordinates", {})
    assert coords["sensor.temp_1"] == {"x": 60.0, "y": 50.0, "z": 100.0}


# ---------------------------------------------------------------------------
# _collect_sensors_to_configure
# ---------------------------------------------------------------------------


def test_collect_sensors_from_list_value() -> None:
    """List values produce multiple entries in sensors_to_configure."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent")
    env_config = {"temperature_sensors": ["sensor.t1", "sensor.t2"]}

    sensors, allowed = handler._collect_sensors_to_configure(env_config, growspace)

    assert "sensor.t1" in sensors
    assert "sensor.t2" in sensors
    assert "sensor.t1" not in allowed


def test_collect_sensors_single_string_value() -> None:
    """A single string value is collected as one sensor."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent")
    env_config = {"co2_sensor": "sensor.co2"}

    sensors, allowed = handler._collect_sensors_to_configure(env_config, growspace)

    assert "sensor.co2" in sensors


def test_collect_sensors_humidifier_is_allowed_outside() -> None:
    """Humidifier entities are added to sensors_allowed_outside."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent")
    env_config = {"humidifier_entities": ["switch.humidifier"]}

    sensors, allowed = handler._collect_sensors_to_configure(env_config, growspace)

    assert "switch.humidifier" in sensors
    assert "switch.humidifier" in allowed


def test_collect_sensors_camera_is_allowed_outside() -> None:
    """Camera entities are added to sensors_allowed_outside."""
    from custom_components.growspace_manager.const import CONF_CAMERA_ENTITIES

    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent")
    env_config = {CONF_CAMERA_ENTITIES: ["camera.grow_cam"]}

    sensors, allowed = handler._collect_sensors_to_configure(env_config, growspace)

    assert "camera.grow_cam" in allowed


def test_collect_sensors_skips_non_string_list_entries() -> None:
    """Non-string entries inside a list are silently skipped."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent")
    env_config = {"temperature_sensors": [42, None, "sensor.valid"]}

    sensors, _ = handler._collect_sensors_to_configure(env_config, growspace)

    assert sensors == ["sensor.valid"]


def test_collect_sensors_skips_list_with_only_non_string_entries() -> None:
    """A list whose every entry is non-string produces no sensors for that key."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent")
    env_config = {"temperature_sensors": [42, None]}

    sensors, _ = handler._collect_sensors_to_configure(env_config, growspace)

    assert sensors == []


def test_collect_sensors_from_irrigation_tanks() -> None:
    """irrigation_tanks sensor_entity entries are collected and allowed outside."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent")
    env_config = {
        "irrigation_tanks": [{"sensor_entity": "sensor.tank_1"}, {"other": "x"}]
    }

    sensors, allowed = handler._collect_sensors_to_configure(env_config, growspace)

    assert "sensor.tank_1" in sensors
    assert "sensor.tank_1" in allowed


def test_collect_sensors_from_irrigation_config_pumps() -> None:
    """Pump entities from growspace.irrigation_config are collected and allowed outside."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    irrigation = IrrigationConfig(
        irrigation_pump_entity="switch.pump",
        drain_pump_entity="switch.drain_pump",
    )
    growspace = Growspace(id="gs1", name="Tent", irrigation_config=irrigation)
    env_config: dict = {}

    sensors, allowed = handler._collect_sensors_to_configure(env_config, growspace)

    assert "switch.pump" in sensors
    assert "switch.pump" in allowed
    assert "switch.drain_pump" in sensors
    assert "switch.drain_pump" in allowed


# ---------------------------------------------------------------------------
# _build_sensor_coordinate_schema — allowed-outside sensor expands ranges
# ---------------------------------------------------------------------------


def test_build_sensor_coordinate_schema_expands_ranges_for_outside_sensors() -> None:
    """Sensors in sensors_allowed_outside get wider min/max ranges."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(
        id="gs1",
        name="Tent",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 120.0, "length": 100.0, "height": 200.0, "unit": "cm"},
    )

    schema_outside = handler._build_sensor_coordinate_schema(
        sensors_to_configure=["switch.pump"],
        sensors_allowed_outside={"switch.pump"},
        growspace=growspace,
    )
    schema_inside = handler._build_sensor_coordinate_schema(
        sensors_to_configure=["sensor.temp_1"],
        sensors_allowed_outside=set(),
        growspace=growspace,
    )

    def _get_selector_config(schema_dict: dict, coord_key: str):  # type: ignore[return]
        for k, v in schema_dict.items():
            if (k.schema if hasattr(k, "schema") else k) == coord_key:
                return v.config

    outside_x = _get_selector_config(schema_outside, "coord_switch.pump_x")
    inside_x = _get_selector_config(schema_inside, "coord_sensor.temp_1_x")

    assert outside_x["min"] < inside_x["min"]
    assert outside_x["max"] > inside_x["max"]


def test_build_sensor_coordinate_schema_uses_defaults_when_dimensions_missing() -> None:
    """Missing growspace dimensions fall back to (120, 120, 200) cm defaults."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(id="gs1", name="Tent", environment_config=EnvironmentConfig())

    schema_dict = handler._build_sensor_coordinate_schema(
        sensors_to_configure=["sensor.temp_1"],
        sensors_allowed_outside=set(),
        growspace=growspace,
    )

    def _get_selector_config(schema_dict: dict, coord_key: str):  # type: ignore[return]
        for k, v in schema_dict.items():
            if (k.schema if hasattr(k, "schema") else k) == coord_key:
                return v.config

    z_config = _get_selector_config(schema_dict, "coord_sensor.temp_1_z")
    assert z_config["max"] == 200.0


def test_build_sensor_coordinate_schema_falls_back_unit_when_not_string() -> None:
    """A non-string unit in dimensions falls back to 'cm'."""
    flow = _make_flow()
    handler = BayesianAdvancedHandler(flow)
    growspace = Growspace(
        id="gs1",
        name="Tent",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 120.0, "length": 100.0, "height": 200.0, "unit": 42},
    )

    def _get_selector_config(schema_dict: dict, coord_key: str):  # type: ignore[return]
        for k, v in schema_dict.items():
            if (k.schema if hasattr(k, "schema") else k) == coord_key:
                return v.config

    schema_dict = handler._build_sensor_coordinate_schema(
        sensors_to_configure=["sensor.temp_1"],
        sensors_allowed_outside=set(),
        growspace=growspace,
    )
    x_config = _get_selector_config(schema_dict, "coord_sensor.temp_1_x")
    assert x_config["unit_of_measurement"] == "cm"
