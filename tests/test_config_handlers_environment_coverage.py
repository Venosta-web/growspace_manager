"""Coverage-focused tests for EnvironmentConfigHandler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.config_handlers.environment_config_handler import (
    EnvironmentConfigHandler,
)
from custom_components.growspace_manager.const import DEHUMIDIFIER_STAGES
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

    with patch.object(handler, "parse_advanced_bayesian_input", return_value=parsed):
        with patch.object(
            handler,
            "async_step_configure_sensor_placement",
            return_value={"type": "form"},
        ):
            await handler.async_step_configure_advanced_bayesian(user_input)
            assert (
                handler.flow.env_config_step1["bayesian_options"]["test_option"]
                == "new_val"
            )
            assert handler.flow.env_config_step1["bayesian_options"]["old"] == "val"
