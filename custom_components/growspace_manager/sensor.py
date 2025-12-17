"""Sensor platform for Growspace Manager.

This file defines the main sensor entities for the Growspace Manager integration,
including sensors for individual plants, growspace overviews, the strain library,
and environmental calculations like VPD.
"""

from __future__ import annotations

# Standard library
import logging
from typing import Any, override

# Third-party / external
# Home Assistant
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    ATTR_COL,
    ATTR_GROWSPACE_ID,
    ATTR_PHENOTYPE,
    ATTR_PLANT_ID,
    ATTR_ROW,
    ATTR_STAGE,
    ATTR_STRAIN,
    CONF_HUMIDITY_SENSOR,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    DOMAIN,
    METRIC_HUMIDITY,
    METRIC_TEMPERATURE,
    METRIC_VPD,
    PLANT_STAGES,
)

# Local / relative imports
from .coordinator import GrowspaceCoordinator
from .helpers import async_setup_statistics_sensor, async_setup_trend_sensor
from .models import Growspace, Plant
from .utils import (
    VPDCalculator,
    calculate_plant_stage,
    generate_growspace_overview_unique_id,
    generate_vpd_sensor_unique_id,
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
    if not growspace.environment_config:
        return

    created_entity_ids = config_entry.runtime_data.created_entity_ids

    async def _create_and_track(sensor_cls_setup, platform, domain, s_type, s_source):
        unique_id = await sensor_cls_setup(
            hass, s_source, growspace.id, growspace.name, s_type
        )
        if unique_id:
            entity_key = (platform, domain, unique_id)
            if entity_key not in created_entity_ids:
                created_entity_ids.append(entity_key)

    metric_map = {
        METRIC_TEMPERATURE: CONF_TEMP_SENSOR,
        METRIC_HUMIDITY: CONF_HUMIDITY_SENSOR,
        METRIC_VPD: CONF_VPD_SENSOR,
    }

    for sensor_type, conf_key in metric_map.items():
        # Support both dict (legacy/mock) and dataclass
        if isinstance(growspace.environment_config, dict):
            source_sensor = growspace.environment_config.get(conf_key)
        else:
            source_sensor = getattr(growspace.environment_config, conf_key, None)

        if not source_sensor:
            continue

        await _create_and_track(
            async_setup_trend_sensor,
            "binary_sensor",
            "trend",
            sensor_type,
            source_sensor,
        )
        await _create_and_track(
            async_setup_statistics_sensor,
            "sensor",
            "statistics",
            sensor_type,
            source_sensor,
        )


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the Growspace Manager sensor platform from a config entry."""
    coordinator = config_entry.runtime_data

    # Track created entities so we can add/remove dynamically
    growspace_entities: dict[str, GrowspaceOverviewSensor] = {}
    plant_entities: dict[str, PlantEntity] = {}
    initial_entities: list[Entity] = []

    calculated_vpd_growspace_ids: set[str] = set()

    # Create initial entities
    await _create_initial_entities(
        hass,
        coordinator,
        config_entry,
        initial_entities,
        growspace_entities,
        plant_entities,
        calculated_vpd_growspace_ids,
    )

    if initial_entities:
        async_add_entities(initial_entities)
        _LOGGER.debug(
            "Added %d initial entities (growspaces/plants/strain library)",
            len(initial_entities),
        )

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
            hass,
            coordinator,
            config_entry,
            growspace_entities,
            async_add_entities,
            calculated_vpd_growspace_ids,
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
    calculated_vpd_growspace_ids: set[str],
) -> None:
    """Create initial entities for the platform."""
    # Strain Library
    initial_entities.append(StrainLibrarySensor(coordinator))

    # Growspaces and Plants
    for growspace_id, growspace in coordinator.growspaces.items():
        gs_entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
        growspace_entities[growspace_id] = gs_entity
        initial_entities.append(gs_entity)

        vpd_entity = _check_calculated_vpd_sensor(coordinator, growspace)
        if vpd_entity:
            initial_entities.append(vpd_entity)
            calculated_vpd_growspace_ids.add(growspace_id)

        await _async_create_derivative_sensors(hass, config_entry, growspace)

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
    calculated_vpd_growspace_ids: set[str],
) -> None:
    """Update growspace entities based on coordinator data."""
    # Add new
    for growspace_id, growspace in coordinator.growspaces.items():
        # New Growspace Entity
        if growspace_id not in growspace_entities:
            entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
            growspace_entities[growspace_id] = entity
            async_add_entities([entity])

        # Check for new derivative/calculated sensors for ALL growspaces
        await _async_create_derivative_sensors(hass, config_entry, growspace)

        if growspace_id not in calculated_vpd_growspace_ids:
            vpd_entity = _check_calculated_vpd_sensor(coordinator, growspace)
            if vpd_entity:
                async_add_entities([vpd_entity])
                calculated_vpd_growspace_ids.add(growspace_id)
                # Request a refresh so the coordinator can use the newly created sensor data
                # for its derived calculations (mold risk, etc.)
                hass.async_create_task(coordinator.async_request_refresh())

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


def _check_calculated_vpd_sensor(
    coordinator: GrowspaceCoordinator,
    growspace: Growspace,
) -> CalculatedVpdSensor | None:
    """Create calculated VPD sensor if needed."""
    env_config = growspace.environment_config
    if not env_config:
        return None

    def get_val(key):
        if isinstance(env_config, dict):
            return env_config.get(key)
        return getattr(env_config, key, None)

    temp_sensor = get_val(CONF_TEMP_SENSOR)
    humidity_sensor = get_val(CONF_HUMIDITY_SENSOR)
    vpd_sensor = get_val(CONF_VPD_SENSOR)

    # Create calculated VPD if temp and humidity exist but no VPD sensor
    # OR if the configured sensor appears to be one we generated (contains calculated_vpd)
    should_create = False
    if temp_sensor and humidity_sensor:
        if not vpd_sensor:
            should_create = True
        elif "calculated_vpd" in vpd_sensor:
            should_create = True

    if should_create:
        lst_offset = get_val("lst_offset")
        if lst_offset is None:
            lst_offset = -2.0
        calc_vpd_sensor = CalculatedVpdSensor(
            coordinator,
            growspace.id,
            growspace.name,
            temp_sensor,
            humidity_sensor,
            lst_offset,
        )

        return calc_vpd_sensor
    return None


class BaseVpdSensor(SensorEntity):
    """Base class for VPD sensors providing common functionality."""

    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "kPa"

    @override
    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        if self.entities_to_track:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, self.entities_to_track, self._handle_source_update
                )
            )

    async def _handle_source_update(self, event) -> None:
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
    @override
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

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace_name: str,
        temp_sensor: str,
        humidity_sensor: str,
        lst_offset: float = -2.0,
    ) -> None:
        """Initialize the calculated VPD sensor."""
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        self._attr_name = f"{growspace_name} Calculated VPD"
        self._attr_unique_id = generate_vpd_sensor_unique_id(growspace_id)
        self._temp_sensor = temp_sensor
        self._humidity_sensor = humidity_sensor
        self._lst_offset = lst_offset
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
    @override
    def native_value(self) -> float | None:
        """Return the calculated VPD value in kPa."""
        temp = self._get_float_state(self._temp_sensor)
        humidity = self._get_float_state(self._humidity_sensor)

        if temp is not None and humidity is not None:
            return VPDCalculator.calculate_vpd_with_lst_offset(
                temp, humidity, self._lst_offset
            )
        return None

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            CONF_TEMP_SENSOR: self._temp_sensor,
            CONF_HUMIDITY_SENSOR: self._humidity_sensor,
            "lst_offset": self._lst_offset,
            "calculation_method": "Calculated from temperature and humidity",
        }


class AirExchangeSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """A sensor that provides an air exchange recommendation for a growspace.

    This sensor's state reflects the recommended action (e.g., 'Open Window',
    'Ventilate Lung Room', 'Idle') calculated by the coordinator to help
    alleviate environmental stress.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "air_exchange"
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator: GrowspaceCoordinator, growspace_id: str) -> None:
        """Initialize the air exchange sensor.

        Args:
            coordinator: The data update coordinator.
            growspace_id: The ID of the growspace this sensor belongs to.
        """
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
    @override
    def native_value(self) -> str:
        """Return the current recommended air exchange action."""
        # The actual state is calculated in the coordinator and stored.
        # This sensor just retrieves it.
        return self.coordinator.data.get("air_exchange_recommendations", {}).get(
            self.growspace_id, "Idle"
        )


class GrowspaceOverviewSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """A sensor that provides an overview of a single growspace.

    The state of this sensor is the number of plants in the growspace. Its
    attributes contain a wealth of information, including the grid layout,
    plant details, and overall stage progression, making it the primary
    entity for the companion Lovelace card.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "overview"
    _attr_native_unit_of_measurement = None

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
        # self._attr_name removed to rely on translation_key
        self._attr_unique_id = generate_growspace_overview_unique_id(growspace_id)

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override
    def native_value(self) -> int:
        """Return the number of plants in the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        return len(plants)

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the growspace."""
        # Fetch pre-calculated serialization from coordinator
        # This replaces all the heavy logic that was previously here
        if not self.coordinator.data:
            return {}

        serialized = self.coordinator.data.get("serialized_growspaces", {}).get(
            self.growspace_id, {}
        )
        # Create a copy to avoid modifying the original data
        attributes = serialized.copy()

        # Remove large data structures
        attributes.pop("grid", None)
        attributes.pop("plants", None)

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
        self._attr_translation_key = "plant"
        self._attr_native_unit_of_measurement = None

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
    @override
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
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the plant."""
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return {}

        stage = calculate_plant_stage(plant)
        attributes = {
            ATTR_STAGE: stage,
            ATTR_GROWSPACE_ID: plant.growspace_id,
            ATTR_PLANT_ID: plant.plant_id,
            ATTR_STRAIN: plant.strain,
            ATTR_PHENOTYPE: plant.phenotype,
            ATTR_ROW: plant.row,
            ATTR_COL: plant.col,
            "position": f"({int(plant.row)},{int(plant.col)})",
        }

        # Dynamic Stage Attributes
        for stage_name in PLANT_STAGES:
            # Start dates
            start_key = f"{stage_name}_start"
            if hasattr(plant, start_key):
                attributes[start_key] = getattr(plant, start_key)

            # Days in stage
            attributes[f"{stage_name}_days"] = plant.get_days_in_stage(stage_name)

        # Calculate weeks using domain logic
        attributes["veg_week"] = plant.get_week_in_stage("veg")
        attributes["flower_week"] = plant.get_week_in_stage("flower")

        return attributes

    @override
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

    _attr_has_entity_name = True
    _attr_translation_key = "strain_library"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the Strain Library sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{DOMAIN}_strain_library"

    @property
    @override
    def native_value(self) -> int:
        """Return the number of unique strains in the library."""
        return len(self.coordinator.strain_library.get_all())

    @property
    @override
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the calculated strain analytics as state attributes."""
        # Use the cached analytics from StrainLibrary to avoid heavy computation on the main loop.
        return self.coordinator.strain_library.get_analytics()


class GrowspaceListSensor(SensorEntity):
    """A sensor that exposes the list of all configured growspaces.

    The state of this sensor is the total number of growspaces. Its attributes
    contain a dictionary mapping growspace IDs to their names, which is useful
    """

    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_native_unit_of_measurement = None

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the growspace list sensor."""
        self.coordinator = coordinator
        self._attr_name = "Growspaces List"
        self._attr_unique_id = f"{DOMAIN}_growspaces_list"
        self._attr_translation_key = "growspaces_list"
        self._update_growspaces()

    def _update_growspaces(self):
        """Update the internal list of growspaces from the coordinator."""
        self._growspaces = self.coordinator.get_growspace_options()

    @property
    @override
    def native_value(self):
        """Return the total number of growspaces."""
        self._update_growspaces()
        return len(self._growspaces)

    @property
    @override
    def extra_state_attributes(self):
        """Return the list of growspaces as a state attribute."""
        return {"growspaces": self._growspaces}
