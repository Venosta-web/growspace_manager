"""Config handlers for Growspace Manager."""

from __future__ import annotations

import logging
from abc import ABC
from typing import Any, Generic, TypeVar

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

T = TypeVar("T")


class BaseConfigHandler(ABC, Generic[T]):
    """Base class for configuration handlers."""

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize the handler."""
        self.hass = hass
        self.config_entry = config_entry

    def clean_input(self, user_input: dict[str, Any]) -> dict[str, Any]:
        """Remove empty or None values from input."""
        return {k: v for k, v in user_input.items() if v is not None and v != ""}

    def merge_options(
        self, current_options: dict[str, Any], new_options: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge new options into current options."""
        updated = current_options.copy()
        updated.update(new_options)
        return updated
