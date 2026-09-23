"""Emergency stop buttons for each growspace."""

from __future__ import annotations

from typing import TYPE_CHECKING, override

from homeassistant.components.button import ButtonEntity
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .services.safety import async_emergency_stop_growspace

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

    from . import GrowspaceConfigEntry
    from .coordinator import GrowspaceCoordinator
    from .models import Growspace


async def async_setup_entry(
    hass: HomeAssistant,
    entry: GrowspaceConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create one emergency stop button per growspace."""
    coordinator = entry.runtime_data
    known: set[str] = set()

    def add_new_growspaces() -> None:
        entities = [
            GrowspaceEmergencyStopButton(coordinator, growspace_id, growspace)
            for growspace_id, growspace in coordinator.growspaces.items()
            if growspace_id not in known
        ]
        known.update(coordinator.growspaces)
        if entities:
            async_add_entities(entities)

    add_new_growspaces()
    entry.async_on_unload(coordinator.async_add_listener(add_new_growspaces))


class GrowspaceEmergencyStopButton(ButtonEntity):
    """Latch and verify all of a growspace's managed outputs."""

    _attr_has_entity_name = True
    _attr_translation_key = "emergency_stop"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace: Growspace,
    ) -> None:
        """Bind the button to one growspace and its HA device."""
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_emergency_stop"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @override
    async def async_press(self) -> None:
        """Invoke the same stop path as the domain service."""
        await async_emergency_stop_growspace(
            self.hass,
            self._coordinator,
            self._growspace_id,
            self._context.user_id if self._context else None,
        )
