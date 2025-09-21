from __future__ import annotations

from dataclasses import asdict
from .models import Plant, Growspace
from .utils import (
    calculate_days_since,
    parse_date_field,
    find_first_free_position,
    generate_growspace_grid,
)
from .strain_library import StrainLibrary
from .const import (
    DOMAIN,
    STORAGE_KEY,
    PLANT_STAGES,
    DATE_FIELDS,
    STORAGE_VERSION,
    STORAGE_KEY_STRAIN_LIBRARY,
    DEFAULT_NOTIFICATION_EVENTS,
    SPECIAL_GROWSPACES,
)

import logging
import uuid
from datetime import datetime, date
from typing import TYPE_CHECKING, Any, Optional

from dateutil import parser
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers import (
    device_registry as dr,
    entity_registry as er,
)
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util


_LOGGER = logging.getLogger(__name__)
if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.storage import Store

# Type aliases for better readability
PlantDict = dict[str, Any]
GrowspaceDict = dict[str, Any]
NotificationDict = dict[str, Any]
DateInput = str | datetime | date | None


class GrowspaceCoordinator(DataUpdateCoordinator):
    """Coordinator for Growspace Manager with improved organization and error handling."""

    def __init__(
        self,
        hass: HomeAssistant,
        data: Optional[dict] = None,
        entry_id: Optional[str] = None,
    ):
        """Initialize the GrowspaceCoordinator.

        Args:
            hass: The Home Assistant instance.
            store: The storage object for persisting data.
            data: Initial data dictionary for growspaces and plants.
            entry_id: The config entry ID for this integration.
        """

        super().__init__(hass, _LOGGER, name="growspace_manager")
        # Persistent data
        self.data: dict[str, Any] = data or {}
        self.plants: dict[str, Plant] = {
            pid: Plant(**p) if isinstance(p, dict) else p
            for pid, p in self.data.get("plants", {}).items()
        }
        self.growspaces: dict[str, Growspace] = {
            gid: Growspace(**g) if isinstance(g, dict) else g
            for gid, g in self.data.get("growspaces", {}).items()
        }
        # Initialize the store properly as an instance attribute
        self.store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self.notifications: dict[str, Any] = self.data.get("notifications_sent", {})
        # Strain library management
        self.strains = StrainLibrary(hass, STORAGE_VERSION, STORAGE_KEY_STRAIN_LIBRARY)

        self.update_data_property()

    # -----------------------------
    # Methods for editor dropdown
    # -----------------------------

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces for dropdown selection in editor.

        Returns:
            dict: {growspace_id: growspace_name}
        """
        return {
            gs_id: getattr(gs, "name", gs_id) for gs_id, gs in self.growspaces.items()
        }

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return sorted list of growspaces for dropdown, sorted by name."""
        return sorted(
            (
                (gs_id, getattr(gs, "name", gs_id))
                for gs_id, gs in self.growspaces.items()
            ),
            key=lambda x: x[1].lower(),
        )

    # =============================================================================
    # INITIALIZATION AND MIGRATION METHODS
    # =============================================================================

    def _migrate_legacy_growspaces(self) -> None:
        """Migrate legacy special growspace aliases to canonical forms."""
        try:
            for config in SPECIAL_GROWSPACES.values():
                canonical_id = config["canonical_id"]
                canonical_name = config["canonical_name"]
                aliases = config["aliases"]

                for alias in aliases:
                    self._migrate_special_alias_if_needed(
                        alias, canonical_id, canonical_name
                    )
        except ValueError as e:
            _LOGGER.debug("Special growspace migration skipped: %s", e)

    def _migrate_special_alias_if_needed(
        self, alias_id: str, canonical_id: str, canonical_name: str
    ) -> None:
        """Migrate alias growspace to canonical id and update plants."""
        if alias_id == canonical_id:
            return

        alias_exists = alias_id in self.growspaces
        canonical_exists = canonical_id in self.growspaces

        if alias_exists and not canonical_exists:
            self._create_canonical_from_alias(alias_id, canonical_id, canonical_name)
        elif alias_exists and canonical_exists:
            self._consolidate_alias_into_canonical(alias_id, canonical_id)

    def _create_canonical_from_alias(
        self, alias_id: str, canonical_id: str, canonical_name: str
    ) -> None:
        """Create canonical growspace from alias."""
        src = self.growspaces[alias_id]
        self.growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=int(
                getattr(src, "rows", 3)
                if isinstance(src, Growspace)
                else src.get("rows", 3)
            ),
            plants_per_row=int(
                getattr(src, "plants_per_row", 3)
                if isinstance(src, Growspace)
                else src.get("plants_per_row", 3)
            ),
            notification_target=getattr(src, "notification_target", None)
            if isinstance(src, Growspace)
            else src.get("notification_target"),
            device_id=getattr(src, "device_id", None)
            if isinstance(src, Growspace)
            else None,
        )

        self._migrate_plants_to_growspace(alias_id, canonical_id)
        self.growspaces.pop(alias_id, None)
        self.update_data_property()

        _LOGGER.info("Migrated growspace alias '%s' → '%s'", alias_id, canonical_id)

    def _consolidate_alias_into_canonical(
        self, alias_id: str, canonical_id: str
    ) -> None:
        """Consolidate alias growspace into existing canonical."""
        self._migrate_plants_to_growspace(alias_id, canonical_id)
        self.growspaces.pop(alias_id, None)
        self.update_data_property()

        _LOGGER.info(
            "Consolidated growspace alias '%s' into '%s'", alias_id, canonical_id
        )

    def _migrate_plants_to_growspace(self, from_id: str, to_id: str) -> None:
        """Migrate all plants from one growspace to another."""
        for plant in self.plants.values():
            if plant.growspace_id == from_id:
                plant.growspace_id = to_id

    # =============================================================================
    # UTILITY AND HELPER METHODS
    # =============================================================================

    def _get_plant_stage(self, plant: Plant) -> str:
        if getattr(plant, "cure_start", None):
            return "cure"
        if getattr(plant, "dry_start", None):
            return "dry"
        if getattr(plant, "flower_start", None):
            return "flower"
        if getattr(plant, "veg_start", None):
            return "veg"
        if getattr(plant, "clone_start", None):
            return "clone"
        if getattr(plant, "mother_start", None):
            return "mother"
        return "seedling"

    def get_plant(self, plant_id: str) -> Plant | None:
        return self.plants.get(plant_id)

    def _canonical_special(self, gs_id: str) -> tuple[str, str]:
        """Return canonical (id, name) for special growspaces."""
        for config in SPECIAL_GROWSPACES.values():
            canonical_id = config["canonical_id"]
            canonical_name = config["canonical_name"]
            aliases = config["aliases"]

            for alias in aliases:
                self._migrate_special_alias_if_needed(
                    alias, canonical_id, canonical_name
                )

        growspace = self.growspaces.get(gs_id)
        if growspace:
            return gs_id, growspace.name  # access attribute, not dict key
        return gs_id, gs_id

    def _validate_growspace_exists(self, growspace_id: str) -> None:
        """Validate that a growspace exists."""
        if growspace_id not in self.growspaces:
            raise ValueError(f"Growspace {growspace_id} does not exist")

    def _validate_plant_exists(self, plant_id: str) -> None:
        """Validate that a plant exists."""
        if plant_id not in self.plants:
            raise ValueError(f"Plant {plant_id} does not exist")

    def _validate_position_bounds(self, growspace_id: str, row: int, col: int) -> None:
        """Validate position is within growspace bounds."""
        growspace = self.growspaces[growspace_id]
        max_rows = int(growspace.rows)
        max_cols = int(growspace.plants_per_row)

        if row < 1 or row > max_rows:
            raise ValueError(f"Row {row} is outside growspace bounds (1-{max_rows})")
        if col < 1 or col > max_cols:
            raise ValueError(f"Column {col} is outside growspace bounds (1-{max_cols})")

    def _validate_position_not_occupied(
        self,
        growspace_id: str,
        row: int,
        col: int,
        exclude_plant_id: str | None = None,
    ) -> None:
        """Validate position is not occupied by another plant."""
        existing_plants = self.get_growspace_plants(growspace_id)
        for existing_plant in existing_plants:
            if (
                existing_plant.plant_id != exclude_plant_id
                and existing_plant.row == row
                and existing_plant.col == col
            ):
                raise ValueError(
                    f"Position ({row},{col}) is already occupied by {existing_plant.strain}"
                )

    def _find_first_available_position(self, growspace_id: str) -> tuple[int, int]:
        growspace = self.growspaces[growspace_id]
        occupied = {(p.row, p.col) for p in self.get_growspace_plants(growspace_id)}
        return find_first_free_position(growspace, occupied)

    def _parse_date_field(self, date_value: str | datetime | date | None) -> str | None:
        return parse_date_field(date_value)

    def _parse_date_fields(self, kwargs: dict[str, Any]) -> None:
        """Parse all date fields in kwargs in-place."""
        for field in DATE_FIELDS:
            if field in kwargs:
                kwargs[field] = self._parse_date_field(kwargs[field])

    def _calculate_days(self, start_date: str | date | datetime | None) -> int:
        """Calculate days since a given date."""
        if not start_date:
            return 0

        try:
            if isinstance(start_date, datetime):
                dt = start_date.date()
            elif isinstance(start_date, date):
                dt = start_date
            elif isinstance(start_date, str):
                dt = parser.isoparse(start_date).date()
            else:
                return 0

            return (date.today() - dt).days
        except Exception as e:
            _LOGGER.warning("Failed to calculate days for date %s: %s", start_date, e)
            return 0

    def _generate_unique_name(self, base_name: str) -> str:
        """Generate a unique growspace name."""
        existing_names = {gs.name.lower() for gs in self.growspaces.values()}
        name = base_name
        counter = 1

        while name.lower() in existing_names:
            name = f"{base_name} {counter}"
            counter += 1

        return name

    # =============================================================================
    # SPECIAL GROWSPACE MANAGEMENT
    # =============================================================================

    def _ensure_special_growspace(
        self, growspace_id: str, name: str, rows: int = 3, plants_per_row: int = 3
    ) -> str:
        """Ensure a special growspace exists with a stable id and return its id."""
        # Get canonical form
        canonical_id, canonical_name = self._canonical_special(growspace_id)

        # Clean up any legacy aliases
        self._cleanup_legacy_aliases(canonical_id)

        # Create or update the canonical growspace
        if canonical_id not in self.growspaces:
            self._create_special_growspace(
                canonical_id, canonical_name, rows, plants_per_row
            )
        else:
            self._update_special_growspace_name(canonical_id, canonical_name)

        self.update_data_property()
        return canonical_id

    def _cleanup_legacy_aliases(self, canonical_id: str) -> None:
        """Remove legacy aliases for a canonical growspace."""
        config = SPECIAL_GROWSPACES.get(canonical_id, {})
        aliases = config.get("aliases", [])

        for alias in aliases:
            for legacy_id in list(self.growspaces.keys()):
                if legacy_id.startswith(alias):
                    self._migrate_plants_to_growspace(legacy_id, canonical_id)
                    self.growspaces.pop(legacy_id, None)
                    _LOGGER.info("Removed legacy growspace: %s", legacy_id)

    def _create_special_growspace(
        self, canonical_id: str, canonical_name: str, rows: int, plants_per_row: int
    ) -> None:
        """Create a new special growspace."""
        self.growspaces[canonical_id] = Growspace(
            id=canonical_id,
            name=canonical_name,
            rows=rows,
            plants_per_row=plants_per_row,
        )
        _LOGGER.info(
            "Created canonical growspace: %s with name '%s'",
            canonical_id,
            canonical_name,
        )

    def _update_special_growspace_name(
        self, canonical_id: str, canonical_name: str
    ) -> None:
        """Update the name of an existing special growspace if needed."""
        existing = self.growspaces[canonical_id]
        if existing.name != canonical_name:
            existing.name = canonical_name
            _LOGGER.info(
                "Updated growspace name: %s -> '%s'", canonical_id, canonical_name
            )

    def _ensure_mother_growspace(self) -> str:
        """Ensure the 'mother' growspace exists."""
        return self._ensure_special_growspace(
            "mother", "mother", rows=3, plants_per_row=3
        )

    # =============================================================================
    # DATA UPDATE COORDINATOR OVERRIDE
    # =============================================================================

    async def _async_update_data(self) -> dict[str, Any]:
        """Refresh data. Called by the DataUpdateCoordinator."""
        self.update_data_property()

        return self.data

    async def async_save(self) -> None:
        await self.store.async_save(
            {
                "plants": {pid: asdict(p) for pid, p in self.plants.items()},
                "growspaces": {gid: asdict(g) for gid, g in self.growspaces.items()},
                "strain_library": list(self.strains.get_all()),
            }
        )

    async def async_load(self) -> None:
        data = await self.store.async_load()
        if not data:
            return

        self.plants = {pid: Plant(**p) for pid, p in data.get("plants", {}).items()}
        self.growspaces = {
            gid: Growspace(**g) for gid, g in data.get("growspaces", {}).items()
        }
        self.strains = StrainLibrary(
            self.hass, STORAGE_VERSION, STORAGE_KEY_STRAIN_LIBRARY
        )

    def update_data_property(self) -> None:
        """Keep self.data in sync with coordinator state."""
        self.data = {
            "growspaces": self.growspaces,
            "plants": self.plants,
            "notifications_sent": self.notifications,
        }

    # =============================================================================
    # GROWSPACE MANAGEMENT METHODS
    # =============================================================================

    async def async_add_growspace(
        self,
        name: str,
        rows: int = 3,
        plants_per_row: int = 3,
        notification_target: str | None = None,
        device_id: str | None = None,
    ) -> Growspace:
        """Add a new growspace."""
        growspace_id = str(uuid.uuid4())
        growspace = Growspace(
            id=growspace_id,
            name=name.strip(),
            rows=rows,
            plants_per_row=plants_per_row,
            notification_target=notification_target,
            device_id=device_id,
        )
        self.growspaces[growspace_id] = growspace
        await self.async_save()
        return growspace

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all its plants."""
        self._validate_growspace_exists(growspace_id)

        # Remove all plants in this growspace
        plants_to_remove = [
            plant_id
            for plant_id, plant in self.plants.items()
            if plant.growspace_id == growspace_id
        ]

        for plant_id in plants_to_remove:
            self.plants.pop(plant_id, None)
            self.notifications.pop(plant_id, None)

        growspace_name = self.growspaces[growspace_id].name
        self.growspaces.pop(growspace_id, None)

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Removed growspace %s (%s) and %d plants",
            growspace_id,
            growspace_name,
            len(plants_to_remove),
        )

    # =============================================================================
    # PLANT MANAGEMENT METHODS
    # =============================================================================

    async def async_add_plant(
        self,
        growspace_id: str,
        strain: str,
        phenotype: str = "",
        row: int = 1,
        col: int = 1,
        stage: str = "seedling",
        type: str = "normal",
        device_id: str | None = None,
    ) -> Plant:
        plant_id = str(uuid.uuid4())
        today = date.today().isoformat()
        plant = Plant(
            plant_id=plant_id,
            growspace_id=growspace_id,
            strain=strain.strip(),
            phenotype=phenotype or "",
            row=row,
            col=col,
            stage=stage,
            created_at=today,
        )
        self.plants[plant_id] = plant

        await self.async_save()
        return plant

    async def _handle_clone_creation(
        self,
        plant_id: str,
        growspace_id: str,
        strain: str,
        phenotype: str,
        row: int,
        col: int,
        **kwargs: Any,
    ) -> str:
        """Handle clone creation by copying from mother plant."""

        # Check if source_mother is provided
        source_mother_id = kwargs.get("source_mother")

        if source_mother_id:
            # Validate mother plant exists
            self._validate_plant_exists(source_mother_id)
            mother_plant = self.plants[source_mother_id]

            # Verify it's actually a mother plant
            if mother_plant.stage != "mother":
                _LOGGER.warning(
                    "Source plant %s is not in mother stage, but proceeding with clone creation",
                    source_mother_id,
                )
        else:
            # Try to find a mother plant with matching strain
            mother_plant = self._find_mother_by_strain(strain, phenotype)
            if mother_plant:
                source_mother_id = mother_plant.plant_id
                _LOGGER.info(
                    "Found mother plant %s for strain %s", source_mother_id, strain
                )
            else:
                _LOGGER.warning(
                    "No mother plant found for strain %s, creating clone without source",
                    strain,
                )
                mother_plant = None

        now = date.today().isoformat()

        # Create clone data
        clone_data = {
            "plant_id": plant_id,
            "growspace_id": growspace_id,
            "strain": str(strain).strip(),
            "row": int(row),
            "col": int(col),
            "stage": "clone",
            "type": "clone",
            "clone_start": now,
            "created_at": now,
        }

        # Copy relevant data from mother plant if available
        if mother_plant:
            clone_data.update(
                {
                    "phenotype": mother_plant.phenotype,
                    "source_mother": source_mother_id,
                    # Copy any additional metadata you want to preserve
                }
            )

        # Override with any explicitly provided kwargs
        clone_data.update(
            {k: v for k, v in kwargs.items() if k not in ["stage", "clone_start"]}
        )

        # Parse dates
        self._parse_date_fields(clone_data)

        # Save the clone
        self.plants[plant_id] = Plant(**clone_data)
        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Created clone %s: %s at (%d,%d) from mother %s",
            plant_id,
            strain,
            row,
            col,
            source_mother_id or "unknown",
        )

        return plant_id

    def _find_mother_by_strain(self, strain: str, phenotype: str) -> Plant | None:
        """Find a mother plant with the specified strain."""
        for plant in self.plants.values():
            if (
                plant.stage == "mother"
                and plant.strain.lower() == strain.lower()
                and plant.phenotype.lower() == phenotype.lower()
            ):
                return plant

        return None

    async def async_add_mother_plant(
        self,
        phenotype: str,
        strain: str,
        row: int,
        col: int,
        **kwargs: Any,
    ) -> Plant:
        """Add a plant to the permanent mother growspace."""
        mother_id: str = self._ensure_mother_growspace()
        kwargs["type"] = "mother"

        plant: Plant = await self.async_add_plant(
            mother_id, strain, phenotype, row, col, **kwargs
        )
        return plant

    async def async_take_clones(
        self,
        mother_plant_id: str,
        num_clones: int,
        target_growspace_id: str | None,
        target_growspace_name: str | None,
        transition_date: str | None,
    ) -> list[str]:
        """Take clones from a mother plant into clone growspace."""
        self._validate_plant_exists(mother_plant_id)

        mother = self.plants[mother_plant_id]
        clone_gs_id = self._ensure_special_growspace("clone", "clone", 5, 5)
        clone_ids = []

        for _ in range(num_clones):
            row, col = self._find_first_available_position(clone_gs_id)
            clone_data = {
                "strain": mother.strain,
                "phenotype": mother.phenotype,
                "type": "clone",
                "source_mother": mother_plant_id,
                "stage": "clone",
                "growspace": target_growspace_name,
                "clone_start": datetime.today().isoformat(),
            }
            clone_id = await self.async_add_plant(
                clone_gs_id, **clone_data, row=row, col=col
            )
            clone_ids.append(clone_id)

        return clone_ids

    async def async_transition_clone_to_veg(self, clone_id: str) -> None:
        """Transition a clone to veg in veg growspace."""
        self._validate_plant_exists(clone_id)

        clone = self.plants[clone_id]
        if clone.stage != "clone":
            raise ValueError("Plant is not in clone stage")

        veg_gs_id = self._ensure_special_growspace("veg", "veg", 5, 5)
        row, col = self._find_first_available_position(veg_gs_id)

        await self.async_update_plant(
            clone_id,
            growspace_id=veg_gs_id,
            row=row,
            col=col,
            stage="veg",
            veg_start=datetime.today().isoformat(),
        )

    async def async_update_plant(self, plant_id: str, **updates) -> Plant:
        """Update fields of an existing plant."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} does not exist")

        for key, value in updates.items():
            if hasattr(plant, key):
                setattr(plant, key, value)
        plant.updated_at = date.today().isoformat()

        await self.async_save()
        return plant

    def _handle_position_update(
        self,
        plant_id: str,
        plant: Plant,
        force_position: bool,
        kwargs: dict[str, Any],
    ) -> None:
        """Handle position updates with proper validation."""
        new_row = int(kwargs.get("row", plant.row))
        new_col = int(kwargs.get("col", plant.col))

        growspace_id = kwargs.get("growspace_id", plant.growspace_id)

        # Validate bounds
        self._validate_position_bounds(growspace_id, new_row, new_col)

        # Check for conflicts unless force_position is True
        if not force_position and (new_row != plant.row or new_col != plant.col):
            self._validate_position_not_occupied(
                growspace_id, new_row, new_col, plant_id
            )

    async def async_move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position."""
        await self.async_update_plant(plant_id, row=new_row, col=new_col)

    async def async_switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants."""
        self._validate_plant_exists(plant1_id)
        self._validate_plant_exists(plant2_id)

        plant1 = self.plants[plant1_id]
        plant2 = self.plants[plant2_id]

        # Ensure both plants are in the same growspace
        if plant1.growspace_id != plant2.growspace_id:
            raise ValueError("Cannot switch plants in different growspaces")

        # Store and swap positions
        plant1_row, plant1_col = plant1.row, plant1.col
        plant2_row, plant2_col = plant2.row, plant2.col

        plant1.row, plant1.col = plant2_row, plant2_col
        plant2.row, plant2.col = plant1_row, plant1_col

        # Update timestamps
        update_time = date.today().isoformat()
        plant1.updated_at = update_time
        plant2.updated_at = update_time

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Switched positions: %s (%s) moved from (%d,%d) to (%d,%d), %s (%s) moved from (%d,%d) to (%d,%d)",
            plant1_id,
            plant1.strain,
            plant1_col,
            plant1_row,
            plant2_col,
            plant2_row,
            plant2_id,
            plant2.strain,
            plant2_row,
            plant2_col,
            plant1_row,
            plant1_col,
        )

    async def switch_plants_service(self, plant1_id: str, plant2_id: str) -> None:
        """Service wrapper for switching plants."""
        await self.async_switch_plants(plant1_id, plant2_id)

    async def async_transition_plant_stage(
        self, plant_id: str, new_stage: str, transition_date: str | None
    ) -> None:
        """Transition a plant to a new growth stage."""
        self._validate_plant_exists(plant_id)

        if new_stage not in PLANT_STAGES:
            raise ValueError(
                f"Invalid stage {new_stage}. Must be one of: {PLANT_STAGES}"
            )

        # Parse transition date
        parsed_date = (
            self._parse_date_field(transition_date) or date.today().isoformat()
        )
        # update_data = {f"{new_stage}_start": parsed_date}

        await self.async_update_plant(
            plant_id,
            stage=new_stage,
            **{f"{new_stage}_start": parsed_date},
            force_position=False,
        )
        _LOGGER.info("Transitioned plant %s to %s stage", plant_id, new_stage)

    async def async_start_flowering(self, plant_id: str) -> Plant:
        """Set a plant to flowering stage."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "flowering"
        plant.flower_start = date.today().isoformat()
        plant.updated_at = plant.flower_start
        await self.async_save()
        return plant

    async def async_start_drying(self, plant_id: str) -> Plant:
        """Set a plant to drying stage."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "drying"
        plant.dry_start = date.today().isoformat()
        plant.updated_at = plant.dry_start
        await self.async_save()
        return plant

    async def async_start_curing(self, plant_id: str) -> Plant:
        """Set a plant to curing stage."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "curing"
        plant.cure_start = date.today().isoformat()
        plant.updated_at = plant.cure_start
        await self.async_save()
        return plant

    async def async_harvest(self, plant_id: str) -> Plant:
        """Mark a plant as harvested."""
        plant = self.plants.get(plant_id)
        if not plant:
            raise ValueError(f"Plant {plant_id} not found")

        plant.stage = "dry"
        plant.dry_start = date.today().isoformat()
        plant.updated_at = plant.dry_start
        await self.async_save()
        return plant

    async def async_harvest_plant(
        self,
        plant_id: str,
        target_growspace_id: str | None,
        target_growspace_name: str | None,
        transition_date: str | None,
    ) -> None:
        """Harvest a plant and optionally move it to another growspace."""
        self._validate_plant_exists(plant_id)

        plant = self.plants[plant_id]
        transition_date = transition_date or date.today().isoformat()

        # Log harvest start
        stage_before = self._get_plant_stage(plant)
        _LOGGER.info(
            "Harvest start: plant_id=%s stage=%s current_growspace=%s target_id=%s target_name=%s date=%s",
            plant_id,
            stage_before,
            plant.growspace_id,
            target_growspace_id,
            target_growspace_name,
            transition_date,
        )

        # Handle harvest logic
        moved = await self._handle_harvest_logic(
            plant_id, plant, target_growspace_id, target_growspace_name, transition_date
        )

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Harvest end: plant_id=%s moved=%s target_growspace_id=%s row=%s col=%s stage=%s dry_start=%s cure_start=%s",
            plant_id,
            moved,
            target_growspace_id,
            plant.row,
            plant.col,
            plant.stage,
            plant.dry_start,
            plant.cure_start,
        )

    async def _handle_harvest_logic(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str | None,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Handle the core harvest logic and return whether plant was moved."""
        # Explicit target provided
        if target_growspace_id and target_growspace_id in self.growspaces:
            return await self._harvest_to_explicit_target(
                plant_id,
                plant,
                target_growspace_id,
                target_growspace_name,
                transition_date,
            )

        # Auto-flow based on hints or current stage
        return await self._harvest_auto_flow(
            plant_id, plant, target_growspace_name, transition_date
        )

    async def _harvest_to_explicit_target(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Handle harvest to explicit target growspace."""
        plant.growspace_id = target_growspace_id

        try:
            row, col = self._find_first_available_position(target_growspace_id)
            plant.row, plant.col = row, col
        except ValueError as e:
            _LOGGER.warning(
                "Failed to find position in target growspace %s: %s",
                target_growspace_id,
                e,
            )

        # Set stage based on target
        if target_growspace_id == "dry" or (
            target_growspace_name and "dry" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="dry", dry_start=transition_date
            )
        elif target_growspace_id == "cure" or (
            target_growspace_name and "cure" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="cure", cure_start=transition_date
            )
        elif target_growspace_id == "clone" or (
            target_growspace_name and "clone" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="clone", clone_start=transition_date
            )
        elif target_growspace_id == "mother" or (
            target_growspace_name and "mother" in target_growspace_name.lower()
        ):
            await self.async_update_plant(
                plant_id, stage="mother", clone_start=transition_date
            )

        _LOGGER.info("Moved plant %s to growspace %s", plant_id, target_growspace_id)
        return True

    async def _harvest_auto_flow(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Handle auto-flow harvest logic."""
        current_stage = self._get_plant_stage(plant)

        # Handle name hints
        if target_growspace_name:
            if "dry" in target_growspace_name.lower():
                return await self._move_to_dry_growspace(
                    plant_id, plant, transition_date
                )
            if "cure" in target_growspace_name.lower():
                return await self._move_to_cure_growspace(
                    plant_id, plant, transition_date
                )
            if "clone" in target_growspace_name.lower():
                return await self._move_to_clone_growspace(
                    plant_id, plant, transition_date
                )
            if "mother" in target_growspace_name.lower():
                return await self._move_to_clone_growspace(
                    plant_id, plant, transition_date
                )

        # Handle stage transitions
        if current_stage == "flower":
            return await self._move_to_dry_growspace(plant_id, plant, transition_date)
        if current_stage == "dry":
            return await self._move_to_cure_growspace(plant_id, plant, transition_date)
        if current_stage == "mother":
            return await self._move_to_clone_growspace(plant_id, plant, transition_date)
        # Fallback: move to dry
        return await self._move_to_dry_growspace(plant_id, plant, transition_date)

    async def _move_to_clone_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move plant to clone growspace."""
        clone_id = self._ensure_special_growspace("clone", "clone", 5, 5)
        plant.growspace_id = clone_id

        try:
            new_row, new_col = self._find_first_available_position(clone_id)
            plant.row, plant.col = new_row, new_col
            await self.async_update_plant(
                plant_id,
                growspace_id=clone_id,
                row=new_row,
                col=new_col,
                stage="clone",
                clone_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in clone growspace: %s", e)

        plant.clone_start = transition_date
        plant.stage = "clone"
        _LOGGER.info("Moved plant %s → clone (ID: %s)", plant_id, clone_id)
        return True

    async def _move_to_dry_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move plant to dry growspace."""
        dry_id = self._ensure_special_growspace("dry", "dry")
        plant.growspace_id = dry_id

        growspace = self.growspaces.get(dry_id)
        if growspace and growspace.device_id:
            plant.device_id = growspace.device_id

        try:
            new_row, new_col = self._find_first_available_position(dry_id)
            plant.row, plant.col = new_row, new_col
            await self.async_update_plant(
                plant_id,
                growspace_id=dry_id,
                row=new_row,
                col=new_col,
                stage="dry",
                dry_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in dry growspace: %s", e)

        plant.dry_start = transition_date
        plant.stage = "dry"
        _LOGGER.info("Moved plant %s → dry (ID: %s)", plant_id, dry_id)
        return True

    async def _move_to_cure_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move plant to cure growspace."""
        cure_id = self._ensure_special_growspace("cure", "cure")
        plant.growspace_id = cure_id

        try:
            new_row, new_col = self._find_first_available_position(cure_id)
            plant.row, plant.col = new_row, new_col
            await self.async_update_plant(
                plant_id,
                growspace_id=cure_id,
                row=new_row,
                col=new_col,
                stage="cure",
                cure_start=transition_date,
            )
        except ValueError as e:
            _LOGGER.warning("Failed to assign position in cure growspace: %s", e)

        plant.cure_start = transition_date
        plant.stage = "cure"
        _LOGGER.info("Moved plant %s → cure (ID: %s)", plant_id, cure_id)
        return True

    async def async_remove_plant(self, plant_id: str) -> bool:
        """Remove a plant from the coordinator."""
        if plant_id in self.plants:
            del self.plants[plant_id]
            await self.async_save()
            return True
        return False

    async def _remove_plant_entities(self, plant_id: str) -> None:
        """Remove all entities for a given plant from Home Assistant."""
        entity_registry = er.async_get(self.hass)

        # Find all entities belonging to this plant
        for entity_id, entry in list(entity_registry.entities.items()):
            if entry.unique_id.startswith(plant_id):
                _LOGGER.info("Removing entity %s for plant %s", entity_id, plant_id)
                entity_registry.async_remove(entity_id)

    # =============================================================================
    # STRAIN LIBRARY MANAGEMENT
    # =============================================================================

    def add_strain(self, strain: str) -> None:
        self.strains.add(strain)

    def remove_strain(self, strain: str) -> None:
        self.strains.remove(strain)

    def get_strain_options(self) -> list[str]:
        return self.strains.get_all()

    def export_strain_library(self) -> list[str]:
        """Export all strains from the library."""
        return self.get_strain_options()

    async def import_strains(self, strains: list[str], replace: bool = False) -> int:
        return await self.strains.import_strains(strains, replace)

    async def clear_strains(self) -> int:
        return await self.strains.clear()

    # =============================================================================
    # QUERY AND CALCULATION METHODS
    # =============================================================================

    def get_growspace_plants(self, growspace_id: str) -> list[Plant]:
        """Get all plants in a specific growspace."""
        return [
            plant
            for plant in self.plants.values()
            if plant.growspace_id == growspace_id
        ]

    def calculate_days_in_stage(self, plant: Plant, stage: str) -> int:
        """Calculate days a plant has been in a specific stage."""
        start_date = getattr(plant, f"{stage}_start", None)
        return self._calculate_days(start_date)

    def get_growspace_grid(self, growspace_id: str) -> list[list[str | None]]:
        growspace = self.growspaces[growspace_id]
        plants = self.get_growspace_plants(growspace_id)
        return generate_growspace_grid(
            int(growspace.rows), int(growspace.plants_per_row), plants
        )

    def _guess_overview_entity_id(self, growspace_id: str) -> str:
        """Best-effort guess of the overview sensor entity_id for a growspace."""
        # Handle special cases first
        if growspace_id in ("dry", "dry_overview"):
            return "sensor.dry"
        if growspace_id in ("cure", "cure_overview"):
            return "sensor.cure"
        if growspace_id in ("mother", "mother_overview"):
            return "sensor.mother"
        if growspace_id in ("clone", "clone_overview"):
            return "sensor.clone"
        # General case
        growspace = self.growspaces.get(growspace_id)
        # Use getattr with default in case the attribute doesn't exist
        name = getattr(growspace, "name", growspace_id) if growspace else growspace_id

        # Simple slugify: lowercase, spaces->underscore, keep alnum/underscore only
        slug = "".join(
            ch if ch.isalnum() or ch == "_" else "_"
            for ch in str(name).lower().replace(" ", "_")
        )

        # Collapse repeated underscores
        while "__" in slug:
            slug = slug.replace("__", "_")

        return f"sensor.{slug}"

    # =============================================================================
    # NOTIFICATION MANAGEMENT
    # =============================================================================

    def should_send_notification(self, plant_id: str, stage: str, days: int) -> bool:
        """Check if a notification should be sent for a plant."""
        return (
            not self.notifications.get(plant_id, {})
            .get(stage, {})
            .get(str(days), False)
        )

    async def mark_notification_sent(
        self, plant_id: str, stage: str, days: int
    ) -> None:
        """Mark a notification as sent to prevent duplicates."""
        if plant_id not in self.notifications:
            self.notifications[plant_id] = {}
        if stage not in self.notifications[plant_id]:
            self.notifications[plant_id][stage] = {}

        self.notifications[plant_id][stage][str(days)] = True
        await self.async_save()
