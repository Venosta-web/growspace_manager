"""Dehumidifier Coordinator for Growspace Manager."""

from __future__ import annotations

from .const import (
    CATEGORY_DEHUMIDIFIER,
    DEFAULT_DEHUMIDIFIER_MIN_OFFTIME,
    DEFAULT_DEHUMIDIFIER_MIN_RUNTIME,
    PlantStage,
)
from .vpd_on_off_controller import VpdOnOffController

# Default thresholds — dehumidifier turns ON when VPD falls below `on`, OFF when it rises above `off`.
# Low VPD = high humidity = needs dehumidification.
# Format: {stage: {day_or_night: {on: float, off: float}}}
DEFAULT_THRESHOLDS = {
    PlantStage.SEEDLING: {
        "day": {"on": 0.5, "off": 0.6},
        "night": {"on": 0.55, "off": 0.65},
    },
    PlantStage.MOTHER: {
        "day": {"on": 0.6, "off": 0.7},
        "night": {"on": 0.65, "off": 0.75},
    },
    PlantStage.VEG: {
        "day": {"on": 0.6, "off": 0.7},
        "night": {"on": 0.65, "off": 0.75},
    },
    PlantStage.FLOWER_EARLY: {
        "day": {"on": 1.1, "off": 1.2},
        "night": {"on": 0.7, "off": 0.9},
    },
    PlantStage.FLOWER_MID: {
        "day": {"on": 1.25, "off": 1.35},
        "night": {"on": 0.9, "off": 1},
    },
    PlantStage.FLOWER_LATE: {
        "day": {"on": 1.35, "off": 1.4},
        "night": {"on": 0.95, "off": 1.05},
    },
    PlantStage.DRY: {
        "day": {"on": 0.8, "off": 1.0},
        "night": {"on": 0.85, "off": 1.05},
    },
    PlantStage.CURE: {
        "day": {"on": 0.9, "off": 1.1},
        "night": {"on": 0.95, "off": 1.15},
    },
}


class DehumidifierCoordinator(VpdOnOffController):
    """Controls a dehumidifier based on VPD and growth stage.

    Turns ON when VPD falls below the threshold (air is too humid).
    Turns OFF when VPD rises above the off threshold (humidity acceptable).

    Exhaust fans are owned solely by the ``ExhaustFanController`` (ADR-0019);
    this coordinator controls only ``dehumidifier_entities``.
    """

    _CONTROL_FLAG_ATTR = "control_dehumidifier"
    _THRESHOLDS_ATTR = "dehumidifier_thresholds"
    _DEVICE_CONFIG_ATTR = "dehumidifier_config"
    _ON_TRIGGER_IS_HIGH_VPD = False
    _DEFAULT_THRESHOLDS = DEFAULT_THRESHOLDS
    _LOGBOOK_SENSOR_TYPE = "dehumidifier_control"
    _LOGBOOK_CATEGORY = CATEGORY_DEHUMIDIFIER
    _DEFAULT_MIN_RUNTIME = DEFAULT_DEHUMIDIFIER_MIN_RUNTIME
    _DEFAULT_MIN_OFFTIME = DEFAULT_DEHUMIDIFIER_MIN_OFFTIME

    def _get_all_controlled_entities(self) -> list[str]:
        if not self.growspace or not self.growspace.environment_config:
            return []
        env = self.growspace.environment_config
        return list(env.dehumidifier_entities or [])
