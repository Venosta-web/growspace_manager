from dataclasses import dataclass, field, asdict
from typing import Optional
from datetime import date


@dataclass
class Growspace:
    id: str
    name: str
    rows: int = 3
    plants_per_row: int = 3
    notification_target: Optional[str] = None
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    device_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Growspace":
        return Growspace(**data)


@dataclass
class Plant:
    plant_id: str
    growspace_id: str
    strain: str
    phenotype: str = ""
    row: int = 1
    col: int = 1
    stage: str = "seedling"
    type: str = "normal"
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    updated_at: Optional[str] = None
    # Stage start dates
    seedling_start: Optional[str] = None
    clone_start: Optional[str] = None
    mother_start: Optional[str] = None
    veg_start: Optional[str] = None
    flower_start: Optional[str] = None
    dry_start: Optional[str] = None
    cure_start: Optional[str] = None
    # Metadata
    source_mother: Optional[str] = None
    device_id: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Plant":
        return Plant(**data)
