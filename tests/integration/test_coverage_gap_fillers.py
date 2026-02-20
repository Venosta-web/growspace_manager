from unittest.mock import AsyncMock, MagicMock, Mock, patch

from custom_components.growspace_manager.config_handlers.environment_config_handler import (
    EnvironmentConfigHandler,
)
from custom_components.growspace_manager.config_handlers.irrigation_config_handler import (
    IrrigationConfigHandler,
)
from custom_components.growspace_manager.const import (
    ATTR_AMOUNT,
    ATTR_COL,
    ATTR_GROWSPACE_ID,
    ATTR_PHENOTYPE,
    ATTR_ROW,
    ATTR_STRAIN,
    CONF_LIGHT_SENSORS,
)
from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)

# Direct imports of the functions we want to test
from custom_components.growspace_manager.services.plant import handle_add_plants
from custom_components.growspace_manager.websocket import _merge_logbook_event
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant


async def test_add_plants_with_base_phenotype(hass: HomeAssistant) -> None:
    """Test handle_add_plants with base_phenotype to cover the specific branch."""
    # Mocks
    mock_coordinator = Mock()
    mock_coordinator.growspaces = {"gs1": Mock()}
    mock_coordinator.validator = Mock()
    mock_coordinator.validator.find_first_available_position.return_value = (1, 1)
    mock_coordinator._plant_service = MagicMock()
    mock_coordinator._plant_service.add_plant = AsyncMock()

    mock_strain_library = Mock()

    # Service Call Data
    data = {
        ATTR_GROWSPACE_ID: "gs1",
        ATTR_STRAIN: "Blue Dream",
        ATTR_AMOUNT: 1,
        ATTR_PHENOTYPE: "Bluey",
        ATTR_ROW: 1,
        ATTR_COL: 1,
    }
    # Use simple Mock for call to guarantee behavior
    call = Mock()
    call.data = data

    # Execute
    await handle_add_plants(hass, mock_coordinator, mock_strain_library, call)

    # Verify
    mock_coordinator._plant_service.add_plant.assert_called_once()
    call_kwargs = mock_coordinator._plant_service.add_plant.call_args.kwargs

    # Check that 'Bluey #1' was passed as phenotype
    assert call_kwargs["phenotype"] == "Bluey #1"


def test_websocket_merge_event_log_exception() -> None:
    """Test exception handling in _merge_logbook_event."""
    # Setup data that passes the IF conditions but fails inside the TRY block
    # Logic requires:
    # category=alert, growspace_id matches, sensor_type matches, severity present

    last_evt = {
        "category": "alert",
        "growspace_id": "gs1",
        "sensor_type": "temp",
        "severity": 1.0,
        "start_time": "INVALID_DATE_STRING",  # This causes ValueError in fromisoformat
    }

    data_dict = {
        "category": "alert",
        "growspace_id": "gs1",
        "sensor_type": "temp",
        "severity": 1.0,
        "end_time": "2023-01-01T12:00:00",
    }

    events_list = [last_evt]

    # Execute - should catch Exception and return False (or pass silently if return is implicit None/False)
    # The function returns True if merged, False otherwise.
    # Exception block does 'pass', then returns False at end of function.

    result = _merge_logbook_event(events_list, data_dict, None)

    assert result is False


async def test_irrigation_config_handler_abort_missing_coordinator(
    hass: HomeAssistant,
) -> None:
    """Test IrrigationConfigHandler aborts when coordinator is missing."""
    mock_flow = Mock()
    mock_flow.hass = hass
    mock_config_entry = Mock()
    mock_config_entry.runtime_data = None  # Simulate missing coordinator
    mock_flow.config_entry = mock_config_entry

    mock_flow.async_abort = Mock(return_value="ABORT")

    handler = IrrigationConfigHandler(flow=mock_flow)

    # Test step 1
    result = await handler.async_step_configure_irrigation()
    assert result == "ABORT"
    mock_flow.async_abort.assert_called_with(reason="setup_error")

    # Test step 2
    mock_flow.async_abort.reset_mock()
    result = await handler.async_step_irrigation_overview()
    assert result == "ABORT"
    mock_flow.async_abort.assert_called_with(reason="setup_error")


async def test_environment_config_handler_abort_missing_coordinator(
    hass: HomeAssistant,
) -> None:
    """Test EnvironmentConfigHandler aborts when coordinator is missing."""
    mock_flow = Mock()
    mock_flow.hass = hass
    mock_config_entry = Mock()
    mock_config_entry.runtime_data = None  # Simulate missing coordinator
    mock_flow.config_entry = mock_config_entry

    mock_flow.async_abort = Mock(return_value="ABORT")

    handler = EnvironmentConfigHandler(flow=mock_flow)

    # Test step 1
    result = await handler.async_step_select_growspace_for_env()
    assert result == "ABORT"
    mock_flow.async_abort.assert_called_with(reason="setup_error")


def test_environment_config_handler_clean_input(hass: HomeAssistant) -> None:
    """Test EnvironmentConfigHandler clean_input specifically for list handling."""
    mock_flow = Mock()
    mock_flow.hass = hass
    mock_flow.config_entry = Mock()
    handler = EnvironmentConfigHandler(flow=mock_flow)

    # Test 1: List field as list
    input_data = {
        CONF_LIGHT_SENSORS: ["light.1", "light.2"],
        "other": "value",
    }
    cleaned = handler.clean_input(input_data)
    assert cleaned[CONF_LIGHT_SENSORS] == ["light.1", "light.2"]

    # Test 2: List field as single value (backward compat path)
    input_data = {
        CONF_LIGHT_SENSORS: "light.single",
    }
    cleaned = handler.clean_input(input_data)
    assert cleaned[CONF_LIGHT_SENSORS] == ["light.single"]

    # Test 3: List field empty
    input_data = {
        CONF_LIGHT_SENSORS: [],
    }
    cleaned = handler.clean_input(input_data)
    assert cleaned[CONF_LIGHT_SENSORS] == []


async def test_dehumidifier_coordinator_control_exceptions(hass: HomeAssistant) -> None:
    """Test _control_dehumidifier exception handling and domain fallback."""
    coordinator = Mock(spec=DehumidifierCoordinator)
    coordinator.hass = hass
    coordinator.dehumidifier_entities = [
        "light.fake_dehumidifier"
    ]  # Unknown domain -> homeassistant
    coordinator.exhaust_fan_entities = []
    # Bind the method to the mock object so self works
    coordinator._control_dehumidifier = (
        DehumidifierCoordinator._control_dehumidifier.__get__(
            coordinator, DehumidifierCoordinator
        )
    )

    # Test 1: Fallback domain
    with patch(
        "homeassistant.core.ServiceRegistry.async_call", new_callable=AsyncMock
    ) as mock_call:
        await coordinator._control_dehumidifier(True)
        # Should call homeassistant.turn_on because 'light' is not in allowed list?
        # Allowed: switch, humidifier, fan, input_boolean
        mock_call.assert_called_with(
            "homeassistant",
            "turn_on",
            {"entity_id": "light.fake_dehumidifier"},
            blocking=False,
        )

    # Test 2: Exception handling
    coordinator.dehumidifier_entities = ["switch.valid"]
    with patch(
        "homeassistant.core.ServiceRegistry.async_call", side_effect=Exception("Boom")
    ) as mock_call:
        # Should not raise
        await coordinator._control_dehumidifier(True)


def test_dehumidifier_coordinator_vpd_parsing(hass: HomeAssistant) -> None:
    """Test _get_current_vpd parsing logic."""
    coordinator = Mock(spec=DehumidifierCoordinator)
    coordinator.hass = hass
    coordinator.vpd_sensor = "sensor.vpd"
    coordinator._get_current_vpd = DehumidifierCoordinator._get_current_vpd.__get__(
        coordinator, DehumidifierCoordinator
    )

    # Test 1: State Missing
    hass.states.async_set("sensor.vpd", STATE_UNKNOWN)
    assert coordinator._get_current_vpd() is None

    # Test 2: ValueError
    hass.states.async_set("sensor.vpd", "invalid_float")
    assert coordinator._get_current_vpd() is None

    # Test 3: Valid
    hass.states.async_set("sensor.vpd", "1.5")
    assert coordinator._get_current_vpd() == 1.5


def test_dehumidifier_coordinator_is_day_logic(hass: HomeAssistant) -> None:
    """Test _determine_is_day logic including ValueError fallback."""
    coordinator = Mock(spec=DehumidifierCoordinator)
    coordinator.hass = hass
    coordinator.light_sensors = ["sensor.light"]
    coordinator._determine_is_day = DehumidifierCoordinator._determine_is_day.__get__(
        coordinator, DehumidifierCoordinator
    )

    # Test 1: Float value > 0
    hass.states.async_set("sensor.light", "100")
    assert coordinator._determine_is_day() is True

    # Test 2: Float value 0
    hass.states.async_set("sensor.light", "0")
    assert coordinator._determine_is_day() is False

    # Test 3: String value "on" (ValueError fallback)
    hass.states.async_set("sensor.light", "on")
    assert coordinator._determine_is_day() is True

    # Test 4: String value "off"
    hass.states.async_set("sensor.light", "off")
    assert coordinator._determine_is_day() is False
