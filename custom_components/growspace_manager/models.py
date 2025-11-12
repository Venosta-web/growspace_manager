"""Models for the Growspace Manager component."""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from typing import Any

_LOGGER = logging.getLogger(__name__)


@dataclass
class Growspace:
    """Represents a growspace."""

    id: str
    name: str
    rows: int = 3
    plants_per_row: int = 3
    notification_target: str | None = None
    created_at: str = field(default_factory=lambda: date.today().isoformat())
    device_id: str | None = None
    environment_config: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a dictionary representation of the growspace."""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> Growspace:
        """Create Growspace from dict, handling legacy fields and casting types."""
        data = data.copy()  # Don't modify original

        # Migrate old field names
        if "created" in data and "created_at" not in data:
            data["created_at"] = data.pop("created")

        # Get all defined field names from the dataclass
        known_keys = {f.name for f in fields(Growspace)}
        filtered_data = {}

        for key, value in data.items():
            if key in known_keys:
                # Cast types
                if key in ("rows", "plants_per_row"):
                    try:
                        filtered_data[key] = int(value)
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            "Invalid type for Growspace %s: %s. Using default",
                            data.get("id", "Unknown"),
                            key,
                        )
                        filtered_data[key] = 3  # Default fallback
                else:
                    filtered_data[key] = value

        # Ensure required fields are present
        if "id" not in filtered_data:
            # This case should ideally not happen if data is managed by the integration
            _LOGGER.error("Growspace data missing 'id': %s", data)
            raise ValueError("Growspace data missing 'id'")
        if "name" not in filtered_data:
            _LOGGER.error("Growspace data missing 'name': %s", data)
            raise ValueError("Growspace data missing 'name'")

        return Growspace(**filtered_data)


@dataclass
class Plant:
    """Represents a plant."""

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
        """Return a dictionary representation of the plant."""
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> Plant:
        """Create Plant from dict, handling legacy fields and casting types."""
        data = data.copy()  # Don't modify original

        # Migrate old field names
        if "created" in data and "created_at" not in data:
            data["created_at"] = data.pop("created")

        if "updated" in data and "updated_at" not in data:
            data["updated_at"] = data.pop("updated")

        # Get all defined field names from the dataclass
        known_keys = {f.name for f in fields(Plant)}
        filtered_data = {}

        for key, value in data.items():
            if key in known_keys:
                # Cast types
                if key in ("row", "col"):
                    try:
                        filtered_data[key] = int(value)
                    except (ValueError, TypeError):
                        _LOGGER.warning(
                            "Invalid type for Plant %s: %s. Using 1.",
                            data.get("plant_id", "Unknown"),
                            key,
                        )
                        filtered_data[key] = 1  # Default fallback
                else:
                    filtered_data[key] = value

        # Ensure required fields are present
        if "plant_id" not in filtered_data:
            _LOGGER.error("Plant data missing 'plant_id': %s", data)
            raise ValueError("Plant data missing 'plant_id'")
        if "growspace_id" not in filtered_data:
            _LOGGER.error("Plant data missing 'growspace_id': %s", data)
            raise ValueError("Plant data missing 'growspace_id'")
        if "strain" not in filtered_data:
            _LOGGER.error("Plant data missing 'strain': %s", data)
            raise ValueError("Plant data missing 'strain'")

        return Plant(**filtered_data)
