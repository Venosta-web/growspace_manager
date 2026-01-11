"""Describe logbook events."""

from __future__ import annotations

from typing import Any

from homeassistant.components.logbook import LogbookEntry
from homeassistant.core import HomeAssistant, callback

from .const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY


@callback
def async_describe_events(hass: HomeAssistant, async_describe_event) -> None:
    """Describe logbook events."""

    @callback
    def async_describe_log_entry_event(event: LogbookEntry) -> dict[str, Any]:
        """Describe a log entry event."""
        data = event.data
        category = data.get("category")

        # Note Event
        if category == "note":
            notes = data.get("notes", "")
            tags = data.get("tags", [])
            images = data.get("images", [])

            message = notes

            extras = []
            if tags:
                extras.append(f"Tags: {', '.join(tags)}")
            if images:
                extras.append(f"{len(images)} Image{'s' if len(images) > 1 else ''}")

            if extras:
                if message:
                    message += " "
                message += f"[{' | '.join(extras)}]"

            return {
                "name": "Plant Note",
                "message": message,
            }

        # Watering Event
        if category in ("water", "watering", "irrigation"):
            amount = data.get("amount_ml")
            message = "Watered"
            if amount:
                message += f" {amount}ml"

            # Add nutrient/recipe info if available
            if "recipe" in data:
                message += f" with {data['recipe']}"

            return {"name": "Watering", "message": message}

        # Training Event
        if category == "training":
            technique = data.get("sensor_type", "Training")
            # Capitalize first letter of technique
            if technique:
                technique = technique.replace("_", " ").title()

            return {
                "name": technique,
                "message": data.get("notes", "Training performed"),
            }

        # IPM Event
        if category == "ipm":
            treatment = data.get("sensor_type", "IPM")
            # Clean up sensor type string (e.g. ipm_neem -> Neem)
            if treatment.startswith("ipm_"):
                treatment = treatment[4:]
            treatment = treatment.replace("_", " ").title()

            return {
                "name": "IPM Treatment",
                "message": f"{treatment}: {data.get('notes', 'Applied')}",
            }

        # Default fallback
        return {
            "name": f"Growspace {category.title() if category else 'Event'}",
            "message": data.get("notes", "")
            or data.get("sensor_type", "")
            or "Event recorded",
        }

    async_describe_event(
        DOMAIN, EVENT_GROWSPACE_LOG_ENTRY, async_describe_log_entry_event
    )
