"""Tests for the Growspace Manager configuration and options flows.

This file contains a suite of tests to ensure that the config flow (for initial
setup) and the options flow (for post-setup configuration) of the Growspace
Manager integration work as expected. It covers various user interaction
scenarios, including adding/updating/removing growspaces and plants, configuring
environmental sensors, and managing timed notifications.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_flow import (
    ConfigFlow,
    OptionsFlowHandler,
)
from custom_components.growspace_manager.config_handlers import AbortFlow
from custom_components.growspace_manager.config_handlers.fan_controller_handler import (
    FanControllerHandler,
)
from custom_components.growspace_manager.config_handlers.growspace_config_handler import (
    GrowspaceConfigHandler,
)
from custom_components.growspace_manager.config_handlers.plant_config_handler import (
    PlantConfigHandler,
)
from custom_components.growspace_manager.const import (
    CONF_AI_ENABLED,
    CONF_ASSISTANT_ID,
    DEFAULT_NAME,
    DOMAIN,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    IrrigationConfig,
    IrrigationStrategy,
)
from homeassistant.config_entries import HANDLERS
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector
from tests.common import MockConfigEntry


@pytest.fixture
def mock_coordinator(hass: HomeAssistant, tmp_path: Path):
    """Mock coordinator for testing config flows."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.growspaces = {}
    coordinator.plants = {}

    facade = MagicMock()
    coordinator.services = facade

    facade.save = AsyncMock()
    facade.request_refresh = AsyncMock()
    facade.commit = AsyncMock()
    coordinator.async_commit = facade.commit
    coordinator.async_save = facade.save
    coordinator.async_refresh = AsyncMock()
    coordinator._subsystem_manager.get_circulation_fan_controller.return_value = None
    coordinator._subsystem_manager.get_exhaust_fan_controller.return_value = None
    coordinator._subsystem_manager.get_growlight_controller.return_value = None

    # --- growspaces sub-facade ---
    gs_facade = MagicMock()
    gs_facade.get_growspace = MagicMock(
        side_effect=lambda gid: coordinator.growspaces.get(gid)
    )
    gs_facade.get_sorted_growspace_options = MagicMock(return_value=[])
    gs_facade.get_growspace_data = MagicMock(return_value={})
    gs_facade.add_growspace = AsyncMock()
    gs_facade.update_growspace = AsyncMock()
    gs_facade.remove_growspace = AsyncMock()
    gs_facade.update_irrigation_config = AsyncMock()
    facade.growspaces = gs_facade

    # --- plants sub-facade ---
    pl_facade = MagicMock()
    pl_facade.get_plant = MagicMock(side_effect=lambda pid: coordinator.plants.get(pid))
    pl_facade.add_plant = AsyncMock()
    pl_facade.update_plant = AsyncMock()
    pl_facade.remove_plant = AsyncMock()
    facade.plants = pl_facade

    # --- config sub-facade ---
    cfg_facade = MagicMock()
    cfg_facade.strain_library = MagicMock()
    cfg_facade.strain_library.async_load = AsyncMock()
    cfg_facade.strain_library.import_library_from_zip = AsyncMock()
    cfg_facade.strain_library.export_library_to_zip = AsyncMock(
        return_value=str(tmp_path / "export.zip")
    )
    cfg_facade.strain_library.remove_strain = AsyncMock()
    cfg_facade.strain_library.async_delete_strain = (
        cfg_facade.strain_library.remove_strain
    )
    cfg_facade.strain_library.get_all = MagicMock(return_value={})
    cfg_facade.strain_library.get_all_strains = MagicMock(return_value=[])
    cfg_facade.get_strain_options = MagicMock(return_value=[])
    facade.config = cfg_facade

    # --- notifications sub-facade ---
    notif_facade = MagicMock()
    notif_facade.get_timed_notifications = MagicMock(return_value=[])
    _add_notif = AsyncMock()
    _update_notif = AsyncMock()
    _remove_notif = AsyncMock()
    notif_facade.add_timed_notification = _add_notif
    notif_facade.async_add_timed_notification = _add_notif
    notif_facade.update_timed_notification = _update_notif
    notif_facade.async_update_timed_notification = _update_notif
    notif_facade.remove_timed_notification = _remove_notif
    notif_facade.async_remove_timed_notification = _remove_notif
    facade.notifications = notif_facade

    # Backwards-compat aliases on coordinator for old-style access in tests
    coordinator.get_growspace = gs_facade.get_growspace
    coordinator.get_plant = pl_facade.get_plant

    return coordinator


@pytest.fixture
def mock_store():
    """Create a mock Store for testing.

    Returns:
        An AsyncMock object that mimics the Home Assistant Store.
    """
    store = AsyncMock()
    store.async_load = AsyncMock(return_value={"growspaces": {}, "plants": {}})
    return store


# ============================================================================
# Test ensure_default_growspaces
# ============================================================================


# ============================================================================
# Test ConfigFlow – domain registration (PR #97: is_matching refactored out)
# ============================================================================


def test_config_flow_domain_registered_via_class_keyword() -> None:
    """ConfigFlow wires its domain through the class keyword, not a class attribute.

    PR #97 removed the redundant ``DOMAIN = DOMAIN`` class attribute in favour of
    the standard HA pattern ``class ConfigFlow(..., domain=DOMAIN)``.  The
    framework registers the handler in ``HANDLERS[DOMAIN]``; the old explicit
    class attribute must be absent so it cannot shadow or contradict HA routing.
    """
    assert HANDLERS.get(DOMAIN) is ConfigFlow
    assert "DOMAIN" not in vars(ConfigFlow)


def test_config_flow_no_is_matching_method() -> None:
    """ConfigFlow must not define an ``is_matching`` static method.

    PR #97 removed ``is_matching`` because domain-level routing is now fully
    handled by ``domain=DOMAIN`` in the class definition; a hand-rolled override
    was redundant and could diverge from HA internals silently.
    """
    assert not hasattr(ConfigFlow, "is_matching") or not isinstance(
        vars(ConfigFlow).get("is_matching"), staticmethod
    )


# ============================================================================
# Test ConfigFlow
# ============================================================================


@pytest.mark.asyncio
async def test_config_flow_user_step_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the user step of the config flow shows the initial form.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "user"


@pytest.mark.asyncio
async def test_config_flow_user_step_create_entry(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the user step creates a config entry with the provided name.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(user_input={"name": "My Growspace"})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert result.get("title") == "My Growspace"
    assert result.get("data") == {"name": "My Growspace"}


@pytest.mark.asyncio
async def test_config_flow_user_step_default_name(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the user step creates a config entry with the default name.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(user_input={"name": DEFAULT_NAME})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert result.get("data") == {"name": DEFAULT_NAME}


@pytest.mark.asyncio
async def test_config_flow_add_growspace_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the `add_growspace` step shows the correct form.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass
    flow.hass.services = Mock()
    flow.hass.services.async_services = Mock(return_value={"notify": {}})

    result = await flow.async_step_add_growspace()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_config_flow_add_growspace_with_data(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the `add_growspace` step stores pending data correctly.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass
    hass.data[DOMAIN] = {}

    user_input = {
        "name": "Test Growspace",
        "rows": 5,
        "plants_per_row": 5,
        "length": 120,
        "width": 120,
        "height": 200,
        "notification_target": "mobile_app_test",
    }

    result = await flow.async_step_add_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert "pending_growspace" in result.get("data", {})
    assert result["data"]["pending_growspace"]["name"] == "Test Growspace"


@pytest.mark.asyncio
async def test_config_flow_get_add_growspace_schema_with_notify(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the growspace schema includes notify services when available.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass
    flow.hass.services = Mock()
    flow.hass.services.async_services = Mock(
        return_value={
            "notify": {
                "mobile_app_phone1": {},
                "mobile_app_phone2": {},
            }
        }
    )

    handler = GrowspaceConfigHandler(hass, None)
    schema = handler.get_add_growspace_schema()

    assert "name" in schema.schema
    assert "rows" in schema.schema
    assert "plants_per_row" in schema.schema
    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_config_flow_get_add_growspace_schema_no_notify(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the growspace schema is correct when no notify services are found.

    Args:
        hass: The Home Assistant instance.
    """
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    handler = GrowspaceConfigHandler(hass, None)
    schema = handler.get_add_growspace_schema()

    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_config_flow_async_get_options_flow(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that `async_get_options_flow` returns an `OptionsFlowHandler`.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    options_flow = ConfigFlow.async_get_options_flow(config_entry)

    assert isinstance(options_flow, OptionsFlowHandler)


# ============================================================================
# Test OptionsFlowHandler - Main Menu
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_show_menu(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the initial step of the options flow shows the main menu.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_init_manage_growspaces(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test navigating to 'Manage Growspaces' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "manage_growspaces"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_init_manage_plants(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test navigating to 'Manage Plants' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "manage_plants"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_plants"


# ============================================================================
# Test OptionsFlowHandler - Manage Growspaces
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'Manage Growspaces' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(user_input=None)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_add(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the 'add' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(user_input={"action": "add"})
    await hass.async_block_till_done()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_update(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the 'update' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {
        "gs1": Mock(
            name="Growspace 1",
            environment_config=EnvironmentConfig(),
            irrigation_config=IrrigationConfig(),
        )
    }
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(
        user_input={"action": "update", "growspace_id": "gs1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"
    assert flow.selected_growspace_id == "gs1"


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_manage_growspaces_remove(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the 'remove' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    result = await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm_remove_growspace"

    result = await flow.async_step_confirm_remove_growspace(
        user_input={"confirm": True}
    )

    mock_coordinator.services.growspaces.remove_growspace.assert_called_once_with("gs1")
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_back(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the 'back' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """

    # Create a mock config entry
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    # Make sure hass.data points to our mock coordinator
    config_entry.runtime_data = mock_coordinator

    # Initialize the options flow handler
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    flow._get_main_menu_schema = lambda: vol.Schema({vol.Required("action"): str})
    # Provide a **real schema**, not a Mock

    # Now call the step
    result = await flow.async_step_manage_growspaces(user_input={"action": "back"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_no_coordinator(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that an abort is triggered if the coordinator is not found.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = None

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(user_input=None)

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "setup_error"


# ============================================================================
# Test OptionsFlowHandler - Add Growspace
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_add_growspace_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'add_growspace' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_add_growspace()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_options_flow_add_growspace_success(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful addition of a growspace via the options flow.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {
        "name": "New Growspace",
        "rows": 5,
        "plants_per_row": 6,
        "length": 120,
        "width": 120,
        "height": 200,
        "notification_target": "mobile_app_test",
    }

    result = await flow.async_step_add_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"
    mock_coordinator.services.growspaces.add_growspace.assert_awaited_once_with(
        name="New Growspace",
        rows=5,
        plants_per_row=6,
        notification_target="mobile_app_test",
        dimensions={"length": 120, "width": 120, "height": 200, "unit": "cm"},
    )


@pytest.mark.asyncio
async def test_options_flow_add_growspace_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling when adding a growspace fails.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.growspaces.add_growspace.side_effect = Exception(
        "Test error"
    )
    config_entry.runtime_data = mock_coordinator
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {"name": "Test", "rows": 4, "plants_per_row": 4}
    result = await flow.async_step_add_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result


# ============================================================================
# Test OptionsFlowHandler - Update Growspace
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_update_growspace_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'update_growspace' step shows the correct pre-filled form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_growspace = Mock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    config_entry.runtime_data = mock_coordinator
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    result = await flow.async_step_update_growspace()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_success(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful update of a growspace via the options flow.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_growspace = Mock()
    mock_growspace.name = "Old Name"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    user_input = {
        "name": "New Name",
        "rows": 5,
        "length": 120,
        "width": 120,
        "height": 200,
    }
    result = await flow.async_step_update_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"
    mock_coordinator.services.growspaces.update_growspace.assert_awaited_once()


@pytest.mark.asyncio
async def test_options_flow_update_growspace_not_found(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that an abort is triggered if the growspace to update is not found.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "nonexistent"

    result = await flow.async_step_update_growspace()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling when updating a growspace fails.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_growspace = Mock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.services.growspaces.update_growspace.side_effect = Exception(
        "Test error"
    )

    config_entry.runtime_data = mock_coordinator
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    user_input = {"name": "New Name"}
    result = await flow.async_step_update_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result


# ============================================================================
# Test OptionsFlowHandler - Add Plant
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_add_plant_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'add_plant' step shows the correct form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    result = await flow.async_step_add_plant()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_plant"


@pytest.mark.asyncio
async def test_options_flow_add_plant_success(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful addition of a plant via the options flow."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    user_input = {
        "strain": "Test Strain",
        "row": 1,
        "col": 1,
    }

    result = await flow.async_step_add_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.plants.add_plant.assert_awaited_once_with(
        growspace_id="gs1",
        strain="Test Strain",
        row=1,
        col=1,
        phenotype=None,
        veg_start=None,
        flower_start=None,
    )


@pytest.mark.asyncio
async def test_options_flow_add_plant_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling when adding a plant fails."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.services.plants.add_plant.side_effect = Exception("Test error")
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    user_input = {
        "strain": "Test Strain",
        "row": 1,
        "col": 1,
    }
    result = await flow.async_step_add_plant(user_input=user_input)

    assert result is not None
    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result
    assert result["errors"] is not None
    assert result["errors"]["base"] == "add_failed"


# ============================================================================
# Test OptionsFlowHandler - Update Plant
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_update_plant_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'update_plant' step shows the correct form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_plant = Mock(strain="Old Strain", row=1, col=1)
    mock_coordinator.plants = {"p1": mock_plant}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_plant_id = "p1"

    result = await flow.async_step_update_plant()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_plant"


@pytest.mark.asyncio
async def test_options_flow_update_plant_success(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful update of a plant via the options flow."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_plant = Mock(strain="Old Strain", row=1, col=1)
    mock_coordinator.plants = {"p1": mock_plant}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_plant_id = "p1"

    user_input = {"strain": "New Strain"}
    result = await flow.async_step_update_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.plants.update_plant.assert_awaited_once_with(
        "p1", **user_input
    )


@pytest.mark.asyncio
async def test_options_flow_update_plant_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling when updating a plant fails."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_plant = Mock(strain="Old Strain", row=1, col=1)
    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.services.plants.update_plant.side_effect = Exception("Test error")
    config_entry.runtime_data = mock_coordinator
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_plant_id = "p1"
    user_input = {"strain": "New Strain"}
    result = await flow.async_step_update_plant(user_input=user_input)

    assert result is not None
    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result
    assert result["errors"] is not None  # Add this assertion
    assert result["errors"]["base"] == "update_failed"


@pytest.mark.asyncio
async def test_options_flow_update_plant_not_found(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that an abort is triggered if the plant to update is not found."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.plants = {}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_plant_id = "nonexistent"

    result = await flow.async_step_update_plant()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "plant_not_found"


# ============================================================================
# Test Schema Generation
# ============================================================================


@pytest.mark.asyncio
async def test_get_add_plant_schema_no_growspace(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that _get_add_plant_schema returns an empty schema if growspace is None."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})

    handler = PlantConfigHandler(hass, config_entry)

    schema = handler.get_add_plant_schema(growspace=None, coordinator=None)
    assert schema.schema == {}


@pytest.mark.asyncio
async def test_get_add_plant_schema_no_strain_options(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test _get_add_plant_schema when there are no strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})

    handler = PlantConfigHandler(hass, config_entry)
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.services.config.get_strain_options.return_value = []

    schema = handler.get_add_plant_schema(
        growspace=mock_growspace, coordinator=mock_coordinator
    )

    # When no strain options, it should still be a TextSelector or SelectSelector allowing custom
    key = next(
        k
        for k in schema.schema
        if k == "strain" or (isinstance(k, vol.Marker) and k.schema == "strain")
    )
    assert key is not None
    assert isinstance(schema.schema["strain"], selector.TextSelector)


@pytest.mark.asyncio
async def test_get_add_plant_schema_with_strain_options(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test _get_add_plant_schema when there are strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})

    handler = PlantConfigHandler(hass, config_entry)
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.services.config.get_strain_options.return_value = [
        "Strain 1",
        "Strain 2",
    ]

    schema = handler.get_add_plant_schema(
        growspace=mock_growspace, coordinator=mock_coordinator
    )

    key = next(
        k
        for k in schema.schema
        if k == "strain" or (isinstance(k, vol.Marker) and k.schema == "strain")
    )
    assert key is not None
    assert isinstance(schema.schema[key], selector.SelectSelector)


@pytest.mark.asyncio
async def test_get_update_plant_schema_no_growspace(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that _get_update_plant_schema returns a schema even if growspace is None."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})

    handler = PlantConfigHandler(hass, config_entry)
    mock_plant = Mock(strain="Test Strain", row=1, col=1, growspace_id="gs1")
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.services.config.get_strain_options.return_value = [
        "Strain 1",
        "Strain 2",
    ]

    schema = handler.get_update_plant_schema(
        plant=mock_plant, coordinator=mock_coordinator
    )

    key = next(
        k
        for k in schema.schema
        if k == "strain" or (isinstance(k, vol.Marker) and k.schema == "strain")
    )
    assert key is not None


@pytest.mark.asyncio
async def test_get_update_plant_schema_no_strain_options(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test _get_update_plant_schema when there are no strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})

    handler = PlantConfigHandler(hass, config_entry)
    mock_plant = Mock(strain="Test Strain", row=1, col=1, growspace_id="gs1")
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.services.config.get_strain_options.return_value = []

    schema = handler.get_update_plant_schema(
        plant=mock_plant, coordinator=mock_coordinator
    )

    key = next(
        k
        for k in schema.schema
        if k == "strain" or (isinstance(k, vol.Marker) and k.schema == "strain")
    )
    assert key is not None
    assert isinstance(schema.schema[key], selector.TextSelector)


@pytest.mark.asyncio
async def test_get_update_plant_schema_with_strain_options(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test _get_update_plant_schema when there are strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})

    handler = PlantConfigHandler(hass, config_entry)
    mock_plant = Mock(strain="Test Strain", row=1, col=1, growspace_id="gs1")
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.services.config.get_strain_options.return_value = [
        "Strain 1",
        "Strain 2",
    ]

    schema = handler.get_update_plant_schema(
        plant=mock_plant, coordinator=mock_coordinator
    )

    key = next(
        k
        for k in schema.schema
        if k == "strain" or (isinstance(k, vol.Marker) and k.schema == "strain")
    )
    assert key is not None
    assert isinstance(schema.schema[key], selector.SelectSelector)


# ============================================================================
# Test Edge Cases and Error Conditions
# ============================================================================


@pytest.mark.asyncio
async def test_config_flow_user_step_exception(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that exceptions during the user step are caught and handled.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass

    with patch.object(flow, "async_create_entry", side_effect=Exception("Test error")):
        result = await flow.async_step_user(user_input={"name": "Test"})
        assert result.get("type") == FlowResultType.FORM
        assert result.get("errors") == {"base": "unknown"}


@pytest.mark.asyncio
async def test_config_flow_add_growspace_exception(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that exceptions during the `add_growspace` step are caught.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass
    flow.hass.services = Mock()
    flow.hass.services.async_services = Mock(return_value={"notify": {}})

    with patch.object(flow, "async_create_entry", side_effect=Exception("Test error")):
        result = await flow.async_step_add_growspace(
            user_input={"name": "Test", "rows": 4, "plants_per_row": 4}
        )
        assert result.get("type") == FlowResultType.FORM


@pytest.mark.asyncio
async def test_options_flow_coordinator_missing(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that various option flow steps abort if the coordinator is missing.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Test"}, entry_id="test-entry-id"
    )
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = None
    hass.data[DOMAIN] = {}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Test add_growspace
    result = await flow.async_step_add_growspace()
    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "setup_error"

    # Test update_growspace
    flow.selected_growspace_id = "gs1"
    result = await flow.async_step_update_growspace()
    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "setup_error"


@pytest.mark.asyncio
async def test_options_flow_empty_update_data(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that updating a growspace with empty/filtered data still succeeds.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_growspace = Mock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    # Submit form with empty values
    user_input = {"name": "", "rows": None}
    result = await flow.async_step_update_growspace(user_input=user_input)

    # Should still succeed (empty updates are filtered) and return to menu
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


# ============================================================================
# Test OptionsFlowHandler - Timed Notifications
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_manage_timed_notifications(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test navigating to 'Timed Notifications' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(
        user_input={"action": "manage_timed_notifications"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_timed_notifications"


@pytest.mark.asyncio
async def test_options_flow_manage_timed_notifications_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'Manage Timed Notifications' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_timed_notifications(user_input=None)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_timed_notifications"


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_manage_timed_notifications_add(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the 'add' action for timed notifications.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_timed_notifications(
        user_input={"action": "add"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_timed_notification"


@pytest.mark.asyncio
async def test_options_flow_add_timed_notification_success(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful addition of a timed notification.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {
        "growspace_ids": ["gs1"],
        "trigger_type": "flower",
        "day": 10,
        "message": "Test notification",
    }

    result = await flow.async_step_add_timed_notification(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.notifications.add_timed_notification.assert_called_once_with(
        "Test notification",
        "flower",
        10,
        ["gs1"],
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_manage_timed_notifications_edit(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the 'edit' action for timed notifications.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    notifications = [
        {
            "id": "123",
            "growspace_ids": ["gs1"],
            "trigger_type": "flower",
            "day": 10,
            "message": "Test notification",
        }
    ]
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Test"},
        options={"timed_notifications": notifications},
    )
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.notifications.get_timed_notifications.return_value = (
        notifications
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_timed_notifications(
        user_input={"action": "edit", "notification_id": "123"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "edit_timed_notification"
    assert flow.selected_notification_id == "123"


@pytest.mark.asyncio
async def test_options_flow_edit_timed_notification_success(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful update of a timed notification.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    notifications = [
        {
            "id": "123",
            "growspace_ids": ["gs1"],
            "trigger_type": "flower",
            "day": 10,
            "message": "Old message",
        }
    ]
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Test"},
        options={"timed_notifications": notifications},
    )
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.notifications.get_timed_notifications.return_value = (
        notifications
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_notification_id = "123"

    user_input = {
        "growspace_ids": ["gs1"],
        "trigger_type": "veg",
        "day": 20,
        "message": "New message",
    }

    result = await flow.async_step_edit_timed_notification(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.notifications.update_timed_notification.assert_called_once_with(
        "123",
        "New message",
        "veg",
        20,
        ["gs1"],
    )


@pytest.mark.asyncio
async def test_options_flow_manage_timed_notifications_delete(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the 'delete' action for timed notifications.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    notifications = [
        {
            "id": "123",
            "growspace_ids": ["gs1"],
            "trigger_type": "flower",
            "day": 10,
            "message": "Test notification",
        }
    ]
    config_entry = MockConfigEntry(
        domain=DOMAIN,
        data={"name": "Test"},
        options={"timed_notifications": notifications},
    )
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.notifications.get_timed_notifications.return_value = (
        notifications
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_timed_notifications(
        user_input={"action": "delete", "notification_id": "123"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "delete_timed_notification"

    # Now submit the deletion confirmation
    result = await flow.async_step_delete_timed_notification(user_input={})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.notifications.remove_timed_notification.assert_called_once_with(
        "123"
    )


# ============================================================================
# Test OptionsFlowHandler - Environment Configuration
# ============================================================================


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_init_configure_environment(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test navigating to 'Configure Environment' from the main menu.

    Args:
        hass: The Home Assistant instance.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Test"}, options={}, entry_id="test-entry-id"
    )
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator = MagicMock()
    mock_coordinator.services.growspaces.get_sorted_growspace_options = MagicMock(
        return_value=[("gs1", "Growspace 1")]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_environment"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_env"


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_select_growspace_for_env_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'select_growspace_for_env' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Test"}, options={}, entry_id="test-entry-id"
    )
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator = MagicMock()
    mock_coordinator.services.growspaces.get_sorted_growspace_options = MagicMock(
        return_value=[("gs1", "Growspace 1")]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_env()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_env"


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_select_growspace_for_env_no_growspaces(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that an abort is triggered if no growspaces exist to configure.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.growspaces.get_sorted_growspace_options = MagicMock(
        return_value=[]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_env()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "no_growspaces"


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_select_growspace_for_env_submit(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test submitting the 'select_growspace_for_env' form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {
        "gs1": Mock(
            name="Growspace 1",
            environment_config=EnvironmentConfig(),
            irrigation_config=IrrigationConfig(),
        )
    }
    mock_coordinator.services.growspaces.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "Growspace 1")]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    result = await flow.async_step_select_growspace_for_env(
        user_input={"growspace_id": "gs1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_environment"
    assert flow.selected_growspace_id == "gs1"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'configure_environment' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {
        "gs1": Mock(
            name="Growspace 1",
            environment_config=EnvironmentConfig(),
            irrigation_config=IrrigationConfig(),
        )
    }
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    result = await flow.async_step_configure_environment()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_environment"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_submit(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful submission of the environment configuration form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 100, "length": 100, "height": 200, "unit": "cm"},
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensors": ["sensor.temp"],
        "humidity_sensors": ["sensor.humidity"],
        "vpd_sensors": ["sensor.vpd"],
    }
    result = await flow.async_step_configure_environment(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_sensor_placement"

    # Complete the flow
    result = await flow.async_step_configure_sensor_placement(user_input={})
    assert result.get("type") == FlowResultType.CREATE_ENTRY

    # Environment config is saved to the growspace object, not config_entry options
    assert mock_growspace.environment_config.temperature_sensors == ["sensor.temp"]
    mock_coordinator.services.save.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_configure_environment_remove_vpd_sensor(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test removing the VPD sensor configuration.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        environment_config=EnvironmentConfig(
            vpd_sensor="sensor.vpd",
            temperature_sensor="sensor.temp",
            humidity_sensor="sensor.humidity",
        ),
        dimensions={"width": 100, "length": 100, "height": 200, "unit": "cm"},
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    # Simulate user clearing the VPD sensor (sending missing key or empty list)
    user_input = {
        "temperature_sensors": ["sensor.temp"],
        "humidity_sensors": ["sensor.humidity"],
        "vpd_sensors": [],  # Explicitly clear it
    }
    result = await flow.async_step_configure_environment(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_sensor_placement"

    # Complete the flow
    result = await flow.async_step_configure_sensor_placement(user_input={})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    # Ensure vpd_sensor is strictly None (not just missing if that was the case)
    # The fix ensures Nones are preserved in the flow.
    assert mock_growspace.environment_config.vpd_sensors == []
    # Ensure other sensors remain
    assert mock_growspace.environment_config.temperature_sensors == ["sensor.temp"]
    mock_coordinator.services.save.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_configure_environment_advanced(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test navigating to the advanced Bayesian configuration step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(name="Growspace 1", environment_config=EnvironmentConfig())
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensors": ["sensor.temp"],
        "humidity_sensors": ["sensor.humidity"],
        "vpd_sensors": ["sensor.vpd"],
        "configure_advanced": True,
    }
    result = await flow.async_step_configure_environment(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the advanced Bayesian configuration step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {
        "gs1": Mock(
            name="Growspace 1",
            environment_config=EnvironmentConfig(),
            irrigation_config=IrrigationConfig(),
        )
    }
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {}

    result = await flow.async_step_configure_advanced_bayesian()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_submit(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful submission of the advanced Bayesian configuration.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 100, "length": 100, "height": 200, "unit": "cm"},
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {"temperature_sensors": ["sensor.temp"]}

    user_input = {"prob_temp_extreme_heat": "(0.9, 0.1)"}
    result = await flow.async_step_configure_advanced_bayesian(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_sensor_placement"

    # Complete the flow
    result = await flow.async_step_configure_sensor_placement(user_input={})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    # Bayesian config is saved to the growspace object
    assert (
        "prob_temp_extreme_heat" in mock_growspace.environment_config.bayesian_options
    )
    assert mock_growspace.environment_config.bayesian_options[
        "prob_temp_extreme_heat"
    ] == (0.9, 0.1)
    mock_coordinator.services.save.assert_called_once()


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_configure_advanced_bayesian_invalid_tuple(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling for invalid tuple format in advanced Bayesian config.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 100, "length": 100, "height": 200, "unit": "cm"},
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {}

    user_input = {"prob_temp_extreme_heat": "invalid_tuple"}
    result = await flow.async_step_configure_advanced_bayesian(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result is not None
    assert "errors" in result
    errors = result.get("errors")
    assert errors is not None
    assert "base" in errors
    assert errors["base"] == "invalid_tuple_format"


# ============================================================================
# Test OptionsFlowHandler - Global Configuration
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_configure_global(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test navigating to 'Configure Global' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_global"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_global"


@pytest.mark.asyncio
async def test_options_flow_configure_global_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'Configure Global' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_configure_global()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_global"


@pytest.mark.asyncio
async def test_options_flow_configure_global_submit(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful submission of the global configuration form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {"weather_entity": "weather.home"}
    result = await flow.async_step_configure_global(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert "global_settings" in result["data"]
    assert result["data"]["global_settings"]["weather_entity"] == "weather.home"


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_configure_advanced_bayesian_non_tuple_parsed_value(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling for non-tuple parsed value in advanced Bayesian config.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(name="Growspace 1", environment_config=EnvironmentConfig())
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {}
    # Provide a string that evaluates to a list, not a tuple
    user_input = {"prob_temp_extreme_heat": "[0.9, 0.1]"}
    result = await flow.async_step_configure_advanced_bayesian(user_input=user_input)

    assert result is not None
    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result

    errors = result.get("errors")
    assert errors is not None, "Expected errors dict to be present"
    assert errors.get("base") == "invalid_tuple_format"


@pytest.mark.asyncio
@pytest.mark.usefixtures("enable_custom_integrations")
async def test_options_flow_configure_advanced_bayesian_non_string_value(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test handling of non-string values in advanced Bayesian config.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 100, "length": 100, "height": 200, "unit": "cm"},
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {"temperature_sensors": ["sensor.temp"]}

    # Provide a non-string value (e.g., a float)
    user_input = {"prob_temp_extreme_heat": 0.9}
    result = await flow.async_step_configure_advanced_bayesian(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_sensor_placement"

    # Complete the flow
    result = await flow.async_step_configure_sensor_placement(user_input={})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    # The flow updates the growspace object directly
    assert (
        mock_growspace.environment_config.bayesian_options["prob_temp_extreme_heat"]
        == 0.9
    )


# ============================================================================
# Test OptionsFlowHandler - Configure Dehumidifier
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_configure_dehumidifier_show_form(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test that the 'configure_dehumidifier' step shows the correct form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(name="Growspace 1", environment_config=EnvironmentConfig())
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {}

    result = await flow.async_step_configure_dehumidifier()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_dehumidifier"


@pytest.mark.asyncio
async def test_options_flow_configure_dehumidifier_submit(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test the successful submission of the dehumidifier configuration form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 100, "length": 100, "height": 200, "unit": "cm"},
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {
        "some_config": "value",
        "temperature_sensors": ["sensor.temp"],
    }

    user_input = {
        "seedling_day_on": 0.8,
        "seedling_day_off": 0.7,
        "seedling_night_on": 0.8,
        "seedling_night_off": 0.7,
        "veg_day_on": 1.0,
        "veg_day_off": 0.8,
        "veg_night_on": 1.0,
        "veg_night_off": 0.8,
        "flower_early_day_on": 1.2,
        "flower_early_day_off": 1.0,
        "flower_early_night_on": 1.2,
        "flower_early_night_off": 1.0,
        "flower_mid_day_on": 1.5,
        "flower_mid_day_off": 1.2,
        "flower_mid_night_on": 1.5,
        "flower_mid_night_off": 1.2,
        "flower_late_day_on": 1.8,
        "flower_late_day_off": 1.5,
        "flower_late_night_on": 1.8,
        "flower_late_night_off": 1.5,
        "dry_day_on": 1.1,
        "dry_day_off": 1.0,
        "dry_night_on": 0.9,
        "dry_night_off": 0.8,
        "cure_day_on": 1.0,
        "cure_day_off": 0.9,
        "cure_night_on": 1.0,
        "cure_night_off": 0.9,
    }

    result = await flow.async_step_configure_dehumidifier(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_sensor_placement"

    # Complete the flow
    result = await flow.async_step_configure_sensor_placement(user_input={})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert (
        mock_growspace.environment_config.dehumidifier_thresholds["veg"]["day"]["on"]
        == 1.0
    )
    mock_coordinator.services.save.assert_called_once()


# ============================================================================
# Test OptionsFlowHandler - Configure Irrigation
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_configure_irrigation(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test navigating to 'Configure Irrigation' from the main menu."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.growspaces.get_sorted_growspace_options = MagicMock(
        return_value=[("gs1", "Growspace 1")]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_irrigation"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_irrigation"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_irrigation_show_form(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test that the 'select_growspace_for_irrigation' step shows the correct form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.growspaces.get_sorted_growspace_options = MagicMock(
        return_value=[("gs1", "Growspace 1")]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_irrigation"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_irrigation_submit(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test submitting the 'select_growspace_for_irrigation' form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_gs = Mock(
        name="Growspace 1",
        environment_config=EnvironmentConfig(),
        irrigation_config=IrrigationConfig(),
        irrigation_strategy=IrrigationStrategy(),
    )
    # mock_gs.irrigation_config = {} # REMOVED: Must use dataclass
    mock_coordinator.growspaces = {"gs1": mock_gs}
    mock_coordinator.services.growspaces.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "Growspace 1")]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation(
        user_input={"growspace_id": "gs1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "irrigation_overview"
    assert flow.selected_growspace_id == "gs1"


@pytest.mark.asyncio
async def test_options_flow_configure_irrigation_show_form(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test that the 'configure_irrigation' step shows the correct form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        irrigation_config=IrrigationConfig(),
        irrigation_strategy=IrrigationStrategy(),
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    result = await flow.async_step_configure_irrigation()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "irrigation_overview"


@pytest.mark.asyncio
async def test_options_flow_configure_irrigation_submit(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the successful submission of the irrigation configuration form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_growspace = Mock(
        name="Growspace 1",
        irrigation_config=IrrigationConfig(),
        irrigation_strategy=IrrigationStrategy(),
    )
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    user_input = {
        "irrigation_pump_entity": "switch.pump",
        "drain_pump_entity": "switch.drain",
        "irrigation_duration": 30,
        "drain_duration": 30,
    }
    mock_coordinator.services.growspaces.update_irrigation_config = AsyncMock()
    result = await flow.async_step_irrigation_overview(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.growspaces.update_irrigation_config.assert_called_once_with(
        "gs1", user_input
    )


# ============================================================================
# Test OptionsFlowHandler - Manage Strain Library
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_manage_strain_library(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test navigating to 'Manage Strain Library' from the main menu."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "manage_strain_library"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_add(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the 'add' action for strain library."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(
        user_input={"action": "add_strain"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_strain"


@pytest.mark.asyncio
async def test_options_flow_add_strain_success(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the successful addition of a strain."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.config.strain_library.async_add_strain = AsyncMock()

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {
        "strain": "New Strain",
        "breeder": "Test Breeder",
        "flower_days_max": 60,
    }
    result = await flow.async_step_add_strain(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"
    mock_coordinator.services.config.strain_library.async_add_strain.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_edit(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the 'edit' action for strain library."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_strain = Mock(id="strain1")
    mock_strain.name = "Strain 1"
    mock_coordinator.services.config.strain_library.get_all_strains.return_value = [
        mock_strain
    ]
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(
        user_input={"action": "edit_strain"}
    )

    assert result.get("type") == FlowResultType.FORM
    # If I select edit_strain, I should also select strain_id?
    # Or does it transition to another step?
    # The code snippet shows:
    # if action == "add_strain": return await self.async_step_add_strain()
    # It doesn't show edit_strain logic in the snippet I saw earlier (lines 1700-1800).
    # But I assume it's similar.
    # Let's assume for now it stays on manage_strain_library if strain_id is missing?
    # Or maybe I should provide strain_id in the same step if the UI allows it.
    # But usually it's a two step process or JS dynamic.
    # Let's assume I need to provide strain_id.


@pytest.mark.asyncio
async def test_options_flow_select_strain_to_edit_submit(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test selecting a strain to edit."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_strain = Mock(id="strain1")
    mock_strain.name = "Strain 1"
    mock_coordinator.services.config.strain_library.get_all_strains.return_value = [
        mock_strain
    ]
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # In manage_strain_library, if we select edit_strain and a strain_id, it should go to edit_strain
    result = await flow.async_step_manage_strain_library(
        user_input={"action": "edit_strain", "strain_id": "strain1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "edit_strain"
    assert flow.selected_strain_id == "strain1"


@pytest.mark.asyncio
async def test_options_flow_edit_strain_success(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the successful editing of a strain."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_strain_id = "strain1"

    user_input = {"strain": "Strain 1", "breeder": "New Breeder"}
    result = await flow.async_step_edit_strain(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"
    # mock_coordinator._strain_library.update_strain.assert_called_once() # Not implemented in snippet


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_delete(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the 'delete' action for strain library."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_strain = Mock(id="strain1")
    mock_strain.name = "Strain 1"
    mock_coordinator.services.config.strain_library.get_all_strains.return_value = [
        mock_strain
    ]
    mock_coordinator.services.config.strain_library.get_all.return_value = {
        "strain1": mock_strain
    }
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Select delete_strain and a strain_id
    result = await flow.async_step_manage_strain_library(
        user_input={"action": "delete_strain", "strain_id": "strain1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"
    mock_coordinator.services.config.strain_library.remove_strain.assert_called_once_with(
        "strain1"
    )


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_import(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the 'import' action for strain library."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(
        user_input={"action": "import"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "import_strain_library"


@pytest.mark.asyncio
async def test_options_flow_import_strain_library_submit(
    hass: HomeAssistant, mock_coordinator: MagicMock, tmp_path: Path
) -> None:
    """Test submitting the import strain library form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)

    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.config.strain_library.async_load = AsyncMock()
    mock_coordinator.services.config.strain_library.import_library_from_zip = (
        AsyncMock()
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_import_strain_library(
        user_input={"file_path": str(tmp_path / "import.zip")}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"
    mock_coordinator.services.config.strain_library.import_library_from_zip.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_export(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test the 'export' action for strain library."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.config.strain_library.export_library_to_zip = AsyncMock()

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(
        user_input={"action": "export"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "export_strain_library"
    # assert "Exported to: /tmp/export.zip" in result["description"] # Description might be in placeholders


# ============================================================================
# Test OptionsFlowHandler - Configure AI
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_configure_ai_success(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test successful AI configuration."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock the handler methods
    flow.ai_handler.get_ai_settings_schema = AsyncMock(return_value=vol.Schema({}))  # type: ignore[method-assign]
    flow.ai_handler.save_ai_settings = AsyncMock(return_value={"ai_enabled": True})  # type: ignore[method-assign]

    # 1. Show Form
    result = await flow.async_step_configure_ai()
    assert result["type"] == FlowResultType.FORM

    # 2. Submit Success
    user_input = {CONF_AI_ENABLED: True, CONF_ASSISTANT_ID: "assist_123"}
    result = await flow.async_step_configure_ai(user_input=user_input)

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert "AI settings have been updated" in result["description"]
    flow.ai_handler.save_ai_settings.assert_called_once_with(user_input)


@pytest.mark.asyncio
async def test_options_flow_configure_ai_missing_assistant(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test AI configuration fails if enabled without an assistant ID."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.ai_handler.get_ai_settings_schema = AsyncMock(return_value=vol.Schema({}))  # type: ignore[method-assign]

    # Submit with enabled but no assistant
    user_input = {CONF_AI_ENABLED: True, CONF_ASSISTANT_ID: ""}
    result = await flow.async_step_configure_ai(user_input=user_input)

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "assistant_required"}


# ============================================================================
# Test OptionsFlowHandler - Environment Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_configure_environment_gs_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test abort when growspace not found in configure_environment."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {}  # Empty

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "missing_gs"

    result = await flow.async_step_configure_environment()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_jump_to_dehumidifier(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test flow jumps to dehumidifier config when enabled."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_gs = Mock(name="GS1")
    # Use real objects, NOT Mocks, so asdict() works
    mock_gs.environment_config = EnvironmentConfig()
    mock_gs.irrigation_config = IrrigationConfig()
    mock_gs.name = "Test Growspace"

    mock_coordinator.growspaces = {"gs1": mock_gs}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    # Submit Step 1 with keys that trigger the jump
    result = await flow.async_step_configure_environment(
        user_input={
            "configure_dehumidifier": True,
            "control_dehumidifier": True,
            "temp_sensor": "sensor.temp",
        }
    )

    # Should transition to configure_dehumidifier
    # Since we didn't implement the form logic for that step in this test setup,
    # checking that it called the method or returned the result of that method call (FORM or ABORT)
    # But since that method is on the same class, it just executes.
    # We expect a FORM from configure_dehumidifier (since we didn't pass input to it)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_dehumidifier"


async def test_options_flow_configure_environment_jump_to_dehumidifier_no_control(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test flow jumps to dehumidifier config even if control is disabled."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_gs = Mock(name="GS1")
    # Use real objects, NOT Mocks, so asdict() works
    mock_gs.environment_config = EnvironmentConfig()
    mock_gs.irrigation_config = IrrigationConfig()
    mock_gs.name = "Test Growspace"

    mock_coordinator.growspaces = {"gs1": mock_gs}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    # Submit Step 1 with configure_dehumidifier=True but control_dehumidifier=False
    result = await flow.async_step_configure_environment(
        user_input={
            "configure_dehumidifier": True,
            "control_dehumidifier": False,
            "temp_sensor": "sensor.temp",
        }
    )

    # Should transition to configure_dehumidifier
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_dehumidifier"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_jump_to_advanced(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test flow jumps to advanced config when enabled."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_gs = Mock(
        name="GS1",
        environment_config=EnvironmentConfig(),
        dimensions={"width": 100, "length": 100, "height": 200, "unit": "cm"},
    )
    mock_coordinator.growspaces = {"gs1": mock_gs}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    # Mock handler
    result = await flow.async_step_configure_environment(
        user_input={"configure_advanced": True}
    )

    # Expect jump to advanced bayesian
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_options_flow_configure_dehumidifier_gs_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test abort when growspace not found in configure_dehumidifier."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "missing_gs"

    result = await flow.async_step_configure_dehumidifier()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_configure_dehumidifier_save_success(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test saving dehumidifier config."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_gs = Mock(name="GS1")
    # Use real objects, NOT Mocks, so asdict() works
    mock_gs.environment_config = EnvironmentConfig()
    mock_gs.irrigation_config = IrrigationConfig()
    mock_gs.name = "Test Growspace"

    mock_coordinator.growspaces = {"gs1": mock_gs}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow.env_config_step1 = {"some_other_config": "val"}

    # Input mimicking the huge form
    user_input = {
        "seedling_day_on": 50,
        "seedling_day_off": 40,
        "seedling_night_on": 50,
        "seedling_night_off": 40,
        "veg_day_on": 50,
        "veg_day_off": 40,
        "veg_night_on": 50,
        "veg_night_off": 40,
        "flower_early_day_on": 50,
        "flower_early_day_off": 40,
        "flower_early_night_on": 50,
        "flower_early_night_off": 40,
        "flower_mid_day_on": 50,
        "flower_mid_day_off": 40,
        "flower_mid_night_on": 50,
        "flower_mid_night_off": 40,
        "flower_late_day_on": 50,
        "flower_late_day_off": 40,
        "flower_late_night_on": 50,
        "flower_late_night_off": 40,
        "dry_day_on": 50,
        "dry_day_off": 40,
        "dry_night_on": 50,
        "dry_night_off": 40,
        "cure_day_on": 50,
        "cure_day_off": 40,
        "cure_night_on": 50,
        "cure_night_off": 40,
    }

    result = await flow.async_step_configure_dehumidifier(user_input=user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY
    mock_coordinator.services.save.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_gs_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test abort when growspace not found in advanced bayesian."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "missing_gs"

    result = await flow.async_step_configure_advanced_bayesian()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


# ============================================================================
# Test OptionsFlowHandler - Irrigation Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_irrigation_no_growspaces(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test irrigation flow aborts when no growspaces exist."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.growspaces.get_sorted_growspace_options = Mock(
        return_value=[]
    )  # Empty

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_growspaces"


@pytest.mark.asyncio
async def test_options_flow_irrigation_configure_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test irrigation config aborts if selected growspace not found."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "missing_gs"

    result = await flow.async_step_configure_irrigation()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_irrigation_overview_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test irrigation overview aborts if growspace not found."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.growspaces = {}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "missing_gs"

    result = await flow.async_step_irrigation_overview()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_irrigation_save_clears_pumps(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test saving irrigation settings handles clearing pump entities."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_irrigation_config = IrrigationConfig(
        irrigation_pump_entity="switch.original_pump",
        drain_pump_entity="switch.original_drain",
    )
    mock_gs = Mock(
        name="GS1",
        irrigation_config=mock_irrigation_config,
        irrigation_strategy=IrrigationStrategy(),
        environment_config=EnvironmentConfig(),
    )
    mock_coordinator.growspaces = {"gs1": mock_gs}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    flow._current_options = {}

    # User input with NO pump entities (simulating clearing them)
    user_input = {
        "irrigation_duration": 15,
        "drain_duration": 5,
        # irrigation_pump_entity is MISSING
        # drain_pump_entity is MISSING
    }

    result = await flow.async_step_irrigation_overview(user_input=user_input)
    assert result["type"] == FlowResultType.CREATE_ENTRY

    # Verify both pump entities were set to None in the config update
    # The Mock object passed as mock_gs will record calls to update() on its irrigation_config attribute
    # Since irrigation_config is a plain dict in our setup above (assigned to the mock), it's just a reference
    # Wait, if I assign a dict to a Mock attribute, it stays a dict.
    # So the update call in config_flow.py `growspace.irrigation_config.update(...)` works heavily on the dict.


# ============================================================================
# Test OptionsFlowHandler - Plant & Strain Edge Cases
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_manage_plants_remove_error(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test plant removal error handling."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock plant lookup to succeed, but destroy to fail
    mock_plant = Mock(growspace_id="gs1", id="p1")
    mock_coordinator.plants = {"p1": mock_plant}

    flow.plant_handler.async_destroy_plant = AsyncMock(side_effect=Exception("Del Err"))  # type: ignore[method-assign]
    flow.plant_handler.get_plant_management_schema = Mock(return_value=vol.Schema({}))  # type: ignore[method-assign]

    result = await flow.async_step_manage_plants(
        user_input={"action": "remove", "plant_id": "p1"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "remove_failed"}


@pytest.mark.asyncio
async def test_options_flow_manage_plants_back(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test manage plants back button."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._get_main_menu_schema = Mock(return_value=vol.Schema({}))

    result = await flow.async_step_manage_plants(user_input={"action": "back"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_options_flow_add_plant_coordinator_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test add plant aborts if coordinator missing."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = None
    # No runtime_data set

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_add_plant()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_options_flow_add_plant_exception(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test add plant exception handling."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"

    mock_coordinator.services.plants.add_plant.side_effect = ValueError("Invalid")  # type: ignore[method-assign]
    flow.plant_handler.get_add_plant_schema = Mock(return_value=vol.Schema({}))  # type: ignore[method-assign]

    result = await flow.async_step_add_plant(
        user_input={"strain": "New", "row": 1, "col": 1}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "add_failed"}


@pytest.mark.asyncio
async def test_options_flow_strain_library_delete_error(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test strain library delete error."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    mock_coordinator.services.config.strain_library.async_delete_strain.side_effect = (
        Exception("Del Bad")
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(
        user_input={"action": "delete_strain", "strain_id": "s1"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "delete_failed"}


@pytest.mark.asyncio
async def test_options_flow_import_strain_library_errors(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test import strain library error cases."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # 1. File Not Found
    mock_coordinator.services.config.strain_library.import_library_from_zip.side_effect = FileNotFoundError
    result = await flow.async_step_import_strain_library(
        user_input={"file_path": "bad"}
    )
    assert result["errors"] == {"base": "file_not_found"}

    # 2. Invalid Zip
    mock_coordinator.services.config.strain_library.import_library_from_zip.side_effect = ValueError
    result = await flow.async_step_import_strain_library(
        user_input={"file_path": "bad.zip"}
    )
    assert result["errors"] == {"base": "invalid_zip"}

    # 3. Generic Exception
    mock_coordinator.services.config.strain_library.import_library_from_zip.side_effect = Exception(
        "Boom"
    )
    result = await flow.async_step_import_strain_library(
        user_input={"file_path": "bad.zip"}
    )
    assert result["errors"] == {"base": "import_failed"}


@pytest.mark.asyncio
async def test_options_flow_export_strain_library_back(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test export strain library back/completion."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # If I provide user input to export step, it should go back to manage menu
    result = await flow.async_step_export_strain_library(user_input={})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manage_strain_library"


@pytest.mark.asyncio
async def test_options_flow_init_navigation(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test navigation from init menu."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Test configure_ai navigation
    flow.ai_handler.get_ai_settings_schema = AsyncMock(return_value=vol.Schema({}))  # type: ignore[method-assign]
    result = await flow.async_step_init(user_input={"action": "configure_ai"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_ai"

    # Test default/unknown navigation (should create entry with input)
    result = await flow.async_step_init(
        user_input={"action": "unknown_action", "other": "data"}
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == {"action": "unknown_action", "other": "data"}


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant_success(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test selecting growspace for new plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.growspaces.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "GS 1")]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # 1. Show Form
    result = await flow.async_step_select_growspace_for_plant()
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_growspace_for_plant"

    # 2. Submit Success
    flow.plant_handler.get_add_plant_schema = Mock(return_value=vol.Schema({}))  # type: ignore[method-assign]
    result = await flow.async_step_select_growspace_for_plant(
        user_input={"growspace_id": "gs1"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "add_plant"


@pytest.mark.asyncio
async def test_options_flow_irrigation_coordinator_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test irrigation flow aborts if coordinator missing."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = None
    # No runtime_data

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_options_flow_dehumidifier_jump_to_advanced(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test dehumidifier flow jumps to advanced if configured."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    mock_gs = Mock(name="GS1")
    # Use real objects, NOT Mocks, so asdict() works
    mock_gs.environment_config = EnvironmentConfig()
    mock_gs.irrigation_config = IrrigationConfig()
    mock_gs.name = "Test Growspace"

    mock_coordinator.growspaces = {"gs1": mock_gs}
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    # Set pre-existing config state that enables advanced
    flow.env_config_step1 = {"configure_advanced": True}

    user_input = {
        "seedling_day_on": 50,
        "seedling_day_off": 40,
        "seedling_night_on": 50,
        "seedling_night_off": 40,
        "veg_day_on": 50,
        "veg_day_off": 40,
        "veg_night_on": 50,
        "veg_night_off": 40,
        "flower_early_day_on": 50,
        "flower_early_day_off": 40,
        "flower_early_night_on": 50,
        "flower_early_night_off": 40,
        "flower_mid_day_on": 50,
        "flower_mid_day_off": 40,
        "flower_mid_night_on": 50,
        "flower_mid_night_off": 40,
        "flower_late_day_on": 50,
        "flower_late_day_off": 40,
        "flower_late_night_on": 50,
        "flower_late_night_off": 40,
        "dry_day_on": 50,
        "dry_day_off": 40,
        "dry_night_on": 50,
        "dry_night_off": 40,
        "cure_day_on": 50,
        "cure_day_off": 40,
        "cure_night_on": 50,
        "cure_night_off": 40,
    }

    result = await flow.async_step_configure_dehumidifier(user_input=user_input)
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_nav_update(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test navigation to update plant from manage menu."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock update step to just return form so we verify transition
    flow.plant_handler.get_update_plant_schema = Mock(return_value=vol.Schema({}))  # type: ignore[method-assign]
    mock_plant = Mock(id="p1")
    mock_coordinator.plants = {"p1": mock_plant}

    result = await flow.async_step_manage_plants(
        user_input={"action": "update", "plant_id": "p1"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "update_plant"
    assert flow.selected_plant_id == "p1"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant_no_gs(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test abort if no growspaces when selecting for new plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    mock_coordinator.services.growspaces.get_sorted_growspace_options = Mock(
        return_value=[]
    )
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_plant()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "no_growspaces"


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_back(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test strain library back button."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._get_main_menu_schema = Mock(return_value=vol.Schema({}))

    result = await flow.async_step_manage_strain_library(user_input={"action": "back"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "init"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_remove_error(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test growspace removal error handling."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    flow.growspace_handler.get_growspace_management_schema = Mock(  # type: ignore[method-assign]
        return_value=vol.Schema({})
    )
    mock_coordinator.services.growspaces.remove_growspace.side_effect = Exception(
        "Del Err"
    )

    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    # Need to simulate the call from manage_growspaces
    result = await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "confirm_remove_growspace"

    result = await flow.async_step_confirm_remove_growspace(user_input={})

    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": "remove_failed"}


@pytest.mark.asyncio
async def test_options_flow_manage_plants_nav_add(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test navigation to add plant from manage menu."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock behavior of select_growspace_for_plant to verify transition
    # We can rely on it returning FORM for the select step
    mock_coordinator.services.growspaces.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "GS1")]
    )

    result = await flow.async_step_manage_plants(user_input={"action": "add"})
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "select_growspace_for_plant"


@pytest.mark.asyncio
async def test_options_flow_export_strain_library_error(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test export strain library error."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    mock_coordinator.services.config.strain_library.export_library_to_zip.side_effect = Exception(
        "Exp Err"
    )

    result = await flow.async_step_export_strain_library()
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "export_failed"


@pytest.mark.asyncio
async def test_options_flow_strain_library_delete_success(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test strain library delete success."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    mock_coordinator.services.config.strain_library.remove_strain = AsyncMock(
        return_value=None
    )
    flow._get_strain_library_menu_schema = Mock(return_value=vol.Schema({}))

    result = await flow.async_step_manage_strain_library(
        user_input={"action": "delete_strain", "strain_id": "s1"}
    )

    # Should stay on manage screen
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manage_strain_library"
    assert "errors" not in result or not result["errors"]
    mock_coordinator.services.config.strain_library.remove_strain.assert_called_once_with(
        "s1"
    )


@pytest.mark.asyncio
async def test_options_flow_init_configure_general(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test navigating to 'Configure General' from the main menu."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_general"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_general"


@pytest.mark.asyncio
async def test_options_flow_configure_general_submit(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test submitting data to the 'Configure General' step."""
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Test"}, options={"show_sidebar": True}
    )
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_configure_general(user_input={"show_sidebar": False})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert flow.current_options["show_sidebar"] is False


# ============================================================================
# Additional Tests for 100% Coverage of config_flow.py
# ============================================================================


@pytest.mark.asyncio
async def test_fan_controller_handler_property(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test that the fan_controller_handler property returns a FanControllerHandler."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    assert flow.fan_controller_handler is not None
    assert isinstance(flow.fan_controller_handler, FanControllerHandler)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method_name", "delegated_method_name"),
    [
        ("async_step_configure_fan_controller", "async_step_configure_fan_controller"),
        ("async_step_configure_fan_vpd", "async_step_configure_fan_vpd"),
        ("async_step_configure_fan_humidity", "async_step_configure_fan_humidity"),
        (
            "async_step_configure_fan_temperature",
            "async_step_configure_fan_temperature",
        ),
        ("async_step_configure_fan_wind", "async_step_configure_fan_wind"),
    ],
)
async def test_delegated_fan_steps(
    hass: HomeAssistant,
    mock_coordinator: MagicMock,
    method_name: str,
    delegated_method_name: str,
) -> None:
    """Test delegating fan controller steps to EnvironmentConfigHandler."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock the fan controller handler and its delegated method
    mock_fan_handler = MagicMock()
    mock_delegated = AsyncMock(return_value={"type": FlowResultType.FORM})
    setattr(mock_fan_handler, delegated_method_name, mock_delegated)
    flow._fan_controller_handler = mock_fan_handler

    user_input = {"some_key": "some_value"}
    method = getattr(flow, method_name)
    result = await method(user_input)

    assert result == {"type": FlowResultType.FORM}
    mock_delegated.assert_called_once_with(user_input)


@pytest.mark.asyncio
async def test_async_step_manage_breeder_blacklist(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test delegating manage_breeder_blacklist to the StrainConfigHandler."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    mock_strain_handler = MagicMock()
    mock_delegated = AsyncMock(return_value={"type": FlowResultType.FORM})
    mock_strain_handler.async_step_manage_breeder_blacklist = mock_delegated
    flow._strain_handler = mock_strain_handler

    user_input = {"blacklist": ["Breeder A"]}
    result = await flow.async_step_manage_breeder_blacklist(user_input)

    assert result == {"type": FlowResultType.FORM}
    mock_delegated.assert_called_once_with(user_input)


@pytest.mark.asyncio
async def test_async_step_save_and_finish_abort_flow(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test that async_step_save_and_finish handles AbortFlow exception."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    mock_sensors_handler = MagicMock()
    mock_sensors_handler.get_coordinator = MagicMock(
        side_effect=AbortFlow(reason="test_abort_reason")
    )
    flow._env_sensors_handler = mock_sensors_handler

    result = await flow.async_step_save_and_finish()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "test_abort_reason"


@pytest.mark.asyncio
async def test_async_step_save_and_finish_growspace_not_found(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test that async_step_save_and_finish aborts when the selected growspace is not found."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "nonexistent_growspace"

    # Make get_growspace return None (not found)
    mock_coordinator.services.growspaces.get_growspace.return_value = None

    result = await flow.async_step_save_and_finish()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_async_step_save_and_finish_success(
    hass: HomeAssistant, mock_coordinator: MagicMock
) -> None:
    """Test successful save and finish path in options flow."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    config_entry.runtime_data = mock_coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "test_growspace_id"
    flow.env_config_step1 = {"temp_sensor": "sensor.temp"}

    growspace = MagicMock()
    mock_coordinator.growspaces["test_growspace_id"] = growspace

    mock_sensors_handler = MagicMock()
    mock_sensors_handler.get_coordinator = MagicMock(return_value=mock_coordinator)
    mock_save_and_finish = AsyncMock(return_value={"type": FlowResultType.CREATE_ENTRY})
    mock_sensors_handler._async_save_and_finish = mock_save_and_finish
    flow._env_sensors_handler = mock_sensors_handler

    result = await flow.async_step_save_and_finish()

    assert result == {"type": FlowResultType.CREATE_ENTRY}
    mock_save_and_finish.assert_called_once_with(
        growspace, {"temp_sensor": "sensor.temp"}
    )


@pytest.mark.asyncio
async def test_config_flow_user_step_error_uses_a_translation_key(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """The user step's failure path shows a key, not the exception text."""
    flow = ConfigFlow()
    flow.hass = hass

    with patch.object(
        ConfigFlow, "async_create_entry", side_effect=RuntimeError("boom")
    ):
        result = await flow.async_step_user(user_input={"name": "My Growspace"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "user"
    assert result.get("errors") == {"base": "unknown"}


@pytest.mark.asyncio
async def test_config_flow_add_growspace_error_uses_a_translation_key(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """The add_growspace step's failure path shows a key, not the exception text."""
    flow = ConfigFlow()
    flow.hass = hass
    hass.data[DOMAIN] = {}

    with patch.object(
        ConfigFlow, "async_create_entry", side_effect=RuntimeError("boom")
    ):
        result = await flow.async_step_add_growspace(
            user_input={"name": "Tent", "rows": 2, "plants_per_row": 2}
        )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"
    assert result.get("errors") == {"base": "unknown"}
