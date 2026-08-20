"""Notification state for the Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NotificationState:
    """Tracks per-growspace notification enablement and per-plant sent history."""

    sent: dict[str, dict[str, dict[str, bool]]] = field(default_factory=dict)
    enabled: dict[str, bool] = field(default_factory=dict)

    def mark_sent(self, plant_id: str, stage: str, days: int) -> None:
        """Record that a notification has been sent for plant/stage/days."""
        self.sent.setdefault(plant_id, {}).setdefault(stage, {})[str(days)] = True

    def is_sent(self, plant_id: str, stage: str, days: int) -> bool:
        """Return True if the notification has already been sent."""
        return self.sent.get(plant_id, {}).get(stage, {}).get(str(days), False)
