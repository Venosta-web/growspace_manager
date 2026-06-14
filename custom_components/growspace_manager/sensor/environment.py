"""Environment sensor classes for Growspace Manager."""

from __future__ import annotations

from datetime import datetime
from typing import Any, override

from custom_components.growspace_manager.const import DEFAULT_DLI_TARGET_FLOWER, DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.ec_state import (
    band_for_week,
    resolve_feed_stage_week,
)
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util


class AirExchangeSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """A sensor that provides an air exchange recommendation for a growspace."""

    _attr_has_entity_name = True
    _attr_translation_key = "air_exchange"
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator: GrowspaceCoordinator, growspace_id: str) -> None:
        """Initialize the air exchange sensor."""
        super().__init__(coordinator)
        self.growspace_id = growspace_id
        self.growspace = coordinator.growspaces[growspace_id]
        self._attr_unique_id = f"{DOMAIN}_{self.growspace_id}_air_exchange"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.growspace_id)},
            name=self.growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> str:
        """Return the current recommended air exchange action."""
        return self.coordinator.data.get("air_exchange_recommendations", {}).get(  # type: ignore[no-any-return]
            self.growspace_id, "Idle"
        )


class DLISensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor tracking Daily Light Integral (mol/m2/day) for a growspace."""

    _attr_has_entity_name = True
    _attr_translation_key = "dli"
    _attr_native_unit_of_measurement = "mol/m²/d"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:white-balance-sunny"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
    ) -> None:
        """Initialize the DLI sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_dli"
        self._accumulated_mol: float = 0.0
        self._last_sample_time: datetime | None = None
        self._last_reset_date: str = ""
        self._photoperiod: float | None = None

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    def _get_current_ppfd(self) -> float | None:
        """Get current PPFD from configured light sensors."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace or not growspace.environment_config:
            return None
        for sensor_id in growspace.environment_config.light_sensors:
            state = self.hass.states.get(sensor_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except ValueError, TypeError:
                    continue
        return None

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return current day's accumulated DLI."""
        return round(self._accumulated_mol, 1) if self._accumulated_mol > 0 else 0.0

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return DLI attributes."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        ppfd = self._get_current_ppfd()

        target = DEFAULT_DLI_TARGET_FLOWER
        if growspace and growspace.environment_config:
            if growspace.growspace_type.value == "veg":
                target = growspace.environment_config.dli_target_veg
            else:
                target = growspace.environment_config.dli_target_flower

        pct = (self._accumulated_mol / target * 100) if target > 0 else 0.0

        estimated_final = None
        if ppfd is not None and growspace and growspace.environment_config:
            day_hours = growspace.environment_config.flower_day_hours
            if growspace.growspace_type.value == "veg":
                day_hours = growspace.environment_config.veg_day_hours
            estimated_final = round(ppfd * day_hours * 3600 / 1_000_000, 1)

        return {
            "target_dli": target,
            "accumulated_dli": self._accumulated_mol,
            "percentage_of_target": round(pct, 1),
            "estimated_final_dli": estimated_final,
            "ppfd_current": ppfd,
            "photoperiod": self._photoperiod,
            "last_reset": self._last_reset_date,
        }

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates by accumulating DLI."""
        now = dt_util.now()
        today = now.date().isoformat()

        if self._last_reset_date != today:
            self._accumulated_mol = 0.0
            self._last_reset_date = today
            self._last_sample_time = now

        ppfd = self._get_current_ppfd()
        if ppfd is not None and self._last_sample_time is not None:
            elapsed_seconds = (now - self._last_sample_time).total_seconds()
            if elapsed_seconds > 0:
                delta_mol = ppfd * elapsed_seconds / 1_000_000
                self._accumulated_mol += delta_mol

        self._last_sample_time = now
        super()._handle_coordinator_update()


class ECTargetSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor showing current EC target from an EC ramp curve."""

    _attr_has_entity_name = True
    _attr_translation_key = "ec_target"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:chart-bell-curve-cumulative"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
    ) -> None:
        """Initialize the EC target sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_ec_target"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    def _get_active_curve(self) -> Any:
        """Get the active EC ramp curve for this growspace's feed stage.

        Resolves the stage through the EC State seam (``resolve_feed_stage_week``),
        so the sensor agrees with the feed-target reconciliation and the card on
        which stage and week are current: the furthest-along live stage, never an
        arbitrary first plant.
        """
        ec_ramp_curves = self.coordinator.services.config.ec_ramp_curves
        if not ec_ramp_curves:
            return None

        plants = self.coordinator.services.growspaces.get_growspace_plants(
            self._growspace_id
        )
        stage, _ = resolve_feed_stage_week(plants)
        if stage is None:
            return None

        return next(
            (curve for curve in ec_ramp_curves.values() if curve.stage == stage),
            None,
        )

    def _get_current_week(self) -> int:
        """Get the current week in the feed stage via the canonical ``days_to_week``.

        Resolved through the same seam as ``_get_active_curve`` so the week here
        matches ``Plant.get_week_in_stage`` and the growspace view model (which
        the prior inline ``(days // 7) + 1`` did not at 7-day boundaries).
        """
        plants = self.coordinator.services.growspaces.get_growspace_plants(
            self._growspace_id
        )
        _, week = resolve_feed_stage_week(plants)
        return week

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return current target EC midpoint."""
        curve = self._get_active_curve()
        if not curve or not curve.points:
            return None
        band = band_for_week(curve.points, self._get_current_week())
        if band is None:
            return None
        return round((band[0] + band[1]) / 2, 2)

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return EC target details."""
        curve = self._get_active_curve()
        if not curve:
            return {}

        week = self._get_current_week()
        band = band_for_week(curve.points, week) if curve.points else None
        ec_min, ec_max = band if band is not None else (None, None)

        return {
            "ec_min": ec_min,
            "ec_max": ec_max,
            "current_week": week,
            "stage": curve.stage,
            "curve_name": curve.name,
        }
