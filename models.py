from dataclasses import dataclass, field, asdict, fields
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
    phenotype: str = ""  # default
    row: int = 1
    col: int = 1
    stage: str = ""
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

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "Plant":
        # Only keep keys that match dataclass fields
        allowed_keys = {f.name for f in fields(Plant)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_keys}
        return Plant(**filtered_data)
