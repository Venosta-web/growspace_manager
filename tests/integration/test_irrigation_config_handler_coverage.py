"""Tests for the Irrigation Config Handler."""

from dataclasses import asdict, dataclass, field
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
    p1_shot_duration_seconds: int = 10
    p1_shot_interval_minutes: int = 15
    p2_shot_duration_seconds: int = 10
    p2_shot_interval_minutes: int = 15
    maintenance_dryback_percent: float = 2.0
    p2_stop_before_lights_off_minutes: int = 120
    irrigation_times: list = None
    drain_times: list = None
    soil_trigger_percent: float | None = None
    daily_volume_cap_liters: float | None = None
    max_cycles_per_day: int | None = None
    skip_during_dark: bool = False
    pause_on_low_tank: bool = True
    log_to_logbook: bool = True


@dataclass
class MockSubstrateProfile:
    media_type: str = "coco"
    liters_per_pot: float = 0.0


@dataclass
class MockIrrigationStrategy:
    enabled: bool = False
    shot_sizing_mode: str = "seconds"
    substrate_profile: MockSubstrateProfile = field(
        default_factory=MockSubstrateProfile
    )
    p1_shot_volume_percent: float = 4.0
    p2_shot_volume_percent: float = 4.0


@dataclass
class MockGrowspace:
    id: str
    name: str
    irrigation_config: MockIrrigationConfig
    irrigation_strategy: MockIrrigationStrategy = field(
        default_factory=MockIrrigationStrategy
    )


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
    entry.options = {}
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
    coordinator.services.growspaces.get_sorted_growspace_options.return_value = []
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_select_growspace_for_irrigation()
    assert result == {"type": "abort"}
    handler.flow.async_abort.assert_called_with(reason="no_growspaces")


async def test_async_step_select_growspace_for_irrigation_get(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.services.growspaces.get_sorted_growspace_options.return_value = [
        ("gs1", "GS1")
    ]
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    result = await handler.async_step_select_growspace_for_irrigation()
    assert result["type"] == "form"


async def test_async_step_select_growspace_for_irrigation_post(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.services.growspaces.get_sorted_growspace_options.return_value = [
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
    handler.config_entry.runtime_data.services.growspaces.get_growspace.return_value = None
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
    coordinator.services.growspaces.get_growspace.return_value = growspace
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
    coordinator.services.growspaces.get_growspace.return_value = growspace
    coordinator.services.growspaces.update_irrigation_config = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    user_input = {"irrigation_duration": 40}
    result = await handler.async_step_irrigation_overview(user_input)
    assert result["type"] == "create_entry"
    coordinator.services.growspaces.update_irrigation_config.assert_called_once_with(
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
    coordinator.services.growspaces.get_growspace.return_value = None
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_irrigation_overview()
    assert result == {"type": "abort"}


async def test_async_step_configure_irrigation_no_growspace(
    handler: IrrigationConfigHandler,
) -> None:
    coordinator = handler.config_entry.runtime_data
    coordinator.services.growspaces.get_growspace.return_value = None
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_configure_irrigation()
    assert result == {"type": "abort"}


async def test_async_step_select_growspace_for_irrigation_no_entry_abort(
    mock_hass: MagicMock,
) -> None:
    """Test select growspace step aborts if config entry is missing."""
    handler = IrrigationConfigHandler(mock_hass, None)
    handler.flow = MagicMock()
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})
    result = await handler.async_step_select_growspace_for_irrigation()
    assert result == {"type": "abort"}


async def test_get_irrigation_overview_schema_new_fields(
    handler: IrrigationConfigHandler,
) -> None:
    """Test that get_irrigation_overview_schema contains the new configuration fields."""
    options = asdict(MockIrrigationConfig())
    schema = handler.get_irrigation_overview_schema(options, "gs1")
    assert "soil_trigger_percent" in schema.schema
    assert "daily_volume_cap_liters" in schema.schema
    assert "max_cycles_per_day" in schema.schema
    assert "skip_during_dark" in schema.schema
    assert "pause_on_low_tank" in schema.schema
    assert "log_to_logbook" in schema.schema


async def test_async_step_irrigation_overview_post_new_fields(
    handler: IrrigationConfigHandler,
) -> None:
    """Test updating the new irrigation config parameters via the config flow."""
    coordinator = handler.config_entry.runtime_data
    growspace = MockGrowspace(
        id="gs1", name="GS1", irrigation_config=MockIrrigationConfig()
    )
    coordinator.services.growspaces.get_growspace.return_value = growspace
    coordinator.services.growspaces.update_irrigation_config = AsyncMock()
    handler.flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})

    user_input = {
        "irrigation_duration": 40,
        "soil_trigger_percent": 45.5,
        "daily_volume_cap_liters": 25.0,
        "max_cycles_per_day": 5,
        "skip_during_dark": True,
        "pause_on_low_tank": False,
        "log_to_logbook": False,
    }
    result = await handler.async_step_irrigation_overview(user_input)
    assert result["type"] == "create_entry"
    coordinator.services.growspaces.update_irrigation_config.assert_called_once_with(
        "gs1", user_input
    )
