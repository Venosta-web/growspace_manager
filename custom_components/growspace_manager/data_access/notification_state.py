"""Notification state for the Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NotificationState:
    """Tracks per-growspace notification enablement and per-plant sent history."""

    sent: dict[str, dict[str, dict[str, bool]]] = field(default_factory=dict)
    enabled: dict[str, bool] = field(default_factory=dict)
