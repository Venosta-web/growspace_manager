"""Tests for the Dehumidifier Coordinator."""

import logging
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.dehumidifier_coordinator import (
    DehumidifierCoordinator,
)
from custom_components.growspace_manager.models import Plant
from homeassistant.const import (
    ATTR_ENTITY_ID,
    SERVICE_TURN_OFF,
    SERVICE_TURN_ON,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass():
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()

    def mock_create_task(target):
        """Mock async_create_task to close coroutines."""
        if hasattr(target, "close"):
            target.close()
        return MagicMock()

    hass.async_create_task = MagicMock(side_effect=mock_create_task)
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
    coordinator.get_growspace_plants = MagicMock(return_value=[])
    return coordinator


@pytest.fixture
def mock_growspace():
    """Mock a Growspace object."""
    growspace = MagicMock()
    growspace.id = "gs1"
    growspace.name = "Test Growspace"

    # Create env_config as MagicMock with proper attribute access
    env_config = MagicMock()
    env_config.vpd_sensor = "sensor.vpd"
    env_config.light_sensors = ["sensor.light"]
    env_config.dehumidifier_entities = ["switch.dehumidifier"]
    env_config.exhaust_fan_entities = []
    env_config.control_dehumidifier = True
    env_config.dehumidifier_thresholds = {}

    growspace.environment_config = env_config
    growspace.dehumidifier_config = {}
    return growspace


@pytest.fixture
async def coordinator(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
):
    """Create a DehumidifierCoordinator instance."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coord = DehumidifierCoordinator(
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
    assert coordinator.dehumidifier_entities == ["switch.dehumidifier"]
    assert coordinator.control_dehumidifier is True

    # Verify listener setup
    assert len(coordinator._remove_listeners) > 0
    mock_track_state_change_event.assert_called_once()


async def test_initialization_disabled(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test initialization when control is disabled."""
    mock_growspace.environment_config.control_dehumidifier = False
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()
    setattr(coord, "async_check_and_control", MagicMock())

    assert coord.control_dehumidifier is False
    assert len(coord._remove_listeners) == 0
    mock_track_state_change_event.assert_not_called()
    mock_hass.async_create_task.assert_not_called()


async def test_initialization_missing_entities(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test initialization with missing required entities."""
    mock_growspace.environment_config.vpd_sensor = None
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()
    setattr(coord, "async_check_and_control", MagicMock())

    assert len(coord._remove_listeners) == 0
    mock_track_state_change_event.assert_not_called()
    mock_hass.async_create_task.assert_not_called()


async def test_check_and_control_turn_on(coordinator, mock_hass) -> None:
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
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )


async def test_check_and_control_turn_off(coordinator, mock_hass) -> None:
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
        "switch",
        SERVICE_TURN_OFF,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )


async def test_check_and_control_no_change(coordinator, mock_hass) -> None:
    """Test no action when VPD is within deadband."""
    # Setup state: Medium VPD, Light ON (Day), Dehumidifier OFF
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.65"),  # Between 0.6 and 0.7
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    mock_hass.services.async_call.assert_not_called()


async def test_check_and_control_night_mode(coordinator, mock_hass) -> None:
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
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )


async def test_growth_stage_detection(coordinator, mock_main_coordinator) -> None:
    """Test correct growth stage detection based on plant days."""
    plant1 = MagicMock(spec=Plant)
    plant2 = MagicMock(spec=Plant)
    mock_main_coordinator.get_growspace_plants.return_value = [plant1, plant2]

    # Case 1: Veg
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: {
            "veg": 10,
            "flower": 0,
        }.get(stage, 0),
    ):
        assert coordinator._get_growth_stage() == "veg"

    # Case 2: Early Flower
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: {
            "veg": 30,
            "flower": 10,
        }.get(stage, 0),
    ):
        assert coordinator._get_growth_stage() == "early_flower"

    # Case 3: Mid Flower
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: {
            "veg": 30,
            "flower": 30,
        }.get(stage, 0),
    ):
        assert coordinator._get_growth_stage() == "mid_flower"

    # Case 4: Late Flower
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: {
            "veg": 30,
            "flower": 60,
        }.get(stage, 0),
    ):
        assert coordinator._get_growth_stage() == "late_flower"


async def test_user_threshold_override(coordinator, mock_hass, mock_growspace) -> None:
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
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )


async def test_missing_sensor_data(coordinator, mock_hass) -> None:
    """Test graceful handling of missing or invalid sensor data."""
    # Case 1: VPD Unavailable
    mock_hass.states.get.return_value = MagicMock(state=STATE_UNAVAILABLE)
    await coordinator.async_check_and_control()
    mock_hass.services.async_call.assert_not_called()

    # Case 2: VPD Invalid
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


async def test_min_runtime_prevents_early_turnoff(coordinator, mock_hass) -> None:
    """Test that min runtime prevents turning off too early."""
    # Simulate: Dehumidifier is ON, was turned on 60 seconds ago
    coordinator._last_turn_on_time = time.monotonic() - 60  # 60s ago, min is 300s

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.9"),  # High VPD, should turn OFF
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    # Should NOT turn off because min runtime (300s) not elapsed
    mock_hass.services.async_call.assert_not_called()


async def test_min_offtime_prevents_early_turnon(coordinator, mock_hass) -> None:
    """Test that min offtime prevents turning on too early."""
    # Simulate: Dehumidifier is OFF, was turned off 60 seconds ago
    coordinator._last_turn_off_time = time.monotonic() - 60  # 60s ago, min is 300s

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.5"),  # Low VPD, should turn ON
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    # Should NOT turn on because min offtime (300s) not elapsed
    mock_hass.services.async_call.assert_not_called()


async def test_timer_allows_action_after_min_duration(coordinator, mock_hass) -> None:
    """Test that actions are allowed after minimum duration has elapsed."""
    # Simulate: Dehumidifier was turned off 400 seconds ago (> 300s min)
    coordinator._last_turn_off_time = time.monotonic() - 400

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.5"),  # Low VPD, should turn ON
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    # Should turn on because min offtime has elapsed
    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )


async def test_timestamps_updated_on_control(coordinator, mock_hass) -> None:
    """Test that timestamps are updated when control actions occur."""
    # Initial timestamps should be 0
    assert coordinator._last_turn_on_time == 0.0
    assert coordinator._last_turn_off_time == 0.0

    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.5"),  # Low VPD
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    before = time.monotonic()
    await coordinator.async_check_and_control()
    after = time.monotonic()

    # Turn on timestamp should be updated
    assert coordinator._last_turn_on_time >= before
    assert coordinator._last_turn_on_time <= after
    assert coordinator._last_turn_off_time == 0.0  # Still 0


async def test_timer_guard_bypassed_on_first_action(coordinator, mock_hass) -> None:
    """Test that timer guards don't block the very first action."""
    # Timestamps are 0.0, so guard should not apply
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.5"),  # Low VPD
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    # Should turn on even though we haven't tracked any previous actions
    mock_hass.services.async_call.assert_called_once_with(
        "switch",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "switch.dehumidifier"},
        blocking=False,
    )


def test_init_missing_growspace(
    mock_hass, mock_main_coordinator, caplog: pytest.LogCaptureFixture
) -> None:
    """Test initialization when growspace does not exist (lines 80-83)."""
    mock_main_coordinator.growspaces = {}

    with caplog.at_level(logging.ERROR):
        DehumidifierCoordinator(
            mock_hass, MagicMock(), "nonexistent", mock_main_coordinator
        )

    assert "Growspace nonexistent not found" in caplog.text


@pytest.mark.asyncio
async def test_on_sensor_change(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test _on_sensor_change triggers check (line 134)."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coordinator = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coordinator.async_setup()

    # Mock async_check_and_control to verify it's awaited
    coordinator.async_check_and_control = AsyncMock()  # type: ignore[method-assign]

    await coordinator._on_sensor_change(None)

    coordinator.async_check_and_control.assert_awaited_once()


@pytest.mark.asyncio
async def test_check_and_control_missing_entities(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test async_check_and_control with missing entities (line 138-139)."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coordinator = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coordinator.async_setup()

    # Force vpd_sensor to None after init
    coordinator.vpd_sensor = None

    # Should yield early without error
    await coordinator.async_check_and_control()


@pytest.mark.asyncio
async def test_binary_light_sensor(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test light sensor with binary state (lines 167-169)."""
    mock_growspace.environment_config.light_sensors = ["binary_sensor.light"]
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coordinator = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coordinator.async_setup()

    # Setup states
    mock_hass.states.get.side_effect = lambda entity_id: MagicMock(
        state="1.5" if entity_id == "sensor.vpd" else STATE_ON
    )

    # Mock internal methods to isolate logic
    coordinator._get_growth_stage = MagicMock(return_value="veg")  # type: ignore[method-assign]
    coordinator._get_current_thresholds = MagicMock(  # type: ignore[method-assign]
        return_value={"on": 1.0, "off": 2.0}
    )
    coordinator._control_dehumidifier = AsyncMock()  # type: ignore[method-assign]

    await coordinator.async_check_and_control()

    # Verify is_day was calculated as True (STATE_ON)
    # logic: is_day = light_state.state == STATE_ON
    # We can check if _get_current_thresholds was called with is_day=True
    coordinator._get_current_thresholds.assert_called_with("veg", True)

    # Now test with "off"
    mock_hass.states.get.side_effect = lambda entity_id: MagicMock(
        state="1.5" if entity_id == "sensor.vpd" else STATE_OFF
    )

    await coordinator.async_check_and_control()
    coordinator._get_current_thresholds.assert_called_with("veg", False)


@pytest.mark.asyncio
async def test_generic_domain_control(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test controlling an entity from a generic domain (line 304)."""
    mock_growspace.environment_config.dehumidifier_entities = [
        "input_boolean.dehumidifier"
    ]
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coordinator = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coordinator.async_setup()

    # Manually invoke control
    await coordinator._control_dehumidifier(True)

    # Should call input_boolean.turn_on
    mock_hass.services.async_call.assert_awaited_with(
        "input_boolean",
        "turn_on",
        {ATTR_ENTITY_ID: "input_boolean.dehumidifier"},
        blocking=False,
    )


async def test_growth_stage_detection_cure_dry_seedling(
    coordinator, mock_main_coordinator
) -> None:
    """Test detection of cure, dry, and seedling stages."""
    plant = MagicMock(spec=Plant)
    mock_main_coordinator.get_growspace_plants.return_value = [plant]

    # Test Cure
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: 1 if stage == "cure" else 0,
    ):
        assert coordinator._get_growth_stage() == "cure"

    # Test Dry
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: 1 if stage == "dry" else 0,
    ):
        assert coordinator._get_growth_stage() == "dry"

    # Test Seedling
    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: 1 if stage == "seedling" else 0,
    ):
        assert coordinator._get_growth_stage() == "seedling"

    with patch(
        "custom_components.growspace_manager.dehumidifier_coordinator.calculate_days_in_stage",
        side_effect=lambda p, stage: 1 if stage == "mother" else 0,
    ):
        assert coordinator._get_growth_stage() == "mother"


async def test_control_domain_fallback(
    mock_hass, mock_main_coordinator, mock_growspace, mock_track_state_change_event
) -> None:
    """Test domain fallback in _control_dehumidifier."""
    mock_growspace.environment_config.dehumidifier_entities = ["light.dehumidifier"]
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}

    coordinator = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coordinator.async_setup()

    await coordinator._control_dehumidifier(True)

    # light is not in the list of recognized domains, so should fallback to homeassistant
    mock_hass.services.async_call.assert_awaited_with(
        "homeassistant",
        SERVICE_TURN_ON,
        {ATTR_ENTITY_ID: "light.dehumidifier"},
        blocking=False,
    )


async def test_control_device_exception(
    coordinator, mock_hass, caplog: pytest.LogCaptureFixture
) -> None:
    """Test exception handling in _control_dehumidifier."""
    mock_hass.services.async_call.side_effect = Exception("Service failure")

    with caplog.at_level(logging.WARNING):
        await coordinator._control_dehumidifier(True)

    assert "Failed to control device" in caplog.text


async def test_get_current_vpd_missing_sensor(
    coordinator,
) -> None:
    """Test _get_current_vpd returns None when sensor is missing."""
    coordinator.vpd_sensor = None
    assert coordinator._get_current_vpd() is None


async def test_logbook_event_fired_on_turn_on(coordinator, mock_hass) -> None:
    """Test that a logbook event is fired when dehumidifier turns on."""
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.5"),
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    coordinator.main_coordinator.add_event.assert_called_once()
    call_args = coordinator.main_coordinator.add_event.call_args
    growspace_id, event = call_args[0]
    assert growspace_id == "gs1"
    assert event.category == "dehumidifier"
    assert "Turned ON" in event.reasons
    assert any("VPD:" in r for r in event.reasons)
    assert any("Stage:" in r for r in event.reasons)


async def test_logbook_event_fired_on_turn_off(coordinator, mock_hass) -> None:
    """Test that a logbook event is fired when dehumidifier turns off."""
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.8"),
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_ON),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    coordinator.main_coordinator.add_event.assert_called_once()
    call_args = coordinator.main_coordinator.add_event.call_args
    growspace_id, event = call_args[0]
    assert growspace_id == "gs1"
    assert event.category == "dehumidifier"
    assert "Turned OFF" in event.reasons
    assert any("VPD:" in r for r in event.reasons)


async def test_logbook_event_not_fired_when_no_action(coordinator, mock_hass) -> None:
    """Test that no logbook event is fired when VPD is in deadband."""
    mock_hass.states.get.side_effect = lambda entity_id: {
        "sensor.vpd": MagicMock(state="0.65"),
        "sensor.light": MagicMock(state="100"),
        "switch.dehumidifier": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    await coordinator.async_check_and_control()

    coordinator.main_coordinator.add_event.assert_not_called()


async def test_determine_is_day_all_sensors_unavailable_uses_cached_state(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_growspace: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that all-unavailable sensors fall back to last known state, not True."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()

    # Prime the cache with night state (sensor reports 0 lux)
    mock_hass.states.get.side_effect = lambda entity_id: MagicMock(state="0")
    assert coord._determine_is_day() is False
    assert coord._last_known_is_day is False

    # Now all sensors become unavailable
    mock_hass.states.get.side_effect = lambda entity_id: MagicMock(
        state=STATE_UNAVAILABLE
    )
    # Should return cached False, not True
    assert coord._determine_is_day() is False
    assert coord._sensors_unavailable_since is not None


async def test_determine_is_day_all_sensors_unavailable_no_cache_defaults_true(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_growspace: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that all-unavailable sensors with no cache default to True."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()

    mock_hass.states.get.side_effect = lambda entity_id: MagicMock(
        state=STATE_UNAVAILABLE
    )
    # No prior cache — should still default to True (safe fallback)
    assert coord._determine_is_day() is True
    assert coord._sensors_unavailable_since is not None


async def test_determine_is_day_valid_read_clears_unavailability_timer(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_growspace: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that a valid sensor read clears the unavailability timer and updates cache."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()

    # Simulate prior unavailability
    coord._sensors_unavailable_since = time.monotonic() - 100

    mock_hass.states.get.side_effect = lambda entity_id: MagicMock(state="500")
    result = coord._determine_is_day()

    assert result is True
    assert coord._last_known_is_day is True
    assert coord._sensors_unavailable_since is None


async def test_determine_is_day_prolonged_unavailability_logs_warning(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_growspace: MagicMock,
    mock_track_state_change_event: MagicMock,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Test that a warning is logged after sensors are unavailable for over 5 minutes."""
    mock_main_coordinator.growspaces = {"gs1": mock_growspace}
    coord = DehumidifierCoordinator(
        mock_hass, mock_track_state_change_event, "gs1", mock_main_coordinator
    )
    await coord.async_setup()

    coord._last_known_is_day = True
    coord._sensors_unavailable_since = time.monotonic() - 400  # > 300 s

    mock_hass.states.get.side_effect = lambda entity_id: MagicMock(
        state=STATE_UNAVAILABLE
    )

    with caplog.at_level(logging.WARNING):
        coord._determine_is_day()

    assert any("unavailable" in r.message.lower() for r in caplog.records)


async def test_determine_is_device_on_exhaust_fans(coordinator, mock_hass) -> None:
    """Test _determine_is_device_on checks exhaust fans."""
    coordinator.dehumidifier_entities = []
    coordinator.exhaust_fan_entities = ["fan.exhaust"]

    mock_hass.states.get.side_effect = lambda entity_id: {
        "fan.exhaust": MagicMock(state=STATE_ON),
    }.get(entity_id)

    assert coordinator._determine_is_device_on() is True

    mock_hass.states.get.side_effect = lambda entity_id: {
        "fan.exhaust": MagicMock(state=STATE_OFF),
    }.get(entity_id)

    assert coordinator._determine_is_device_on() is False
