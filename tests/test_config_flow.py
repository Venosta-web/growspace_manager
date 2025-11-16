"""Test the Growspace Manager config and options flow."""

import pytest
import voluptuous as vol
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN, DEFAULT_NAME
from custom_components.growspace_manager.config_flow import (
    ConfigFlow,
    OptionsFlowHandler,
    ensure_default_growspaces,
)


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    """Fixture for a mock coordinator."""
    coordinator = MagicMock()
    coordinator.hass = hass
    mock_growspace = MagicMock()
    mock_growspace.name = "Growspace 1"
    coordinator.growspaces = {"gs1": mock_growspace}
    coordinator.plants = {}
    coordinator.get_growspace_plants.return_value = []
    coordinator.get_sorted_growspace_options.return_value = [("gs1", "Growspace 1")]
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
# Test ensure_default_growspaces
# ============================================================================


@pytest.mark.asyncio
async def test_ensure_default_growspaces_creates_new(
    hass: HomeAssistant, mock_coordinator
):
    """Test creating default growspaces when they don't exist."""
    mock_coordinator.growspaces = {}
    await ensure_default_growspaces(hass, mock_coordinator)

    # Should create 5 default growspaces
    assert mock_coordinator.ensure_special_growspace.call_count == 5
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_set_updated_data.assert_called_once()


@pytest.mark.asyncio
async def test_ensure_default_growspaces_already_exist(hass, mock_coordinator):
    """Test when default growspaces already exist."""
    mock_coordinator.growspaces = {
        "dry": Mock(),
        "cure": Mock(),
        "mother": Mock(),
        "clone": Mock(),
        "veg": Mock(),
    }

    # Ensure method returns the same IDs so they are "already present"
    mock_coordinator.ensure_special_growspace = lambda gid, name, rows, plants: gid

    await ensure_default_growspaces(hass, mock_coordinator)

    # Should not save if all exist
    mock_coordinator.async_save.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_default_growspaces_error_handling(
    hass: HomeAssistant, mock_coordinator
):
    """Test error handling in ensure_default_growspaces."""
    mock_coordinator.ensure_special_growspace.side_effect = Exception("Test error")

    # Should not raise exception
    await ensure_default_growspaces(hass, mock_coordinator)


# ============================================================================
# Test ConfigFlow
# ============================================================================


@pytest.mark.asyncio
async def test_config_flow_user_step_show_form(hass: HomeAssistant):
    """Test showing the user config form."""
    flow = ConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "user"


@pytest.mark.asyncio
async def test_config_flow_user_step_create_entry(hass: HomeAssistant):
    """Test creating entry from user input."""
    flow = ConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(user_input={"name": "My Growspace"})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert result.get("title") == "My Growspace"
    assert result.get("data") == {"name": "My Growspace"}


@pytest.mark.asyncio
async def test_config_flow_user_step_default_name(hass: HomeAssistant):
    """Test using default name."""
    flow = ConfigFlow()
    flow.hass = hass

    result = await flow.async_step_user(user_input={"name": DEFAULT_NAME})

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert result.get("data") == {"name": DEFAULT_NAME}


@pytest.mark.asyncio
async def test_config_flow_add_growspace_show_form(hass: HomeAssistant):
    """Test showing add growspace form."""
    flow = ConfigFlow()
    flow.hass = hass
    flow.hass.services = Mock()
    flow.hass.services.async_services = Mock(return_value={"notify": {}})

    result = await flow.async_step_add_growspace()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_config_flow_add_growspace_with_data(hass: HomeAssistant):
    """Test adding growspace with data."""
    flow = ConfigFlow()
    flow.hass = hass
    integration_name = "Growspace Manager"
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
    """Test schema generation with notify services."""
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
    """Test schema generation without notify services."""
    flow = ConfigFlow()
    flow.hass = hass
    flow.hass.services = Mock()
    flow.hass.services.async_services = Mock(return_value={"notify": {}})

    schema = flow._get_add_growspace_schema()

    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_config_flow_async_get_options_flow():
    """Test getting options flow handler."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})

    options_flow = ConfigFlow.async_get_options_flow(config_entry)

    assert isinstance(options_flow, OptionsFlowHandler)


# ============================================================================
# Test OptionsFlowHandler - Main Menu
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_show_menu(hass: HomeAssistant):
    """Test showing the main options menu."""
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
    """Test selecting manage growspaces from menu."""
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
    """Test selecting manage plants from menu."""
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
    """Test showing manage growspaces form."""
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
    """Test adding growspace action."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_growspaces(user_input={"action": "add"})

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_update(
    hass: HomeAssistant, mock_coordinator
):
    """Test update growspace action."""
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
    """Test remove growspace action."""
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
    """Test error handling when removing growspace."""
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
    """Test going back to main menu in manage growspaces step."""

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
    """Test error when coordinator not found."""
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
    """Test showing add growspace form."""
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
    """Test successfully adding a growspace."""
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
    """Test error handling when adding growspace."""
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
    """Test showing update growspace form."""
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
    """Test successfully updating a growspace."""
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
    """Test updating non-existent growspace."""
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
    """Test error handling when updating growspace."""
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
# Test OptionsFlowHandler - Manage Plants
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_manage_plants_show_form(
    hass: HomeAssistant, mock_coordinator
):
    """Test showing manage plants form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_plants()

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_plants"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_add(hass):
    """Test the add plant action in the options flow."""

    # Create mock config entry
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    entry_id = config_entry.entry_id

    # Mock coordinator
    mock_coordinator = Mock()
    mock_coordinator.async_add_plant = AsyncMock()
    mock_coordinator.async_remove_plant = AsyncMock()
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.plants = {}
    mock_coordinator.growspaces = {"test_grow": Mock(name="Test Growspace")}
    mock_coordinator.get_strain_options = Mock(return_value=["Strain A", "Strain B"])

    # Mock store
    mock_store = Mock()
    mock_store.async_load = AsyncMock(return_value={})

    # Register both under hass.data
    hass.data[DOMAIN] = {
        entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    # Create the flow
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Patch schema getter to avoid device registry dependency
    flow._get_plant_management_schema = lambda _: vol.Schema(
        {vol.Required("action"): str}
    )

    # Call the step
    result = await flow.async_step_manage_plants(user_input={"action": "add"})

    # Verify result type and step
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "select_growspace_for_plant"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_update(hass: HomeAssistant, mock_coordinator):
    """Test update plant action."""
    # Create mock config entry
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    entry_id = config_entry.entry_id

    # Mock coordinator
    mock_coordinator = Mock()
    mock_coordinator.async_add_plant = AsyncMock()
    mock_coordinator.async_remove_plant = AsyncMock()
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.plants = {}
    mock_coordinator.growspaces = {"test_grow": Mock(name="Test Growspace")}
    mock_coordinator.get_strain_options = Mock(return_value=["Strain A", "Strain B"])

    # Mock store
    mock_store = Mock()
    mock_store.async_load = AsyncMock(return_value={})

    # Register both under hass.data
    hass.data[DOMAIN] = {
        entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    # Create the flow
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    # Patch schema getter to avoid device registry dependency
    flow._get_plant_management_schema = lambda _: vol.Schema(
        {vol.Required("action"): str}
    )

    # Call the step
    result = await flow.async_step_manage_plants(user_input={"action": "update"})

    # Verify result type and step
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_plants"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_remove(hass: HomeAssistant, mock_coordinator):
    """Test remove plant action."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_plants(
        user_input={"action": "remove", "plant_id": "p1"}
    )

    mock_coordinator.async_remove_plant.assert_called_once_with("p1")
    assert result.get("type") == FlowResultType.FORM


@pytest.mark.asyncio
async def test_options_flow_manage_plants_remove_error(
    hass: HomeAssistant, mock_coordinator
):
    """Test error when removing plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    result = await flow.async_step_manage_plants(
        user_input={"action": "remove", "plant_id": "p1"}
    )

    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result


# ============================================================================
# Test OptionsFlowHandler - Select Growspace for Plant
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant(
    hass: HomeAssistant, mock_coordinator, mock_store, enable_custom_integrations
):
    """Test selecting growspace for new plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    hass.data[DOMAIN] = {
        config_entry.entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    # Mock device registry
    with patch(
        "custom_components.growspace_manager.config_flow.dr.async_get"
    ) as mock_dr:
        mock_device_registry = Mock()
        mock_device = Mock()
        mock_device.name = "Test Growspace"
        mock_device.model = "Growspace"
        mock_device.identifiers = {(DOMAIN, "gs1")}

        mock_device_registry.devices.get_devices_for_config_entry_id = Mock(
            return_value=[mock_device]
        )
        mock_dr.return_value = mock_device_registry

        mock_growspace = Mock()
        mock_growspace.rows = 4
        mock_growspace.plants_per_row = 4
        mock_coordinator.growspaces = {"gs1": mock_growspace}

        flow = OptionsFlowHandler(config_entry)
        flow.hass = hass

        result = await flow.async_step_select_growspace_for_plant()

        assert result.get("type") == FlowResultType.FORM
        assert result.get("step_id") == "select_growspace_for_plant"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_for_plant_submit(
    hass: HomeAssistant, mock_coordinator, mock_store, enable_custom_integrations
):
    """Test submitting growspace selection."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    hass.data[DOMAIN] = {
        config_entry.entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    with patch(
        "custom_components.growspace_manager.config_flow.dr.async_get"
    ) as mock_dr:
        mock_device_registry = Mock()
        mock_device = Mock()
        mock_device.name = "Test Growspace"
        mock_device.model = "Growspace"
        mock_device.identifiers = {(DOMAIN, "gs1")}

        mock_device_registry.devices.get_devices_for_config_entry_id = Mock(
            return_value=[mock_device]
        )
        mock_dr.return_value = mock_device_registry

        mock_growspace = Mock()
        mock_growspace.rows = 4
        mock_growspace.plants_per_row = 4
        mock_coordinator.growspaces = {"gs1": mock_growspace}

        flow = OptionsFlowHandler(config_entry)
        flow.hass = hass

        result = await flow.async_step_select_growspace_for_plant(
            user_input={"growspace_id": "gs1"}
        )

        assert result.get("type") == FlowResultType.FORM
        assert result.get("step_id") == "add_plant"
        assert flow._selected_growspace_id == "gs1"


@pytest.mark.asyncio
async def test_options_flow_select_growspace_no_growspaces(
    hass: HomeAssistant, mock_coordinator, mock_store, enable_custom_integrations
):
    """Test when no growspaces are available."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    hass.data[DOMAIN] = {
        config_entry.entry_id: {
            "coordinator": mock_coordinator,
            "store": mock_store,
        }
    }

    with patch(
        "custom_components.growspace_manager.config_flow.dr.async_get"
    ) as mock_dr:
        mock_device_registry = Mock()
        mock_device_registry.devices.get_devices_for_config_entry_id = Mock(
            return_value=[]
        )
        mock_dr.return_value = mock_device_registry

        flow = OptionsFlowHandler(config_entry)
        flow.hass = hass

        result = await flow.async_step_select_growspace_for_plant()

        assert result.get("type") == FlowResultType.FORM
        assert "errors" in result


# ============================================================================
# Test OptionsFlowHandler - Add Plant
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_add_plant_show_form(hass: HomeAssistant, mock_coordinator):
    """Test showing add plant form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
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
    """Test successfully adding a plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    user_input = {
        "strain": "Blue Dream",
        "row": 2,
        "col": 3,
        "phenotype": "Pheno A",
        "veg_start": "2024-01-01",
        "flower_start": "2024-02-01",
    }

    result = await flow.async_step_add_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_add_plant.assert_called_once_with(
        growspace_id="gs1",
        strain="Blue Dream",
        row=2,
        col=3,
        phenotype="Pheno A",
        veg_start="2024-01-01",
        flower_start="2024-02-01",
    )


@pytest.mark.asyncio
async def test_options_flow_add_plant_error(hass: HomeAssistant, mock_coordinator):
    """Test error handling when adding plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_add_plant.side_effect = Exception("Test error")

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_growspace_id = "gs1"

    user_input = {"strain": "Test", "row": 1, "col": 1}
    result = await flow.async_step_add_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result


# ============================================================================
# Test OptionsFlowHandler - Update Plant
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_update_plant_show_form(
    hass: HomeAssistant, mock_coordinator
):
    """Test showing update plant form."""

    # Create a mock config entry
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    # Mock a plant
    mock_plant = Mock()
    mock_plant.strain = "Test Strain"
    mock_plant.growspace_id = "gs1"
    mock_plant.row = 2
    mock_plant.col = 3

    # Add the plant to the coordinator
    mock_coordinator.plants = {"p1": mock_plant}

    mock_growspace = Mock()
    mock_growspace.id = "gs1"
    mock_growspace.name = "Growspace 1"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    # Coordinator also needs async_save since the flow references it in some paths
    mock_coordinator.async_save = AsyncMock()

    # Register the coordinator
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    # Create flow
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_plant_id = "p1"

    # Call the step
    result = await flow.async_step_update_plant()

    # Validate result
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_plant"


@pytest.mark.asyncio
async def test_options_flow_update_plant_success(hass: HomeAssistant, mock_coordinator):
    """Test successfully updating a plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_plant = Mock()
    mock_plant.get = lambda k, default=None: {
        "strain": "Old Strain",
        "row": 1,
        "col": 1,
    }.get(k, default)
    mock_plant.growspace_id = "gs1"
    mock_coordinator.plants = {"p1": mock_plant}

    mock_growspace = {"rows": 4, "plants_per_row": 4}
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_plant_id = "p1"

    user_input = {"strain": "New Strain", "row": 2}
    result = await flow.async_step_update_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_update_plant.assert_called_once()


@pytest.mark.asyncio
async def test_options_flow_update_plant_not_found(
    hass: HomeAssistant, mock_coordinator
):
    """Test updating non-existent plant."""
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


@pytest.mark.asyncio
async def test_options_flow_update_plant_error(hass: HomeAssistant, mock_coordinator):
    """Test error handling when updating plant."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_plant = Mock()
    mock_plant.get = lambda k, default=None: {"strain": "Test", "row": 1, "col": 1}.get(
        k, default
    )
    mock_plant.growspace_id = "gs1"
    mock_coordinator.plants = {"p1": mock_plant}

    mock_growspace = Mock()
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_update_plant.side_effect = Exception("Test error")

    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._selected_plant_id = "p1"

    user_input = {"strain": "New Strain"}
    result = await flow.async_step_update_plant(user_input=user_input)

    assert result.get("type") == FlowResultType.FORM
    assert "errors" in result


# ============================================================================
# Test Schema Generation Methods
# ============================================================================


@pytest.mark.asyncio
async def test_get_growspace_management_schema(hass: HomeAssistant, mock_coordinator):
    """Test growspace management schema generation."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.name = "Test Growspace"
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_growspace_management_schema(mock_coordinator)

    assert "action" in schema.schema
    assert "growspace_id" in schema.schema


@pytest.mark.asyncio
async def test_get_growspace_management_schema_no_growspaces(
    hass: HomeAssistant, mock_coordinator
):
    """Test schema when no growspaces exist."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_coordinator.growspaces = {}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_growspace_management_schema(mock_coordinator)

    assert "action" in schema.schema
    assert "growspace_id" in schema.schema


@pytest.mark.asyncio
async def test_get_add_growspace_schema_with_notifications(hass: HomeAssistant):
    """Test add growspace schema with notification services."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    hass.services = Mock()
    hass.services.async_services = Mock(
        return_value={
            "notify": {
                "mobile_app_phone": {},
            }
        }
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_growspace_schema()

    assert "name" in schema.schema
    assert "rows" in schema.schema
    assert "plants_per_row" in schema.schema
    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_get_add_growspace_schema_no_notifications(hass: HomeAssistant):
    """Test add growspace schema without notification services."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_growspace_schema()

    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_get_update_growspace_schema(hass: HomeAssistant):
    """Test update growspace schema generation."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 5
    mock_growspace.plants_per_row = 6
    mock_growspace.notification_target = "mobile_app_test"

    hass.services = Mock()
    hass.services.async_services = Mock(
        return_value={"notify": {"mobile_app_test": {}}}
    )

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_update_growspace_schema(mock_growspace)

    assert "name" in schema.schema
    assert "rows" in schema.schema
    assert "plants_per_row" in schema.schema
    assert "notification_target" in schema.schema


@pytest.mark.asyncio
async def test_get_update_growspace_schema_none(hass: HomeAssistant):
    """Test update growspace schema with None growspace."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_update_growspace_schema(None)

    assert len(schema.schema) == 0


@pytest.mark.asyncio
async def test_get_main_menu_schema(hass: HomeAssistant):
    """Test main menu schema generation."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_main_menu_schema()

    assert "action" in schema.schema


@pytest.mark.asyncio
async def test_get_plant_management_schema(hass: HomeAssistant, mock_coordinator):
    """Test plant management schema generation."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_plant = Mock()
    mock_plant.strain = "Test Strain"
    mock_plant.growspace_id = "gs1"
    mock_plant.row = 1
    mock_plant.col = 1

    mock_growspace = Mock()
    mock_growspace.name = "Test Growspace"

    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_plant_management_schema(mock_coordinator)

    assert "action" in schema.schema
    assert "plant_id" in schema.schema


@pytest.mark.asyncio
async def test_get_plant_management_schema_no_plants(
    hass: HomeAssistant, mock_coordinator
):
    """Test plant management schema with no plants."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_coordinator.plants = {}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_plant_management_schema(mock_coordinator)

    assert "action" in schema.schema


@pytest.mark.asyncio
async def test_get_growspace_selection_schema_from_devices(
    hass: HomeAssistant, mock_coordinator
):
    """Test growspace selection schema from devices."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_device = Mock()
    mock_device.name = "Test Growspace"
    mock_device.identifiers = {(DOMAIN, "gs1")}

    mock_growspace = Mock()
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_growspace_selection_schema_from_devices(
        [mock_device], mock_coordinator
    )

    assert "growspace_id" in schema.schema


@pytest.mark.asyncio
async def test_get_add_plant_schema(hass: HomeAssistant, mock_coordinator):
    """Test add plant schema generation."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.rows = 5
    mock_growspace.plants_per_row = 6

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_plant_schema(mock_growspace, mock_coordinator)

    assert "strain" in schema.schema
    assert "row" in schema.schema
    assert "col" in schema.schema
    assert "phenotype" in schema.schema
    assert "veg_start" in schema.schema
    assert "flower_start" in schema.schema


@pytest.mark.asyncio
async def test_get_add_plant_schema_none(hass: HomeAssistant):
    """Test add plant schema with None growspace."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_plant_schema(None)

    assert len(schema.schema) == 0


@pytest.mark.asyncio
async def test_get_add_plant_schema_no_strains(hass: HomeAssistant):
    """Test add plant schema without existing strains."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_growspace = Mock()
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4

    mock_coordinator = Mock()
    mock_coordinator.get_strain_options = Mock(return_value=[])

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_add_plant_schema(mock_growspace, mock_coordinator)

    assert "strain" in schema.schema


@pytest.mark.asyncio
async def test_get_update_plant_schema(hass: HomeAssistant, mock_coordinator):
    """Test update plant schema generation."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.add_to_hass(hass)

    mock_plant = Mock()
    mock_plant.get = lambda k, default=None: {
        "strain": "Test Strain",
        "phenotype": "Pheno A",
        "row": 2,
        "col": 3,
    }.get(k, default)
    mock_plant.growspace_id = "gs1"

    mock_growspace = Mock()
    mock_growspace.rows = 5
    mock_growspace.plants_per_row = 6
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    schema = flow._get_update_plant_schema(mock_plant, mock_coordinator)

    assert "strain" in schema.schema
    assert "phenotype" in schema.schema
    assert "row" in schema.schema
    assert "col" in schema.schema


# ============================================================================
# Test Edge Cases and Error Conditions
# ============================================================================


@pytest.mark.asyncio
async def test_config_flow_user_step_exception(hass: HomeAssistant):
    """Test exception handling in user step."""
    flow = ConfigFlow()
    flow.hass = hass

    # This should not raise, but show form with error
    with patch.object(flow, "async_create_entry", side_effect=Exception("Test")):
        result = await flow.async_step_user(user_input={"name": "Test"})
        # The code catches the exception and shows the form again
        assert result.get("type") == FlowResultType.FORM


@pytest.mark.asyncio
async def test_config_flow_add_growspace_exception(hass: HomeAssistant):
    """Test exception handling in add_growspace."""
    flow = ConfigFlow()
    flow.hass = hass
    flow.hass.services = Mock()
    flow.hass.services.async_services = Mock(return_value={"notify": {}})

    with patch.object(flow, "async_create_entry", side_effect=Exception("Test")):
        result = await flow.async_step_add_growspace(
            user_input={"name": "Test", "rows": 4, "plants_per_row": 4}
        )
        assert result.get("type") == FlowResultType.FORM


@pytest.mark.asyncio
async def test_options_flow_coordinator_missing(hass: HomeAssistant):
    """Test handling of missing coordinator in various steps."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
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
    """Test updating with empty data (all filtered out)."""
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
    """Test selecting manage timed notifications from menu."""
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
    """Test showing manage timed notifications form."""
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
    """Test adding a timed notification."""
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
    """Test successfully adding a timed notification."""
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

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_timed_notifications"
    assert "timed_notifications" in config_entry.options
    assert len(config_entry.options["timed_notifications"]) == 1
    assert (
        config_entry.options["timed_notifications"][0]["message"] == "Test notification"
    )


@pytest.mark.asyncio
async def test_options_flow_manage_timed_notifications_edit(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test editing a timed notification."""
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
    """Test successfully editing a timed notification."""
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

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_timed_notifications"
    assert "timed_notifications" in config_entry.options
    assert len(config_entry.options["timed_notifications"]) == 1
    assert config_entry.options["timed_notifications"][0]["message"] == "New message"
    assert config_entry.options["timed_notifications"][0]["day"] == 20


@pytest.mark.asyncio
async def test_options_flow_manage_timed_notifications_delete(
    hass: HomeAssistant, mock_coordinator
):
    """Test deleting a timed notification."""
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

    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_timed_notifications"
    assert "timed_notifications" in config_entry.options
    assert len(config_entry.options["timed_notifications"]) == 0


# ============================================================================
# Test OptionsFlowHandler - Environment Configuration
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_configure_environment(
    hass: HomeAssistant, enable_custom_integrations
):
    """Test selecting configure environment from menu."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.get_sorted_growspace_options = AsyncMock(
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
    """Test showing select growspace for environment form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_coordinator = MagicMock()
    mock_coordinator.get_sorted_growspace_options = AsyncMock(
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
    """Test select growspace for env when no growspaces exist."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    mock_coordinator.get_sorted_growspace_options = AsyncMock(return_value=[])
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
    """Test submitting select growspace for environment form."""
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
    """Test showing configure environment form."""
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
    """Test submitting configure environment form."""
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
    assert "gs1" in config_entry.options
    assert config_entry.options["gs1"]["temperature_sensor"] == "sensor.temp"


@pytest.mark.asyncio
async def test_options_flow_configure_environment_advanced(
    hass: HomeAssistant, mock_coordinator
):
    """Test submitting configure environment form with advanced option."""
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
    """Test showing configure advanced bayesian form."""
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
    """Test submitting configure advanced bayesian form."""
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
    assert "gs1" in config_entry.options
    assert config_entry.options["gs1"]["prob_temp_extreme_heat"] == (0.9, 0.1)


@pytest.mark.asyncio
async def test_options_flow_configure_advanced_bayesian_invalid_tuple(
    hass: HomeAssistant, mock_coordinator, enable_custom_integrations
):
    """Test submitting configure advanced bayesian form with invalid tuple."""
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
    assert "errors" in result
    assert result["errors"]["base"] == "invalid_tuple_format"


# ============================================================================
# Test OptionsFlowHandler - Global Configuration
# ============================================================================


@pytest.mark.asyncio
async def test_options_flow_init_configure_global(
    hass: HomeAssistant, mock_coordinator
):
    """Test selecting configure global from menu."""
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
    """Test showing configure global form."""
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
    """Test submitting configure global form."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.add_to_hass(hass)
    hass.data[DOMAIN] = {config_entry.entry_id: {"coordinator": mock_coordinator}}

    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass

    user_input = {"weather_entity": "weather.home"}
    result = await flow.async_step_configure_global(user_input=user_input)

    assert result.get("type") == FlowResultType.CREATE_ENTRY
    assert "global_settings" in config_entry.options
    assert config_entry.options["global_settings"]["weather_entity"] == "weather.home"
