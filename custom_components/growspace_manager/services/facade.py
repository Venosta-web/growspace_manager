"""Service facade container for the Growspace Manager integration.

This module composes four domain sub-facades under a single entry point
(coordinator.services) so callers never need to reach into coordinator
internals directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from custom_components.growspace_manager.const import (
    CATEGORY_NOTE,
    EVENT_GROWSPACE_LOG_ENTRY,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from .config_facade import ConfigFacade
from .growspace_facade import GrowspaceFacade
from .notifications_facade import NotificationsFacade
from .plant_facade import PlantFacade

if TYPE_CHECKING:
    from custom_components.growspace_manager.coordinator import GrowspaceCoordinator

_LOGGER = logging.getLogger(__name__)


class ServiceFacade:
    """Container that composes all domain sub-facades.

    Access via coordinator.services:
        coordinator.services.growspaces.*
        coordinator.services.plants.*
        coordinator.services.config.*
        coordinator.services.notifications.*
        coordinator.services.save()
        coordinator.services.fire_event(...)
        coordinator.services.add_timeline_note(...)
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        self._coordinator = coordinator
        self.growspaces = GrowspaceFacade(coordinator)
        self.plants = PlantFacade(coordinator)
        self.config = ConfigFacade(coordinator)
        self.notifications = NotificationsFacade(coordinator)

    # -------------------------------------------------------------------------
    # Infrastructure
    # -------------------------------------------------------------------------

    async def save(self) -> None:
        """Persist current data to storage."""
        await self._coordinator.async_commit()

    async def request_refresh(self) -> None:
        """Request a refresh of all entities."""
        await self._coordinator.async_request_refresh()

    def fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire a growspace manager event on the HA bus."""
        payload = {"event_type": event_type, "data": data}
        self._coordinator.hass.bus.async_fire("growspace_manager_updated", payload)

    # -------------------------------------------------------------------------
    # Cross-domain operations
    # -------------------------------------------------------------------------

    async def add_timeline_note(
        self,
        plant_id: str,
        notes: str,
        timestamp: str | None = None,
        images_base64: list[str] | None = None,
        tags: list[str] | None = None,
        ph: float | None = None,
        ec: float | None = None,
        amount_ml: float | None = None,
        external_metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add a timeline note to a plant, snapshotting environment sensor values."""
        if images_base64 is None:
            images_base64 = []
        if tags is None:
            tags = []
        if external_metadata is None:
            external_metadata = {}

        plant = self._coordinator.plants.get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Plant {plant_id} not found")

        growspace_id = plant.growspace_id
        metadata: dict[str, Any] = {}

        if growspace := self._coordinator.growspaces.get(growspace_id):
            env_config = growspace.environment_config

            def _get_state(entity_id: str | None) -> float | None:
                if not entity_id:
                    return None
                state = self._coordinator.hass.states.get(entity_id)
                try:
                    if state and state.state not in ("unknown", "unavailable"):
                        return float(state.state)
                except ValueError:
                    pass
                return None

            metadata.update(
                {
                    "temperature": _get_state(env_config.temperature_sensor),
                    "humidity": _get_state(env_config.humidity_sensor),
                    "vpd": _get_state(env_config.vpd_sensor),
                    "soil_moisture": _get_state(env_config.soil_moisture_sensor),
                    "light_intensity": _get_state(env_config.light_sensor),
                }
            )

        if ph is not None:
            metadata["ph"] = ph
        if ec is not None:
            metadata["ec"] = ec
        if amount_ml is not None:
            metadata["amount_ml"] = amount_ml
        metadata.update(external_metadata)

        image_paths: list[str] = []
        if images_base64 and self._coordinator.strain_library:
            image_manager = self._coordinator.strain_library.image_manager
            if image_manager:
                for img_b64 in images_base64:
                    try:
                        abs_path = await image_manager.save_timeline_image(
                            plant_id=plant_id,
                            image_base64=img_b64,
                            timestamp=timestamp,
                        )
                        image_paths.append(f"timeline/{Path(abs_path).name}")
                    except (OSError, ValueError) as e:
                        _LOGGER.error("Failed to save timeline image: %s", e)

        event_data = {
            "plant_id": plant_id,
            "growspace_id": growspace_id,
            "notes": notes,
            "tags": tags,
            "metadata": metadata,
            "images": image_paths,
            "category": CATEGORY_NOTE,
            "timestamp": timestamp or dt_util.now().isoformat(),
        }
        self._coordinator.hass.bus.async_fire(EVENT_GROWSPACE_LOG_ENTRY, event_data)
        _LOGGER.info("Added timeline note for plant %s", plant_id)
