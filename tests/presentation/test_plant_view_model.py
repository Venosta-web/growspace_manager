from unittest.mock import MagicMock, patch

import pytest

from custom_components.growspace_manager.const import PLANT_STAGES
from custom_components.growspace_manager.models import (
    DryingData,
    HarvestMetrics,
    MoistureEntry,
    Plant,
    WeightEntry,
)
from custom_components.growspace_manager.models.plant import PhenotypeScore
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
    plant.harvest_metrics = HarvestMetrics()
    plant.drying_data = DryingData()
    plant.phenotype_score = PhenotypeScore()
    plant.phi_clearance_date = None
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
    "custom_components.growspace_manager.presentation.plant_view_model.resolve_current_stage"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.get_days_since_watering"
)
def test_build_full_payload(
    mock_get_days_since_watering,
    mock_resolve_current_stage,
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
    mock_resolve_current_stage.return_value = "veg"
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
    assert mock_calculate_days_in_stage.call_count == len(PLANT_STAGES)


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
    "custom_components.growspace_manager.presentation.plant_view_model.resolve_current_stage"
)
@patch(
    "custom_components.growspace_manager.presentation.plant_view_model.get_days_since_watering"
)
def test_build_provided_entity_id(
    mock_get_days_since_watering,
    mock_resolve_current_stage,
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


def test_build_includes_drying_data(builder, mock_plant: Plant):
    """Drying-stage fields must be in the frontend payload.

    The plant overview dialog reads ``visual_tag`` and the drying stats from
    this view model (not the sensor entity), so a saved visual tag only
    round-trips back to the card if these top-level fields are present.
    """
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"
    mock_plant.harvest_metrics = HarvestMetrics(wet_weight=100.0)
    mock_plant.drying_data = DryingData(
        weight_log=[
            WeightEntry(date="2024-01-01", weight_grams=100.0),
            WeightEntry(date="2024-01-02", weight_grams=80.0),
        ],
        moisture_log=[MoistureEntry(date="2024-01-02", moisture_percent=11.0)],
        visual_tag="Red Velcro",
    )

    result = builder.build(mock_plant)

    assert result["visual_tag"] == "Red Velcro"
    assert result["drying_weight"] == 80.0
    assert result["weight_lost_pct"] == 20.0
    assert result["days_to_target"] is not None
    assert result["drying_moisture"] == 11.0
    assert result["drying_ready_for_cure"] is True


def test_build_drying_data_empty_logs(builder, mock_plant: Plant):
    """With no drying observations the fields default to None/False, not errors."""
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"
    mock_plant.harvest_metrics = HarvestMetrics()
    mock_plant.drying_data = DryingData()

    result = builder.build(mock_plant)

    assert result["visual_tag"] is None
    assert result["drying_weight"] is None
    assert result["weight_lost_pct"] is None
    assert result["days_to_target"] is None
    assert result["drying_moisture"] is None
    assert result["drying_ready_for_cure"] is False


def test_build_sub_dataclass_blocks_are_model_complete(
    builder, mock_plant: Plant
) -> None:
    """phenotype_score / harvest_metrics carry every model field (ADR-0028)."""
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"
    mock_plant.phenotype_score = PhenotypeScore(vigor=8, notes="keeper candidate")

    result = builder.build(mock_plant)

    score_keys = set(PhenotypeScore().to_dict()) | {"total_score"}
    assert set(result["phenotype_score"]) == score_keys
    assert result["phenotype_score"]["notes"] == "keeper candidate"
    assert result["phenotype_score"]["total_score"] == 8
    assert set(result["harvest_metrics"]) == set(HarvestMetrics().to_dict())


def test_build_includes_phi_fields_when_clearance_set(
    builder, mock_plant: Plant
) -> None:
    """A set PHI clearance date ships with its computed days-remaining."""
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"
    mock_plant.phi_clearance_date = "2099-01-01"

    result = builder.build(mock_plant)

    assert result["phi_clearance_date"] == "2099-01-01"
    assert result["phi_days_remaining"] > 0


def test_build_attributes_matches_wire_payload_on_shared_blocks(
    builder, mock_plant: Plant
) -> None:
    """The sensor attribute projection shares the computed blocks with build()."""
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.plant_1"
    mock_plant.harvest_metrics = HarvestMetrics(wet_weight=100.0)
    mock_plant.drying_data = DryingData(
        weight_log=[WeightEntry(date="2024-01-01", weight_grams=80.0)],
        visual_tag="Red Velcro",
    )

    wire = builder.build(mock_plant)
    attributes = PlantViewModelBuilder.build_attributes(mock_plant)

    for key in (
        "drying_weight",
        "weight_lost_pct",
        "days_to_target",
        "visual_tag",
        "drying_moisture",
        "drying_ready_for_cure",
        "phenotype_score",
        "harvest_metrics",
        "position",
    ):
        assert attributes[key] == wire[key], key
