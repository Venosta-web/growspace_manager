"""Tests for the Irrigation Config Handler."""

from dataclasses import asdict, dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.config_handlers.irrigation_config_handler import (
    IrrigationConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant


@dataclass
class MockIrrigationConfig:
    irrigation_pump_entity: str | None = None
    drain_pump_entity: str | None = None
    irrigation_duration: int = 30
    drain_duration: int = 30
    use_vwc_steering: bool = False
    lights_on_time: str = "06:00:00"
    target_vwc_percent: float = 55.0
    p0_duration_minutes: int = 60
    shot_duration_seconds: int = 10
    shot_interval_minutes: int = 15
    maintenance_dryback_percent: float = 2.0
    p2_stop_before_lights_off_minutes: int = 120
    irrigation_times: list = None
    drain_times: list = None


@dataclass
class MockGrowspace:
    id: str
    name: str
    irrigation_config: MockIrrigationConfig


@pytest.fixture
def mock_hass() -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {DOMAIN: {}}
    return hass


@pytest.fixture
def mock_config_entry() -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.entry_id = "test_entry"
    entry.runtime_data = MagicMock()
    return entry


@pytest.fixture
def handler(
    mock_hass: MagicMock, mock_config_entry: MagicMock
) -> IrrigationConfigHandler:
    """Create an IrrigationConfigHandler instance."""
    handler = IrrigationConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.selected_growspace_id = "gs1"
    handler.flow.current_options = {}
    return handler


async def test_async_step_select_growspace_for_irrigation_abort_no_entry(
    mock_hass: MagicMock,
) -> None:
    handler = IrrigationConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_select_growspace_for_irrigation()
    assert result == {"type": "abort"}


async def test_async_step_select_growspace_for_irrigation_no_growspaces(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspace_service.get_sorted_growspace_options.return_value = []
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_select_growspace_for_irrigation()
    assert result == {"type": "abort"}
    handler.flow.async_abort.assert_called_with(reason="no_growspaces")


async def test_async_step_select_growspace_for_irrigation_get(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspace_service.get_sorted_growspace_options.return_value = [
        ("gs1", "GS1")
    ]
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_select_growspace_for_irrigation()
    assert result["type"] == "form"


async def test_async_step_select_growspace_for_irrigation_post(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspace_service.get_sorted_growspace_options.return_value = [
        ("gs1", "GS1")
    ]
    handler.async_step_configure_irrigation = AsyncMock(return_value={"type": "form"})
    result = await handler.async_step_select_growspace_for_irrigation(
        {"growspace_id": "gs1"}
    )
    assert result["type"] == "form"
    assert handler.flow.selected_growspace_id == "gs1"


async def test_async_step_configure_irrigation_errors(
    handler: IrrigationConfigHandler,
) -> None:
    # No entry
    handler.config_entry = None
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_configure_irrigation()
    assert result == {"type": "abort"}

    # Restore entry, no growspace
    handler.config_entry = MagicMock()
    handler.config_entry.runtime_data.growspaces = {}
    result = await handler.async_step_configure_irrigation()
    assert result == {"type": "abort"}


async def test_async_steps_no_coordinator(handler: IrrigationConfigHandler) -> None:
    handler.config_entry.runtime_data = None
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    assert await handler.async_step_select_growspace_for_irrigation() == {
        "type": "abort"
    }
    assert await handler.async_step_configure_irrigation() == {"type": "abort"}
    assert await handler.async_step_irrigation_overview() == {"type": "abort"}


async def test_async_step_irrigation_overview_success(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    growspace = MockGrowspace(
        id="gs1", name="GS1", irrigation_config=MockIrrigationConfig()
    )
    coordinator.growspaces = {"gs1": growspace}
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})

    result = await handler.async_step_irrigation_overview()
    assert result["type"] == "form"


async def test_async_step_irrigation_overview_post(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    growspace = MockGrowspace(
        id="gs1", name="GS1", irrigation_config=MockIrrigationConfig()
    )
    coordinator.growspaces = {"gs1": growspace}
    coordinator.async_update_irrigation_config = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    user_input = {"irrigation_duration": 40}
    result = await handler.async_step_irrigation_overview(user_input)
    assert result["type"] == "create_entry"
    coordinator.async_update_irrigation_config.assert_called_once_with(
        "gs1", user_input
    )


async def test_get_irrigation_overview_schema_vwc(
    handler: IrrigationConfigHandler,
) -> None:
    options = asdict(MockIrrigationConfig(use_vwc_steering=True))
    schema = handler.get_irrigation_overview_schema(options, "gs1")
    assert "lights_on_time" in schema.schema
    assert "target_vwc_percent" in schema.schema


async def test_async_step_irrigation_overview_no_growspace(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {}
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_irrigation_overview()
    assert result == {"type": "abort"}


async def test_async_step_configure_irrigation_no_growspace(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.growspaces = {}
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_configure_irrigation()
    assert result == {"type": "abort"}


async def test_async_step_select_growspace_for_irrigation_no_entry_abort(
    mock_hass: MagicMock,
) -> None:
    handler = IrrigationConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_select_growspace_for_irrigation()
    assert result == {"type": "abort"}
