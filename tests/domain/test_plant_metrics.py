"""Tests for plant metrics calculations."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.domain.plant_metrics import (
    format_plant_position,
    get_days_since_ipm,
    get_days_since_training,
    get_days_since_watering,
    get_formatted_dates,
)
from custom_components.growspace_manager.models import Plant


@pytest.fixture
def mock_plant():
    """Fixture for a mock plant."""
    plant = MagicMock(spec=Plant)
    plant.last_watered = "2024-01-01T12:00:00"
    plant.last_trained = "2024-01-02T12:00:00"
    plant.last_ipm = "2024-01-03T12:00:00"
    plant.row = 1.0
    plant.col = 2.0
    plant.seedling_start = "2024-01-01"
    plant.mother_start = None
    plant.clone_start = None
    plant.veg_start = "2024-01-10"
    plant.flower_start = None
    plant.dry_start = None
    plant.cure_start = None
    return plant


def test_get_days_since_watering(mock_plant):
    """Test get_days_since_watering."""
    with MagicMock() as mock_calc, pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.domain.plant_metrics.calculate_days_since",
            mock_calc,
        )
        mock_calc.return_value = 5
        assert get_days_since_watering(mock_plant) == 5
        mock_calc.assert_called_once_with(mock_plant.last_watered)


def test_get_days_since_training(mock_plant):
    """Test get_days_since_training."""
    with MagicMock() as mock_calc, pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.domain.plant_metrics.calculate_days_since",
            mock_calc,
        )
        mock_calc.return_value = 3
        assert get_days_since_training(mock_plant) == 3
        mock_calc.assert_called_once_with(mock_plant.last_trained)


def test_get_days_since_ipm(mock_plant):
    """Test get_days_since_ipm."""
    with MagicMock() as mock_calc, pytest.MonkeyPatch().context() as mp:
        mp.setattr(
            "custom_components.growspace_manager.domain.plant_metrics.calculate_days_since",
            mock_calc,
        )
        mock_calc.return_value = 2
        assert get_days_since_ipm(mock_plant) == 2
        mock_calc.assert_called_once_with(mock_plant.last_ipm)


def test_format_plant_position(mock_plant):
    """Test format_plant_position."""
    assert format_plant_position(mock_plant) == "(1,2)"

    # Test with other values
    mock_plant.row = 3
    mock_plant.col = 4
    assert format_plant_position(mock_plant) == "(3,4)"


def test_get_formatted_dates(mock_plant):
    """Test get_formatted_dates."""
    dates = get_formatted_dates(mock_plant)
    assert isinstance(dates, dict)
    assert "seedling_start" in dates
    assert "last_watered" in dates
    assert "last_trained" in dates
    assert "last_ipm" in dates
    # Verify values are strings or None as per format_date
    for key in dates:
        assert dates[key] is None or isinstance(dates[key], str)
