"""Describe logbook events."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from homeassistant.components.logbook import LOGBOOK_ENTRY_MESSAGE, LOGBOOK_ENTRY_NAME
from homeassistant.core import HomeAssistant, callback

from .const import CATEGORY_ALERT, CATEGORY_DEHUMIDIFIER, CATEGORY_HUMIDIFIER, CATEGORY_MILESTONE, CATEGORY_NOTE, DOMAIN, EVENT_GROWSPACE_LOG_ENTRY

if TYPE_CHECKING:
    from homeassistant.components.logbook import LazyEventPartialState


@callback
def async_describe_events(
    hass: HomeAssistant,
    async_describe_event: Callable[
        [str, str, Callable[[LazyEventPartialState], dict[str, Any]]], None
    ],
) -> None:
    """Describe logbook events."""

    @callback
    def async_describe_log_entry_event(
        event: LazyEventPartialState,
    ) -> dict[str, Any]:
        """Describe a log entry event."""
        data = event.data
        category = data.get("category")

        match category:
            case category if category == CATEGORY_NOTE:
                return _describe_note_event(data)
            case "water" | "watering" | "irrigation":
                return _describe_watering_event(data)
            case "training":
                return _describe_training_event(data)
            case "ipm":
                return _describe_ipm_event(data)
            case category if category == CATEGORY_DEHUMIDIFIER:
                return _describe_dehumidifier_event(data)
            case category if category == CATEGORY_HUMIDIFIER:
                return _describe_humidifier_event(data)
            case category if category == CATEGORY_MILESTONE:
                return _describe_milestone_event(data)
            case category if category == CATEGORY_ALERT:
                return _describe_alert_event(data)
            case "environment":
                return _describe_environment_event(data)
            case _:
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

    return {LOGBOOK_ENTRY_NAME: "Plant Note", LOGBOOK_ENTRY_MESSAGE: message}


def _describe_watering_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a watering event."""
    amount = data.get("amount_ml")
    message = "Watered"
    if amount:
        message += f" {amount}ml"

    if "recipe" in data:
        message += f" with {data['recipe']}"

    return {LOGBOOK_ENTRY_NAME: "Watering", LOGBOOK_ENTRY_MESSAGE: message}


def _describe_training_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a training event."""
    technique = data.get("sensor_type", "Training")
    if technique:
        technique = technique.replace("_", " ").title()

    return {
        LOGBOOK_ENTRY_NAME: technique,
        LOGBOOK_ENTRY_MESSAGE: data.get("notes", "Training performed"),
    }


def _describe_ipm_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe an IPM event."""
    treatment = data.get("sensor_type", "IPM")
    treatment = treatment.removeprefix("ipm_")
    treatment = treatment.replace("_", " ").title()

    return {
        LOGBOOK_ENTRY_NAME: "IPM Treatment",
        LOGBOOK_ENTRY_MESSAGE: f"{treatment}: {data.get('notes', 'Applied')}",
    }


def _describe_dehumidifier_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a dehumidifier control event."""
    reasons = data.get("reasons", [])
    action = next(
        (r for r in reasons if r in ("Turned ON", "Turned OFF")), "Controlled"
    )
    details = [r for r in reasons if r not in ("Turned ON", "Turned OFF")]
    message = action
    if details:
        message += f" • {', '.join(details)}"
    return {LOGBOOK_ENTRY_NAME: "Dehumidifier Control", LOGBOOK_ENTRY_MESSAGE: message}


def _describe_humidifier_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a humidifier control event."""
    reasons = data.get("reasons", [])
    action = next(
        (r for r in reasons if r in ("Turned ON", "Turned OFF")), "Controlled"
    )
    details = [r for r in reasons if r not in ("Turned ON", "Turned OFF")]
    message = action
    if details:
        message += f" • {', '.join(details)}"
    return {LOGBOOK_ENTRY_NAME: "Humidifier Control", LOGBOOK_ENTRY_MESSAGE: message}


def _describe_milestone_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a growth milestone event (e.g. stage transition)."""
    reasons = data.get("reasons", [])
    message = reasons[0] if reasons else data.get("sensor_type", "Milestone reached")
    return {LOGBOOK_ENTRY_NAME: "Growth Milestone", LOGBOOK_ENTRY_MESSAGE: message}


def _describe_alert_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe a stress or mold alert event."""
    sensor_type = data.get("sensor_type", "alert")
    label = sensor_type.replace("_", " ").title()
    reasons = data.get("reasons", [])
    duration = data.get("duration_sec", 0)
    message = f"{label} detected"
    if duration:
        minutes = duration // 60
        message += f" — lasted {minutes} minutes" if minutes else f" — lasted {duration} seconds"
    if reasons:
        message += f" • {reasons[0]}"
    return {LOGBOOK_ENTRY_NAME: f"{label} Alert", LOGBOOK_ENTRY_MESSAGE: message}


def _describe_environment_event(data: dict[str, Any]) -> dict[str, Any]:
    """Describe an optimal-conditions drop event."""
    reasons = data.get("reasons", [])
    duration = data.get("duration_sec", 0)
    message = "Conditions left optimal range"
    if duration:
        minutes = duration // 60
        message += f" for {minutes} min" if minutes else f" for {duration}s"
    if reasons:
        message += f" • {reasons[0]}"
    return {LOGBOOK_ENTRY_NAME: "Environment Alert", LOGBOOK_ENTRY_MESSAGE: message}


def _describe_default_event(
    category: str | None, data: dict[str, Any]
) -> dict[str, Any]:
    """Describe a default event."""
    return {
        LOGBOOK_ENTRY_NAME: f"Growspace {category.title() if category else 'Event'}",
        LOGBOOK_ENTRY_MESSAGE: data.get("notes", "")
        or data.get("sensor_type", "")
        or "Event recorded",
    }
