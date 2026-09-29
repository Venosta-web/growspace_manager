"""Load Plant records without discarding records this version cannot read."""

from __future__ import annotations

from copy import deepcopy
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.issue_registry import (
    IssueSeverity,
    async_create_issue,
    async_delete_issue,
)

from .const import DOMAIN
from .models import Plant

_LOGGER = logging.getLogger(__name__)
ISSUE_PREFIX = "plant_record_unreadable_"


def _deserialize_plant(raw: Any) -> Plant:
    """Accept an existing Plant or deserialize its stored dictionary."""
    if isinstance(raw, Plant):
        return raw
    if isinstance(raw, dict):
        # The Plant migration hook mutates its input before validation can fail.
        return Plant.from_dict(deepcopy(raw))
    raise TypeError(f"invalid stored type: {type(raw).__name__}")


def load_plant_records(
    hass: HomeAssistant, data: dict[str, Any], quarantine: dict[str, Any]
) -> dict[str, Plant]:
    """Read both stored sections, retaining rejected records for the next save."""
    plants: dict[str, Plant] = {}
    quarantine.clear()
    for section in ("quarantined_plants", "plants"):
        for plant_id, raw in data.get(section, {}).items():
            try:
                plant = _deserialize_plant(raw)
            except Exception as err:
                if isinstance(raw, dict):
                    _LOGGER.exception(
                        "Failed to load plant %s due to data structure mismatch",
                        plant_id,
                    )
                else:
                    _LOGGER.error(
                        "Failed to load plant %s (invalid type: %s)",
                        plant_id,
                        type(raw),
                    )
                quarantine[plant_id] = raw
                async_create_issue(
                    hass,
                    DOMAIN,
                    f"{ISSUE_PREFIX}{plant_id}",
                    is_fixable=False,
                    severity=IssueSeverity.ERROR,
                    translation_key="plant_record_unreadable",
                    translation_placeholders={
                        "plant_id": str(plant_id),
                        "reason": str(err) or type(err).__name__,
                    },
                )
            else:
                plants[plant_id] = plant
                quarantine.pop(plant_id, None)
                async_delete_issue(hass, DOMAIN, f"{ISSUE_PREFIX}{plant_id}")
    return plants
