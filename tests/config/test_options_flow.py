"""Test the Growspace Manager options flow."""

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.growspace_manager.config_flow import OptionsFlowHandler
from custom_components.growspace_manager.const import DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType


# Helper function to set up the test environment
async def setup_test_environment(hass: HomeAssistant, coordinator):
    """Set up the test environment with a mock coordinator and config entry."""
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"}, options={})
    config_entry.runtime_data = MagicMock()
    config_entry.runtime_data = coordinator
    config_entry.add_to_hass(hass)
    return config_entry


@pytest.fixture
def mock_coordinator(hass: HomeAssistant):
    """Fixture for a basic mock coordinator."""
    coordinator = AsyncMock()
    coordinator.hass = hass
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.get_growspace_plants.return_value = []

    # Mock services
    coordinator.growspace_manager = MagicMock()
    coordinator.growspace_manager.add_growspace = AsyncMock()
    coordinator.growspace_manager.update_growspace = AsyncMock()
    coordinator.growspace_manager.get_sorted_growspace_options = Mock(return_value=[])
    coordinator.growspace_manager.get_growspace_options = Mock(return_value={})

    coordinator.plant_manager = MagicMock()
    coordinator.plant_manager.add_plant = AsyncMock()
    coordinator.plant_manager.update_plant = AsyncMock()

    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh = AsyncMock()

    # Public properties for services
    type(coordinator).growspace_service = property(lambda self: self.growspace_manager)
    type(coordinator).plant_service = property(lambda self: self.plant_manager)

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
async def test_options_flow_init_show_menu(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test showing the main options menu."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_init()

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_init_manage_growspaces(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test selecting manage growspaces from menu."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_init(user_input={"action": "manage_growspaces"})

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_init_manage_plants(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test selecting manage plants from menu."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

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
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test showing manage growspaces form."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(user_input=None)

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_growspaces"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_add(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test adding growspace action."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(user_input={"action": "add"})

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "add_growspace"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_update(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test update growspace action."""
    # Given
    mock_coordinator.growspaces = {"gs1": Mock(name="Growspace 1")}
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(
        user_input={"action": "update", "growspace_id": "gs1"}
    )

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"
    assert flow.selected_growspace_id == "gs1"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_remove(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test remove growspace action."""
    # Given
    mock_coordinator.growspaces = {"gs1": Mock(name="Test Growspace")}
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )

    # Should show confirmation form first
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "confirm_remove_growspace"

    # Confirm removal
    result = await flow.async_step_confirm_remove_growspace(
        user_input={"confirm": True}
    )

    # Then
    mock_coordinator.async_remove_growspace.assert_called_once_with("gs1")
    assert result.get("type") == FlowResultType.CREATE_ENTRY


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_remove_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling when removing growspace."""
    # Given
    mock_coordinator.async_remove_growspace.side_effect = Exception("Test error")
    mock_coordinator.growspaces = {"gs1": Mock(name="Test Growspace")}
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_growspaces(
        user_input={"action": "remove", "growspace_id": "gs1"}
    )

    # Confirm removal (this triggers the actual removal attempt)
    result = await flow.async_step_confirm_remove_growspace(
        user_input={"confirm": True}
    )

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert (
        result.get("step_id") == "confirm_remove_growspace"
    )  # Should return to confirmation form with error
    assert result.get("errors") == {"base": "remove_failed"}


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_back(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test going back to main menu in manage growspaces step."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow._get_main_menu_schema = lambda: vol.Schema({vol.Required("action"): str})
    result = await flow.async_step_manage_growspaces(user_input={"action": "back"})

    # Then
    assert result.get("type") == "form"
    assert result.get("step_id") == "init"


@pytest.mark.asyncio
async def test_options_flow_manage_growspaces_no_coordinator(
    hass: HomeAssistant,
) -> None:
    """Test error when coordinator not found."""
    # Given
    config_entry = MockConfigEntry(domain=DOMAIN, data={"name": "Test"})
    config_entry.mock_runtime_data = (
        None  # property setter might not exist on MockConfigEntry depending on version
    )
    # Since we cannot trust property setters on mocks sometimes, let's just assume accessing it via attribute works or we set it if possible.
    # However, MockConfigEntry usually doesn't have runtime_data in __init__.
    # The error was AttributeError. We can set it after creation.
    config_entry.runtime_data = None
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
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test showing add growspace form."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)
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
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test successfully adding a growspace."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    user_input = {
        "name": "New Growspace",
        "rows": 5,
        "plants_per_row": 6,
        "notification_target": "mobile_app_test",
        "length": 120,
        "width": 120,
        "height": 200,
    }
    result = await flow.async_step_add_growspace(user_input=user_input)

    # Then
    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_add_growspace.assert_awaited_once_with(
        name="New Growspace",
        rows=5,
        plants_per_row=6,
        notification_target="mobile_app_test",
        dimensions={
            "length": 120,
            "width": 120,
            "height": 200,
            "unit": "cm",
        },
    )


@pytest.mark.asyncio
async def test_options_flow_add_growspace_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling when adding growspace."""
    # Given
    mock_coordinator.async_add_growspace.side_effect = Exception("Test error")
    config_entry = await setup_test_environment(hass, mock_coordinator)
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
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test showing update growspace form."""
    # Given
    mock_growspace = Mock()
    mock_growspace.name = "Test Growspace"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry = await setup_test_environment(hass, mock_coordinator)
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    result = await flow.async_step_update_growspace()

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "update_growspace"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_success(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test successfully updating a growspace."""
    # Given
    mock_growspace = Mock()
    mock_growspace.name = "Old Name"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
    user_input = {"name": "New Name", "rows": 5}
    result = await flow.async_step_update_growspace(user_input=user_input)

    # Then
    assert result.get("type") == FlowResultType.CREATE_ENTRY
    mock_coordinator.async_update_growspace.assert_awaited_once_with(
        "gs1", name="New Name", rows=5
    )


@pytest.mark.asyncio
async def test_options_flow_update_growspace_not_found(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test updating non-existent growspace."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "nonexistent"
    result = await flow.async_step_update_growspace()

    # Then
    assert result.get("type") == FlowResultType.ABORT
    assert result.get("reason") == "growspace_not_found"


@pytest.mark.asyncio
async def test_options_flow_update_growspace_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error handling when updating growspace."""
    # Given
    mock_growspace = Mock()
    mock_growspace.name = "Test"
    mock_growspace.rows = 4
    mock_growspace.plants_per_row = 4
    mock_growspace.notification_target = None
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_update_growspace.side_effect = Exception("Test error")
    config_entry = await setup_test_environment(hass, mock_coordinator)
    hass.services = Mock()
    hass.services.async_services = Mock(return_value={"notify": {}})

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    flow.selected_growspace_id = "gs1"
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
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test showing manage plants form."""
    # Given
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_plants()

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("step_id") == "manage_plants"


@pytest.mark.asyncio
async def test_options_flow_manage_plants_add(
    hass: HomeAssistant, mock_coordinator, mock_store
) -> None:
    """Test the add plant action in the options flow."""
    # Given
    mock_coordinator.growspaces = {"test_grow": Mock(name="Test Growspace")}
    mock_coordinator.growspace_manager.get_sorted_growspace_options.return_value = [
        ("test_grow", "Test Growspace")
    ]
    mock_coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]
    config_entry = await setup_test_environment(hass, mock_coordinator)
    config_entry.runtime_data.store = mock_store

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
async def test_options_flow_manage_plants_update(
    hass: HomeAssistant, mock_coordinator, mock_store
) -> None:
    """Test update plant action."""
    # Given
    mock_coordinator.growspaces = {"test_grow": Mock(name="Test Growspace")}
    mock_coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]
    config_entry = await setup_test_environment(hass, mock_coordinator)
    config_entry.runtime_data.store = mock_store

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
async def test_options_flow_manage_plants_remove(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test remove plant action."""
    # Given
    mock_plant = Mock(id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": mock_plant}
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    await flow.async_step_manage_plants(
        user_input={"action": "remove", "plant_id": "p1"}
    )

    # Then
    mock_coordinator.async_remove_plant.assert_called()


@pytest.mark.asyncio
async def test_options_flow_manage_plants_remove_error(
    hass: HomeAssistant, mock_coordinator
) -> None:
    """Test error when removing plant."""
    # Given
    mock_coordinator.async_remove_plant.side_effect = Exception("Test error")
    mock_plant = Mock(id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": mock_plant}
    config_entry = await setup_test_environment(hass, mock_coordinator)

    # When
    flow = OptionsFlowHandler(config_entry)
    flow.hass = hass
    result = await flow.async_step_manage_plants(
        user_input={"action": "remove", "plant_id": "p1"}
    )

    # Then
    assert result.get("type") == FlowResultType.FORM
    assert result.get("errors") == {"base": "remove_failed"}
