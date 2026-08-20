"""Tank sensor classes for Growspace Manager."""

from __future__ import annotations

from typing import Any

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.tank_depletion_predictor import (
    TankDepletionPredictor,
)
from custom_components.growspace_manager.tank_water_tracker import TankWaterTracker
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfTime, UnitOfVolume
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity


class TankDepletionSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Sensor predicting time until tank needs refill.

    Uses sliding window linear regression to predict when an irrigation tank
    will reach its warning level based on historical depletion patterns.
    """

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-alert"
    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        tank_name: str,
        predictor: TankDepletionPredictor,
    ) -> None:
        """Initialize the tank depletion sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._tank_name = tank_name
        self._predictor = predictor
        self._attr_name = f"Tank Depletion {tank_name}"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_tank_depletion_{tank_name}"

        growspace = coordinator.growspaces.get(growspace_id)
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name if growspace else growspace_id,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def available(self) -> bool:
        """Return if sensor is available."""
        return self.coordinator.last_update_success

    @property
    def native_value(self) -> float | None:
        """Return hours remaining until refill threshold."""
        prediction = self._predictor.get_prediction()

        if prediction.status == "insufficient_data":
            return None

        if prediction.status in ("refilling", "static"):
            return None

        return prediction.hours_remaining

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return prediction details as attributes."""
        prediction = self._predictor.get_prediction()

        attributes = {
            "status": prediction.status,
            "data_points": prediction.data_points,
        }

        if prediction.slope_pct_per_hour is not None:
            attributes["slope_pct_per_hour"] = round(prediction.slope_pct_per_hour, 3)

        if prediction.daily_usage_rate is not None:
            attributes["daily_usage_rate"] = round(prediction.daily_usage_rate, 2)

        if prediction.active_consumption_rate is not None:
            attributes["active_consumption_rate"] = round(
                prediction.active_consumption_rate, 2
            )

        if prediction.dormant_consumption_rate is not None:
            attributes["dormant_consumption_rate"] = round(
                prediction.dormant_consumption_rate, 2
            )

        return attributes

    async def async_update(self) -> None:
        """Update the predictor buffer."""
        await self._predictor.async_update()

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates by refreshing predictor buffer."""
        self.coordinator.config_entry.async_create_background_task(
            self.hass,
            self._predictor.async_update(),
            f"update_predictor_{self.entity_id or self.unique_id}",
        )
        super()._handle_coordinator_update()


def _should_create_derived_water_sensor(
    growspace: Growspace,
    tank: Any,
) -> bool:
    """Return True only when tank-derived water inference should activate.

    This sensor is a fallback: it infers water consumption from tank level
    changes when no dedicated flow or drain volume sensors are configured.
    """
    env = growspace.environment_config
    return (
        tank.volume_liters is not None
        and not env.irrigation_flow_sensors
        and not env.drain_volume_sensors
    )


class TankDerivedWaterSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Sensor reporting water consumption inferred from tank level changes.

    Used as a fallback when no dedicated irrigation flow or drain volume
    sensors are present. Consumption is calculated from the difference
    in measured tank level readings over time, scaled by the tank volume.
    """

    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = UnitOfVolume.LITERS
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:water-pump"
    _attr_has_entity_name = True
    _attr_translation_key = "tank_derived_water"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        tank: Any,
    ) -> None:
        """Initialize the tank-derived water sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._tank = tank
        tank_slug = tank.sensor_entity.replace(".", "_").replace(" ", "_")
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_tank_derived_water_{tank_slug}"

    @property
    def _tracker(self) -> TankWaterTracker | None:
        """Return the TankWaterTracker for this tank, or None."""
        return self.coordinator.services.growspaces.get_tank_tracker(
            self._growspace_id, self._tank.sensor_entity
        )

    @property
    def available(self) -> bool:
        """Return True when coordinator is healthy and the tracker exists."""
        return self.coordinator.last_update_success and self._tracker is not None

    @property
    def native_value(self) -> float | None:
        """Return litres consumed today (rolling 24-hour window)."""
        if (tracker := self._tracker) is None:
            return None
        return round(tracker.get_total_liters_today(), 2)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return history and tank configuration as attributes."""
        if (tracker := self._tracker) is None:
            return {}
        return {
            "liters_today": round(tracker.get_total_liters_today(), 2),
            "liters_7d": round(tracker.get_total_liters_7d(), 2),
            "volume_liters": self._tank.volume_liters,
            "tank_entity": self._tank.sensor_entity,
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to tank sensor state changes via the tracker."""
        await super().async_added_to_hass()
        tracker = self.coordinator.services.growspaces.get_tank_tracker(
            self._growspace_id, self._tank.sensor_entity
        )
        if tracker is None:
            return

        def _on_change() -> None:
            self.schedule_update_ha_state()

        unsub = await tracker.async_setup(self.hass, _on_change)
        self.async_on_remove(unsub)
