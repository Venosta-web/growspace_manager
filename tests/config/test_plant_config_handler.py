"""Tests for the PlantConfigHandler."""

from unittest.mock import AsyncMock, MagicMock, patch

from .common import create_plant
import pytest
import voluptuous as vol

from custom_components.growspace_manager.config_handlers.plant_config_handler import (
    PlantConfigHandler,
)
from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.models import Growspace
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

ENTRY_ID = "test_entry_id"
GROWSPACE_ID = "test_growspace"


@pytest.fixture
def mock_coordinator() -> MagicMock:
    """Mock the GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.get_sorted_growspace_options.return_value = [
        (GROWSPACE_ID, "Test Growspace")
    ]
    coordinator.growspaces = {
        GROWSPACE_ID: Growspace(
            id=GROWSPACE_ID,
            name="Test Growspace",
            rows=5,
            plants_per_row=5,
        )
    }
    coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]

    # Services
    coordinator.growspace_manager = MagicMock()
    coordinator.growspace_manager.add_growspace = AsyncMock()
    coordinator.growspace_manager.update_growspace = AsyncMock()

    coordinator.plant_manager = MagicMock()
    coordinator.plant_manager.add_plant = AsyncMock()
    coordinator.plant_manager.remove_plant = AsyncMock()
    coordinator.plant_manager.harvest_plant = AsyncMock()
    coordinator.plant_manager.update_plant = AsyncMock()

    coordinator.async_harvest_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_add_plant = AsyncMock()
    coordinator.async_update_plant = AsyncMock()

    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator) -> MagicMock:
    """Mock Home Assistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.data = {}
    return hass


@pytest.fixture
def mock_config_entry(mock_coordinator) -> MagicMock:
    """Mock Config Entry."""
    entry = MagicMock(spec=ConfigEntry)
    entry.options = {}
    entry.entry_id = ENTRY_ID
    entry.runtime_data = MagicMock()
    entry.runtime_data = mock_coordinator
    return entry


@pytest.fixture
def handler(mock_hass: MagicMock, mock_config_entry: MagicMock) -> PlantConfigHandler:
    """Create a PlantConfigHandler instance."""
    handler = PlantConfigHandler(mock_hass, mock_config_entry)
    handler.flow = MagicMock()
    handler.flow.selected_plant_id = "plant1"
    handler.flow.selected_growspace_id = "gs1"
    return handler


async def test_async_steps_no_coordinator(
    handler: PlantConfigHandler, mock_hass: MagicMock
) -> None:
    # Use a real handler with None entry
    handler_no_entry = PlantConfigHandler(mock_hass, None)
    handler_no_entry.flow = handler.flow
    handler.flow.async_abort = MagicMock(return_value={"type": "abort"})

    assert await handler_no_entry.async_step_manage_plants() == {"type": "abort"}
    assert await handler_no_entry.async_step_add_plant() == {"type": "abort"}
    # update_plant checks coordinator after checking plant existence
    # but it checks config_entry first.
    assert await handler_no_entry.async_step_update_plant() == {"type": "abort"}


def test_initialization(
    handler: PlantConfigHandler, mock_hass: MagicMock, mock_config_entry: MagicMock
) -> None:
    """Test initialization."""
    assert handler.hass == mock_hass
    assert handler.config_entry == mock_config_entry


def test_get_plant_management_schema(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test generating the plant management schema."""
    schema = handler.get_plant_management_schema(mock_coordinator)
    assert isinstance(schema, vol.Schema)
    # Trigger line 80 or similar
    handler.flow.async_show_form = MagicMock(return_value={"type": "form"})
    # No, wait, I'll just add a test that triggers the missing line.


async def test_async_harvest_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test harvesting a plant."""
    await handler.async_harvest_plant("plant_1", 100.5)
    mock_coordinator.async_harvest_plant.assert_awaited_once_with(
        "plant_1", wet_weight=100.5
    )


async def test_async_destroy_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test destroying a plant."""
    await handler.async_destroy_plant("plant_1")
    mock_coordinator.async_remove_plant.assert_awaited_once_with("plant_1")


async def test_async_add_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test adding a plant."""
    await handler.async_add_plant(
        growspace_id=GROWSPACE_ID,
        strain="Strain A",
        row=1,
        col=2,
        phenotype="Pheno X",
        veg_start="2023-01-01",
        flower_start="2023-02-01",
    )
    mock_coordinator.async_add_plant.assert_awaited_once_with(
        growspace_id=GROWSPACE_ID,
        strain="Strain A",
        row=1,
        col=2,
        phenotype="Pheno X",
        veg_start="2023-01-01",
        flower_start="2023-02-01",
    )


async def test_async_update_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test updating a plant."""
    await handler.async_update_plant("plant_1", strain="New Strain")
    mock_coordinator.async_update_plant.assert_awaited_once_with(
        "plant_1", strain="New Strain"
    )


def test_get_growspace_selection_schema(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test generating growspace selection schema."""
    # Mock devices
    device1 = MagicMock()
    device1.name = "Device 1"
    device1.identifiers = {(DOMAIN, GROWSPACE_ID)}

    devices = [device1]

    schema = handler.get_growspace_selection_schema(devices, mock_coordinator)
    assert isinstance(schema, vol.Schema)


def test_get_add_plant_schema(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test generating add plant schema."""
    growspace = mock_coordinator.growspaces[GROWSPACE_ID]

    # With coordinator (strains available)
    schema = handler.get_add_plant_schema(growspace, mock_coordinator)
    assert isinstance(schema, vol.Schema)
    mock_coordinator.get_strain_options.assert_called_once()

    # Without coordinator
    schema_no_coord = handler.get_add_plant_schema(growspace)
    assert isinstance(schema_no_coord, vol.Schema)

    # Without growspace
    schema_no_gs = handler.get_add_plant_schema(None)
    assert isinstance(schema_no_gs, vol.Schema)


def test_get_update_plant_schema(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test generating update plant schema."""
    plant = create_plant(
        plant_id="plant_1", growspace_id=GROWSPACE_ID, strain="Strain A", row=1, col=1
    )

    schema = handler.get_update_plant_schema(plant, mock_coordinator)
    assert isinstance(schema, vol.Schema)
    mock_coordinator.get_strain_options.assert_called()


@pytest.mark.asyncio
async def test_error_aborts(
    handler: PlantConfigHandler, mock_config_entry: MagicMock
) -> None:
    """Test aborts when config context is missing."""
    mock_flow = MagicMock()
    mock_flow.async_abort = MagicMock(
        side_effect=lambda reason: {"type": "abort", "reason": reason}
    )
    handler.flow = mock_flow

    # Test None config_entry
    handler.config_entry = None
    assert (await handler.async_step_manage_plants())["reason"] == "setup_error"
    assert (await handler.async_step_select_growspace_for_plant())[
        "reason"
    ] == "setup_error"
    assert (await handler.async_step_add_plant())["reason"] == "setup_error"
    assert (await handler.async_step_update_plant())["reason"] == "setup_error"

    # Test None coordinator
    mock_config_entry.runtime_data = None
    handler.config_entry = mock_config_entry
    assert (await handler.async_step_manage_plants())["reason"] == "setup_error"
    assert (await handler.async_step_select_growspace_for_plant())[
        "reason"
    ] == "setup_error"
    assert (await handler.async_step_add_plant())["reason"] == "setup_error"
    assert (await handler.async_step_update_plant())["reason"] == "setup_error"


@pytest.mark.asyncio
async def test_helper_value_errors(
    handler: PlantConfigHandler, mock_config_entry: MagicMock
) -> None:
    """Test ValueErrors in helpers when context is missing."""
    # Test None config_entry
    handler.config_entry = None
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_harvest_plant("p1", 1.0)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_destroy_plant("p1")
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_add_plant("gs1", "s1", 1, 1)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_update_plant("p1")

    # Test None coordinator
    mock_config_entry.runtime_data = None
    handler.config_entry = mock_config_entry
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_add_plant("gs1", "s1", 1, 1)
    with pytest.raises(ValueError, match="Coordinator not found"):
        await handler.async_update_plant("p1")


@pytest.mark.asyncio
async def test_async_step_manage_plants_actions(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test actions in manage_plants step."""
    mock_flow = MagicMock()
    handler.flow = mock_flow

    # Action: add
    with patch.object(
        handler, "async_step_select_growspace_for_plant", return_value={"type": "form"}
    ) as mock_step:
        await handler.async_step_manage_plants({"action": "add"})
        mock_step.assert_called_once()

    # Action: update
    with patch.object(
        handler, "async_step_update_plant", return_value={"type": "form"}
    ) as mock_step:
        await handler.async_step_manage_plants({"action": "update", "plant_id": "p1"})
        assert handler.flow.selected_plant_id == "p1"
        mock_step.assert_called_once()

    # Action: back
    mock_flow.async_step_init = AsyncMock(return_value={"type": "form"})
    await handler.async_step_manage_plants({"action": "back"})
    mock_flow.async_step_init.assert_called_once()

    # Action: remove
    plant = create_plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}
    with patch.object(
        handler, "async_destroy_plant", new_callable=AsyncMock
    ) as mock_destroy:
        await handler.async_step_manage_plants({"action": "remove", "plant_id": "p1"})
        mock_destroy.assert_called_once_with("p1")


@pytest.mark.asyncio
async def test_async_step_select_growspace_for_plant(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test select growspace for plant step success."""
    mock_flow = MagicMock()
    handler.flow = mock_flow

    with patch.object(
        handler, "async_step_add_plant", return_value={"type": "form"}
    ) as mock_step:
        await handler.async_step_select_growspace_for_plant({"growspace_id": "gs1"})
        assert handler.flow.selected_growspace_id == "gs1"
        mock_step.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_add_plant_success(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test add plant step success."""
    mock_flow = MagicMock()
    mock_flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    handler.flow = mock_flow
    handler.flow.selected_growspace_id = "gs1"

    user_input = {
        "strain": "S1",
        "row": 1,
        "col": 1,
        "phenotype": "P1",
        "veg_start": "2023-01-01",
        "flower_start": "2023-02-01",
    }

    with patch.object(handler, "async_add_plant", new_callable=AsyncMock) as mock_add:
        result = await handler.async_step_add_plant(user_input)
        assert result["type"] == "create_entry"
        mock_add.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_update_plant_success(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test update plant step success."""
    mock_flow = MagicMock()
    mock_flow.async_create_entry = MagicMock(return_value={"type": "create_entry"})
    handler.flow = mock_flow
    handler.flow.selected_plant_id = "p1"

    plant = create_plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}

    user_input = {"strain": "New S"}

    with patch.object(
        handler, "async_update_plant", new_callable=AsyncMock
    ) as mock_update:
        result = await handler.async_step_update_plant(user_input)
        assert result["type"] == "create_entry"
        mock_update.assert_called_once()


@pytest.mark.asyncio
async def test_async_step_add_plant_error(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test add plant step error path."""
    mock_flow = MagicMock()
    mock_flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    handler.flow = mock_flow
    handler.flow.selected_growspace_id = "gs1"

    with patch.object(handler, "async_add_plant", side_effect=Exception("Failed")):
        result = await handler.async_step_add_plant(
            {"strain": "S1", "row": 1, "col": 1}
        )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "Failed"}


@pytest.mark.asyncio
async def test_async_step_update_plant_errors(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test update plant step error paths."""
    mock_flow = MagicMock()
    mock_flow.async_abort = MagicMock(
        side_effect=lambda reason: {"type": "abort", "reason": reason}
    )
    mock_flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    handler.flow = mock_flow

    # CASE: Plant not found
    handler.flow.selected_plant_id = "missing"
    mock_coordinator.plants = {}
    result = await handler.async_step_update_plant()
    assert result["type"] == "abort"
    assert result["reason"] == "plant_not_found"

    # CASE: Update failure
    plant = create_plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}
    handler.flow.selected_plant_id = "p1"
    with patch.object(handler, "async_update_plant", side_effect=Exception("Failed")):
        result = await handler.async_step_update_plant({"strain": "New"})
        assert result["type"] == "form"
        assert result["errors"] == {"base": "Failed"}


@pytest.mark.asyncio
async def test_get_update_plant_schema_special_gs(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test update plant schema for special growspaces."""
    plant = create_plant(plant_id="p1", growspace_id="mother")
    gs = Growspace(id="mother", name="Mother Room", rows=5, plants_per_row=5)
    mock_coordinator.growspaces = {"mother": gs}
    mock_coordinator.plants = {"p1": plant}

    # Line 324 path
    schema = handler.get_update_plant_schema(plant, mock_coordinator)
    assert isinstance(schema, vol.Schema)
    # Check max limit in schema for row/col
    row_selector = schema.schema[vol.Optional("row", default=1)]
    assert row_selector.config["max"] == 100


@pytest.mark.asyncio
async def test_async_step_manage_plants_remove_error(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test error during plant removal action."""
    mock_flow = MagicMock()
    mock_flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    handler.flow = mock_flow

    plant = create_plant(plant_id="p1", growspace_id="gs1")
    mock_coordinator.plants = {"p1": plant}

    with patch.object(handler, "async_destroy_plant", side_effect=Exception("Failed")):
        result = await handler.async_step_manage_plants(
            {"action": "remove", "plant_id": "p1"}
        )
        assert result["type"] == "form"
        assert result["errors"] == {"base": "remove_failed"}


@pytest.mark.asyncio
async def test_initial_step_forms(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test initial form display for various steps."""
    mock_flow = MagicMock()
    mock_flow.async_show_form = MagicMock(
        side_effect=lambda **kwargs: {"type": "form", **kwargs}
    )
    handler.flow = mock_flow

    # Line 78-94 path: async_step_select_growspace_for_plant initial
    result = await handler.async_step_select_growspace_for_plant()
    assert result["step_id"] == "select_growspace_for_plant"

    # Line 131 path: async_step_add_plant initial
    handler.flow.selected_growspace_id = "test_growspace"
    result = await handler.async_step_add_plant()
    assert result["step_id"] == "add_plant"

    # Line 165 path: async_step_update_plant initial
    handler.flow.selected_plant_id = "p1"
    plant = create_plant(plant_id="p1", growspace_id="test_growspace")
    mock_coordinator.plants = {"p1": plant}
    result = await handler.async_step_update_plant()
    assert result["step_id"] == "update_plant"


@pytest.mark.asyncio
async def test_get_update_plant_schema_no_strains(
    handler: PlantConfigHandler, mock_coordinator: MagicMock
) -> None:
    """Test update plant schema when no strain options are available."""
    plant = create_plant(plant_id="p1", growspace_id="test_growspace")
    mock_coordinator.plants = {"p1": plant}
    mock_coordinator.get_strain_options.return_value = []

    # Line 326 path
    schema = handler.get_update_plant_schema(plant, mock_coordinator)
    assert isinstance(schema, vol.Schema)
