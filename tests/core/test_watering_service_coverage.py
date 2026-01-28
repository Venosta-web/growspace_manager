"""Targeted tests for WateringService to reach 100% coverage."""

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.exceptions import GrowspaceError
from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.services.watering_service import (
    WateringService,
)


@pytest.fixture
def mock_hass():
    return MagicMock()


@pytest.fixture
def mock_repository():
    repo = MagicMock()
    repo.plants = {}
    repo.get_growspace_plants.return_value = []
    return repo


@pytest.fixture
def mock_validator():
    return MagicMock()


@pytest.fixture
def mock_nutrient_manager():
    manager = MagicMock()
    manager.resolve_nutrient_mix.return_value = ({}, None)
    return manager


@pytest.fixture
def watering_service(
    mock_hass,
    mock_repository,
    mock_validator,
    mock_nutrient_manager,
):
    return WateringService(
        hass=mock_hass,
        repository=mock_repository,
        validator=mock_validator,
        nutrient_manager=mock_nutrient_manager,
        save_callback=AsyncMock(),
        lock=asyncio.Lock(),
        add_event_callback=MagicMock(),
        invalidate_cache_callback=MagicMock(),
    )


@pytest.mark.asyncio
async def test_water_growspace_missing_amount_raises(watering_service, mock_repository):
    """Test that async_water_growspace raises GrowspaceError if no amount is provided."""
    growspace_id = "test_gs"

    # Setup: mock repository to return some plants so we reach the check
    mock_plant = MagicMock(spec=Plant)
    mock_plant.plant_id = "p1"
    mock_repository.get_growspace_plants.return_value = [mock_plant]

    # Call with both amount and amount_per_plant as None
    with pytest.raises(
        GrowspaceError,
        match=r"Either 'amount' \(total\) or 'amount_per_plant' is required",
    ):
        await watering_service.async_water_growspace(
            growspace_id=growspace_id, amount=None, amount_per_plant=None
        )
