"""Test batch add plants service."""

from datetime import date, datetime
from unittest.mock import AsyncMock, MagicMock, Mock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.services.plant import handle_add_plants
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util.dt import as_local


@pytest.fixture
def mock_growspace() -> Mock:
    """Create a mock growspace."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    return growspace


@pytest.fixture
def mock_coordinator(mock_growspace: Mock) -> Mock:
    """Create a mock coordinator."""
    coordinator = Mock()
    coordinator.plant_manager = MagicMock()
    coordinator.plant_manager.add_plant = AsyncMock()
    coordinator.growspaces = {"gs1": mock_growspace}
    coordinator.services.add_plant = coordinator.plant_manager.add_plant
    coordinator.validator = Mock()
    # default infinite space
    coordinator.validator.find_first_available_position = Mock(return_value=(1, 1))
    return coordinator


@pytest.fixture
def mock_strain_library() -> Mock:
    """Create a mock strain library."""
    return Mock()


@pytest.mark.asyncio
async def test_batch_add_plants_success(
    hass: HomeAssistant, mock_coordinator: Mock, mock_strain_library: Mock
) -> None:
    """Test successful batch add of plants."""
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plants",
        data={
            "growspace_id": "gs1",
            "strain": "Blue Dream",
            "amount": 3,
            "start_number": 1,
            "veg_start": date(2024, 1, 1),
        },
    )

    # Mock finding position for 4 calls (1 pre-check + 3 per-plant)
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (1, 1),  # Pre-check
        (1, 1),  # 1st plant
        (1, 2),  # 2nd plant
        (1, 3),  # 3rd plant
    ]

    await handle_add_plants(hass, mock_coordinator, mock_strain_library, call)

    assert mock_coordinator.services.add_plant.call_count == 3

    # Check calls
    calls = mock_coordinator.services.add_plant.call_args_list

    # 1st plant
    kwargs1 = calls[0].kwargs
    assert kwargs1["growspace_id"] == "gs1"
    assert kwargs1["strain"] == "Blue Dream"
    assert kwargs1["phenotype"] == "Blue Dream #1"
    assert kwargs1["row"] == 1
    assert kwargs1["col"] == 1
    assert kwargs1["veg_start"] == as_local(datetime(2024, 1, 1, 0, 0))

    # 2nd plant
    kwargs2 = calls[1].kwargs
    assert kwargs2["phenotype"] == "Blue Dream #2"
    assert kwargs2["row"] == 1
    assert kwargs2["col"] == 2

    # 3rd plant
    kwargs3 = calls[2].kwargs
    assert kwargs3["phenotype"] == "Blue Dream #3"
    assert kwargs3["row"] == 1
    assert kwargs3["col"] == 3


@pytest.mark.asyncio
async def test_batch_add_plants_growspace_full(
    hass: HomeAssistant, mock_coordinator: Mock, mock_strain_library: Mock
) -> None:
    """Test handling when growspace becomes full mid-batch."""
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plants",
        data={
            "growspace_id": "gs1",
            "strain": "Blue Dream",
            "amount": 3,
        },
    )

    # 1st ok (pre-check), 2nd ok (1st plant), 3rd full (2nd plant)
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (1, 1),
        (1, 1),
        (None, None),
        (None, None),
    ]

    await handle_add_plants(hass, mock_coordinator, mock_strain_library, call)

    # Should have added 1 plant and then stopped
    assert mock_coordinator.services.add_plant.call_count == 1
    assert (
        mock_coordinator.services.add_plant.call_args.kwargs["phenotype"]
        == "Blue Dream #1"
    )


@pytest.mark.asyncio
async def test_batch_add_plants_initially_full(
    hass: HomeAssistant, mock_coordinator: Mock, mock_strain_library: Mock
) -> None:
    """Test error when growspace is full from the start."""
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plants",
        data={
            "growspace_id": "gs1",
            "strain": "Blue Dream",
            "amount": 1,
        },
    )

    mock_coordinator.validator.find_first_available_position.return_value = (None, None)

    with pytest.raises(ServiceValidationError, match=".*is full.*"):
        await handle_add_plants(hass, mock_coordinator, mock_strain_library, call)

    mock_coordinator.services.add_plant.assert_not_called()


@pytest.mark.asyncio
async def test_batch_add_plants_growspace_not_found(
    hass: HomeAssistant, mock_coordinator: Mock, mock_strain_library: Mock
) -> None:
    """Test error when growspace ID is invalid."""
    mock_coordinator.growspaces = {}  # Empty

    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plants",
        data={
            "growspace_id": "missing",
            "strain": "Blue Dream",
            "amount": 1,
        },
    )

    with pytest.raises(ServiceValidationError, match=".*does not exist.*"):
        await handle_add_plants(hass, mock_coordinator, mock_strain_library, call)


@pytest.mark.asyncio
async def test_batch_add_plants_individual_error(
    hass: HomeAssistant, mock_coordinator: Mock, mock_strain_library: Mock
) -> None:
    """Test aborting when an individual plant addition fails."""
    call = ServiceCall(
        hass,
        domain=DOMAIN,
        service="add_plants",
        data={
            "growspace_id": "gs1",
            "strain": "Blue Dream",
            "amount": 3,
        },
    )

    # Pre-check + loop calls
    mock_coordinator.validator.find_first_available_position.reset_mock()
    mock_coordinator.validator.find_first_available_position.side_effect = [
        (1, 1),  # Pre-check
        (1, 1),  # 1st plant
        (1, 2),  # 2nd plant
    ]

    # 1st add raises error
    mock_coordinator.services.add_plant.side_effect = GrowspaceError("Test Error")

    await handle_add_plants(hass, mock_coordinator, mock_strain_library, call)

    # Should stop after first failure
    assert mock_coordinator.services.add_plant.call_count == 1
