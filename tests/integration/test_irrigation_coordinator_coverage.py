"""Additional tests for irrigation_coordinator coverage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.irrigation_coordinator import (
    BaseIrrigationCoordinator,
    IrrigationCoordinator,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

GROWSPACE_ID = "test_growspace"
ENTRY_ID = "test_entry_id"


@pytest.fixture
def mock_main_coordinator() -> MagicMock:
    """Mock the main GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Test Growspace",
            notification_target="notify.test",
            irrigation_config=IrrigationConfig(
                irrigation_pump_entity="switch.irrigation_pump",
                drain_pump_entity="switch.drain_pump",
                irrigation_duration=30,
                drain_duration=60,
                irrigation_times=[{"time": "10:00:00"}],
                drain_times=[{"time": "12:00:00"}],
            ),
        )
    }
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh_growspace_data = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    coordinator.add_event = MagicMock()
    return coordinator


@pytest.fixture
def mock_hass(mock_main_coordinator) -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.services = AsyncMock()
    hass.async_create_task = asyncio.create_task
    type(hass).loop = property(lambda self: asyncio.get_running_loop())
    hass.data = {DOMAIN: {}}
    hass.states = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.options = {}
    entry.entry_id = ENTRY_ID
    entry.runtime_data = MagicMock()
    entry.options = {}
    return entry


async def test_base_coordinator_async_request_refresh(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test base class async_request_refresh (pass statement)."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Should not raise
    await coordinator.async_request_refresh()


async def test_base_coordinator_async_setup(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test base class async_setup (pass statement)."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Should not raise
    await coordinator.async_setup()


async def test_base_coordinator_async_unload(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test base class async_unload."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )
    # Add a listener
    coordinator._listeners.append(MagicMock())

    await coordinator.async_unload()

    # Listeners should be cancelled
    assert len(coordinator._listeners) == 0


async def test_get_sensor_value_valid(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with valid sensor."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock state
    mock_state = MagicMock()
    mock_state.state = "25.5"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value == 25.5


async def test_get_sensor_value_unknown(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with unknown state."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock unknown state
    mock_state = MagicMock()
    mock_state.state = "unknown"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_get_sensor_value_unavailable(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with unavailable state."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock unavailable state
    mock_state = MagicMock()
    mock_state.state = "unavailable"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_get_sensor_value_invalid_float(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with invalid float value."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock invalid float state
    mock_state = MagicMock()
    mock_state.state = "not_a_number"
    mock_hass.states.get.return_value = mock_state

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_get_sensor_value_no_state(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test _get_sensor_value with no state."""
    coordinator = BaseIrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock no state
    mock_hass.states.get.return_value = None

    value = coordinator._get_sensor_value("sensor.test")
    assert value is None


async def test_async_request_refresh_override(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test IrrigationCoordinator async_request_refresh override."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    with patch.object(
        coordinator, "async_update_listeners", new_callable=AsyncMock
    ) as mock_update:
        await coordinator.async_request_refresh()
        mock_update.assert_awaited_once()


async def test_async_set_settings_unknown_key(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test async_set_settings with unknown setting key."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    new_settings = {
        "irrigation_duration": 45,
        "unknown_setting": "value",  # This should trigger warning
    }

    with patch.object(coordinator, "async_update_listeners", new_callable=AsyncMock):
        await coordinator.async_set_settings(new_settings)

        # Verify valid setting was applied
        growspace = coordinator._main_coordinator.growspaces[GROWSPACE_ID]
        assert growspace.irrigation_config.irrigation_duration == 45


async def test_async_add_schedule_item_invalid_key(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test async_add_schedule_item with invalid schedule key."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Should return early without raising
    await coordinator.async_add_schedule_item("invalid_schedule_key", "10:00", 30)

    # Should not save
    mock_main_coordinator.async_save.assert_not_awaited()


async def test_run_pump_cycle_event_logging_exception(
    mock_hass: MagicMock, mock_config_entry: MagicMock, mock_main_coordinator: MagicMock
) -> None:
    """Test exception handling in event logging during pump cycle."""
    coordinator = IrrigationCoordinator(
        mock_hass, mock_config_entry, GROWSPACE_ID, mock_main_coordinator
    )

    # Mock add_event to raise exception
    mock_main_coordinator.add_event.side_effect = Exception("Event logging failed")

    with patch("asyncio.sleep", new_callable=AsyncMock):
        mock_config_entry.runtime_data = mock_main_coordinator

        # Should not raise, exception is caught and logged
        await coordinator._run_pump_cycle(
            "irrigation", "switch.irrigation_pump", 30, {"time": "10:00:00"}
        )

        # Pump should still be turned off
        mock_hass.services.async_call.assert_any_call(
            "switch",
            "turn_off",
            {"entity_id": "switch.irrigation_pump"},
            blocking=True,
        )
