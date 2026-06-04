"""Base model classes and utilities for the Growspace Manager."""

from __future__ import annotations

from dataclasses import MISSING, dataclass, field, fields
from typing import Any

from mashumaro.mixins.dict import DataClassDictMixin

from custom_components.growspace_manager.const import PlantStage
import homeassistant.util.dt as dt_util

__all__ = ["BaseModel", "BasePreset", "_sanitize_numeric_fields"]


def _sanitize_numeric_fields(cls: type, data: dict[str, Any]) -> dict[str, Any]:
    """Coerce None and float values to proper types for int fields before deserialization.

    With `from __future__ import annotations`, field types are stored as strings,
    so we compare against 'float'/'int' string literals rather than actual types.
    Avoids super() which is broken inside @dataclass(slots=True) classmethods.
    """
    data = data.copy()
    for f in fields(cls):
        if f.name in data:
            val = data[f.name]
            if val is None:
                if f.type in ("float", "int"):
                    if f.default is not MISSING:
                        data[f.name] = f.default
                    else:
                        data[f.name] = 0.0 if f.type == "float" else 0
            elif f.type == "int" and isinstance(val, (float, str)):
                try:
                    data[f.name] = int(float(val))
                except (ValueError, TypeError):
                    # On conversion error, fall back to the field's default or 0.
                    if f.default is not MISSING:
                        data[f.name] = f.default
                    else:
                        data[f.name] = 0
    return data


@dataclass(slots=True)
class BaseModel(DataClassDictMixin):
    """Base class providing generic serialization methods."""

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Generic pre-deserialization to handle None values for numeric fields."""
        return _sanitize_numeric_fields(cls, data)


@dataclass(slots=True, kw_only=True)
class BasePreset(BaseModel):
    """Base class providing generic preset attributes."""

    id: str
    name: str
    items: list[Any]
    stage: PlantStage | str | None = None
    min_days_in_stage: int | None = None
    created_at: str = field(default_factory=lambda: dt_util.utcnow().isoformat())

    @classmethod
    def __pre_deserialize__(cls, data: dict[str, Any]) -> dict[str, Any]:
        """Handle missing 'id' in legacy data by generating one if necessary."""
        data = super().__pre_deserialize__(data)
        if "id" not in data:
            # If id is missing, use a deterministic one based on name if possible,
            # or a random one. Using a name-based ID helps maintain consistency
            # if the same legacy data is loaded multiple times.
            name = data.get("name", "Legacy Preset")
            data["id"] = f"legacy_{name.lower().replace(' ', '_')}"
        return data
