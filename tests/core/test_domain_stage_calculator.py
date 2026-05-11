"""Tests for stage_calculator logic."""

from unittest.mock import MagicMock, patch

from freezegun import freeze_time
import pytest
from syrupy.assertion import SnapshotAssertion

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.domain.stage_calculator import (
    calculate_days_in_stage,
)
from custom_components.growspace_manager.models import Plant


def test_calculate_days_in_stage_no_start() -> None:
    """Test when the stage has not started yet."""
    plant = MagicMock(spec=Plant)
    # Ensure all possible start dates are None
    plant.seedling_start = None
    plant.clone_start = None
    plant.veg_start = None
    plant.flower_start = None
    plant.dry_start = None
    plant.cure_start = None

    with patch(
        "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
    ) as mock_calc:
        mock_calc.return_value = 0
        assert calculate_days_in_stage(plant, PlantStage.VEG) == 0
        mock_calc.assert_called_with(None, None)


@freeze_time("2024-01-01 12:00:00", tz_offset=0)
def test_calculate_days_in_stage_ongoing(snapshot: SnapshotAssertion) -> None:
    """Test when the stage is currently ongoing (no end date)."""
    plant = MagicMock(spec=Plant)
    plant.veg_start = "2024-01-01T12:00:00"
    plant.flower_start = None

    with patch(
        "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
    ) as mock_calc:
        mock_calc.return_value = 10
        result = calculate_days_in_stage(plant, PlantStage.VEG)
        assert result == 10
        mock_calc.assert_called_with("2024-01-01T12:00:00", None)
        # Snapshot test for record
        assert {"stage": "veg", "days": result} == snapshot


@freeze_time("2024-01-20 12:00:00", tz_offset=0)
def test_calculate_days_in_stage_completed() -> None:
    """Test when the stage is completed (has an end date)."""
    plant = MagicMock(spec=Plant)
    plant.veg_start = "2024-01-01T12:00:00"
    plant.flower_start = "2024-01-20T12:00:00"

    with patch(
        "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
    ) as mock_calc:
        mock_calc.return_value = 19
        assert calculate_days_in_stage(plant, PlantStage.VEG) == 19
        mock_calc.assert_called_with("2024-01-01T12:00:00", "2024-01-20T12:00:00")


@pytest.mark.parametrize(
    ("stage", "start_attr", "end_attr"),
    [
        (PlantStage.SEEDLING, "seedling_start", "veg_start"),
        (PlantStage.CLONE, "clone_start", "veg_start"),
        (PlantStage.VEG, "veg_start", "flower_start"),
        (PlantStage.FLOWER, "flower_start", "dry_start"),
        (PlantStage.DRY, "dry_start", "cure_start"),
    ],
)
@freeze_time("2024-01-05 12:00:00", tz_offset=0)
def test_calculate_days_in_stage_transitions(stage, start_attr, end_attr) -> None:
    """Test all stage transitions and their corresponding end date attributes."""
    plant = MagicMock(spec=Plant)
    setattr(plant, start_attr, "2024-01-01")
    setattr(plant, end_attr, "2024-01-05")

    with patch(
        "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
    ) as mock_calc:
        mock_calc.return_value = 4
        assert calculate_days_in_stage(plant, stage) == 4
        mock_calc.assert_called_with("2024-01-01", "2024-01-05")


@freeze_time("2024-01-05 12:00:00", tz_offset=0)
def test_calculate_days_in_stage_cure_no_end() -> None:
    """Test the cure stage which has no defined next stage end date in logic."""
    plant = MagicMock(spec=Plant)
    plant.cure_start = "2024-01-01"

    with patch(
        "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
    ) as mock_calc:
        mock_calc.return_value = 5
        # stages not in the set/mapping in stage_calculator.py default to end_date=None
        assert calculate_days_in_stage(plant, PlantStage.CURE) == 5
        mock_calc.assert_called_with("2024-01-01", None)
