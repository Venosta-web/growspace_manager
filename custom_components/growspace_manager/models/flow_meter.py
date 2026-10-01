"""A meter's placement; measurement metadata always belongs to Home Assistant."""

from dataclasses import dataclass

from .base import BaseModel


@dataclass
class FlowMeter(BaseModel):
    """One configured instrument, on the supply or an irrigation zone."""

    entity_id: str
    placement: str
