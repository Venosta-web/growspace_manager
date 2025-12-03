"""Sensor platform for Growspace Manager.

This file defines the main sensor entities for the Growspace Manager integration,
including sensors for individual plants, growspace overviews, the strain library,
and environmental calculations like VPD.
"""

from __future__ import annotations

# Standard library
import logging
from typing import Any

# Third-party / external
# Home Assistant
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN

# Local / relative imports
from .coordinator import GrowspaceCoordinator
from .helpers import async_setup_statistics_sensor, async_setup_trend_sensor
from .models import Growspace, Plant
from .utils import (
    VPDCalculator,
    calculate_days_since,
    calculate_plant_stage,
    days_to_week,
)

_LOGGER = logging.getLogger(__name__)


async def _async_create_derivative_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    growspace: Growspace,
):
    """Create helper trend and statistics sensors for a growspace's environment.

    This function sets up `trend` and `statistics` helper entities for the
    primary environmental sensors (temperature, humidity, VPD) of a given
    growspace.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry.
        growspace: The Growspace object for which to create sensors.
    """
    if growspace.environment_config:
        created_entities = config_entry.runtime_data.created_entities
        for sensor_type in ["temperature", "humidity", "vpd"]:
            source_sensor = growspace.environment_config.get(f"{sensor_type}_sensor")
            if source_sensor:
                trend_unique_id = await async_setup_trend_sensor(
                    hass, source_sensor, growspace.id, growspace.name, sensor_type
                )
                if trend_unique_id and trend_unique_id not in created_entities:
                    created_entities.append(trend_unique_id)
                stats_unique_id = await async_setup_statistics_sensor(
                    hass, source_sensor, growspace.id, growspace.name, sensor_type
                )
                if stats_unique_id and stats_unique_id not in created_entities:
                    created_entities.append(stats_unique_id)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager sensor platform from a config entry."""
    coordinator = config_entry.runtime_data.coordinator

    # Track created entities so we can add/remove dynamically
    growspace_entities: dict[str, GrowspaceOverviewSensor] = {}
    plant_entities: dict[str, PlantEntity] = {}
    initial_entities: list[Entity] = []

    # Create initial entities
    await _create_initial_entities(
        hass,
        coordinator,
        config_entry,
        initial_entities,
        growspace_entities,
        plant_entities,
    )

    if initial_entities:
        async_add_entities(initial_entities)
        _LOGGER.debug(
            "Added %d initial entities (growspaces/plants/strain library)",
            len(initial_entities),
        )

    # Ensure dry and cure growspaces exist after coordinator setup
    await _ensure_special_growspaces(coordinator)

    # Create global VPD sensors
    global_entities = []
    global_settings = config_entry.options.get("global_settings", {})
    if global_settings:
        if global_settings.get("weather_entity"):
            global_entities.append(
                VpdSensor(
                    coordinator,
                    "outside",
                    "Outside VPD",
                    global_settings.get("weather_entity"),
                    None,
                    None,
                )
            )
        if global_settings.get("lung_room_temp_sensor") and global_settings.get(
            "lung_room_humidity_sensor"
        ):
            global_entities.append(
                VpdSensor(
                    coordinator,
                    "lung_room",
                    "Lung Room VPD",
                    None,
                    global_settings.get("lung_room_temp_sensor"),
                    global_settings.get("lung_room_humidity_sensor"),
                )
            )
    if global_entities:
        async_add_entities(global_entities)

    # Add AirExchange recommendation sensors for each growspace
    air_exchange_sensors = [
        AirExchangeSensor(coordinator, growspace_id)
        for growspace_id in coordinator.growspaces
    ]
    async_add_entities(air_exchange_sensors)

    async def _handle_coordinator_update_async() -> None:
        """Add new entities and remove missing ones when coordinator changes."""
        await _update_growspace_entities(
            hass, coordinator, config_entry, growspace_entities, async_add_entities
        )
        await _update_plant_entities(
            hass, coordinator, plant_entities, async_add_entities
        )

    def _listener_callback() -> None:
        """Handle coordinator updates."""
        hass.async_create_task(_handle_coordinator_update_async())

    config_entry.async_on_unload(coordinator.async_add_listener(_listener_callback))


async def _create_initial_entities(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    config_entry: ConfigEntry,
    initial_entities: list[Entity],
    growspace_entities: dict[str, GrowspaceOverviewSensor],
    plant_entities: dict[str, PlantEntity],
) -> None:
    """Create initial entities for the platform."""
    # Strain Library
    initial_entities.append(StrainLibrarySensor(coordinator))

    # Growspaces and Plants
    for growspace_id, growspace in coordinator.growspaces.items():
        gs_entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
        growspace_entities[growspace_id] = gs_entity
        initial_entities.append(gs_entity)

        await _async_create_derivative_sensors(hass, config_entry, growspace)
        _handle_calculated_vpd_sensor(coordinator, growspace, initial_entities)

        for plant in coordinator.get_growspace_plants(growspace_id):
            pe = PlantEntity(coordinator, plant)
            plant_entities[plant.plant_id] = pe
            initial_entities.append(pe)

    # Growspace List
    initial_entities.append(GrowspaceListSensor(coordinator))


async def _update_growspace_entities(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    config_entry: ConfigEntry,
    growspace_entities: dict[str, GrowspaceOverviewSensor],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Update growspace entities based on coordinator data."""
    # Add new
    for growspace_id, growspace in coordinator.growspaces.items():
        if growspace_id not in growspace_entities:
            entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
            growspace_entities[growspace_id] = entity
            async_add_entities([entity])
            await _async_create_derivative_sensors(hass, config_entry, growspace)

    # Remove deleted
    for removed_gs_id in list(growspace_entities.keys()):
        if removed_gs_id not in coordinator.growspaces:
            entity = growspace_entities.pop(removed_gs_id)
            if entity.registry_entry:
                er.async_get(hass).async_remove(entity.registry_entry.entity_id)
            await entity.async_remove()


async def _update_plant_entities(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    plant_entities: dict[str, PlantEntity],
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Update plant entities based on coordinator data."""
    # Add new
    new_entities = []
    for plant_id, plant in coordinator.plants.items():
        if plant_id not in plant_entities:
            pe = PlantEntity(coordinator, plant)
            plant_entities[plant_id] = pe
            new_entities.append(pe)

    if new_entities:
        async_add_entities(new_entities)

    # Remove deleted
    entity_registry = er.async_get(hass)
    removed_plant_ids = set(plant_entities.keys()) - set(coordinator.plants.keys())
    for pid in removed_plant_ids:
        entity = plant_entities.pop(pid)
        if entity.registry_entry:
            entity_registry.async_remove(entity.registry_entry.entity_id)
        await entity.async_remove()


def _handle_calculated_vpd_sensor(
    coordinator: GrowspaceCoordinator,
    growspace: Growspace,
    initial_entities: list[Entity],
) -> None:
    """Create calculated VPD sensor if needed."""
    env_config = growspace.environment_config or {}
    temp_sensor = env_config.get("temperature_sensor")
    humidity_sensor = env_config.get("humidity_sensor")
    vpd_sensor = env_config.get("vpd_sensor")

    # Create calculated VPD if temp and humidity exist but no VPD sensor
    if temp_sensor and humidity_sensor and not vpd_sensor:
        lst_offset = env_config.get("lst_offset", -2.0)
        calc_vpd_sensor = CalculatedVpdSensor(
            coordinator,
            growspace.id,
            growspace.name,
            temp_sensor,
            humidity_sensor,
            lst_offset,
        )
        initial_entities.append(calc_vpd_sensor)

        # Auto-populate the vpd_sensor in env_config with the calculated sensor
        env_config["vpd_sensor"] = f"sensor.{growspace.id}_calculated_vpd"
        growspace.environment_config = env_config

        _LOGGER.info(
            "Created calculated VPD sensor for %s (LST offset: %.1f°C)",
            growspace.name,
            lst_offset,
        )


async def _ensure_special_growspaces(coordinator: GrowspaceCoordinator) -> None:
    """Ensure special growspaces exist."""
    dry_id = coordinator._ensure_special_growspace(
        "dry", "dry", rows=3, plants_per_row=3
    )
    cure_id = coordinator._ensure_special_growspace(
        "cure", "cure", rows=3, plants_per_row=3
    )
    clone_id = coordinator._ensure_special_growspace(
        "clone", "clone", rows=3, plants_per_row=3
    )
    mother_id = coordinator._ensure_special_growspace(
        "mother", "mother", rows=3, plants_per_row=3
    )

    await coordinator.async_save()

    _LOGGER.info(
        "Ensured special growspaces exist: dry=%s, cure=%s clone=%s mother=%s",
        dry_id,
        cure_id,
        clone_id,
        mother_id,
    )


class VpdSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """A sensor that calculates Vapor Pressure Deficit (VPD).

    This sensor can calculate VPD from either a weather entity (for outside
    conditions) or a pair of temperature and humidity sensors (for indoor
    spaces like a lung room).
    """

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        location_id: str,
        name: str,
        weather_entity: str | None,
        temp_sensor: str | None,
        humidity_sensor: str | None,
    ) -> None:
        """Initialize the VPD sensor.

        Args:
            coordinator: The data update coordinator.
            location_id: A unique identifier for the location (e.g., 'outside').
            name: The display name for the sensor.
            weather_entity: The entity ID of a weather entity (optional).
            temp_sensor: The entity ID of a temperature sensor (optional).
            humidity_sensor: The entity ID of a humidity sensor (optional).
        """
        super().__init__(coordinator)
        self._location_id = location_id
        self._attr_name = name
        self._attr_unique_id = f"{DOMAIN}_{location_id}_vpd"
        self._weather_entity = weather_entity
        self._temp_sensor = temp_sensor
        self._humidity_sensor = humidity_sensor
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "kPa"
        self._attr_icon = "mdi:cloud-check-variant"

    @property
    def native_value(self) -> float | None:
        """Return the calculated VPD value in kPa."""
        hass = self.coordinator.hass
        temp = None
        humidity = None

        if self._weather_entity:
            weather_state = hass.states.get(self._weather_entity)
            if weather_state and weather_state.attributes:
                temp = weather_state.attributes.get("temperature")
                humidity = weather_state.attributes.get("humidity")
        elif self._temp_sensor and self._humidity_sensor:
            temp_state = hass.states.get(self._temp_sensor)
            if temp_state and temp_state.state not in ["unknown", "unavailable"]:
                try:
                    temp = float(temp_state.state)
                except (ValueError, TypeError):
                    temp = None
            humidity_state = hass.states.get(self._humidity_sensor)
            if humidity_state and humidity_state.state not in [
                "unknown",
                "unavailable",
            ]:
                try:
                    humidity = float(humidity_state.state)
                except (ValueError, TypeError):
                    humidity = None

        if temp is not None and humidity is not None:
            return VPDCalculator.calculate_vpd(temp, humidity)
        return None


class CalculatedVpdSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """A sensor that calculates VPD from temperature and humidity with LST offset.

    This sensor is automatically created when a growspace has temperature and
    humidity sensors configured but no physical VPD sensor. It uses the configured
    LST (Leaf Surface Temperature) offset to calculate VPD more accurately.
    """

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
        temp_sensor: str,
        humidity_sensor: str,
        lst_offset: float = -2.0,
    ) -> None:
        """Initialize the calculated VPD sensor.

        Args:
            coordinator: The data update coordinator.
            growspace_id: The ID of the growspace.
            growspace_name: The name of the growspace.
            temp_sensor: The entity ID of the temperature sensor.
            humidity_sensor: The entity ID of the humidity sensor.
            lst_offset: The leaf surface temperature offset in °C (default: -2.0).
        """
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_name = f"{growspace_name} Calculated VPD"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_calculated_vpd"
        self._temp_sensor = temp_sensor
        self._humidity_sensor = humidity_sensor
        self._lst_offset = lst_offset
        self._attr_state_class = SensorStateClass.MEASUREMENT
        self._attr_native_unit_of_measurement = "kPa"
        self._attr_icon = "mdi:cloud-percent"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace_name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def native_value(self) -> float | None:
        """Return the calculated VPD value in kPa."""
        hass = self.coordinator.hass
        temp = None
        humidity = None

        temp_state = hass.states.get(self._temp_sensor)
        if temp_state and temp_state.state not in ["unknown", "unavailable"]:
            try:
                temp = float(temp_state.state)
            except (ValueError, TypeError):
                temp = None

        humidity_state = hass.states.get(self._humidity_sensor)
        if humidity_state and humidity_state.state not in ["unknown", "unavailable"]:
            try:
                humidity = float(humidity_state.state)
            except (ValueError, TypeError):
                humidity = None

        if temp is not None and humidity is not None:
            return VPDCalculator.calculate_vpd_with_lst_offset(
                temp, humidity, self._lst_offset
            )
        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "temperature_sensor": self._temp_sensor,
            "humidity_sensor": self._humidity_sensor,
            "lst_offset": self._lst_offset,
            "calculation_method": "Calculated from temperature and humidity",
        }


class AirExchangeSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """A sensor that provides an air exchange recommendation for a growspace.

    This sensor's state reflects the recommended action (e.g., 'Open Window',
    'Ventilate Lung Room', 'Idle') calculated by the coordinator to help
    alleviate environmental stress.
    """

    def __init__(self, coordinator: GrowspaceCoordinator, growspace_id: str) -> None:
        """Initialize the air exchange sensor.

        Args:
            coordinator: The data update coordinator.
            growspace_id: The ID of the growspace this sensor belongs to.
        """
        super().__init__(coordinator)
        self.growspace_id = growspace_id
        self.growspace = coordinator.growspaces[growspace_id]
        self._attr_name = f"{self.growspace.name} Air Exchange"
        self._attr_unique_id = f"{DOMAIN}_{self.growspace_id}_air_exchange"
        self._attr_icon = "mdi:air-filter"

        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, self.growspace_id)},
            name=self.growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def native_value(self) -> str:
        """Return the current recommended air exchange action."""
        # The actual state is calculated in the coordinator and stored.
        # This sensor just retrieves it.
        recommendation = self.coordinator.data.get(
            "air_exchange_recommendations", {}
        ).get(self.growspace_id, "Idle")
        return recommendation


class GrowspaceOverviewSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """A sensor that provides an overview of a single growspace.

    The state of this sensor is the number of plants in the growspace. Its
    attributes contain a wealth of information, including the grid layout,
    plant details, and overall stage progression, making it the primary
    entity for the companion Lovelace card.
    """

    def __init__(
        self, coordinator: GrowspaceCoordinator, growspace_id: str, growspace: Growspace
    ) -> None:
        """Initialize the growspace overview sensor.

        Args:
            coordinator: The data update coordinator.
            growspace_id: The ID of the growspace.
            growspace: The Growspace data object.
        """
        super().__init__(coordinator)
        self.growspace_id = growspace_id
        # We don't store self.growspace anymore to ensure we always get the latest
        # object from the coordinator.
        self._attr_name = growspace.name
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}"

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def native_value(self) -> int:
        """Return the number of plants in the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        return len(plants)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the growspace."""
        # Always fetch the latest growspace object from the coordinator
        growspace = self.coordinator.growspaces[self.growspace_id]
        plants = self.coordinator.get_growspace_plants(self.growspace_id)

        # Calculate max stage days
        max_veg = max(
            (calculate_days_since(p.veg_start) for p in plants if p.veg_start),
            default=0,
        )
        max_flower = max(
            (calculate_days_since(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )

        # Calculate weeks from days
        veg_week = days_to_week(max_veg)
        flower_week = days_to_week(max_flower)

        # Get irrigation settings from growspace object
        irrigation_options = growspace.irrigation_config

        _LOGGER.debug(
            "GrowspaceOverviewSensor attributes update for %s. Irrigation items: %d",
            self.growspace_id,
            len(irrigation_options.get("irrigation_times", [])),
        )

        # Create grid representation
        grid: dict[str, dict[str, Any] | None] = {}
        for row in range(1, int(growspace.rows) + 1):
            for col in range(
                1,
                int(
                    growspace.plants_per_row,
                )
                + 1,
            ):
                grid[f"position_{row}_{col}"] = None

        # Fill grid with plants (include position inside grid entry)
        for plant in plants:
            row_i = int(plant.row)
            col_i = int(plant.col)
            position_key = f"position_{row_i}_{col_i}"
            grid[position_key] = {
                "plant_id": plant.plant_id,
                "strain": plant.strain,
                "phenotype": plant.phenotype,
                "veg_days": self.coordinator.calculate_days_in_stage(plant, "veg"),
                "flower_days": self.coordinator.calculate_days_in_stage(
                    plant, "flower"
                ),
                "row": row_i,
                "col": col_i,
                "position": f"({row_i},{col_i})",
            }

        # Build attributes dict
        attributes = {
            "growspace_id": growspace.id,
            "rows": growspace.rows,
            "plants_per_row": growspace.plants_per_row,
            "total_plants": len(plants),
            "notification_target": growspace.notification_target,
            "max_veg_days": max_veg,
            "max_flower_days": max_flower,
            "veg_week": veg_week,
            "flower_week": flower_week,
            "max_stage_summary": f"Veg: {max_veg}d (W{veg_week}), Flower: {max_flower}d (W{flower_week})",
            "irrigation_times": irrigation_options.get("irrigation_times", []),
            "drain_times": irrigation_options.get("drain_times", []),
            "grid": grid,
        }

        # Add dehumidifier state if configured
        if growspace.environment_config:
            env_config = growspace.environment_config

            # Dehumidifier
            dehumidifier_entity = env_config.get("dehumidifier_entity")
            if dehumidifier_entity:
                state_obj = self.coordinator.hass.states.get(dehumidifier_entity)
                attributes["dehumidifier_entity"] = dehumidifier_entity
                attributes["dehumidifier_state"] = (
                    state_obj.state if state_obj else None
                )
                if state_obj:
                    attributes["dehumidifier_humidity"] = state_obj.attributes.get(
                        "humidity"
                    )
                    attributes["dehumidifier_current_humidity"] = (
                        state_obj.attributes.get("current_humidity")
                    )
                    attributes["dehumidifier_mode"] = state_obj.attributes.get("mode")
                    attributes["dehumidifier_control_enabled"] = env_config.get(
                        "control_dehumidifier", False
                    )
            # Exhaust Sensor
            exhaust_entity = env_config.get("exhaust_sensor")
            if exhaust_entity:
                state_obj = self.coordinator.hass.states.get(exhaust_entity)
                attributes["exhaust_entity"] = exhaust_entity
                attributes["exhaust_value"] = state_obj.state if state_obj else None

            # Humidifier Sensor
            humidifier_entity = env_config.get("humidifier_sensor")
            if humidifier_entity:
                state_obj = self.coordinator.hass.states.get(humidifier_entity)
                attributes["humidifier_entity"] = humidifier_entity
                attributes["humidifier_value"] = state_obj.state if state_obj else None

        return attributes


class PlantEntity(SensorEntity):
    """A sensor representing a single plant in a growspace.

    The state of this sensor is the plant's current growth stage (e.g., 'veg',
    'flower'). Its attributes contain all other details about the plant, such as
    strain, position, and the duration of each growth stage.
    """

    def __init__(self, coordinator, plant: Plant) -> None:
        """Initialize the plant sensor entity.

        Args:
            coordinator: The data update coordinator.
            plant: The Plant data object.
        """
        self.coordinator = coordinator
        self._plant = plant
        self._attr_unique_id = f"{DOMAIN}_{plant.plant_id}"
        self._attr_name = f"{plant.strain} ({plant.row},{plant.col})"
        self._attr_icon = "mdi:cannabis"

        # Set up device info - plant belongs to growspace device
        growspace_id = plant.growspace_id
        growspace = coordinator.growspaces.get(growspace_id, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=getattr(growspace, "name", growspace_id),
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def native_value(self) -> str:
        """Return the current growth stage of the plant."""
        # Get updated plant data
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return "unknown"

        stage = calculate_plant_stage(plant)

        # Get growspace if needed
        self.coordinator.growspaces.get(plant.growspace_id)

        return stage

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the plant."""
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return {}

        stage = calculate_plant_stage(plant)
        seedling_days = self.coordinator.calculate_days_in_stage(plant, "seedling")
        mother_days = self.coordinator.calculate_days_in_stage(plant, "mother")
        clone_days = self.coordinator.calculate_days_in_stage(plant, "clone")
        veg_days = self.coordinator.calculate_days_in_stage(plant, "veg")
        flower_days = self.coordinator.calculate_days_in_stage(plant, "flower")
        dry_days = self.coordinator.calculate_days_in_stage(plant, "dry")
        cure_days = self.coordinator.calculate_days_in_stage(plant, "cure")

        # Calculate weeks
        veg_week = days_to_week(veg_days or 0)
        flower_week = days_to_week(flower_days or 0)

        return {
            "stage": stage,
            "growspace_id": plant.growspace_id,
            "plant_id": plant.plant_id,
            "strain": plant.strain,
            "phenotype": plant.phenotype,
            "row": plant.row,
            "col": plant.col,
            "position": f"({int(plant.row)},{int(plant.col)})",
            "seedling_start": plant.seedling_start,
            "mother_start": plant.mother_start,
            "clone_start": plant.clone_start,
            "veg_start": plant.veg_start,
            "flower_start": plant.flower_start,
            "dry_start": plant.dry_start,
            "cure_start": plant.cure_start,
            "seedling_days": seedling_days or 0,
            "mother_days": mother_days or 0,
            "clone_days": clone_days or 0,
            "veg_days": veg_days or 0,
            "flower_days": flower_days or 0,
            "dry_days": dry_days or 0,
            "cure_days": cure_days or 0,
            "veg_week": veg_week,
            "flower_week": flower_week,
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        self.coordinator.async_add_listener(self.async_write_ha_state)


class StrainLibrarySensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """A sensor that provides analytics from the user's strain library.

    The state of this sensor is the total number of unique strains (and
    phenotypes) that have been grown. Its attributes contain calculated
    analytics, such as the average veg and flower times for each strain,
    based on recorded harvest data.
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the Strain Library sensor."""
        super().__init__(coordinator)
        self._attr_name = "Growspace Strain Library"
        self._attr_unique_id = f"{DOMAIN}_strain_library"
        self._attr_icon = "mdi:leaf"

    @property
    def native_value(self) -> int:
        """Return the number of unique strains in the library."""
        return len(self.coordinator.strains.get_all())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the calculated strain analytics as state attributes."""
        # Use the cached analytics from StrainLibrary to avoid heavy computation on the main loop.
        return self.coordinator.strains.get_analytics()


class GrowspaceListSensor(SensorEntity):
    """A sensor that exposes the list of all configured growspaces.

    The state of this sensor is the total number of growspaces. Its attributes
    contain a dictionary mapping growspace IDs to their names, which is useful
    for populating dynamic dropdowns in the UI.
    """

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the growspace list sensor."""
        self.coordinator = coordinator
        self._attr_name = "Growspaces List"
        self._attr_unique_id = f"{DOMAIN}_growspaces_list"
        self._attr_icon = "mdi:home-group"
        self._update_growspaces()

    def _update_growspaces(self):
        """Update the internal list of growspaces from the coordinator."""
        self._growspaces = self.coordinator.get_growspace_options()

    @property
    def native_value(self):
        """Return the total number of growspaces."""
        self._update_growspaces()
        return len(self._growspaces)

    @property
    def extra_state_attributes(self):
        """Return the list of growspaces as a state attribute."""
        return {"growspaces": self._growspaces}
