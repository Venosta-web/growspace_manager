"""Tests for the Growspace Manager configuration and options flows.

This file contains a suite of tests to ensure that the config flow (for initial
setup) and the options flow (for post-setup configuration) of the Growspace
Manager integration work as expected. It covers various user interaction
scenarios, including adding/updating/removing growspaces and plants, configuring
environmental sensors, and managing timed notifications.
"""

import pytest
import voluptuous as vol
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import selector
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.const import DOMAIN, DEFAULT_NAME
from custom_components.growspace_manager.config_flow import (
    ConfigFlow,
    OptionsFlowHandler,
    ensure_default_growspaces,
)


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    """Create a mock GrowspaceCoordinator for testing.

    Args:
        hass: The Home Assistant instance.

    Returns:
        A MagicMock object that mimics the GrowspaceCoordinator.
    """
    # Use MagicMock with a spec for better type checking
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.hass = hass
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.data = {}
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()

    coordinator._ensure_special_growspace = Mock(return_value="mock_id")
    # Add mocks for all async methods called by the config/options flow
    coordinator.async_add_growspace = AsyncMock(return_value=Mock(id="gs1"))
    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_update_growspace = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_update_plant = AsyncMock()
    coordinator.get_growspace_plants = Mock(return_value=[])

    coordinator.get_sorted_growspace_options = AsyncMock(
        return_value=[("gs1", "Growspace 1")]
    )

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


@pytest.mark.asyncio
async def test_ensure_default_growspaces_creates_new(
    hass: HomeAssistant, mock_coordinator
):
    """Test that `ensure_default_growspaces` creates growspaces when none exist.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    mock_coordinator.growspaces = {}
    await ensure_default_growspaces(mock_coordinator)

    # Should create 5 default growspaces
    assert mock_coordinator._ensure_special_growspace.call_count == 5
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_set_updated_data.assert_called_once()


# ============================================================================
# Test ConfigFlow
# ============================================================================


@pytest.mark.asyncio
async def test_config_flow_user_step_show_form(hass: HomeAssistant):
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
async def test_config_flow_user_step_create_entry(hass: HomeAssistant):
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
async def test_config_flow_user_step_default_name(hass: HomeAssistant):
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
async def test_config_flow_add_growspace_show_form(hass: HomeAssistant):
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
async def test_config_flow_add_growspace_with_data(hass: HomeAssistant):
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
        "notification_target": "mobile_app_test",
    }

    result = await flow.async_step_add_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert "pending_growspace" in hass.data[DOMAIN]
    assert hass.data[DOMAIN]["pending_growspace"]["name"] == "Test Growspace"


@pytest.mark.asyncio
async def test_config_flow_get_add_growspace_schema_with_notify(hass: HomeAssistant):
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

    schema = flow._get_add_growspace_schema()

    assert "name" in schema.schema
    assert "rows" in schema.schema
    assert "plants_per_row" in schema.schema
    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_config_flow_get_add_growspace_schema_no_notify(hass: HomeAssistant):
    """Test that the growspace schema is correct when no notify services are found.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass
    flow.hass.services = Mock()
    flow.hass.services.async_services = Mock(return_value={"notify": {}})

    schema = flow._get_add_growspace_schema()

    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_config_flow_async_get_options_flow(hass: HomeAssistant):
    """Test that `async_get_options_flow` returns an `OptionsFlowHandler`.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    options_flow = ConfigFlow.async_get_options_flow(config_entry)

    assert isinstance(options_flow, OptionsFlowHandler)


# ============================================================================
# Test OptionsFlowHandler - Main Menu
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_show_menu(hass: HomeAssistant):
    """Test that the initial step of the options flow shows the main menu.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_init_manage_growspaces(
    hass: HomeAssistant, mock_coordinator
):
    """Test navigating to 'Manage Growspaces' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "manage_growspaces"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_init_manage_plants(hass: HomeAssistant, mock_coordinator):
    """Test navigating to 'Manage Plants' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

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
):
    """Test that the 'Manage Growspaces' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(user_input=None)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_add(
    hass: HomeAssistant, mock_coordinator
):
    """Test the 'add' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(user_input={"action": "add"})
    await hass.async_block_till_done()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_update(
    hass: HomeAssistant, mock_coordinator
):
    """Test the 'update' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(
        user_input={"action": "update", "growspace_id": "gs1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"
    assert flow._selected_growspace_id == "gs1"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_remove(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test the 'remove' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )

    mock_coordinator.async_remove_growspace.assert_called_once_with("gs1")
    assert result.get("type") == FlowResultType.FORM


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_remove_error(
    hass: HomeAssistant, mock_coordinator
):
    """Test error handling for the 'remove' action.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_back(hass, mock_coordinator):
    """Test the 'back' action in the 'Manage Growspaces' step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """

    # Create a mock config entry
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    # Make sure hass.data points to our mock coordinator
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

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
async def test_options_flow_manage_growspaces_no_coordinator(hass: HomeAssistant):
    """Test that an abort is triggered if the coordinator is not found.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

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
):
    """Test that the 'add_growspace' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}
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
):
    """Test the successful addition of a growspace via the options flow.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {
        "name": "New Growspace",
        "rows": 5,
        "plants_per_row": 6,
        "notification_target": "mobile_app_test",
    }

    result = await flow.async_step_add_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_add_growspace.assert_called_once_with(
        name="New Growspace",
        rows=5,
        plants_per_row=6,
        notification_target="mobile_app_test",
    )


@pytest.mark.asyncio
async def test_options_flow_add_growspace_error(hass: HomeAssistant, mock_coordinator):
    """Test error handling when adding a growspace fails.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_coordinator.async_add_growspace.side_effect = Exception("Test error")
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}
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
):
    """Test that the 'update_growspace' step shows the correct pre-filled form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    result = await flow.async_step_update_growspace()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_success(
    hass: HomeAssistant, mock_coordinator
):
    """Test the successful update of a growspace via the options flow.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.name = "Old Name"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    user_input = {"name": "New Name", "rows": 5}
    result = await flow.async_step_update_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_update_growspace.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_update_growspace_not_found(
    hass: HomeAssistant, mock_coordinator
):
    """Test that an abort is triggered if the growspace to update is not found.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_coordinator.growspaces = {}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "nonexistent"

    result = await flow.async_step_update_growspace()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_error(
    hass: HomeAssistant, mock_coordinator
):
    """Test error handling when updating a growspace fails.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_update_growspace.side_effect = Exception("Test error")

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    user_input = {"name": "New Name"}
    result = await flow.async_step_update_growspace(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result


# ============================================================================
# Test OptionsFlowHandler - Add Plant
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_add_plant_show_form(hass: HomeAssistant, mock_coordinator):
    """Test that the 'add_plant' step shows the correct form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    result = await flow.async_step_add_plant()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_plant"


@pytest.mark.asyncio
async def test_options_flow_add_plant_success(hass: HomeAssistant, mock_coordinator):
    """Test the successful addition of a plant via the options flow."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    user_input = {
        "strain": "Test Strain",
        "row": 1,
        "col": 1,
    }

    result = await flow.async_step_add_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_add_plant.assert_called_once_with(
        growspace_id="gs1",
        strain="Test Strain",
        row=1,
        col=1,
        phenotype=None,
        veg_start=None,
        flower_start=None,
    )


@pytest.mark.asyncio
async def test_options_flow_add_plant_error(hass: HomeAssistant, mock_coordinator):
    """Test error handling when adding a plant fails."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_add_plant.side_effect = Exception("Test error")
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

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
    assert result["errors"]["base"] == "Test error"


# ============================================================================
# Test OptionsFlowHandler - Update Plant
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_update_plant_show_form(
    hass: HomeAssistant, mock_coordinator
):
    """Test that the 'update_plant' step shows the correct form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_plant = Mock(strain="Old Strain", row=1, col=1)
    mock_coordinator.plants = {"p1": mock_plant}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_plant_id = "p1"

    result = await flow.async_step_update_plant()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_plant"


@pytest.mark.asyncio
async def test_options_flow_update_plant_success(hass: HomeAssistant, mock_coordinator):
    """Test the successful update of a plant via the options flow."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_plant = Mock(strain="Old Strain", row=1, col=1)
    mock_coordinator.plants = {"p1": mock_plant}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_plant_id = "p1"

    user_input = {"strain": "New Strain"}
    result = await flow.async_step_update_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_update_plant.assert_called_once_with("p1", **user_input)


@pytest.mark.asyncio
async def test_options_flow_update_plant_error(hass: HomeAssistant, mock_coordinator):
    """Test error handling when updating a plant fails."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_plant = Mock(strain="Old Strain", row=1, col=1)
    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.async_update_plant.side_effect = Exception("Test error")
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_plant_id = "p1"
    user_input = {"strain": "New Strain"}
    result = await flow.async_step_update_plant(user_input=user_input)

    assert result is not None
    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result
    assert result["errors"] is not None  # Add this assertion
    assert result["errors"]["base"] == "Test error"


@pytest.mark.asyncio
async def test_options_flow_update_plant_not_found(
    hass: HomeAssistant, mock_coordinator
):
    """Test that an abort is triggered if the plant to update is not found."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    mock_coordinator.plants = {}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_plant_id = "nonexistent"

    result = await flow.async_step_update_plant()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "plant_not_found"


# ============================================================================
# Test Schema Generation
# ============================================================================


@pytest.mark.asyncio
async def test_get_add_plant_schema_no_growspace(hass: HomeAssistant):
    """Test that _get_add_plant_schema returns an empty schema if growspace is None."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_plant_schema(growspace=None)
    assert schema.schema == {}


@pytest.mark.asyncio
async def test_get_add_plant_schema_no_strain_options(
    hass: HomeAssistant, mock_coordinator
):
    """Test _get_add_plant_schema when there are no strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.get_strain_options.return_value = []

    schema = flow._get_add_plant_schema(
        growspace=mock_growspace, coordinator=mock_coordinator
    )
    assert "strain" in schema.schema
    assert isinstance(schema.schema["strain"], selector.TextSelector)


@pytest.mark.asyncio
async def test_get_add_plant_schema_with_strain_options(
    hass: HomeAssistant, mock_coordinator
):
    """Test _get_add_plant_schema when there are strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.get_strain_options.return_value = ["Strain 1", "Strain 2"]

    schema = flow._get_add_plant_schema(
        growspace=mock_growspace, coordinator=mock_coordinator
    )
    assert "strain" in schema.schema
    assert isinstance(schema.schema["strain"], selector.SelectSelector)


@pytest.mark.asyncio
async def test_get_update_plant_schema_no_growspace(
    hass: HomeAssistant, mock_coordinator
):
    """Test that _get_update_plant_schema returns a schema even if growspace is None."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    mock_plant = Mock(strain="Test Strain", row=1, col=1, growspace_id="gs1")
    mock_coordinator.growspaces = {}  # No growspace

    schema = flow._get_update_plant_schema(
        plant=mock_plant, coordinator=mock_coordinator
    )
    assert "strain" in schema.schema


@pytest.mark.asyncio
async def test_get_update_plant_schema_no_strain_options(
    hass: HomeAssistant, mock_coordinator
):
    """Test _get_update_plant_schema when there are no strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    mock_plant = Mock(strain="Test Strain", row=1, col=1, growspace_id="gs1")
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_strain_options.return_value = []

    schema = flow._get_update_plant_schema(
        plant=mock_plant, coordinator=mock_coordinator
    )
    assert "strain" in schema.schema
    assert isinstance(schema.schema["strain"], selector.TextSelector)


@pytest.mark.asyncio
async def test_get_update_plant_schema_with_strain_options(
    hass: HomeAssistant, mock_coordinator
):
    """Test _get_update_plant_schema when there are strain options."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    mock_plant = Mock(strain="Test Strain", row=1, col=1, growspace_id="gs1")
    mock_growspace = Mock(name="Growspace 1", rows=4, plants_per_row=4)
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_strain_options.return_value = ["Strain 1", "Strain 2"]

    schema = flow._get_update_plant_schema(
        plant=mock_plant, coordinator=mock_coordinator
    )
    assert "strain" in schema.schema
    assert isinstance(schema.schema["strain"], selector.SelectSelector)


# ============================================================================
# Test Edge Cases and Error Conditions
# ============================================================================


@pytest.mark.asyncio
async def test_config_flow_user_step_exception(hass: HomeAssistant):
    """Test that exceptions during the user step are caught and handled.

    Args:
        hass: The Home Assistant instance.
    """
    flow = ConfigFlow()
    flow.hass = hass

    with patch.object(flow, "async_create_entry", side_effect=Exception("Test error")):
        result = await flow.async_step_user(user_input={"name": "Test"})
        assert result.get("type") == FlowResultType.FORM
        assert result.get("errors") == {"base": "Error: Test error"}


@pytest.mark.asyncio
async def test_config_flow_add_growspace_exception(hass: HomeAssistant):
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
async def test_options_flow_coordinator_missing(hass: HomeAssistant):
    """Test that various option flow steps abort if the coordinator is missing.

    Args:
        hass: The Home Assistant instance.
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Test"}, entry_id="test-entry-id"
    )
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Test add_growspace
    result = await flow.async_step_add_growspace()
    assert result.get("type") == FlowResultType.ABORT

    # Test update_growspace
    flow._selected_growspace_id = "gs1"
    result = await flow.async_step_update_growspace()
    assert result.get("type") == FlowResultType.ABORT


@pytest.mark.asyncio
async def test_options_flow_empty_update_data(hass: HomeAssistant, mock_coordinator):
    """Test that updating a growspace with empty/filtered data still succeeds.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    # Submit form with empty values
    user_input = {"name": "", "rows": None}
    result = await flow.async_step_update_growspace(user_input=user_input)

    # Should still succeed (empty updates are filtered)
    assert result.get("type") == FlowResultType.CREATE_ENTRY


# ============================================================================
# Test OptionsFlowHandler - Timed Notifications
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_manage_timed_notifications(
    hass: HomeAssistant, mock_coordinator
):
    """Test navigating to 'Timed Notifications' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

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
):
    """Test that the 'Manage Timed Notifications' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_timed_notifications(user_input=None)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_timed_notifications"


@pytest.mark.asyncio
async def test_options_flow_manage_timed_notifications_add(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test the 'add' action for timed notifications.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

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
):
    """Test the successful addition of a timed notification.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

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
    assert "timed_notifications" in result["data"]
    assert len(result["data"]["timed_notifications"]) == 1
    assert result["data"]["timed_notifications"][0]["message"] == "Test notification"


@pytest.mark.asyncio
async def test_options_flow_manage_timed_notifications_edit(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
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
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_timed_notifications(
        user_input={"action": "edit", "notification_id": "123"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "edit_timed_notification"
    assert flow._selected_notification_id == "123"


@pytest.mark.asyncio
async def test_options_flow_edit_timed_notification_success(
    hass: HomeAssistant, mock_coordinator
):
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
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_notification_id = "123"

    user_input = {
        "growspace_ids": ["gs1"],
        "trigger_type": "veg",
        "day": 20,
        "message": "New message",
    }

    result = await flow.async_step_edit_timed_notification(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert "timed_notifications" in result["data"]
    assert len(result["data"]["timed_notifications"]) == 1
    assert result["data"]["timed_notifications"][0]["message"] == "New message"
    assert result["data"]["timed_notifications"][0]["day"] == 20


@pytest.mark.asyncio
async def test_options_flow_manage_timed_notifications_delete(
    hass: HomeAssistant, mock_coordinator
):
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
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_timed_notifications(
        user_input={"action": "delete", "notification_id": "123"}
    )

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert "timed_notifications" in result["data"]
    assert len(result["data"]["timed_notifications"]) == 0


# ============================================================================
# Test OptionsFlowHandler - Environment Configuration
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_configure_environment(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test navigating to 'Configure Environment' from the main menu.

    Args:
        hass: The Home Assistant instance.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Test"}, options={}, entry_id="test-entry-id"
    )
    config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.get_sorted_growspace_options = MagicMock(
        return_value=[("gs1", "Growspace 1")]
    )
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_environment"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_env"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_env_show_form(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test that the 'select_growspace_for_env' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(
        domain=DOMAIN, data={"name": "Test"}, options={}, entry_id="test-entry-id"
    )
    config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.get_sorted_growspace_options = MagicMock(
        return_value=[("gs1", "Growspace 1")]
    )
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_env()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_env"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_env_no_growspaces(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that an abort is triggered if no growspaces exist to configure.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_coordinator.get_sorted_growspace_options = MagicMock(return_value=[])
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_env()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "no_growspaces"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_env_submit(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test submitting the 'select_growspace_for_env' form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    mock_coordinator.get_sorted_growspace_options = AsyncMock(
        return_value=[("gs1", "Growspace 1")]
    )
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    result = await flow.async_step_select_growspace_for_env(
        user_input={"growspace_id": "gs1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_environment"
    assert flow._selected_growspace_id == "gs1"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_show_form(
    hass: HomeAssistant, mock_coordinator
):
    """Test that the 'configure_environment' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    result = await flow.async_step_configure_environment()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_environment"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_submit(
    hass: HomeAssistant, mock_coordinator
):
    """Test the successful submission of the environment configuration form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", environment_config={})
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
    }
    result = await flow.async_step_configure_environment(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY

    # Check that environment_config was updated on the growspace object
    assert mock_growspace.environment_config["temperature_sensor"] == "sensor.temp"
    mock_coordinator.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_configure_environment_advanced(
    hass: HomeAssistant, mock_coordinator
):
    """Test navigating to the advanced Bayesian configuration step.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", environment_config={})
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    user_input = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        "vpd_sensor": "sensor.vpd",
        "configure_advanced": True,
    }
    result = await flow.async_step_configure_environment(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_show_form(
    hass: HomeAssistant, mock_coordinator
):
    """Test that the advanced Bayesian configuration step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    flow._env_config_step1 = {}

    result = await flow.async_step_configure_advanced_bayesian()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_advanced_bayesian"


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_submit(
    hass: HomeAssistant, mock_coordinator
):
    """Test the successful submission of the advanced Bayesian configuration.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", environment_config={})
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    flow._env_config_step1 = {}

    user_input = {"prob_temp_extreme_heat": "(0.9, 0.1)"}
    result = await flow.async_step_configure_advanced_bayesian(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY

    # Check that environment_config was updated
    assert mock_growspace.environment_config["prob_temp_extreme_heat"] == (0.9, 0.1)
    mock_coordinator.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_invalid_tuple(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test error handling for invalid tuple format in advanced Bayesian config.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", environment_config={})
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    flow._env_config_step1 = {}

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
):
    """Test navigating to 'Configure Global' from the main menu.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_global"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_global"


@pytest.mark.asyncio
async def test_options_flow_configure_global_show_form(
    hass: HomeAssistant, mock_coordinator
):
    """Test that the 'Configure Global' step shows the correct form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_configure_global()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_global"


@pytest.mark.asyncio
async def test_options_flow_configure_global_submit(
    hass: HomeAssistant, mock_coordinator
):
    """Test the successful submission of the global configuration form.

    Args:
        hass: The Home Assistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {"weather_entity": "weather.home"}
    result = await flow.async_step_configure_global(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert "global_settings" in result["data"]
    assert result["data"]["global_settings"]["weather_entity"] == "weather.home"


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_non_tuple_parsed_value(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test error handling for non-tuple parsed value in advanced Bayesian config.
    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", environment_config={})
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    flow._env_config_step1 = {}
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
async def test_options_flow_configure_advanced_bayesian_non_string_value(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test handling of non-string values in advanced Bayesian config.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_growspace = Mock(name="Growspace 1", environment_config={})
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    flow._env_config_step1 = {}

    # Provide a non-string value (e.g., a float)
    user_input = {"prob_temp_extreme_heat": 0.9}
    result = await flow.async_step_configure_advanced_bayesian(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY

    # Check updated config
    assert mock_growspace.environment_config["prob_temp_extreme_heat"] == 0.9
    mock_coordinator.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_default_growspaces_already_exist(mock_coordinator):
    """Test that no changes are made if default growspaces already exist.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    mock_coordinator.growspaces = {
        "dry": Mock(),
        "cure": Mock(),
        "mother": Mock(),
        "clone": Mock(),
        "veg": Mock(),
    }

    # Ensure method returns the same IDs so they are "already present"
    mock_coordinator._ensure_special_growspace = lambda gid, name, rows, plants: gid

    await ensure_default_growspaces(mock_coordinator)

    # Should not save if all exist
    mock_coordinator.async_save.assert_not_called()


# ============================================================================
# Test ensure_default_growspaces Error Handling
# ============================================================================


@pytest.mark.asyncio
async def test_ensure_default_growspaces_error_handling(mock_coordinator):
    """Test that errors in ensure_default_growspaces are handled gracefully.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    # Make _ensure_special_growspace raise an error
    mock_coordinator._ensure_special_growspace = Mock(
        side_effect=ValueError("Test error")
    )

    # Should not raise, just log the error
    await ensure_default_growspaces(mock_coordinator)

    # async_save should not be called if there's an error
    mock_coordinator.async_save.assert_not_called()


# ============================================================================
# Test Options Flow - AI Settings
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_configure_ai_show_form(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that the AI configuration step shows the form.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_configure_ai()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_ai"


@pytest.mark.asyncio
async def test_options_flow_configure_ai_enable(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test enabling AI features with valid settings.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.options = {}
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {
        "ai_enabled": True,
        "assistant_id": "conversation.openai",
        "notification_personality": "Friendly",
        "ai_notifications_enabled": True,
    }

    result = await flow.async_step_configure_ai(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_save.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_configure_ai_missing_assistant(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test error when AI is enabled but no assistant selected.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {
        "ai_enabled": True,
        "assistant_id": None,  # Missing assistant
    }

    result = await flow.async_step_configure_ai(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "assistant_required"}


@pytest.mark.asyncio
async def test_options_flow_navigate_to_configure_ai(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test navigation from main menu to AI configuration.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_ai"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_ai"


@pytest.mark.asyncio
async def test_options_flow_navigate_to_strain_library(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test navigation from main menu to strain library management.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "manage_strain_library"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"


@pytest.mark.asyncio
async def test_options_flow_navigate_to_irrigation(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test navigation from main menu to irrigation configuration.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "Test Growspace")]
    )

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_init(user_input={"action": "configure_irrigation"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_irrigation"


# ============================================================================
# Test Options Flow - Irrigation Configuration
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_irrigation_show_form(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that the irrigation growspace selection shows the form.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "Test Growspace")]
    )

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_irrigation"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_irrigation_no_growspaces(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that irrigation flow aborts when no growspaces exist.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.growspaces = {}
    mock_coordinator.get_sorted_growspace_options = Mock(return_value=[])

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "no_growspaces"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_irrigation_submit(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test selecting a growspace for irrigation configuration.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.irrigation_config = {}
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "Test Growspace")]
    )

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation(
        user_input={"growspace_id": "gs1"}
    )

    # Should proceed to irrigation overview
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "irrigation_overview"


@pytest.mark.asyncio
async def test_options_flow_configure_irrigation_growspace_not_found(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that irrigation config aborts if growspace not found.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.growspaces = {}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "nonexistent"

    result = await flow.async_step_configure_irrigation()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_irrigation_overview_show_form(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that irrigation overview shows the full form.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.irrigation_config = {
        "irrigation_pump_entity": "switch.pump",
        "drain_pump_entity": "switch.drain",
        "irrigation_duration": 60,
        "drain_duration": 30,
        "irrigation_times": [],
        "drain_times": [],
    }
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    result = await flow.async_step_irrigation_overview()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "irrigation_overview"


# ============================================================================
# Test Options Flow - Strain Library Management
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_show_form(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that strain library management shows the form.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_add_action(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test navigating to add strain form.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(user_input={"action": "add"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_strain"


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_remove_action(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test removing a strain from the library.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(
        return_value={"Blue Dream": {"phenotypes": {"default": {}}}}
    )
    mock_coordinator.strains.remove_strain_phenotype = AsyncMock()

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(
        user_input={"action": "remove", "strain_id": "Blue Dream|default"}
    )

    mock_coordinator.strains.remove_strain_phenotype.assert_called_once_with(
        "Blue Dream", "default"
    )
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"


@pytest.mark.asyncio
async def test_options_flow_manage_strain_library_back_action(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test going back to main menu from strain library.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_strain_library(user_input={"action": "back"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_add_strain_show_form(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test that add strain step shows the form.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_add_strain()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_strain"


@pytest.mark.asyncio
async def test_options_flow_add_strain_submit(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test adding a new strain successfully.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})
    mock_coordinator.strains.add_strain = AsyncMock()

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {
        "strain": "Blue Dream",
        "phenotype": "default",
        "breeder": "DJ Short",
        "type": "Hybrid",
    }

    result = await flow.async_step_add_strain(user_input=user_input)

    mock_coordinator.strains.add_strain.assert_called_once()
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_strain_library"


@pytest.mark.asyncio
async def test_options_flow_add_strain_error(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test error handling when adding a strain fails.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})
    mock_coordinator.strains.add_strain = AsyncMock(
        side_effect=Exception("Database error")
    )

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {"strain": "Blue Dream"}

    result = await flow.async_step_add_strain(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_strain"
    assert "base" in result.get("errors", {})


# ============================================================================
# Test AI Settings Schema Building
# ============================================================================


@pytest.mark.asyncio
async def test_get_ai_settings_schema_with_assistants(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test AI settings schema when conversation agents are available.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    from homeassistant.components import conversation

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock conversation agents
    mock_agent = MagicMock()
    mock_agent.name = "OpenAI"

    with patch.object(
        conversation,
        "async_get_conversation_agents",
        return_value={"conversation.openai": mock_agent},
        create=True,
    ):
        schema = await flow._get_ai_settings_schema()

    assert schema is not None


@pytest.mark.asyncio
async def test_get_ai_settings_schema_no_assistants(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test AI settings schema when no conversation agents are available.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    from homeassistant.components import conversation

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock no agents - use patch.object with create=True for methods that may not exist
    with (
        patch.object(
            conversation,
            "async_get_conversation_agents",
            return_value={},
            create=True,
        ),
        patch.object(
            conversation,
            "async_get_agent",
            side_effect=Exception("No default agent"),
            create=True,
        ),
    ):
        schema = await flow._get_ai_settings_schema()

    # Should still return a schema with text selector fallback
    assert schema is not None


@pytest.mark.asyncio
async def test_get_ai_settings_schema_agent_fetch_error(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test AI settings schema when agent fetching fails.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    from homeassistant.components import conversation

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Mock agent fetch error - use patch.object with create=True
    with (
        patch.object(
            conversation,
            "async_get_conversation_agents",
            side_effect=Exception("Network error"),
            create=True,
        ),
        patch.object(
            conversation,
            "async_get_agent",
            side_effect=Exception("No agent"),
            create=True,
        ),
    ):
        schema = await flow._get_ai_settings_schema()

    # Should gracefully handle error and still return a schema
    assert schema is not None


# ============================================================================
# Test Options Flow - Irrigation Flow Error Cases
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_select_growspace_irrigation_coordinator_missing(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test irrigation flow when coordinator is missing.

    Args:
        hass: The HomeAssistant instance.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    # Don't set up coordinator in hass.data
    hass.data[DOMAIN] = {}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_irrigation()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "setup_error"


# ============================================================================
# Test Strain Management Schema
# ============================================================================


def test_get_strain_management_schema_with_strains(mock_coordinator):
    """Test strain management schema with existing strains.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(
        return_value={
            "Blue Dream": {"phenotypes": {"default": {}, "purple": {}}},
            "OG Kush": {"phenotypes": {"default": {}}},
        }
    )

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)

    schema = flow._get_strain_management_schema(mock_coordinator)

    assert schema is not None


def test_get_strain_management_schema_empty(mock_coordinator):
    """Test strain management schema with no strains.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    mock_coordinator.strains = MagicMock()
    mock_coordinator.strains.get_all = Mock(return_value={})

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)

    schema = flow._get_strain_management_schema(mock_coordinator)

    assert schema is not None


# ============================================================================
# Test Plant Management Schema
# ============================================================================


def test_get_plant_management_schema_with_plants(mock_coordinator):
    """Test plant management schema with existing plants.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    mock_plant = MagicMock()
    mock_plant.strain = "Blue Dream"
    mock_plant.growspace_id = "gs1"
    mock_plant.row = 1
    mock_plant.col = 2

    mock_growspace = MagicMock()
    mock_growspace.name = "Flower Tent"

    mock_coordinator.plants = {"plant1": mock_plant}
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)

    schema = flow._get_plant_management_schema(mock_coordinator)

    assert schema is not None


# ============================================================================
# Test Add Strain Schema
# ============================================================================


def test_get_add_strain_schema():
    """Test add strain schema generation."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)

    schema = flow._get_add_strain_schema()

    assert schema is not None


# ============================================================================
# Additional Edge Case Tests for Coverage
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_configure_environment_growspace_not_found(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test environment config aborts if growspace not found.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.growspaces = {}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "nonexistent"

    result = await flow.async_step_configure_environment()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_lst_offset_branch(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test environment config shows LST offset when temp/humidity set but not VPD.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.environment_config = {
        "temperature_sensor": "sensor.temp",
        "humidity_sensor": "sensor.humidity",
        # vpd_sensor intentionally not set
    }
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    result = await flow.async_step_configure_environment()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_environment"


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_growspace_not_found(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test advanced Bayesian config aborts if growspace not found.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.growspaces = {}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "nonexistent"
    flow._env_config_step1 = {}

    result = await flow.async_step_configure_advanced_bayesian()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_update_action(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test manage plants update action with plant selected.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_plant = MagicMock()
    mock_plant.strain = "Blue Dream"
    mock_plant.growspace_id = "gs1"
    mock_plant.row = 1
    mock_plant.col = 1

    mock_growspace = MagicMock()
    mock_growspace.name = "Flower"

    mock_coordinator.plants = {"plant1": mock_plant}
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "Flower")]
    )
    mock_coordinator.get_strain_options = Mock(return_value=["Blue Dream"])

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_plants(
        user_input={"action": "update", "plant_id": "plant1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_plant"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_back_action(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test manage plants back action returns to main menu.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.plants = {}
    mock_coordinator.growspaces = {}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_plants(user_input={"action": "back"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant_no_devices(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test plant growspace selection shows error when no devices found.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    from homeassistant.helpers.storage import Store

    mock_store = MagicMock(spec=Store)
    mock_store.async_load = AsyncMock(return_value={"growspaces": {}, "plants": {}})

    mock_coordinator.growspaces = {}
    mock_coordinator.plants = {}
    mock_coordinator.data = {"growspaces": {}, "plants": {}}
    mock_coordinator._notifications_sent = {}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {
        config_entry.entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_plant()

    assert result.get("type") == FlowResultType.FORM
    assert "base" in result.get("errors", {})


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant_coordinator_error(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test plant growspace selection aborts on coordinator error.

    Args:
        hass: The HomeAssistant instance.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {}  # No coordinator

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_select_growspace_for_plant()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "setup_error"


def test_get_timed_notification_schema_with_notifications(mock_coordinator, hass):
    """Test timed notification schema with existing notifications.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
        hass: The HomeAssistant instance.
    """
    mock_coordinator.options = {
        "timed_notifications": [
            {"id": "notif1", "time": "08:00", "message": "Water plants"},
            {"id": "notif2", "time": "20:00", "message": "Check lights"},
        ]
    }

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_timed_notification_schema(mock_coordinator)

    assert schema is not None


def test_get_add_growspace_schema(mock_coordinator, hass):
    """Test add growspace schema generation.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
        hass: The HomeAssistant instance.
    """
    # Set up notify services for the branch
    hass.services._services = {"notify": {"mobile_app_phone": MagicMock()}}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_growspace_schema()

    assert schema is not None


def test_get_add_growspace_schema_no_notify_services(mock_coordinator, hass):
    """Test add growspace schema when no notify services available.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
        hass: The HomeAssistant instance.
    """
    hass.services._services = {"notify": {}}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_growspace_schema()

    assert schema is not None


def test_get_update_growspace_schema_no_growspace():
    """Test update growspace schema returns empty when growspace is None."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)

    schema = flow._get_update_growspace_schema(None)

    assert schema is not None


def test_get_update_growspace_schema_with_notify_services(mock_coordinator, hass):
    """Test update growspace schema with notify services.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
        hass: The HomeAssistant instance.
    """
    hass.services._services = {"notify": {"mobile_app_phone": MagicMock()}}

    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = "mobile_app_phone"

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_update_growspace_schema(mock_growspace)

    assert schema is not None


def test_get_update_growspace_schema_no_notify_services(mock_coordinator, hass):
    """Test update growspace schema without notify services.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
        hass: The HomeAssistant instance.
    """
    hass.services._services = {"notify": {}}

    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_update_growspace_schema(mock_growspace)

    assert schema is not None


def test_get_growspace_management_schema_with_growspaces(mock_coordinator):
    """Test growspace management schema with existing growspaces.

    Args:
        mock_coordinator: The mock GrowspaceCoordinator.
    """
    mock_coordinator.get_sorted_growspace_options = Mock(
        return_value=[("gs1", "Flower Tent"), ("gs2", "Veg Tent")]
    )

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    flow = OptionsFlowHandler(config_entry)

    schema = flow._get_growspace_management_schema(mock_coordinator)

    assert schema is not None


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_back_action(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test manage growspaces back action returns to main menu.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.get_sorted_growspace_options = Mock(return_value=[])

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(user_input={"action": "back"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_irrigation_overview_growspace_not_found(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test irrigation overview aborts when growspace not found.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_coordinator.growspaces = {}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "nonexistent"

    result = await flow.async_step_irrigation_overview()

    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_non_tuple_result(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test advanced Bayesian config with non-tuple parsed value (TypeError branch).

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    mock_growspace = MagicMock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.environment_config = {}
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    flow._env_config_step1 = {}

    # Provide a value that parses but is not a tuple (e.g., list)
    user_input = {"prob_temp_extreme_heat": "[0.9, 0.1]"}
    result = await flow.async_step_configure_advanced_bayesian(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "configure_advanced_bayesian"
    assert "base" in result.get("errors", {})


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant_with_devices(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test plant growspace selection with devices available and submission.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    from homeassistant.helpers.storage import Store
    from homeassistant.helpers import device_registry as dr

    mock_store = MagicMock(spec=Store)
    mock_store.async_load = AsyncMock(
        return_value={
            "growspaces": {
                "gs1": {"id": "gs1", "name": "Test", "rows": 4, "plants_per_row": 4}
            },
            "plants": {},
        }
    )

    mock_growspace = MagicMock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4

    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.plants = {}
    mock_coordinator.data = {"growspaces": {"gs1": mock_growspace}, "plants": {}}
    mock_coordinator._notifications_sent = {}
    mock_coordinator.get_strain_options = Mock(return_value=["Blue Dream"])

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {
        config_entry.entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    # Create a mock device in the registry
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "gs1")},
        name="Test Growspace",
        model="Growspace",
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Test with user input selecting a growspace
    result = await flow.async_step_select_growspace_for_plant(
        user_input={"growspace_id": "gs1"}
    )

    assert result.get("type") == FlowResultType.FORM
    # Should proceed to add_plant step
    assert result.get("step_id") == "add_plant"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant_show_form(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test plant growspace selection shows form when devices exist.

    Args:
        hass: The HomeAssistant instance.
        mock_coordinator: The mock GrowspaceCoordinator.
        enable_custom_integrations: Fixture to enable custom integrations.
    """
    from homeassistant.helpers.storage import Store
    from homeassistant.helpers import device_registry as dr

    mock_store = MagicMock(spec=Store)
    mock_store.async_load = AsyncMock(
        return_value={
            "growspaces": {
                "gs1": {"id": "gs1", "name": "Test", "rows": 4, "plants_per_row": 4}
            },
            "plants": {},
        }
    )

    mock_growspace = MagicMock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4

    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.plants = {}
    mock_coordinator.data = {"growspaces": {"gs1": mock_growspace}, "plants": {}}
    mock_coordinator._notifications_sent = {}

    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {
        config_entry.entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    # Create a mock device in the registry
    dev_reg = dr.async_get(hass)
    dev_reg.async_get_or_create(
        config_entry_id=config_entry.entry_id,
        identifiers={(DOMAIN, "gs1")},
        name="Test Growspace",
        model="Growspace",
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Test without user input to get form
    result = await flow.async_step_select_growspace_for_plant()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_plant"
