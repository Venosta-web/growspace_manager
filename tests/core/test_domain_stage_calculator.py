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


@freeze_time("2024-01-11T12:00:00")
def test_calculate_days_in_stage_card_trigger_vocabulary() -> None:
    """The card's timed-notification trigger must be a bare stage to ever fire.

    Regression guard for the cross-repo vocabulary bug: the card used to send
    '*_start' values (e.g. 'veg_start'), which resolve to no plant start field
    and so always return 0 days — the notification never reached its threshold.
    The bare stage 'veg' resolves to the veg_start field and counts correctly.
    """
    from custom_components.growspace_manager.domain import (  # noqa: PLC0415
        calculate_days_in_stage as domain_calc,
    )

    plant = MagicMock(spec=Plant)
    plant.seedling_start = None
    plant.clone_start = None
    plant.veg_start = "2024-01-01T12:00:00"  # 10 days before frozen now
    plant.flower_start = None
    plant.dry_start = None
    plant.cure_start = None

    # Bare stage (what the card now sends) resolves and counts.
    assert domain_calc(plant, "veg") == 10
    # Legacy '*_start' value (the bug) resolves to nothing → never fires.
    assert domain_calc(plant, "veg_start") == 0


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


def test_calculate_days_in_stage_ongoing(snapshot: SnapshotAssertion) -> None:
    """Test when the stage is currently ongoing (no end date)."""
    plant = MagicMock(spec=Plant)
    plant.veg_start = "2024-01-01T12:00:00"
    plant.flower_start = None

    with (
        patch(
            "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
        ) as mock_calc,
        freeze_time("2024-01-11T12:00:00"),
    ):
        mock_calc.return_value = 10
        result = calculate_days_in_stage(plant, PlantStage.VEG)
        assert result == 10
        mock_calc.assert_called_with("2024-01-01T12:00:00", None)
        # Snapshot test for record
        assert {"stage": "veg", "days": result} == snapshot


def test_calculate_days_in_stage_completed() -> None:
    """Test when the stage is completed (has an end date)."""
    plant = MagicMock(spec=Plant)
    plant.veg_start = "2024-01-01T12:00:00"
    plant.flower_start = "2024-01-20T12:00:00"

    with (
        patch(
            "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
        ) as mock_calc,
        freeze_time("2024-01-20 12:00:00", tz_offset=0),
    ):
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
def test_calculate_days_in_stage_transitions(stage, start_attr, end_attr) -> None:
    """Test all stage transitions and their corresponding end date attributes."""
    plant = MagicMock(spec=Plant)
    setattr(plant, start_attr, "2024-01-01")
    setattr(plant, end_attr, "2024-01-05")

    with (
        patch(
            "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
        ) as mock_calc,
        freeze_time("2024-01-05 12:00:00", tz_offset=0),
    ):
        mock_calc.return_value = 4
        assert calculate_days_in_stage(plant, stage) == 4
        mock_calc.assert_called_with("2024-01-01", "2024-01-05")


def test_calculate_days_in_stage_cure_no_end() -> None:
    """Test the cure stage which has no defined next stage end date in logic."""
    plant = MagicMock(spec=Plant)
    plant.cure_start = "2024-01-01"

    with (
        patch(
            "custom_components.growspace_manager.domain.stage_calculator.calculate_days_since"
        ) as mock_calc,
        freeze_time("2024-01-05 12:00:00", tz_offset=0),
    ):
        mock_calc.return_value = 5
        # stages not in the set/mapping in stage_calculator.py default to end_date=None
        assert calculate_days_in_stage(plant, PlantStage.CURE) == 5
        mock_calc.assert_called_with("2024-01-01", None)
