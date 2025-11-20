"""Test plant services."""

from datetime import date
from unittest.mock import Mock, AsyncMock, patch

import pytest


from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import event as event_helper

from custom_components.growspace_manager.services.plant import (
    handle_add_plant,
    handle_take_clone,
    handle_move_clone,
    handle_update_plant,
    handle_remove_plant,
    handle_switch_plants,
    handle_move_plant,
    handle_transition_plant_stage,
    handle_harvest_plant,
)

from custom_components.growspace_manager.const import DOMAIN


@pytest.fixture
def mock_coordinator():
    """Create a mock coordinator."""
    coordinator = Mock()
    coordinator.hass = Mock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.async_add_plant = AsyncMock(return_value="plant_1")
    coordinator.async_update_plant = AsyncMock()
    coordinator.async_remove_plant = AsyncMock()
    coordinator.async_move_plant = AsyncMock()
    coordinator.async_switch_plants = AsyncMock()
    coordinator.async_transition_plant_stage = AsyncMock()
    coordinator.async_harvest_plant = AsyncMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.get_growspace_plants = Mock(return_value=[])
    coordinator.find_first_free_position = Mock(return_value=(1, 1))
    coordinator.store = Mock()
    coordinator.store.async_load = AsyncMock()
    coordinator.async_load = AsyncMock()
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Create a mock strain library."""
    return Mock()


@pytest.fixture
def mock_growspace():
    """Create a mock growspace."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.rows = 5
    growspace.plants_per_row = 5
    return growspace


@pytest.fixture
def mock_plant():
    """Create a mock plant."""
    plant = Mock()
    plant.plant_id = "plant_1"
    plant.strain = "Test Strain"
    plant.phenotype = "Pheno A"
    plant.growspace_id = "gs1"
    plant.row = 2
    plant.col = 3
    plant.clone_start = None
    plant.source_mother = None
    return plant


# ============================================================================
# Test handle_add_plant
# ============================================================================


@pytest.mark.asyncio
async def test_add_plant_success(
    hass, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test adding plant."""
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "gs1",
            "strain": "Blue Dream",
            "row": 2,
            "col": 3,
            "phenotype": "Pheno A",
        },
    )

    events = []

    # Listen for the event
    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plant_added", listener)

    await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    mock_coordinator.async_add_plant.assert_called_once()
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()
    assert len(events) == 1


@pytest.mark.asyncio
async def test_add_plant_growspace_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test adding plant to non-existent growspace."""
    mock_coordinator.growspaces = {}  # No growspaces

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "nonexistent",
            "strain": "Test",
            "row": 1,
            "col": 1,
        },
    )

    # Patch the notification function
    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)

        # Assert notification was called
        mock_notify.assert_called_once()

        # Assert no plant was added
        mock_coordinator.async_add_plant.assert_not_called()

        # Optionally, check that async_save / async_request_refresh were not called
        mock_coordinator.async_save.assert_not_called()
        mock_coordinator.async_request_refresh.assert_not_called()


@pytest.mark.asyncio
async def test_add_plant_position_out_of_bounds(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test adding plant at out-of-bounds position."""
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "gs1",
            "strain": "Test",
            "row": 10,  # Out of bounds
            "col": 10,
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_add_plant.assert_not_called()


@pytest.mark.asyncio
async def test_add_plant_position_occupied(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_growspace,
    mock_plant,
):
    """Test adding plant at occupied position."""
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_plant.row = 2
    mock_plant.col = 3
    mock_coordinator.get_growspace_plants = Mock(return_value=[mock_plant])

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "gs1",
            "strain": "Test",
            "row": 2,
            "col": 3,
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_add_plant.assert_not_called()


@pytest.mark.asyncio
async def test_add_plant_with_dates(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test adding plant with date fields."""
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    test_date = date(2024, 1, 15)
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "gs1",
            "strain": "Test",
            "row": 1,
            "col": 1,
            "veg_start": test_date,
            "flower_start": test_date,
        },
    )

    await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_add_plant.call_args[1]
    assert call_kwargs["veg_start"] == test_date
    assert call_kwargs["flower_start"] == test_date


@pytest.mark.asyncio
async def test_add_plant_mother_growspace_auto_date(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test auto-setting mother_start date for mother growspace."""
    mock_coordinator.growspaces = {"mother": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "mother",
            "strain": "Test",
            "row": 1,
            "col": 1,
        },
    )

    await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_add_plant.call_args[1]
    assert call_kwargs["mother_start"] == date.today()


@pytest.mark.asyncio
async def test_add_plant_exception(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test exception handling in add_plant."""
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_add_plant.side_effect = Exception("Test error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "gs1",
            "strain": "Test",
            "row": 1,
            "col": 1,
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


# ============================================================================
# Test handle_take_clone
# ============================================================================


@pytest.mark.asyncio
async def test_take_clone_success(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test successfully taking clones."""
    # Setup mocks
    mock_coordinator.plants = {"mother_1": mock_plant}
    mock_coordinator.growspaces = {"clone": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "mother_1",
            "num_clones": 2,
        },
    )

    # Capture events with a listener
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_clones_taken", listener)

    # Call the service handler
    await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assertions
    assert mock_coordinator.async_add_plant.call_count == 2
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()
    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_clones_taken"


@pytest.mark.asyncio
async def test_take_clone_mother_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test taking clone from non-existent mother."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "nonexistent",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_add_plant.assert_not_called()


@pytest.mark.asyncio
async def test_take_clone_no_space(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test taking clone when no space available."""
    mock_coordinator.plants = {"mother_1": mock_plant}
    mock_coordinator.growspaces = {"clone": mock_growspace}
    mock_coordinator._find_first_available_position = Mock(return_value=(None, None))

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "mother_1",
            "num_clones": 1,
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_save.assert_not_called()


@pytest.mark.asyncio
async def test_take_clone_with_transition_date(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test taking clone with transition date."""
    mock_coordinator.plants = {"mother_1": mock_plant}
    mock_coordinator.growspaces = {"clone": mock_growspace}

    test_date = date(2024, 1, 15)
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "mother_1",
            "transition_date": test_date,
        },
    )

    await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_add_plant.call_args[1]
    assert call_kwargs["clone_start"] == test_date


@pytest.mark.asyncio
async def test_take_clone_invalid_num_clones(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test taking clone with invalid num_clones."""
    mock_coordinator.plants = {"mother_1": mock_plant}
    mock_coordinator.growspaces = {"clone": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "mother_1",
            "num_clones": "invalid",
        },
    )

    await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)

    # Should default to 1 clone
    mock_coordinator.async_add_plant.assert_called_once()


@pytest.mark.asyncio
async def test_take_clone_partial_failure(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test taking clones with partial failure."""
    mock_coordinator.plants = {"mother_1": mock_plant}
    mock_coordinator.growspaces = {"clone": mock_growspace}

    # First clone succeeds, second one raises an error
    mock_coordinator.async_add_plant = AsyncMock(
        side_effect=[AsyncMock(return_value="clone_1"), Exception("Test error")]
    )

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "mother_1",
            "num_clones": 2,
        },
    )

    # Capture events with a listener
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_clones_taken", listener)

    # Run the handler
    await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert that the coordinator still saved after the partial success
    mock_coordinator.async_save.assert_called_once()

    # Only one event should be fired (for clones_taken)
    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_clones_taken"


# ============================================================================
# Test handle_move_clone
# ============================================================================


@pytest.mark.asyncio
async def test_move_clone_success(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test successfully moving a clone."""
    # Setup
    mock_coordinator.plants = {"clone_1": mock_plant}
    mock_coordinator.growspaces = {"veg": mock_growspace}
    mock_coordinator.async_add_plant = AsyncMock(return_value="plant_2")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={
            "plant_id": "clone_1",
            "target_growspace_id": "veg",
            "transition_date": "2024-01-15",
        },
    )

    # Capture events
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plant_moved", listener)

    # Run the handler
    await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assertions
    mock_coordinator.async_add_plant.assert_called_once()
    mock_coordinator.async_remove_plant.assert_called_once_with("clone_1")
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_moved"


@pytest.mark.asyncio
async def test_move_clone_missing_params(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test move clone with missing parameters."""
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={},
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_move_clone_plant_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test moving non-existent clone."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={
            "plant_id": "nonexistent",
            "target_growspace_id": "veg",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_move_clone_no_space(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test moving clone when no space available."""
    mock_coordinator.plants = {"clone_1": mock_plant}
    mock_coordinator.growspaces = {"veg": mock_growspace}
    mock_coordinator._find_first_available_position = Mock(return_value=(None, None))

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={
            "plant_id": "clone_1",
            "target_growspace_id": "veg",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_add_plant.assert_not_called()


@pytest.mark.asyncio
async def test_move_clone_invalid_date(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test moving clone with invalid transition date."""
    mock_coordinator.plants = {"clone_1": mock_plant}
    mock_coordinator.growspaces = {"veg": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={
            "plant_id": "clone_1",
            "target_growspace_id": "veg",
            "transition_date": "invalid-date",
        },
    )

    await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)

    # Should default to today's date
    mock_coordinator.async_add_plant.assert_called_once()


@pytest.mark.asyncio
async def test_move_clone_exception_finding_position(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test exception when finding position for clone."""
    mock_coordinator.plants = {"clone_1": mock_plant}
    mock_coordinator.growspaces = {"veg": mock_growspace}
    mock_coordinator._find_first_available_position = Mock(
        side_effect=Exception("Test error")
    )

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={
            "plant_id": "clone_1",
            "target_growspace_id": "veg",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_move_clone_exception_during_move(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test exception during clone move."""
    mock_coordinator.plants = {"clone_1": mock_plant}
    mock_coordinator.growspaces = {"veg": mock_growspace}
    mock_coordinator.async_add_plant.side_effect = Exception("Test error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={
            "plant_id": "clone_1",
            "target_growspace_id": "veg",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


# ============================================================================
# Test handle_update_plant
# ============================================================================


@pytest.mark.asyncio
async def test_update_plant_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test successfully updating a plant."""
    # Arrange
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "strain": "New Strain",
            "phenotype": "New Pheno",
        },
    )

    # Capture events using async_listen
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plant_updated", listener)

    # Act
    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_update_plant.assert_called_once()
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_updated"


@pytest.mark.asyncio
async def test_update_plant_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test updating non-existent plant."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "nonexistent",
            "strain": "Test",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_update_plant.assert_not_called()


@pytest.mark.asyncio
async def test_update_plant_with_dates(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test updating plant with date fields."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    test_date = date(2024, 1, 15)
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "veg_start": test_date,
            "flower_start": test_date,
        },
    )

    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_update_plant.call_args[1]
    assert call_kwargs["veg_start"] == test_date
    assert call_kwargs["flower_start"] == test_date


@pytest.mark.asyncio
async def test_update_plant_with_date_strings(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test updating plant with date strings."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "veg_start": "2024-01-15",
            "flower_start": "2024-02-15T00:00:00Z",
        },
    )

    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_update_plant.call_args[1]
    assert call_kwargs["veg_start"] == date(2024, 1, 15)
    assert call_kwargs["flower_start"] == date(2024, 2, 15)


@pytest.mark.asyncio
async def test_update_plant_invalid_date(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test updating plant with invalid date."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "veg_start": "invalid-date",
        },
    )

    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_update_plant.call_args[1]
    assert call_kwargs["veg_start"] is None


@pytest.mark.asyncio
async def test_update_plant_none_values(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test updating plant with None values."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "strain": None,
            "phenotype": "Valid",
        },
    )

    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_update_plant.call_args[1]
    assert "strain" not in call_kwargs  # None values should be skipped
    assert call_kwargs["phenotype"] == "Valid"


@pytest.mark.asyncio
async def test_update_plant_no_update_fields(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test updating plant with no valid update fields."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
        },
    )

    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)

    mock_coordinator.async_update_plant.assert_not_called()


@pytest.mark.asyncio
async def test_update_plant_exception(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test exception handling in update_plant."""
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.async_update_plant.side_effect = Exception("Test error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "strain": "Test",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


# ============================================================================
# Test handle_remove_plant
# ============================================================================


@pytest.mark.asyncio
async def test_remove_plant_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test successfully removing a plant."""
    # Arrange
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="remove_plant",
        data={
            "plant_id": "plant_1",
        },
    )

    # Capture events
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plant_removed", listener)

    # Act
    await handle_remove_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_remove_plant.assert_called_once_with("plant_1")
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_removed"


@pytest.mark.asyncio
async def test_remove_plant_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test removing non-existent plant."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="remove_plant",
        data={
            "plant_id": "nonexistent",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_remove_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_remove_plant.assert_not_called()


@pytest.mark.asyncio
async def test_remove_plant_exception(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test exception handling in remove_plant."""
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.async_remove_plant.side_effect = Exception("Test error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="remove_plant",
        data={
            "plant_id": "plant_1",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_remove_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


# ============================================================================
# Test handle_switch_plants
# ============================================================================


@pytest.mark.asyncio
async def test_switch_plants_success(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test successfully switching two plants."""
    # Arrange
    plant1 = Mock()
    plant1.strain = "Strain 1"
    plant1.row = 1
    plant1.col = 1

    plant2 = Mock()
    plant2.strain = "Strain 2"
    plant2.row = 2
    plant2.col = 2

    mock_coordinator.plants = {"plant_1": plant1, "plant_2": plant2}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="switch_plants",
        data={
            "plant_id_1": "plant_1",
            "plant_id_2": "plant_2",
        },
    )

    # Capture events using listener
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plants_switched", listener)

    # Act
    await handle_switch_plants(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_switch_plants.assert_called_once_with("plant_1", "plant_2")
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plants_switched"


@pytest.mark.asyncio
async def test_switch_plants_first_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test switching when first plant doesn't exist."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="switch_plants",
        data={
            "plant_id_1": "nonexistent",
            "plant_id_2": "plant_2",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_switch_plants(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_switch_plants.assert_not_called()


@pytest.mark.asyncio
async def test_switch_plants_second_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test switching when second plant doesn't exist."""
    plant1 = Mock()
    mock_coordinator.plants = {"plant_1": plant1}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="switch_plants",
        data={
            "plant_id_1": "plant_1",
            "plant_id_2": "nonexistent",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_switch_plants(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_switch_plants.assert_not_called()


@pytest.mark.asyncio
async def test_switch_plants_exception(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test exception handling in switch_plants."""
    plant1 = Mock()
    plant1.strain = "Strain 1"
    plant2 = Mock()
    plant2.strain = "Strain 2"

    mock_coordinator.plants = {"plant_1": plant1, "plant_2": plant2}
    mock_coordinator.async_switch_plants.side_effect = Exception("Test error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="switch_plants",
        data={
            "plant_id_1": "plant_1",
            "plant_id_2": "plant_2",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_switch_plants(
                hass, mock_coordinator, mock_strain_library, call
            )
        mock_notify.assert_called()


@pytest.mark.asyncio
async def test_update_plant_adds_to_strain_library_if_new(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test that updating a plant with a new strain/phenotype adds it to the library."""
    # Arrange
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_strain_library._get_key.return_value = "New Strain|New Pheno"
    mock_strain_library.strains = {}  # Strain doesn't exist

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "strain": "New Strain",
            "phenotype": "New Pheno",
        },
    )

    # Act
    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_strain_library.add_strain.assert_called_once_with(
        "New Strain", "New Pheno"
    )
    mock_coordinator.async_update_plant.assert_called_once()


@pytest.mark.asyncio
async def test_move_plant_to_empty_position(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test moving plant to an empty position."""
    # Arrange
    mock_plant.row = 1
    mock_plant.col = 1
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_growspace_plants = Mock(return_value=[mock_plant])

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_plant",
        data={
            "plant_id": "plant_1",
            "new_row": 3,
            "new_col": 3,
        },
    )

    # Capture events via async_listen
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plant_moved", listener)

    # Act
    await handle_move_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_move_plant.assert_called_once_with("plant_1", 3, 3)
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_moved"


@pytest.mark.asyncio
async def test_move_plant_switch_with_occupant(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test moving plant to occupied position (switch)."""
    # Arrange
    plant1 = Mock()
    plant1.plant_id = "plant_1"
    plant1.strain = "Strain 1"
    plant1.row = 1
    plant1.col = 1
    plant1.growspace_id = "gs1"

    plant2 = Mock()
    plant2.plant_id = "plant_2"
    plant2.strain = "Strain 2"
    plant2.row = 3
    plant2.col = 3
    plant2.growspace_id = "gs1"

    mock_coordinator.plants = {"plant_1": plant1, "plant_2": plant2}
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_growspace_plants = Mock(return_value=[plant1, plant2])

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_plant",
        data={
            "plant_id": "plant_1",
            "new_row": 3,
            "new_col": 3,
        },
    )

    # Capture events using listener
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plants_switched", listener)

    # Act
    await handle_move_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_switch_plants.assert_called_once_with("plant_1", "plant_2")
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plants_switched"


@pytest.mark.asyncio
async def test_move_plant_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test moving non-existent plant."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_plant",
        data={
            "plant_id": "nonexistent",
            "new_row": 2,
            "new_col": 2,
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_move_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_move_plant_out_of_bounds(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test moving plant to out-of-bounds position."""
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_plant",
        data={
            "plant_id": "plant_1",
            "new_row": 10,
            "new_col": 10,
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_move_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_move_plant.assert_not_called()


@pytest.mark.asyncio
async def test_move_plant_exception(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test exception handling in move_plant."""
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.async_move_plant.side_effect = Exception("Test error")
    mock_coordinator.get_growspace_plants = Mock(return_value=[mock_plant])

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_plant",
        data={
            "plant_id": "plant_1",
            "new_row": 2,
            "new_col": 2,
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_move_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


# ============================================================================
# Test handle_transition_plant_stage
# ============================================================================


@pytest.mark.asyncio
async def test_transition_plant_stage_success(
    hass, mock_coordinator, mock_strain_library, mock_plant
):
    """Test successfully transitioning plant stage."""
    # Arrange
    mock_coordinator.plants = {"plant_1": mock_plant}

    # Make async methods AsyncMock
    mock_coordinator.async_transition_plant_stage = AsyncMock()
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="transition_plant_stage",
        data={
            "plant_id": "plant_1",
            "new_stage": "flower",
            "transition_date": "2024-01-15",
        },
    )

    events = []
    hass.bus.async_listen(f"{DOMAIN}_plant_transitioned", events.append)

    # Act
    await handle_transition_plant_stage(
        hass, mock_coordinator, mock_strain_library, call
    )
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_transition_plant_stage.assert_called_once_with(
        plant_id="plant_1", new_stage="flower", transition_date=date(2024, 1, 15)
    )
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_transitioned"


@pytest.mark.asyncio
async def test_transition_plant_stage_without_date(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test transitioning plant stage without date."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="transition_plant_stage",
        data={
            "plant_id": "plant_1",
            "new_stage": "flower",
        },
    )

    await handle_transition_plant_stage(
        hass, mock_coordinator, mock_strain_library, call
    )

    call_kwargs = mock_coordinator.async_transition_plant_stage.call_args[1]
    assert call_kwargs["transition_date"] is None


@pytest.mark.asyncio
async def test_transition_plant_stage_not_found(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test transitioning non-existent plant."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="transition_plant_stage",
        data={
            "plant_id": "nonexistent",
            "new_stage": "flower",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_transition_plant_stage(
            hass, mock_coordinator, mock_strain_library, call
        )
        mock_notify.assert_called_once()
        mock_coordinator.async_transition_plant_stage.assert_not_called()


@pytest.mark.asyncio
async def test_transition_plant_stage_invalid_date(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test transitioning with invalid date format."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="transition_plant_stage",
        data={
            "plant_id": "plant_1",
            "new_stage": "flower",
            "transition_date": "invalid-date",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_transition_plant_stage(
            hass, mock_coordinator, mock_strain_library, call
        )
        mock_notify.assert_called_once()
        mock_coordinator.async_transition_plant_stage.assert_not_called()


@pytest.mark.asyncio
async def test_transition_plant_stage_with_timezone(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test transitioning with timezone in date."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="transition_plant_stage",
        data={
            "plant_id": "plant_1",
            "new_stage": "flower",
            "transition_date": "2024-01-15T12:00:00Z",
        },
    )

    await handle_transition_plant_stage(
        hass, mock_coordinator, mock_strain_library, call
    )

    call_kwargs = mock_coordinator.async_transition_plant_stage.call_args[1]
    assert call_kwargs["transition_date"] == date(2024, 1, 15)


@pytest.mark.asyncio
async def test_transition_plant_stage_exception(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test exception handling in transition_plant_stage."""
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.async_transition_plant_stage.side_effect = Exception("Test error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="transition_plant_stage",
        data={
            "plant_id": "plant_1",
            "new_stage": "flower",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_transition_plant_stage(
                hass, mock_coordinator, mock_strain_library, call
            )
        mock_notify.assert_called()


# ============================================================================
# Test handle_harvest_plant
# ============================================================================


@pytest.mark.asyncio
async def test_harvest_plant_success(
    hass, mock_coordinator, mock_strain_library, mock_plant
):
    """Test successfully harvesting a plant."""

    mock_coordinator.plants = {"plant_1": mock_plant}

    # Make async methods AsyncMock
    mock_coordinator.async_harvest_plant = AsyncMock()
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",
            "target_growspace_id": "dry",
            "transition_date": "2024-01-15",
        },
    )

    events = []
    hass.bus.async_listen(f"{DOMAIN}_plant_harvested", events.append)

    await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_harvest_plant.assert_called_once_with(
        plant_id="plant_1", target_growspace_id="dry", transition_date=date(2024, 1, 15)
    )
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()
    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_harvested"


@pytest.mark.asyncio
async def test_harvest_plant_missing_plant_id(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test harvest with missing plant_id."""
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "target_growspace_id": "dry",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_harvest_plant_entity_id_resolution(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test harvest with entity ID resolution."""

    # Arrange
    mock_coordinator.plants = {"plant_1": mock_plant}

    # Set up a fake entity with a plant_id attribute
    hass.states.async_set("plant.my_plant", "on", attributes={"plant_id": "plant_1"})

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",  # pass plant_id directly
            "target_growspace_id": "dry",
        },
    )

    # Capture events
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plant_harvested", listener)

    # Act
    await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_harvest_plant.assert_called_once_with(
        plant_id="plant_1", target_growspace_id="dry", transition_date=None
    )
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_harvested"


@pytest.mark.asyncio
async def test_harvest_plant_entity_id_no_attribute(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test harvest with entity ID but no plant_id attribute."""
    mock_coordinator.plants = {}

    # Mock entity state without plant_id attribute
    mock_state = Mock()
    mock_state.attributes = {}
    hass.states = Mock()
    hass.states.get = Mock(return_value=mock_state)

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant.my_plant",
            "target_growspace_id": "dry",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


@pytest.mark.asyncio
async def test_harvest_plant_not_found_reload_attempt(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test harvest when plant not found, triggers reload."""
    # Initially empty, then populated after reload
    mock_coordinator.plants = {}

    async def mock_load():
        mock_coordinator.plants = {"plant_1": mock_plant}

    mock_coordinator.async_load = mock_load

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",
            "target_growspace_id": "dry",
        },
    )

    await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)

    mock_coordinator.async_harvest_plant.assert_called_once()


@pytest.mark.asyncio
async def test_harvest_plant_not_found_after_reload(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test harvest when plant still not found after reload."""
    mock_coordinator.plants = {}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "nonexistent",
            "target_growspace_id": "dry",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()
        mock_coordinator.async_harvest_plant.assert_not_called()


@pytest.mark.asyncio
async def test_harvest_plant_reload_error(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test harvest when reload fails."""
    mock_coordinator.plants = {}
    mock_coordinator.store.async_load.side_effect = Exception("Load error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",
            "target_growspace_id": "dry",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


@pytest.mark.asyncio
async def test_harvest_plant_invalid_date(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test harvest with invalid transition date."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",
            "target_growspace_id": "dry",
            "transition_date": "invalid-date",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called_once()
        mock_coordinator.async_harvest_plant.assert_not_called()


@pytest.mark.asyncio
async def test_harvest_plant_with_timezone(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test harvest with timezone in date."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",
            "target_growspace_id": "dry",
            "transition_date": "2024-01-15T12:00:00Z",
        },
    )

    await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_harvest_plant.call_args[1]
    assert call_kwargs["transition_date"] == date(2024, 1, 15)


@pytest.mark.asyncio
async def test_harvest_plant_without_date(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test harvest without transition date."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",
            "target_growspace_id": "dry",
        },
    )

    await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_harvest_plant.call_args[1]
    assert call_kwargs["transition_date"] is None


@pytest.mark.asyncio
async def test_harvest_plant_exception(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test exception handling in harvest_plant."""
    mock_coordinator.plants = {"plant_1": mock_plant}
    mock_coordinator.async_harvest_plant.side_effect = Exception("Test error")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant_1",
            "target_growspace_id": "dry",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        with pytest.raises(Exception):
            await handle_harvest_plant(
                hass, mock_coordinator, mock_strain_library, call
            )
        mock_notify.assert_called()


@pytest.mark.asyncio
async def test_harvest_plant_entity_id_resolution_error(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test harvest when entity ID resolution fails."""
    mock_coordinator.plants = {}

    # Mock entity state but cause exception during resolution
    hass.states = Mock()
    hass.states.get = Mock(side_effect=Exception("State error"))

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant.my_plant",
            "target_growspace_id": "dry",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
        # Should still attempt to find plant and eventually fail
        mock_notify.assert_called()


@pytest.mark.asyncio
async def test_harvest_plant_no_entity_registry(
    hass: HomeAssistant, mock_coordinator, mock_strain_library
):
    """Test harvest when entity registry is not available."""
    mock_coordinator.plants = {}
    hass.data = {}
    hass.states = Mock()
    hass.states.get = Mock(return_value=None)

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="harvest_plant",
        data={
            "plant_id": "plant.my_plant",
            "target_growspace_id": "dry",
        },
    )

    with patch(
        "custom_components.growspace_manager.services.plant.create_notification"
    ) as mock_notify:
        await handle_harvest_plant(hass, mock_coordinator, mock_strain_library, call)
        mock_notify.assert_called()


# ============================================================================
# Test Edge Cases and Additional Coverage
# ============================================================================


@pytest.mark.asyncio
async def test_add_plant_with_empty_date_strings(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test adding plant with empty date strings."""
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "gs1",
            "strain": "Test",
            "row": 1,
            "col": 1,
            "veg_start": "",
            "flower_start": None,
        },
    )

    await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_add_plant.call_args[1]
    assert call_kwargs["veg_start"] is None
    assert call_kwargs["flower_start"] is None


@pytest.mark.asyncio
async def test_update_plant_with_empty_string_dates(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test updating plant with empty string dates."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "veg_start": "",
            "flower_start": "None",
        },
    )

    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_update_plant.call_args[1]
    assert call_kwargs["veg_start"] is None
    assert call_kwargs["flower_start"] is None


@pytest.mark.asyncio
async def test_update_plant_moves_to_free_space_if_occupied(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test that updating a plant to an occupied position moves it to a free space."""
    # Arrange
    plant_2 = Mock()
    plant_2.plant_id = "plant_2"
    plant_2.row = 2
    plant_2.col = 2
    plant_2.growspace_id = "gs1"

    mock_coordinator.plants = {"plant_1": mock_plant, "plant_2": plant_2}
    mock_coordinator.get_growspace_plants.return_value = [mock_plant, plant_2]
    mock_coordinator.find_first_free_position.return_value = (3, 3)

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={"plant_id": "plant_1", "row": 2, "col": 2},  # Try to move to plant_2's spot
    )

    # Act
    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_update_plant.assert_called_once()
    update_kwargs = mock_coordinator.async_update_plant.call_args[1]
    assert update_kwargs.get("row") == 3
    assert update_kwargs.get("col") == 3


@pytest.mark.asyncio
async def test_move_plant_switch_with_occupant(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test moving plant to occupied position (switch)."""
    # Arrange
    plant1 = Mock()
    plant1.plant_id = "plant_1"
    plant1.strain = "Strain 1"
    plant1.row = 1
    plant1.col = 1
    plant1.growspace_id = "gs1"

    plant2 = Mock()
    plant2.plant_id = "plant_2"
    plant2.strain = "Strain 2"
    plant2.row = 3
    plant2.col = 3
    plant2.growspace_id = "gs1"

    mock_coordinator.plants = {"plant_1": plant1, "plant_2": plant2}
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    mock_coordinator.get_growspace_plants = Mock(return_value=[plant1, plant2])

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_plant",
        data={
            "plant_id": "plant_1",
            "new_row": 3,
            "new_col": 3,
        },
    )

    # Capture events using listener
    events = []

    def listener(event):
        events.append(event)

    hass.bus.async_listen(f"{DOMAIN}_plants_switched", listener)

    # Act
    await handle_move_plant(hass, mock_coordinator, mock_strain_library, call)
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_switch_plants.assert_called_once_with("plant_1", "plant_2")
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plants_switched"


@pytest.mark.asyncio
async def test_transition_plant_stage_success(
    hass, mock_coordinator, mock_strain_library, mock_plant
):
    """Test successfully transitioning plant stage."""
    # Arrange
    mock_coordinator.plants = {"plant_1": mock_plant}

    # Make async methods AsyncMock
    mock_coordinator.async_transition_plant_stage = AsyncMock()
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.async_request_refresh = AsyncMock()

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="transition_plant_stage",
        data={
            "plant_id": "plant_1",
            "new_stage": "flower",
            "transition_date": "2024-01-15",
        },
    )

    events = []
    hass.bus.async_listen(f"{DOMAIN}_plant_transitioned", events.append)

    # Act
    await handle_transition_plant_stage(
        hass, mock_coordinator, mock_strain_library, call
    )
    await hass.async_block_till_done()

    # Assert
    mock_coordinator.async_transition_plant_stage.assert_called_once_with(
        plant_id="plant_1", new_stage="flower", transition_date=date(2024, 1, 15)
    )
    mock_coordinator.async_save.assert_called_once()
    mock_coordinator.async_request_refresh.assert_called_once()

    assert len(events) == 1
    assert events[0].event_type == f"{DOMAIN}_plant_transitioned"


@pytest.mark.asyncio
async def test_take_clone_negative_clones(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test taking negative number of clones (should default to 1)."""
    mock_coordinator.plants = {"mother_1": mock_plant}
    mock_coordinator.growspaces = {"clone": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "mother_1",
            "num_clones": -5,
        },
    )

    await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)

    # Should default to 1
    mock_coordinator.async_add_plant.assert_called_once()


@pytest.mark.asyncio
async def test_move_clone_default_transition_date(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test move clone with no transition date (should use today)."""
    mock_coordinator.plants = {"clone_1": mock_plant}
    mock_coordinator.growspaces = {"veg": mock_growspace}
    mock_coordinator.async_add_plant = AsyncMock(return_value="plant_2")

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="move_clone",
        data={
            "plant_id": "clone_1",
            "target_growspace_id": "veg",
        },
    )

    await handle_move_clone(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_add_plant.call_args[1]
    assert call_kwargs["veg_start"] == date.today()


@pytest.mark.asyncio
async def test_add_plant_with_empty_date_strings(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_growspace
):
    """Test adding plant with empty date strings."""
    mock_coordinator.growspaces = {"gs1": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plant",
        data={
            "growspace_id": "gs1",
            "strain": "Test",
            "row": 1,
            "col": 1,
            "veg_start": "",
            "flower_start": None,
        },
    )

    await handle_add_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_add_plant.call_args[1]
    assert call_kwargs["veg_start"] is None
    assert call_kwargs["flower_start"] is None


@pytest.mark.asyncio
async def test_update_plant_with_empty_string_dates(
    hass: HomeAssistant, mock_coordinator, mock_strain_library, mock_plant
):
    """Test updating plant with empty string dates."""
    mock_coordinator.plants = {"plant_1": mock_plant}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="update_plant",
        data={
            "plant_id": "plant_1",
            "veg_start": "",
            "flower_start": "None",
        },
    )

    await handle_update_plant(hass, mock_coordinator, mock_strain_library, call)

    call_kwargs = mock_coordinator.async_update_plant.call_args[1]
    assert call_kwargs["veg_start"] is None
    assert call_kwargs["flower_start"] is None


@pytest.mark.asyncio
async def test_take_clone_zero_clones(
    hass: HomeAssistant,
    mock_coordinator,
    mock_strain_library,
    mock_plant,
    mock_growspace,
):
    """Test taking zero clones (should default to 1)."""
    mock_coordinator.plants = {"mother_1": mock_plant}
    mock_coordinator.growspaces = {"clone": mock_growspace}

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="take_clone",
        data={
            "mother_plant_id": "mother_1",
            "num_clones": 0,
        },
    )

    await handle_take_clone(hass, mock_coordinator, mock_strain_library, call)

    # Should default to 1
    mock_coordinator.async_add_plant.assert_called_once()
