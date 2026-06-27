"""Coverage tests for calendar.py."""

from unittest.mock import MagicMock, Mock, patch

import pytest

from custom_components.growspace_manager.calendar import GrowspaceCalendar


@pytest.fixture
def mock_coordinator() -> Mock:
    """Create a mock GrowspaceCoordinator."""
    coordinator = MagicMock()
    coordinator.hass = Mock()
    coordinator.services = MagicMock()  # ADDED: Initialize the services namespace

    growspace_mock = Mock()
    growspace_mock.name = "Growspace 1"
    growspace_mock.id = "gs1"
    coordinator.growspaces = {"gs1": growspace_mock}
    coordinator.plants = {
        "p1": Mock(
            plant_id="p1",
            growspace_id="gs1",
            strain="Strain A",
            veg_start="2023-01-01",
        )
    }
    coordinator.options = {
        "timed_notifications": [
            {
                "id": "veg_reminder",
                "growspace_ids": ["gs1"],
                "trigger_type": "veg",
                "day": "5",
                "message": "Check veg progress",
            }
        ]
    }

    # UPDATED: Point to the new services location
    coordinator.services.growspaces.get_growspace_plants.return_value = list(
        coordinator.plants.values()
    )
    return coordinator


def test_generate_events_exception_handling(mock_coordinator: Mock) -> None:
    """Test exception handling in _generate_events."""
    calendar = GrowspaceCalendar(mock_coordinator, "gs1")

    # Patch dt_util.parse_datetime to raise ValueError
    with (
        patch(
            "homeassistant.util.dt.parse_datetime", side_effect=ValueError("Test Error")
        ),
        patch(
            "custom_components.growspace_manager.calendar._LOGGER.warning"
        ) as mock_warning,
    ):
        calendar._generate_events()

        # Verify that warning was logged
        assert mock_warning.called
        args = mock_warning.call_args[0]
        assert args[0] == "Could not generate calendar event for plant %s: %s"
        assert args[1] == "p1"
        assert isinstance(args[2], ValueError)
        assert str(args[2]) == "Test Error"
