"""Tests for the EnvironmentReporter."""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.services.environment_reporter import (
    EnvironmentReporter,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util

GROWSPACE_ID = "test_growspace"
GROWSPACE_NAME = "Test Growspace"
LIGHT_SENSOR = "sensor.grow_light"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name=GROWSPACE_NAME,
            environment_config=EnvironmentConfig(
                light_sensors=[LIGHT_SENSOR],
                temperature_sensor="sensor.temp",
                humidity_sensor="sensor.humidity",
                vpd_sensor="sensor.vpd",
            ),
        )
    }
    # Add config_entry with background task support
    coordinator.config_entry = MagicMock()
    coordinator.config_entry.async_create_background_task = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    hass.async_add_executor_job = AsyncMock()
    hass.states = MagicMock()
    return hass


@pytest.fixture
def reporter(mock_hass: MagicMock, mock_coordinator: MagicMock) -> EnvironmentReporter:
    """Fixture for EnvironmentReporter."""
    return EnvironmentReporter(mock_hass, mock_coordinator)


async def test_initialization(
    reporter: EnvironmentReporter, mock_coordinator: MagicMock
) -> None:
    """Test initialization and listener setup."""
    with patch.object(reporter, "_setup_growspace_listener") as mock_setup:
        await reporter.async_initialize()
        mock_setup.assert_awaited_once_with(GROWSPACE_ID)


async def test_setup_growspace_listener_success(
    reporter: EnvironmentReporter, mock_hass: MagicMock
) -> None:
    """Test successful listener setup."""
    with patch(
        "custom_components.growspace_manager.services.environment_reporter.async_track_state_change_event"
    ) as mock_track:
        await reporter._setup_growspace_listener(GROWSPACE_ID)

        mock_track.assert_called_once()
        args = mock_track.call_args[0]
        assert args[1] == [LIGHT_SENSOR]
        assert GROWSPACE_ID in reporter._unsub_listeners
        assert GROWSPACE_ID in reporter._state_start_times


async def test_setup_growspace_listener_cleanup(
    reporter: EnvironmentReporter, mock_hass: MagicMock
) -> None:
    """Test listener cleanup before setup."""
    mock_unsub = MagicMock()
    reporter._unsub_listeners[GROWSPACE_ID] = mock_unsub

    with patch(
        "custom_components.growspace_manager.services.environment_reporter.async_track_state_change_event"
    ):
        await reporter._setup_growspace_listener(GROWSPACE_ID)
        mock_unsub.assert_called_once()


async def test_setup_growspace_listener_no_growspace(
    reporter: EnvironmentReporter, mock_coordinator: MagicMock
) -> None:
    """Test setup with missing growspace."""
    mock_coordinator.growspaces = {}
    await reporter._setup_growspace_listener(GROWSPACE_ID)
    assert GROWSPACE_ID not in reporter._unsub_listeners


async def test_setup_growspace_listener_no_sensor(
    reporter: EnvironmentReporter, mock_coordinator: MagicMock
) -> None:
    """Test setup with missing light sensor."""
    mock_coordinator.growspaces[GROWSPACE_ID].environment_config.light_sensors = []
    await reporter._setup_growspace_listener(GROWSPACE_ID)
    assert GROWSPACE_ID not in reporter._unsub_listeners


async def test_light_state_listener_callback(
    reporter: EnvironmentReporter, mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test the internal light state listener callback."""
    # We need to capture the listener defined inside _setup_growspace_listener
    captured_listener = None

    def mock_track(hass, sensors, listener):
        nonlocal captured_listener
        captured_listener = listener
        return MagicMock()

    with patch(
        "custom_components.growspace_manager.services.environment_reporter.async_track_state_change_event",
        side_effect=mock_track,
    ):
        await reporter._setup_growspace_listener(GROWSPACE_ID)

    assert captured_listener is not None

    # Trigger the listener
    event = MagicMock()
    captured_listener(event)

    # Verify task created
    mock_coordinator.config_entry.async_create_background_task.assert_called_once()


def test_is_light_on(reporter: EnvironmentReporter) -> None:
    """Test _is_light_on logic."""
    assert reporter._is_light_on(State("s.l", STATE_ON)) is True
    assert reporter._is_light_on(State("s.l", STATE_OFF)) is False
    assert reporter._is_light_on(State("s.l", "100")) is True
    assert reporter._is_light_on(State("s.l", "0")) is False
    assert reporter._is_light_on(State("s.l", "invalid")) is False


async def test_handle_light_change_invalid_states(
    reporter: EnvironmentReporter,
) -> None:
    """Test _handle_light_change with invalid states."""
    # None states
    await reporter._handle_light_change(GROWSPACE_ID, None, State("s.l", STATE_ON))
    await reporter._handle_light_change(GROWSPACE_ID, State("s.l", STATE_OFF), None)

    # Unknown/Unavailable
    await reporter._handle_light_change(
        GROWSPACE_ID, State("s.l", STATE_UNKNOWN), State("s.l", STATE_ON)
    )
    await reporter._handle_light_change(
        GROWSPACE_ID, State("s.l", STATE_OFF), State("s.l", STATE_UNAVAILABLE)
    )

    # Verify no action taken (check if start time updated for next period - it shouldn't for invalid)
    # But wait, start times are only updated on valid transitions.
    # We can check if _generate_report was called
    with patch.object(reporter, "_generate_report") as mock_report:
        await reporter._handle_light_change(
            GROWSPACE_ID, State("s.l", STATE_UNKNOWN), State("s.l", STATE_ON)
        )
        mock_report.assert_not_called()


async def test_handle_light_change_no_logical_change(
    reporter: EnvironmentReporter,
) -> None:
    """Test change with no logical state change (e.g. brightness only)."""
    await reporter._handle_light_change(
        GROWSPACE_ID, State("s.l", "50"), State("s.l", "100")
    )
    # Assuming start time tracked
    assert GROWSPACE_ID not in reporter._state_start_times


async def test_handle_light_change_first_transition(
    reporter: EnvironmentReporter,
) -> None:
    """Test first transition (just tracks start time)."""
    # clear init start time
    reporter._state_start_times.clear()

    now = dt_util.utcnow()
    with patch(
        "custom_components.growspace_manager.services.environment_reporter.dt_util.utcnow",
        return_value=now,
    ):
        await reporter._handle_light_change(
            GROWSPACE_ID, State("s.l", STATE_OFF), State("s.l", STATE_ON)
        )

    assert reporter._state_start_times[GROWSPACE_ID] == now
    # Report generation skipped


async def test_handle_light_change_short_cycle(reporter: EnvironmentReporter) -> None:
    """Test short cycle is ignored."""
    now = dt_util.utcnow()
    reporter._state_start_times[GROWSPACE_ID] = now - timedelta(minutes=10)

    with (
        patch(
            "custom_components.growspace_manager.services.environment_reporter.dt_util.utcnow",
            return_value=now,
        ),
        patch.object(reporter, "_generate_report") as mock_report,
    ):
        await reporter._handle_light_change(
            GROWSPACE_ID, State("s.l", STATE_ON), State("s.l", STATE_OFF)
        )

        mock_report.assert_not_called()
        # Start time updated
        assert reporter._state_start_times[GROWSPACE_ID] == now


async def test_handle_light_change_valid_cycle(reporter: EnvironmentReporter) -> None:
    """Test valid cycle generates report."""
    now = dt_util.utcnow()
    start = now - timedelta(hours=12)
    reporter._state_start_times[GROWSPACE_ID] = start

    with (
        patch(
            "custom_components.growspace_manager.services.environment_reporter.dt_util.utcnow",
            return_value=now,
        ),
        patch.object(reporter, "_generate_report") as mock_report,
    ):
        await reporter._handle_light_change(
            GROWSPACE_ID, State("s.l", STATE_OFF), State("s.l", STATE_ON)
        )

        mock_report.assert_awaited_once_with(GROWSPACE_ID, "night_report", start, now)
        assert reporter._state_start_times[GROWSPACE_ID] == now


async def test_get_sensor_stats_no_data(
    reporter: EnvironmentReporter, mock_hass: MagicMock
) -> None:
    """Test get_sensor_stats with no data."""
    mock_hass.async_add_executor_job.return_value = {}

    result = await reporter._get_sensor_stats(
        "sensor.test", dt_util.utcnow(), dt_util.utcnow()
    )
    assert result is None


async def test_get_sensor_stats_valid(
    reporter: EnvironmentReporter, mock_hass: MagicMock
) -> None:
    """Test get_sensor_stats with valid data."""
    s1 = State("sensor.test", "20")
    s2 = State("sensor.test", "22")
    mock_hass.async_add_executor_job.return_value = {"sensor.test": [s1, s2]}

    mock_hass.states.get.return_value = MagicMock(
        attributes={"unit_of_measurement": "°C"}
    )

    result = await reporter._get_sensor_stats(
        "sensor.test", dt_util.utcnow(), dt_util.utcnow()
    )
    assert result == "21.0°C"


async def test_get_sensor_stats_filtered(
    reporter: EnvironmentReporter, mock_hass: MagicMock
) -> None:
    """Test get_sensor_stats filters invalid states."""
    s1 = State("sensor.test", "20")
    s2 = State("sensor.test", "unknown")
    s3 = State("sensor.test", "invalid")
    mock_hass.async_add_executor_job.return_value = {"sensor.test": [s1, s2, s3]}

    mock_hass.states.get.return_value = MagicMock(attributes={})

    result = await reporter._get_sensor_stats(
        "sensor.test", dt_util.utcnow(), dt_util.utcnow()
    )
    assert result == "20.0"


async def test_get_sensor_stats_all_invalid(
    reporter: EnvironmentReporter, mock_hass: MagicMock
) -> None:
    """Test get_sensor_stats with only invalid data."""
    s1 = State("sensor.test", "unknown")
    s2 = State("sensor.test", "unavailable")
    mock_hass.async_add_executor_job.return_value = {"sensor.test": [s1, s2]}

    result = await reporter._get_sensor_stats(
        "sensor.test", dt_util.utcnow(), dt_util.utcnow()
    )
    assert result is None


async def test_generate_report_success(
    reporter: EnvironmentReporter, mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test report generation success."""
    with patch.object(
        reporter, "_get_sensor_stats", side_effect=["25°C", "50%", "1.2kPa"]
    ):
        await reporter._generate_report(
            GROWSPACE_ID, "day_report", dt_util.utcnow(), dt_util.utcnow()
        )

        mock_hass.bus.async_fire.assert_called_once()
        args = mock_hass.bus.async_fire.call_args[0]
        assert args[0] == EVENT_GROWSPACE_LOG_ENTRY
        data = args[1]
        assert data["growspace_id"] == GROWSPACE_ID
        assert data["sensor_type"] == "day_report"
        assert "Temperature: 25°C" in data["reasons"]


async def test_generate_report_missing_growspace(
    reporter: EnvironmentReporter, mock_coordinator: MagicMock, mock_hass: MagicMock
) -> None:
    """Test report generation for missing growspace."""
    mock_coordinator.growspaces = {}
    await reporter._generate_report(
        GROWSPACE_ID, "day_report", dt_util.utcnow(), dt_util.utcnow()
    )
    mock_hass.bus.async_fire.assert_not_called()


async def test_generate_report_no_stats(
    reporter: EnvironmentReporter, mock_hass: MagicMock
) -> None:
    """Test report generation when no stats available."""
    with patch.object(reporter, "_get_sensor_stats", return_value=None):
        await reporter._generate_report(
            GROWSPACE_ID, "day_report", dt_util.utcnow(), dt_util.utcnow()
        )
        mock_hass.bus.async_fire.assert_not_called()


async def test_generate_report_no_sensors_configured(
    reporter: EnvironmentReporter, mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test report generation with no sensors configured."""
    mock_coordinator.growspaces[GROWSPACE_ID].environment_config = EnvironmentConfig()

    await reporter._generate_report(
        GROWSPACE_ID, "day_report", dt_util.utcnow(), dt_util.utcnow()
    )
    mock_hass.bus.async_fire.assert_not_called()


async def test_generate_report_partial_sensors(
    reporter: EnvironmentReporter, mock_hass: MagicMock, mock_coordinator: MagicMock
) -> None:
    """Test report generation with some sensors missing."""
    mock_coordinator.growspaces[GROWSPACE_ID].environment_config = EnvironmentConfig(
        temperature_sensor="sensor.temp",
        humidity_sensor=None,
        vpd_sensor=None,
    )

    with patch.object(reporter, "_get_sensor_stats", return_value="25°C"):
        await reporter._generate_report(
            GROWSPACE_ID, "day_report", dt_util.utcnow(), dt_util.utcnow()
        )

        mock_hass.bus.async_fire.assert_called_once()
        data = mock_hass.bus.async_fire.call_args[0][1]
        assert data["reasons"] == ["Temperature: 25°C"]


def test_unload(reporter: EnvironmentReporter) -> None:
    """Test unload."""
    mock_unsub = MagicMock()
    reporter._unsub_listeners["gs1"] = mock_unsub

    reporter.unload()

    mock_unsub.assert_called_once()
    assert reporter._unsub_listeners == {}
