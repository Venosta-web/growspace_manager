"""Tests for the Growspace Manager config flow."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.config_entries import SOURCE_USER, ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import Growspace


@pytest.fixture
def mock_setup_entry() -> MagicMock:
    """Fixture to mock async_setup_entry."""
    with patch(
        "custom_components.growspace_manager.async_setup_entry",
        return_value=True,
    ) as mock_setup:
        yield mock_setup

@pytest.fixture(autouse=True)
def mock_dependencies(hass: HomeAssistant):
    """Mock dependencies for the config flow tests."""
    hass.data[DOMAIN] = {}


async def test_config_flow_user_step(
    hass: HomeAssistant, mock_setup_entry: MagicMock
) -> None:
    """Test the user step of the config flow."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {"name": "Test Growspace"},
    )

    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["title"] == "Test Growspace"
    assert result["data"] == {"name": "Test Growspace"}

    await hass.async_block_till_done()
    assert len(mock_setup_entry.mock_calls) == 1


async def test_options_flow_add_growspace(
    hass: HomeAssistant, mock_config_entry: ConfigEntry
) -> None:
    """Test adding a growspace via the options flow."""
    mock_config_entry.add_to_hass(hass)

    mock_coordinator = MagicMock()
    mock_coordinator.async_add_growspace = AsyncMock(
        return_value=Growspace(id="new_growspace_id", name="New Growspace", rows=2, plants_per_row=3)
    )
    hass.data[DOMAIN][mock_config_entry.entry_id] = {"coordinator": mock_coordinator}

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "manage_growspaces"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manage_growspaces"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "add"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "add_growspace"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "name": "New Growspace",
            "rows": 2,
            "plants_per_row": 3,
            "notification_target": "notify.test",
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    mock_coordinator.async_add_growspace.assert_called_once_with(
        name="New Growspace",
        rows=2,
        plants_per_row=3,
        notification_target="notify.test",
    )


async def test_options_flow_remove_growspace(
    hass: HomeAssistant, mock_config_entry: ConfigEntry
) -> None:
    """Test removing a growspace via the options flow."""
    mock_config_entry.add_to_hass(hass)

    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {
        "growspace_to_remove": Growspace(id="growspace_to_remove", name="Growspace to Remove", rows=1, plants_per_row=1)
    }
    mock_coordinator.get_growspace_plants = MagicMock(return_value=[])
    mock_coordinator.async_remove_growspace = AsyncMock()
    hass.data[DOMAIN][mock_config_entry.entry_id] = {"coordinator": mock_coordinator}

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "manage_growspaces"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "remove", "growspace_id": "growspace_to_remove"}
    )

    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "manage_growspaces"

    mock_coordinator.async_remove_growspace.assert_called_once_with("growspace_to_remove")

async def test_options_flow_update_growspace(
    hass: HomeAssistant, mock_config_entry: ConfigEntry
) -> None:
    """Test updating a growspace via the options flow."""
    mock_config_entry.add_to_hass(hass)

    growspace_to_update = Growspace(id="growspace_to_update", name="Growspace to Update", rows=1, plants_per_row=1)

    mock_coordinator = MagicMock()
    mock_coordinator.growspaces = {
        "growspace_to_update": growspace_to_update
    }
    mock_coordinator.get_growspace_plants = MagicMock(return_value=[])

    mock_coordinator.async_update_growspace = AsyncMock()
    hass.data[DOMAIN][mock_config_entry.entry_id] = {"coordinator": mock_coordinator}

    result = await hass.config_entries.options.async_init(mock_config_entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "manage_growspaces"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={"action": "update", "growspace_id": "growspace_to_update"}
    )
    assert result["type"] == FlowResultType.FORM
    assert result["step_id"] == "update_growspace"

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            "name": "Updated Growspace",
            "rows": 3,
            "plants_per_row": 4,
        },
    )
    assert result["type"] == FlowResultType.CREATE_ENTRY

    mock_coordinator.async_update_growspace.assert_called_once_with(
        "growspace_to_update",
        name="Updated Growspace",
        rows=3,
        plants_per_row=4,
    )
