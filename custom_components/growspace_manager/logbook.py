"""Describe logbook events."""

from __future__ import annotations

from typing import Any

try:
    from homeassistant.components.recorder.models import LogbookEntry
except ImportError:
    try:
        from homeassistant.components.logbook import LogbookEntry
    except ImportError:
        from typing import Protocol, runtime_checkable

        @runtime_checkable
        class LogbookEntry(Protocol):
            """Fallback protocol for LogbookEntry."""

            data: dict[str, Any]


from homeassistant.core import HomeAssistant, callback

from .const import CATEGORY_NOTE, DOMAIN, EVENT_GROWSPACE_LOG_ENTRY


@callback
def async_describe_events(hass: HomeAssistant, async_describe_event) -> None:
    """Describe logbook events."""

    @callback
    def async_describe_log_entry_event(event: LogbookEntry) -> dict[str, Any]:
        """Describe a log entry event."""
        data = event.data
        category = data.get("category")

        # Use helper based on category
        if category == CATEGORY_NOTE:
            return _describe_note_event(data)
        if category in ("water", "watering", "irrigation"):
            return _describe_watering_event(data)
        if category == "training":
            return _describe_training_event(data)
        if category == "ipm":
            return _describe_ipm_event(data)

        # Default fallback
        return _describe_default_event(category, data)

    async_describe_event(
        DOMAIN, EVENT_GROWSPACE_LOG_ENTRY, async_describe_log_entry_event
    )


def _describe_note_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a note event."""
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

    return {"name": "Plant Note", "message": message}


def _describe_watering_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a watering event."""
    amount = data.get("amount_ml")
    message = "Watered"
    if amount:
        message += f" {amount}ml"

    if "recipe" in data:
        message += f" with {data['recipe']}"

    return {"name": "Watering", "message": message}


def _describe_training_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a training event."""
    technique = data.get("sensor_type", "Training")
    if technique:
        technique = technique.replace("_", " ").title()

    return {
        "name": technique,
        "message": data.get("notes", "Training performed"),
    }


def _describe_ipm_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe an IPM event."""
    treatment = data.get("sensor_type", "IPM")
    if treatment.startswith("ipm_"):
        treatment = treatment[4:]
    treatment = treatment.replace("_", " ").title()

    return {
        "name": "IPM Treatment",
        "message": f"{treatment}: {data.get('notes', 'Applied')}",
    }


def _describe_default_event(
    category: str | None, data: dict[str, Any]
) -> dict[str, Any]:
    """Describe a default event."""
    return {
        "name": f"Growspace {category.title() if category else 'Event'}",
        "message": data.get("notes", "")
        or data.get("sensor_type", "")
        or "Event recorded",
    }
