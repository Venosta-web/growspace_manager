from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.presentation.plant_view_model import (
    PlantViewModelBuilder,
)
from homeassistant.core import HomeAssistant


@pytest.fixture
def builder(hass: HomeAssistant) -> PlantViewModelBuilder:
    """Fixture for PlantViewModelBuilder."""
    return PlantViewModelBuilder(hass)


@pytest.fixture
def mock_plant() -> Plant:
    """Fixture for a mock Plant."""
    plant = MagicMock(spec=Plant)
    plant.plant_id = "p1"
    plant.growspace_id = "gs1"
    plant.strain = "OG Kush"
    plant.phenotype = "Pheno 1"
    plant.row = 1
    plant.col = 1
    plant.last_training_technique = "LST"
    plant.last_ipm_type = "Neem"
    return plant


def test_builder_initialization(hass: HomeAssistant):
    """Test that the builder initializes correctly."""
    builder = PlantViewModelBuilder(hass)
    assert builder.hass == hass
    assert builder.entity_queries is not None


@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.get_formatted_dates"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.calculate_days_in_stage"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.format_plant_position"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.calculate_plant_stage"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.get_days_since_watering"
)
def test_build_full_payload(
    mock_get_days_since_watering,
    mock_calculate_plant_stage,
    mock_format_plant_position,
    mock_calculate_days_in_stage,
    mock_get_formatted_dates,
    builder,
    mock_plant: Plant,
):
    """Test building complete plant payload."""
    # Setup mocks
    mock_get_formatted_dates.return_value = {"started_at": "2024-01-01"}
    mock_calculate_days_in_stage.return_value = 5
    mock_format_plant_position.return_value = "R1:C1"
    mock_calculate_plant_stage.return_value = "veg"
    mock_get_days_since_watering.return_value = 2

    # Mock EntityQueries
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"

    result = builder.build(mock_plant)

    assert result["plant_id"] == "p1"
    assert result["growspace_id"] == "gs1"
    assert result["entity_id"] == "sensor.plant_1"
    assert result["strain"] == "OG Kush"
    assert result["phenotype"] == "Pheno 1"
    assert result["seedling_days"] == 5
    assert result["started_at"] == "2024-01-01"
    assert result["row"] == 1
    assert result["col"] == 1
    assert result["position"] == "R1:C1"
    assert result["stage"] == "veg"
    assert result["last_training_technique"] == "LST"
    assert result["last_ipm_type"] == "Neem"
    assert result["days_since_last_watering"] == 2

    # Verify mocks were called
    builder.entity_queries.lookup_plant_entity_id.assert_called_once_with("p1")
    mock_get_formatted_dates.assert_called_once_with(mock_plant)
    assert mock_calculate_days_in_stage.call_count == 7


@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.get_formatted_dates"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.calculate_days_in_stage"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.format_plant_position"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.calculate_plant_stage"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.get_days_since_watering"
)
def test_build_provided_entity_id(
    mock_get_days_since_watering,
    mock_calculate_plant_stage,
    mock_format_plant_position,
    mock_calculate_days_in_stage,
    mock_get_formatted_dates,
    builder,
    mock_plant,
):
    """Test building payload with provided entity_id."""
    builder.entity_queries = MagicMock()

    result = builder.build(mock_plant, entity_id="sensor.custom_plant")

    assert result["entity_id"] == "sensor.custom_plant"
    builder.entity_queries.lookup_plant_entity_id.assert_not_called()
