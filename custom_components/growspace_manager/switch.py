"""Switch platform for Growspace Manager.

This file defines the switch entities for the Growspace Manager integration.
It includes a switch for each growspace to allow the user to enable or disable
notifications for that specific area.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import TYPE_CHECKING, Any, override

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import GrowspaceConfigEntry
from .const import DOMAIN
from .models import Growspace

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GrowspaceSwitchDescription(SwitchEntityDescription):  # type: ignore[misc]  # HA base class
    """Class describing Growspace Manager switch entities."""

    has_entity_name: bool = True


NOTIFICATION_SWITCH = GrowspaceSwitchDescription(
    key="notifications",
    translation_key="notifications",
)

SWITCH_TYPES: tuple[GrowspaceSwitchDescription, ...] = (NOTIFICATION_SWITCH,)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrowspaceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager switch platform from a config entry."""
    coordinator = entry.runtime_data
    entities: list[GrowspaceNotificationSwitch] = []

    # Create switches for each growspace
    for growspace_id, growspace in coordinator.growspaces.items():
        # Notifications switch
        if growspace.notification_target:
            entities.append(
                GrowspaceNotificationSwitch(
                    coordinator, growspace_id, growspace, NOTIFICATION_SWITCH
                )
            )

    if entities:
        async_add_entities(entities)
        _LOGGER.debug("Added %d switches", len(entities))


class GrowspaceNotificationSwitch(SwitchEntity):  # type: ignore[misc]  # HA base class
    """A switch entity to control notifications for a specific growspace."""

    entity_description: GrowspaceSwitchDescription
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace: Growspace,
        description: GrowspaceSwitchDescription,
    ) -> None:
        """Initialize the GrowspaceNotificationSwitch."""
        self.entity_description = description
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        self._growspace = growspace

        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_{description.key}"

        # Set up device info using dot notation from typed model
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]  # SwitchEntity.is_on exists but not detected by mypy
    def is_on(self) -> bool:
        """Return true if notifications are enabled for the growspace."""
        return self._coordinator.services.is_notifications_enabled(
            self._growspace_id
        )

    @override  # type: ignore[misc]  # SwitchEntity.async_turn_on exists but not detected by mypy
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable notifications for the growspace."""
        await self._coordinator.services.set_notifications_enabled(
            self._growspace_id, True
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Notifications enabled for growspace %s (%s)",
            self._growspace_id,
            self._growspace.name,
        )

    @override  # type: ignore[misc]  # SwitchEntity.async_turn_off exists but not detected by mypy
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable notifications for the growspace."""
        await self._coordinator.services.set_notifications_enabled(
            self._growspace_id, False
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Notifications disabled for growspace %s (%s)",
            self._growspace_id,
            self._growspace.name,
        )

    @override  # type: ignore[misc]  # Entity.async_added_to_hass exists but not detected by mypy
    async def async_added_to_hass(self) -> None:
        """Register a listener when the entity is added to Home Assistant."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )
