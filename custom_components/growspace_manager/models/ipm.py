"""Integrated Pest Management (IPM) preset recipes and types."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TypedDict

from .base import BasePreset

__all__ = ["IPMPreset", "IPMPresetItem", "IPMType"]


class IPMType(StrEnum):
    """Types of IPM applications."""

    FOLIAR = "foliar"
    DRENCH = "drench"
    SYSTEMIC = "systemic"
    OTHER = "other"


class IPMPresetItem(TypedDict, total=False):
    """A single item in an IPM preset recipe."""

    name: str  # type: ignore[assignment]
    dose_amount: float  # type: ignore[assignment]
    dose_unit: str  # type: ignore[assignment]
    phi_days: int  # Pre-harvest interval in days, default 0


@dataclass(slots=True, kw_only=True)
class IPMPreset(BasePreset):
    """A reusable IPM recipe with optional stage conditions."""

    type: IPMType | str
    items: list[IPMPresetItem]
