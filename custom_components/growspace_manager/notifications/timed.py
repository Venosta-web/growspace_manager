"""Timed notification trigger vocabulary."""

from __future__ import annotations

from typing import Any, Final

TIMED_NOTIFICATION_TRIGGER_OPTIONS: Final = (
    ("clone", "Clone"),
    ("veg", "Vegetative"),
    ("flower", "Flowering"),
    ("dry", "Drying"),
)

_LEGACY_TRIGGER_TYPES: Final = {
    "days_since_flip": "flower",
    # Seed-grown plants enter the supported timed-notification vocabulary at veg.
    "days_since_germination": "veg",
    "clone_start": "clone",
    "veg_start": "veg",
    "flower_start": "flower",
    "dry_start": "dry",
}


def normalize_timed_notification_trigger(trigger_type: str) -> str:
    """Return the bare stage name for a timed notification trigger."""
    return _LEGACY_TRIGGER_TYPES.get(trigger_type, trigger_type)


def normalize_timed_notifications(
    notifications: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return timed notifications with legacy trigger values normalized."""
    return [
        {
            **notification,
            "trigger_type": normalize_timed_notification_trigger(
                notification["trigger_type"]
            ),
        }
        if "trigger_type" in notification
        else notification.copy()
        for notification in notifications
    ]
