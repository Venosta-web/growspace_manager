"""Tests for the calendar platform of the Growspace Manager integration."""

from datetime import timedelta
from unittest.mock import MagicMock, Mock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.growspace_manager.calendar import (
    GrowspaceCalendar,
    async_setup_entry,
)
from custom_components.growspace_manager.const import DOMAIN


# --------------------
# Fixtures
# --------------------
@pytest.fixture
def mock_coordinator():
    """Create a mock GrowspaceCoordinator for calendar testing."""
    coordinator = Mock()
    coordinator.hass = Mock()

    growspace_mock = Mock()
    growspace_mock.name = "Growspace 1"
    growspace_mock.id = "gs1"

    coordinator.growspaces = {
        "gs1": growspace_mock
    }

    coordinator.plants = {
        "p1": Mock(
            plant_id="p1",
            growspace_id="gs1",
            strain="Strain A",
            veg_start=str(dt_util.now().date() - timedelta(days=10)),
            flower_start=str(dt_util.now().date() - timedelta(days=5)),
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
            },
            {
                "id": "flower_reminder",
                "growspace_ids": ["gs1"],
                "trigger_type": "flower",
                "day": "1",
                "message": "First day of flower",
            },
        ]
    }
    coordinator.get_growspace_plants.return_value = list(coordinator.plants.values())
    coordinator.async_add_listener = Mock()
    return coordinator


# --------------------
# async_setup_entry
# --------------------
@pytest.mark.asyncio
async def test_async_setup_entry_adds_entities(mock_coordinator):
    """Test that `async_setup_entry` correctly adds calendar entities."""
    hass = MagicMock()

    added_entities = []

    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    await async_setup_entry(hass, Mock(entry_id="entry_1", runtime_data=Mock(coordinator=mock_coordinator)), async_add_entities)

    assert len(added_entities) == 1
    assert isinstance(added_entities[0], GrowspaceCalendar)
    assert added_entities[0].unique_id == f"{DOMAIN}_gs1_calendar"


# --------------------
# GrowspaceCalendar
# --------------------
def test_growspace_calendar_init(mock_coordinator):
    """Test the initialization of the GrowspaceCalendar."""
    calendar = GrowspaceCalendar(mock_coordinator, "gs1")
    assert calendar.growspace_id == "gs1"
    assert calendar.name == "Growspace 1 Tasks"
    assert calendar.unique_id == f"{DOMAIN}_gs1_calendar"


@pytest.mark.asyncio
async def test_growspace_calendar_update_and_get_events(mock_coordinator):
    """Test event generation and retrieval."""
    calendar = GrowspaceCalendar(mock_coordinator, "gs1")
    await calendar.async_update()

    start_date = dt_util.now() - timedelta(days=30)
    end_date = dt_util.now() + timedelta(days=30)

    events = await calendar.async_get_events(mock_coordinator.hass, start_date, end_date)
    assert len(events) == 2
    assert all(e.start.tzinfo is not None for e in events)

    veg_event_date = dt_util.parse_datetime(mock_coordinator.plants["p1"].veg_start).date() + timedelta(days=5)
    flower_event_date = dt_util.parse_datetime(mock_coordinator.plants["p1"].flower_start).date() + timedelta(days=1)

    assert any(e.start.date() == veg_event_date for e in events)
    assert any(e.summary == "Veg Day 5 (Strain A): Check veg progress" for e in events)
    assert any(e.start.date() == flower_event_date for e in events)
    assert any(e.summary == "Flower Day 1 (Strain A): First day of flower" for e in events)


@pytest.mark.asyncio
async def test_growspace_calendar_event_property(mock_coordinator):
    """Test the event property to get the next upcoming event."""
    calendar = GrowspaceCalendar(mock_coordinator, "gs1")

    # Manually create future events
    now = dt_util.now()
    future_event1 = MagicMock()
    future_event1.start_datetime_local = now + timedelta(hours=1)
    future_event2 = MagicMock()
    future_event2.start_datetime_local = now + timedelta(hours=2)
    past_event = MagicMock()
    past_event.start_datetime_local = now - timedelta(hours=1)

    calendar._events = [past_event, future_event2, future_event1]
    # Need to sort them as the property expects sorted list
    calendar._events.sort(key=lambda e: e.start_datetime_local)

    next_event = calendar.event
    assert next_event is not None
    assert next_event.start_datetime_local == future_event1.start_datetime_local

@pytest.mark.asyncio
async def test_growspace_calendar_no_events(mock_coordinator):
    """Test calendar when no events are generated."""
    mock_coordinator.options["timed_notifications"] = []
    calendar = GrowspaceCalendar(mock_coordinator, "gs1")
    await calendar.async_update()

    start_date = dt_util.now() - timedelta(days=30)
    end_date = dt_util.now() + timedelta(days=30)

    events = await calendar.async_get_events(mock_coordinator.hass, start_date, end_date)
    assert len(events) == 0
    assert calendar.event is None

@pytest.mark.asyncio
async def test_generate_events_handles_missing_start_date(mock_coordinator):
    """Test that event generation skips notifications with missing plant start dates."""
    mock_coordinator.plants["p1"].veg_start = None
    calendar = GrowspaceCalendar(mock_coordinator, "gs1")
    await calendar.async_update()

    start_date = dt_util.now() - timedelta(days=30)
    end_date = dt_util.now() + timedelta(days=30)
    events = await calendar.async_get_events(mock_coordinator.hass, start_date, end_date)

    # Only the flower event should be created
    assert len(events) == 1
    assert events[0].summary.startswith("Flower")

@pytest.mark.asyncio
async def test_generate_events_handles_invalid_date_format(mock_coordinator, caplog):
    """Test that event generation handles and logs errors for invalid date formats."""
    mock_coordinator.plants["p1"].flower_start = "not a date"
    calendar = GrowspaceCalendar(mock_coordinator, "gs1")
    await calendar.async_update()

    start_date = dt_util.now() - timedelta(days=30)
    end_date = dt_util.now() + timedelta(days=30)
    events = await calendar.async_get_events(mock_coordinator.hass, start_date, end_date)

    # Only the veg event should be created
    assert len(events) == 1
    assert events[0].summary.startswith("Veg")
    assert "Could not generate calendar event" in caplog.text
    assert "plant p1" in caplog.text
