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
from homeassistant.const import EntityCategory, UnitOfTime, UnitOfVolume
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
    DEFAULT_DLI_TARGET_FLOWER,
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
                    from .models import IrrigationTank  # noqa: PLC0415

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

        # DLI sensor - only if light sensors configured
        if growspace.environment_config and growspace.environment_config.light_sensors:
            initial_entities.append(
                DLISensor(coordinator, growspace_id, growspace.name)
            )

        # Crop steering sensor - only if VWC strategy is enabled
        if growspace.irrigation_strategy and growspace.irrigation_strategy.enabled:
            initial_entities.append(
                CropSteeringSensor(coordinator, growspace_id, growspace.name)
            )

        # Energy usage sensor - only if energy sensors configured
        if growspace.environment_config and growspace.environment_config.energy_sensors:
            initial_entities.append(
                EnergyUsageSensor(coordinator, growspace_id, growspace.name)
            )

        # Water usage sensor - always created per growspace
        initial_entities.append(
            WaterUsageSensor(coordinator, growspace_id, growspace.name)
        )

        # EC target sensor - always created (will be None if no curve active)
        initial_entities.append(
            ECTargetSensor(coordinator, growspace_id, growspace.name)
        )

        # Vision checkup sensor - only if camera entities configured
        if growspace.environment_config and getattr(
            growspace.environment_config, "camera_entities", None
        ):
            initial_entities.append(
                VisionCheckupSensor(coordinator, growspace_id, growspace.name)
            )

        # Tank-derived water inference sensors (fallback when no flow/drain sensors)
        if growspace.environment_config:
            initial_entities.extend(
                TankDerivedWaterSensor(coordinator, growspace_id, tank)
                for tank in getattr(
                    growspace.environment_config, "irrigation_tanks", []
                )
                if not isinstance(tank, dict)
                and _should_create_derived_water_sensor(growspace, tank)
            )

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


class TankDerivedWaterSensor(CoordinatorEntity, SensorEntity):
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
        """Initialize the tank-derived water sensor.

        Args:
            coordinator: Growspace coordinator instance
            growspace_id: ID of the growspace containing the tank
            tank: IrrigationTank instance to track
        """
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._tank = tank
        tank_slug = tank.sensor_entity.replace(".", "_").replace(" ", "_")
        self._attr_unique_id = (
            f"{DOMAIN}_{growspace_id}_tank_derived_water_{tank_slug}"
        )

    @property
    def _tracker(self) -> Any:
        """Return the TankWaterTracker for this tank, or None."""
        return self.coordinator.get_tank_tracker(
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
            "history_24h": tracker.get_history_24h(),
            "history_7d": tracker.get_history_7d(),
            "events": tracker.tank.water_history.events[-50:],
        }

    async def async_added_to_hass(self) -> None:
        """Subscribe to tank sensor state changes via the tracker."""
        await super().async_added_to_hass()
        tracker = self.coordinator.get_tank_tracker(
            self._growspace_id, self._tank.sensor_entity
        )
        if tracker is None:
            return

        def _on_change() -> None:
            self.async_write_ha_state()

        unsub = tracker.async_setup(self.hass, _on_change)
        self.async_on_remove(unsub)


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
            "scores": plant.scores.to_dict()
            if hasattr(plant.scores, "to_dict")
            else {},
            "harvest_metrics": plant.harvest_metrics.to_dict()
            if hasattr(plant.harvest_metrics, "to_dict")
            else {},
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

        # PHI (Pre-Harvest Interval) attributes
        if plant.phi_clearance_date:
            from datetime import date as date_cls  # noqa: PLC0415

            attributes["phi_clearance_date"] = plant.phi_clearance_date
            try:
                clearance = date_cls.fromisoformat(plant.phi_clearance_date)
                remaining = (clearance - date_cls.today()).days
                attributes["phi_days_remaining"] = max(0, remaining)
            except (ValueError, TypeError):
                attributes["phi_days_remaining"] = None

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


# =============================================================================
# NEW FEATURE SENSORS
# =============================================================================


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
                except (ValueError, TypeError):
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

        # Determine target based on growspace type
        target = DEFAULT_DLI_TARGET_FLOWER
        if growspace and growspace.environment_config:
            if growspace.growspace_type.value == "veg":
                target = growspace.environment_config.dli_target_veg
            else:
                target = growspace.environment_config.dli_target_flower

        pct = (self._accumulated_mol / target * 100) if target > 0 else 0.0

        # Estimate final DLI based on current rate
        estimated_final = None
        if ppfd is not None and growspace and growspace.environment_config:
            day_hours = growspace.environment_config.flower_day_hours
            if growspace.growspace_type.value == "veg":
                day_hours = growspace.environment_config.veg_day_hours
            estimated_final = round(ppfd * day_hours * 3600 / 1_000_000, 1)

        return {
            "target_dli": target,
            "percentage_of_target": round(pct, 1),
            "estimated_final_dli": estimated_final,
            "ppfd_current": ppfd,
        }

    def _handle_coordinator_update(self) -> None:
        """Handle coordinator updates by accumulating DLI."""
        now = datetime.now()
        today = now.date().isoformat()

        # Reset at midnight
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
        from .crop_steering import get_crop_steering_state  # noqa: PLC0415

        state = get_crop_steering_state(self.coordinator, self._growspace_id)
        return round(state.score, 2) if state else None

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return crop steering details."""
        from .crop_steering import get_crop_steering_state  # noqa: PLC0415

        state = get_crop_steering_state(self.coordinator, self._growspace_id)
        if not state:
            return {}

        # Determine mode from score
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
        plant_count = len(self.coordinator.get_growspace_plants(self._growspace_id))
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

        # Today's usage from daily_readings
        today_str = datetime.now().date().isoformat()
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
        """Get the active EC ramp curve for this growspace's current stage."""
        if not hasattr(self.coordinator, "nutrient_manager"):
            return None
        nm = self.coordinator.nutrient_manager
        if not hasattr(nm, "ec_ramp_curves"):
            return None

        # Find a curve matching current growspace stage
        growspace = self.coordinator.growspaces.get(self._growspace_id)
        if not growspace:
            return None

        plants = self.coordinator.get_growspace_plants(self._growspace_id)
        if not plants:
            return None

        # Use the dominant stage
        current_stage = calculate_plant_stage(plants[0])

        for curve in nm.ec_ramp_curves.values():
            if curve.stage == current_stage:
                return curve
        return None

    def _get_current_week(self) -> int:
        """Get the current week number in the active stage."""
        plants = self.coordinator.get_growspace_plants(self._growspace_id)
        if not plants:
            return 1
        stage = calculate_plant_stage(plants[0])
        days = plants[0].get_days_in_stage(stage)
        return max(1, (days // 7) + 1)

    @property
    @override  # type: ignore[misc]
    def native_value(self) -> float | None:
        """Return current target EC midpoint."""
        curve = self._get_active_curve()
        if not curve or not curve.points:
            return None
        week = self._get_current_week()
        for point in curve.points:
            if point.week == week:
                return round((point.ec_min + point.ec_max) / 2, 2)
        # If no exact match, use the last point
        last = curve.points[-1]
        if week >= last.week:
            return round((last.ec_min + last.ec_max) / 2, 2)
        return None

    @property
    @override  # type: ignore[misc]
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return EC target details."""
        curve = self._get_active_curve()
        if not curve:
            return {}

        week = self._get_current_week()
        ec_min = ec_max = None
        for point in curve.points:
            if point.week == week:
                ec_min = point.ec_min
                ec_max = point.ec_max
                break
        if ec_min is None and curve.points:
            last = curve.points[-1]
            if week >= last.week:
                ec_min = last.ec_min
                ec_max = last.ec_max

        return {
            "ec_min": ec_min,
            "ec_max": ec_max,
            "current_week": week,
            "stage": curve.stage,
            "curve_name": curve.name,
        }


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
