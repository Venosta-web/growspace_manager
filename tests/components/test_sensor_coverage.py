"""Additional tests for sensor.py to reach 100% coverage."""

from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.sensor import (
    GrowspaceListSensor,
    _async_create_derivative_sensors,
)


@pytest.mark.asyncio
async def test_async_create_derivative_sensors_skips_none():
    """Test that _async_create_derivative_sensors skips None source sensors (Line 116)."""
    hass = MagicMock()
    config_entry = Mock()
    config_entry.runtime_data = Mock()
    config_entry.runtime_data.created_entity_ids = []

    growspace = Mock()
    growspace.id = "gs_test"
    growspace.name = "Test GS"
    # Provide a list with None to trigger Line 116
    growspace.environment_config = {
        "temperature_sensors": [None, "sensor.valid_temp"],
        "humidity_sensors": [],
        "vpd_sensors": [],
    }

    with patch(
        "custom_components.growspace_manager.sensor.async_setup_trend_sensor",
        new_callable=AsyncMock,
    ) as mock_trend:
        # We also need to patch async_setup_statistics_sensor because it's called after trend
        with patch(
            "custom_components.growspace_manager.sensor.async_setup_statistics_sensor",
            new_callable=AsyncMock,
        ):
            await _async_create_derivative_sensors(hass, config_entry, growspace)

            # Verify it was called for the valid sensor but not for None
            # Metric map has 3 sensors. temperature has [None, "sensor.valid_temp"].
            # i=0, source_sensor=None -> continue
            # i=1, source_sensor="sensor.valid_temp" -> setup
            mock_trend.assert_any_call(
                hass, "sensor.valid_temp", "gs_test", "Test GS 2", "temperature"
            )


def test_growspace_list_sensor_native_value(mock_coordinator):
    """Test GrowspaceListSensor.native_value to cover lines 918-919."""
    # Populate coordinator with at least one growspace
    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}

    sensor = GrowspaceListSensor(mock_coordinator)

    # Initially coordinator has 1 gs
    assert sensor.native_value == 1

    # Add another gs to coordinator
    mock_coordinator.growspaces["gs2"] = Mock(name="Growspace 2")

    # native_value should call _update_growspaces and return 2
    assert sensor.native_value == 2
