
"""Test the Growspace Manager options flow."""

import pytest
import voluptuous as vol
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.config_flow import (
    OptionsFlowHandler,
)


# Helper function to set up the test environment
async def setup_test_environment(hass: HomeAssistant, coordinator):
    """Set up the test environment with a mock coordinator and config entry."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": coordinator}}
    return config_entry


@pytest.fixture
def basic_mock_coordinator(hass: HomeAssistant):
    """Fixture for a basic mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = hass
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.get_growspace_plants.return_value = []
    coordinator.get_sorted_growspace_options.return_value = []
    coordinator.async_add_growspace = AsyncMock()
    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_update_growspace = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_update_plant = AsyncMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    return coordinator


@pytest.fixture
def mock_store():
    """Fixture for a mock store."""
    store = AsyncMock()
    store.async_load = AsyncMock(return_value={"growspaces": {}, "plants": {}})
    return store


# ============================================================================
# Test OptionsFlowHandler - Main Menu
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_show_menu(hass: HomeAssistant, basic_mock_coordinator):
    """Test showing the main options menu."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_init()

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_init_manage_growspaces(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test selecting manage growspaces from menu."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_init(user_input={"action": "manage_growspaces"})

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_init_manage_plants(hass: HomeAssistant, basic_mock_coordinator):
    """Test selecting manage plants from menu."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_init(user_input={"action": "manage_plants"})

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_plants"


# ============================================================================
# Test OptionsFlowHandler - Manage Growspaces
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_show_form(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test showing manage growspaces form."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(user_input=None)

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_add(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test adding growspace action."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(user_input={"action": "add"})

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_update(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test update growspace action."""
    # Given
    basic_mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(
        user_input={"action": "update", "growspace_id": "gs1"}
    )

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"
    assert flow._selected_growspace_id == "gs1"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_remove(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test remove growspace action."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )

    # Then
    basic_mock_coordinator.async_remove_growspace.assert_called_once_with("gs1")


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_remove_error(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test error handling when removing growspace."""
    # Given
    basic_mock_coordinator.async_remove_growspace.side_effect = Exception("Test error")
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "remove_failed"}


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_back(hass, basic_mock_coordinator):
    """Test going back to main menu in manage growspaces step."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._get_main_menu_schema = lambda: vol.Schema({vol.Required("action"): str})
    result = await flow.async_step_manage_growspaces(user_input={"action": "back"})

    # Then
    assert result.get("type") == "form"
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_no_coordinator(hass: HomeAssistant):
    """Test error when coordinator not found."""
    # Given
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(user_input=None)

    # Then
    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "setup_error"


# ============================================================================
# Test OptionsFlowHandler - Add Growspace
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_add_growspace_show_form(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test showing add growspace form."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_add_growspace()

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_options_flow_add_growspace_success(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test successfully adding a growspace."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    user_input = {
        "name": "New Growspace",
        "rows": 5,
        "plants_per_row": 6,
        "notification_target": "mobile_app_test",
    }
    result = await flow.async_step_add_growspace(user_input=user_input)

    # Then
    assert result.get("type") == FlowResultType.CREATE_ENTRY
    basic_mock_coordinator.async_add_growspace.assert_called_once_with(
        name="New Growspace",
        rows=5,
        plants_per_row=6,
        notification_target="mobile_app_test",
    )


@pytest.mark.asyncio
async def test_options_flow_add_growspace_error(hass: HomeAssistant, basic_mock_coordinator):
    """Test error handling when adding growspace."""
    # Given
    basic_mock_coordinator.async_add_growspace.side_effect = Exception("Test error")
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    user_input = {"name": "Test", "rows": 4, "plants_per_row": 4}
    result = await flow.async_step_add_growspace(user_input=user_input)

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "add_failed"}


# ============================================================================
# Test OptionsFlowHandler - Update Growspace
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_update_growspace_show_form(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test showing update growspace form."""
    # Given
    mock_growspace = Mock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    basic_mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    result = await flow.async_step_update_growspace()

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_success(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test successfully updating a growspace."""
    # Given
    mock_growspace = Mock()
    mock_growspace.name = "Old Name"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    basic_mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    user_input = {"name": "New Name", "rows": 5}
    result = await flow.async_step_update_growspace(user_input=user_input)

    # Then
    assert result.get("type") == FlowResultType.CREATE_ENTRY
    basic_mock_coordinator.async_update_growspace.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_update_growspace_not_found(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test updating non-existent growspace."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "nonexistent"
    result = await flow.async_step_update_growspace()

    # Then
    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_error(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test error handling when updating growspace."""
    # Given
    mock_growspace = Mock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    basic_mock_coordinator.growspaces = {"gs1": mock_growspace}
    basic_mock_coordinator.async_update_growspace.side_effect = Exception("Test error")
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"
    user_input = {"name": "New Name"}
    result = await flow.async_step_update_growspace(user_input=user_input)

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "update_failed"}


# ============================================================================
# Test OptionsFlowHandler - Manage Plants
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_manage_plants_show_form(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test showing manage plants form."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_plants()

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_plants"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_add(hass, basic_mock_coordinator, mock_store):
    """Test the add plant action in the options flow."""
    # Given
    basic_mock_coordinator.growspaces = {"test_grow": Mock(name="Test Growspace")}
    basic_mock_coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)
    hass.data[DOMAIN][config_entry.entry_id]["store"] = mock_store

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._get_plant_management_schema = lambda _: vol.Schema(
        {vol.Required("action"): str}
    )
    result = await flow.async_step_manage_plants(user_input={"action": "add"})

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_plant"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_update(hass: HomeAssistant, basic_mock_coordinator, mock_store):
    """Test update plant action."""
    # Given
    basic_mock_coordinator.growspaces = {"test_grow": Mock(name="Test Growspace")}
    basic_mock_coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)
    hass.data[DOMAIN][config_entry.entry_id]["store"] = mock_store

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._get_plant_management_schema = lambda _: vol.Schema(
        {vol.Required("action"): str}
    )
    result = await flow.async_step_manage_plants(user_input={"action": "update"})

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_plants"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_remove(hass: HomeAssistant, basic_mock_coordinator):
    """Test remove plant action."""
    # Given
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    await flow.async_step_manage_plants(
        user_input={"action": "remove", "plant_id": "p1"}
    )

    # Then
    basic_mock_coordinator.async_remove_plant.assert_called_once_with("p1")


@pytest.mark.asyncio
async def test_options_flow_manage_plants_remove_error(
    hass: HomeAssistant, basic_mock_coordinator
):
    """Test error when removing plant."""
    # Given
    basic_mock_coordinator.async_remove_plant.side_effect = Exception("Test error")
    config_entry = await setup_test_environment(hass, basic_mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_plants(
        user_input={"action": "remove", "plant_id": "p1"}
    )

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "remove_failed"}
