from __future__ import annotations

import logging
import uuid
from datetime import datetime, date
from typing import TYPE_CHECKING, Any

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
        self, hass: HomeAssistant, store: Store, data: dict[str, Any], entry_id: str
    ) -> None:
        """Initialize the GrowspaceCoordinator.

        Args:
            hass: The Home Assistant instance.
            store: The storage object for persisting data.
            data: Initial data dictionary for growspaces and plants.
            entry_id: The config entry ID for this integration.
        """
        super().__init__(hass, _LOGGER, name="growspace_manager")

        self.hass = hass
        self.store = store
        self.entry_id = entry_id
        self.data = data or {}

        # Core data
        self.growspaces: dict[str, GrowspaceDict] = self.data.get("growspaces", {})
        self.plants: dict[str, PlantDict] = self.data.get("plants", {})
        self.notifications: NotificationDict = self.data.get("notifications_sent", {})
        # Strain library management
        self.strain_library: set[str] = set()
        self.strain_store: Store = Store(
            hass, STORAGE_VERSION, STORAGE_KEY_STRAIN_LIBRARY
        )

        self.update_data_property()

    # -----------------------------
    # Methods for editor dropdown
    # -----------------------------

    def get_growspace_options(self) -> dict[str, str]:
        """Return growspaces for dropdown selection in editor.

        Returns:
            dict: {growspace_id: growspace_name}
        """
        return {gs_id: gs.get("name", gs_id) for gs_id, gs in self.growspaces.items()}

    def get_sorted_growspace_options(self) -> list[tuple[str, str]]:
        """Return sorted list of growspaces for dropdown, sorted by name."""
        return sorted(
            ((gs_id, gs.get("name", gs_id)) for gs_id, gs in self.growspaces.items()),
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
        self.growspaces[canonical_id] = {
            "id": canonical_id,
            "name": canonical_name,
            "rows": int(src.get("rows", 3)),
            "plants_per_row": int(src.get("plants_per_row", 3)),
            "notification_target": src.get("notification_target"),
            "created_at": src.get("created_at") or date.today().isoformat(),
        }

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
            if plant.get("growspace_id") == from_id:
                plant["growspace_id"] = to_id

    # =============================================================================
    # UTILITY AND HELPER METHODS
    # =============================================================================

    def _get_plant_stage(self, plant: dict[str, Any]) -> str:
        """Determine current stage for a plant using explicit stage or dates."""
        # Infer from dates: priority cure > dry > flower > veg > clone > mother > seedling
        if plant.get("cure_start"):
            return "cure"
        if plant.get("dry_start"):
            return "dry"
        if plant.get("flower_start"):
            return "flower"
        if plant.get("veg_start"):
            return "veg"
        if plant.get("clone_start"):
            return "clone"
        if plant.get("mother_start"):
            return "mother"
        return "seedling"

    def get_plant(self, plant_id: str):
        for growspace in self.growspaces.values():
            for plant in growspace.get("plants", []):
                if plant.get("plant_id") == plant_id:
                    return plant
        return None

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

        return gs_id, self.growspaces.get(gs_id, {}).get("name", gs_id)

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
        max_rows = int(growspace["rows"])
        max_cols = int(growspace["plants_per_row"])

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
                existing_plant["plant_id"] != exclude_plant_id
                and existing_plant["row"] == row
                and existing_plant["col"] == col
            ):
                raise ValueError(
                    f"Position ({row},{col}) is already occupied by {existing_plant['strain']}"
                )

    def _find_first_available_position(self, growspace_id: str) -> tuple[int, int]:
        """Find the first free (row, col) position in a growspace grid."""
        self._validate_growspace_exists(growspace_id)

        growspace = self.growspaces[growspace_id]
        occupied = {
            (int(p["row"]), int(p["col"]))
            for p in self.get_growspace_plants(growspace_id)
        }

        total_rows = int(growspace["rows"])
        total_cols = int(growspace["plants_per_row"])

        for row in range(1, total_rows + 1):
            for col in range(1, total_cols + 1):
                if (row, col) not in occupied:
                    return row, col
        return total_rows, total_cols

    def _parse_date_field(self, date_value: str | datetime | date | None) -> str | None:
        """Parse and normalize date field to ISO string format."""
        if not date_value:
            return None

        try:
            if isinstance(date_value, str):
                return parser.isoparse(date_value).date().isoformat()
            if isinstance(date_value, datetime):
                return date_value.date().isoformat()
            if isinstance(date_value, date):
                return date_value.isoformat()
        except ValueError as e:
            _LOGGER.warning("Failed to parse date %s: %s", date_value, e)

        return None

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
        existing_names = {gs["name"].lower() for gs in self.growspaces.values()}
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
        self.growspaces[canonical_id] = {
            "id": canonical_id,
            "name": canonical_name,
            "rows": int(rows),
            "plants_per_row": int(plants_per_row),
            "notification_target": None,
            "created_at": date.today().isoformat(),
        }
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
        if existing.get("name") != canonical_name:
            existing["name"] = canonical_name
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

    async def async_load(self):
        """Load stored data from disk."""
        stored = await self.store.async_load() or {}
        self.growspaces = stored.get("growspaces", {})
        self.plants = stored.get("plants", {})
        # Load strains separately
        stored_strains = await self.strain_store.async_load() or []
        self.strain_library = set(stored_strains)
        self.notifications = stored.get("notifications_sent", {})
        self.update_data_property()

    async def async_save(self) -> None:
        """Persist growspaces, plants, notifications to disk."""
        await self.store.async_save(
            {
                "growspaces": self.growspaces,
                "plants": self.plants,
                "notifications_sent": self.notifications,
            }
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
        rows: int,
        plants_per_row: int,
        notification_target: str | None,
    ) -> str:
        """Add a new growspace."""
        growspace_id = f"growspace_{uuid.uuid4().hex[:8]}"
        unique_name = self._generate_unique_name(name)

        self.growspaces[growspace_id] = {
            "id": growspace_id,
            "name": unique_name,
            "rows": int(rows),
            "plants_per_row": int(plants_per_row),
            "notification_target": notification_target,
            "created_at": date.today().isoformat(),
        }

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Added growspace %s: %s (%dx%d)",
            growspace_id,
            unique_name,
            rows,
            plants_per_row,
        )
        return growspace_id

    async def async_remove_growspace(self, growspace_id: str) -> None:
        """Remove a growspace and all its plants."""
        self._validate_growspace_exists(growspace_id)

        # Remove all plants in this growspace
        plants_to_remove = [
            plant_id
            for plant_id, plant in self.plants.items()
            if plant["growspace_id"] == growspace_id
        ]

        for plant_id in plants_to_remove:
            self.plants.pop(plant_id, None)
            self.notifications.pop(plant_id, None)

        growspace_name = self.growspaces[growspace_id]["name"]
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
        phenotype: str,
        strain: str,
        row: int,
        col: int,
        **kwargs: Any,
    ) -> str:
        """Add a plant to a growspace and automatically set only the correct stage start date."""
        self._validate_growspace_exists(growspace_id)
        self._validate_position_bounds(growspace_id, row, col)
        self._validate_position_not_occupied(growspace_id, row, col)

        plant_id = f"plant_{uuid.uuid4().hex[:8]}"
        growspace = self.growspaces[growspace_id]
        growspace_name = growspace.get("name", "unknown")

        if not strain or not strain.strip():
            raise ValueError("Strain name cannot be empty")
        self.strain_library.add(strain.strip())

        # Special handling for clone growspace
        if growspace_name.lower() == "clone" or growspace_id == "clone":
            return await self._handle_clone_creation(
                plant_id, growspace_id, strain, phenotype, row, col, **kwargs
            )
        # Determine stage
        if growspace_name in ["mother", "clone", "veg", "flower", "dry", "cure"]:
            stage = growspace_name
        elif "veg_start" in kwargs:
            stage = "veg"
        else:
            stage = "seedling"
        now = date.today().isoformat()

        # Map stages to their start date fields
        stage_start_field_map = {
            "seedling": "seedling_start",
            "clone": "clone_start",
            "mother": "mother_start",
            "veg": "veg_start",
            "flower": "flower_start",
            "dry": "dry_start",
            "cure": "cure_start",
        }

        # Only set the start date field corresponding to the plant's stage
        start_field = stage_start_field_map.get(stage)
        if start_field and not kwargs.get(start_field):
            kwargs[start_field] = now

        # Parse dates
        self._parse_date_fields(kwargs)

        # Create plant record
        plant_data = {
            "plant_id": plant_id,
            "growspace_id": growspace_id,
            "strain": str(strain).strip(),
            "row": int(row),
            "col": int(col),
            "stage": stage,
            "created_at": now,
            **kwargs,
        }
        plant_data["phenotype"] = phenotype.strip() if phenotype else ""

        self.plants[plant_id] = plant_data
        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Added plant %s: %s at (%d,%d) in %s stage in %s growspace",
            plant_id,
            strain,
            row,
            col,
            stage,
            growspace_name,
        )

        return plant_id

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
            if mother_plant.get("stage") != "mother":
                _LOGGER.warning(
                    "Source plant %s is not in mother stage, but proceeding with clone creation",
                    source_mother_id,
                )
        else:
            # Try to find a mother plant with matching strain
            mother_plant = self._find_mother_by_strain(strain, phenotype)
            if mother_plant:
                source_mother_id = mother_plant["plant_id"]
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
                    "phenotype": mother_plant.get("phenotype"),
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
        self.plants[plant_id] = clone_data
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

    def _find_mother_by_strain(
        self, strain: str, phenotype: str
    ) -> dict[str, Any] | None:
        """Find a mother plant with the specified strain."""
        for plant in self.plants.values():
            if (
                plant.get("stage") == "mother"
                and plant.get("strain", "").lower() == strain.lower()
                and plant.get("phenotype", "").lower() == phenotype.lower()
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
    ) -> str:
        """Add plant to permanent mother growspace."""
        mother_id = self._ensure_mother_growspace()
        kwargs["type"] = "mother"
        return await self.async_add_plant(
            mother_id, phenotype, strain, row, col, **kwargs
        )

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
                "strain": mother["strain"],
                "phenotype": mother.get("phenotype"),
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
        if clone.get("stage") != "clone":
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

    async def async_update_plant(
        self,
        plant_id: str,
        force_position: bool = False,
        **kwargs: Any,
    ) -> None:
        """Update a plant's properties."""
        self._validate_plant_exists(plant_id)

        plant = self.plants[plant_id]
        growspace_name = kwargs.get("growspace_id", plant["growspace_id"])

        # Handle position changes with validation
        if "row" in kwargs or "col" in kwargs:
            self._handle_position_update(plant_id, plant, force_position, kwargs)

        # Parse date fields
        self._parse_date_fields(kwargs)
        creation_date_fields = []
        if growspace_name in ["mother"]:
            creation_date_fields.append("mother_start")
        if growspace_name in ["clone"]:
            creation_date_fields.append("clone_start")
        if growspace_name in ["dry"]:
            creation_date_fields.append("dry_start")
        if growspace_name in ["cure"]:
            creation_date_fields.append("cure_start")
        if growspace_name == "mother" and "mother_start" not in plant:
            plant["mother_start"] = date.today().isoformat()
        if "mother_start" not in plant:
            plant["mother_start"] = None  # or "Unbekannt"
        if growspace_name == "clone" and "clone_start" not in plant:
            plant["clone_start"] = date.today().isoformat()
        if growspace_name in ["veg", "flower"]:
            creation_date_fields.append("veg_start")
            creation_date_fields.append("flower_start")

        # Update plant data
        plant.update(kwargs)
        plant["updated_at"] = date.today().isoformat()
        plant["stage"] = self._get_plant_stage(plant)

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info("Updated plant %s with fields: %s", plant_id, list(kwargs.keys()))

    def _handle_position_update(
        self,
        plant_id: str,
        plant: dict[str, Any],
        force_position: bool,
        kwargs: dict[str, Any],
    ) -> None:
        """Handle position updates with proper validation."""
        new_row = int(kwargs.get("row", plant["row"]))
        new_col = int(kwargs.get("col", plant["col"]))

        growspace_id = kwargs.get("growspace_id", plant["growspace_id"])

        # Validate bounds
        self._validate_position_bounds(growspace_id, new_row, new_col)

        # Check for conflicts unless force_position is True
        if not force_position and (new_row != plant["row"] or new_col != plant["col"]):
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
        if plant1["growspace_id"] != plant2["growspace_id"]:
            raise ValueError("Cannot switch plants in different growspaces")

        # Store and swap positions
        plant1_row, plant1_col = plant1["row"], plant1["col"]
        plant2_row, plant2_col = plant2["row"], plant2["col"]

        plant1["row"], plant1["col"] = plant2_row, plant2_col
        plant2["row"], plant2["col"] = plant1_row, plant1_col

        # Update timestamps
        update_time = date.today().isoformat()
        plant1["updated_at"] = update_time
        plant2["updated_at"] = update_time

        self.update_data_property()
        await self.async_save()
        self.async_set_updated_data(self.data)

        _LOGGER.info(
            "Switched positions: %s (%s) moved from (%d,%d) to (%d,%d), %s (%s) moved from (%d,%d) to (%d,%d)",
            plant1_id,
            plant1["strain"],
            plant1_col,
            plant1_row,
            plant2_col,
            plant2_row,
            plant2_id,
            plant2["strain"],
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
            plant.get("growspace_id"),
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
            plant.get("row"),
            plant.get("col"),
            plant.get("stage"),
            plant.get("dry_start"),
            plant.get("cure_start"),
        )

    async def _handle_harvest_logic(
        self,
        plant_id: str,
        plant: dict[str, Any],
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
        plant: dict[str, Any],
        target_growspace_id: str,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Handle harvest to explicit target growspace."""
        plant["growspace_id"] = target_growspace_id

        try:
            row, col = self._find_first_available_position(target_growspace_id)
            plant["row"], plant["col"] = row, col
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
        plant: dict[str, Any],
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
        self, plant_id: str, plant: dict[str, Any], transition_date: str
    ) -> bool:
        """Move plant to clone growspace."""
        clone_id = self._ensure_special_growspace("clone", "clone", 5, 5)
        plant["growspace_id"] = clone_id

        try:
            new_row, new_col = self._find_first_available_position(clone_id)
            plant["row"], plant["col"] = new_row, new_col
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

        plant["clone_start"] = transition_date
        plant["stage"] = "clone"
        _LOGGER.info("Moved plant %s → clone (ID: %s)", plant_id, clone_id)
        return True

    async def _move_to_dry_growspace(
        self, plant_id: str, plant: dict[str, Any], transition_date: str
    ) -> bool:
        """Move plant to dry growspace."""
        dry_id = self._ensure_special_growspace("dry", "dry")
        plant["growspace_id"] = dry_id

        growspace = self.growspaces.get(dry_id)
        if growspace and growspace.get("device_id"):
            plant["device_id"] = growspace["device_id"]

        try:
            new_row, new_col = self._find_first_available_position(dry_id)
            plant["row"], plant["col"] = new_row, new_col
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

        plant["dry_start"] = transition_date
        plant["stage"] = "dry"
        _LOGGER.info("Moved plant %s → dry (ID: %s)", plant_id, dry_id)
        return True

    async def _move_to_cure_growspace(
        self, plant_id: str, plant: dict[str, Any], transition_date: str
    ) -> bool:
        """Move plant to cure growspace."""
        cure_id = self._ensure_special_growspace("cure", "cure")
        plant["growspace_id"] = cure_id

        try:
            new_row, new_col = self._find_first_available_position(cure_id)
            plant["row"], plant["col"] = new_row, new_col
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

        plant["cure_start"] = transition_date
        plant["stage"] = "cure"
        _LOGGER.info("Moved plant %s → cure (ID: %s)", plant_id, cure_id)
        return True

    async def async_remove_plant(self, plant_id: str) -> None:
        """Remove a plant and its entities."""
        self._validate_plant_exists(plant_id)

        plant = self.plants.pop(plant_id)
        self.notifications.pop(plant_id, None)

        # Update data and save
        self.update_data_property()

        await self.store.async_save(self.data)

        # Remove entities tied to this plant
        await self._remove_plant_entities(plant_id)

        # Notify HA
        self.async_set_updated_data(self.data)

        _LOGGER.info("Removed plant %s (%s)", plant_id, plant["strain"])

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
        """Add a new strain to the library."""
        clean_strain = str(strain).strip()
        if clean_strain and clean_strain not in self.strain_library:
            self.strain_library.add(clean_strain)
            self.hass.async_create_task(
                self.strain_store.async_save(list(self.strain_library))
            )

    def remove_strain(self, strain: str) -> None:
        """Remove a strain from the library."""
        if strain in self.strain_library:
            self.strain_library.remove(strain)
            self.hass.async_create_task(
                self.strain_store.async_save(list(self.strain_library))
            )

    def get_strain_options(self) -> list[str]:
        """Return sorted list of strains."""
        return sorted(self.strain_library)

    def export_strain_library(self) -> list[str]:
        """Export all strains from the library."""
        return self.get_strain_options()

    async def import_strain_library(
        self, strains: list[str], replace: bool = False
    ) -> int:
        """Import strains into the library, optionally replacing existing ones.

        Args:
            strains (list[str]): List of strain names to import.
            replace (bool): If True, replace existing strains. If False, merge.

        Returns:
            int: Number of strains in the library after import.
        """
        clean_strains = {s.strip() for s in strains if s.strip()}

        if replace:
            self.strain_library = clean_strains
        else:
            self.strain_library.update(clean_strains)

        # Save to dedicated store
        await self.strain_store.async_save(list(self.strain_library))

        return len(self.strain_library)

    async def clear_strain_library(self) -> int:
        """Clear all strains from the library."""
        count = len(self.strain_library)
        self.strain_library.clear()
        await self.strain_store.async_save(list(self.strain_library))
        return count

    # =============================================================================
    # QUERY AND CALCULATION METHODS
    # =============================================================================

    def get_growspace_plants(self, growspace_id: str) -> list[dict[str, Any]]:
        """Get all plants in a specific growspace."""
        return [
            plant
            for plant in self.plants.values()
            if plant["growspace_id"] == growspace_id
        ]

    def calculate_days_in_stage(self, plant: dict[str, Any], stage: str) -> int:
        """Calculate days a plant has been in a specific stage."""
        start_date = plant.get(f"{stage}_start")
        return self._calculate_days(start_date)

    def get_growspace_grid(self, growspace_id: str) -> dict[str, Any]:
        """Get a grid representation of a growspace with plant positions."""
        if growspace_id not in self.growspaces:
            return {}

        growspace = self.growspaces[growspace_id]
        plants = self.get_growspace_plants(growspace_id)

        # Initialize empty grid
        grid = {}
        total_rows = int(growspace["rows"])
        total_cols = int(growspace["plants_per_row"])

        for row in range(1, total_rows + 1):
            for col in range(1, total_cols + 1):
                position_key = f"position_{row}_{col}"
                grid[position_key] = None

        # Fill grid with plants
        for plant in plants:
            position_key = f"position_{plant['row']}_{plant['col']}"
            grid[position_key] = {
                "plant_id": plant["plant_id"],
                "strain": plant["strain"],
                "phenotype": plant.get("phenotype", ""),
                "veg_days": self.calculate_days_in_stage(plant, "veg"),
                "flower_days": self.calculate_days_in_stage(plant, "flower"),
                "dry_days": self.calculate_days_in_stage(plant, "dry"),
                "cure_days": self.calculate_days_in_stage(plant, "cure"),
                "mom_days": self.calculate_days_in_stage(plant, "mother"),
                "clone_days": self.calculate_days_in_stage(plant, "clone"),
            }

        return grid

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
        growspace = self.growspaces.get(growspace_id, {})
        name = str(growspace.get("name", growspace_id))

        # Simple slugify: lowercase, spaces->underscore, keep alnum/underscore only
        slug = "".join(
            ch if ch.isalnum() or ch == "_" else "_"
            for ch in name.lower().replace(" ", "_")
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
        await self.store.async_save(self.data)
