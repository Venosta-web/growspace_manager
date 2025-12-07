"""Tests for the VWC Irrigation Coordinator."""

import asyncio
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager.models import (
    Growspace,
    IrrigationStrategy,
)
from custom_components.growspace_manager.vwc_irrigation_coordinator import (
    VWCIrrigationCoordinator,
)


# Patch asyncio.sleep globally for this test module to avoid lingering tasks
@pytest.fixture(autouse=True)
def mock_sleep():
    with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
        yield mock_sleep


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states = MagicMock()
    # Schedule the coroutine on the loop to avoid "never awaited" warning and actually run it
    hass.async_create_task = MagicMock(side_effect=asyncio.create_task)
    return hass


@pytest.fixture
def mock_growspace():
    growspace = Growspace(
        id="gs1",
        name="Test Growspace",
        environment_config={"soil_moisture_sensor": "sensor.moisture"},
        irrigation_config={"irrigation_pump_entity": "switch.pump"},
    )
    growspace.irrigation_strategy = IrrigationStrategy(
        enabled=True,
        lights_on_time="08:00:00",
        p0_duration_minutes=60,  # Ends 09:00
        target_vwc_percent=50.0,
        maintenance_dryback_percent=2.0,
        shot_duration_seconds=10,
        shot_interval_minutes=15,
        p2_stop_before_lights_off_minutes=120,  # Lights off 20:00 (12h default) -> Stop 18:00
    )
    return growspace


@pytest.fixture
def mock_main_coordinator(mock_growspace):
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    coordinator.add_event = MagicMock()
    return coordinator


async def await_pump_task():
    """Find and await the pump cycle task."""
    # Give the loop a moment to start the task
    await asyncio.sleep(0)

    tasks = asyncio.all_tasks()
    for task in tasks:
        if "VWCIrrigationCoordinator._run_pump_cycle" in str(task.get_coro()):
            await task
            return
    # If not found, that's okay, maybe it finished instantly or didn't start (if logic was wrong)
    # But for our tests expecting watering, it should be found unless we are too slow/fast.


@pytest.fixture
def vwc_coordinator(mock_hass, mock_main_coordinator):
    return VWCIrrigationCoordinator(
        mock_hass, MagicMock(), "gs1", mock_main_coordinator
    )


async def test_p0_activation(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test P0 phase (Activation) - No watering."""
    # Time: 08:30 (Inside P0)
    now = datetime(2023, 1, 1, 8, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Sensor value low, but P0 shouldn't water
        mock_hass.states.get.return_value = MagicMock(state="40.0")

        await vwc_coordinator._update_loop(now)

        assert vwc_coordinator._current_phase == "P0 - Activation"
        mock_hass.services.async_call.assert_not_called()


async def test_p1_ramp_up(vwc_coordinator, mock_hass) -> None:
    """Test P1 phase (Ramp Up) - Watering until target."""
    # Time: 09:30 (Inside P1)
    now = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Sensor value: 40% (Target 50%) -> Should Water
        mock_hass.states.get.return_value = MagicMock(state="40.0")

        await vwc_coordinator._update_loop(now)
        await await_pump_task()

        assert vwc_coordinator._current_phase == "P1 - Ramp Up"
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
        )


async def test_p1_target_reached(vwc_coordinator, mock_hass) -> None:
    """Test switching from P1 to P2 when target reached."""
    now = datetime(2023, 1, 1, 9, 30, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Sensor value: 50% (Target 50%) -> Target Reached
        mock_hass.states.get.return_value = MagicMock(state="50.0")

        await vwc_coordinator._update_loop(now)

        # Should NOT water, but advance internal state
        assert vwc_coordinator._target_reached_today is True
        mock_hass.services.async_call.assert_not_called()


async def test_p2_maintenance(vwc_coordinator, mock_hass) -> None:
    """Test P2 phase - Water only on dryback."""
    # Set internal state to target reached
    vwc_coordinator._target_reached_today = True

    now = datetime(2023, 1, 1, 12, 0, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Case A: VWC 49% (Target 50%, Dryback 2% -> Trigger at 48%)
        # 49 > 48 -> No Water
        mock_hass.states.get.return_value = MagicMock(state="49.0")
        await vwc_coordinator._update_loop(now)
        mock_hass.services.async_call.assert_not_called()
        assert vwc_coordinator._current_phase == "P2 - Maintenance"

        # Case B: VWC 47% (Below 48%) -> Water
        mock_hass.states.get.return_value = MagicMock(state="47.0")
        await vwc_coordinator._update_loop(now)
        await await_pump_task()
        mock_hass.services.async_call.assert_any_call(
            "switch", "turn_on", {"entity_id": "switch.pump"}, blocking=True
        )


async def test_p3_dryback(vwc_coordinator, mock_hass) -> None:
    """Test P3 phase (Dry Back) - Hard stop."""
    # Time: 19:00 (Lights off 20:00, Stop 18:00 -> Inside P3)
    now = datetime(2023, 1, 1, 19, 0, 0, tzinfo=dt_util.UTC)

    with patch(
        "custom_components.growspace_manager.vwc_irrigation_coordinator.now",
        return_value=now,
    ):
        # Even if very dry, should NOT water
        mock_hass.states.get.return_value = MagicMock(state="30.0")

        await vwc_coordinator._update_loop(now)

        assert "P3" in vwc_coordinator._current_phase
        mock_hass.services.async_call.assert_not_called()


async def test_missing_sensor(vwc_coordinator, mock_hass, mock_growspace) -> None:
    """Test handling of missing sensor."""
    mock_growspace.environment_config = {}  # No sensor

    now = datetime(2023, 1, 1, 10, 0, 0, tzinfo=dt_util.UTC)

    await vwc_coordinator._update_loop(now)

    assert vwc_coordinator._current_phase == "Disabled (No Sensor)"
    mock_hass.services.async_call.assert_not_called()
