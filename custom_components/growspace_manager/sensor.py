"""Sensor platform for Growspace Manager.

This file defines the main sensor entities for the Growspace Manager integration,
including sensors for individual plants, growspace overviews, the strain library,
and environmental calculations like VPD.
"""

from __future__ import annotations

# Standard library
import logging
from datetime import date, datetime
from typing import Any

# Third-party / external
from dateutil import parser

# Home Assistant
from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
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
    parse_date_field,
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
        created_entities = hass.data[DOMAIN][config_entry.entry_id]["created_entities"]
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
    """Set up the Growspace Manager sensor platform from a config entry.

    This function is called by Home Assistant to initialize the sensor platform.
    It creates sensors for each growspace and plant, as well as global sensors
    like the Strain Library. It also sets up a listener to dynamically add and
    remove entities as they are changed in the coordinator.

    Args:
        hass: The Home Assistant instance.
        config_entry: The configuration entry.
        async_add_entities: A callback function for adding new entities.
    """
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    # Track created entities so we can add/remove dynamically
    growspace_entities: dict[str, GrowspaceOverviewSensor] = {}
    plant_entities: dict[str, PlantEntity] = {}

    initial_entities: list[Entity] = [
        StrainLibrarySensor(coordinator),
    ]

    # Create initial entities
    for growspace_id, growspace in coordinator.growspaces.items():
        gs_entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
        growspace_entities[growspace_id] = gs_entity
        initial_entities.append(gs_entity)

        await _async_create_derivative_sensors(hass, config_entry, growspace)

        for plant in coordinator.get_growspace_plants(growspace_id):
            pe = PlantEntity(coordinator, plant)
            plant_entities[plant.plant_id] = pe
            initial_entities.append(pe)

    # Add your GrowspaceListSensor
    initial_entities.append(GrowspaceListSensor(coordinator))

    _LOGGER.debug(
        "coordinator.growspaces = %s",
        {gid: gs.name for gid, gs in coordinator.growspaces.items()},
    )
    _LOGGER.debug("Created growspace_entities = %s", list(growspace_entities.keys()))
    _LOGGER.debug("Total initial_entities = %d", len(initial_entities))
    for entity in initial_entities:
        if isinstance(entity, GrowspaceOverviewSensor):
            _LOGGER.debug(
                "Growspace entity - unique_id=%s, name=%s",
                entity.unique_id,
                entity.name,
            )

    if initial_entities:
        async_add_entities(initial_entities)
        _LOGGER.debug(
            "Added %d initial entities (growspaces/plants/strain library)",
            len(initial_entities),
        )
    # Ensure dry and cure growspaces exist after coordinator setup
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

    # Save the changes to storage

    await coordinator.async_save()

    _LOGGER.info(
        "Ensured special growspaces exist: dry=%s, cure=%s clone=%s mother=%s",
        dry_id,
        cure_id,
        clone_id,
        mother_id,
    )

    async def _handlecoordinator_update_async() -> None:
        """Add new entities and remove missing ones when coordinator changes."""
        # Growspaces: add new
        for growspace_id, growspace in coordinator.growspaces.items():
            if growspace_id not in growspace_entities:
                entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
                growspace_entities[growspace_id] = entity
                async_add_entities([entity])

                await _async_create_derivative_sensors(hass, config_entry, growspace)

        # Growspaces: remove deleted
        for removed_gs_id in list(growspace_entities.keys()):
            if removed_gs_id not in coordinator.growspaces:
                entity = growspace_entities.pop(removed_gs_id)
                await entity.async_remove()

        # Plants: add new
        for plant in list(coordinator.plants.values()):
            plant_id = plant.plant_id
            if plant_id not in plant_entities:
                entity = PlantEntity(coordinator, plant)
                plant_entities[plant_id] = entity
                async_add_entities([entity])

        # Plants: remove deleted
        from homeassistant.helpers import entity_registry as er

        entity_registry = er.async_get(coordinator.hass)

        for existing_id in list(plant_entities.keys()):
            if existing_id not in coordinator.plants:
                entity = plant_entities.pop(existing_id)

                # Try to find and remove from registry
                ent_reg_entry = entity_registry.async_get(entity.entity_id)
                if ent_reg_entry:
                    _LOGGER.info(
                        "Removing orphaned plant entity from registry: %s",
                        entity.entity_id,
                    )
                    entity_registry.async_remove(ent_reg_entry.entity_id)

                await entity.async_remove()

    # Listen for coordinator updates to manage dynamic entities
    def _listener_callback() -> None:
        hass.async_create_task(_handlecoordinator_update_async())

    coordinator.async_add_listener(_listener_callback)

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
    def state(self) -> str:
        """Return the current recommended air exchange action."""
        # The actual state is calculated in the coordinator and stored.
        # This sensor just retrieves it.
        recommendation = self.coordinator.data.get(
            "air_exchange_recommendations", {}
        ).get(self.growspace_id, "Idle")
        return recommendation


class GrowspaceOverviewSensor(SensorEntity):
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
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.growspace = growspace
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
    def state(self) -> int:
        """Return the number of plants in the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        return len(plants)

    @staticmethod
    def _days_since(date_str: str) -> int:
        """Calculate the number of days since a given date string.

        Args:
            date_str: The date in 'YYYY-MM-DD' format.

        Returns:
            The number of days that have passed.
        """
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return 0
        return (date.today() - dt).days

    @staticmethod
    def _days_to_week(days: int) -> int:
        """Convert a number of days into a week number (1-indexed).

        Args:
            days: The number of days.

        Returns:
            The corresponding week number.
        """
        if days <= 0:
            return 0
        return (days - 1) // 7 + 1

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)

        # Calculate max stage days
        max_veg = max(
            (self._days_since(p.veg_start) for p in plants if p.veg_start), default=0
        )
        max_flower = max(
            (self._days_since(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )

        # Calculate weeks from days
        veg_week = self._days_to_week(max_veg)
        flower_week = self._days_to_week(max_flower)

        # Create grid representation
        grid = {}
        for row in range(1, int(self.growspace.rows) + 1):
            for col in range(
                1,
                int(
                    self.growspace.plants_per_row,
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

        return {
            "growspace_id": self.growspace.id,
            "rows": self.growspace.rows,
            "plants_per_row": self.growspace.plants_per_row,
            "total_plants": len(plants),
            "notification_target": self.growspace.notification_target,
            "max_veg_days": max_veg,
            "max_flower_days": max_flower,
            "veg_week": veg_week,
            "flower_week": flower_week,
            "max_stage_summary": f"Veg: {max_veg}d (W{veg_week}), Flower: {max_flower}d (W{flower_week})",
            "grid": grid,
        }

    async def async_added_to_hass(self) -> None:
        """Register callbacks when the entity is added to Home Assistant."""
        self.coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """Clean up when the entity is removed from Home Assistant."""
        # Note: In a real implementation, you'd remove the listener here
        pass


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

    def _parse_date(self, value: str | None) -> date | None:
        """Safely parse a date string into a date object.

        Args:
            value: The date string to parse.

        Returns:
            A date object, or None if parsing fails.
        """
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return parser.isoparse(value).date()
        except Exception:
            return None

    def _determine_stage(self, plant: Plant) -> str:
        """Determine the current growth stage of the plant.

        The stage is determined by a hierarchy: first by the special growspace
        it's in, then by the most recent start date, and finally by the
        explicitly set stage property.

        Args:
            plant: The Plant object to analyze.

        Returns:
            The determined stage as a string.
        """
        now = date.today()

        # 1. Special growspaces override everything
        if plant.growspace_id == "mother":
            return "mother"
        if plant.growspace_id == "clone":
            return "clone"
        if plant.growspace_id == "dry":
            return "dry"
        if plant.growspace_id == "cure":
            return "cure"

        # 2. Date-based progression (most advanced stage wins)
        flower_start = parse_date_field(plant.flower_start)
        veg_start = parse_date_field(plant.veg_start)
        seedling_start = parse_date_field(plant.seedling_start)

        if flower_start and flower_start <= now:
            return "flower"
        if veg_start and veg_start <= now:
            return "veg"
        if seedling_start and seedling_start <= now:
            return "seedling"

        # 3. Fallback to explicitly set stage if none of the above applies
        if plant.stage in [
            "seedling",
            "mother",
            "clone",
            "veg",
            "flower",
            "dry",
            "cure",
        ]:
            return plant.stage

        # Default
        return "seedling"

    @staticmethod
    def _days_to_week(days: int) -> int:
        """Convert a number of days into a week number (1-indexed).

        Args:
            days: The number of days.

        Returns:
            The corresponding week number.
        """
        if days <= 0:
            return 0
        return (days - 1) // 7 + 1

    @property
    def state(self) -> str:
        """Return the current growth stage of the plant."""
        # Get updated plant data
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return "unknown"

        stage = self._determine_stage(plant)

        # Get growspace if needed
        self.coordinator.growspaces.get(plant.growspace_id)

        return stage

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the detailed state attributes for the plant."""
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return {}

        stage = self._determine_stage(plant)
        seedling_days = self.coordinator.calculate_days_in_stage(plant, "seedling")
        mother_days = self.coordinator.calculate_days_in_stage(plant, "mother")
        clone_days = self.coordinator.calculate_days_in_stage(plant, "clone")
        veg_days = self.coordinator.calculate_days_in_stage(plant, "veg")
        flower_days = self.coordinator.calculate_days_in_stage(plant, "flower")
        dry_days = self.coordinator.calculate_days_in_stage(plant, "dry")
        cure_days = self.coordinator.calculate_days_in_stage(plant, "cure")

        # Calculate weeks
        veg_week = self._days_to_week(veg_days or 0)
        flower_week = self._days_to_week(flower_days or 0)

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
    def state(self) -> int:
        """Return the number of unique strains in the library."""
        return len(self.coordinator.strains.get_all())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the calculated strain analytics as state attributes."""
        analytics_data = {}
        all_strains = self.coordinator.strains.get_all()

        for strain_name, strain_data in all_strains.items():
            phenotypes = strain_data.get("phenotypes", {})
            strain_harvests = []

            # Process each phenotype
            pheno_analytics = {}
            for pheno_name, pheno_data in phenotypes.items():
                harvests = pheno_data.get("harvests", [])
                strain_harvests.extend(harvests)

                num_harvests = len(harvests)
                if num_harvests > 0:
                    total_veg = sum(h.get("veg_days", 0) for h in harvests)
                    total_flower = sum(h.get("flower_days", 0) for h in harvests)
                    stats = {
                        "avg_veg_days": round(total_veg / num_harvests),
                        "avg_flower_days": round(total_flower / num_harvests),
                        "total_harvests": num_harvests,
                    }
                else:
                    stats = {
                        "avg_veg_days": 0,
                        "avg_flower_days": 0,
                        "total_harvests": 0,
                    }

                # Extract metadata, excluding the raw harvest list
                pheno_meta = {k: v for k, v in pheno_data.items() if k != "harvests"}

                # Merge them
                pheno_analytics[pheno_name] = {**stats, **pheno_meta}

            # Calculate strain-level analytics
            num_strain_harvests = len(strain_harvests)
            strain_avg_veg = 0
            strain_avg_flower = 0
            if num_strain_harvests > 0:
                strain_avg_veg = round(sum(h.get("veg_days", 0) for h in strain_harvests) / num_strain_harvests)
                strain_avg_flower = round(sum(h.get("flower_days", 0) for h in strain_harvests) / num_strain_harvests)

            analytics_data[strain_name] = {
                "meta": strain_data.get("meta", {}),
                "analytics": {
                    "avg_veg_days": strain_avg_veg,
                    "avg_flower_days": strain_avg_flower,
                    "total_harvests": num_strain_harvests
                },
                "phenotypes": pheno_analytics
            }

        return {
            "strains": analytics_data,
            "strain_list": list(all_strains.keys())
        }


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
    def state(self):
        """Return the total number of growspaces."""
        self._update_growspaces()
        return len(self._growspaces)

    @property
    def extra_state_attributes(self):
        """Return the list of growspaces as a state attribute."""
        return {"growspaces": self._growspaces}
