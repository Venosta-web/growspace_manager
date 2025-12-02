"""Tests for the Dehumidifier Coordinator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.models import Growspace, Plant


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.async_create_task = MagicMock()
    hass.data = {}
    return hass


@pytest.fixture
def mock_track_state_change_event():
    """Mock async_track_state_change_event."""
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.async_track_state_change_event"
    ) as mock:
        yield mock


@pytest.fixture
def mock_main_coordinator():
    """Mock the main GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    coordinator.calculate_days_in_stage = MagicMock(return_value=0)
    return coordinator


@pytest.fixture
def mock_growspace():
    """Mock a Growspace object."""
    growspace = MagicMock(spec=Growspace)
    growspace.id = "gs1"
    growspace.name = "Test Growspace"
    growspace.environment_config = {
        "vpd_sensor": "sensor.vpd",
        "light_sensor": "sensor.light",
        "dehumidifier_entity": "switch.dehumidifier",
        "control_dehumidifier": True,
    }
    growspace.dehumidifier_config = {}
    return growspace


@pytest.fixture
def coordinator(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
):
    """Create a DehumidifierCoordinator instance."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    return DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )


async def test_initialization(coordinator, mock_hass, mock_track_state_change_event):
    """Test successful initialization."""
    assert coordinator.vpd_sensor == "sensor.vpd"
    assert coordinator.light_sensor == "sensor.light"
    assert coordinator.dehumidifier_entity == "switch.dehumidifier"
    assert coordinator.control_dehumidifier is True

    # Verify listener setup
    assert len(coordinator._remove_listeners) > 0
    mock_track_state_change_event.assert_called_once()
    mock_hass.async_create_task.assert_called_once()


async def test_initialization_disabled(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
):
    """Test initialization when control is disabled."""
    mock_growspace.environment_config["control_dehumidifier"] = False
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )

    assert coord.control_dehumidifier is False
    assert len(coord._remove_listeners) == 0
    mock_track_state_change_event.assert_not_called()
    mock_hass.async_create_task.assert_not_called()


async def test_initialization_missing_entities(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
):
    """Test initialization with missing required entities."""
    mock_growspace.environment_config["vpd_sensor"] = None
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )

    assert len(coord._remove_listeners) == 0
    mock_track_state_change_event.assert_not_called()
    mock_hass.async_create_task.assert_not_called()


async def test_check_and_control_turn_on(coordinator, mock_hass):
    """Test turning on the dehumidifier when VPD is low (high humidity)."""
    # Setup state: Low VPD, Light ON (Day), Dehumidifier OFF
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.5"),
        "sensor.light": MagicMock(state="100"),  # > 0 means Day
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    # Default veg day on threshold is 0.6. Current 0.5 < 0.6 -> Turn ON
    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: "switch.dehumidifier"}
    )


async def test_check_and_control_turn_off(coordinator, mock_hass):
    """Test turning off the dehumidifier when VPD is high (low humidity)."""
    # Setup state: High VPD, Light ON (Day), Dehumidifier ON
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.8"),
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    # Default veg day off threshold is 0.7. Current 0.8 > 0.7 -> Turn OFF
    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch", SERVICE_TURN_OFF, {ATTR_ENTITY_ID: "switch.dehumidifier"}
    )


async def test_check_and_control_no_change(coordinator, mock_hass):
    """Test no action when VPD is within deadband."""
    # Setup state: Medium VPD, Light ON (Day), Dehumidifier OFF
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.65"),  # Between 0.6 and 0.7
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_not_called()


async def test_check_and_control_night_mode(coordinator, mock_hass):
    """Test logic with night thresholds."""
    # Setup state: Night (Light 0), VPD needs adjustment
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.6"),
        "sensor.light": MagicMock(state="0"),  # Night
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    # Default veg night on threshold is 0.65. Current 0.6 < 0.65 -> Turn ON
    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: "switch.dehumidifier"}
    )


async def test_growth_stage_detection(coordinator, mock_main_coordinator):
    """Test correct growth stage detection based on plant days."""
    plant1 = MagicMock(spec=Plant)
    plant2 = MagicMock(spec=Plant)
    mock_main_coordinator.get_growspace_plants.return_value = [plant1, plant2]

    # Case 1: Veg
    mock_main_coordinator.calculate_days_in_stage.side_effect = lambda p, stage: {
        "veg": 10,
        "flower": 0,
    }.get(stage, 0)
    assert coordinator._get_growth_stage() == "veg"

    # Case 2: Early Flower
    mock_main_coordinator.calculate_days_in_stage.side_effect = lambda p, stage: {
        "veg": 30,
        "flower": 10,
    }.get(stage, 0)
    assert coordinator._get_growth_stage() == "early_flower"

    # Case 3: Mid Flower
    mock_main_coordinator.calculate_days_in_stage.side_effect = lambda p, stage: {
        "veg": 30,
        "flower": 30,
    }.get(stage, 0)
    assert coordinator._get_growth_stage() == "mid_flower"

    # Case 4: Late Flower
    mock_main_coordinator.calculate_days_in_stage.side_effect = lambda p, stage: {
        "veg": 30,
        "flower": 60,
    }.get(stage, 0)
    assert coordinator._get_growth_stage() == "late_flower"


async def test_user_threshold_override(coordinator, mock_hass, mock_growspace):
    """Test that user thresholds override defaults."""
    # Override thresholds for veg/day
    coordinator.user_thresholds = {"veg": {"day": {"on": 0.8, "off": 0.9}}}

    # Setup state: VPD 0.75 (would be OFF by default, but ON with override? No wait)
    # Default ON < 0.6. Override ON < 0.8.
    # VPD 0.75 is < 0.8, so it should turn ON.

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.75"),
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_called_once_with(
        "switch", SERVICE_TURN_ON, {ATTR_ENTITY_ID: "switch.dehumidifier"}
    )


async def test_missing_sensor_data(coordinator, mock_hass):
    """Test graceful handling of missing or invalid sensor data."""
    # Case 1: VPD Unavailable
    mock_hass.states.get.return_value = MagicMock(state=STATE_UNAVAILABLE)
    await coordinator.async_check_and_control()
    mock_hass.services.async_call.assert_not_called()

    # Case 2: VPD Invalid
    mock_hass.states.get.return_value = MagicMock(state="invalid")
    await coordinator.async_check_and_control()
    mock_hass.services.async_call.assert_not_called()


async def test_unload(coordinator):
    """Test unloading removes listeners."""
    remove_mock = MagicMock()
    coordinator._remove_listeners.append(remove_mock)

    coordinator.unload()

    remove_mock.assert_called_once()
    assert len(coordinator._remove_listeners) == 0
