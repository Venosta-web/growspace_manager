"""Tests for the Light Cycle Tracker."""

from datetime import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.light_cycle_tracker import LightCycleTracker
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    IrrigationStrategy,
)
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant


@pytest.fixture
def mock_hass() -> MagicMock:
    """Fixture for mocking HomeAssistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    return hass


@pytest.fixture
def mock_track_state_change_event():
    """Fixture to mock async_track_state_change_event."""
    with patch(
        "custom_components.growspace_manager.light_cycle_tracker.async_track_state_change_event"
    ) as mock:
        yield mock


@pytest.fixture
def mock_main_coordinator() -> MagicMock:
    """Fixture for mocking GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.async_commit = AsyncMock()
    return coordinator


def make_growspace(
    *,
    enabled: bool = True,
    auto_light_tracking: bool = True,
    light_sensors: list[str] | None = None,
) -> Growspace:
    """Helper to create a Growspace config for testing."""
    growspace = Growspace(
        id="gs1",
        name="Test Growspace",
        environment_config=EnvironmentConfig(
            light_sensors=light_sensors
            if light_sensors is not None
            else ["sensor.light1"],
        ),
    )
    growspace.irrigation_strategy = IrrigationStrategy(
        enabled=enabled,
        auto_light_tracking=auto_light_tracking,
        lights_on_time="08:00:00",
    )
    return growspace


@pytest.fixture
def growspace() -> Growspace:
    """Fixture for a standard test Growspace config."""
    return make_growspace()


async def fire_state_change(
    tracker, entity_id: str, old_state: str, new_state: str
) -> None:
    """Simulate a state-change event fired at the tracker."""
    event = MagicMock()
    event.data = {
        "entity_id": entity_id,
        "old_state": MagicMock(state=old_state),
        "new_state": MagicMock(state=new_state, domain="binary_sensor"),
    }
    await tracker._on_sensor_change(event)


# ---------------------------------------------------------------------------
# Tracer bullet: off→on with all preconditions met writes detected_lights_on_time
# ---------------------------------------------------------------------------


async def test_lights_on_transition_writes_detected_lights_on_time(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    growspace: Growspace,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that a lights-on transition correctly records the detected time."""
    mock_main_coordinator.growspaces = {"gs1": growspace}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    fixed_time = time(9, 15, 30)
    with patch(
        "custom_components.growspace_manager.light_cycle_tracker.dt_util.now",
        return_value=MagicMock(time=lambda: fixed_time),
    ):
        await fire_state_change(tracker, "sensor.light1", "off", "on")

    assert growspace.irrigation_strategy.detected_lights_on_time == "09:15:30"
    mock_main_coordinator.async_commit.assert_awaited_once()


async def test_no_write_when_auto_light_tracking_disabled(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that detected lights-on time is not recorded if auto-tracking is disabled."""
    gs = make_growspace(auto_light_tracking=False)
    mock_main_coordinator.growspaces = {"gs1": gs}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    await fire_state_change(tracker, "sensor.light1", "off", "on")

    assert gs.irrigation_strategy.detected_lights_on_time is None
    mock_main_coordinator.async_commit.assert_not_awaited()


async def test_no_write_when_light_sensors_empty(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that no tracking setup happens if light sensors list is empty."""
    gs = make_growspace(light_sensors=[])
    mock_main_coordinator.growspaces = {"gs1": gs}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    mock_track_state_change_event.assert_not_called()
    await fire_state_change(tracker, "sensor.light1", "off", "on")

    assert gs.irrigation_strategy.detected_lights_on_time is None
    mock_main_coordinator.async_commit.assert_not_awaited()


async def test_numeric_sensor_above_zero_is_on(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that numeric sensor values above zero are treated as lights-on."""
    gs = make_growspace(light_sensors=["sensor.lux"])
    mock_main_coordinator.growspaces = {"gs1": gs}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    event = MagicMock()
    event.data = {
        "entity_id": "sensor.lux",
        "old_state": MagicMock(state="0", domain="sensor"),
        "new_state": MagicMock(state="500", domain="sensor"),
    }

    fixed_time = time(7, 0, 0)
    with patch(
        "custom_components.growspace_manager.light_cycle_tracker.dt_util.now",
        return_value=MagicMock(time=lambda: fixed_time),
    ):
        await tracker._on_sensor_change(event)

    assert gs.irrigation_strategy.detected_lights_on_time == "07:00:00"


async def test_numeric_sensor_zero_is_off_no_write(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that numeric sensor values at zero are treated as lights-off."""
    gs = make_growspace(light_sensors=["sensor.lux"])
    mock_main_coordinator.growspaces = {"gs1": gs}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    event = MagicMock()
    event.data = {
        "entity_id": "sensor.lux",
        "old_state": MagicMock(state="500", domain="sensor"),
        "new_state": MagicMock(state="0", domain="sensor"),
    }
    await tracker._on_sensor_change(event)

    assert gs.irrigation_strategy.detected_lights_on_time is None
    mock_main_coordinator.async_commit.assert_not_awaited()


async def test_binary_sensor_state_on_is_on(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that a binary sensor changing to 'on' is treated as lights-on."""
    gs = make_growspace(light_sensors=["binary_sensor.growlight"])
    mock_main_coordinator.growspaces = {"gs1": gs}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    fixed_time = time(6, 0, 0)
    with patch(
        "custom_components.growspace_manager.light_cycle_tracker.dt_util.now",
        return_value=MagicMock(time=lambda: fixed_time),
    ):
        await fire_state_change(tracker, "binary_sensor.growlight", "off", "on")

    assert gs.irrigation_strategy.detected_lights_on_time == "06:00:00"


async def test_listeners_removed_on_unload(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that unloading the tracker removes all state change listeners."""
    gs = make_growspace()
    mock_main_coordinator.growspaces = {"gs1": gs}
    remove_fn = MagicMock()
    mock_track_state_change_event.return_value = remove_fn

    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    tracker.unload()

    remove_fn.assert_called_once()
    assert tracker._remove_listeners == []


async def test_no_write_when_irrigation_disabled(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    mock_track_state_change_event: MagicMock,
) -> None:
    """Test that detected lights-on is not recorded if irrigation is disabled."""
    gs = make_growspace(enabled=False)
    mock_main_coordinator.growspaces = {"gs1": gs}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker.async_setup()

    await fire_state_change(tracker, "sensor.light1", "off", "on")

    assert gs.irrigation_strategy.detected_lights_on_time is None
    mock_main_coordinator.async_commit.assert_not_awaited()


async def test_is_active_no_growspace(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test _is_active returns False when the growspace is missing from coordinator."""
    mock_main_coordinator.growspaces = {}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    assert tracker._is_active() is False


async def test_is_active_no_irrigation_strategy(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test _is_active returns False when the growspace has no irrigation strategy."""
    growspace = Growspace(id="gs1", name="Test Growspace")
    growspace.irrigation_strategy = None
    mock_main_coordinator.growspaces = {"gs1": growspace}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    assert tracker._is_active() is False


async def test_light_sensors_no_growspace(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test _light_sensors returns empty list when the growspace is missing."""
    mock_main_coordinator.growspaces = {}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    assert tracker._light_sensors() == []


@pytest.mark.parametrize("state", [STATE_UNAVAILABLE, STATE_UNKNOWN])
async def test_is_sensor_on_unavailable_or_unknown(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
    state: str,
) -> None:
    """Test _is_sensor_on returns None when sensor state is unavailable or unknown."""
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    assert tracker._is_sensor_on("sensor.light1", state, "sensor") is None


async def test_is_sensor_on_non_numeric_sensor_value(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test _is_sensor_on returns None when sensor value cannot be converted to float."""
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    assert tracker._is_sensor_on("sensor.light1", "not-a-number", "sensor") is None


async def test_record_lights_on_no_growspace(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test _record_lights_on exits early when the growspace is missing from coordinator."""
    mock_main_coordinator.growspaces = {}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker._record_lights_on()
    mock_main_coordinator.async_commit.assert_not_awaited()


async def test_record_lights_on_no_irrigation_strategy(
    mock_hass: MagicMock,
    mock_main_coordinator: MagicMock,
) -> None:
    """Test _record_lights_on exits early when the growspace has no irrigation strategy."""
    growspace = Growspace(id="gs1", name="Test Growspace")
    growspace.irrigation_strategy = None
    mock_main_coordinator.growspaces = {"gs1": growspace}
    tracker = LightCycleTracker(mock_hass, "gs1", mock_main_coordinator)
    await tracker._record_lights_on()
    mock_main_coordinator.async_commit.assert_not_awaited()
