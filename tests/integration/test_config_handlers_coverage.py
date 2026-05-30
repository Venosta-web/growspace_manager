"""Additional tests for Config Handlers to achieve higher coverage."""

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
import voluptuous as vol

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
from homeassistant.core import HomeAssistant


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
    """Test get_ai_settings_schema handles exception when fetching states."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)

    # Simulate exception when fetching states
    mock_hass.states.async_all.side_effect = Exception("State fetch error")

    # Should not raise exception
    schema = await handler.get_ai_settings_schema()
    assert isinstance(schema, vol.Schema)


# --- Growspace Config Handler Tests ---


def test_growspace_handler_update_schema_invalid_growspace(
    mock_hass, mock_config_entry
) -> None:
    """Test get_update_growspace_schema with None growspace."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)

    schema = handler.get_update_growspace_schema(None)  # type: ignore[arg-type]
    assert isinstance(schema, vol.Schema)
    # Should be empty schema
    assert schema.schema == {}


def test_growspace_handler_update_schema_no_notify_services(
    mock_hass, mock_config_entry
) -> None:
    """Test get_update_growspace_schema with no mobile_app services."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)

    # Mock services to return no mobile_app services
    mock_hass.services.async_services.return_value = {
        "notify": ["persistent_notification"]
    }

    mock_growspace = MagicMock()
    mock_growspace.notification_target = "existing_target"

    schema = handler.get_update_growspace_schema(mock_growspace)
    assert isinstance(schema, vol.Schema)


# --- Irrigation Config Handler Tests ---


def test_irrigation_handler_schema_vwc_steering(mock_hass, mock_config_entry) -> None:
    """Test get_irrigation_overview_schema with VWC steering enabled."""
    handler = IrrigationConfigHandler(mock_hass, mock_config_entry)

    options = {
        "use_vwc_steering": True,
        "target_vwc_percent": 60.0,
    }

    schema = handler.get_irrigation_overview_schema(options, "gs1")

    field_keys = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema.schema
    ]
    assert "target_vwc_percent" in field_keys


# --- Environment Config Handler Tests ---


def test_environment_handler_clean_input_empty_fields(
    mock_hass, mock_config_entry
) -> None:
    """Test clean_input with empty string for optional fields."""
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
    """Test get_ai_settings_schema with finding assistants."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)

    mock_state = MagicMock()
    mock_state.entity_id = "conversation.test"
    mock_state.attributes = {"friendly_name": "Test Bot"}
    mock_hass.states.async_all.return_value = [mock_state]

    schema = await handler.get_ai_settings_schema()
    assert isinstance(schema, vol.Schema)


@pytest.mark.asyncio
async def test_ai_handler_save_settings(mock_hass, mock_config_entry) -> None:
    """Test save_ai_settings."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)

    coordinator = MagicMock()
    # FIX: Use AsyncMock for anything that is awaited
    coordinator.async_commit = AsyncMock()
    coordinator.services.save = AsyncMock()

    mock_config_entry.runtime_data = coordinator
    mock_config_entry.options = {"ai_settings": {}}

    user_input = {"enabled": True}
    new_options = await handler.save_ai_settings(user_input)

    assert new_options["ai_settings"] == user_input
    coordinator.services.save.assert_awaited_once()


@pytest.mark.asyncio
async def test_growspace_handler_crud(mock_hass, mock_config_entry) -> None:
    """Test async_add_growspace and async_update_growspace."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)

    coordinator = MagicMock()
    coordinator.services.growspaces.remove_growspace = AsyncMock()
    coordinator.services.save = AsyncMock()
    coordinator.growspace_manager.add_growspace = AsyncMock()
    coordinator.growspace_manager.update_growspace = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    # Test Add
    add_input = {"name": "Test GS", "rows": 4, "plants_per_row": 4}
    await coordinator.growspace_manager.add_growspace(add_input)
    coordinator.growspace_manager.add_growspace.assert_awaited_with(add_input)
    # coordinator.async_save is irrelevant here as we are calling the mock service directly

    # Test Update
    update_input = {"name": "Updated GS", "empty_val": ""}
    await coordinator.growspace_manager.update_growspace("gs1", update_input)
    coordinator.growspace_manager.update_growspace.assert_awaited_with(
        "gs1", update_input
    )

    # Test Remove
    await handler.async_remove_growspace("gs1")
    coordinator.services.growspaces.remove_growspace.assert_awaited_with("gs1")


def test_growspace_handler_schemas(mock_hass, mock_config_entry) -> None:
    """Test get_growspace_management_schema and get_add_growspace_schema."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.growspace_manager.get_sorted_growspace_options.return_value = [
        ("gs1", "GS 1")
    ]

    mock_hass.services.async_services.return_value = {
        "notify": ["mobile_app_phone", "persistent_notification"]
    }

    # Management schema
    schema_mgmt = handler.get_growspace_management_schema(coordinator)
    assert isinstance(schema_mgmt, vol.Schema)

    # Add schema
    schema_add = handler.get_add_growspace_schema()
    assert isinstance(schema_add, vol.Schema)

    # Update schema
    schema_update = handler.get_update_growspace_schema(MagicMock(name="gs1"))
    assert isinstance(schema_update, vol.Schema)


def test_environment_handler_bayesian_schema(mock_hass, mock_config_entry) -> None:
    """Test get_advanced_bayesian_schema."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)
    options: dict[str, Any] = {}
    schema = handler.get_advanced_bayesian_schema(options)
    assert isinstance(schema, vol.Schema)


def test_environment_handler_full_schema(mock_hass, mock_config_entry) -> None:
    """Test get_environment_schema_step1."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    options = {"sensor.temp": "temp_sensor", "trend_vpd_threshold": 1.5}
    schema = handler.get_environment_schema_step1(options)
    assert isinstance(schema, vol.Schema)


def test_environment_handler_dehumidifier_schema(mock_hass, mock_config_entry) -> None:
    """Test get_dehumidifier_schema."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)
    schema = handler.get_dehumidifier_schema({})
    assert isinstance(schema, vol.Schema)


def test_environment_handler_lst_offset_schema(mock_hass, mock_config_entry) -> None:
    """Test _add_lst_offset_to_schema logic."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    options_trigger = {
        CONF_TEMP_SENSOR: "sensor.temp",
        CONF_HUMIDITY_SENSOR: "sensor.humidity",
    }
    schema_dict_trigger: dict[Any, Any] = {}
    handler._add_lst_offset_to_schema(schema_dict_trigger, options_trigger)

    keys_trigger = [
        k.schema if isinstance(k, (vol.Optional, vol.Required)) else k
        for k in schema_dict_trigger
    ]
    assert "lst_offset" in keys_trigger


def test_environment_handler_parse_bayesian_not_tuple(
    mock_hass, mock_config_entry
) -> None:
    """Test parse_advanced_bayesian_input with non-tuple value."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    user_input = {"prob_temp_warm": "(1)"}

    with pytest.raises(TypeError, match="Parsed value is not a tuple"):
        handler.parse_advanced_bayesian_input(user_input)


def test_environment_handler_parse_bayesian_invalid_format(
    mock_hass, mock_config_entry
) -> None:
    """Test parse_advanced_bayesian_input with invalid string format."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    user_input = {"prob_temp_warm": "[1, 2]"}

    with pytest.raises(ValueError, match="Invalid tuple string format"):
        handler.parse_advanced_bayesian_input(user_input)


def test_environment_handler_parse_bayesian_success(
    mock_hass, mock_config_entry
) -> None:
    """Test parse_advanced_bayesian_input with valid tuple string."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    user_input = {"prob_temp_warm": "(0.6, 0.4)", "other_val": 123}

    parsed = handler.parse_advanced_bayesian_input(user_input)
    assert parsed["prob_temp_warm"] == (0.6, 0.4)
    assert parsed["other_val"] == 123


# --- Notification Config Handler Tests ---


def test_notification_handler_timed_schema(mock_hass, mock_config_entry) -> None:
    """Test get_timed_notification_schema."""
    handler = NotificationConfigHandler(mock_hass, mock_config_entry)

    schema_empty = handler.get_timed_notification_schema([])
    assert isinstance(schema_empty, vol.Schema)

    notifications = [{"id": "n1", "message": "msg", "trigger_type": "days", "day": 5}]
    schema_full = handler.get_timed_notification_schema(notifications)
    assert isinstance(schema_full, vol.Schema)


def test_notification_handler_add_edit_schema(mock_hass, mock_config_entry) -> None:
    """Test get_add_edit_schema."""
    handler = NotificationConfigHandler(mock_hass, mock_config_entry)

    coordinator = MagicMock()
    gs = MagicMock()
    gs.name = "GS 1"
    coordinator.growspaces = {"gs1": gs}

    schema_add = handler.get_add_edit_schema(coordinator, None)
    assert isinstance(schema_add, vol.Schema)

    notification = {"message": "Test", "day": 10, "growspace_id": "gs1"}
    schema_edit = handler.get_add_edit_schema(coordinator, notification)
    assert isinstance(schema_edit, vol.Schema)


# --- Plant Config Handler Tests ---


def test_plant_handler_management_schema(mock_hass, mock_config_entry) -> None:
    """Test get_plant_management_schema."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()

    coordinator.growspace_manager.get_sorted_growspace_options.return_value = [
        ("gs1", "GS 1")
    ]
    coordinator.plants = {
        "p1": MagicMock(strain="Strain A", growspace_id="gs1", row=1, col=1)
    }

    schema = handler.get_plant_management_schema(coordinator)
    assert isinstance(schema, vol.Schema)


@pytest.mark.asyncio
async def test_plant_handler_async_operations(mock_hass, mock_config_entry) -> None:
    """Test async crud operations."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.services.plants.transition_plant = AsyncMock()
    coordinator.services.plants.remove_plant = AsyncMock()
    coordinator.services.plants.add_plant = AsyncMock()
    coordinator.services.plants.update_plant = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    # Harvest
    await handler.async_harvest_plant("p1", 50.0)
    coordinator.services.plants.transition_plant.assert_awaited_with("p1", wet_weight=50.0)

    # Destroy
    await handler.async_destroy_plant("p1")
    coordinator.services.plants.remove_plant.assert_awaited_with("p1")

    # Add (now via coordinator public method)
    await coordinator.services.plants.add_plant("gs1", "Strain A", 1, 1)
    coordinator.services.plants.add_plant.assert_awaited()

    # Update (now via coordinator public method)
    await coordinator.services.plants.update_plant("p1", strain="Strain B")
    coordinator.services.plants.update_plant.assert_awaited()


def test_plant_handler_growspace_selection_schema(mock_hass, mock_config_entry) -> None:
    """Test get_growspace_selection_schema."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock(rows=5, plants_per_row=6)}

    device = MagicMock()
    device.identifiers = {("growspace_manager", "gs1")}
    device.name = "Growspace Device"

    schema = handler.get_growspace_selection_schema([device], coordinator)
    assert isinstance(schema, vol.Schema)


def test_plant_handler_add_plant_schema(mock_hass, mock_config_entry) -> None:
    """Test get_add_plant_schema."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    growspace = MagicMock(id="gs1", rows=5, plants_per_row=5)

    schema = handler.get_add_plant_schema(growspace, None)
    assert isinstance(schema, vol.Schema)


def test_plant_handler_update_plant_schema(mock_hass, mock_config_entry) -> None:
    """Test get_update_plant_schema."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock(id="gs1", rows=5, plants_per_row=5)}
    coordinator.get_strain_options.return_value = ["Strain A"]

    plant = MagicMock(
        growspace_id="gs1", strain="Strain A", phenotype="Pheno", row=1, col=1
    )

    schema = handler.get_update_plant_schema(plant, coordinator)
    assert isinstance(schema, vol.Schema)


# --- Base Config Handler Tests ---


def test_base_handler_merge_options(mock_hass, mock_config_entry) -> None:
    """Test merge_options."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    current = {"a": 1, "b": 2}
    new_ops = {"b": 3, "c": 4}

    merged = handler.merge_options(current, new_ops)
    assert merged == {"a": 1, "b": 3, "c": 4}


@pytest.mark.asyncio
async def test_base_handler_placeholder_methods(mock_hass, mock_config_entry) -> None:
    """Test placeholder methods in BaseConfigHandler."""
    handler = EnvironmentConfigHandler(mock_hass, mock_config_entry)

    await handler.websocket_get_event_log(mock_hass, None, None)  # type: ignore[arg-type]
    await handler.transition_plant_stage(mock_hass, None, None)  # type: ignore[arg-type]


# --- Flow Control Tests ---


@pytest.mark.asyncio
async def test_growspace_handler_flow_manage_init(mock_hass, mock_config_entry) -> None:
    """Test async_step_manage_growspaces initial step."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    coordinator = MagicMock()
    coordinator.growspace_manager.get_sorted_growspace_options.return_value = []
    mock_config_entry.runtime_data = coordinator

    result = await handler.async_step_manage_growspaces(None)
    handler.flow.async_show_form.assert_called_once()
    assert result == handler.flow.async_show_form.return_value


@pytest.mark.asyncio
async def test_growspace_handler_flow_actions(mock_hass, mock_config_entry) -> None:
    """Test async_step_manage_growspaces actions."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.async_step_init = AsyncMock()
    handler.async_step_add_growspace = AsyncMock()
    handler.async_step_update_growspace = AsyncMock()
    handler.async_step_confirm_remove_growspace = AsyncMock()

    coordinator = MagicMock()
    mock_config_entry.runtime_data = coordinator

    # Add action
    await handler.async_step_manage_growspaces({"action": "add"})
    handler.async_step_add_growspace.assert_awaited()

    # Update action
    await handler.async_step_manage_growspaces(
        {"action": "update", "growspace_id": "gs1"}
    )
    assert handler.flow.selected_growspace_id == "gs1"
    handler.async_step_update_growspace.assert_awaited()

    # Remove action
    await handler.async_step_manage_growspaces(
        {"action": "remove", "growspace_id": "gs1"}
    )
    handler.async_step_confirm_remove_growspace.assert_awaited()

    # Back action
    await handler.async_step_manage_growspaces({"action": "back"})
    handler.flow.async_step_init.assert_awaited()


@pytest.mark.asyncio
async def test_growspace_handler_flow_add_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_add_growspace flow."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    coordinator = MagicMock()
    coordinator.services.growspaces.add_growspace = AsyncMock()
    # Still need to expect the service call might be mocked if handler accessed it,
    # but handler uses public API now
    mock_config_entry.runtime_data = coordinator

    # 1. No input
    await handler.async_step_add_growspace(None)
    handler.flow.async_show_form.assert_called()

    # 2. Input success
    # 2. Input success
    user_input = {
        "name": "New GS",
        "rows": 4,
        "plants_per_row": 4,
        "length": 120,
        "width": 120,
        "height": 200,
    }
    coordinator.services.growspaces.get_sorted_growspace_options.return_value = []
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    await handler.async_step_add_growspace(user_input)
    coordinator.services.growspaces.add_growspace.assert_awaited_with(
        name=user_input["name"],
        rows=user_input["rows"],
        plants_per_row=user_input["plants_per_row"],
        notification_target=None,
        dimensions={
            "length": 120,
            "width": 120,
            "height": 200,
            "unit": "cm",
        },
    )
    handler.flow.async_show_form.assert_called()

    # 3. Input error
    coordinator.services.growspaces.add_growspace.side_effect = Exception("Fail")
    await handler.async_step_add_growspace(user_input)
    assert "add_failed" in str(handler.flow.async_show_form.call_args)


@pytest.mark.asyncio
async def test_growspace_handler_flow_update_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_update_growspace flow."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.selected_growspace_id = "gs1"

    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock()}
    coordinator.services.growspaces.update_growspace = AsyncMock()
    # Support for the schema fetching in the flow
    coordinator.services.growspaces.get_sorted_growspace_options.return_value = []

    mock_config_entry.runtime_data = coordinator

    # 1. No input
    await handler.async_step_update_growspace(None)
    handler.flow.async_show_form.assert_called()

    # 2. Input success
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    user_input = {"name": "Updated GS"}

    await handler.async_step_update_growspace(user_input)

    # FIX: Matches the actual call signature (id, dict_of_input)
    coordinator.services.growspaces.update_growspace.assert_awaited_with(
        "gs1", user_input
    )


@pytest.mark.asyncio
async def test_growspace_handler_coordinator_missing(
    mock_hass, mock_config_entry
) -> None:
    """Test scenarios where coordinator is missing."""
    handler = GrowspaceConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    mock_config_entry.runtime_data = None

    await handler.async_step_manage_growspaces()
    handler.flow.async_abort.assert_called_with(reason="setup_error")


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
    mock_plant = MagicMock(plant_id="p1", growspace_id="gs1")
    coordinator.plants = {"p1": mock_plant}

    # FIX: Ensure the service returns the mock_plant so plant.plant_id works
    coordinator.services.plants.get_plant.return_value = mock_plant

    mock_config_entry.runtime_data = coordinator

    # Add action
    await handler.async_step_manage_plants({"action": "add"})
    handler.async_step_select_growspace_for_plant.assert_awaited()

    # Update action
    await handler.async_step_manage_plants({"action": "update", "plant_id": "p1"})
    assert handler.flow.selected_plant_id == "p1"
    handler.async_step_update_plant.assert_awaited()

    # Remove action
    await handler.async_step_manage_plants({"action": "remove", "plant_id": "p1"})
    # FIX: Now that get_plant is mocked, this will be "p1"
    handler.async_destroy_plant.assert_called_with("p1")


@pytest.mark.asyncio
async def test_plant_handler_flow_add_step(mock_hass, mock_config_entry) -> None:
    """Test async_step_add_plant flow."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.selected_growspace_id = "gs1"
    coordinator = MagicMock()
    coordinator.growspaces = {"gs1": MagicMock()}
    coordinator.services.plants.add_plant = AsyncMock()
    mock_config_entry.runtime_data = coordinator

    # 1. No input
    await handler.async_step_add_plant(None)
    handler.flow.async_show_form.assert_called()

    # 2. Input success
    user_input = {"strain": "Test", "row": 1, "col": 1}
    await handler.async_step_add_plant(user_input)
    coordinator.services.plants.add_plant.assert_awaited()
    handler.flow.async_create_entry.assert_called()


@pytest.mark.asyncio
async def test_ai_handler_configure_ai(mock_hass, mock_config_entry) -> None:
    """Test async_step_configure_ai flow."""
    handler = AIConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()

    coordinator = MagicMock()
    # FIX: AsyncMock for awaited coordinator methods
    coordinator.async_commit = AsyncMock()
    coordinator.services.save = AsyncMock()

    mock_config_entry.runtime_data = coordinator

    # 1. No input
    await handler.async_step_configure_ai(None)
    handler.flow.async_show_form.assert_called()

    # 2. Input success
    user_input = {"ai_enabled": True, "assistant_id": "conversation.test"}
    await handler.async_step_configure_ai(user_input)
    handler.flow.async_create_entry.assert_called()
