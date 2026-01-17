"""Additional tests for Config Handlers to achieve higher coverage."""

from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.config_handlers.ai_config_handler import (
    AIConfigHandler,
)
from custom_components.growspace_manager.config_handlers.environment_config_handler import (
    EnvironmentConfigHandler,
)
from custom_components.growspace_manager.config_handlers.growspace_config_handler import (
    GrowspaceConfigHandler,
)
from custom_components.growspace_manager.config_handlers.irrigation_config_handler import (
    IrrigationConfigHandler,
)
from custom_components.growspace_manager.config_handlers.notification_config_handler import (
    NotificationConfigHandler,
)
from custom_components.growspace_manager.config_handlers.plant_config_handler import (
    PlantConfigHandler,
)
from custom_components.growspace_manager.const import (
    CONF_HUMIDITY_SENSOR,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
)


@pytest.fixture
def mock_hass():
    """Mock Home Assistant."""
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.services = MagicMock()
    return hass


@pytest.fixture
def mock_config_entry():
    """Mock Config Entry."""
    entry = MagicMock()
    entry.options = {}
    entry.runtime_data = MagicMock()
    return entry


# --- AI Config Handler Tests ---


@pytest.mark.asyncio
async def test_ai_handler_get_schema_exception(mock_hass, mock_config_entry) -> None:
    """Test get_ai_settings_schema handles exception when fetching states (lines 48-49)."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)

    # Simulate exception when fetching states
    mock_hass.states.async_all.side_effect = Exception("State fetch error")

    # Should not raise exception
    schema = await handler.get_ai_settings_schema()
    assert isinstance(schema, vol.Schema)

    # Verify warning logged (implicitly covered by execution flow)


# --- Growspace Config Handler Tests ---


def test_growspace_handler_update_schema_invalid_growspace(
    mock_hass, mock_config_entry
) -> None:
    """Test get_update_growspace_schema with None growspace (line 128)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)

    schema = handler.get_update_growspace_schema(None)
    assert isinstance(schema, vol.Schema)
    # Should be empty schema
    assert schema.schema == {}


def test_growspace_handler_update_schema_no_notify_services(
    mock_hass, mock_config_entry
) -> None:
    """Test get_update_growspace_schema with no mobile_app services (line 179)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)

    # Mock services to return no mobile_app services
    mock_hass.services.async_services.return_value = {
        "notify": ["persistent_notification"]
    }

    mock_growspace = MagicMock()
    mock_growspace.notification_target = "existing_target"

    schema = handler.get_update_growspace_schema(mock_growspace)

    # Check if notification_target uses TextSelector (implied if not in options)
    # Voluptuous schema inspection is tricky, but we can assume if no crash it worked.
    # We can check specific coverage by execution.
    assert isinstance(schema, vol.Schema)


# --- Irrigation Config Handler Tests ---


def test_irrigation_handler_schema_vwc_steering(mock_hass, mock_config_entry) -> None:
    """Test get_irrigation_overview_schema with VWC steering enabled (line 72)."""
    handler = IrrigationConfigHandler(mock_hass, mock_config_entry)

    options = {
        "use_vwc_steering": True,
        "target_vwc_percent": 60.0,
    }

    schema = handler.get_irrigation_overview_schema(options, "gs1")

    # Verify VWC fields are present in schema
    # We simply iterate keys and check if "target_vwc_percent" is there
    # The keys in vol.Schema are Optional/Required objects.
    field_keys = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema.schema
    ]
    assert "target_vwc_percent" in field_keys


# --- Environment Config Handler Tests ---


def test_environment_handler_clean_input_empty_fields(
    mock_hass, mock_config_entry
) -> None:
    """Test clean_input with empty string for optional fields (line 72)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    user_input = {
        CONF_VPD_SENSOR: "",  # Should become None
        "other_field": "value",
    }

    cleaned = handler.clean_input(user_input)
    assert cleaned[CONF_VPD_SENSOR] is None
    assert cleaned["other_field"] == "value"


@pytest.mark.asyncio
async def test_ai_handler_get_schema_success(mock_hass, mock_config_entry) -> None:
    """Test get_ai_settings_schema with finding assistants (lines 40-47, 75)."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)

    mock_state = MagicMock()
    mock_state.entity_id = "conversation.test"
    mock_state.attributes = {"friendly_name": "Test Bot"}
    mock_hass.states.async_all.return_value = [mock_state]

    schema = await handler.get_ai_settings_schema()
    # Should have assistant_id selector with options
    # Hard to deep inspect schema, but code execution covers the lines
    assert isinstance(schema, vol.Schema)


@pytest.mark.asyncio
async def test_ai_handler_save_settings(mock_hass, mock_config_entry) -> None:
    """Test save_ai_settings (lines 137-147)."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)

    coordinator = MagicMock()
    coordinator.async_save = AsyncMock()
    mock_config_entry.runtime_data = coordinator
    mock_config_entry.options = {"ai_settings": {}}

    user_input = {"enabled": True}
    new_options = await handler.save_ai_settings(user_input)

    assert new_options["ai_settings"] == user_input
    coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_growspace_handler_crud(mock_hass, mock_config_entry) -> None:
    """Test async_add_growspace and async_update_growspace (lines 107-118, 190-195)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)

    coordinator = MagicMock()
    coordinator.async_add_growspace = AsyncMock()
    coordinator.async_update_growspace = AsyncMock()
    coordinator.async_remove_growspace = AsyncMock()
    coordinator.async_save = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    # Test Add
    add_input = {"name": "Test GS", "rows": 4, "plants_per_row": 4}
    await handler.async_add_growspace(add_input)
    coordinator.async_add_growspace.assert_awaited_with(
        name="Test GS", rows=4, plants_per_row=4, notification_target=None
    )
    coordinator.async_save.assert_awaited_once()

    # Test Update
    update_input = {"name": "Updated GS", "empty_val": ""}
    await handler.async_update_growspace("gs1", update_input)
    coordinator.async_update_growspace.assert_awaited_with("gs1", name="Updated GS")

    # Test Remove
    await handler.async_remove_growspace("gs1")
    coordinator.async_remove_growspace.assert_awaited_with("gs1")


def test_growspace_handler_schemas(mock_hass, mock_config_entry) -> None:
    """Test get_growspace_management_schema and get_add_growspace_schema (lines 30-103)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.get_sorted_growspace_options.return_value = [("gs1", "GS 1")]

    # Mock mobile_app services to hit lines 93, 143, 170
    mock_hass.services.async_services.return_value = {
        "notify": ["mobile_app_phone", "persistent_notification"]
    }

    # Management schema
    schema_mgmt = handler.get_growspace_management_schema(coordinator)
    assert isinstance(schema_mgmt, vol.Schema)

    # Add schema (with mobile apps)
    schema_add = handler.get_add_growspace_schema()
    assert isinstance(schema_add, vol.Schema)

    # Update schema
    schema_update = handler.get_update_growspace_schema(MagicMock(name="gs1"))
    assert isinstance(schema_update, vol.Schema)


def test_environment_handler_bayesian_schema(mock_hass, mock_config_entry) -> None:
    """Test get_advanced_bayesian_schema (lines 453-487)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)
    options = {}
    schema = handler.get_advanced_bayesian_schema(options)
    assert isinstance(schema, vol.Schema)


def test_environment_handler_full_schema(mock_hass, mock_config_entry) -> None:
    """Test get_environment_schema_step1 calling all sub-methods (lines 41-49 etc)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    options = {"sensor.temp": "temp_sensor", "trend_vpd_threshold": 1.5}
    schema = handler.get_environment_schema_step1(options)
    assert isinstance(schema, vol.Schema)
    # Just running it covers the calls to _add_basic_sensors, _add_lst_offset etc.


def test_environment_handler_dehumidifier_schema(mock_hass, mock_config_entry) -> None:
    """Test get_dehumidifier_schema (lines 416-449)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)
    schema = handler.get_dehumidifier_schema({})
    assert isinstance(schema, vol.Schema)


def test_environment_handler_lst_offset_schema(mock_hass, mock_config_entry) -> None:
    """Test _add_lst_offset_to_schema logic (line 146)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    # Case 1: Temp + Humidity + No VPD -> Should add lst_offset
    options_trigger = {
        CONF_TEMP_SENSOR: "sensor.temp",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
        # CONF_VPD_SENSOR missing
    }
    schema_dict_trigger = {}
    handler._add_lst_offset_to_schema(schema_dict_trigger, options_trigger)

    # Check if lst_offset key exists
    keys_trigger = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema_dict_trigger
    ]
    assert "lst_offset" in keys_trigger

    # Case 2: Missing Temp -> Should NOT add lst_offset
    options_miss = {
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
    }
    schema_dict_miss = {}
    handler._add_lst_offset_to_schema(schema_dict_miss, options_miss)
    keys_miss = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema_dict_miss
    ]
    assert "lst_offset" not in keys_miss


def test_environment_handler_parse_bayesian_not_tuple(
    mock_hass, mock_config_entry
) -> None:
    """Test parse_advanced_bayesian_input with non-tuple value (line 504)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    # Pass a valid python literal that is NOT a tuple, e.g. a list
    user_input = {"prob_temp_warm": "(1)"}

    with pytest.raises(TypeError, match="Parsed value is not a tuple"):
        handler.parse_advanced_bayesian_input(user_input)


def test_environment_handler_parse_bayesian_invalid_format(
    mock_hass, mock_config_entry
) -> None:
    """Test parse_advanced_bayesian_input with invalid string format (lines 497-499)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    user_input = {"prob_temp_warm": "[1, 2]"}

    with pytest.raises(ValueError, match="Invalid tuple string format"):
        handler.parse_advanced_bayesian_input(user_input)


def test_environment_handler_parse_bayesian_success(
    mock_hass, mock_config_entry
) -> None:
    """Test parse_advanced_bayesian_input with valid tuple string (lines 506-509)."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    user_input = {"prob_temp_warm": "(0.6, 0.4)", "other_val": 123}

    parsed = handler.parse_advanced_bayesian_input(user_input)
    assert parsed["prob_temp_warm"] == (0.6, 0.4)
    assert parsed["other_val"] == 123


# --- Notification Config Handler Tests ---


def test_notification_handler_timed_schema(mock_hass, mock_config_entry) -> None:
    """Test get_timed_notification_schema (lines 24-57)."""
    handler = NotificationConfigHandler(mock_hass, mock_config_entry)

    # Case 1: Empty notifications
    schema_empty = handler.get_timed_notification_schema([])
    assert isinstance(schema_empty, vol.Schema)
    # notification_id selector should NOT be present
    keys_empty = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema_empty.schema
    ]
    assert "notification_id" not in keys_empty

    # Case 2: With notifications
    notifications = [{"id": "n1", "message": "msg", "trigger_type": "days", "day": 5}]
    schema_full = handler.get_timed_notification_schema(notifications)
    assert isinstance(schema_full, vol.Schema)
    keys_full = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema_full.schema
    ]
    assert "notification_id" in keys_full


def test_notification_handler_add_edit_schema(mock_hass, mock_config_entry) -> None:
    """Test get_add_edit_schema (lines 59-111)."""
    handler = NotificationConfigHandler(mock_hass, mock_config_entry)

    coordinator = MagicMock()
    gs = MagicMock()
    gs.name = "GS 1"
    coordinator.growspaces = {"gs1": gs}

    # Case 1: Add (notification=None)
    schema_add = handler.get_add_edit_schema(coordinator, None)
    assert isinstance(schema_add, vol.Schema)

    # Case 2: Edit (notification provided)
    notification = {"message": "Test", "day": 10, "growspace_id": "gs1"}
    schema_edit = handler.get_add_edit_schema(coordinator, notification)
    assert isinstance(schema_edit, vol.Schema)

    # Case 3: No growspaces available
    coordinator.growspaces = {}
    schema_no_gs = handler.get_add_edit_schema(coordinator, None)

    # Check if growspace_id is omitted
    keys_no_gs = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema_no_gs.schema
    ]
    assert "growspace_id" not in keys_no_gs


# --- Plant Config Handler Tests ---


def test_plant_handler_management_schema(mock_hass, mock_config_entry) -> None:
    """Test get_plant_management_schema (lines 27-65)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()

    # Case 1: With growspaces
    coordinator.get_sorted_growspace_options.return_value = [("gs1", "GS 1")]
    # Populate plants so the schema includes plant_id
    coordinator.plants = {
        "p1": MagicMock(strain="Strain A", growspace_id="gs1", row=1, col=1)
    }

    schema = handler.get_plant_management_schema(coordinator)
    assert isinstance(schema, vol.Schema)
    keys = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema.schema
    ]
    assert "plant_id" in keys

    # Case 2: No growspaces
    coordinator.get_sorted_growspace_options.return_value = []
    coordinator.plants = {}  # Clear plants
    schema_empty = handler.get_plant_management_schema(coordinator)
    keys_empty = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema_empty.schema
    ]
    assert "plant_id" not in keys_empty


@pytest.mark.asyncio
async def test_plant_handler_async_operations(mock_hass, mock_config_entry) -> None:
    """Test async crud operations (lines 67-104)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.async_harvest_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_update_plant = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    # Harvest
    await handler.async_harvest_plant("gs1", "p1", 50.0)
    coordinator.async_harvest_plant.assert_awaited_with("gs1", "p1", 50.0)

    # Destroy
    await handler.async_destroy_plant("gs1", "p1")
    coordinator.async_remove_plant.assert_awaited_with("p1")

    # Add
    await handler.async_add_plant("gs1", "Strain A", 1, 1)
    coordinator.async_add_plant.assert_awaited_with(
        growspace_id="gs1",
        strain="Strain A",
        row=1,
        col=1,
        phenotype=None,
        veg_start=None,
        flower_start=None,
    )

    # Update
    await handler.async_update_plant("p1", strain="Strain B")
    coordinator.async_update_plant.assert_awaited_with("p1", strain="Strain B")


def test_plant_handler_growspace_selection_schema(mock_hass, mock_config_entry) -> None:
    """Test get_growspace_selection_schema (lines 106-138)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.growspaces = {}

    # Mock device with DOMAIN identifier
    device = MagicMock()
    device.identifiers = {("other_domain", "id"), ("growspace_manager", "gs1")}
    device.name = "Growspace Device"

    growspace_devices = [device]

    coordinator.growspaces = {"gs1": MagicMock(rows=5, plants_per_row=6)}

    schema = handler.get_growspace_selection_schema(growspace_devices, coordinator)
    assert isinstance(schema, vol.Schema)


def test_plant_handler_add_plant_schema(mock_hass, mock_config_entry) -> None:
    """Test get_add_plant_schema (lines 140-191)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    growspace = MagicMock(id="gs1", rows=5, plants_per_row=5)

    # Case 1: Normal growspace, no coordinator (no strains)
    schema = handler.get_add_plant_schema(growspace, None)
    assert isinstance(schema, vol.Schema)

    # Case 2: Special growspace, with coordinator strains
    growspace_special = MagicMock(id="mother", rows=5, plants_per_row=5)
    coordinator = MagicMock()
    coordinator.get_strain_options.return_value = ["Strain A"]

    schema_special = handler.get_add_plant_schema(growspace_special, coordinator)
    assert isinstance(schema_special, vol.Schema)

    # Case 3: No growspace
    schema_none = handler.get_add_plant_schema(None)
    assert isinstance(schema_none, vol.Schema)
    assert schema_none.schema == {}


def test_plant_handler_update_plant_schema(mock_hass, mock_config_entry) -> None:
    """Test get_update_plant_schema (lines 193-251)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock(id="gs1", rows=5, plants_per_row=5)}
    coordinator.get_strain_options.return_value = ["Strain A"]

    plant = MagicMock(
        growspace_id="gs1", strain="Strain A", phenotype="Pheno", row=1, col=1
    )

    schema = handler.get_update_plant_schema(plant, coordinator)
    assert isinstance(schema, vol.Schema)

    # Check if strain options logic is hit (SelectSelector)
    # Logic: if strain_options: SelectSelector else TextSelector
    # We provided strains so it should be SelectSelector.

    # Test with no strains (TextSelector path)
    coordinator.get_strain_options.return_value = []
    schema_text = handler.get_update_plant_schema(plant, coordinator)
    assert isinstance(schema_text, vol.Schema)


# --- Base Config Handler Tests ---


def test_base_handler_merge_options(mock_hass, mock_config_entry) -> None:
    """Test merge_options (lines 45-51)."""
    # Use EnvironmentConfigHandler as concrete implementation
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    current = {"a": 1, "b": 2}
    new_ops = {"b": 3, "c": 4}

    merged = handler.merge_options(current, new_ops)
    assert merged == {"a": 1, "b": 3, "c": 4}
    # Ensure original dicts are not mutated
    assert current == {"a": 1, "b": 2}
    assert new_ops == {"b": 3, "c": 4}


@pytest.mark.asyncio
async def test_base_handler_placeholder_methods(mock_hass, mock_config_entry) -> None:
    """Test placeholder methods in BaseConfigHandler to ensure coverage."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    # These just pass, so we just call them ensuring no error
    await handler.websocket_get_event_log(mock_hass, None, None)
    await handler.transition_plant_stage(mock_hass, None, None)


def test_growspace_handler_add_schema_no_notify(mock_hass, mock_config_entry) -> None:
    """Test get_add_growspace_schema with no mobile_app services (line 101)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)

    # Mock services to return NO mobile_app services
    mock_hass.services.async_services.return_value = {
        "notify": ["persistent_notification"]
    }

    schema = handler.get_add_growspace_schema()
    assert isinstance(schema, vol.Schema)

    # Verify notification_target uses TextSelector (fallback)
    # Checking specific key existence or type within schema internals is hard,
    # but execution covers the line.


@pytest.mark.asyncio
async def test_growspace_handler_flow_manage_init(mock_hass, mock_config_entry) -> None:
    """Test async_step_manage_growspaces initial step (lines 105-142)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()

    coordinator = MagicMock()
    coordinator.get_sorted_growspace_options.return_value = []
    mock_config_entry.runtime_data = coordinator

    # 1. Init (no input) -> Show menu
    result = await handler.async_step_manage_growspaces(None)
    handler.flow.async_show_form.assert_called_once()
    assert result == handler.flow.async_show_form.return_value


@pytest.mark.asyncio
async def test_growspace_handler_flow_actions(mock_hass, mock_config_entry) -> None:
    """Test async_step_manage_growspaces actions (lines 116-137)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    # Make sure async methods on flow are awaitable
    handler.flow.async_step_init = AsyncMock()

    # Need to verify method calls on handler itself
    handler.async_step_add_growspace = AsyncMock()
    handler.async_step_update_growspace = AsyncMock()
    handler.async_step_confirm_remove_growspace = AsyncMock()

    coordinator = MagicMock()
    mock_config_entry.runtime_data = coordinator

    # 2. Add action
    await handler.async_step_manage_growspaces({"action": "add"})
    handler.async_step_add_growspace.assert_awaited()

    # 3. Update action (no selection) -> Show error
    handler.flow._selected_growspace_id = None
    await handler.async_step_manage_growspaces(
        {"action": "update", "growspace_id": None}
    )
    # Should re-show form with error
    assert handler.flow.async_show_form.call_count == 1
    args, kwargs = handler.flow.async_show_form.call_args
    assert kwargs["errors"] == {"base": "select_growspace"}

    handler.flow.async_show_form.reset_mock()

    # 4. Update action (valid selection)
    await handler.async_step_manage_growspaces(
        {"action": "update", "growspace_id": "gs1"}
    )
    assert handler.flow._selected_growspace_id == "gs1"
    handler.async_step_update_growspace.assert_awaited()

    # 5. Remove action (no selection) -> Show error
    handler.flow._selected_growspace_id = None
    await handler.async_step_manage_growspaces(
        {"action": "remove", "growspace_id": None}
    )
    assert handler.flow.async_show_form.call_count == 1
    args, kwargs = handler.flow.async_show_form.call_args
    assert kwargs["errors"] == {"base": "select_growspace"}

    handler.flow.async_show_form.reset_mock()

    # 6. Remove action (valid selection)
    await handler.async_step_manage_growspaces(
        {"action": "remove", "growspace_id": "gs1"}
    )
    handler.async_step_confirm_remove_growspace.assert_awaited()

    # 7. Back action
    await handler.async_step_manage_growspaces({"action": "back"})
    handler.flow.async_step_init.assert_awaited()


@pytest.mark.asyncio
async def test_growspace_handler_flow_add_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_add_growspace (lines 144-167)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.async_add_growspace = AsyncMock()

    coordinator = MagicMock()
    mock_config_entry.runtime_data = coordinator

    # 1. No input -> Show form
    await handler.async_step_add_growspace(None)
    handler.flow.async_show_form.assert_called()
    assert handler.flow.async_show_form.call_args[1]["step_id"] == "add_growspace"

    handler.flow.async_show_form.reset_mock()

    # 2. Input -> Success
    user_input = {"name": "New GS"}
    await handler.async_step_add_growspace(user_input)
    handler.async_add_growspace.assert_awaited_with(user_input)
    handler.flow.async_create_entry.assert_called_with(title="", data={})

    # 3. Input -> Error
    handler.async_add_growspace.side_effect = Exception("Fail")
    await handler.async_step_add_growspace(user_input)
    handler.flow.async_show_form.assert_called()
    assert handler.flow.async_show_form.call_args[1]["errors"] == {"base": "add_failed"}


@pytest.mark.asyncio
async def test_growspace_handler_flow_update_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_update_growspace (lines 297-327)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow._selected_growspace_id = "gs1"
    handler.async_update_growspace = AsyncMock()

    coordinator = MagicMock()
    # Mock growspace existing
    mock_gs = MagicMock(name="My GS")
    coordinator.growspaces = {"gs1": mock_gs}
    mock_config_entry.runtime_data = coordinator

    # 1. No input -> Show form
    await handler.async_step_update_growspace(None)
    handler.flow.async_show_form.assert_called()
    assert handler.flow.async_show_form.call_args[1]["step_id"] == "update_growspace"

    handler.flow.async_show_form.reset_mock()

    # 2. Input -> Success
    user_input = {"name": "Renamed GS"}
    await handler.async_step_update_growspace(user_input)
    handler.async_update_growspace.assert_awaited_with("gs1", user_input)
    handler.flow.async_create_entry.assert_called()

    # 3. Input -> Error
    handler.async_update_growspace.side_effect = Exception("Fail")
    await handler.async_step_update_growspace(user_input)
    handler.flow.async_show_form.assert_called()
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "update_failed"
    }

    # 4. Growspace disappeared
    coordinator.growspaces = {}
    await handler.async_step_update_growspace(None)
    handler.flow.async_abort.assert_called_with(reason="growspace_not_found")


@pytest.mark.asyncio
async def test_growspace_handler_flow_remove_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_confirm_remove_growspace (lines 186-214)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow._selected_growspace_id = "gs1"
    handler.async_remove_growspace = AsyncMock()

    coordinator = MagicMock()
    mock_gs = MagicMock(name="My GS")
    coordinator.growspaces = {"gs1": mock_gs}
    mock_config_entry.runtime_data = coordinator

    # 1. No input -> Show form
    await handler.async_step_confirm_remove_growspace(None)
    handler.flow.async_show_form.assert_called()
    assert (
        handler.flow.async_show_form.call_args[1]["step_id"]
        == "confirm_remove_growspace"
    )

    handler.flow.async_show_form.reset_mock()

    # 2. Input -> Success
    await handler.async_step_confirm_remove_growspace({})
    handler.async_remove_growspace.assert_awaited_with("gs1")
    handler.flow.async_create_entry.assert_called()

    # 3. Input -> Error
    handler.async_remove_growspace.side_effect = Exception("Fail")
    await handler.async_step_confirm_remove_growspace({})
    handler.flow.async_show_form.assert_called()
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "remove_failed"
    }

    # 4. Growspace disappeared
    coordinator.growspaces = {}
    await handler.async_step_confirm_remove_growspace(None)
    handler.flow.async_abort.assert_called_with(reason="growspace_not_found")


@pytest.mark.asyncio
async def test_growspace_handler_coordinator_missing(
    mock_hass, mock_config_entry
) -> None:
    """Test scenarios where coordinator is missing (lines 111, 150, 173, etc)."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    # Make sure async methods on flow are awaitable
    handler.flow.async_step_init = AsyncMock()

    # Set runtime_data to None to trigger the checks
    mock_config_entry.runtime_data = None

    # 1. manage_growspaces
    await handler.async_step_manage_growspaces()
    handler.flow.async_abort.assert_called_with(reason="setup_error")

    handler.flow.async_abort.reset_mock()

    # 2. add_growspace (step)
    await handler.async_step_add_growspace()
    handler.flow.async_abort.assert_called_with(reason="setup_error")

    # 3. add_growspace (method)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_add_growspace({})

    handler.flow.async_abort.reset_mock()

    # 4. update_growspace (step)
    await handler.async_step_update_growspace()
    handler.flow.async_abort.assert_called_with(reason="setup_error")

    # 5. update_growspace (method)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_update_growspace("gs1", {})

    handler.flow.async_abort.reset_mock()

    # 6. remove_growspace (step)
    await handler.async_step_confirm_remove_growspace()
    handler.flow.async_abort.assert_called_with(reason="setup_error")

    # 7. remove_growspace (method)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_remove_growspace("gs1")


@pytest.mark.asyncio
async def test_plant_handler_flow_manage_init(mock_hass, mock_config_entry) -> None:
    """Test async_step_manage_plants initial step (lines 26-60)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    # Make sure async methods on flow are awaitable
    handler.flow.async_step_init = AsyncMock()

    coordinator = MagicMock()
    coordinator.plants = {}
    mock_config_entry.runtime_data = coordinator

    # 1. Init (no input) -> Show menu
    result = await handler.async_step_manage_plants(None)
    handler.flow.async_show_form.assert_called_once()
    assert result == handler.flow.async_show_form.return_value


@pytest.mark.asyncio
async def test_plant_handler_flow_actions(mock_hass, mock_config_entry) -> None:
    """Test async_step_manage_plants actions."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.async_step_init = AsyncMock()

    handler.async_step_select_growspace_for_plant = AsyncMock()
    handler.async_step_update_plant = AsyncMock()
    handler.async_destroy_plant = AsyncMock()

    coordinator = MagicMock()
    mock_plant = MagicMock(id="p1", growspace_id="gs1")
    coordinator.plants = {"p1": mock_plant}
    mock_config_entry.runtime_data = coordinator

    # 1. Add action
    await handler.async_step_manage_plants({"action": "add"})
    handler.async_step_select_growspace_for_plant.assert_awaited()

    # 2. Update action (with ID)
    await handler.async_step_manage_plants({"action": "update", "plant_id": "p1"})
    assert handler.flow._selected_plant_id == "p1"
    handler.async_step_update_plant.assert_awaited()

    # 3. Remove action (with ID) -> Success
    await handler.async_step_manage_plants({"action": "remove", "plant_id": "p1"})
    handler.async_destroy_plant.assert_awaited_with("gs1", "p1")

    # 4. Remove action (exception)
    handler.async_destroy_plant.side_effect = Exception("Fail")
    await handler.async_step_manage_plants({"action": "remove", "plant_id": "p1"})
    handler.flow.async_show_form.assert_called()
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "remove_failed"
    }

    # 5. Back action
    await handler.async_step_manage_plants({"action": "back"})
    handler.flow.async_step_init.assert_awaited()


@pytest.mark.asyncio
async def test_plant_handler_flow_select_growspace(
    mock_hass, mock_config_entry
) -> None:
    """Test async_step_select_growspace_for_plant (lines 62-93)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.async_step_add_plant = AsyncMock()

    coordinator = MagicMock()
    coordinator.get_sorted_growspace_options.return_value = [("gs1", "GS1")]
    mock_config_entry.runtime_data = coordinator

    # 1. No input -> Show form
    await handler.async_step_select_growspace_for_plant(None)
    handler.flow.async_show_form.assert_called()

    handler.flow.async_show_form.reset_mock()

    # 2. Input -> Add Plant
    await handler.async_step_select_growspace_for_plant({"growspace_id": "gs1"})
    assert handler.flow._selected_growspace_id == "gs1"
    handler.async_step_add_plant.assert_awaited()

    # 3. No growspaces available
    coordinator.get_sorted_growspace_options.return_value = []
    await handler.async_step_select_growspace_for_plant(None)
    handler.flow.async_abort.assert_called_with(reason="no_growspaces")


@pytest.mark.asyncio
async def test_plant_handler_flow_add_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_add_plant (lines 95-128)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow._selected_growspace_id = "gs1"
    handler.async_add_plant = AsyncMock()

    coordinator = MagicMock()
    mock_gs = MagicMock(id="gs1")
    coordinator.growspaces = {"gs1": mock_gs}
    mock_config_entry.runtime_data = coordinator

    # 1. No input -> Show form
    await handler.async_step_add_plant(None)
    handler.flow.async_show_form.assert_called()

    # 2. Input -> Success
    user_input = {"strain": "Test", "row": 1, "col": 1}
    await handler.async_step_add_plant(user_input)
    handler.async_add_plant.assert_awaited()
    handler.flow.async_create_entry.assert_called()

    # 3. Input -> Error
    handler.async_add_plant.side_effect = Exception("Fail")
    await handler.async_step_add_plant(user_input)
    assert handler.flow.async_show_form.call_args[1]["errors"] == {"base": "Fail"}


@pytest.mark.asyncio
async def test_plant_handler_flow_update_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_update_plant (lines 130-160)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow._selected_plant_id = "p1"
    handler.async_update_plant = AsyncMock()

    coordinator = MagicMock()
    mock_plant = MagicMock(id="p1")
    coordinator.plants = {"p1": mock_plant}
    mock_config_entry.runtime_data = coordinator

    # 1. No input -> Show form
    await handler.async_step_update_plant(None)
    handler.flow.async_show_form.assert_called()

    # 2. Input -> Success
    user_input = {"strain": "New Strain"}
    await handler.async_step_update_plant(user_input)
    handler.async_update_plant.assert_awaited()
    handler.flow.async_create_entry.assert_called()

    # 3. Input -> Error
    handler.async_update_plant.side_effect = Exception("Fail")
    await handler.async_step_update_plant(user_input)
    assert handler.flow.async_show_form.call_args[1]["errors"] == {"base": "Fail"}

    # 4. Plant disappeared
    coordinator.plants = {}
    await handler.async_step_update_plant(None)
    handler.flow.async_abort.assert_called_with(reason="plant_not_found")


@pytest.mark.asyncio
async def test_plant_handler_coordinator_missing(mock_hass, mock_config_entry) -> None:
    """Test scenarios where coordinator is missing (lines 30, 66, 99, 134, etc)."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.async_step_init = AsyncMock()

    mock_config_entry.runtime_data = None

    # 1. manage_plants
    await handler.async_step_manage_plants()
    handler.flow.async_abort.assert_called_with(reason="setup_error")
    handler.flow.async_abort.reset_mock()

    # 2. select_growspace
    await handler.async_step_select_growspace_for_plant()
    handler.flow.async_abort.assert_called_with(reason="setup_error")
    handler.flow.async_abort.reset_mock()

    # 3. add_plant (step)
    await handler.async_step_add_plant()
    handler.flow.async_abort.assert_called_with(reason="setup_error")
    handler.flow.async_abort.reset_mock()

    # 4. add_plant (method)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_add_plant("gs1", "strain", 1, 1)

    # 5. update_plant (step)
    await handler.async_step_update_plant()
    handler.flow.async_abort.assert_called_with(reason="setup_error")
    handler.flow.async_abort.reset_mock()

    # 6. update_plant (method)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_update_plant("p1")


@pytest.mark.asyncio
async def test_ai_handler_configure_ai_init(mock_hass, mock_config_entry) -> None:
    """Test async_step_configure_ai initial step (lines 135-170)."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    # Mock runtime_data to satisfy the coordinator check
    mock_config_entry.runtime_data = MagicMock()

    # 1. No input -> Show form
    await handler.async_step_configure_ai(None)
    handler.flow.async_show_form.assert_called_once()


@pytest.mark.asyncio
async def test_ai_handler_configure_ai_submit_error(
    mock_hass, mock_config_entry
) -> None:
    """Test async_step_configure_ai validation error."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    mock_config_entry.runtime_data = MagicMock()

    # AI enabled but no assistant selected
    user_input = {"ai_enabled": True, "assistant_id": None}
    await handler.async_step_configure_ai(user_input)

    handler.flow.async_show_form.assert_called_once()
    assert handler.flow.async_show_form.call_args[1]["errors"] == {
        "base": "assistant_required"
    }


@pytest.mark.asyncio
async def test_ai_handler_configure_ai_submit_success(
    mock_hass, mock_config_entry
) -> None:
    """Test async_step_configure_ai successful submission."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()

    coordinator = MagicMock()
    coordinator.async_save = AsyncMock()
    mock_config_entry.runtime_data = coordinator
    mock_config_entry.options = {"ai_settings": {}}

    user_input = {"ai_enabled": True, "assistant_id": "conversation.test"}
    await handler.async_step_configure_ai(user_input)

    handler.flow.async_create_entry.assert_called_once()
    assert (
        "AI features are now enabled"
        in handler.flow.async_create_entry.call_args[1]["description"]
    )

    # Test with AI disabled message
    handler.flow.async_create_entry.reset_mock()
    user_input = {"ai_enabled": False, "assistant_id": "conversation.test"}
    await handler.async_step_configure_ai(user_input)
    assert (
        "AI features are disabled"
        in handler.flow.async_create_entry.call_args[1]["description"]
    )


@pytest.mark.asyncio
async def test_ai_handler_configure_ai_coordinator_missing(
    mock_hass, mock_config_entry
) -> None:
    """Test async_step_configure_ai when coordinator is missing."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    mock_config_entry.runtime_data = None

    await handler.async_step_configure_ai()
    handler.flow.async_abort.assert_called_with(reason="setup_error")


@pytest.mark.asyncio
async def test_ai_handler_save_settings_coordinator_missing(
    mock_hass, mock_config_entry
) -> None:
    """Test save_ai_settings when coordinator is missing."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)
    mock_config_entry.runtime_data = None

    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.save_ai_settings({"enabled": True})
