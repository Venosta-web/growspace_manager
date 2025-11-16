
"""Test the Growspace Manager config flow."""

import pytest
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
    coordinator.growspaces = {}
    coordinator.async_save = AsyncMock()
    coordinator.async_set_updated_data = AsyncMock()
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
# Test Edge Cases and Error Conditions
# ============================================================================


@pytest.mark.asyncio
async def test_config_flow_user_step_exception(hass: HomeAssistant):
    """Test exception handling in user step."""
    flow = ConfigFlow()
    flow.hass = hass

    with patch.object(flow, "async_create_entry", side_effect=Exception("Test error")):
        result = await flow.async_step_user(user_input={"name": "Test"})
        assert result.get("type") == FlowResultType.FORM
        assert result.get("errors") == {"base": "Error: Test error"}


@pytest.mark.asyncio
async def test_config_flow_add_growspace_exception(hass: HomeAssistant):
    """Test exception handling in add_growspace."""
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
