"""Centralized stage definitions for Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..bayesian_constants import ACCLIMATION_END_DAYS, ACCLIMATION_START_DAYS
from .plant_lifecycle import CultivationBandId, LifecycleStage, cultivation_band_for

# Constants for stage logic and transitions. The flower band boundaries are not
# here: `cultivation_band_for` in the Plant Lifecycle module owns them, and
# copies of "21" and "42" in the classifier modules are what let this file, the
# coordinator stage, and the Bayesian stage key drift apart at those days (#635).
TRANSITION_WINDOW: Final = 3


class PlantStage(StrEnum):
    """Stages of plant growth (persisted to storage)."""

    SEEDLING = "seedling"
    CLONE = "clone"
    MOTHER = "mother"
    VEG = "veg"
    VEG_EARLY = "veg_early"
    VEG_LATE = "veg_late"
    FLOWER = "flower"
    FLOWER_EARLY = "flower_early"
    FLOWER_MID = "flower_mid"
    FLOWER_LATE = "flower_late"
    DRY = "dry"
    CURE = "cure"


class BayesianStage(StrEnum):
    """Internal stage identifiers used for logic and transitions."""

    SEEDLING = "seedling"
    SEEDLING_STANDARD = "seedling_standard"
    CLONE = "clone"
    CLONE_STANDARD = "clone_standard"
    MOTHER = "mother"
    VEG = "veg"
    VEG_EARLY = "veg_early"
    VEG_LATE = "veg_late"
    FLOWER_EARLY = "flower_early"
    FLOWER_MID = "flower_mid"
    FLOWER_LATE = "flower_late"
    DRY = "dry"
    CURE = "cure"
    EMPTY = "empty"


# Maps internal Bayesian sub-stages to their card-visible parent stage.
# SEEDLING_STANDARD and CLONE_STANDARD are acclimation sub-stages that the
# frontend doesn't distinguish; VEG_EARLY/VEG_LATE collapse to VEG for the
# same reason (ECTargetStage only knows "veg").
_COLLAPSE_MAP: Final[dict[BayesianStage, BayesianStage]] = {
    BayesianStage.SEEDLING_STANDARD: BayesianStage.SEEDLING,
    BayesianStage.CLONE_STANDARD: BayesianStage.CLONE,
    BayesianStage.VEG_EARLY: BayesianStage.VEG,
    BayesianStage.VEG_LATE: BayesianStage.VEG,
}


@dataclass(frozen=True, slots=True)
class StageDays:
    """Max days per stage across all plants in a growspace. -1 means no plant in that stage."""

    veg: int = -1
    flower: int = -1
    dry: int = -1
    cure: int = -1
    seedling: int = -1
    clone: int = -1
    mother: int = -1


@dataclass(frozen=True, slots=True)
class StageClassification:
    """Result of classifying a growspace's current stage from its plant days."""

    stage_a: BayesianStage
    stage_b: BayesianStage
    factor: float
    is_transition_blend: bool = False

    @property
    def display_stage(self) -> BayesianStage:
        """Reported selector stage, preserving band identity during interpolation."""
        raw = (
            self.stage_b
            if self.is_transition_blend and self.factor >= 0.5
            else self.stage_a
        )
        return _COLLAPSE_MAP.get(raw, raw)


FLOWER_BAND_STAGES: Final[dict[CultivationBandId, BayesianStage]] = {
    CultivationBandId.EARLY_FLOWER: BayesianStage.FLOWER_EARLY,
    CultivationBandId.MID_FLOWER: BayesianStage.FLOWER_MID,
    CultivationBandId.LATE_FLOWER: BayesianStage.FLOWER_LATE,
}


def flower_classification(flower_days: int) -> StageClassification:
    """Project the lifecycle module's flower [[Cultivation Band]] onto the pair.

    The band identity is the stage the growspace is *in*; its interpolation hint,
    present only in the three days before a boundary, becomes the blend toward
    the next one. Routing through ``cultivation_band_for`` keeps the day-21 and
    day-42 boundaries in the lifecycle module rather than duplicated here (#635).
    """
    band = cultivation_band_for(LifecycleStage.FLOWER, flower_days)
    stage_a = FLOWER_BAND_STAGES[band.identity]
    if band.interpolation is None:
        return StageClassification(stage_a, stage_a, 0.0)
    stage_b = FLOWER_BAND_STAGES[band.interpolation.adjacent_band]
    return StageClassification(stage_a, stage_b, round(band.interpolation.factor, 2))


def flower_band_stage(flower_days: int) -> BayesianStage | None:
    """Return the flower band a day count falls in, or None when not in flower."""
    if flower_days < 0:
        return None
    return flower_classification(flower_days).stage_a


def classify_stages(days: StageDays) -> StageClassification:
    """Classify a growspace into a StageClassification from per-stage max-days inputs.

    Returns EMPTY when no plants are present (all days == -1). Callers that produce
    probabilistic outputs (Bayesian evaluators, mold strategies) should treat EMPTY
    as "skip evaluation / return 0 probability".
    """
    if days.cure >= 0:
        return StageClassification(BayesianStage.CURE, BayesianStage.CURE, 0.0)
    if days.dry >= 0:
        return StageClassification(BayesianStage.DRY, BayesianStage.DRY, 0.0)
    if days.mother >= 0:
        return StageClassification(BayesianStage.MOTHER, BayesianStage.MOTHER, 0.0)

    if days.flower >= 0:
        return flower_classification(days.flower)

    if days.veg >= 0:
        if days.veg < TRANSITION_WINDOW:
            factor = days.veg / TRANSITION_WINDOW
            return StageClassification(
                BayesianStage.SEEDLING_STANDARD,
                BayesianStage.VEG,
                round(float(factor), 2),
                is_transition_blend=True,
            )
        return StageClassification(BayesianStage.VEG, BayesianStage.VEG, 0.0)

    if days.seedling >= 0:
        ac_start = ACCLIMATION_START_DAYS
        ac_end = ACCLIMATION_END_DAYS
        if days.seedling <= ac_end:
            if days.seedling <= ac_start:
                return StageClassification(
                    BayesianStage.SEEDLING, BayesianStage.SEEDLING, 0.0
                )
            window = ac_end - ac_start
            factor = (days.seedling - ac_start) / window
            return StageClassification(
                BayesianStage.SEEDLING,
                BayesianStage.SEEDLING_STANDARD,
                round(float(factor), 2),
            )
        return StageClassification(
            BayesianStage.SEEDLING_STANDARD, BayesianStage.SEEDLING_STANDARD, 0.0
        )

    if days.clone >= 0:
        ac_start = ACCLIMATION_START_DAYS
        ac_end = ACCLIMATION_END_DAYS
        if days.clone <= ac_end:
            if days.clone <= ac_start:
                return StageClassification(
                    BayesianStage.CLONE, BayesianStage.CLONE, 0.0
                )
            window = ac_end - ac_start
            factor = (days.clone - ac_start) / window
            return StageClassification(
                BayesianStage.CLONE,
                BayesianStage.CLONE_STANDARD,
                round(float(factor), 2),
            )
        return StageClassification(
            BayesianStage.CLONE_STANDARD, BayesianStage.CLONE_STANDARD, 0.0
        )

    return StageClassification(BayesianStage.EMPTY, BayesianStage.EMPTY, 0.0)


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
    try:
        stage_enum = PlantStage(stage)
    except ValueError:
        return None

    return STAGE_REGISTRY.get(stage_enum)
