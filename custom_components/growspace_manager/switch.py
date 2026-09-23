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
from homeassistant.helpers.restore_state import RestoreEntity

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.issue_registry import async_delete_issue

from . import GrowspaceConfigEntry
from .const import DOMAIN
from .models import Growspace

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, kw_only=True)
class GrowspaceSwitchDescription(SwitchEntityDescription):  # HA base class
    """Class describing Growspace Manager switch entities."""

    has_entity_name: bool = True


NOTIFICATION_SWITCH = GrowspaceSwitchDescription(
    key="notifications",
    translation_key="notifications",
)

SWITCH_TYPES: tuple[GrowspaceSwitchDescription, ...] = (NOTIFICATION_SWITCH,)

AUTOMATION_SWITCH = GrowspaceSwitchDescription(
    key="automation", translation_key="automation"
)
IRRIGATION_ARM_SWITCH = GrowspaceSwitchDescription(
    key="irrigation_armed", translation_key="irrigation_armed"
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrowspaceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager switch platform from a config entry."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    def add_new_growspaces() -> None:
        entities: list[SwitchEntity] = []
        for growspace_id, growspace in coordinator.growspaces.items():
            if growspace_id in known:
                continue
            known.add(growspace_id)
            entities.extend(
                GrowspaceSafetySwitch(coordinator, growspace_id, growspace, description)
                for description in (AUTOMATION_SWITCH, IRRIGATION_ARM_SWITCH)
            )
            if growspace.notification_target:
                entities.append(
                    GrowspaceNotificationSwitch(
                        coordinator, growspace_id, growspace, NOTIFICATION_SWITCH
                    )
                )
        if entities:
            async_add_entities(entities)
            _LOGGER.debug("Added %d switches", len(entities))

    add_new_growspaces()
    entry.async_on_unload(coordinator.async_add_listener(add_new_growspaces))


class GrowspaceNotificationSwitch(SwitchEntity):  # HA base class
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
    @override  # SwitchEntity.is_on exists but not detected by mypy
    def is_on(self) -> bool:
        """Return true if notifications are enabled for the growspace."""
        return self._coordinator.services.notifications.is_notifications_enabled(
            self._growspace_id
        )

    @override  # SwitchEntity.async_turn_on exists but not detected by mypy
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Enable notifications for the growspace."""
        await self._coordinator.services.notifications.set_notifications_enabled(
            self._growspace_id, True
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Notifications enabled for growspace %s (%s)",
            self._growspace_id,
            self._growspace.name,
        )

    @override  # SwitchEntity.async_turn_off exists but not detected by mypy
    async def async_turn_off(self, **kwargs: Any) -> None:
        """Disable notifications for the growspace."""
        await self._coordinator.services.notifications.set_notifications_enabled(
            self._growspace_id, False
        )
        self.async_write_ha_state()
        _LOGGER.info(
            "Notifications disabled for growspace %s (%s)",
            self._growspace_id,
            self._growspace.name,
        )

    @override  # Entity.async_added_to_hass exists but not detected by mypy
    async def async_added_to_hass(self) -> None:
        """Register a listener when the entity is added to Home Assistant."""
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )


class GrowspaceSafetySwitch(SwitchEntity, RestoreEntity):
    """Durable per-growspace operator control backed by the safety store."""

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace: Growspace,
        description: GrowspaceSwitchDescription,
    ) -> None:
        """Bind the control to the persisted state of one growspace."""
        self.entity_description = description
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        self._key = description.key
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_{description.key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override
    def is_on(self) -> bool:
        controls = self._coordinator.irrigation_safety.controls.get(
            self._growspace_id, {}
        )
        return controls.get(self._key, self._key == "automation")

    async def _set(self, enabled: bool) -> None:
        await self._coordinator.irrigation_safety.async_set_control(
            self._growspace_id,
            self._key,
            enabled,
            self._context.user_id if self._context else None,
        )
        if self._key == "irrigation_armed":
            async_delete_issue(
                self.hass, DOMAIN, f"irrigation_arm_review_{self._growspace_id}"
            )
        self._coordinator.async_update_listeners()
        self.async_write_ha_state()

    @override
    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    @override
    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)

    @override
    async def async_added_to_hass(self) -> None:
        """Use the store for restoration so controls gate before HA entity setup."""
        await super().async_added_to_hass()
        self.async_on_remove(
            self._coordinator.async_add_listener(self.async_write_ha_state)
        )
