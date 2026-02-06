"""Centralized stage definitions for Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final


# Constants for stage logic and transitions
DEFAULT_FLOWER_EARLY_DAYS: Final = 21
DEFAULT_FLOWER_MID_DAYS: Final = 21
FLOWER_LATE_MIN_DAYS: Final = 42

TRANSITION_WINDOW: Final = 3


class PlantStage(StrEnum):
    """Stages of plant growth (persisted to storage)."""

    SEEDLING = "seedling"
    CLONE = "clone"
    MOTHER = "mother"
    VEG = "veg"
    FLOWER = "flower"
    DRY = "dry"
    CURE = "cure"


class BayesianStage(StrEnum):
    """Internal stage identifiers used for logic and transitions."""

    SEEDLING = "seedling"
    SEEDLING_STANDARD = "seedling_standard"
    CLONE = "clone"
    CLONE_STANDARD = "clone_standard"
    VEG = "veg"
    FLOWER_EARLY = "flower_early"
    FLOWER_MID = "flower_mid"
    FLOWER_LATE = "flower_late"
    DRY = "dry"
    CURE = "cure"


@dataclass(frozen=True, slots=True)
class StageDefinition:
    """Metadata definition for a plant stage."""

    id: PlantStage
    start_field: str
    order: int
    is_special_growspace: bool = False
    has_substages: bool = False
    display_name: str = ""
    icon: str = ""

    def __post_init__(self) -> None:
        """Set default display name if none provided."""
        if not self.display_name:
            object.__setattr__(self, "display_name", self.id.value.capitalize())


# Registry for all stages
STAGE_REGISTRY: Final[dict[PlantStage, StageDefinition]] = {
    PlantStage.SEEDLING: StageDefinition(
        id=PlantStage.SEEDLING,
        start_field="seedling_start",
        order=10,
        icon="mdi:sprout",
    ),
    PlantStage.CLONE: StageDefinition(
        id=PlantStage.CLONE,
        start_field="clone_start",
        order=20,
        is_special_growspace=True,
        icon="mdi:sprout",
    ),
    PlantStage.MOTHER: StageDefinition(
        id=PlantStage.MOTHER,
        start_field="mother_start",
        order=30,
        is_special_growspace=True,
        icon="mdi:sprout",
    ),
    PlantStage.VEG: StageDefinition(
        id=PlantStage.VEG,
        start_field="veg_start",
        order=40,
        icon="mdi:sprout",
    ),
    PlantStage.FLOWER: StageDefinition(
        id=PlantStage.FLOWER,
        start_field="flower_start",
        order=50,
        has_substages=True,
        icon="mdi:flower",
    ),
    PlantStage.DRY: StageDefinition(
        id=PlantStage.DRY,
        start_field="dry_start",
        order=60,
        is_special_growspace=True,
        icon="mdi:hair-dryer",
    ),
    PlantStage.CURE: StageDefinition(
        id=PlantStage.CURE,
        start_field="cure_start",
        order=70,
        is_special_growspace=True,
        icon="mdi:cannabis",
    ),
}

# Sorted stages by order (progression)
STAGES_ORDERED: Final[list[StageDefinition]] = sorted(
    STAGE_REGISTRY.values(), key=lambda s: s.order
)

# Derived lists for constants
PLANT_STAGES: Final[list[str]] = [s.value for s in PlantStage]
SPECIAL_GROWSPACE_STAGES: Final[list[str]] = [
    s.id.value for s in STAGE_REGISTRY.values() if s.is_special_growspace
]


def get_stage_definition(stage: str | PlantStage) -> StageDefinition | None:
    """Retrieve stage definition by ID or string."""
    if isinstance(stage, str):
        try:
            stage_enum = PlantStage(stage)
        except ValueError:
            return None
    else:
        stage_enum = stage

    return STAGE_REGISTRY.get(stage_enum)
