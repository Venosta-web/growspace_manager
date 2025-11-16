
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
        assert result.get("errors") == {"base": "Error: Test error"}
