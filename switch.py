"""Switch platform for Growspace Manager."""

from __future__ import annotations

import logging
from typing import Any, Dict

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform."""
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    entities = []

    # Create notification switches for each growspace
    for growspace_id, growspace in coordinator.growspaces.items():
        if growspace.get("notification_target"):
            entities.append(
                GrowspaceNotificationSwitch(coordinator, growspace_id, growspace)
            )

    async_add_entities(entities)


class GrowspaceNotificationSwitch(SwitchEntity):
    """Switch to enable/disable notifications for a growspace."""

    def __init__(self, coordinator, growspace_id: str, growspace: dict[str, Any]):
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        self._growspace = growspace
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_notifications"
        self._attr_name = f"{growspace['name']} Notifications"
        self._attr_icon = "mdi:bell"
        self._is_on = True  # Default to enabled

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace["name"],
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def is_on(self) -> bool:
        """Return true if the switch is on."""
        return self._is_on

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Turn the switch on."""
        self._is_on = True
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn the switch off."""
        self._is_on = False
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self._coordinator.async_add_listener(self.async_write_ha_state)
