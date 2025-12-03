"""Calendar platform for Growspace Manager.

This file defines the calendar entities for the Growspace Manager integration.
Each growspace gets its own calendar, which displays scheduled tasks and reminders
based on the timed notifications configured by the user.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the calendar platform for Growspace Manager from a config entry.

    This function is called by Home Assistant to set up the calendar platform. It
    creates a `GrowspaceCalendar` entity for each growspace managed by the
    coordinator.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry.
        async_add_entities: A callback function for adding new entities.
    """
    coordinator = config_entry.runtime_data.coordinator
    calendars = [
        GrowspaceCalendar(coordinator, growspace_id)
        for growspace_id in coordinator.growspaces
    ]
    async_add_entities(calendars, True)


class GrowspaceCalendar(CalendarEntity):
    """A calendar entity for a growspace.

    This calendar displays events that are generated from the user-configured
    timed notifications, providing a schedule of upcoming tasks and reminders
    for the plants within the growspace.
    """

    def __init__(self, coordinator: GrowspaceCoordinator, growspace_id: str) -> None:
        """Initialize the GrowspaceCalendar.

        Args:
            coordinator: The data update coordinator.
            growspace_id: The ID of the growspace this calendar belongs to.
        """
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{self.growspace.name} Tasks"
        self._attr_unique_id = f"{DOMAIN}_{self.growspace_id}_calendar"
        self._events: list[CalendarEvent] = []

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event on the calendar."""
        return next(
            (
                event
                for event in self._events
                if event.start_datetime_local > dt_util.now()
            ),
            None,
        )

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        """Return a list of calendar events within a specific time range.

        Args:
            hass: The Home Assistant instance.
            start_date: The start of the date range.
            end_date: The end of the date range.

        Returns:
            A list of `CalendarEvent` objects.
        """
        return [
            event
            for event in self._events
            if event.start_datetime_local >= start_date
            and event.end_datetime_local <= end_date
        ]

    def _generate_events(self) -> None:
        """Generate all calendar events for the growspace based on timed notifications."""
        events = []
        notifications = self.coordinator.options.get("timed_notifications", [])
        plants = self.coordinator.get_growspace_plants(self.growspace_id)

        for plant in plants:
            for notification in notifications:
                # Check if the notification applies to this growspace
                if self.growspace_id not in notification["growspace_ids"]:
                    continue

                trigger_type = notification["trigger_type"]  # 'veg' or 'flower' etc
                days_offset = int(notification["day"])
                message = notification["message"]

                start_date_str = getattr(plant, f"{trigger_type}_start", None)
                if not start_date_str:
                    continue

                try:
                    start_date = dt_util.parse_datetime(start_date_str).date()
                    event_date = start_date + timedelta(days=days_offset)

                    # Create an all-day event and make it timezone-aware
                    event_start = dt_util.as_local(
                        datetime.combine(event_date, datetime.min.time())
                    )
                    event_end = dt_util.as_local(
                        datetime.combine(event_date, datetime.max.time())
                    )

                    event = CalendarEvent(
                        start=event_start,
                        end=event_end,
                        summary=f"{trigger_type.capitalize()} Day {days_offset} ({plant.strain}): {message}",
                        description=f"Task for plant {plant.strain} in growspace {self.growspace.name}.",
                        uid=f"{plant.plant_id}_{notification['id']}",
                    )
                    events.append(event)
                except Exception as e:
                    _LOGGER.warning(
                        "Could not generate calendar event for plant %s: %s",
                        plant.plant_id,
                        e,
                    )

        self._events = sorted(events, key=lambda e: e.start_datetime_local)

    async def async_update(self) -> None:
        """Update the calendar's list of events."""
        self._generate_events()
