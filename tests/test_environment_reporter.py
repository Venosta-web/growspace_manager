"""Tests for the EnvironmentReporter service."""

import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.growspace_manager.const import EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import EnvironmentConfig, Growspace
from custom_components.growspace_manager.services.environment_reporter import (
    EnvironmentReporter,
)
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.util import dt as dt_util


@pytest.fixture
def mock_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.hass = hass
    coordinator.growspaces = {}
    return coordinator


class TestEnvironmentReporter:
    """Test suite for EnvironmentReporter."""

    @pytest.mark.asyncio
    async def test_initialization(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test initialization of the reporter."""
        reporter = EnvironmentReporter(hass, mock_coordinator)
        assert reporter.hass == hass
        assert reporter.coordinator == mock_coordinator
        assert reporter._unsub_listeners == {}
        assert reporter._state_start_times == {}

    @pytest.mark.asyncio
    async def test_async_initialize_with_growspaces(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test async_initialize setups listeners for growspaces."""
        # Setup growspaces with light sensors
        gs1 = Growspace(
            id="gs1",
            name="Growspace 1",
            environment_config=EnvironmentConfig(light_sensors=["sensor.light_1"]),
        )
        gs2 = Growspace(
            id="gs2",
            name="Growspace 2",
            environment_config=EnvironmentConfig(light_sensors=["sensor.light_2"]),
        )
        mock_coordinator.growspaces = {"gs1": gs1, "gs2": gs2}

        reporter = EnvironmentReporter(hass, mock_coordinator)

        with patch(
            "custom_components.growspace_manager.services.environment_reporter.async_track_state_change_event"
        ) as mock_track:
            await reporter.async_initialize()

            # Should track both sensors
            assert mock_track.call_count == 2
            assert "gs1" in reporter._unsub_listeners
            assert "gs2" in reporter._unsub_listeners

            # Should initialize state start times
            assert "gs1" in reporter._state_start_times
            assert "gs2" in reporter._state_start_times

    @pytest.mark.asyncio
    async def test_setup_growspace_listener_missing_sensor(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test listener setup skips growspaces without light sensor."""
        gs1 = Growspace(
            id="gs1",
            name="Growspace 1",
            environment_config=EnvironmentConfig(light_sensors=[]),
        )
        mock_coordinator.growspaces = {"gs1": gs1}

        reporter = EnvironmentReporter(hass, mock_coordinator)

        with patch(
            "custom_components.growspace_manager.services.environment_reporter.async_track_state_change_event"
        ) as mock_track:
            await reporter._setup_growspace_listener("gs1")

            assert mock_track.call_count == 0
            assert "gs1" not in reporter._unsub_listeners

    @pytest.mark.asyncio
    async def test_setup_growspace_listener_missing_growspace(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test listener setup handles missing growspace ID."""
        mock_coordinator.growspaces = {}
        reporter = EnvironmentReporter(hass, mock_coordinator)

        await reporter._setup_growspace_listener("missing_id")
        assert "missing_id" not in reporter._unsub_listeners

    @pytest.mark.asyncio
    async def test_setup_listener_cleanup(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test setting up a listener cleans up existing ones."""
        gs1 = Growspace(
            id="gs1",
            name="Growspace 1",
            environment_config=EnvironmentConfig(light_sensors=["sensor.light_1"]),
        )
        mock_coordinator.growspaces = {"gs1": gs1}

        reporter = EnvironmentReporter(hass, mock_coordinator)
        mock_unsub = MagicMock()
        reporter._unsub_listeners["gs1"] = mock_unsub

        with patch(
            "custom_components.growspace_manager.services.environment_reporter.async_track_state_change_event"
        ):
            await reporter._setup_growspace_listener("gs1")

            mock_unsub.assert_called_once()
            assert "gs1" in reporter._unsub_listeners

    def test_is_light_on(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test is_light_on Logic."""
        reporter = EnvironmentReporter(hass, mock_coordinator)

        # Binary states
        assert reporter._is_light_on(State("sensor.light", STATE_ON)) is True
        assert reporter._is_light_on(State("sensor.light", STATE_OFF)) is False

        # Numeric states (brightness/power)
        assert reporter._is_light_on(State("sensor.light", "10.5")) is True
        assert reporter._is_light_on(State("sensor.light", "0.0")) is False
        assert reporter._is_light_on(State("sensor.light", "0")) is False

        # Invalid numeric
        assert reporter._is_light_on(State("sensor.light", "invalid")) is False

        # Unknown/Unavailable are not strictly checked here (caller handles),
        # but fall through to False via ValueError/TypeError path
        assert reporter._is_light_on(State("sensor.light", STATE_UNKNOWN)) is False
        assert reporter._is_light_on(State("sensor.light", STATE_UNAVAILABLE)) is False

    @pytest.mark.asyncio
    async def test_handle_light_change_invalid_states(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test handle_light_change exits early on invalid states."""
        reporter = EnvironmentReporter(hass, mock_coordinator)

        # None states
        await reporter._handle_light_change("gs1", None, State("sensor.test", STATE_ON))
        await reporter._handle_light_change("gs1", State("sensor.test", STATE_ON), None)

        # Unknown/Unavailable states
        await reporter._handle_light_change(
            "gs1", State("sensor.test", STATE_UNKNOWN), State("sensor.test", STATE_ON)
        )
        await reporter._handle_light_change(
            "gs1",
            State("sensor.test", STATE_ON),
            State("sensor.test", STATE_UNAVAILABLE),
        )

        # Should not generate any report (requires more setup to verify call count, see below)

    @pytest.mark.asyncio
    async def test_handle_light_change_no_logical_change(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test update ignored if logical state (ON/OFF) hasn't changed."""
        reporter = EnvironmentReporter(hass, mock_coordinator)

        # ON -> ON (e.g. brightness change)
        with patch.object(reporter, "_generate_report") as mock_report:
            await reporter._handle_light_change(
                "gs1", State("sensor.test", STATE_ON), State("sensor.test", STATE_ON)
            )
            mock_report.assert_not_called()

        # Numeric logical check: 10 -> 20 (Both > 0, so both ON)
        with patch.object(reporter, "_generate_report") as mock_report:
            await reporter._handle_light_change(
                "gs1", State("sensor.test", "10"), State("sensor.test", "20")
            )
            mock_report.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_light_change_generates_report(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test switching states generates report."""
        reporter = EnvironmentReporter(hass, mock_coordinator)

        now = dt_util.utcnow()
        start_time = now - datetime.timedelta(hours=12)
        reporter._state_start_times["gs1"] = start_time

        with patch.object(reporter, "_generate_report") as mock_report:
            # ON -> OFF should generate DAY report (was_on=True)
            await reporter._handle_light_change(
                "gs1", State("sensor.test", STATE_ON), State("sensor.test", STATE_OFF)
            )

            mock_report.assert_awaited_once()
            args = mock_report.call_args[0]
            assert args[0] == "gs1"
            assert args[1] == "day_report"
            assert args[2] == start_time
            # End time is approximately now
            assert (args[3] - now).total_seconds() < 1

            # Start time update verification
            assert reporter._state_start_times["gs1"] != start_time

    @pytest.mark.asyncio
    async def test_handle_light_change_generates_night_report(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test OFF->ON generates NIGHT report."""
        reporter = EnvironmentReporter(hass, mock_coordinator)

        now = dt_util.utcnow()
        start_time = now - datetime.timedelta(hours=12)
        reporter._state_start_times["gs1"] = start_time

        with patch.object(reporter, "_generate_report") as mock_report:
            # OFF -> ON (was_on=False)
            await reporter._handle_light_change(
                "gs1", State("sensor.test", STATE_OFF), State("sensor.test", STATE_ON)
            )

            mock_report.assert_awaited_once()
            assert mock_report.call_args[0][1] == "night_report"

    @pytest.mark.asyncio
    async def test_handle_light_change_skips_short_cycles(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test cycles < 30 mins are ignored."""
        reporter = EnvironmentReporter(hass, mock_coordinator)

        now = dt_util.utcnow()
        start_time = now - datetime.timedelta(minutes=10)  # Too short
        reporter._state_start_times["gs1"] = start_time

        with patch.object(reporter, "_generate_report") as mock_report:
            await reporter._handle_light_change(
                "gs1", State("sensor.test", STATE_ON), State("sensor.test", STATE_OFF)
            )

            mock_report.assert_not_called()
            # Start time should still update though
            assert reporter._state_start_times["gs1"] != start_time

    @pytest.mark.asyncio
    async def test_handle_light_change_first_transition(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test first transition only sets start time, no report."""
        reporter = EnvironmentReporter(hass, mock_coordinator)
        # No previous start time
        if "gs1" in reporter._state_start_times:
            del reporter._state_start_times["gs1"]

        with patch.object(reporter, "_generate_report") as mock_report:
            await reporter._handle_light_change(
                "gs1", State("sensor.test", STATE_ON), State("sensor.test", STATE_OFF)
            )

            mock_report.assert_not_called()
            assert "gs1" in reporter._state_start_times

    @pytest.mark.asyncio
    async def test_get_sensor_stats_basic(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test basic stat calculation."""
        reporter = EnvironmentReporter(hass, mock_coordinator)
        t1 = dt_util.utcnow()
        t2 = t1 + datetime.timedelta(hours=1)

        # Mock history states
        mock_states = [
            State("sensor.temp", "20.0"),
            State("sensor.temp", "22.0"),
            State("sensor.temp", "21.0"),
        ]

        hass.states.async_set("sensor.temp", "21.0", {"unit_of_measurement": "°C"})

        # We patch async_add_executor_job to return immediately without threads
        mock_exec = AsyncMock(return_value={"sensor.temp": mock_states})

        with patch.object(hass, "async_add_executor_job", side_effect=mock_exec):
            result = await reporter._get_sensor_stats("sensor.temp", t1, t2)

            # (20+22+21)/3 = 21.0
            assert result == "21.0°C"

    @pytest.mark.asyncio
    async def test_get_sensor_stats_unavailable_values(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test stats filters out unavailable/invalid values."""
        reporter = EnvironmentReporter(hass, mock_coordinator)
        t1 = dt_util.utcnow()
        t2 = t1 + datetime.timedelta(hours=1)

        mock_states = [
            State("sensor.val", "10.0"),
            State("sensor.val", STATE_UNAVAILABLE),
            State("sensor.val", "invalid"),
            State("sensor.val", "20.0"),
        ]

        mock_exec = AsyncMock(return_value={"sensor.val": mock_states})

        with patch.object(hass, "async_add_executor_job", side_effect=mock_exec):
            # (10+20)/2 = 15.0
            result = await reporter._get_sensor_stats("sensor.val", t1, t2)
            # No unit set
            assert result == "15.0"

    @pytest.mark.asyncio
    async def test_get_sensor_stats_no_data(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test stats returning None when no data."""
        reporter = EnvironmentReporter(hass, mock_coordinator)
        t1 = dt_util.utcnow()
        t2 = t1 + datetime.timedelta(hours=1)

        with patch.object(
            hass, "async_add_executor_job", new_callable=AsyncMock
        ) as mock_exec:
            # Case 1: No history
            mock_exec.return_value = {}
            assert await reporter._get_sensor_stats("sensor.val", t1, t2) is None

            # Case 2: History exists but all invalid
            mock_exec.return_value = {"sensor.val": [State("sensor.val", "unknown")]}
            assert await reporter._get_sensor_stats("sensor.val", t1, t2) is None

    @pytest.mark.asyncio
    async def test_generate_report_successful(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test generating a detailed report."""
        gs1 = Growspace(
            id="gs1",
            name="GS1",
            environment_config=EnvironmentConfig(
                temperature_sensor="sensor.temp",
                humidity_sensor="sensor.hum",
                vpd_sensor="sensor.vpd",
            ),
        )
        mock_coordinator.growspaces = {"gs1": gs1}
        reporter = EnvironmentReporter(hass, mock_coordinator)

        t1 = dt_util.utcnow()
        t2 = t1 + datetime.timedelta(hours=12)

        events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

        with patch.object(reporter, "_get_sensor_stats") as mock_stats:
            mock_stats.side_effect = ["25.0°C", "60.0%", "1.2kPa"]

            await reporter._generate_report("gs1", "day_report", t1, t2)

            assert len(events) == 1
            data = events[0].data
            assert data["category"] == "environmental_report"
            assert data["sensor_type"] == "day_report"
            assert data["growspace_id"] == "gs1"
            assert len(data["reasons"]) == 3
            assert "Temperature: 25.0°C" in data["reasons"]

    @pytest.mark.asyncio
    async def test_generate_report_missing_sensors(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test report skips if no sensors configured."""
        gs1 = Growspace(
            id="gs1",
            name="GS1",
            environment_config=EnvironmentConfig(),  # No sensors
        )
        mock_coordinator.growspaces = {"gs1": gs1}
        reporter = EnvironmentReporter(hass, mock_coordinator)

        events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

        await reporter._generate_report(
            "gs1", "day_report", dt_util.utcnow(), dt_util.utcnow()
        )
        assert len(events) == 0

    @pytest.mark.asyncio
    async def test_generate_report_no_stats_available(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test report skips if no stats could be calculated."""
        gs1 = Growspace(
            id="gs1",
            name="GS1",
            environment_config=EnvironmentConfig(temperature_sensor="sensor.bad"),
        )
        mock_coordinator.growspaces = {"gs1": gs1}
        reporter = EnvironmentReporter(hass, mock_coordinator)

        events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

        with patch.object(reporter, "_get_sensor_stats", return_value=None):
            await reporter._generate_report(
                "gs1", "day_report", dt_util.utcnow(), dt_util.utcnow()
            )
            assert len(events) == 0

    def test_unload(
        self, hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test unload cleans up listeners."""
        reporter = EnvironmentReporter(hass, mock_coordinator)
        mock_unsub = MagicMock()
        reporter._unsub_listeners["gs1"] = mock_unsub

        reporter.unload()

        mock_unsub.assert_called_once()
        assert reporter._unsub_listeners == {}
