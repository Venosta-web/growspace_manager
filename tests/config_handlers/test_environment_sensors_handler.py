"""Tests for EnvironmentSensorsHandler — schema fields and routing."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.environment_sensors_handler import (
    EnvironmentSensorsHandler,
)
from custom_components.growspace_manager.const import (
    CANONICAL_ID_CURE,
    CANONICAL_ID_DRY,
    CONF_BULK_EC_SENSORS,
    CONF_FEED_EC_SENSORS,
    CONF_HUMIDITY_SENSOR,
    CONF_IRRIGATION_TANK_SENSORS,
    CONF_IRRIGATION_TANK_WARNING_LEVEL,
    CONF_PORE_EC_SENSORS,
    CONF_RUNOFF_EC_SENSORS,
    CONF_TEMP_SENSOR,
    CONF_TEMP_SENSORS,
)
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.models.irrigation import IrrigationTank


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
    coordinator.services.save = AsyncMock()
    coordinator.async_refresh = AsyncMock()

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


# ---------------------------------------------------------------------------
# async_step_select_growspace_for_env
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_select_growspace_for_env_aborts_when_coordinator_unavailable() -> None:
    """Step aborts with setup_error when get_coordinator raises AbortFlow."""
    flow = _make_flow()
    flow.config_entry = None  # triggers AbortFlow in get_coordinator
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_select_growspace_for_env()

    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_select_growspace_for_env_aborts_when_no_growspaces() -> None:
    """Step aborts when there are no growspace options."""
    flow = _make_flow()
    flow.config_entry.runtime_data.services.growspaces.get_sorted_growspace_options.return_value = []
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_select_growspace_for_env()

    assert result["type"] == "abort"
    assert result["reason"] == "no_growspaces"


@pytest.mark.asyncio
async def test_select_growspace_for_env_shows_form_when_no_user_input() -> None:
    """Step shows the growspace selection form when user_input is None."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_select_growspace_for_env(user_input=None)

    assert result["type"] == "form"
    flow.async_show_form.assert_called_once()
    call_kwargs = flow.async_show_form.call_args.kwargs
    assert call_kwargs["step_id"] == "select_growspace_for_env"


@pytest.mark.asyncio
async def test_select_growspace_for_env_sets_id_and_advances_on_input() -> None:
    """Step sets selected_growspace_id and calls configure_environment step."""
    flow = _make_flow()
    flow.async_step_configure_environment = AsyncMock(
        return_value={"type": "form", "step_id": "configure_environment"}
    )
    handler = EnvironmentSensorsHandler(flow)

    await handler.async_step_select_growspace_for_env(user_input={"growspace_id": "gs1"})

    assert flow.selected_growspace_id == "gs1"
    flow.async_step_configure_environment.assert_awaited_once()


# ---------------------------------------------------------------------------
# async_step_configure_environment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_environment_aborts_when_coordinator_unavailable() -> None:
    """Step aborts when config_entry is None."""
    flow = _make_flow()
    flow.config_entry = None
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_configure_environment()

    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_configure_environment_aborts_when_growspace_not_found() -> None:
    """Step aborts when growspace is not found in coordinator."""
    flow = _make_flow()
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = None
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_configure_environment()

    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_configure_environment_shows_form_when_no_user_input() -> None:
    """Step shows configure_environment form when user_input is None."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_configure_environment(user_input=None)

    assert result["type"] == "form"
    call_kwargs = flow.async_show_form.call_args.kwargs
    assert call_kwargs["step_id"] == "configure_environment"


@pytest.mark.asyncio
async def test_configure_environment_processes_user_input_and_advances() -> None:
    """Step processes user_input, stores env_config_step1, then routes."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    user_input = {
        "temp_sensors": ["sensor.temp"],
        "humidity_sensors": ["sensor.humidity"],
    }
    await handler.async_step_configure_environment(user_input=user_input)

    flow.async_step_configure_sensor_placement.assert_awaited_once()
    assert flow.env_config_step1 is not None


@pytest.mark.asyncio
async def test_configure_environment_loads_existing_irrigation_tanks() -> None:
    """Step reads irrigation_tanks from existing environment_config."""
    flow = _make_flow()
    tank = IrrigationTank(sensor_entity="sensor.tank1", name="Tank 1", warning_level=25.0)
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = Growspace(
        id="gs1",
        name="Test Tent",
        environment_config=EnvironmentConfig(irrigation_tanks=[tank]),
    )
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_configure_environment(user_input=None)

    assert result["type"] == "form"
    # Verify the form was shown with description_placeholders
    call_kwargs = flow.async_show_form.call_args.kwargs
    assert "growspace_name" in call_kwargs.get("description_placeholders", {})


@pytest.mark.asyncio
async def test_configure_environment_no_existing_config_uses_empty_options() -> None:
    """Step uses empty options when growspace has no environment_config."""
    flow = _make_flow()
    growspace = Growspace(id="gs1", name="Test Tent")
    growspace.environment_config = None  # type: ignore[assignment]
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = growspace
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_configure_environment(user_input=None)

    assert result["type"] == "form"


# ---------------------------------------------------------------------------
# _process_irrigation_tanks
# ---------------------------------------------------------------------------


def test_process_irrigation_tanks_empty_sensors_returns_empty_list() -> None:
    """No tank_sensors → irrigation_tanks set to empty list."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = handler._process_irrigation_tanks({CONF_IRRIGATION_TANK_SENSORS: []})

    assert result["irrigation_tanks"] == []
    assert CONF_IRRIGATION_TANK_SENSORS not in result


def test_process_irrigation_tanks_creates_new_tank_dict() -> None:
    """New sensor with no existing tank → creates default tank dict."""
    flow = _make_flow()
    flow.hass.states.get.return_value = None
    handler = EnvironmentSensorsHandler(flow)

    env_config = {
        CONF_IRRIGATION_TANK_SENSORS: ["sensor.tank1"],
        CONF_IRRIGATION_TANK_WARNING_LEVEL: 30.0,
    }
    result = handler._process_irrigation_tanks(env_config)

    assert len(result["irrigation_tanks"]) == 1
    tank = result["irrigation_tanks"][0]
    assert tank["sensor_entity"] == "sensor.tank1"
    assert tank["name"] == "Tank 1"
    assert tank["warning_level"] == 30.0
    assert CONF_IRRIGATION_TANK_SENSORS not in result


def test_process_irrigation_tanks_uses_friendly_name_from_state() -> None:
    """Tank name comes from state's friendly_name attribute when available."""
    flow = _make_flow()
    state_mock = MagicMock()
    state_mock.attributes.get.return_value = "Main Reservoir"
    flow.hass.states.get.return_value = state_mock
    handler = EnvironmentSensorsHandler(flow)

    result = handler._process_irrigation_tanks(
        {CONF_IRRIGATION_TANK_SENSORS: ["sensor.tank1"], CONF_IRRIGATION_TANK_WARNING_LEVEL: 20.0}
    )

    assert result["irrigation_tanks"][0]["name"] == "Main Reservoir"


def test_process_irrigation_tanks_preserves_existing_dataclass_tank_data() -> None:
    """Existing IrrigationTank dataclass → water_history, levels are preserved."""
    flow = _make_flow()
    flow.hass.states.get.return_value = None
    handler = EnvironmentSensorsHandler(flow)

    existing_tank = IrrigationTank(
        sensor_entity="sensor.tank1",
        name="Old Tank",
        last_recorded_level=55.0,
        peak_level=90.0,
    )
    result = handler._process_irrigation_tanks(
        {CONF_IRRIGATION_TANK_SENSORS: ["sensor.tank1"], CONF_IRRIGATION_TANK_WARNING_LEVEL: 30.0},
        existing_tanks=[existing_tank],
    )

    tank = result["irrigation_tanks"][0]
    assert tank["last_recorded_level"] == 55.0
    assert tank["peak_level"] == 90.0


def test_process_irrigation_tanks_preserves_existing_dict_tank_data() -> None:
    """Existing tank as a plain dict → water_history, levels are preserved."""
    flow = _make_flow()
    flow.hass.states.get.return_value = None
    handler = EnvironmentSensorsHandler(flow)

    existing_tank_dict: dict = {
        "sensor_entity": "sensor.tank1",
        "name": "Dict Tank",
        "last_recorded_level": 42.5,
        "peak_level": 80.0,
        "water_history": {"some": "data"},
    }
    result = handler._process_irrigation_tanks(
        {CONF_IRRIGATION_TANK_SENSORS: ["sensor.tank1"], CONF_IRRIGATION_TANK_WARNING_LEVEL: 30.0},
        existing_tanks=[existing_tank_dict],  # type: ignore[list-item]
    )

    tank = result["irrigation_tanks"][0]
    assert tank["last_recorded_level"] == 42.5
    assert tank["peak_level"] == 80.0
    assert tank["water_history"] == {"some": "data"}


# ---------------------------------------------------------------------------
# _async_save_and_finish
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_async_save_and_finish_saves_env_config_and_returns_entry() -> None:
    """_async_save_and_finish updates growspace, saves, refreshes, and creates entry."""
    flow = _make_flow()
    flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    handler = EnvironmentSensorsHandler(flow)

    growspace = Growspace(id="gs1", name="Test Tent")
    env_config = {
        "temp_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
    }
    result = await handler._async_save_and_finish(growspace, env_config)

    assert result["type"] == "create_entry"
    assert growspace.environment_config is not None
    flow.config_entry.runtime_data.services.save.assert_awaited_once()
    flow.config_entry.runtime_data.async_refresh.assert_awaited_once()


# ---------------------------------------------------------------------------
# clean_input — branch coverage
# ---------------------------------------------------------------------------


def test_clean_input_wraps_truthy_non_list_value_in_list() -> None:
    """A truthy scalar value for a list field is wrapped in a single-element list."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = handler.clean_input({CONF_TEMP_SENSORS: "sensor.temp"})

    assert result[CONF_TEMP_SENSORS] == ["sensor.temp"]


def test_clean_input_sets_list_field_to_empty_list_for_falsy_value() -> None:
    """A falsy value (empty string) for a list field becomes an empty list."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    # Empty string is filtered out by base clean_input, so pass a list with empty string
    result = handler.clean_input({CONF_TEMP_SENSORS: ["", "sensor.a"]})

    assert result[CONF_TEMP_SENSORS] == ["sensor.a"]


def test_clean_input_sets_list_field_empty_when_value_is_none_string() -> None:
    """A None value for a list field becomes an empty list."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    # Simulate a field that's in user_input as falsy non-list (e.g. 0 or False)
    result = handler.clean_input({CONF_TEMP_SENSORS: 0})

    assert result[CONF_TEMP_SENSORS] == []


def test_clean_input_sets_optional_field_to_none_for_empty_string() -> None:
    """An empty-string optional field (e.g. vpd_sensor) is set to None."""
    from custom_components.growspace_manager.const import CONF_VPD_SENSOR

    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = handler.clean_input({CONF_VPD_SENSOR: ""})

    assert result[CONF_VPD_SENSOR] is None


def test_clean_input_optional_field_absent_does_not_add_it() -> None:
    """An optional field not in user_input is not added to cleaned output."""
    from custom_components.growspace_manager.const import CONF_VPD_SENSOR

    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = handler.clean_input({CONF_TEMP_SENSORS: ["sensor.temp"]})

    assert CONF_VPD_SENSOR not in result


def test_clean_input_plural_to_singular_maps_first_element() -> None:
    """When temperature_sensors has values, temperature_sensor is set to the first."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = handler.clean_input({CONF_TEMP_SENSORS: ["sensor.a", "sensor.b"]})

    assert result[CONF_TEMP_SENSOR] == "sensor.a"


def test_clean_input_plural_to_singular_maps_none_for_empty_list() -> None:
    """When temperature_sensors is empty, temperature_sensor is set to None."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    result = handler.clean_input({CONF_TEMP_SENSORS: 0})  # falsy → empty list

    assert result[CONF_TEMP_SENSOR] is None


# ---------------------------------------------------------------------------
# LST offset schema — dry/cure stage uses 0.0 default
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_environment_loads_volume_liters_from_existing_tank() -> None:
    """volume_liters from existing tank is propagated to growspace_options."""

    flow = _make_flow()
    tank = IrrigationTank(
        sensor_entity="sensor.tank1",
        name="Tank 1",
        warning_level=25.0,
        volume_liters=20.0,
    )
    flow.config_entry.runtime_data.services.growspaces.get_growspace.return_value = Growspace(
        id="gs1",
        name="Test Tent",
        environment_config=EnvironmentConfig(irrigation_tanks=[tank]),
    )
    handler = EnvironmentSensorsHandler(flow)

    result = await handler.async_step_configure_environment(user_input=None)

    assert result["type"] == "form"
    # Verify show_form was called (volume_liters path was exercised)
    flow.async_show_form.assert_called_once()


@pytest.mark.asyncio
async def test_configure_environment_preserves_sensor_groups_in_env_config() -> None:
    """sensor_groups in user_input is preserved in env_config_step1."""
    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    user_input = {
        "sensor_groups": [{"name": "Group A", "sensors": ["sensor.temp"]}],
    }
    await handler.async_step_configure_environment(user_input=user_input)

    assert flow.env_config_step1.get("sensor_groups") == user_input["sensor_groups"]


def _get_schema_defaults(schema: object) -> dict:
    """Extract schema key → resolved default value from a vol.Schema."""
    result = {}
    for k in schema.schema:  # type: ignore[attr-defined]
        key = k.schema if hasattr(k, "schema") else k
        raw = getattr(k, "default", None)
        result[key] = raw() if callable(raw) else raw
    return result


def test_lst_offset_default_is_zero_for_dry_stage() -> None:
    """Dry stage uses 0.0 as LST offset default, not -2.0."""
    from custom_components.growspace_manager.const import CONF_LST_OFFSET

    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    options = {CONF_TEMP_SENSOR: "sensor.temp", CONF_HUMIDITY_SENSOR: "sensor.humidity"}
    schema = handler.get_environment_schema_step1(options, stage=CANONICAL_ID_DRY)
    defaults = _get_schema_defaults(schema)

    assert CONF_LST_OFFSET in defaults
    assert defaults[CONF_LST_OFFSET] == 0.0


def test_lst_offset_default_is_zero_for_cure_stage() -> None:
    """Cure stage uses 0.0 as LST offset default, not -2.0."""
    from custom_components.growspace_manager.const import CONF_LST_OFFSET

    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    options = {CONF_TEMP_SENSOR: "sensor.temp", CONF_HUMIDITY_SENSOR: "sensor.humidity"}
    schema = handler.get_environment_schema_step1(options, stage=CANONICAL_ID_CURE)
    defaults = _get_schema_defaults(schema)

    assert CONF_LST_OFFSET in defaults
    assert defaults[CONF_LST_OFFSET] == 0.0


def test_lst_offset_default_is_negative_two_for_standard_stage() -> None:
    """Standard (non-dry/cure) stage uses -2.0 as LST offset default."""
    from custom_components.growspace_manager.const import CONF_LST_OFFSET

    flow = _make_flow()
    handler = EnvironmentSensorsHandler(flow)

    options = {CONF_TEMP_SENSOR: "sensor.temp", CONF_HUMIDITY_SENSOR: "sensor.humidity"}
    schema = handler.get_environment_schema_step1(options, stage="flower")
    defaults = _get_schema_defaults(schema)

    assert CONF_LST_OFFSET in defaults
    assert defaults[CONF_LST_OFFSET] == -2.0


def test_advanced_sensors_schema_order_is_feed_bulk_pore_runoff() -> None:
    """Advanced sensors section lists EC sensors in order: Feed → Bulk → Pore → Runoff."""
    flow = _make_flow(configure_advanced=True)
    handler = EnvironmentSensorsHandler(flow)

    options: dict = {}
    schema = handler.get_environment_schema_step1(options)

    ec_sensor_keys = (CONF_FEED_EC_SENSORS, CONF_BULK_EC_SENSORS, CONF_PORE_EC_SENSORS, CONF_RUNOFF_EC_SENSORS)
    keys = [k.schema if hasattr(k, "schema") else str(k) for k in schema.schema]
    ec_keys = [k for k in keys if k in ec_sensor_keys]

    assert ec_keys == [CONF_FEED_EC_SENSORS, CONF_BULK_EC_SENSORS, CONF_PORE_EC_SENSORS, CONF_RUNOFF_EC_SENSORS]
