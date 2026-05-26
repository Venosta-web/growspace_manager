"""Vision checkup sensor for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator


class VisionCheckupSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor showing the latest AI vision checkup result for a growspace."""

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
    def _growspace(self) -> Any:
        """Return the growspace from coordinator."""
        return self.coordinator.growspaces.get(self._growspace_id)

    @property
    def _latest_result(self) -> Any:
        """Return the latest vision checkup result or None."""
        gs = self._growspace
        if gs and gs.vision_checkup_history:
            return gs.vision_checkup_history[0]
        return None

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> str | None:
        """Return the severity of the latest checkup."""
        result = self._latest_result
        return result.severity if result else None

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed attributes from the latest checkup."""
        result = self._latest_result
        if not result:
            return {
                "last_check_type": None,
                "last_analysis": None,
                "issues_detected": [],
                "recommendations": [],
                "last_checkup_time": None,
                "total_checkups": 0,
            }

        gs = self._growspace
        return {
            "last_check_type": result.check_type,
            "last_analysis": result.analysis,
            "issues_detected": result.issues_detected,
            "recommendations": result.recommendations,
            "last_checkup_time": result.timestamp,
            "total_checkups": len(gs.vision_checkup_history) if gs else 0,
        }
