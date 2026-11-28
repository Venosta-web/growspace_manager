"""Persisted supplemental lighting assignments."""

from dataclasses import dataclass
from enum import StrEnum

from .base import BaseModel


class LightAnchor(StrEnum):
    """Planned main-light transition used by a window endpoint."""

    ON = "lights_on"
    OFF = "lights_off"


@dataclass(frozen=True, slots=True)
class LightWindowEndpoint:
    """Wall-clock minutes before or after a planned transition."""

    anchor: LightAnchor
    offset_minutes: int


@dataclass(frozen=True, slots=True)
class SupplementalLightWindow:
    """One recurring window within the main photoperiod."""

    start: LightWindowEndpoint
    end: LightWindowEndpoint


@dataclass(slots=True)
class SupplementalLight(BaseModel):
    """An output assigned to one growspace with its recurring windows."""

    entity_id: str
    enabled: bool
    windows: list[SupplementalLightWindow]
