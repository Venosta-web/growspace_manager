"""Crop steering sensor for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.crop_steering import get_crop_steering_state
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
        state = get_crop_steering_state(self.coordinator, self._growspace_id)
        return round(state.score, 2) if state else None

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return crop steering details."""
        state = get_crop_steering_state(self.coordinator, self._growspace_id)
        if not state:
            return {}

        if state.score > 0.3:
            mode = "generative"
        elif state.score < -0.3:
            mode = "vegetative"
        else:
            mode = "balanced"

        attributes: dict[str, Any] = {
            "dryback_percent": round(state.dryback_percent, 1),
            "peak_vwc": round(state.peak_vwc, 1),
            "trough_vwc": round(state.trough_vwc, 1),
            "steering_mode": mode,
            # ec_trend is None when no pore-EC sensors are configured (or no
            # reading yet). ec_trend_available distinguishes that from a
            # measured "stable" so the card can show its unlock hint.
            "ec_trend": state.ec_trend,
            "ec_trend_available": state.ec_trend_available,
            "ec_day_start": state.ec_day_start,
            "ec_current": state.ec_current,
        }

        # Measured substrate metrics from the SubstrateTracker (see ADR-0010).
        tracker = self.coordinator.services.growspaces.get_substrate_tracker(
            self._growspace_id
        )
        if tracker is not None:
            latest_overnight = tracker.get_latest_overnight_dryback()
            attributes["overnight_dryback"] = (
                round(latest_overnight["dryback"], 1)
                if latest_overnight is not None
                else None
            )
            incycle = tracker.get_incycle_drybacks_today()
            attributes["incycle_dryback_count"] = len(incycle)
            avg = tracker.get_average_incycle_dryback_today()
            attributes["incycle_dryback_avg"] = (
                round(avg, 1) if avg is not None else None
            )

        # Shot Size Composition: base × VWC factor × EC modulation factor, with
        # the configured pore-EC band and modulation capability. Surfaced here
        # (not in the static strategy payload) because the factors are runtime
        # state on the VWC coordinator. Absent on time-based irrigation.
        irrigation_coord = (
            self.coordinator.services.growspaces.get_irrigation_coordinator(
                self._growspace_id
            )
        )
        if irrigation_coord is not None and hasattr(
            irrigation_coord, "shot_composition_payload"
        ):
            attributes["shot_composition"] = irrigation_coord.shot_composition_payload()

        return attributes
