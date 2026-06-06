"""Humidifier Coordinator for Growspace Manager."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .const import (
    CATEGORY_HUMIDIFIER,
    DEFAULT_HUMIDIFIER_MIN_OFFTIME,
    DEFAULT_HUMIDIFIER_MIN_RUNTIME,
    PlantStage,
)
from .vpd_on_off_controller import VpdOnOffController

if TYPE_CHECKING:
    from .coordinator import GrowspaceCoordinator

# Default thresholds — humidifier turns ON when VPD exceeds `on`, OFF when it drops below `off`.
# High VPD = low humidity = needs humidification.
# Format: {stage: {day_or_night: {on: float, off: float}}}
DEFAULT_THRESHOLDS = {
    PlantStage.SEEDLING: {
        "day": {"on": 0.7, "off": 0.5},
        "night": {"on": 0.75, "off": 0.55},
    },
    PlantStage.MOTHER: {
        "day": {"on": 0.9, "off": 0.7},
        "night": {"on": 0.85, "off": 0.65},
    },
    PlantStage.VEG: {
        "day": {"on": 1.0, "off": 0.8},
        "night": {"on": 0.85, "off": 0.65},
    },
    PlantStage.FLOWER_EARLY: {
        "day": {"on": 1.4, "off": 1.2},
        "night": {"on": 1.0, "off": 0.8},
    },
    PlantStage.FLOWER_MID: {
        "day": {"on": 1.6, "off": 1.4},
        "night": {"on": 1.2, "off": 1.0},
    },
    PlantStage.FLOWER_LATE: {
        "day": {"on": 1.7, "off": 1.5},
        "night": {"on": 1.3, "off": 1.1},
    },
    PlantStage.DRY: {
        "day": {"on": 1.2, "off": 1.0},
        "night": {"on": 1.2, "off": 1.0},
    },
    PlantStage.CURE: {
        "day": {"on": 1.2, "off": 1.0},
        "night": {"on": 1.2, "off": 1.0},
    },
}


class HumidifierCoordinator(VpdOnOffController):
    """Controls a humidifier based on VPD and growth stage.

    Turns ON when VPD rises above the threshold (air is too dry).
    Turns OFF when VPD falls below the off threshold (sufficient humidity).
    """

    _CONTROL_FLAG_ATTR = "control_humidifier"
    _THRESHOLDS_ATTR = "humidifier_thresholds"
    _DEVICE_CONFIG_ATTR = "humidifier_config"
    _ON_TRIGGER_IS_HIGH_VPD = True
    _DEFAULT_THRESHOLDS = DEFAULT_THRESHOLDS
    _LOGBOOK_SENSOR_TYPE = "humidifier_control"
    _LOGBOOK_CATEGORY = CATEGORY_HUMIDIFIER
    _DEFAULT_MIN_RUNTIME = DEFAULT_HUMIDIFIER_MIN_RUNTIME
    _DEFAULT_MIN_OFFTIME = DEFAULT_HUMIDIFIER_MIN_OFFTIME

    def _get_all_controlled_entities(self) -> list[str]:
        if not self.growspace or not self.growspace.environment_config:
            return []
        return list(self.growspace.environment_config.humidifier_entities or [])
