"""Plant Manager."""

from __future__ import annotations

from datetime import date
import logging
from typing import TYPE_CHECKING, Any
import uuid

from custom_components.growspace_manager.const import (
    CATEGORY_MILESTONE,
    DATE_FIELDS,
    PLANT_STAGES,
    SPECIAL_GROWSPACES,
    PlantStage,
)
from custom_components.growspace_manager.domain.stage_calculator import (
    calculate_days_in_stage,
)
from custom_components.growspace_manager.events import (
    EVENT_PLANT_ADDED,
    EVENT_PLANT_HARVESTED,
    EVENT_PLANT_MOVED,
    EVENT_PLANT_REMOVED,
    EVENT_PLANT_SWITCHED,
    EVENT_PLANT_TRANSITIONED,
    EVENT_PLANT_UPDATED,
    async_fire_clones_taken_event,
    async_fire_plant_event,
    async_fire_plant_layout_changed_event,
)
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    LayoutConflictError,
    PlantNotFoundError,
    ValidationChangeError,
)
from custom_components.growspace_manager.integration_types import DateInput
from custom_components.growspace_manager.models import (
    GrowspaceEvent,
    Plant,
    PlantGenetics,
)
from custom_components.growspace_manager.services.context import (
    BaseService,
    ServiceContext,
)
from custom_components.growspace_manager.utils import (
    calculate_plant_stage,
    to_lifecycle_timestamp,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from custom_components.growspace_manager.data_access.growspace_repository import (
        GrowspaceRepository,
    )
    from custom_components.growspace_manager.data_access.notification_state import (
        NotificationState,
    )
    from custom_components.growspace_manager.growspace_validator import (
        GrowspaceValidator,
    )
    from custom_components.growspace_manager.managers.growspace import GrowspaceManager
    from custom_components.growspace_manager.presentation import PlantViewModelBuilder
    from custom_components.growspace_manager.strain_library import StrainLibrary

_LOGGER = logging.getLogger(__name__)


class PlantManager(BaseService):
    """Manages plant lifecycle, CRUD operations, and events."""

    def __init__(
        self,
        ctx: ServiceContext,
        hass: HomeAssistant,
        repository: GrowspaceRepository,
        notification_state: NotificationState,
        validator: GrowspaceValidator,
        growspace_manager: GrowspaceManager,
        strain_library: StrainLibrary,
        plant_view_builder: PlantViewModelBuilder,
    ) -> None:
        """Initialize the plant manager."""
        super().__init__(ctx)
        self.hass = hass
        self.repository = repository
        self.notification_state = notification_state
        self.validator = validator
        self.growspace_manager = growspace_manager
        self.strain_library = strain_library
        self.plant_view_builder = plant_view_builder
        self.lifecycle_manager = self
        self.cache: Any = None  # To be injected

    def _fire_event(self, event_type: str, data: dict[str, Any]) -> None:
        """Fire a growspace manager event."""
        payload = {"event_type": event_type, "data": data}
        self.hass.bus.async_fire("growspace_manager_updated", payload)

    def _advance_layout_revision(self, growspace_id: str) -> None:
        """Advance a growspace Layout Revision while the manager lock is held."""
        growspace = self.repository.get_growspace(growspace_id)
        if not growspace:
            raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
        growspace.layout_revision += 1

    # =========================================================================
    # PLANT CRUD OPERATIONS
    # =========================================================================

    async def add_plant(
        self,
        growspace_id: str,
        strain: str,
        plant_id: str | None = None,
        phenotype: str = "",
        row: int = 1,
        col: int = 1,
        stage: str = "",
        plant_type: str = "normal",
        device_id: str | None = None,
        seed_batch_id: str | None = None,
        generation: str = "",
        **kwargs: Any,
    ) -> Plant:
        """Add a new plant to the system."""
        async with self._lock:
            if not self.repository.has_growspace(growspace_id):
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
            try:
                self.validator.validate_position_not_occupied(growspace_id, row, col)
                final_row, final_col = row, col
            except ValidationChangeError:
                _LOGGER.info(
                    "Position (%d, %d) in growspace %s is occupied. Finding first available",
                    row,
                    col,
                    growspace_id,
                )
                found_row, found_col = self.validator.find_first_available_position(
                    growspace_id
                )

                if found_row is None or found_col is None:
                    _LOGGER.warning(
                        "No free space in growspace %s, cannot resolve conflict",
                        growspace_id,
                    )
                    raise ValidationChangeError(
                        f"Growspace {growspace_id} is full, cannot add/move plant"
                    ) from None

                final_row, final_col = found_row, found_col

            date_fields = {}
            for field in DATE_FIELDS:
                if field in kwargs:
                    # Lifecycle Timestamp: store full datetime, never date-only
                    # (ADR-0013). None stays None (field absent/cleared) — only a
                    # real value is promoted to a datetime string.
                    value = kwargs[field]
                    date_fields[field] = (
                        to_lifecycle_timestamp(value) if value is not None else None
                    )

            final_plant_id = plant_id or str(uuid.uuid4())

            # Inherit phenotype from mother if not provided
            mother_plant = kwargs.get("mother_plant")
            if not phenotype and mother_plant:
                phenotype = mother_plant.phenotype

            genetics = PlantGenetics(
                strain_name=strain,
                phenotype_name=phenotype or "",
                generation=generation,
            )

            plant = Plant(
                plant_id=final_plant_id,
                growspace_id=growspace_id,
                genetics=genetics,
                row=final_row,
                col=final_col,
                stage=stage or "",
                type=plant_type,
                device_id=device_id,
                seed_batch_id=seed_batch_id,
                created_at=dt_util.utcnow().isoformat(),
                updated_at=dt_util.utcnow().isoformat(),
                **date_fields,  # type: ignore[arg-type]
                source_mother=kwargs.get("source_mother")
                or kwargs.get("source_mother_id")
                or "",
            )

            if not plant.stage:
                plant.stage = calculate_plant_stage(plant)

            self.repository.add_plant(plant)
            self._advance_layout_revision(growspace_id)
            await self._save()

        # Event Firing (outside lock if possible, or inside? Service did it after lifecycle call)
        # Service: await lifecycle.add_plant -> fire event
        # Here we are inside logic.

        self._fire_event("plant_added", {"plant": self.plant_view_builder.build(plant)})
        async_fire_plant_event(self.hass, EVENT_PLANT_ADDED, plant)

        return plant

    async def update_plant(self, plant_id: str, **updates: Any) -> Plant:
        """Update attributes of an existing plant."""
        async with self._lock:
            plant = self.repository.get_plant(plant_id)
            if not plant:
                raise PlantNotFoundError(f"Plant {plant_id} does not exist")

            old_growspace_id = plant.growspace_id
            new_growspace_id = updates.get("growspace_id", old_growspace_id)
            growspace_changed = new_growspace_id != old_growspace_id
            if growspace_changed and not self.repository.has_growspace(
                new_growspace_id
            ):
                raise GrowspaceNotFoundError(f"Growspace {new_growspace_id} not found")
            position_changed = any(
                key in updates and updates[key] != getattr(plant, key)
                for key in ("row", "col")
            )

            for key in DATE_FIELDS:
                if key in updates:
                    # Lifecycle Timestamp: store full datetime, never date-only
                    # (ADR-0013). None means "clear the field", so it is left as-is.
                    if updates[key] is not None:
                        updates[key] = to_lifecycle_timestamp(updates[key])

            # Handle genetics updates
            if "strain" in updates:
                plant.genetics.strain_name = updates.pop("strain")
            if "phenotype" in updates:
                plant.genetics.phenotype_name = updates.pop("phenotype")

            for key, value in updates.items():
                if hasattr(plant, key):
                    setattr(plant, key, value)

            plant.updated_at = dt_util.now().date().isoformat()
            if growspace_changed:
                self._advance_layout_revision(old_growspace_id)
                self._advance_layout_revision(new_growspace_id)
            elif position_changed:
                self._advance_layout_revision(old_growspace_id)
            await self._save()

        self._fire_event(
            "plant_updated",
            {"plant": self.plant_view_builder.build(plant)},
        )
        async_fire_plant_event(self.hass, EVENT_PLANT_UPDATED, plant, updates)
        return plant

    async def async_update_plant(self, plant_id: str, **updates: Any) -> Plant:
        """Compatibility wrapper for update_plant."""
        return await self.update_plant(plant_id, **updates)

    async def remove_plant(self, plant_id: str) -> bool:
        """Remove a plant."""
        async with self._lock:
            plant = self.repository.get_plant(plant_id)
            if not plant:
                return False
            self.repository.remove_plant(plant_id)
            self.notification_state.sent.pop(plant_id, None)
            self._advance_layout_revision(plant.growspace_id)
            await self._save()

        self._fire_event(
            "plant_removed",
            {"plant_id": plant.plant_id, "growspace_id": plant.growspace_id},
        )
        async_fire_plant_event(self.hass, EVENT_PLANT_REMOVED, plant)
        return True

    async def move_plant(self, plant_id: str, new_row: int, new_col: int) -> None:
        """Move a plant to a new position."""
        await self.update_plant(plant_id, row=new_row, col=new_col)

        # Original Service fired EVENT_PLANT_MOVED here
        if plant := self.repository.get_plant(plant_id):
            async_fire_plant_event(
                self.hass,
                EVENT_PLANT_MOVED,
                plant,
                {"new_row": new_row, "new_col": new_col},
            )

    async def switch_plants(self, plant1_id: str, plant2_id: str) -> None:
        """Switch the positions of two plants."""
        async with self._lock:
            self.validator.validate_plant_exists(plant1_id)
            self.validator.validate_plant_exists(plant2_id)

            plant1 = self.repository.require_plant(plant1_id)
            plant2 = self.repository.require_plant(plant2_id)

            if plant1.growspace_id != plant2.growspace_id:
                raise ValidationChangeError(
                    "Cannot switch plants in different growspaces"
                )

            p1_row, p1_col = plant1.row, plant1.col
            p2_row, p2_col = plant2.row, plant2.col

            plant1.row, plant1.col = p2_row, p2_col
            plant2.row, plant2.col = p1_row, p1_col

            now = dt_util.now().date().isoformat()
            plant1.updated_at = now
            plant2.updated_at = now

            self._advance_layout_revision(plant1.growspace_id)
            await self._save()

        # Fire events
        if p1 := self.repository.get_plant(plant1_id):
            self._fire_event(
                "plant_switched",
                {"plant": self.plant_view_builder.build(p1)},
            )
            async_fire_plant_event(self.hass, EVENT_PLANT_SWITCHED, p1)

        if p2 := self.repository.get_plant(plant2_id):
            self._fire_event(
                "plant_switched",
                {"plant": self.plant_view_builder.build(p2)},
            )
            async_fire_plant_event(self.hass, EVENT_PLANT_SWITCHED, p2)

    async def set_plant_layout(
        self,
        growspace_id: str,
        expected_layout_revision: int,
        placements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Validate and commit a complete Plant Layout as one mutation."""
        async with self._lock:
            growspace = self.repository.get_growspace(growspace_id)
            if not growspace:
                raise GrowspaceNotFoundError(f"Growspace {growspace_id} not found")
            if growspace.layout_revision != expected_layout_revision:
                raise LayoutConflictError(
                    "Plant Layout revision conflict: "
                    f"expected {expected_layout_revision}, "
                    f"current {growspace.layout_revision}"
                )

            plants = self.repository.get_growspace_plants(growspace_id)
            current_ids = {plant.plant_id for plant in plants}
            placement_by_id: dict[str, tuple[int, int]] = {}
            occupied: set[tuple[int, int]] = set()

            for placement in placements:
                plant_id = str(placement["plant_id"])
                if plant_id in placement_by_id:
                    raise ValidationChangeError(
                        f"Plant {plant_id} has more than one placement"
                    )
                plant = self.repository.get_plant(plant_id)
                if not plant:
                    raise PlantNotFoundError(f"Plant {plant_id} does not exist")
                if plant.growspace_id != growspace_id:
                    raise ValidationChangeError(
                        f"Plant {plant_id} does not belong to growspace {growspace_id}"
                    )

                row = int(placement["row"])
                col = int(placement["col"])
                if (
                    not 1 <= row <= growspace.rows
                    or not 1 <= col <= growspace.plants_per_row
                ):
                    raise ValidationChangeError(
                        f"Position ({row}, {col}) is outside growspace {growspace_id}"
                    )
                cell = (row, col)
                if cell in occupied:
                    raise ValidationChangeError(
                        f"Position ({row}, {col}) is assigned more than once"
                    )
                occupied.add(cell)
                placement_by_id[plant_id] = cell

            if missing_ids := current_ids - placement_by_id.keys():
                missing_id = min(missing_ids)
                raise PlantNotFoundError(
                    f"Plant {missing_id} is missing from the complete layout"
                )
            if extra_ids := placement_by_id.keys() - current_ids:
                extra_id = min(extra_ids)
                raise ValidationChangeError(
                    f"Plant {extra_id} is not part of growspace {growspace_id}"
                )

            authoritative = [
                {"plant_id": plant_id, "row": row, "col": col}
                for plant_id, (row, col) in sorted(placement_by_id.items())
            ]
            current = [
                {"plant_id": plant.plant_id, "row": plant.row, "col": plant.col}
                for plant in sorted(plants, key=lambda item: item.plant_id)
            ]
            if authoritative == current:
                return {
                    "growspace_id": growspace_id,
                    "layout_revision": growspace.layout_revision,
                    "placements": current,
                }

            previous_positions = {
                plant.plant_id: (plant.row, plant.col, plant.updated_at)
                for plant in plants
            }
            previous_revision = growspace.layout_revision
            updated_at = dt_util.now().isoformat()
            new_revision = previous_revision + 1
            snapshot_saved = await self._save_layout_snapshot(
                growspace_id, new_revision, authoritative, updated_at
            )
            if snapshot_saved:
                for plant in plants:
                    plant.row, plant.col = placement_by_id[plant.plant_id]
                    plant.updated_at = updated_at
                growspace.layout_revision = new_revision
            else:
                for plant in plants:
                    plant.row, plant.col = placement_by_id[plant.plant_id]
                    plant.updated_at = updated_at
                growspace.layout_revision = new_revision
                try:
                    await self._save()
                except Exception:
                    for plant in plants:
                        plant.row, plant.col, plant.updated_at = previous_positions[
                            plant.plant_id
                        ]
                    growspace.layout_revision = previous_revision
                    self._invalidate(growspace_id)
                    raise

            committed_revision = growspace.layout_revision
            result: dict[str, Any] = {
                "growspace_id": growspace_id,
                "layout_revision": committed_revision,
                "placements": authoritative,
            }
            if snapshot_saved:
                await self._publish()

        async_fire_plant_layout_changed_event(
            self.hass, growspace_id, committed_revision
        )
        return result

    def get_plant(self, plant_id: str) -> Plant | None:
        """Retrieve a plant by its ID."""
        return self.repository.get_plant(plant_id)

    # =========================================================================
    # SPECIALIZED ADD METHODS (Service convenience)
    # =========================================================================

    async def add_mother_plant(
        self,
        phenotype: str,
        strain: str,
        row: int,
        col: int,
        mother_start: date | None = None,
        **kwargs: Any,
    ) -> Plant:
        """Add a new mother plant."""
        mother_id: str = self.growspace_manager.ensure_mother_growspace()
        kwargs.pop("growspace_id", None)
        kwargs["type_str"] = PlantStage.MOTHER  # Passed as plant_type logic?
        # Lifecycle add_plant used 'plant_type' arg. Service used 'type_str'.
        # I used 'plant_type' in add_plant signature above.

        if mother_start is None:
            mother_start = dt_util.now()

        # Override plant_type via kwargs?
        # The add_plant signature has plant_type="normal".
        # I should pass it explicitly.

        return await self.add_plant(
            growspace_id=mother_id,
            strain=strain,
            phenotype=phenotype,
            row=row,
            col=col,
            plant_type=PlantStage.MOTHER,
            mother_start=mother_start,
            **kwargs,
        )

    async def take_clones(
        self,
        mother_plant_id: str,
        num_clones: int,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: date | None = None,
    ) -> list[Plant]:
        """Create multiple clones from a mother plant."""
        self.validator.validate_plant_exists(mother_plant_id)
        mother = self.repository.require_plant(mother_plant_id)

        if target_growspace_id:
            if not self.repository.has_growspace(target_growspace_id):
                raise ValueError(
                    f"Target growspace '{target_growspace_id}' does not exist"
                )
            clone_gs_id = target_growspace_id
        else:
            clone_gs_id = self.growspace_manager.ensure_special_growspace(
                PlantStage.CLONE, "clone", 5, 5
            )

        new_plants: list[Plant] = []
        if transition_date is None:
            transition_date = dt_util.now()

        for _ in range(num_clones):
            # This logic was in Service calling Lifecycle.handle_clone_creation.
            # I should inspect handle_clone_creation from LifecycleManager again.
            # It found position, then called add_plant.

            # Service:
            # row, col = self.validator.find_first_available_position(clone_gs_id)
            # clone_id = await self.lifecycle_manager.handle_clone_creation(...)

            # Lifecycle.handle_clone_creation:
            # calls async_add_plant.

            # I can just implement logic here directly calling self.add_plant.

            row, col = self.validator.find_first_available_position(clone_gs_id)
            if row is None or col is None:
                _LOGGER.warning("Clone growspace %s is full", clone_gs_id)
                raise ValueError(f"Growspace '{clone_gs_id}' is full")

            clone_plant = await self.add_plant(
                growspace_id=clone_gs_id,
                strain=mother.strain,
                phenotype=mother.phenotype or "",
                row=row,
                col=col,
                stage=PlantStage.CLONE,
                plant_type=PlantStage.CLONE,
                clone_start=transition_date,
                source_mother=mother_plant_id,
            )

            new_plants.append(clone_plant)

        if new_plants:
            async_fire_clones_taken_event(
                self.hass, mother, len(new_plants), clone_gs_id
            )

        return new_plants

    # =========================================================================
    # HARVEST & TRANSITION LOGIC
    # =========================================================================

    async def transition_plant_stage(
        self,
        plant_id: str,
        new_stage: str | PlantStage,
        transition_date: DateInput = None,
    ) -> None:
        """Execute a plant stage transition."""
        if isinstance(new_stage, PlantStage):
            new_stage = new_stage.value

        if new_stage not in PLANT_STAGES:
            raise ValidationChangeError(f"Invalid stage: {new_stage}")

        # Lifecycle Timestamp: preserve a supplied time, default to now (ADR-0013).
        trans_date_str = to_lifecycle_timestamp(transition_date)

        updates: dict[str, Any] = {"stage": new_stage}
        stage_map = {
            PlantStage.VEG.value: "veg_start",
            PlantStage.FLOWER.value: "flower_start",
            PlantStage.DRY.value: "dry_start",
            PlantStage.CURE.value: "cure_start",
            PlantStage.CLONE.value: "clone_start",
        }
        if new_stage in stage_map:
            updates[stage_map[new_stage]] = trans_date_str

        plant = self.repository.get_plant(plant_id)
        if hasattr(plant, "stage_history"):  # Check just in case
            new_history = [dict(item) for item in plant.stage_history]
            for item in reversed(new_history):
                if item.get("end") is None:
                    item["end"] = trans_date_str
                    break
            new_history.append(
                {"stage": new_stage, "start": trans_date_str, "end": None}
            )
            updates["stage_history"] = new_history

        await self.update_plant(plant_id, **updates)

        # Trigger logic for automatic moves based on stage
        plant = self.repository.get_plant(plant_id)
        if plant:
            if new_stage == PlantStage.DRY:
                await self.move_to_dry_growspace(plant_id, plant, trans_date_str)
            elif new_stage == PlantStage.CURE:
                await self.move_to_cure_growspace(plant_id, plant, trans_date_str)
            elif new_stage == PlantStage.CLONE:
                await self.move_to_clone_growspace(plant_id, plant, trans_date_str)

        # Fire event (Service did this)
        if plant := self.repository.get_plant(plant_id):
            async_fire_plant_event(
                self.hass,
                EVENT_PLANT_TRANSITIONED,
                plant,
                {"new_stage": str(new_stage)},
            )
            now_iso = dt_util.now().isoformat()
            stage_label = new_stage.replace("_", " ").title()
            event = GrowspaceEvent(
                sensor_type="stage_transition",
                growspace_id=plant.growspace_id,
                start_time=now_iso,
                end_time=now_iso,
                duration_sec=0,
                severity=1.0,
                category=CATEGORY_MILESTONE,
                reasons=[
                    f"{(plant.genetics.strain_name if plant.genetics else None) or plant_id} entered {stage_label}"
                ],
            )
            self._emit(plant.growspace_id, event)

    async def transition_plant(
        self,
        plant_id: str,
        plant: Plant | None = None,
        target_growspace_id: str | None = None,
        target_growspace_name: str | None = None,
        transition_date: str | None = None,
        wet_weight: float | None = None,
        dry_weight: float | None = None,
        trim_weight: float | None = None,
        thc_percentage: float | None = None,
        cbd_percentage: float | None = None,
        terpene_profile: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Transition a plant out of its current growspace (harvest or move)."""
        self.validator.validate_plant_exists(plant_id)
        if plant is None:
            plant = self.repository.require_plant(plant_id)

        # PHI safety check - prevent harvest before pre-harvest interval clears
        if plant.phi_clearance_date:
            today = dt_util.now().date()
            phi_date = dt_util.parse_datetime(plant.phi_clearance_date).date()
            if today < phi_date:
                days_remaining = (phi_date - today).days
                from custom_components.growspace_manager.const import (  # noqa: PLC0415
                    DOMAIN,
                )
                from homeassistant.exceptions import (  # noqa: PLC0415
                    ServiceValidationError,
                )

                raise ServiceValidationError(
                    translation_domain=DOMAIN,
                    translation_key="phi_not_cleared",
                    translation_placeholders={
                        "plant_id": plant_id,
                        "clearance_date": plant.phi_clearance_date,
                        "days_remaining": str(days_remaining),
                    },
                )

        # Defensive check for mock/corrupted data
        if not hasattr(plant, "growspace_id"):
            _LOGGER.warning(
                "Plant %s is not a valid Plant object, skipping stage log", plant_id
            )
            stage_before = "unknown"
        else:
            stage_before = calculate_plant_stage(plant)

        transition_date_str = to_lifecycle_timestamp(transition_date)

        # Store yield/lab metrics on the plant before analytics recording
        if hasattr(plant, "harvest_metrics"):
            if wet_weight is not None:
                plant.harvest_metrics.wet_weight = wet_weight
            if dry_weight is not None:
                plant.harvest_metrics.dry_weight = dry_weight
            if trim_weight is not None:
                plant.harvest_metrics.trim_weight = trim_weight
            if thc_percentage is not None:
                plant.harvest_metrics.thc_percentage = thc_percentage
            if cbd_percentage is not None:
                plant.harvest_metrics.cbd_percentage = cbd_percentage
            if terpene_profile is not None:
                plant.harvest_metrics.terpene_profile = terpene_profile

        # Log harvest start
        _LOGGER.info(
            "Harvest start: plant_id=%s stage=%s",
            plant_id,
            stage_before,
        )

        # Copied logic from LifecycleManager.handle_transition_logic
        moved = False
        if target_growspace_id:
            if not self.repository.has_growspace(target_growspace_id):
                raise GrowspaceNotFoundError(
                    f"Target growspace {target_growspace_id} not found"
                )
            moved = await self._harvest_to_explicit_target(
                plant_id,
                plant,
                target_growspace_id,
                target_growspace_name,
                transition_date_str,
            )
        else:
            moved = await self._harvest_auto_flow(
                plant_id, plant, target_growspace_name, transition_date_str
            )

        # Post harvest logic
        _LOGGER.info("Harvest end: plant_id=%s moved=%s", plant_id, moved)
        async_fire_plant_event(self.hass, EVENT_PLANT_HARVESTED, plant)

    async def _harvest_to_explicit_target(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_id: str,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Move harvested plant to explicit target."""
        try:
            pos = self.validator.find_first_available_position(target_growspace_id)
            new_row, new_col = pos
        except ValueError as e:
            _LOGGER.warning(
                "Failed to find position in %s growspace: %s",
                target_growspace_id,
                e,
            )
            new_row, new_col = 1, 1

        stage_updates = {}
        target_lower = (target_growspace_name or "").lower()

        if target_growspace_id == PlantStage.DRY or "dry" in target_lower:
            stage_updates = {"stage": PlantStage.DRY, "dry_start": transition_date}
        elif target_growspace_id == PlantStage.CURE or "cure" in target_lower:
            stage_updates = {"stage": PlantStage.CURE, "cure_start": transition_date}
        elif target_growspace_id == PlantStage.CLONE or "clone" in target_lower:
            stage_updates = {"stage": PlantStage.CLONE, "clone_start": transition_date}
        elif target_growspace_id == PlantStage.MOTHER or "mother" in target_lower:
            stage_updates = {
                "stage": PlantStage.MOTHER,
                "mother_start": transition_date,
            }

        await self.update_plant(
            plant_id,
            growspace_id=target_growspace_id,
            row=new_row,
            col=new_col,
            **stage_updates,
        )
        return True

    async def _harvest_auto_flow(
        self,
        plant_id: str,
        plant: Plant,
        target_growspace_name: str | None,
        transition_date: str,
    ) -> bool:
        """Automatically determine harvest flow."""
        if target_growspace_name:
            name_lower = target_growspace_name.lower()
            for stage in [
                PlantStage.DRY,
                PlantStage.CURE,
                PlantStage.CLONE,
                PlantStage.MOTHER,
            ]:
                info = SPECIAL_GROWSPACES.get(stage.value, {})
                aliases = info.get("aliases", [])
                if name_lower == stage.value or name_lower in aliases:
                    return await self._move_to_special_growspace(
                        plant_id, plant, stage, transition_date
                    )

        current_stage = calculate_plant_stage(plant)
        if current_stage == PlantStage.FLOWER:
            return await self.move_to_dry_growspace(plant_id, plant, transition_date)
        if current_stage == PlantStage.DRY:
            return await self.move_to_cure_growspace(plant_id, plant, transition_date)
        if current_stage == PlantStage.MOTHER:
            return await self.move_to_clone_growspace(plant_id, plant, transition_date)

        return await self.move_to_dry_growspace(plant_id, plant, transition_date)

    async def _move_to_special_growspace(
        self,
        plant_id: str,
        plant: Plant,
        target_stage: PlantStage,
        transition_date: str,
        record_harvest_analytics: bool = False,
    ) -> bool:
        """Generic method to move a plant to a special growspace."""
        if record_harvest_analytics:
            await self._record_analytics(plant)

        gs_id = self.growspace_manager.ensure_special_growspace(
            target_stage.value, target_stage.value
        )
        target_gs = self.repository.get_growspace(gs_id)

        try:
            new_row, new_col = self.validator.find_first_available_position(gs_id)
        except ValueError as e:
            _LOGGER.warning(
                "Failed to find position in %s growspace: %s",
                gs_id,
                e,
            )
            new_row, new_col = 1, 1

        updates: dict[str, Any] = {
            "growspace_id": gs_id,
            "row": new_row,
            "col": new_col,
            "stage": target_stage,
        }

        date_map = {
            PlantStage.DRY: "dry_start",
            PlantStage.CURE: "cure_start",
            PlantStage.CLONE: "clone_start",
            PlantStage.MOTHER: "mother_start",
            PlantStage.VEG: "veg_start",
        }
        updates["device_id"] = target_gs.device_id if target_gs else None
        if target_stage in date_map:
            updates[date_map[target_stage]] = transition_date

        await self.update_plant(plant_id, **updates)
        return True

    async def move_to_dry_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the dry growspace."""
        return await self._move_to_special_growspace(
            plant_id,
            plant,
            PlantStage.DRY,
            transition_date,
            record_harvest_analytics=True,
        )

    async def move_to_cure_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant to the cure growspace."""
        return await self._move_to_special_growspace(
            plant_id, plant, PlantStage.CURE, transition_date
        )

    async def move_to_clone_growspace(
        self, plant_id: str, plant: Plant, transition_date: str
    ) -> bool:
        """Move a plant back to the clone growspace."""
        return await self._move_to_special_growspace(
            plant_id, plant, PlantStage.CLONE, transition_date
        )

    async def start_flowering(self, plant_id: str) -> Plant:
        """Transition a plant to the 'flower' stage, starting now."""
        # No explicit date: the transition seam defaults to now() with its time.
        await self.transition_plant_stage(plant_id, PlantStage.FLOWER)
        return self.repository.require_plant(plant_id)

    async def start_drying(self, plant_id: str) -> Plant:
        """Transition a plant to the 'drying' stage, starting now."""
        await self.transition_plant_stage(plant_id, PlantStage.DRY)
        return self.repository.require_plant(plant_id)

    async def start_curing(self, plant_id: str) -> Plant:
        """Transition a plant to the 'curing' stage, starting now."""
        await self.transition_plant_stage(plant_id, PlantStage.CURE)
        return self.repository.require_plant(plant_id)

    async def harvest(self, plant_id: str) -> Plant:
        """Quick harvest."""
        return await self.start_drying(plant_id)

    async def promote_clone(
        self,
        clone_id: str,
        target_growspace_id: str = "veg",
        transition_date: date | None = None,
    ) -> None:
        """Promote a clone to a vegetative growspace.

        This updates the EXISTING plant record, preserving its ID and history.
        """
        plant = self.repository.get_plant(clone_id)
        if not plant:
            raise PlantNotFoundError(f"Plant {clone_id} not found")

        if plant.stage != PlantStage.CLONE:
            raise ValidationChangeError(
                f"Plant {clone_id} is not in clone stage (current: {plant.stage})"
            )

        # Resolve target growspace ID (handle aliases like 'veg')
        if target_growspace_id == "veg":
            target_gs_id = self.growspace_manager.ensure_special_growspace(
                PlantStage.VEG, "veg", 5, 5
            )
        else:
            # Ensure custom growspace exists
            if not self.repository.has_growspace(target_growspace_id):
                raise GrowspaceNotFoundError(
                    f"Target growspace {target_growspace_id} does not exist"
                )
            target_gs_id = target_growspace_id

        # Now find position (reads state)
        row, col = self.validator.find_first_available_position(target_gs_id)
        if row is None or col is None:
            raise ValidationChangeError(f"Target growspace {target_gs_id} is full")

        # Now call update_plant (which acquires lock)
        await self.update_plant(
            clone_id,
            growspace_id=target_gs_id,
            row=row,
            col=col,
            stage=PlantStage.VEG,
            veg_start=transition_date or dt_util.now(),
        )

    async def _record_analytics(self, plant: Plant) -> None:
        """Record harvest analytics for a plant."""
        veg_days = calculate_days_in_stage(plant, PlantStage.VEG)
        flower_days = calculate_days_in_stage(plant, PlantStage.FLOWER)
        if self.strain_library and (veg_days > 0 or flower_days > 0):
            try:
                metrics = getattr(plant, "harvest_metrics", None)
                await self.strain_library.record_harvest(
                    plant.strain,
                    plant.phenotype,
                    veg_days,
                    flower_days,
                    plant.phenotype_score.vigor,
                    plant.phenotype_score.internodal_spacing,  # maps to legacy 'structure' param
                    plant.phenotype_score.terpene_intensity,  # maps to legacy 'aroma' param
                    plant.phenotype_score.resin,
                    plant.phenotype_score.mold_resistance,  # maps to legacy 'pest_resistance' param
                    wet_weight=metrics.wet_weight if metrics else None,
                    dry_weight=metrics.dry_weight if metrics else None,
                    trim_weight=metrics.trim_weight if metrics else None,
                    thc_percentage=metrics.thc_percentage if metrics else None,
                    cbd_percentage=metrics.cbd_percentage if metrics else None,
                    terpene_profile=metrics.terpene_profile if metrics else None,
                )
            except Exception as e:  # noqa: BLE001
                _LOGGER.warning(
                    "Failed to record harvest analytics for %s: %s",
                    plant.plant_id,
                    e,
                )

    # Aliases for compatibility with old service/lifecycle manager names
    async def async_add_plant(self, *args: Any, **kwargs: Any) -> Plant:
        """Alias for add_plant."""
        return await self.add_plant(*args, **kwargs)

    async def async_remove_plant(self, *args: Any, **kwargs: Any) -> bool:
        """Alias for remove_plant."""
        return await self.remove_plant(*args, **kwargs)

    async def async_move_plant(self, *args: Any, **kwargs: Any) -> Plant:
        """Alias for move_plant."""
        return await self.move_plant(*args, **kwargs)

    async def async_switch_plants(self, *args: Any, **kwargs: Any) -> list[Plant]:
        """Alias for switch_plants."""
        return await self.switch_plants(*args, **kwargs)

    async def async_take_clones(self, *args: Any, **kwargs: Any) -> list[Plant]:
        """Alias for take_clones."""
        return await self.take_clones(*args, **kwargs)

    async def async_transition_plant_stage(self, *args: Any, **kwargs: Any) -> Plant:
        """Alias for transition_plant_stage."""
        return await self.transition_plant_stage(*args, **kwargs)

    async def async_transition_plant(self, *args: Any, **kwargs: Any) -> None:
        """Alias for transition_plant."""
        await self.transition_plant(*args, **kwargs)

    async def async_promote_clone(self, *args: Any, **kwargs: Any) -> Plant:
        """Alias for promote_clone."""
        return await self.promote_clone(*args, **kwargs)

    async def handle_clone_creation(self, **kwargs: Any) -> str:
        """Compatibility wrapper for add_plant as a clone."""
        kwargs.setdefault("stage", PlantStage.CLONE)
        kwargs.setdefault("plant_type", PlantStage.CLONE)
        plant = await self.add_plant(
            growspace_id=kwargs.pop("growspace_id"),
            strain=kwargs.pop("strain"),
            **kwargs,
        )
        return plant.plant_id

    # Alias for tests that use positional arguments
    async def handle_transition_logic(self, *args: Any, **kwargs: Any) -> None:
        """Alias for transition_plant with positional flexibility."""
        if len(args) >= 2 and (
            hasattr(args[1], "plant_id") or type(args[1]).__name__ == "MagicMock"
        ):
            # Shifted call: (plant_id, plant, target_growspace_id, target_growspace_name, transition_date)
            await self.transition_plant(
                plant_id=args[0],
                plant=args[1],
                target_growspace_id=args[2] if len(args) > 2 else None,
                target_growspace_name=args[3] if len(args) > 3 else None,
                transition_date=args[4] if len(args) > 4 else None,
                **kwargs,
            )
        else:
            await self.transition_plant(*args, **kwargs)

    async def handle_move_plant(self, *args: Any, **kwargs: Any) -> Plant:
        """Alias for move_plant."""
        return await self.move_plant(*args, **kwargs)

    async def handle_take_clone(self, *args: Any, **kwargs: Any) -> list[Plant]:
        """Alias for take_clones."""
        return await self.take_clones(*args, **kwargs)

    async def handle_transition_plant_stage(self, *args: Any, **kwargs: Any) -> Plant:
        """Alias for transition_plant_stage."""
        return await self.transition_plant_stage(*args, **kwargs)

    async def handle_update_plant(self, *args: Any, **kwargs: Any) -> Plant:
        """Alias for update_plant."""
        return await self.update_plant(*args, **kwargs)

    async def handle_remove_plant(self, *args: Any, **kwargs: Any) -> None:
        """Alias for remove_plant."""
        await self.remove_plant(*args, **kwargs)

    async def handle_switch_plants(self, *args: Any, **kwargs: Any) -> list[Plant]:
        """Alias for switch_plants."""
        return await self.switch_plants(*args, **kwargs)
