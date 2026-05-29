"""Usage sensor classes for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from ..const import DOMAIN
from ..coordinator import GrowspaceCoordinator


class EnergyUsageSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor tracking electricity consumption per growspace."""

    _attr_has_entity_name = True
    _attr_translation_key = "energy_usage"
    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = "kWh"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
    ) -> None:
        """Initialize the energy usage sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_energy_usage"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    def _get_total_kwh(self) -> float:
        """Sum current kWh from configured energy sensors."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace or not growspace.environment_config:
            return 0.0
        total = 0.0
        for sensor_id in growspace.environment_config.energy_sensors:
            state = self.hass.states.get(sensor_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    total += float(state.state)
                except (ValueError, TypeError):
                    continue
        return total

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return total kWh for current grow cycle."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace:
            return None
        current_kwh = self._get_total_kwh()
        cycle_start = growspace.energy_tracking.cycle_start_kwh
        return round(max(0.0, current_kwh - cycle_start), 2)

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return energy details."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace:
            return {}
        cycle_kwh = self.native_value or 0.0
        cost_per_kwh = growspace.environment_config.electricity_cost_per_kwh
        return {
            "cost_total": round(cycle_kwh * cost_per_kwh, 2) if cost_per_kwh else None,
            "cycle_start_date": growspace.energy_tracking.cycle_start_date or None,
        }


class PowerUsageSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor tracking current power draw per growspace."""

    _attr_has_entity_name = True
    _attr_translation_key = "power_usage"
    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = "W"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
    ) -> None:
        """Initialize the power usage sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_power_usage"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]
    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return total current wattage across all configured power sensors."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace or not growspace.environment_config:
            return None
        total = 0.0
        any_valid = False
        for sensor_id in (growspace.environment_config.power_sensors or []):
            state = self.hass.states.get(sensor_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    total += float(state.state)
                    any_valid = True
                except (ValueError, TypeError):
                    continue
        return round(total, 1) if any_valid else None
class WaterUsageSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """Sensor tracking water consumption per growspace."""

    _attr_has_entity_name = True
    _attr_translation_key = "water_usage"
    _attr_device_class = SensorDeviceClass.WATER
    _attr_native_unit_of_measurement = "L"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_icon = "mdi:water-pump"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
    ) -> None:
        """Initialize the water usage sensor."""
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_water_usage"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return total liters used in current cycle."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace:
            return None
        return round(growspace.water_usage.total_liters, 2)

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return water usage details."""
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace:
            return {}

        usage = growspace.water_usage
        plant_count = len(self.coordinator.services.growspaces.get_growspace_plants(self._growspace_id))
        days = 1
        if usage.cycle_start_date:
            from datetime import date as date_cls  # noqa: PLC0415

            try:
                start = date_cls.fromisoformat(usage.cycle_start_date)
                days = max(1, (date_cls.today() - start).days)
            except (ValueError, TypeError):
                pass

        liters_per_plant = (
            round(usage.total_liters / plant_count / days, 2)
            if plant_count > 0
            else 0.0
        )

        today_str = dt_util.now().date().isoformat()
        liters_today = 0.0
        for reading in usage.daily_readings:
            if reading.get("date") == today_str:
                liters_today = reading.get("liters", 0.0)
                break

        return {
            "liters_per_plant_per_day": liters_per_plant,
            "liters_today": round(liters_today, 2),
            "cycle_start_date": usage.cycle_start_date or None,
        }
