"""Genetics and breeding models for the Growspace Manager."""

from __future__ import annotations

from dataclasses import dataclass

from .base import BaseModel

__all__ = ["PollinationEvent", "SeedBatch"]


@dataclass(slots=True)
class SeedBatch(BaseModel):
    """A batch of seeds tracked in the genetics inventory."""

    batch_id: str = ""
    strain_name: str = ""
    breeder: str = ""
    quantity: int = 0
    acquisition_date: str = ""  # ISO date YYYY-MM-DD
    generation: str = ""  # e.g. F1, S1, BX1
    lineage: str = ""
    parent_1_strain: str | None = None
    parent_1_phenotype: str | None = None
    parent_2_strain: str | None = None
    parent_2_phenotype: str | None = None
    notes: str = ""


@dataclass(slots=True)
class PollinationEvent(BaseModel):
    """Records a pollination between two plants."""

    event_id: str = ""
    date: str = ""  # ISO date YYYY-MM-DD
    donor_plant_id: str = ""
    receiver_plant_id: str = ""
    notes: str = ""
    result_seed_batch_id: str | None = None
