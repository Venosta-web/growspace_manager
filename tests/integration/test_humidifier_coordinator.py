"""Tests for the Humidifier Coordinator."""

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.domain.stage import PlantStage
from custom_components.growspace_manager.humidifier_coordinator import (
    HumidifierCoordinator,
)
from custom_components.growspace_manager.models import ACInfinityDevice, Plant
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()

    def mock_create_task(target):
        if hasattr(target, "close"):
            target.close()
        return MagicMock()

    hass.async_create_task = MagicMock(side_effect=mock_create_task)
    hass.data = {}

    mock_loop = MagicMock()
    mock_loop.time.return_value = 0.0
    hass.loop = mock_loop

    return hass


@pytest.fixture
def mock_track_state_change_event():
    """Mock async_track_state_change_event."""
    with patch(
        "custom_components.growspace_manager.vpd_on_off_controller.async_track_state_change_event"
    ) as mock:
        yield mock


@pytest.fixture
def mock_main_coordinator():
    """Mock the main GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    return coordinator


@pytest.fixture
def mock_growspace():
    """Mock a Growspace object."""
    growspace = MagicMock()
    growspace.id = "gs1"
    growspace.name = "Test Growspace"

    env_config = MagicMock()
    env_config.vpd_sensor = "sensor.vpd"
    env_config.light_sensors = ["sensor.light"]
    env_config.humidifier_entities = ["switch.humidifier"]
    env_config.control_humidifier = True
    env_config.humidifier_thresholds = {}

    growspace.environment_config = env_config
    growspace.humidifier_config = {}
    return growspace


@pytest.fixture
async def coordinator(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
):
    """Create a HumidifierCoordinator instance."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coord = HumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()
    return coord


async def test_initialization(
    coordinator, mock_hass, mock_track_state_change_event
) -> None:
    """Test successful initialization."""
    assert coordinator.vpd_sensor == "sensor.vpd"
    assert coordinator.light_sensors == ["sensor.light"]
    assert coordinator._get_all_controlled_entities() == ["switch.humidifier"]
    assert coordinator.control_enabled is True
    assert len(coordinator._remove_listeners) > 0
    mock_track_state_change_event.assert_called_once()


async def test_initialization_disabled(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test initialization when control is disabled."""
    mock_growspace.environment_config.control_humidifier = False
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coord = HumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()

    assert coord.control_enabled is False
    assert len(coord._remove_listeners) == 0
    mock_track_state_change_event.assert_not_called()
    mock_hass.async_create_task.assert_not_called()


async def test_initialization_missing_vpd_sensor(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test initialization with missing VPD sensor."""
    mock_growspace.environment_config.vpd_sensor = None
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coord = HumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()

    assert len(coord._remove_listeners) == 0
    mock_track_state_change_event.assert_not_called()
    mock_hass.async_create_task.assert_not_called()


async def test_check_and_control_turn_on(coordinator, mock_hass) -> None:
    """Test turning on the humidifier when VPD is high (low humidity)."""
    # Default veg day on threshold is 1.0. Current 1.1 > 1.0 -> Turn ON
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.1"),
        "sensor.light": MagicMock(state="100"),  # Day
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.humidifier"},
        blocking=False,
    )


async def test_check_and_control_turn_off(coordinator, mock_hass) -> None:
    """Test turning off the humidifier when VPD drops (humidity restored)."""
    # Default veg day off threshold is 0.8. Current 0.7 < 0.8 -> Turn OFF
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.7"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.humidifier"},
        blocking=False,
    )


async def test_check_and_control_no_change(coordinator, mock_hass) -> None:
    """Test no action when VPD is within deadband."""
    # Between off (0.8) and on (1.0) thresholds
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.9"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_not_called()


async def test_check_and_control_night_mode(coordinator, mock_hass) -> None:
    """Test logic with night thresholds."""
    # Default veg night on threshold is 0.85. Current 0.9 > 0.85 -> Turn ON
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.9"),
        "sensor.light": MagicMock(state="0"),  # Night
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.humidifier"},
        blocking=False,
    )


async def test_logbook_event_fired_on_turn_on(coordinator, mock_hass) -> None:
    """Test that a logbook event is fired when humidifier turns on."""
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.1"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    coordinator.main_coordinator.add_event.assert_called_once()
    call_args = coordinator.main_coordinator.add_event.call_args
    growspace_id, event = call_args[0]
    assert growspace_id == "gs1"
    assert event.category == "humidifier"
    assert "Turned ON" in event.reasons
    assert any("VPD:" in r for r in event.reasons)
    assert any("Stage:" in r for r in event.reasons)


async def test_logbook_event_fired_on_turn_off(coordinator, mock_hass) -> None:
    """Test that a logbook event is fired when humidifier turns off."""
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.7"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    coordinator.main_coordinator.add_event.assert_called_once()
    call_args = coordinator.main_coordinator.add_event.call_args
    growspace_id, event = call_args[0]
    assert growspace_id == "gs1"
    assert event.category == "humidifier"
    assert "Turned OFF" in event.reasons


async def test_logbook_event_not_fired_in_deadband(coordinator, mock_hass) -> None:
    """Test that no logbook event fires when VPD is in deadband."""
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.9"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    coordinator.main_coordinator.add_event.assert_not_called()


async def test_min_runtime_prevents_early_turnoff(coordinator, mock_hass) -> None:
    """Test that min runtime prevents turning off too early."""
    coordinator._last_turn_on_time = time.monotonic() - 60  # 60s ago, min is 300s

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.5"),  # Low VPD, should turn OFF
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_not_called()


async def test_min_offtime_prevents_early_turnon(coordinator, mock_hass) -> None:
    """Test that min offtime prevents turning on too early."""
    coordinator._last_turn_off_time = time.monotonic() - 60  # 60s ago, min is 300s

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.1"),  # High VPD, should turn ON
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_not_called()


async def test_user_threshold_override(coordinator, mock_hass) -> None:
    """Test that user thresholds override defaults."""
    coordinator.user_thresholds = {"veg": {"day": {"on": 1.3, "off": 1.1}}}

    # Default on is 1.0. Override on is 1.3. VPD 1.2 is < 1.3 so should NOT turn on.
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.2"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_not_called()

    # VPD 1.4 > 1.3 -> should turn ON
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.4"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.humidifier"},
        blocking=False,
    )


async def test_missing_sensor_data(coordinator, mock_hass) -> None:
    """Test graceful handling of missing or invalid sensor data."""
    mock_hass.states.get.return_value = MagicMock(state=STATE_UNAVAILABLE)
    await coordinator.async_check_and_control()
    mock_hass.services.async_call.assert_not_called()

    mock_hass.states.get.return_value = MagicMock(state="invalid")
    await coordinator.async_check_and_control()
    mock_hass.services.async_call.assert_not_called()


async def test_unload(coordinator) -> None:
    """Test unloading removes listeners."""
    remove_mock = MagicMock()
    coordinator._remove_listeners.append(remove_mock)

    coordinator.unload()

    remove_mock.assert_called_once()
    assert len(coordinator._remove_listeners) == 0


async def test_timestamps_updated_on_control(coordinator, mock_hass) -> None:
    """Test that timestamps are updated when control actions occur."""
    assert coordinator._last_turn_on_time == 0.0
    assert coordinator._last_turn_off_time == 0.0

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="1.1"),
        "sensor.light": MagicMock(state="100"),
        "switch.humidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    before = time.monotonic()
    await coordinator.async_check_and_control()
    after = time.monotonic()

    assert coordinator._last_turn_on_time >= before
    assert coordinator._last_turn_on_time <= after
    assert coordinator._last_turn_off_time == 0.0


def test_init_missing_growspace(
    mock_hass, mock_main_coordinator, caplog: pytest.LogCaptureFixture
) -> None:
    """Test initialization when growspace does not exist."""
    mock_main_coordinator.growspaces = {}

    with caplog.at_level(logging.ERROR):
        HumidifierCoordinator(
            mock_hass, MagicMock(), "nonexistent", mock_main_coordinator
        )

    assert "growspace nonexistent not found" in caplog.text.lower()


async def test_growth_stage_detection(coordinator, mock_main_coordinator) -> None:
    """Test correct growth stage detection."""
    plant = MagicMock(spec=Plant)
    mock_main_coordinator.services.growspaces.get_growspace_plants.return_value = [
        plant
    ]

    with patch(
        "custom_components.growspace_manager.domain.stage_calculator.calculate_days_in_stage",
        side_effect=lambda p, stage: {PlantStage.FLOWER: 60}.get(stage, 0),
    ):
        assert coordinator._get_growth_stage() == PlantStage.FLOWER_LATE

    with patch(
        "custom_components.growspace_manager.domain.stage_calculator.calculate_days_in_stage",
        side_effect=lambda p, stage: {PlantStage.VEG: 10}.get(stage, 0),
    ):
        assert coordinator._get_growth_stage() == PlantStage.VEG


async def test_generic_domain_control(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test controlling an entity from a generic domain falls back to homeassistant."""
    mock_growspace.environment_config.humidifier_entities = ["light.humidifier"]
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coord = HumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()

    await coord._control_devices(True)

    mock_hass.services.async_call.assert_awaited_with(
        "homeassistant",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "light.humidifier"},
        blocking=False,
    )


async def test_control_device_exception(
    coordinator, mock_hass, caplog: pytest.LogCaptureFixture
) -> None:
    """Test exception handling in _control_devices."""
    mock_hass.services.async_call.side_effect = HomeAssistantError("Service failure")

    with caplog.at_level(logging.WARNING):
        await coordinator._control_devices(True)

    assert "Failed to call" in caplog.text


async def test_on_sensor_change(coordinator) -> None:
    """Test _on_sensor_change triggers check."""
    coordinator.async_check_and_control = AsyncMock()

    await coordinator._on_sensor_change(None)

    coordinator.async_check_and_control.assert_awaited_once()


async def test_check_and_control_missing_vpd_sensor(coordinator) -> None:
    """Test async_check_and_control exits early with no VPD sensor."""
    coordinator.vpd_sensor = None
    await coordinator.async_check_and_control()


# ---------------------------------------------------------------------------
# AC Infinity humidifier devices (ADR-0022)
# ---------------------------------------------------------------------------


def _ac_infinity_humidifier(
    mock_hass, mock_main_coordinator, mock_track_state_change_event
) -> HumidifierCoordinator:
    """Build a HumidifierCoordinator controlling one AC Infinity port (no plain entity)."""
    growspace = MagicMock()
    growspace.id = "gs1"
    growspace.name = "Test Growspace"
    env_config = MagicMock()
    env_config.vpd_sensor = "sensor.vpd"
    env_config.light_sensors = []
    env_config.humidifier_entities = []
    env_config.humidifier_ac_infinity_devices = [
        ACInfinityDevice(
            mode_entity="select.hum_mode",
            speed_entity="number.hum_speed",
            on_speed=8,
        )
    ]
    env_config.control_humidifier = True
    env_config.humidifier_thresholds = {}
    growspace.environment_config = env_config
    growspace.humidifier_config = {}
    mock_main_coordinator.growspaces = {"gs1": growspace}
    return HumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )


async def test_ac_infinity_humidifier_turn_on(
    mock_hass, mock_main_coordinator, mock_track_state_change_event
) -> None:
    """Turning the humidifier on drives the port mode On at its configured on-speed."""
    coord = _ac_infinity_humidifier(
        mock_hass, mock_main_coordinator, mock_track_state_change_event
    )
    mock_hass.services.async_call.reset_mock()
    await coord._control_devices(True)
    mock_hass.services.async_call.assert_any_await(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.hum_mode", "option": "On"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.hum_speed", "value": 8},
        blocking=False,
    )


async def test_ac_infinity_only_humidifier_reacts_to_vpd(
    mock_hass, mock_main_coordinator, mock_track_state_change_event
) -> None:
    """An AC-only bundle must pass the event-handler actuator guard."""
    coord = _ac_infinity_humidifier(
        mock_hass, mock_main_coordinator, mock_track_state_change_event
    )
    coord._get_current_vpd = MagicMock(return_value=2.0)
    coord._get_growth_stage = MagicMock(return_value=PlantStage.VEG)
    coord._day_night.determine = MagicMock(return_value=True)
    coord._is_device_on = MagicMock(return_value=False)
    coord._is_locked_by_timer = MagicMock(return_value=False)

    await coord.async_check_and_control()

    mock_hass.services.async_call.assert_any_await(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.hum_mode", "option": "On"},
        blocking=False,
    )
    mock_hass.services.async_call.assert_any_await(
        "number",
        "set_value",
        {ATTR_ENTITY_ID: "number.hum_speed", "value": 8},
        blocking=False,
    )


async def test_ac_infinity_humidifier_turn_off(
    mock_hass, mock_main_coordinator, mock_track_state_change_event
) -> None:
    """Turning the humidifier off sets the port mode to Off."""
    coord = _ac_infinity_humidifier(
        mock_hass, mock_main_coordinator, mock_track_state_change_event
    )
    mock_hass.services.async_call.reset_mock()
    await coord._control_devices(False)
    mock_hass.services.async_call.assert_awaited_once_with(
        "select",
        "select_option",
        {ATTR_ENTITY_ID: "select.hum_mode", "option": "Off"},
        blocking=False,
    )


async def test_ac_infinity_humidifier_is_on_reads_mode_select(
    mock_hass, mock_main_coordinator, mock_track_state_change_event
) -> None:
    """is_on reads the AC Infinity mode select, not a plain entity state."""
    coord = _ac_infinity_humidifier(
        mock_hass, mock_main_coordinator, mock_track_state_change_event
    )
    mock_hass.states.get.return_value = MagicMock(state="On")
    assert coord._is_device_on() is True
    mock_hass.states.get.return_value = MagicMock(state="Off")
    assert coord._is_device_on() is False


async def test_get_ac_infinity_devices_no_growspace(
    mock_hass, mock_main_coordinator, mock_track_state_change_event
) -> None:
    """With no growspace, the AC Infinity bundle accessor returns an empty list."""
    mock_main_coordinator.growspaces = {}
    coord = HumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "missing", mock_main_coordinator
    )
    assert coord._get_ac_infinity_devices() == []
    assert coord._get_all_controlled_entities() == []
