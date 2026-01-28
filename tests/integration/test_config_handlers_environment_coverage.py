"""Coverage-focused tests for EnvironmentConfigHandler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_handlers.environment_config_handler import (
    EnvironmentConfigHandler,
)
from custom_components.growspace_manager.const import (
    CONF_HUMIDITY_SENSOR,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_TEMP_SENSOR,
    DEHUMIDIFIER_STAGES,
)
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from homeassistant.config_entries import ConfigFlow


class MockFlow(ConfigFlow):
    """Mock flow."""

    def __init__(self) -> None:
        super().__init__()
        self.selected_growspace_id = None
        self.env_config_step1 = {}


@pytest.fixture
def handler():
    """EnvironmentConfigHandler fixture."""
    flow = MockFlow()
    handler = EnvironmentConfigHandler(flow)
    handler.config_entry = MagicMock()
    handler.config_entry.runtime_data = MagicMock()
    handler.config_entry.runtime_data.async_save = AsyncMock()
    handler.config_entry.runtime_data.async_refresh = AsyncMock()
    handler.hass = MagicMock()
    return handler


@pytest.mark.asyncio
async def test_select_growspace_for_env_success(handler) -> None:
    """Test selecting a growspace for environment config."""
    handler.config_entry.runtime_data.growspace_service.get_sorted_growspace_options.return_value = [
        ("gs1", "GS1")
    ]

    # Show form
    result = await handler.async_step_select_growspace_for_env()
    assert result["type"] == "form"

    # Submit form
    with patch.object(
        handler, "async_step_configure_environment", return_value={"type": "form"}
    ) as mock_next:
        result = await handler.async_step_select_growspace_for_env(
            {"growspace_id": "gs1"}
        )
        assert handler.flow.selected_growspace_id == "gs1"
        mock_next.assert_called_once()


@pytest.mark.asyncio
async def test_select_growspace_no_options(handler) -> None:
    """Test select growspace when none exist."""
    handler.config_entry.runtime_data.growspace_service.get_sorted_growspace_options.return_value = []
    result = await handler.async_step_select_growspace_for_env()
    assert result["type"] == "abort"
    assert result["reason"] == "no_growspaces"


@pytest.mark.asyncio
async def test_configure_environment_with_tanks(handler) -> None:
    """Test environment config with irrigation tanks."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        environment_config=EnvironmentConfig(
            irrigation_tanks=[{"sensor_entity": "sensor.tank1", "warning_level": 20.0}]
        ),
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    # Show form - should prefill tanks
    result = await handler.async_step_configure_environment()
    assert result["type"] == "form"

    # Submit form with new tank
    user_input = {
        "temperature_sensors": ["sensor.t1"],
        "humidity_sensors": ["sensor.h1"],
        "irrigation_tank_sensors": ["sensor.tank2"],
        "irrigation_tank_warning_level": 15.0,
    }

    # Mock hass.states.get for tank name
    mock_state = MagicMock()
    mock_state.attributes = {"friendly_name": "New Tank"}
    handler.hass.states.get.return_value = mock_state

    with patch.object(
        handler, "async_step_configure_sensor_placement", return_value={"type": "form"}
    ):
        await handler.async_step_configure_environment(user_input)
        env_config = handler.flow.env_config_step1
        assert len(env_config["irrigation_tanks"]) == 1
        assert env_config["irrigation_tanks"][0]["name"] == "New Tank"
        assert env_config["irrigation_tanks"][0]["warning_level"] == 15.0


@pytest.mark.asyncio
async def test_configure_dehumidifier_branch(handler) -> None:
    """Test branching to dehumidifier config."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensors": ["sensor.t1"],
        "humidity_sensors": ["sensor.h1"],
        "configure_dehumidifier": True,
        "control_dehumidifier": True,
        "dehumidifier_entities": ["switch.d1"],
    }

    with patch.object(
        handler, "async_step_configure_dehumidifier", return_value={"type": "form"}
    ) as mock_step:
        await handler.async_step_configure_environment(user_input)
        mock_step.assert_called_once()


@pytest.mark.asyncio
async def test_configure_advanced_branch(handler) -> None:
    """Test branching to advanced config."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensors": ["sensor.t1"],
        "humidity_sensors": ["sensor.h1"],
        "configure_advanced": True,
    }

    with patch.object(
        handler, "async_step_configure_advanced_bayesian", return_value={"type": "form"}
    ) as mock_step:
        await handler.async_step_configure_environment(user_input)
        mock_step.assert_called_once()


@pytest.mark.asyncio
async def test_configure_advanced_bayesian_parse_error(handler) -> None:
    """Test advanced Bayesian config with parsing error."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {}

    with patch.object(
        handler, "parse_advanced_bayesian_input", side_effect=ValueError("Invalid")
    ):
        result = await handler.async_step_configure_advanced_bayesian({"any": "thing"})
        assert result["type"] == "form"
        assert result["errors"] == {"base": "invalid_tuple_format"}


@pytest.mark.asyncio
async def test_configure_sensor_placement_no_sensors(handler) -> None:
    """Test sensor placement step when no sensors are configured."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {}  # No sensors

    with patch.object(
        handler, "_async_save_and_finish", return_value={"type": "create_entry"}
    ) as mock_finish:
        await handler.async_step_configure_sensor_placement()
        mock_finish.assert_called_once()


@pytest.mark.asyncio
async def test_configure_sensor_placement_with_dimensions(handler) -> None:
    """Test sensor placement with dimensions and outside allowed sensors."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        dimensions={"width": 100, "length": 100, "height": 180, "unit": "in"},
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    # sensor.d1 is a dehumidifier (allowed outside)
    handler.flow.env_config_step1 = {
        "temperature_sensors": ["sensor.t1"],
        "dehumidifier_entities": ["sensor.d1"],
    }

    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "form"

    # Check schema bounds (min/max) if possible, but at least hit the code
    user_input = {
        "coord_sensor.t1_x": 50,
        "coord_sensor.t1_y": 50,
        "coord_sensor.t1_z": 50,
        "coord_sensor.d1_x": -10,
        "coord_sensor.d1_y": -10,
        "coord_sensor.d1_z": -10,
    }
    with patch.object(
        handler, "_async_save_and_finish", return_value={"type": "create_entry"}
    ):
        await handler.async_step_configure_sensor_placement(user_input)
        assert handler.flow.env_config_step1["sensor_coordinates"]["sensor.t1"] == {
            "x": 50,
            "y": 50,
            "z": 50,
        }


@pytest.mark.asyncio
async def test_save_and_finish(handler) -> None:
    """Test _async_save_and_finish."""
    gs = Growspace(id="gs1", name="GS1")
    env_config = {"temperature_sensors": ["sensor.t1"]}

    result = await handler._async_save_and_finish(gs, env_config)
    assert result["type"] == "create_entry"
    handler.config_entry.runtime_data.async_save.assert_called_once()
    handler.config_entry.runtime_data.async_refresh.assert_called_once()


@pytest.mark.asyncio
async def test_configure_dehumidifier_success(handler) -> None:
    """Test successful dehumidifier config submission."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"any": "config"}

    user_input = {}

    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ["day", "night"]:
            user_input[f"{stage}_{cycle}_on"] = 60.0
            user_input[f"{stage}_{cycle}_off"] = 55.0

    with patch.object(
        handler, "async_step_configure_sensor_placement", return_value={"type": "form"}
    ) as mock_next:
        await handler.async_step_configure_dehumidifier(user_input)
        assert "dehumidifier_thresholds" in handler.flow.env_config_step1
        mock_next.assert_called_once()


@pytest.mark.asyncio
async def test_configure_advanced_bayesian_success(handler) -> None:
    """Test successful advanced Bayesian config submission."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"bayesian_options": {"old": "val"}}

    user_input = {"test_option": "new_val"}
    parsed = {"test_option": "new_val"}

    with (
        patch.object(handler, "parse_advanced_bayesian_input", return_value=parsed),
        patch.object(
            handler,
            "async_step_configure_sensor_placement",
            return_value={"type": "form"},
        ),
    ):
        await handler.async_step_configure_advanced_bayesian(user_input)
        assert (
            handler.flow.env_config_step1["bayesian_options"]["test_option"]
            == "new_val"
        )
        assert handler.flow.env_config_step1["bayesian_options"]["old"] == "val"


@pytest.mark.asyncio
async def test_error_aborts(handler) -> None:
    """Test aborts when config context is missing."""
    handler.config_entry = None
    result = await handler.async_step_select_growspace_for_env()
    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"

    result = await handler.async_step_configure_environment()
    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"

    result = await handler.async_step_configure_dehumidifier()
    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"

    result = await handler.async_step_configure_advanced_bayesian()
    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"

    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_coordinator_missing_aborts(handler) -> None:
    """Test aborts when coordinator is missing."""
    handler.config_entry.runtime_data = None
    result = await handler.async_step_select_growspace_for_env()
    assert result["type"] == "abort"
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_configure_environment_sensor_groups_preservation(handler) -> None:
    """Test preservation of sensor groups during environment config."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensors": ["sensor.t1"],
        "sensor_groups": [{"name": "Group 1", "entities": ["sensor.t1"]}],
    }

    with patch.object(
        handler, "async_step_configure_sensor_placement", return_value={"type": "form"}
    ):
        await handler.async_step_configure_environment(user_input)
        assert "sensor_groups" in handler.flow.env_config_step1
        assert handler.flow.env_config_step1["sensor_groups"][0]["name"] == "Group 1"


@pytest.mark.asyncio
async def test_configure_sensor_placement_growspace_not_found(handler) -> None:
    """Test sensor placement when growspace is missing."""
    handler.config_entry.runtime_data.growspaces = {}
    handler.flow.selected_growspace_id = "missing"
    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_configure_sensor_placement_pumps(handler) -> None:
    """Test sensor placement with irrigation pumps."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        irrigation_config=MagicMock(
            irrigation_pump_entity="switch.pump1", drain_pump_entity="switch.drain1"
        ),
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {}

    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "form"
    assert "coord_switch.pump1_x" in result["data_schema"].schema
    assert "coord_switch.drain1_x" in result["data_schema"].schema


@pytest.mark.asyncio
async def test_configure_sensor_placement_unit_fallback(handler) -> None:
    """Test fallback to 'cm' when unit is invalid."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        dimensions={"width": 100, "length": 100, "height": 180, "unit": 123},  # Not str
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"temperature_sensors": ["sensor.t1"]}

    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_clean_input_list_fallback(handler) -> None:
    """Test clean_input with list fallback."""
    user_input = {"light_sensors": None}
    cleaned = handler.clean_input(user_input)
    assert cleaned["light_sensors"] == []


@pytest.mark.asyncio
async def test_configure_advanced_bayesian_opts_none(handler) -> None:
    """Test advanced Bayesian config when opts is not a dict."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"bayesian_options": None}

    user_input = {"test": "val"}
    with (
        patch.object(
            handler, "parse_advanced_bayesian_input", return_value={"test": "val"}
        ),
        patch.object(
            handler,
            "async_step_configure_sensor_placement",
            return_value={"type": "form"},
        ),
    ):
        await handler.async_step_configure_advanced_bayesian(user_input)
        assert handler.flow.env_config_step1["bayesian_options"] == {"test": "val"}


@pytest.mark.asyncio
async def test_get_dehumidifier_schema(handler) -> None:
    """Test dehumidifier schema generation."""
    thresholds = {"stage1": {"day": {"on": 1.0, "off": 0.8}}}
    schema = handler.get_dehumidifier_schema(thresholds)
    assert isinstance(schema, vol.Schema)


@pytest.mark.asyncio
async def test_parse_advanced_bayesian_input_failure(handler) -> None:
    """Test advanced Bayesian input parsing failures."""
    # Line 1031-1033: No brackets
    with pytest.raises(ValueError, match="Invalid tuple string format"):
        handler.parse_advanced_bayesian_input({"key": "0.9, 0.1"})

    # Line 1037-1038: Starts with ( but not a tuple (e.g. list inside brackets - wait, literal_eval will parse it)
    # Actually, if it starts with ( and ends with ), literal_eval will try to parse it.
    # If it parses to something that is NOT a tuple, it should raise TypeError.
    # Let's try "( [0.9, 0.1] )" -> literal_eval might parse this as a tuple containing a list? No.
    # Let's try "(1)" -> literal_eval parses as int.
    with pytest.raises(TypeError, match="Parsed value is not a tuple"):
        handler.parse_advanced_bayesian_input({"key": "(1)"})

    # Line 1042-1043: Non-string value (already tuple)
    result = handler.parse_advanced_bayesian_input({"key": (0.9, 0.1)})
    assert result["key"] == (0.9, 0.1)


@pytest.mark.asyncio
async def test_add_lst_offset_to_schema(handler) -> None:
    """Test LST offset schema addition."""
    schema_dict = {}

    opts = {CONF_TEMP_SENSOR: "s1", CONF_HUMIDITY_SENSOR: "s2"}
    # Line 652 path
    handler._add_lst_offset_to_schema(schema_dict, opts)
    assert any("lst_offset" in str(k) for k in schema_dict)


@pytest.mark.asyncio
async def test_configure_environment_no_existing_config(handler) -> None:
    """Test environment config when no config exists yet."""
    gs = Growspace(id="gs1", name="GS1", environment_config=None)
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    # Line 118 path
    result = await handler.async_step_configure_environment()
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_async_step_configure_dehumidifier_growspace_not_found(handler) -> None:
    """Test dehumidifier step when growspace is missing."""
    handler.config_entry.runtime_data.growspaces = {}
    handler.flow.selected_growspace_id = "missing"
    result = await handler.async_step_configure_dehumidifier()
    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_async_step_configure_dehumidifier_to_advanced(handler) -> None:
    """Test dehumidifier step transitioning to advanced."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"configure_advanced": True}

    user_input = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ["day", "night"]:
            user_input[f"{stage}_{cycle}_on"] = 1.0
            user_input[f"{stage}_{cycle}_off"] = 0.8

    with patch.object(
        handler, "async_step_configure_advanced_bayesian", return_value={"type": "form"}
    ) as mock_next:
        # Line 237-238 path
        await handler.async_step_configure_dehumidifier(user_input)
        mock_next.assert_called_once()


@pytest.mark.asyncio
async def test_clean_input_string_to_list(handler) -> None:
    """Test clean_input converting string to list."""
    # Line 522 path
    user_input = {"light_sensors": "sensor.l1"}
    cleaned = handler.clean_input(user_input)
    assert cleaned["light_sensors"] == ["sensor.l1"]


@pytest.mark.asyncio
async def test_async_step_configure_advanced_bayesian_growspace_not_found(
    handler,
) -> None:
    """Test advanced Bayesian step when growspace is missing."""
    handler.config_entry.runtime_data.growspaces = {}
    handler.flow.selected_growspace_id = "missing"
    result = await handler.async_step_configure_advanced_bayesian()
    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


async def test_select_growspace_no_entry_abort(handler) -> None:
    handler.config_entry = None
    result = await handler.async_step_select_growspace_for_env()
    assert result["type"] == "abort"


async def test_configure_environment_no_coord_abort(handler) -> None:
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_environment()
    assert result["type"] == "abort"


async def test_async_step_configure_dehumidifier_no_coord_abort(handler) -> None:
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_dehumidifier()
    assert result["type"] == "abort"


async def test_async_step_configure_advanced_bayesian_no_coord_abort(handler) -> None:
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_advanced_bayesian()
    assert result["type"] == "abort"


async def test_async_step_configure_sensor_placement_v_no_coord_abort(handler) -> None:
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "abort"


@pytest.mark.asyncio
async def test_configure_environment_growspace_not_found(handler) -> None:
    """Test environment config when growspace is not found. Covers line 97."""
    handler.config_entry.runtime_data.growspaces = {}
    handler.flow.selected_growspace_id = "missing"
    result = await handler.async_step_configure_environment()
    assert result["type"] == "abort"
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_async_step_configure_dehumidifier_show_form(handler) -> None:
    """Test dehumidifier step shows form. Covers line 245."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    result = await handler.async_step_configure_dehumidifier(user_input=None)
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_async_step_configure_advanced_bayesian_show_form(handler) -> None:
    """Test advanced Bayesian step shows form. Covers line 303."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {}
    result = await handler.async_step_configure_advanced_bayesian(user_input=None)
    assert result["type"] == "form"


@pytest.mark.asyncio
async def test_configure_sensor_placement_filtering_edge_case(handler) -> None:
    """Test sensor placement filtering with non-string values. Covers line 353."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    # None in list should be filtered out
    handler.flow.env_config_step1 = {"temperature_sensors": [None, "sensor.t1"]}
    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "form"
    assert "coord_sensor.t1_x" in result["data_schema"].schema


@pytest.mark.asyncio
async def test_configure_sensor_placement_with_tanks_full(handler) -> None:
    """Test sensor placement with irrigation tanks. Covers lines 363-367."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {
        "irrigation_tanks": [{"sensor_entity": "sensor.tank1"}]
    }
    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == "form"
    assert "coord_sensor.tank1_x" in result["data_schema"].schema


@pytest.mark.asyncio
async def test_clean_input_clear_optional_fields(handler) -> None:
    """Test clean_input clearing optional fields. Covers line 531."""

    user_input = {CONF_SOIL_MOISTURE_SENSOR: ""}
    cleaned = handler.clean_input(user_input)
    assert cleaned[CONF_SOIL_MOISTURE_SENSOR] is None


@pytest.mark.asyncio
async def test_parse_advanced_bayesian_input_success(handler) -> None:
    """Test successful parsing of advanced Bayesian input. Covers line 1040."""
    user_input = {"key": "(0.9, 0.1)"}
    result = handler.parse_advanced_bayesian_input(user_input)
    assert result["key"] == (0.9, 0.1)
