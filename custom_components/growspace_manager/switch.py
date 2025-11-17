"""Switch platform for Growspace Manager.

This file defines the switch entities for the Growspace Manager integration.
It includes a switch for each growspace to allow the user to enable or disable
notifications for that specific area.
"""

from __future__ import annotations
import logging
from typing import Any
from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.entity import DeviceInfo
from .const import DOMAIN
from .models import Growspace

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the switch platform for Growspace Manager from a config entry.

    This function is called by Home Assistant to set up the switch platform. It
    creates a `GrowspaceNotificationSwitch` for each growspace that has a
    notification target configured.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry.
        async_add_entities: A callback function for adding new entities.
    """
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]
    entities = []

    # Create notification switches for each growspace
    for growspace_id, growspace in coordinator.growspaces.items():
        if growspace.notification_target:
            entities.append(
                GrowspaceNotificationSwitch(coordinator, growspace_id, growspace)
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.debug("Added %d notification switches", len(entities))


class GrowspaceNotificationSwitch(SwitchEntity):
    """A switch entity to control notifications for a specific growspace.

    This switch allows the user to easily enable or disable all notifications
    originating from a particular growspace.
    """

    def __init__(self, coordinator, growspace_id: str, growspace: Growspace) -> None:
        """Initialize the GrowspaceNotificationSwitch.

        Args:
            coordinator: The data update coordinator.
            growspace_id: The ID of the growspace this switch controls.
            growspace: The Growspace data object.
        """
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        self._growspace = growspace
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_notifications"
        self._attr_name = f"{growspace.name} Notifications"
        self._attr_icon = "mdi:bell"

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def is_on(self) -> bool:
        """Return true if notifications are enabled for the growspace."""
        return self._coordinator.is_notifications_enabled(self._growspace_id)

    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable notifications for the growspace."""
        await self._coordinator.set_notifications_enabled(self._growspace_id, True)
        self.async_write_ha_state()
        _LOGGER.info(
            "Notifications enabled for growspace %s (%s)",
            self._growspace_id,
            self._growspace.name,
        )

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable notifications for the growspace."""
        await self._coordinator.set_notifications_enabled(self._growspace_id, False)
        self.async_write_ha_state()
        _LOGGER.info(
            "Notifications disabled for growspace %s (%s)",
            self._growspace_id,
            self._growspace.name,
        )

    async def async_added_to_hass(self) -> None:
        """Register a listener when the entity is added to Home Assistant."""
        self._coordinator.async_add_listener(self.async_write_ha_state)
