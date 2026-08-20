"""Setup functions for the sensor platform."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from custom_components.growspace_manager.const import (
    METRIC_HUMIDITY,
    METRIC_TEMPERATURE,
    METRIC_VPD,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.helpers import (
    async_setup_statistics_sensor,
    async_setup_trend_sensor,
)
from custom_components.growspace_manager.models import Growspace, IrrigationTank
from custom_components.growspace_manager.tank_depletion_predictor import (
    TankDepletionPredictor,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .crop_steering import CropSteeringSensor
from .drying import DryingMoistureSensor, DryingWeightSensor
from .environment import AirExchangeSensor, DLISensor, ECTargetSensor
from .overview import GrowspaceListSensor, GrowspaceOverviewSensor
from .plant import PlantEntity
from .strain import SeedInventorySensor, StrainLibrarySensor
from .tank import (
    TankDepletionSensor,
    TankDerivedWaterSensor,
    _should_create_derived_water_sensor,
)
from .usage import EnergyUsageSensor, PowerUsageSensor, WaterUsageSensor
from .vision import VisionCheckupSensor
from .vpd import CalculatedVpdSensor, SubareaCalculatedVpdSensor, VpdSensor

_LOGGER = logging.getLogger(__name__)


async def _async_create_derivative_sensors(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    growspace: Growspace,
) -> None:
    """Create helper trend and statistics sensors for a growspace's environment."""
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

    def get_val(key: str, default: Any = None) -> Any:
        return getattr(growspace.environment_config, key, default)

    for sensor_type, (singular_key, plural_key) in metric_map.items():
        raw_sensors = get_val(plural_key, [])
        sensors = list(raw_sensors) if hasattr(raw_sensors, "__iter__") else []
        singular_val = get_val(singular_key)
        if singular_val and singular_val not in sensors:
            sensors.insert(0, singular_val)

        for i, source_sensor in enumerate(sensors):
            if not source_sensor:
                continue

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

    growspace_entities: dict[str, GrowspaceOverviewSensor] = {}
    plant_entities: dict[str, PlantEntity] = {}
    initial_entities: list[Entity] = []

    calculated_vpd_growspace_ids: set[str] = set()
    calculated_subarea_vpd_ids: set[str] = set()
    initialized_drying_sensor_ids: set[str] = set()

    await _create_initial_entities(
        hass,
        coordinator,
        config_entry,
        initial_entities,
        growspace_entities,
        plant_entities,
        calculated_vpd_growspace_ids,
        calculated_subarea_vpd_ids,
        initialized_drying_sensor_ids,
    )

    if initial_entities:
        async_add_entities(initial_entities)
        _LOGGER.debug(
            "Added %d initial entities (growspaces/plants/strain library)",
            len(initial_entities),
        )

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

    air_exchange_sensors = [
        AirExchangeSensor(coordinator, growspace_id)
        for growspace_id in coordinator.growspaces
    ]
    async_add_entities(air_exchange_sensors)

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
                calculated_subarea_vpd_ids,
            )
            await _update_plant_entities(
                hass,
                coordinator,
                plant_entities,
                async_add_entities,
                initialized_drying_sensor_ids,
            )

    def _listener_callback() -> None:
        """Handle coordinator updates."""
        config_entry.async_create_background_task(
            hass, _handle_coordinator_update_async(), "handle_coordinator_update"
        )

    config_entry.async_on_unload(coordinator.async_add_listener(_listener_callback))


async def _create_initial_entities(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    config_entry: ConfigEntry,
    initial_entities: list[Entity],
    growspace_entities: dict[str, GrowspaceOverviewSensor],
    plant_entities: dict[str, PlantEntity],
    calculated_vpd_growspace_ids: set[str],
    calculated_subarea_vpd_ids: set[str],
    initialized_drying_sensor_ids: set[str],
) -> None:
    """Create initial entities for the platform."""
    initial_entities.append(StrainLibrarySensor(coordinator))
    initial_entities.append(SeedInventorySensor(coordinator))

    for growspace_id, growspace in coordinator.growspaces.items():
        gs_entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
        growspace_entities[growspace_id] = gs_entity
        initial_entities.append(gs_entity)

        vpd_entities = _check_calculated_vpd_sensor(coordinator, growspace)
        for vpd_entity in vpd_entities:
            initial_entities.append(vpd_entity)
            if vpd_entity.unique_id:
                calculated_vpd_growspace_ids.add(vpd_entity.unique_id)

        subarea_vpd_entities = _check_subarea_calculated_vpd_sensors(
            coordinator, growspace
        )
        for vpd_entity in subarea_vpd_entities:
            initial_entities.append(vpd_entity)
            if vpd_entity.unique_id:
                calculated_subarea_vpd_ids.add(vpd_entity.unique_id)

        env_config = getattr(growspace, "environment_config", None)
        if env_config:
            irrigation_tanks = []
            if isinstance(env_config, dict):
                irrigation_tanks = env_config.get("irrigation_tanks", [])
            elif hasattr(env_config, "irrigation_tanks"):
                irrigation_tanks = env_config.irrigation_tanks or []

            for tank in irrigation_tanks:
                enable_prediction = True
                if isinstance(tank, dict):
                    enable_prediction = tank.get("enable_prediction", True)
                elif hasattr(tank, "enable_prediction"):
                    enable_prediction = tank.enable_prediction

                if enable_prediction:
                    tank_obj = (
                        IrrigationTank.from_dict(tank)
                        if isinstance(tank, dict)
                        else tank
                    )

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
                    await predictor.async_update()

        await _async_create_derivative_sensors(hass, config_entry, growspace)

        if growspace.environment_config and growspace.environment_config.light_sensors:
            initial_entities.append(
                DLISensor(coordinator, growspace_id, growspace.name)
            )

        if growspace.irrigation_strategy and growspace.irrigation_strategy.enabled:
            initial_entities.append(
                CropSteeringSensor(coordinator, growspace_id, growspace.name)
            )

        if growspace.environment_config and growspace.environment_config.energy_sensors:
            initial_entities.append(
                EnergyUsageSensor(coordinator, growspace_id, growspace.name)
            )

        if growspace.environment_config and growspace.environment_config.power_sensors:
            initial_entities.append(
                PowerUsageSensor(coordinator, growspace_id, growspace.name)
            )

        initial_entities.append(
            WaterUsageSensor(coordinator, growspace_id, growspace.name)
        )

        initial_entities.append(
            ECTargetSensor(coordinator, growspace_id, growspace.name)
        )

        if growspace.environment_config and getattr(
            growspace.environment_config, "camera_entities", None
        ):
            initial_entities.append(
                VisionCheckupSensor(coordinator, growspace_id, growspace.name)
            )

        if growspace.environment_config:
            initial_entities.extend(
                TankDerivedWaterSensor(coordinator, growspace_id, tank)
                for tank in getattr(
                    growspace.environment_config, "irrigation_tanks", []
                )
                if not isinstance(tank, dict)
                and _should_create_derived_water_sensor(growspace, tank)
            )

        for plant in coordinator.services.growspaces.get_growspace_plants(growspace_id):
            pe = PlantEntity(coordinator, plant)
            plant_entities[plant.plant_id] = pe
            initial_entities.append(pe)
            if plant.dry_start is not None:
                initial_entities.append(DryingWeightSensor(coordinator, plant))
                initial_entities.append(DryingMoistureSensor(coordinator, plant))
                initialized_drying_sensor_ids.add(plant.plant_id)

    initial_entities.append(GrowspaceListSensor(coordinator))


async def _update_growspace_entities(
    hass: HomeAssistant,
    coordinator: GrowspaceCoordinator,
    config_entry: ConfigEntry,
    growspace_entities: dict[str, GrowspaceOverviewSensor],
    async_add_entities: AddEntitiesCallback,
    calculated_vpd_growspace_ids: set[str],
    calculated_subarea_vpd_ids: set[str],
) -> None:
    """Update growspace entities based on coordinator data."""
    for growspace_id, growspace in coordinator.growspaces.items():
        if growspace_id not in growspace_entities:
            entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
            growspace_entities[growspace_id] = entity
            async_add_entities([entity])

        await _async_create_derivative_sensors(hass, config_entry, growspace)

        vpd_entities = _check_calculated_vpd_sensor(coordinator, growspace)
        new_calculated_vpds = [
            v for v in vpd_entities if v.unique_id not in calculated_vpd_growspace_ids
        ]
        if new_calculated_vpds:
            async_add_entities(new_calculated_vpds)
            for v in new_calculated_vpds:
                if v.unique_id:
                    calculated_vpd_growspace_ids.add(v.unique_id)
            coordinator.config_entry.async_create_background_task(
                hass, coordinator.async_request_refresh(), "coordinator_refresh"
            )

        subarea_vpd_entities = _check_subarea_calculated_vpd_sensors(
            coordinator, growspace
        )
        new_subarea_vpds = [
            v
            for v in subarea_vpd_entities
            if v.unique_id not in calculated_subarea_vpd_ids
        ]
        if new_subarea_vpds:
            async_add_entities(new_subarea_vpds)
            for v in new_subarea_vpds:
                if v.unique_id:
                    calculated_subarea_vpd_ids.add(v.unique_id)

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
    initialized_drying_sensor_ids: set[str],
) -> None:
    """Update plant entities based on coordinator data."""
    new_entities: list[Entity] = []
    for plant_id, plant in coordinator.plants.items():
        if plant_id not in plant_entities:
            pe = PlantEntity(coordinator, plant)
            plant_entities[plant_id] = pe
            new_entities.append(pe)
        if (
            plant.dry_start is not None
            and plant_id not in initialized_drying_sensor_ids
        ):
            new_entities.append(DryingWeightSensor(coordinator, plant))
            new_entities.append(DryingMoistureSensor(coordinator, plant))
            initialized_drying_sensor_ids.add(plant_id)

    if new_entities:
        async_add_entities(new_entities)

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

    def get_val(key: str, default: Any = None) -> Any:
        return getattr(env_config, key, default)

    temp_sensors = get_val("temperature_sensors", [])
    hum_sensors = get_val("humidity_sensors", [])
    vpd_sensors = get_val("vpd_sensors", [])

    if not temp_sensors and (ts := get_val("temperature_sensor")):
        temp_sensors = [ts]
    if not hum_sensors and (hs := get_val("humidity_sensor")):
        hum_sensors = [hs]
    if not vpd_sensors and (vs := get_val("vpd_sensor")):
        vpd_sensors = [vs]

    entities: list[CalculatedVpdSensor] = []

    num_pairs = min(len(temp_sensors), len(hum_sensors))

    lst_offset = get_val("lst_offset", 0.0)

    for i in range(num_pairs):
        t_sensor = temp_sensors[i]
        h_sensor = hum_sensors[i]

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


def _get_env_config_val(env_config: Any, key: str, default: Any = None) -> Any:
    """Safely get a value from an EnvironmentConfig (dataclass or dict)."""
    try:
        if isinstance(env_config, dict):
            return env_config.get(key, default)
        return getattr(env_config, key, default)
    except AttributeError:
        return default


def _check_subarea_calculated_vpd_sensors(
    coordinator: GrowspaceCoordinator,
    growspace: Growspace,
) -> list[SubareaCalculatedVpdSensor]:
    """Create calculated VPD sensors for subareas that have T/H but no VPD sensor."""
    entities: list[SubareaCalculatedVpdSensor] = []

    for subarea in getattr(growspace, "subareas", []):
        env_config = subarea.environment_config
        if not env_config:
            continue

        temp_sensors = _get_env_config_val(env_config, "temperature_sensors", [])
        hum_sensors = _get_env_config_val(env_config, "humidity_sensors", [])
        vpd_sensors = _get_env_config_val(env_config, "vpd_sensors", [])

        if not temp_sensors and (
            ts := _get_env_config_val(env_config, "temperature_sensor")
        ):
            temp_sensors = [ts]
        if not hum_sensors and (
            hs := _get_env_config_val(env_config, "humidity_sensor")
        ):
            hum_sensors = [hs]
        if not vpd_sensors and (vs := _get_env_config_val(env_config, "vpd_sensor")):
            vpd_sensors = [vs]

        num_pairs = min(len(temp_sensors), len(hum_sensors))
        lst_offset = _get_env_config_val(env_config, "lst_offset", 0.0)

        for i in range(num_pairs):
            t_sensor = temp_sensors[i]
            h_sensor = hum_sensors[i]
            existing_vpd = vpd_sensors[i] if i < len(vpd_sensors) else None

            if t_sensor and h_sensor:
                if not existing_vpd or "calculated_vpd" in existing_vpd:
                    index = i if num_pairs > 1 else None
                    entities.append(
                        SubareaCalculatedVpdSensor(
                            coordinator,
                            growspace.id,
                            growspace.name,
                            subarea.id,
                            subarea.name,
                            t_sensor,
                            h_sensor,
                            lst_offset,
                            index=index,
                        )
                    )

    return entities
