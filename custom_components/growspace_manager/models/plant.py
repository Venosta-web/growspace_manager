"""Plant lifecycle, weight, moisture, phenotype, and drying models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.domain.stage import STAGE_REGISTRY
from custom_components.growspace_manager.utils import calculate_days_since, days_to_week

from .base import BaseModel, _sanitize_numeric_fields
from .types import StageHistoryItem

__all__ = [
    "DryingData",
    "HarvestMetrics",
    "MoistureEntry",
    "PhenotypeScore",
    "Plant",
    "PlantGenetics",
    "WeightEntry",
]


@dataclass(slots=True)
class PlantGenetics(BaseModel):
    """Immutable genetics reference for a plant."""

    strain_id: int | None = None
    phenotype_id: int | None = None
    strain_name: str = ""  # Cached for display/search
    phenotype_name: str = ""
    generation: str = ""  # e.g. F1, F2, S1, BX1 — inherited from seed batch at sowing

    @property
    def key(self) -> str:
        """Unique key for strain+phenotype combo."""
        return (
            f"{self.strain_name}_{self.phenotype_name}"
            if self.phenotype_name
            else self.strain_name
        )


@dataclass(slots=True)
class PhenotypeScore(BaseModel):
    """Fused phenotype-selection rubric scored on a 1–10 scale.

    Replaces the legacy PlantScores model, merging its fields with the
    genetics-tracking rubric.  Old field names are migrated in
    Plant.__pre_deserialize__.
    """

    # Rubric fields (1-10, None = not yet scored)
    vigor: int | None = None
    internodal_spacing: int | None = None  # replaces legacy 'structure'
    terpene_intensity: int | None = None  # replaces legacy 'aroma'
    resin: int | None = None
    mold_resistance: int | None = None  # replaces legacy 'pest_resistance'
    yield_potential: int | None = None

    # Meta
    keeper: bool = False
    notes: str = ""
    updated_at: str | None = None

    @property
    def total_score(self) -> float | None:
        """Average of all rubric fields that have been set."""
        scored = [
            v
            for v in (
                self.vigor,
                self.internodal_spacing,
                self.terpene_intensity,
                self.resin,
                self.mold_resistance,
                self.yield_potential,
            )
            if v is not None
        ]
        if not scored:
            return None
        return sum(scored) / len(scored)


@dataclass(slots=True)
class WeightEntry(BaseModel):
    """A single daily weight observation during drying."""

    date: str = ""
    weight_grams: float = 0.0


@dataclass(slots=True)
class MoistureEntry(BaseModel):
    """A single daily moisture meter reading during drying."""

    date: str = ""
    moisture_percent: float = 0.0


@dataclass(slots=True)
class DryingData(BaseModel):
    """In-progress drying observations for a plant in the dry stage."""

    weight_log: list[WeightEntry] = field(default_factory=list)
    moisture_log: list[MoistureEntry] = field(default_factory=list)
    visual_tag: str | None = None


@dataclass(slots=True)
class HarvestMetrics(BaseModel):
    """Quantitative yield and quality data recorded at harvest."""

    wet_weight: float | None = None
    dry_weight: float | None = None
    trim_weight: float | None = None
    thc_percentage: float | None = None
    cbd_percentage: float | None = None
    terpene_profile: str | None = None


@dataclass(slots=True)
class Plant(BaseModel):
    """Represents a single plant."""

    plant_id: str
    growspace_id: str
    genetics: PlantGenetics = field(default_factory=PlantGenetics)
    row: int = 1
    col: int = 1
    stage: PlantStage | str = ""
    type: str = "normal"
    device_id: str | None = None
    seedling_start: str | None = None
    mother_start: str | None = None
    clone_start: str | None = None
    veg_start: str | None = None
    flower_start: str | None = None
    dry_start: str | None = None
    cure_start: str | None = None
    created_at: str | None = None
    updated_at: str | None = None
    source_mother: str | None = None
    seed_batch_id: str | None = None
    sex: str | None = None
    last_watered: str | None = None
    last_trained: str | None = None
    last_training_technique: str | None = None
    last_ipm: str | None = None
    last_ipm_type: str | None = None
    phi_clearance_date: str | None = None
    stage_history: list[StageHistoryItem] = field(default_factory=list)
    phenotype_score: PhenotypeScore = field(default_factory=PhenotypeScore)
    harvest_metrics: HarvestMetrics = field(default_factory=HarvestMetrics)
    drying_data: DryingData = field(default_factory=DryingData)

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Mashumaro hook: transform data before deserialization."""
        data = _sanitize_numeric_fields(cls, data)

        # Sanitize integer fields - handle "30.0" strings
        for field_name in ["row", "col"]:
            if field_name in data:
                try:
                    data[field_name] = int(float(data[field_name]))
                except ValueError, TypeError:
                    data[field_name] = 1  # Safe default

        # Migration: old 'scores' dict → new 'phenotype_score' with renamed fields.
        # If phenotype_score is already present (new format), discard stale scores key.
        if "scores" in data and "phenotype_score" not in data:
            old: dict[str, Any] = data.pop("scores") or {}
            data["phenotype_score"] = {
                "vigor": old.get("vigor"),
                "internodal_spacing": old.get("structure"),
                "terpene_intensity": old.get("aroma"),
                "resin": old.get("resin"),
                "mold_resistance": old.get("pest_resistance"),
            }
        elif "scores" in data:
            data.pop("scores")

        # Migration: flat fields → PlantGenetics
        if "strain" in data and "genetics" not in data:
            data["genetics"] = {
                "strain_name": data.pop("strain", ""),
                "phenotype_name": data.pop("phenotype", ""),
            }

        # Migration: build stage_history from start dates if not present
        if "stage_history" not in data:
            history = []

            # Collect all start dates using registry
            starts = []
            for stage_def in STAGE_REGISTRY.values():
                field_name = stage_def.start_field
                if date_val := data.get(field_name):
                    starts.append((date_val, stage_def.id.value))

            # Sort by date
            starts.sort(key=lambda x: x[0])

            # Build history segments
            for i, (start_date, stage) in enumerate(starts):
                end_date = None
                if i + 1 < len(starts):
                    end_date = starts[i + 1][0]

                history.append(
                    StageHistoryItem(stage=stage, start=start_date, end=end_date)
                )

            data["stage_history"] = history

        return data

    # Backward-compatible properties
    @property
    def strain(self) -> str:
        """Get strain name from genetics."""
        return self.genetics.strain_name

    @property
    def phenotype(self) -> str:
        """Get phenotype name from genetics."""
        return self.genetics.phenotype_name

    def get_days_since_watering(self) -> int | None:
        """Calculate days since last watering.

        Returns:
            Number of days since last watered, or None if never watered.
        """
        if self.last_watered:
            return calculate_days_since(self.last_watered)
        return None

    def get_days_in_stage(self, stage_name: str) -> int:
        """Calculate days spent in a specific stage using history."""
        total_days = 0
        found_in_history = False

        # 1. Calculate from history
        if self.stage_history:
            for item in self.stage_history:
                if item["stage"] == stage_name:
                    found_in_history = True
                    total_days += calculate_days_since(item["start"], item.get("end"))

            if found_in_history:
                return total_days

        # 2. Fallback to legacy start date attributes
        start_date_attr = f"{stage_name}_start"
        if hasattr(self, start_date_attr):
            start_date = getattr(self, start_date_attr)
            if start_date:
                return calculate_days_since(start_date)

        return 0

    def get_week_in_stage(self, stage_name: str) -> int:
        """Calculate the week number in a specific stage."""
        days = self.get_days_in_stage(stage_name)
        return days_to_week(days)
