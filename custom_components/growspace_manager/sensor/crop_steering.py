"""Crop steering sensor for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class CropSteeringSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor calculating a vegetative-to-generative crop steering score."""

    _attr_has_entity_name = True
    _attr_translation_key = "crop_steering"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-timeline-variant-shimmer"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
    ) -> None:
        """Initialize the crop steering sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_crop_steering"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return the crop steering score (-1.0 to 1.0)."""
        from custom_components.growspace_manager.crop_steering import (
            get_crop_steering_state,
        )

        state = get_crop_steering_state(self.coordinator, self._growspace_id)
        return round(state.score, 2) if state else None

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return crop steering details."""
        from custom_components.growspace_manager.crop_steering import (
            get_crop_steering_state,
        )

        state = get_crop_steering_state(self.coordinator, self._growspace_id)
        if not state:
            return {}

        if state.score > 0.3:
            mode = "generative"
        elif state.score < -0.3:
            mode = "vegetative"
        else:
            mode = "balanced"

        return {
            "dryback_percent": round(state.dryback_percent, 1),
            "peak_vwc": round(state.peak_vwc, 1),
            "trough_vwc": round(state.trough_vwc, 1),
            "steering_mode": mode,
            "ec_trend": state.ec_trend,
        }
