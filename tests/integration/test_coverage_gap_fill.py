"""Tests to fill coverage gaps in Growspace Manager backend."""

from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.config_handlers import BaseConfigHandler
from custom_components.growspace_manager.config_handlers.growspace_config_handler import (
    GrowspaceConfigHandler,
)
from custom_components.growspace_manager.config_handlers.notification_config_handler import (
    NotificationConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    IPMPreset,
    IrrigationConfig,
    NutrientInventory,
    NutrientPreset,
)
from custom_components.growspace_manager.strategies.evaluator_strategy import (
    BayesianEvaluatorStrategy,
)
from homeassistant.core import HomeAssistant


class MockFlow:
    def __init__(self, hass: HomeAssistant, config_entry: Any = None) -> None:
        self.hass = hass
        self.config_entry = config_entry
        self.async_show_form = MagicMock()
        self.async_abort = MagicMock()
        self.async_create_entry = MagicMock()
        self.async_step_init = AsyncMock()
        self.selected_growspace_id: str | None = None
        self.selected_notification_id: str | None = None


@pytest.fixture
def mock_flow(hass: HomeAssistant, mock_entry: MockConfigEntry) -> MockFlow:
    return MockFlow(hass, mock_entry)


@pytest.fixture
def mock_entry(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    return entry


@pytest.fixture
def mock_coordinator(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> GrowspaceCoordinator:
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.config_entry = mock_entry
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.growspace_manager.get_sorted_growspace_options = MagicMock(
        return_value=[]
    )
    mock_entry.runtime_data = coordinator
    return coordinator


@pytest.mark.asyncio
async def test_base_config_handler_placeholders(
    hass: HomeAssistant, mock_entry: MockConfigEntry, mock_flow: MockFlow
) -> None:
    """Cover missed lines in BaseConfigHandler placeholders."""
    # 1. Orchestrator style (already covered by other tests, but good to be explicit here)
    handler: BaseConfigHandler = BaseConfigHandler(mock_flow)
    assert handler.flow == mock_flow
    assert handler.hass == hass

    # 2. Traditional/Test style
    handler2: BaseConfigHandler = BaseConfigHandler(hass, mock_entry)
    assert handler2.flow is None
    assert handler2.hass == hass
    assert handler2.config_entry == mock_entry

    # 3. Fallback with flow in kwargs
    handler3: BaseConfigHandler = BaseConfigHandler(flow=mock_flow)
    assert handler3.flow == mock_flow
    assert handler3.hass == hass

    # 4. Fallback with hass/entry in kwargs
    handler4: BaseConfigHandler = BaseConfigHandler(hass=hass, config_entry=mock_entry)
    assert handler4.flow is None
    assert handler4.hass == hass
    assert handler4.config_entry == mock_entry

    # 5. clean_input
    assert handler.clean_input({"a": 1, "b": "", "c": None}) == {"a": 1}

    # 6. merge_options
    assert handler.merge_options({"a": 1}, {"b": 2}) == {"a": 1, "b": 2}

    # Coverage for websocket_get_event_log
    await handler.websocket_get_event_log(hass, None, None)  # type: ignore[arg-type]

    # Coverage for transition_plant_stage
    await handler.transition_plant_stage(hass, None, None)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_evaluator_strategy_placeholders() -> None:
    """Cover missed lines in BayesianEvaluatorStrategy placeholders."""

    class TestStrategy(BayesianEvaluatorStrategy):
        async def async_evaluate(  # type: ignore[override]
            self, environment_state: Any, env_config: dict[str, Any]
        ) -> tuple[list[str], list[str]]:
            return ([], [])

    strategy = TestStrategy(MagicMock())
    assert strategy.get_notification_title_message(False) is None


@pytest.mark.asyncio
async def test_growspace_config_handler_gaps(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_flow: MockFlow,
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Cover missed lines in GrowspaceConfigHandler."""
    handler: GrowspaceConfigHandler = GrowspaceConfigHandler(mock_flow)

    # 1. coordinator is None in async_step_manage_growspaces
    # Temporarily remove runtime_data
    mock_entry.runtime_data = None
    result = await handler.async_step_manage_growspaces()
    assert result is not None
    mock_flow.async_abort.assert_called_with(reason="setup_error")

    # Restore coordinator
    mock_entry.runtime_data = mock_coordinator

    # Now restore coordinator for further tests
    mock_entry.runtime_data = mock_coordinator

    # 2. Add growspace exception branch
    mock_coordinator.growspace_manager.add_growspace = AsyncMock(  # type: ignore[method-assign]
        side_effect=Exception("Test Error")
    )

    # 2. Add growspace exception branch
    mock_coordinator.growspace_manager.add_growspace = AsyncMock(  # type: ignore[method-assign]
        side_effect=Exception("Test Error")
    )
    # mock_entry already has runtime_data restored above

    result = await handler.async_step_add_growspace({"name": "Test"})
    assert result is not None
    mock_flow.async_show_form.assert_called()
    assert mock_flow.async_show_form.call_args[1]["errors"] == {"base": "add_failed"}

    # 3. manage_growspaces 'update' action with no selected growspace
    mock_flow.async_show_form.reset_mock()
    await handler.async_step_manage_growspaces(
        {"action": "update", "growspace_id": None}
    )
    mock_flow.async_show_form.assert_called()
    assert mock_flow.async_show_form.call_args[1]["errors"] == {
        "base": "select_growspace"
    }

    # 4. manage_growspaces 'remove' action with no selected growspace
    mock_flow.async_show_form.reset_mock()
    await handler.async_step_manage_growspaces(
        {"action": "remove", "growspace_id": None}
    )
    mock_flow.async_show_form.assert_called()
    assert mock_flow.async_show_form.call_args[1]["errors"] == {
        "base": "select_growspace"
    }

    # 5. confirm_remove_growspace exception branch
    mock_flow.selected_growspace_id = "gs1"
    gs = Growspace(id="gs1", name="GS1")
    mock_coordinator.growspaces = {"gs1": gs}

    with patch.object(
        handler, "async_remove_growspace", side_effect=Exception("Test Error")
    ):
        await handler.async_step_confirm_remove_growspace({"confirm": True})
        mock_flow.async_show_form.assert_called()
        assert mock_flow.async_show_form.call_args[1]["errors"] == {
            "base": "remove_failed"
        }

    # 7. update_growspace exception branch
    with patch.object(
        handler, "async_update_growspace", side_effect=Exception("Test Error")
    ):
        await handler.async_step_update_growspace({"name": "New Name"})
        mock_flow.async_show_form.assert_called()
        assert mock_flow.async_show_form.call_args[1]["errors"] == {
            "base": "update_failed"
        }

    # 8. update_growspace 'back' action
    mock_flow.async_step_init.reset_mock()
    await handler.async_step_manage_growspaces({"action": "back"})
    mock_flow.async_step_init.assert_called_once()

    # 6. update_growspace_schema with no growspace
    schema = handler.get_update_growspace_schema(None)  # type: ignore[arg-type]
    assert schema.schema == {}


@pytest.mark.asyncio
async def test_notification_config_handler_gaps(
    hass: HomeAssistant,
    mock_entry: MockConfigEntry,
    mock_flow: MockFlow,
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Cover missed lines in NotificationConfigHandler."""
    handler: NotificationConfigHandler = NotificationConfigHandler(mock_flow)

    # 1. manage_timed_notifications 'back' action
    mock_flow.async_step_init.reset_mock()
    cast(MagicMock, mock_coordinator.get_timed_notifications).return_value = []

    # 1. manage_timed_notifications 'back' action
    mock_flow.async_step_init.reset_mock()
    cast(MagicMock, mock_coordinator.get_timed_notifications).return_value = []

    # Check if runtime_data is set (it should be from fixture)
    assert mock_entry.runtime_data == mock_coordinator

    await handler.async_step_manage_timed_notifications({"action": "back"})
    mock_flow.async_step_init.assert_called_once()

    # 2. manage_timed_notifications with None coordinator
    mock_entry.runtime_data = None
    await handler.async_step_manage_timed_notifications()
    mock_flow.async_abort.assert_called_with(reason="setup_error")
    # Restore
    mock_entry.runtime_data = mock_coordinator


@pytest.mark.asyncio
async def test_coordinator_setters_and_gaps(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
) -> None:
    """Cover missed setters and branches in GrowspaceCoordinator."""

    entry = MockConfigEntry(domain=DOMAIN)
    entry.add_to_hass(hass)
    coord = GrowspaceCoordinator(hass, entry)

    # Coverage for setters
    coord.nutrient_presets = {"p1": NutrientPreset(id="p1", name="Preset 1", items=[])}
    coord.ipm_presets = {
        "i1": IPMPreset(id="i1", name="IPM 1", type="foliar", items=[])
    }
    coord.nutrient_inventory_service = MagicMock()
    coord.nutrient_inventory = NutrientInventory(stocks={})

    # Coverage for set_notifications_enabled non-existent growspace
    with patch(
        "custom_components.growspace_manager.notifications.notification_settings_manager._LOGGER.warning"
    ) as mock_warn:
        await coord.set_notifications_enabled("nonexistent", True)
        mock_warn.assert_called()

    # Coverage for async_update_irrigation_config growspace not found
    with pytest.raises(GrowspaceNotFoundError):
        await coord.async_update_irrigation_config("nonexistent", {})

    # _get_target_plants is now in TrainingService - tested through public API

    # Coverage for async_save_ipm_preset update branch
    coord.ipm_presets = {
        "ipm1": IPMPreset(
            id="ipm1", name="Old", type="foliar", items=[], created_at="2026-01-01"
        )
    }
    await coord.async_save_ipm_preset(
        name="New", type="drench", items=[], preset_id="ipm1"
    )
    assert coord.ipm_presets["ipm1"].name == "New"

    # Coverage for async_remove_ipm_preset error
    with pytest.raises(KeyError):
        await coord.async_remove_ipm_preset("nonexistent")

    # Coverage for async_apply_ipm error
    with pytest.raises(KeyError):
        await coord.async_apply_ipm("nonexistent")


@pytest.mark.asyncio
async def test_coordinator_extended_coverage(
    hass: HomeAssistant, mock_entry: MockConfigEntry
) -> None:
    """Cover remaining gaps in GrowspaceCoordinator."""

    # Use a real coordinator for these tests
    coord = GrowspaceCoordinator(hass, mock_entry)

    # 1. Getters for inventory (lines 198, 210)
    service = MagicMock()
    inventory = NutrientInventory(stocks={})
    coord.nutrient_inventory_service = service
    coord.nutrient_inventory = inventory
    assert coord.nutrient_inventory_service == service
    assert coord.nutrient_inventory == inventory

    # 3. _get_target_plants exception branches (lines 597-604 are actually _create_special_growspace)

    coord._create_special_growspace("GS_ID", "GS Name", 2, 2, GrowspaceType.VEG)
    assert "GS_ID" in coord.growspaces
    assert coord.growspaces["GS_ID"].name == "GS Name"

    # 4. _update_growspace_structure (lines 909-923)
    gs = Growspace(id="gs1", name="GS1", rows=1, plants_per_row=1)
    coord.growspaces = {"gs1": gs}
    changes: list[str] = []
    # No changes
    assert not coord._update_growspace_structure("gs1", changes=changes)
    # Rows change
    assert coord._update_growspace_structure("gs1", rows=5, changes=changes)
    assert gs.rows == 5
    assert "rows: 1 -> 5" in changes[0]
    # PPR change
    assert coord._update_growspace_structure("gs1", plants_per_row=10, changes=changes)
    assert gs.plants_per_row == 10
    assert "plants_per_row: 1 -> 10" in changes[1]

    # 5. _update_growspace_config (lines 929-956)
    changes = []
    # Name change
    assert coord._update_growspace_config("gs1", name="New Name", changes=changes)
    assert gs.name == "New Name"
    # Notification target
    assert coord._update_growspace_config(
        "gs1", notification_target=" notify.me ", changes=changes
    )
    assert gs.notification_target == "notify.me"
    # Env config
    assert coord._update_growspace_config(
        "gs1", environment_config=EnvironmentConfig(), changes=changes
    )
    # Irrigation config
    assert coord._update_growspace_config(
        "gs1", irrigation_config=IrrigationConfig(), changes=changes
    )

    # 6. Timed Notification CRUD (lines 1061, 1071-1112)
    # Add
    await coord.async_add_timed_notification("Msg", "veg", 5, ["gs1"])
    notifications = coord.get_timed_notifications()
    assert len(notifications) == 1
    assert notifications[0]["message"] == "Msg"
    nid = notifications[0]["id"]

    # Update
    await coord.async_update_timed_notification(nid, "New Msg", "flower", 10, ["gs2"])
    notifications = coord.get_timed_notifications()
    assert notifications[0]["message"] == "New Msg"
    assert notifications[0]["day"] == 10

    # Remove
    await coord.async_remove_timed_notification(nid)
    assert len(coord.get_timed_notifications()) == 0

    # 7. resolve_nutrient_mix - now tested via NutrientManager (dead code removed from coordinator)
    coord.nutrient_presets = {
        "p1": NutrientPreset(
            id="p1", name="P1", items=[{"name": "N1", "dose_ml_l": 1.0}]
        )
    }
    # Preset only
    mix, name = coord.nutrient_manager.resolve_nutrient_mix(None, "p1")
    assert mix == {"N1": 1.0}
    assert name == "P1"
    # Manual only
    mix, name = coord.nutrient_manager.resolve_nutrient_mix({"N2": 2.0}, None)
    assert mix == {"N2": 2.0}
    assert name is None
    # Both
    mix, name = coord.nutrient_manager.resolve_nutrient_mix({"N1": 5.0}, "p1")
    assert mix == {"N1": 5.0}  # Manual override
    # Preset not found
    with pytest.raises(KeyError):
        coord.nutrient_manager.resolve_nutrient_mix(None, "invalid")
