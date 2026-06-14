"""Coverage-focused tests for EnvironmentConfigHandler."""

from dataclasses import asdict
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_handlers.environment_config_handler import (
    EnvironmentConfigHandler,
)
from custom_components.growspace_manager.const import (
    CONF_CONFIGURE_FAN_CONTROLLER,
    CONF_HUMIDITY_SENSOR,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_TEMP_SENSOR,
    DEHUMIDIFIER_STAGES,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationTank,
    TankWaterHistory,
)
from homeassistant.config_entries import ConfigFlow
from homeassistant.data_entry_flow import FlowResultType


class MockFlow(ConfigFlow):
    """Mock flow."""

    def __init__(self) -> None:
        """Initialize mock flow."""
        super().__init__()
        self.selected_growspace_id = None
        self.env_config_step1 = {}


@pytest.fixture
def handler():
    """EnvironmentConfigHandler fixture with Facade-aware mocks."""
    flow = MockFlow()
    handler = EnvironmentConfigHandler(flow)

    # 1. Setup Coordinator Facade
    coordinator = MagicMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh = AsyncMock()

    # 2. Setup Sub-Services/Repos
    service_mock = MagicMock()
    service_mock.save = AsyncMock()  # This was missing and causing TypeErrors
    coordinator._data_repository = service_mock

    # 3. Default Growspace setup to avoid asdict() errors
    default_gs = Growspace(id="gs1", name="GS1", environment_config=EnvironmentConfig())
    service_mock.get_growspace.return_value = default_gs
    coordinator.growspaces = {"gs1": default_gs}

    # 4. Wire sub-facades so handlers can call coordinator.services.growspaces.*
    gs_facade = MagicMock()
    gs_facade.get_growspace.return_value = default_gs
    gs_facade.get_sorted_growspace_options.return_value = [("gs1", "GS1")]
    gs_facade.update_irrigation_config = AsyncMock()
    gs_facade.configure_tank = AsyncMock()

    coordinator.services = MagicMock()
    coordinator.services.save = AsyncMock()
    coordinator.services.growspaces = gs_facade

    handler.config_entry = MagicMock()
    handler.config_entry.runtime_data = coordinator
    handler.hass = MagicMock()

    return handler


@pytest.mark.asyncio
async def test_select_growspace_for_env_success(handler) -> None:
    """Test selecting a growspace for environment config."""
    handler.config_entry.runtime_data.services.growspaces.get_sorted_growspace_options.return_value = [
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
    # Ensure the correct path in the facade is mocked
    handler.config_entry.runtime_data.services.growspaces.get_sorted_growspace_options.return_value = []

    result = await handler.async_step_select_growspace_for_env()

    # Use the enum for better stability
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_growspaces"


@pytest.mark.asyncio
async def test_configure_environment_with_tanks(handler) -> None:
    """Test environment config with irrigation tanks."""
    # We must use a real Growspace object because the code calls asdict()
    gs = Growspace(
        id="gs1",
        name="GS1",
        environment_config=EnvironmentConfig(
            irrigation_tanks=[
                IrrigationTank(sensor_entity="sensor.tank1", warning_level=20.0)
            ]
        ),
    )

    # Mock the return value for the specific call the handler makes
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        gs
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    result = await handler.async_step_configure_environment()
    assert result["type"] == FlowResultType.FORM


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

    # Code calls await coordinator.async_commit()
    result = await handler._async_save_and_finish(gs, env_config)  # noqa: SLF001

    assert result["type"] == FlowResultType.CREATE_ENTRY
    handler.config_entry.runtime_data.services.save.assert_awaited_once()


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
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        None
    )
    handler.config_entry.runtime_data.growspaces = {}
    handler.flow.selected_growspace_id = "missing"

    result = await handler.async_step_configure_sensor_placement()

    # Now it should actually fail to find the growspace and abort
    assert result["type"] == FlowResultType.ABORT
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
        environment_config=EnvironmentConfig(),
    )
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        gs
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    handler.flow.env_config_step1 = {"temperature_sensors": ["sensor.temp1"]}

    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == FlowResultType.FORM
    assert "coord_switch.pump1_x" in result["data_schema"].schema
    assert "coord_switch.drain1_x" in result["data_schema"].schema


@pytest.mark.asyncio
async def test_configure_sensor_placement_unit_fallback(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test fallback to 'cm' when unit is invalid."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        dimensions={"width": 100, "length": 100, "height": 180, "unit": 123},  # Not str
    )
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        gs
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
    handler._add_lst_offset_to_schema(schema_dict, opts)  # noqa: SLF001
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
    # Ensure both paths to find growspaces return nothing
    handler.config_entry.runtime_data.growspaces = {}
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        None
    )

    handler.flow.selected_growspace_id = "missing"
    result = await handler.async_step_configure_dehumidifier()

    assert result["type"] == FlowResultType.ABORT
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
    # CRITICAL: Override the default mock return
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        None
    )
    handler.flow.selected_growspace_id = "missing"

    result = await handler.async_step_configure_advanced_bayesian()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


async def test_select_growspace_no_entry_abort(handler) -> None:
    """Test select growspace step aborts when config entry is missing."""
    handler.config_entry = None
    result = await handler.async_step_select_growspace_for_env()
    assert result["type"] == FlowResultType.ABORT


async def test_configure_environment_no_coord_abort(handler) -> None:
    """Test configure environment step aborts when coordinator is missing."""
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_environment()
    assert result["type"] == FlowResultType.ABORT


async def test_async_step_configure_dehumidifier_no_coord_abort(handler) -> None:
    """Test configure dehumidifier step aborts when coordinator is missing."""
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_dehumidifier()
    assert result["type"] == FlowResultType.ABORT


async def test_async_step_configure_advanced_bayesian_no_coord_abort(handler) -> None:
    """Test configure advanced bayesian step aborts when coordinator is missing."""
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_advanced_bayesian()
    assert result["type"] == FlowResultType.ABORT


async def test_async_step_configure_sensor_placement_v_no_coord_abort(handler) -> None:
    """Test configure sensor placement step aborts when coordinator is missing."""
    handler.config_entry.runtime_data = None
    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == FlowResultType.ABORT


@pytest.mark.asyncio
async def test_configure_environment_growspace_not_found(handler) -> None:
    """Test environment config when growspace is not found."""
    # CRITICAL: Override the default mock return
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        None
    )
    handler.flow.selected_growspace_id = "missing"

    result = await handler.async_step_configure_environment()

    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_async_step_configure_dehumidifier_show_form(handler) -> None:
    """Test dehumidifier step shows form."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    result = await handler.async_step_configure_dehumidifier(user_input=None)
    assert result["type"] == FlowResultType.FORM


@pytest.mark.asyncio
async def test_async_step_configure_advanced_bayesian_show_form(handler) -> None:
    """Test advanced Bayesian step shows form. Covers line 303."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {}
    result = await handler.async_step_configure_advanced_bayesian(user_input=None)
    assert result["type"] == FlowResultType.FORM


@pytest.mark.asyncio
async def test_configure_sensor_placement_filtering_edge_case(handler) -> None:
    """Test sensor placement filtering with non-string values. Covers line 353."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    # None in list should be filtered out
    handler.flow.env_config_step1 = {"temperature_sensors": [None, "sensor.t1"]}
    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == FlowResultType.FORM
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
    assert result["type"] == FlowResultType.FORM
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


@pytest.mark.asyncio
async def test_collect_sensors_to_configure_empty_after_filtering(handler) -> None:
    """Test _collect_sensors_to_configure when filtering results in empty list."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        gs
    )
    handler.flow.selected_growspace_id = "gs1"

    # Provide an invalid type in a list to trigger filtering logic
    handler.flow.env_config_step1 = {"temperature_sensors": [123]}

    result = await handler.async_step_configure_sensor_placement()

    # If no valid sensors are left, it skips to finish
    assert result["type"] == FlowResultType.CREATE_ENTRY
    handler.config_entry.runtime_data.services.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_configure_environment_with_tank_volume_liters(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test async_step_configure_environment with a tank that has volume_liters set (environment_config_handler.py:128)."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        environment_config=EnvironmentConfig(
            irrigation_tanks=[
                IrrigationTank(
                    sensor_entity="sensor.tank1",
                    warning_level=25.0,
                    volume_liters=200.0,
                )
            ]
        ),
    )
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        gs
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    result = await handler.async_step_configure_environment()
    assert result["type"] == FlowResultType.FORM


@pytest.mark.asyncio
async def test_configure_environment_no_environment_config(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test configure_environment when growspace has no environment_config set. Covers line 185."""
    gs = Growspace(
        id="gs1",
        name="GS1",
        environment_config=None,
    )
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = (
        gs
    )
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    result = await handler.async_step_configure_environment()
    assert result["type"] == FlowResultType.FORM


def test_process_irrigation_tanks_comprehensive(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test _process_irrigation_tanks logic under various conditions. Covers lines 251-258 and 261-307."""
    # Setup some state for self.hass.states.get lookup
    mock_state = MagicMock()
    mock_state.attributes = {"friendly_name": "My Custom Tank"}

    # Mock handler.hass.states.get
    handler.hass.states.get = MagicMock(
        side_effect=lambda entity: mock_state if entity == "sensor.tank_1" else None
    )

    # Mock existing tanks - one object (IrrigationTank) and one dict to cover lines 251-258 and 281-296
    history_obj = TankWaterHistory(
        snapshots=[{"timestamp": "2026-05-19", "level_pct": 50.0}], events=[]
    )
    tank_obj = IrrigationTank(
        sensor_entity="sensor.tank_1",
        warning_level=20.0,
        volume_liters=100.0,
    )
    tank_obj.water_history = history_obj
    tank_obj.last_recorded_level = 50.0
    tank_obj.peak_level = 95.0

    tank_dict = {
        "sensor_entity": "sensor.tank_2",
        "warning_level": 25.0,
        "volume_liters": 150.0,
        "water_history": "raw_history_string_or_dict",
        "last_recorded_level": 40.0,
        "peak_level": 85.0,
    }

    existing_tanks = [tank_obj, tank_dict]

    # Call _process_irrigation_tanks
    env_config = {
        "irrigation_tank_sensors": ["sensor.tank_1", "sensor.tank_2", "sensor.tank_3"],
        "irrigation_tank_warning_level": 35.0,
        "irrigation_tank_volume": 120.0,
    }

    result = handler._process_irrigation_tanks(  # noqa: SLF001
        env_config, existing_tanks=existing_tanks
    )

    # Validate output
    assert "irrigation_tank_sensors" not in result
    assert "irrigation_tank_warning_level" not in result
    assert "irrigation_tank_volume" not in result

    tanks = result["irrigation_tanks"]
    assert len(tanks) == 3

    # Tank 1 (state object exists, friendly name lookup used, existing was object)
    t1 = tanks[0]
    assert t1["sensor_entity"] == "sensor.tank_1"
    assert t1["name"] == "My Custom Tank"
    assert t1["warning_level"] == 35.0
    assert t1["volume_liters"] == 120.0
    assert t1["water_history"] == asdict(history_obj)
    assert t1["last_recorded_level"] == 50.0
    assert t1["peak_level"] == 95.0

    # Tank 2 (no state object, friendly name fallback used, existing was dict)
    t2 = tanks[1]
    assert t2["sensor_entity"] == "sensor.tank_2"
    assert t2["name"] == "Tank 2"
    assert t2["warning_level"] == 35.0
    assert t2["volume_liters"] == 120.0
    assert t2["water_history"] == "raw_history_string_or_dict"
    assert t2["last_recorded_level"] == 40.0
    assert t2["peak_level"] == 85.0

    # Tank 3 (new tank, no existing runtime data)
    t3 = tanks[2]
    assert t3["sensor_entity"] == "sensor.tank_3"
    assert t3["name"] == "Tank 3"
    assert t3["warning_level"] == 35.0
    assert t3["volume_liters"] == 120.0
    assert "water_history" not in t3
    assert "last_recorded_level" not in t3
    assert "peak_level" not in t3


def test_process_irrigation_tanks_empty(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test _process_irrigation_tanks when tank_sensors list is empty."""
    env_config = {
        "irrigation_tank_sensors": [],
    }
    result = handler._process_irrigation_tanks(env_config)  # noqa: SLF001
    assert result["irrigation_tanks"] == []


def test_lst_offset_default_for_dry_and_cure_stages(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test _add_lst_offset_to_schema offset defaults across different stages. Covers line 887."""
    # Test for "dry" stage
    schema_dict = {}
    growspace_options = {
        "temperature_sensors": ["sensor.temp"],
        "humidity_sensors": ["sensor.humid"],
    }
    handler._add_lst_offset_to_schema(schema_dict, growspace_options, stage="dry")  # noqa: SLF001
    lst_key = None
    for k in schema_dict:
        if k.schema == "lst_offset":
            lst_key = k
            break
    assert lst_key is not None
    assert lst_key.default() == 0.0

    # Test for "cure" stage
    schema_dict = {}
    handler._add_lst_offset_to_schema(schema_dict, growspace_options, stage="cure")  # noqa: SLF001
    lst_key = None
    for k in schema_dict:
        if k.schema == "lst_offset":
            lst_key = k
            break
    assert lst_key is not None
    assert lst_key.default() == 0.0

    # Test for other stage e.g. "veg" (should default to -2.0)
    schema_dict = {}
    handler._add_lst_offset_to_schema(schema_dict, growspace_options, stage="veg")  # noqa: SLF001
    lst_key = None
    for k in schema_dict:
        if k.schema == "lst_offset":
            lst_key = k
            break
    assert lst_key is not None
    assert lst_key.default() == -2.0




@pytest.mark.asyncio
async def test_configure_fan_controller_branch(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test CONF_CONFIGURE_FAN_CONTROLLER branches to fan_controller_handler."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensors": ["sensor.t1"],
        "humidity_sensors": ["sensor.h1"],
        CONF_CONFIGURE_FAN_CONTROLLER: True,
    }

    mock_fan_handler = MagicMock()
    mock_fan_handler.async_step_configure_fan_controller = AsyncMock(
        return_value={"type": "form"}
    )
    handler.flow.fan_controller_handler = mock_fan_handler

    result = await handler.async_step_configure_environment(user_input)
    mock_fan_handler.async_step_configure_fan_controller.assert_called_once()
    assert result == {"type": "form"}


@pytest.mark.asyncio
async def test_clean_input_optional_field_present(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test clean_input with an optional field present and others missing. Covers line 1070-1072."""
    user_input = {CONF_SOIL_MOISTURE_SENSOR: "sensor.soil_moisture"}
    cleaned = handler.clean_input(user_input)
    assert cleaned[CONF_SOIL_MOISTURE_SENSOR] == "sensor.soil_moisture"


@pytest.mark.asyncio
async def test_configure_sensor_placement_missing_coord_components(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test sensor placement with incomplete coordinate components. Covers line 813."""
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {
        "temperature_sensors": ["sensor.t1"],
    }
    user_input = {
        "coord_sensor.t1_y": 50,
        "coord_sensor.t1_z": 50,
    }
    with patch.object(
        handler, "_async_save_and_finish", return_value={"type": "create_entry"}
    ):
        await handler.async_step_configure_sensor_placement(user_input)
        assert "sensor.t1" not in handler.flow.env_config_step1["sensor_coordinates"]


@pytest.mark.asyncio
async def test_configure_sensor_placement_tank_sensor_invalid_type(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test sensor placement with irrigation tank having invalid sensor type. Covers line 895."""
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {
        "irrigation_tanks": [
            {"sensor_entity": 12345},  # invalid type, not a string
            {"sensor_entity": "sensor.tank1"},
        ]
    }
    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == FlowResultType.FORM
    assert "coord_sensor.tank1_x" in result["data_schema"].schema
    assert "coord_12345_x" not in result["data_schema"].schema


@pytest.mark.asyncio
async def test_configure_sensor_placement_no_irrigation_config(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test sensor placement with growspace having no irrigation config. Covers line 900."""
    gs = handler.config_entry.runtime_data.growspaces["gs1"]
    gs.irrigation_config = None  # Force it to None
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"temperature_sensors": ["sensor.t1"]}

    result = await handler.async_step_configure_sensor_placement()
    assert result["type"] == FlowResultType.FORM
    assert "coord_sensor.t1_x" in result["data_schema"].schema


@pytest.mark.asyncio
async def test_process_irrigation_tanks_edge_cases(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test _process_irrigation_tanks logic with missing/None fields. Covers lines 262->256, 302->307, 307->309, 309->311."""
    handler.hass.states.get = MagicMock(return_value=None)

    # tank_invalid triggers line 262->256 branch (missing sensor_entity key/attr)
    tank_invalid = {"warning_level": 25.0}

    # tank_none_fields triggers lines 302->307, 307->309, 309->311 branches (None fields)
    tank_none_fields = {
        "sensor_entity": "sensor.tank_none",
        "water_history": None,
        "last_recorded_level": None,
        "peak_level": None,
    }

    existing_tanks = [tank_invalid, tank_none_fields]

    env_config = {
        "irrigation_tank_sensors": ["sensor.tank_none"],
        "irrigation_tank_warning_level": 35.0,
        "irrigation_tank_volume": 120.0,
    }

    result = handler._process_irrigation_tanks(  # noqa: SLF001
        env_config, existing_tanks=existing_tanks
    )

    tanks = result["irrigation_tanks"]
    assert len(tanks) == 1
    t = tanks[0]
    assert t["sensor_entity"] == "sensor.tank_none"
    assert "water_history" not in t
    assert "last_recorded_level" not in t
    assert "peak_level" not in t


# ---------------------------------------------------------------------------
# async_step_configure_humidifier + get_humidifier_schema — missing coverage
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_configure_humidifier_branch(handler: EnvironmentConfigHandler) -> None:
    """Test branching to humidifier config when configure_humidifier is True."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensors": ["sensor.t1"],
        "humidity_sensors": ["sensor.h1"],
        "configure_humidifier": True,
    }

    with patch.object(
        handler, "async_step_configure_humidifier", return_value={"type": "form"}
    ) as mock_step:
        await handler.async_step_configure_environment(user_input)
        mock_step.assert_called_once()


@pytest.mark.asyncio
async def test_configure_humidifier_show_form(handler: EnvironmentConfigHandler) -> None:
    """Test async_step_configure_humidifier shows form when user_input is None."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"

    result = await handler.async_step_configure_humidifier()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_humidifier"


@pytest.mark.asyncio
async def test_configure_humidifier_abort_missing_coordinator(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test async_step_configure_humidifier aborts when config_entry is None."""
    handler.config_entry = None
    result = await handler.async_step_configure_humidifier()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_configure_humidifier_abort_growspace_not_found(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test async_step_configure_humidifier aborts when growspace is missing."""
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = None
    handler.flow.selected_growspace_id = "missing"

    result = await handler.async_step_configure_humidifier()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_configure_humidifier_success_to_sensor_placement(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test humidifier submission routes to sensor placement when configure_advanced is not set."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"any": "config"}

    user_input: dict[str, Any] = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ["day", "night"]:
            user_input[f"{stage}_{cycle}_on"] = 0.8
            user_input[f"{stage}_{cycle}_off"] = 0.6

    with patch.object(
        handler, "async_step_configure_sensor_placement", return_value={"type": "form"}
    ) as mock_next:
        await handler.async_step_configure_humidifier(user_input)
        assert "humidifier_thresholds" in handler.flow.env_config_step1
        mock_next.assert_called_once()


@pytest.mark.asyncio
async def test_configure_humidifier_to_advanced_bayesian(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test humidifier submission routes to advanced Bayesian when configure_advanced is set."""
    gs = Growspace(id="gs1", name="GS1")
    handler.config_entry.runtime_data.growspaces = {"gs1": gs}
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.env_config_step1 = {"configure_advanced": True}

    user_input: dict[str, Any] = {}
    for stage in DEHUMIDIFIER_STAGES:
        for cycle in ["day", "night"]:
            user_input[f"{stage}_{cycle}_on"] = 0.8
            user_input[f"{stage}_{cycle}_off"] = 0.6

    with patch.object(
        handler,
        "async_step_configure_advanced_bayesian",
        return_value={"type": "form"},
    ) as mock_next:
        await handler.async_step_configure_humidifier(user_input)
        assert "humidifier_thresholds" in handler.flow.env_config_step1
        mock_next.assert_called_once()


def test_get_humidifier_schema(handler: EnvironmentConfigHandler) -> None:
    """Test get_humidifier_schema returns a valid voluptuous Schema."""
    schema = handler.get_humidifier_schema({})
    assert isinstance(schema, vol.Schema)

    # Confirm schema is populated (one key per stage × cycle × on/off)
    keys = [str(k.schema) for k in schema.schema]
    assert any("_on" in k for k in keys)
    assert any("_off" in k for k in keys)


def test_get_humidifier_schema_with_existing_thresholds(
    handler: EnvironmentConfigHandler,
) -> None:
    """Test get_humidifier_schema uses existing thresholds as defaults."""
    thresholds = {
        "veg": {"day": {"on": 1.5, "off": 1.2}, "night": {"on": 1.3, "off": 1.0}},
    }
    schema = handler.get_humidifier_schema(thresholds)
    assert isinstance(schema, vol.Schema)
