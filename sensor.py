"""Sensor platform for Growspace Manager."""

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
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

# Local / relative imports
from .coordinator import GrowspaceCoordinator
from .models import Plant, Growspace
from .utils import (
    parse_date_field,
    format_date,
    calculate_days_since,
    find_first_free_position,
    generate_growspace_grid,
)
from .const import DOMAIN, DEFAULT_NOTIFICATION_EVENTS

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator = hass.data[DOMAIN][config_entry.entry_id]["coordinator"]

    # Track created entities so we can add/remove dynamically
    growspace_entities: dict[str, GrowspaceOverviewSensor] = {}
    plant_entities: dict[str, PlantEntity] = {}

    initial_entities: list[Entity] = [
        StrainLibrarySensor(coordinator),
        GrowspaceListSensor(coordinator),  # <- add this
    ]

    # Create initial entities
    for growspace_id, growspace in coordinator.growspaces.items():
        gs_entity = GrowspaceOverviewSensor(coordinator, growspace_id, growspace)
        growspace_entities[growspace_id] = gs_entity
        initial_entities.append(gs_entity)

        for plant in coordinator.get_growspace_plants(growspace_id):
            pe = PlantEntity(coordinator, plant)
            plant_entities[plant.plant_id] = pe
            initial_entities.append(pe)

    # Add your GrowspaceListSensor
    initial_entities.append(GrowspaceListSensor(coordinator))

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

    # Force coordinator to notify listeners of the new growspaces
    coordinator.async_set_updated_data(coordinator.data)

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
        for existing_id in list(plant_entities.keys()):
            if existing_id not in coordinator.plants:
                entity = plant_entities.pop(existing_id)
                await entity.async_remove()

    # Listen for coordinator updates to manage dynamic entities
    def _listener_callback() -> None:
        coordinator.hass.async_create_task(_handlecoordinator_update_async())

    coordinator.async_add_listener(_listener_callback)


class GrowspaceOverviewSensor(SensorEntity):
    def __init__(
        self, coordinator: GrowspaceCoordinator, growspace_id: str, growspace: Growspace
    ):
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.growspace = growspace
        self._attr_name = f"{growspace.name}"  # now Pylance knows "name" exists

        # Use stable unique_id matching canonical growspace_id to avoid duplicates
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}"
        # Use the growspace name directly as entity name to avoid duplicated suffixes
        # e.g., "Dry Overview" → sensor.dry_overview
        # Force fixed entity IDs for dry/cure
        if growspace.id == "dry":
            self._attr_unique_id = f"{DOMAIN}_growspace_dry"
            self._attr_name = "dry"
        elif growspace.id == "cure":
            self._attr_unique_id = "growspace_cure"
            self._attr_name = "cure"
            self._attr_entity_id = "sensor.cure"
        if growspace.id == "mother":
            self._attr_unique_id = "growspace_mother"
            self._attr_name = "mother"
            self._attr_entity_id = "sensor.mother"
        elif growspace.id == "clone":
            self._attr_unique_id = "growspace_clone"
            self._attr_name = "clone"
            self._attr_entity_id = "sensor.clone"
        else:
            self._attr_unique_id = f"growspace_{growspace.id}"
            self._attr_name = f"{growspace.name}"
            self._attr_entity_id = f"sensor.{growspace.id}"

        # Set up device info
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    @property
    def unique_id(self) -> str | None:
        """Return the unique ID of the sensor."""
        return self._attr_unique_id

    @property
    def state(self) -> int:
        """Return the number of plants in the growspace."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)
        return len(plants)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)

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
            "grid": grid,
        }

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        # Note: In a real implementation, you'd remove the listener here
        pass


class GrowspaceMaxStageSensor(CoordinatorEntity[GrowspaceCoordinator], SensorEntity):
    """Sensor showing the max days in veg/flower for a growspace."""

    _attr_icon = "mdi:calendar-clock"

    def __init__(
        self, coordinator: GrowspaceCoordinator, growspace_id: str, name: str
    ) -> None:
        super().__init__(coordinator)
        self._growspace_id = growspace_id
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}_max_stage"
        self._attr_name = f"{name} Max Stage"

    @property
    def native_value(self) -> str | None:
        """Return a human-readable summary of the growspace stage."""
        plants = [
            plant
            for plant in self.coordinator.plants.values()
            if plant.growspace_id == self._growspace_id
        ]
        if not plants:
            return None

        max_veg = max(
            (self._days_since(p.veg_start) for p in plants if p.veg_start), default=0
        )
        max_flower = max(
            (self._days_since(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )

        return f"Veg: {max_veg}d, Flower: {max_flower}d"

    @staticmethod
    def _days_since(date_str: str) -> int:
        """Calculate days since date string (YYYY-MM-DD)."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except Exception:
            return 0
        return (date.today() - dt).days

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return extra attributes with numeric values."""
        plants = [
            plant
            for plant in self.coordinator.plants.values()
            if plant.growspace_id == self._growspace_id
        ]
        max_veg = max(
            (self._days_since(p.veg_start) for p in plants if p.veg_start), default=0
        )
        max_flower = max(
            (self._days_since(p.flower_start) for p in plants if p.flower_start),
            default=0,
        )

        return {
            "growspace_id": self._growspace_id,
            "max_veg_days": max_veg,
            "max_flower_days": max_flower,
            "plant_count": len(plants),
        }


class PlantEntity(SensorEntity):
    """Single entity per plant with stage as state and all variables as attributes."""

    def __init__(self, coordinator, plant: Plant):
        self.coordinator = coordinator
        self._plant = plant
        # self._attr_unique_id = f"{DOMAIN}_{plant['plant_id']}"
        self._attr_unique_id = f"{DOMAIN}_{plant.plant_id}"  # HA internal unique_id
        self._attr_name = f"{plant.strain} ({plant.row},{plant.col})"
        self._attr_icon = "mdi:cannabis"

        # Set up device info - plant belongs to growspace device
        growspace_id = plant.growspace_id
        growspace = coordinator.growspaces.get(growspace_id, {})
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, growspace_id)},
            name=growspace.name,
            model="Growspace",
            manufacturer="Growspace Manager",
        )

    def _parse_date(self, value: str | None) -> date | None:
        """Safely parse a date string or datetime object to a date."""
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return parser.isoparse(value).date()
        except Exception:
            return None

    def _determine_stage(self, plant: Plant) -> str:
        # If explicit stage is set (dry, cure, etc.), use it directly
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

        # Fallback: infer from start dates
        now = date.today()
        flower_start = parse_date_field(plant.flower_start)
        veg_start = parse_date_field(plant.veg_start)

        if flower_start and flower_start <= now:
            return "flower"
        if veg_start and veg_start <= now and (not flower_start or flower_start > now):
            return "veg"

        return "seedling"

    @property
    def state(self) -> str:
        """Return the current stage of the plant."""
        # Get updated plant data
        plant = self.coordinator.plants.get(self._plant.plant_id)
        if not plant:
            return "unknown"

        stage = self._determine_stage(plant)

        # Get growspace if needed
        growspace = self.coordinator.growspaces.get(plant.growspace_id)

        # Check for notifications for current stage
        if stage in ["veg", "flower"] and growspace:
            days = self.coordinator.calculate_days_in_stage(plant, stage)
            if days and self._should_send_notification(plant, stage, days, growspace):
                self._send_notification(plant, stage, days, growspace)

        return stage

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return all plant variables as attributes."""
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
        }

    def _check_and_send_notifications(
        self, plant: Plant, current_stage: str, growspace: Growspace
    ) -> None:
        # Check all stages that could have notifications
        stages_to_check = []

        # Add current stage
        stages_to_check.append(current_stage)

        # For plants in later stages, also check if we missed earlier notifications
        stage_order = ["seedling", "clone", "mother", "veg", "flower", "dry", "cure"]
        current_index = (
            stage_order.index(current_stage) if current_stage in stage_order else 0
        )

        # Check previous stages too (in case we missed notifications during stage transitions)
        for i, stage in enumerate(stage_order):
            if i <= current_index and (f"{plant.stage}_start"):
                stages_to_check.append(stage)

        # Remove duplicates while preserving order
        stages_to_check = list(dict.fromkeys(stages_to_check))

        for stage in stages_to_check:
            if stage in [
                "veg",
                "flower",
                "dry",
                "cure",
            ]:  # Only stages with notification events
                days = self.coordinator.calculate_days_in_stage(plant, stage)
                if days > 0 and self._should_send_notification(
                    plant, stage, days, growspace
                ):
                    self._send_notification(plant, stage, days, growspace)

    def _should_send_notification(
        self, plant: Plant, stage: str, days: int, growspace: Growspace
    ) -> bool:
        """Check if we should send a notification for this plant/stage/days combination."""
        growspace = self.coordinator.growspaces.get(plant.growspace_id)
        notification_target = growspace.notification_target

        if not notification_target:
            _LOGGER.debug(
                "Skipping notification for plant %s (no target set). Stage=%s Days=%s",
                plant.plant_id,
                stage,
                days,
            )
            return False

        # Check if notification already sent
        should_send = self.coordinator.should_send_notification(
            plant.plant_id, stage, days
        )

        has_matching_event = any(
            event["days"] == days and event["stage"] == stage
            for event in DEFAULT_NOTIFICATION_EVENTS.values()
        )

        final_should_send = should_send and has_matching_event

        _LOGGER.debug(
            "Notification check: Plant=%s Stage=%s Days=%s HasTarget=%s AlreadySent=%s HasEvent=%s → %s",
            plant.plant_id,
            stage,
            days,
            bool(notification_target),
            not should_send,
            has_matching_event,
            final_should_send,
        )

        return final_should_send

    def _send_notification(
        self, plant: Plant, stage: str, days: int, growspace: Growspace
    ):
        """Send notification for plant milestone."""

        notification_target = growspace.notification_target

        if not notification_target:
            _LOGGER.debug(
                "No notification target found for growspace %s", plant.growspace_id
            )
            return

        # Find matching notification event
        message = None
        for event_data in DEFAULT_NOTIFICATION_EVENTS.values():
            if event_data["days"] == days and event_data["stage"] == stage:
                message = event_data["message"]
                break

        if not message:
            _LOGGER.debug(
                "No matching notification event for Plant=%s Stage=%s Days=%s",
                plant.plant_id,
                stage,
                days,
            )
            return

        _LOGGER.info(
            "Sending notification → Growspace=%s Plant=%s Target=%s Stage=%s Days=%s Message='%s'",
            growspace.name,
            plant.plant_id,
            notification_target,
            stage,
            days,
            message,
        )

        # Mark notification as sent FIRST to prevent duplicates
        self.hass.async_create_task(
            self.coordinator.mark_notification_sent(plant.plant_id, stage, days)
        )

        # Fire the notify service
        self.hass.async_create_task(
            self.hass.services.async_call(
                "notify",
                notification_target,
                {
                    "title": f"Growspace: {growspace.name}",
                    "message": f"{plant.strain} ({plant.row},{plant.col}) - {message}",
                    "data": {
                        "plant_id": plant.plant_id,
                        "growspace_id": plant.growspace_id,
                        "stage": stage,
                        "days": days,
                    },
                },
            )
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.coordinator.async_add_listener(self.async_write_ha_state)


class StrainLibrarySensor(SensorEntity):
    """Exposes the strain library to Home Assistant."""

    def __init__(self, coordinator: GrowspaceCoordinator):
        self.coordinator = coordinator
        self._attr_name = "Growspace Strain Library"
        self._attr_unique_id = f"{DOMAIN}_strain_library"
        self._attr_icon = "mdi:leaf"

    @property
    def state(self) -> str:
        return "ok"  # the value is trivial, we care about attributes

    @property
    def extra_state_attributes(self) -> dict:
        return {"strains": self.coordinator.get_strain_options()}

    async def async_added_to_hass(self):
        self.coordinator.async_add_listener(self.async_write_ha_state)


class GrowspaceListSensor(SensorEntity):
    """Exposes the list of growspaces as a sensor."""

    def __init__(self, coordinator: GrowspaceCoordinator):
        self.coordinator = coordinator
        self._attr_name = "Growspaces List"
        self._attr_unique_id = f"{DOMAIN}_growspaces_list"  # <- important for HA
        self._attr_icon = "mdi:home-group"
        self._update_growspaces()

    def _update_growspaces(self):
        self._growspaces = self.coordinator.get_growspace_options()

    @property
    def state(self):
        self._update_growspaces()
        return len(self._growspaces)

    @property
    def extra_state_attributes(self):
        return {"growspaces": self._growspaces}
