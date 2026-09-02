"""Vision checkup sensor for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.vision_connection import VisionAvailability
from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class VisionCheckupSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Sensor showing the latest Vision Checkup's operational outcome."""

    _attr_has_entity_name = True
    _attr_translation_key = "vision_checkup"
    _attr_icon = "mdi:eye-check"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
    ) -> None:
        """Initialize the vision checkup sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{growspace_id}_vision_checkup"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def _latest_result(self) -> Any:
        """Return the latest durable V1 projection, never legacy cloud history."""
        return self.coordinator.vision_scheduler.latest_checkup(self._growspace_id)

    @property
    @override
    def native_value(self) -> str | None:
        """Return operational status, or current service unavailability."""
        result = self._latest_result
        if result is not None:
            status = result.get("status")
            return status if isinstance(status, str) else None
        if (
            self.coordinator.vision_connection.status.availability
            is not VisionAvailability.READY
        ):
            return "unavailable"
        return None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return explicit per-camera fusion summaries."""
        result = self._latest_result
        if not result:
            attributes: dict[str, Any] = {
                "checkup_id": None,
                "last_checkup_time": None,
                "trigger_source": None,
                "cameras": {},
            }
            status = self.coordinator.vision_connection.status
            if status.availability is not VisionAvailability.READY:
                attributes["reason"] = (
                    status.reason.value if status.reason is not None else None
                )
            return attributes

        cameras = {}
        for capture in result["captures"]:
            fusion = capture["fusion"]
            cameras[capture["camera_id"]] = {
                "analysis_state": capture["analysis_state"],
                "fusion_state": fusion.get("state"),
                "fusion_confidence": fusion.get("confidence"),
                "fusion_coverage": fusion.get("coverage"),
                "unavailable_reasons": fusion["unavailable_reasons"],
            }
        return {
            "checkup_id": result["checkup_id"],
            "last_checkup_time": result["completed_at"],
            "trigger_source": result["trigger_source"],
            "cameras": cameras,
        }
