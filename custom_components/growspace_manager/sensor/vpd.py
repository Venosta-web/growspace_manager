"""VPD sensor classes for Growspace Manager."""

from __future__ import annotations

from typing import Any, override

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import GrowspaceType
from custom_components.growspace_manager.utils import (
    VPDCalculator,
    generate_subarea_vpd_sensor_unique_id,
    generate_vpd_sensor_unique_id,
)
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.core import Event
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event


class BaseVpdSensor(SensorEntity):  # type: ignore[misc]
    """Base class for VPD sensors providing common functionality."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kPa"

    @override  # type: ignore[misc]
    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        if self.entities_to_track:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, self.entities_to_track, self._handle_source_update
                )
            )

    async def _handle_source_update(self, event: Event) -> None:
        """Handle updates from source sensors."""
        self.async_write_ha_state()

    @property
    def entities_to_track(self) -> list[str]:
        """Return a list of entity IDs to track."""
        raise NotImplementedError

    def _get_float_state(self, entity_id: str | None) -> float | None:
        """Helper to safely get float state of an entity."""
        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if state and state.state not in ["unknown", "unavailable"]:
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return None


class VpdSensor(BaseVpdSensor):
    """A sensor that calculates Vapor Pressure Deficit (VPD).

    This sensor can calculate VPD from either a weather entity (for outside
    conditions) or a pair of temperature and humidity sensors (for indoor
    spaces like a lung room).
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        location_id: str,
        name: str,
        weather_entity: str | None,
        temp_sensor: str | None,
        humidity_sensor: str | None,
    ) -> None:
        """Initialize the VPD sensor."""
        self._coordinator = coordinator
        self._location_id = location_id
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{location_id}_vpd"
        self._weather_entity = weather_entity
        self._temp_sensor = temp_sensor
        self._humidity_sensor = humidity_sensor
        self._attr_translation_key = "vpd"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "service")},
            name="Growspace Manager Service",
            model="Service",
            manufacturer="Growspace Manager",
        )

    @property
    @override
    def entities_to_track(self) -> list[str]:
        """Return a list of entity IDs to track."""
        tracking = []
        if self._weather_entity:
            tracking.append(self._weather_entity)
        if self._temp_sensor:
            tracking.append(self._temp_sensor)
        if self._humidity_sensor:
            tracking.append(self._humidity_sensor)
        return tracking

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return the calculated VPD value in kPa."""
        temp = None
        humidity = None

        if self._weather_entity:
            weather_state = self.hass.states.get(self._weather_entity)
            if weather_state and weather_state.attributes:
                temp = weather_state.attributes.get("temperature")
                humidity = weather_state.attributes.get("humidity")
        elif self._temp_sensor and self._humidity_sensor:
            temp = self._get_float_state(self._temp_sensor)
            humidity = self._get_float_state(self._humidity_sensor)

        if temp is not None and humidity is not None:
            return VPDCalculator.calculate_vpd(temp, humidity)
        return None


class CalculatedVpdSensor(BaseVpdSensor):
    """A sensor that calculates VPD from temperature and humidity with LST offset.

    This sensor is automatically created when a growspace has temperature and
    humidity sensors configured but no physical VPD sensor. It uses the configured
    LST (Leaf Surface Temperature) offset to calculate VPD more accurately.
    """

    _attr_has_entity_name = True

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
        temp_sensor: str,
        humidity_sensor: str,
        lst_offset: float = -2.0,
        index: int | None = None,
    ) -> None:
        """Initialize the calculated VPD sensor."""
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        suffix = f" {index + 1}" if index is not None else ""
        self._attr_name = f"Calculated VPD{suffix}"
        self._attr_unique_id = generate_vpd_sensor_unique_id(growspace_id, index)
        self._temp_sensor = temp_sensor
        self._humidity_sensor = humidity_sensor
        self._lst_offset = lst_offset
        self._index = index
        self._attr_translation_key = "calculated_vpd"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override
    def entities_to_track(self) -> list[str]:
        """Return a list of entity IDs to track."""
        return [self._temp_sensor, self._humidity_sensor]

    @property
    def _active_lst_offset(self) -> float:
        """Return the active LST offset, considering the growspace type."""
        lst_offset = self._lst_offset
        growspace = self._coordinator.growspaces.get(self._growspace_id)
        if growspace and growspace.growspace_type in (
            GrowspaceType.DRY,
            GrowspaceType.CURE,
        ):
            lst_offset = 0.0
        return lst_offset

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return the calculated VPD value in kPa."""
        temp = self._get_float_state(self._temp_sensor)
        humidity = self._get_float_state(self._humidity_sensor)

        if temp is not None and humidity is not None:
            return VPDCalculator.calculate_vpd_with_lst_offset(
                temp, humidity, self._active_lst_offset
            )
        return None

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "temperature_sensor": self._temp_sensor,
            "humidity_sensor": self._humidity_sensor,
            "lst_offset": self._active_lst_offset,
            "configured_lst_offset": self._lst_offset,
            "calculation_method": "Calculated from temperature and humidity",
        }


class SubareaCalculatedVpdSensor(CalculatedVpdSensor):
    """A VPD sensor calculated from a subarea's temperature and humidity sensors."""

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
        subarea_id: str,
        subarea_name: str,
        temp_sensor: str,
        humidity_sensor: str,
        lst_offset: float = 0.0,
        index: int | None = None,
    ) -> None:
        """Initialize the subarea calculated VPD sensor."""
        super().__init__(
            coordinator,
            growspace_id,
            growspace_name,
            temp_sensor,
            humidity_sensor,
            lst_offset,
            index,
        )
        suffix = f" {index + 1}" if index is not None else ""
        self._attr_name = f"{subarea_name} Calculated VPD{suffix}"
        self._attr_unique_id = generate_subarea_vpd_sensor_unique_id(
            growspace_id, subarea_id, index
        )
        self._subarea_id = subarea_id
        self._subarea_name = subarea_name
