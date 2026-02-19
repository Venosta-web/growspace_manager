"""Sensor platform for Growspace Manager.

This file defines the main sensor entities for the Growspace Manager integration,
including sensors for individual plants, growspace overviews, the strain library,
and environmental calculations like VPD.
"""

from __future__ import annotations

# Standard library
import asyncio
from datetime import datetime
import logging
from typing import Any, override

# Home Assistant
from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory, UnitOfTime
from homeassistant.core import Event, HomeAssistant
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
from .tank_depletion_predictor import TankDepletionPredictor
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
) -> None:
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

    async def _create_and_track(
        sensor_cls_setup: Any,
        platform: str,
        domain: str,
        s_type: str,
        s_source: str,
        display_name: str | None = None,
    ) -> None:
        unique_id = await sensor_cls_setup(
            hass, s_source, growspace.id, display_name or growspace.name, s_type
        )
        if unique_id:
            entity_key = (platform, domain, unique_id)
            if entity_key not in created_entity_ids:
                created_entity_ids.append(entity_key)

    metric_map = {
        METRIC_TEMPERATURE: ("temperature_sensor", "temperature_sensors"),
        METRIC_HUMIDITY: ("humidity_sensor", "humidity_sensors"),
        METRIC_VPD: ("vpd_sensor", "vpd_sensors"),
    }

    # Helper to safely get from dataclass or dict
    def get_val(key: str, default: Any = None) -> Any:
        if isinstance(growspace.environment_config, dict):
            return growspace.environment_config.get(key, default)
        return getattr(growspace.environment_config, key, default)

    for sensor_type, (singular_key, plural_key) in metric_map.items():
        # Get all sensors for this metric
        sensors = list(get_val(plural_key, []))
        singular_val = get_val(singular_key)
        if singular_val and singular_val not in sensors:
            sensors.insert(0, singular_val)

        for i, source_sensor in enumerate(sensors):
            if not source_sensor:
                continue

            # Add index suffix if there are multiple sensors of the same type
            suffix = f" {i + 1}" if len(sensors) > 1 else ""
            display_name = f"{growspace.name}{suffix}"

            await _create_and_track(
                async_setup_trend_sensor,
                "binary_sensor",
                "trend",
                sensor_type,
                source_sensor,
                display_name=display_name,
            )
            await _create_and_track(
                async_setup_statistics_sensor,
                "sensor",
                "statistics",
                sensor_type,
                source_sensor,
                display_name=display_name,
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

    # Lock to prevent race conditions during dynamic entity updates
    update_lock = asyncio.Lock()

    async def _handle_coordinator_update_async() -> None:
        """Add new entities and remove missing ones when coordinator changes."""
        async with update_lock:
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

        vpd_entities = _check_calculated_vpd_sensor(coordinator, growspace)
        for vpd_entity in vpd_entities:
            initial_entities.append(vpd_entity)
            calculated_vpd_growspace_ids.add(vpd_entity.unique_id)

        # Create tank depletion sensors if environment config has tanks
        if growspace.environment_config:
            env_config = growspace.environment_config

            # Safely get irrigation_tanks (handle both dict and dataclass)
            irrigation_tanks = []
            if isinstance(env_config, dict):
                irrigation_tanks = env_config.get("irrigation_tanks", [])
            elif hasattr(env_config, "irrigation_tanks"):
                irrigation_tanks = env_config.irrigation_tanks or []

            for tank in irrigation_tanks:
                # Check if prediction is enabled
                enable_prediction = True
                if isinstance(tank, dict):
                    enable_prediction = tank.get("enable_prediction", True)
                elif hasattr(tank, "enable_prediction"):
                    enable_prediction = tank.enable_prediction

                if enable_prediction:
                    # Convert dict to IrrigationTank if needed
                    from .models import IrrigationTank

                    tank_obj = (
                        IrrigationTank.from_dict(tank)
                        if isinstance(tank, dict)
                        else tank
                    )

                    # Only pass environment_config if it's a dataclass
                    env_cfg_for_predictor = (
                        None if isinstance(env_config, dict) else env_config
                    )

                    predictor = TankDepletionPredictor(
                        hass,
                        tank_obj,
                        environment_config=env_cfg_for_predictor,
                    )

                    tank_name = (
                        tank.get("name", "Tank")
                        if isinstance(tank, dict)
                        else tank.name
                    )

                    sensor = TankDepletionSensor(
                        coordinator,
                        growspace_id,
                        tank_name,
                        predictor,
                    )
                    initial_entities.append(sensor)
                    # Perform initial update
                    await predictor.async_update()

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

        vpd_entities = _check_calculated_vpd_sensor(coordinator, growspace)
        new_calculated_vpds = [
            v for v in vpd_entities if v.unique_id not in calculated_vpd_growspace_ids
        ]
        if new_calculated_vpds:
            async_add_entities(new_calculated_vpds)
            for v in new_calculated_vpds:
                calculated_vpd_growspace_ids.add(v.unique_id)
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
) -> list[CalculatedVpdSensor]:
    """Create calculated VPD sensors if needed."""
    env_config = growspace.environment_config
    if not env_config:
        return []

    # Helper to safely get from dataclass or dict
    def get_val(key: str, default: Any = None) -> Any:
        if isinstance(env_config, dict):
            return env_config.get(key, default)
        return getattr(env_config, key, default)

    # Ensure we are working with the plural lists
    temp_sensors = get_val("temperature_sensors", [])
    hum_sensors = get_val("humidity_sensors", [])
    vpd_sensors = get_val("vpd_sensors", [])

    # If lists are empty, fallback to singular fields
    if not temp_sensors and (ts := get_val("temperature_sensor")):
        temp_sensors = [ts]
    if not hum_sensors and (hs := get_val("humidity_sensor")):
        hum_sensors = [hs]
    if not vpd_sensors and (vs := get_val("vpd_sensor")):
        vpd_sensors = [vs]

    entities: list[CalculatedVpdSensor] = []

    # We create a calculated VPD for each T/H pair that lacks a dedicated VPD sensor
    # or where the dedicated VPD sensor is one of our previous 'calculated' ones.
    num_pairs = min(len(temp_sensors), len(hum_sensors))

    lst_offset = get_val("lst_offset", 0.0)

    for i in range(num_pairs):
        t_sensor = temp_sensors[i]
        h_sensor = hum_sensors[i]

        # Check if we already have a VPD sensor at this position
        existing_vpd = vpd_sensors[i] if i < len(vpd_sensors) else None

        should_create = False
        if t_sensor and h_sensor:
            if not existing_vpd or "calculated_vpd" in existing_vpd:
                should_create = True

        if should_create:
            index = i if num_pairs > 1 else None
            entities.append(
                CalculatedVpdSensor(
                    coordinator,
                    growspace.id,
                    growspace.name,
                    t_sensor,
                    h_sensor,
                    lst_offset,
                    index=index,
                )
            )

    return entities


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


class TankDepletionSensor(CoordinatorEntity, SensorEntity):
    """Sensor predicting time until tank needs refill.

    Uses sliding window linear regression to predict when an irrigation tank
    will reach its warning level based on historical depletion patterns.
    """

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.HOURS
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-alert"

    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        tank_name: str,
        predictor: Any,  # TankDepletionPredictor
    ) -> None:
        """Initialize the tank depletion sensor.

        Args:
            coordinator: Growspace coordinator instance
            growspace_id: ID of the growspace containing this tank
            tank_name: Name of the tank
            predictor: TankDepletionPredictor instance
        """
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._tank_name = tank_name
        self._predictor = predictor
        self._attr_name = f"{growspace_id} Tank Depletion {tank_name}"
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_tank_depletion_{tank_name}"

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
        self.hass.async_create_task(self._predictor.async_update())
        super()._handle_coordinator_update()


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
        index: int | None = None,
    ) -> None:
        """Initialize the calculated VPD sensor."""
        self._coordinator = coordinator
        self._growspace_id = growspace_id
        suffix = f" {index + 1}" if index is not None else ""
        self._attr_name = f"{growspace_name} Calculated VPD{suffix}"
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
    @override  # type: ignore[misc]
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
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        return {
            "temperature_sensor": self._temp_sensor,
            "humidity_sensor": self._humidity_sensor,
            "lst_offset": self._lst_offset,
            "calculation_method": "Calculated from temperature and humidity",
        }


class AirExchangeSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
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
    @override  # type: ignore[misc]
    def native_value(self) -> str:
        """Return the current recommended air exchange action."""
        # The actual state is calculated in the coordinator and stored.
        # This sensor just retrieves it.
        return self.coordinator.data.get("air_exchange_recommendations", {}).get(  # type: ignore[no-any-return]
            self.growspace_id, "Idle"
        )


class GrowspaceOverviewSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """A sensor that provides an overview of a single growspace.

    The state of this sensor is the number of plants in the growspace. Its
    attributes contain a wealth of information, including the grid layout,
    plant details, and overall stage progression, making it the primary
    entity for the companion Lovelace card.
    """

    _attr_has_entity_name = True
    _attr_translation_key = "overview"
    _attr_native_unit_of_measurement = None

    # Environment sensor attributes to track for real-time updates
    TRACKABLE_ENVIRONMENT_ATTRS: tuple[str, ...] = (
        "soil_moisture_sensor",
        "temperature_sensor",
        "humidity_sensor",
        "vpd_sensor",
        "dehumidifier_entities",
        "exhaust_fan_entities",
        "humidifier_entities",
        "circulation_fan_entities",
    )

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

    @override  # type: ignore[misc]
    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        await super().async_added_to_hass()

        # Track environment sensors for real-time updates
        entities_to_track = self._get_trackable_sensors()
        if entities_to_track:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass, entities_to_track, self._handle_sensor_update
                )
            )

    def _get_trackable_sensors(self) -> list[str]:
        """Return list of environment sensors to track for real-time updates."""
        growspace = self.coordinator.growspaces.get(self.growspace_id)
        if not growspace or not growspace.environment_config:
            return []

        env_config = growspace.environment_config
        sensors: list[str] = []

        # Add all configured sensors that have dynamic values we display
        for attr in self.TRACKABLE_ENVIRONMENT_ATTRS:
            if val := getattr(env_config, attr, None):
                if isinstance(val, list):
                    sensors.extend(val)
                elif isinstance(val, str):
                    sensors.append(val)

        return sensors

    async def _handle_sensor_update(self, event: Event) -> None:
        """Handle updates from tracked environment sensors."""
        # Use the public thread-safe method to refresh growspace data
        await self.coordinator.async_refresh_growspace_data(self.growspace_id)
        # Update our state
        self.async_write_ha_state()

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> int:
        """Return the number of plants in the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        return len(plants)

    @property
    @override  # type: ignore[misc]
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

        return attributes  # type: ignore[no-any-return]


class PlantEntity(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
    """A sensor representing a single plant in a growspace.

    The state of this sensor is the plant's current growth stage (e.g., 'veg',
    'flower'). Its attributes contain all other details about the plant, such as
    strain, position, and the duration of each growth stage.
    """

    def __init__(self, coordinator: GrowspaceCoordinator, plant: Plant) -> None:
        """Initialize the plant sensor entity.

        Args:
            coordinator: The data update coordinator.
            plant: The Plant data object.
        """
        super().__init__(coordinator)
        self._plant = plant
        self._attr_unique_id = f"{DOMAIN}_{plant.plant_id}"
        self._attr_name = f"{plant.strain} ({plant.row},{plant.col})"
        self._attr_translation_key = "plant"
        self._attr_native_unit_of_measurement = None

        # Set up device info - plant belongs to growspace device
        growspace_id = plant.growspace_id
        growspace: Any = coordinator.growspaces.get(growspace_id, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=getattr(growspace, "name", growspace_id),
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]
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
    @override  # type: ignore[misc]
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

        # Watering attributes
        attributes["last_watered"] = plant.last_watered
        attributes["days_since_last_watering"] = plant.get_days_since_watering()

        return attributes

    @override  # type: ignore[misc]
    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        await super().async_added_to_hass()


class StrainLibrarySensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):  # type: ignore[misc]
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
        self._attr_translation_key = "strain_library"
        self._attr_entity_category = EntityCategory.DIAGNOSTIC
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "service")},
            name="Growspace Manager Service",
            model="Service",
            manufacturer="Growspace Manager",
        )

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> int:
        """Return the number of unique strains in the library."""
        return len(self.coordinator.strain_library.get_all())

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the calculated strain analytics as state attributes."""
        # Get the full data but only extract what is strictly necessary for basic HA usage
        # to avoid hitting the 16KB recorder limit.
        analytics = self.coordinator.strain_library.get_analytics()

        return {
            "strain_count": len(analytics.get("strains", {})),
            "strain_list": analytics.get("strain_list", []),
            "last_updated": datetime.now().isoformat(),
            "note": "Full analytics available via WebSocket API: growspace_manager/get_strain_library",
        }

    # Register common system sensors (Library, etc.)


class GrowspaceListSensor(SensorEntity):  # type: ignore[misc]
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
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, "service")},
            name="Growspace Manager Service",
            model="Service",
            manufacturer="Growspace Manager",
        )
        self._update_growspaces()

    def _update_growspaces(self) -> None:
        """Update the internal list of growspaces from the coordinator."""
        self._growspaces = {
            gs_id: getattr(gs, "name", gs_id)
            for gs_id, gs in self.coordinator.growspaces.items()
        }

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> int:
        """Return the total number of growspaces."""
        self._update_growspaces()
        return len(self._growspaces)

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, dict[str, Any]]:
        """Return the list of growspaces as a state attribute."""
        return {"growspaces": self._growspaces}
