"""Sensor platform for Growspace Manager."""

from __future__ import annotations

# Standard library
import logging
from datetime import date, datetime
from typing import Any

# Third-party / external
from dateutil import parser

# Home Assistant
from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DEFAULT_NOTIFICATION_EVENTS, DOMAIN

# Local / relative imports
from .coordinator import GrowspaceCoordinator
from .models import Growspace, Plant
from .utils import (
    parse_date_field,
)

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

    _LOGGER.debug(
        "DEBUG: coordinator.growspaces = %s",
        {gid: gs.name for gid, gs in coordinator.growspaces.items()},
    )
    _LOGGER.debug(
        "DEBUG: Created growspace_entities = %s",
        list(growspace_entities.keys()),
    )
    _LOGGER.debug("DEBUG: Total initial_entities = %d", len(initial_entities))
    for entity in initial_entities:
        if isinstance(entity, GrowspaceOverviewSensor):
            _LOGGER.debug(
                "DEBUG: Growspace entity - unique_id=%s, name=%s",
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
        "dry",
        "dry",
        rows=3,
        plants_per_row=3,
    )
    cure_id = coordinator._ensure_special_growspace(
        "cure",
        "cure",
        rows=3,
        plants_per_row=3,
    )
    clone_id = coordinator._ensure_special_growspace(
        "clone",
        "clone",
        rows=3,
        plants_per_row=3,
    )
    mother_id = coordinator._ensure_special_growspace(
        "mother",
        "mother",
        rows=3,
        plants_per_row=3,
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
                    _LOGGER.warning(
                        "Removing orphaned plant entity from registry: %s",
                        entity.entity_id,
                    )
                    entity_registry.async_remove(ent_reg_entry.entity_id)

                await entity.async_remove()

    # Listen for coordinator updates to manage dynamic entities
    def _listener_callback() -> None:
        coordinator.hass.async_create_task(_handlecoordinator_update_async())

    coordinator.async_add_listener(_listener_callback)


class GrowspaceOverviewSensor(SensorEntity):
    def __init__(
        self,
        coordinator: GrowspaceCoordinator,
        growspace_id: str,
        growspace: Growspace,
    ) -> None:
        """Initialize the Growspace Overview Sensor."""
        self.coordinator = coordinator
        self.growspace_id = growspace_id
        self.growspace = growspace
        self._attr_has_entity_name = True
        self._attr_name = "Plant Count"

        # Use stable unique_id matching canonical growspace_id to avoid duplicates
        self._attr_unique_id = f"{DOMAIN}_{growspace_id}"
        # Force fixed entity IDs for special growspaces
        if growspace.id == "dry":
            self._attr_unique_id = f"{DOMAIN}_growspace_dry"
            self._attr_name = "Dry"
            self._attr_entity_id = "sensor.growspace_dry"
        elif growspace.id == "cure":
            self._attr_unique_id = f"{DOMAIN}_growspace_cure"
            self._attr_name = "Cure"
            self._attr_entity_id = "sensor.growspace_cure"
        elif growspace.id == "mother":
            self._attr_unique_id = f"{DOMAIN}_growspace_mother"
            self._attr_name = "Mother"
            self._attr_entity_id = "sensor.growspace_mother"
        elif growspace.id == "clone":
            self._attr_unique_id = f"{DOMAIN}_growspace_clone"
            self._attr_name = "Clone"
            self._attr_entity_id = "sensor.growspace_clone"
        else:
            self._attr_unique_id = f"{DOMAIN}_growspace_{growspace.id}"
            self._attr_name = "Plant Count"
            self._attr_entity_id = f"sensor.{growspace.id}_plant_count"

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
        """Calculate days since date string (YYYY-MM-DD)."""
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            return 0
        return (date.today() - dt).days

    @staticmethod
    def _days_to_week(days: int) -> int:
        """Convert days to week number (1-indexed)."""
        if days <= 0:
            return 0
        return (days - 1) // 7 + 1

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return additional state attributes."""
        plants = self.coordinator.get_growspace_plants(self.growspace_id)

        # Calculate max stage days via coordinator
        stage_days = self.coordinator.get_growspace_max_stage_days(self.growspace_id)
        max_veg = stage_days.get("veg", 0)
        max_flower = stage_days.get("flower", 0)

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
                    plant,
                    "flower",
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
        """When entity is added to hass."""
        self.coordinator.async_add_listener(self.async_write_ha_state)

    async def async_will_remove_from_hass(self) -> None:
        """When entity will be removed from hass."""
        # Note: In a real implementation, you'd remove the listener here


class PlantEntity(SensorEntity):
    """Single entity per plant with stage as state and all variables as attributes."""

    def __init__(self, coordinator, plant: Plant) -> None:
        """Initialize the Plant Entity."""
        self.coordinator = coordinator
        self._plant = plant
        self._attr_has_entity_name = True
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
        """Safely parse a date string or datetime object to a date."""
        if not value:
            return None
        if isinstance(value, date):
            return value
        try:
            return parser.isoparse(value).date()
        except (ValueError, TypeError):
            return None

    def _determine_stage(self, plant: Plant) -> str:
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
        """Convert days to week number (1-indexed)."""
        if days <= 0:
            return 0
        return (days - 1) // 7 + 1

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

    def _check_and_send_notifications(
        self,
        plant: Plant,
        current_stage: str,
        growspace: Growspace,
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
                    plant,
                    stage,
                    days,
                    growspace,
                ):
                    self._send_notification(plant, stage, days, growspace)

    def _should_send_notification(
        self,
        plant: Plant,
        stage: str,
        days: int,
        growspace: Growspace,
    ) -> bool:
        """Check if we should send a notification for this plant/stage/days combination."""
        notification_target = growspace.notification_target

        if not notification_target:
            _LOGGER.debug(
                "Skipping notification for plant %s (no target set). Stage=%s Days=%s",
                plant.plant_id,
                stage,
                days,
            )
            return False

        # ✅ NEW: Check if notifications are enabled for this growspace
        if not self.coordinator.is_notifications_enabled(plant.growspace_id):
            _LOGGER.debug(
                "Skipping notification for plant %s (notifications disabled via switch). Stage=%s Days=%s",
                plant.plant_id,
                stage,
                days,
            )
            return False

        # Check if notification already sent
        should_send = self.coordinator.should_send_notification(
            plant.plant_id,
            stage,
            days,
        )

        has_matching_event = any(
            event["days"] == days and event["stage"] == stage
            for event in DEFAULT_NOTIFICATION_EVENTS.values()
        )

        final_should_send = should_send and has_matching_event

        _LOGGER.debug(
            "Notification check: Plant=%s Stage=%s Days=%s HasTarget=%s NotificationsEnabled=%s AlreadySent=%s HasEvent=%s → %s",
            plant.plant_id,
            stage,
            days,
            bool(notification_target),
            self.coordinator.is_notifications_enabled(plant.growspace_id),
            not should_send,
            has_matching_event,
            final_should_send,
        )

        return final_should_send

    def _send_notification(
        self,
        plant: Plant,
        stage: str,
        days: int,
        growspace: Growspace,
    ):
        """Send notification for plant milestone."""
        notification_target = growspace.notification_target

        if not notification_target:
            _LOGGER.debug(
                "No notification target found for growspace %s",
                plant.growspace_id,
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
            self.coordinator.mark_notification_sent(plant.plant_id, stage, days),
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
            ),
        )

    async def async_added_to_hass(self) -> None:
        """When entity is added to hass."""
        self.coordinator.async_add_listener(self.async_write_ha_state)


class StrainLibrarySensor(SensorEntity):
    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the Strain Library Sensor."""
        self.coordinator = coordinator
        self._attr_name = "Growspace Strain Library"
        self._attr_unique_id = f"{DOMAIN}_strain_library"
        self._attr_icon = "mdi:leaf"

    @property
    def state(self) -> str:
        return "ok"

    @property
    def extra_state_attributes(self) -> dict:
        return {"strains": self.coordinator.get_strain_options()}

    async def async_added_to_hass(self):
        self.coordinator.async_add_listener(self.async_write_ha_state)


class GrowspaceListSensor(SensorEntity):
    """Exposes the list of growspaces as a sensor."""

    def __init__(self, coordinator: GrowspaceCoordinator) -> None:
        """Initialize the Growspace List Sensor."""
        self.coordinator = coordinator
        self._attr_name = "Growspaces List"
        self._attr_unique_id = f"{DOMAIN}_growspaces_list"
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
