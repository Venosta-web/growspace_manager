from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import Any


@dataclass
class Growspace:
    id: str
    name: str
    rows: int = 3
    plants_per_row: int = 3
    notification_target: str | None = None
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    device_id: str | None = None
    environment_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> Growspace:
        """Create Growspace from dict, handling legacy field names."""
        data = data.copy()  # Don't modify original

        # Migrate old field names
        if "created" in data and "created_at" not in data:
            data["created_at"] = data.pop("created")

        if "updated" in data and "updated_at" not in data:
            data["updated_at"] = data.pop("updated")

        # Only keep keys that match dataclass fields
        allowed_keys = {f.name for f in fields(Growspace)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_keys}

        return Growspace(**filtered_data)


@dataclass
class Plant:
    plant_id: str
    growspace_id: str
    strain: str
    phenotype: str = ""
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
    transition_date: str | None = None
    source_mother: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> Plant:
        """Create Plant from dict, handling legacy field names."""
        data = data.copy()  # Don't modify original

        # Migrate old field names
        if "created" in data and "created_at" not in data:
            data["created_at"] = data.pop("created")

        if "updated" in data and "updated_at" not in data:
            data["updated_at"] = data.pop("updated")

        # Only keep keys that match dataclass fields
        allowed_keys = {f.name for f in fields(Plant)}
        filtered_data = {k: v for k, v in data.items() if k in allowed_keys}

        return Plant(**filtered_data)
