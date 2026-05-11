"""Constants and type aliases for Bayesian evaluation in Growspace Manager."""

from __future__ import annotations

from typing import Any, Final

from .const import (
    CONF_PROB_VPD_MILD_STRESS_CLONE,
    CONF_PROB_VPD_MILD_STRESS_CLONE_ACCLIMATION,
    CONF_PROB_VPD_MILD_STRESS_CURE,
    CONF_PROB_VPD_MILD_STRESS_DRY,
    CONF_PROB_VPD_MILD_STRESS_FLOWER_EARLY,
    CONF_PROB_VPD_MILD_STRESS_FLOWER_LATE,
    CONF_PROB_VPD_MILD_STRESS_FLOWER_MID,
    CONF_PROB_VPD_MILD_STRESS_MOTHER,
    CONF_PROB_VPD_MILD_STRESS_SEEDLING,
    CONF_PROB_VPD_MILD_STRESS_SEEDLING_ACCLIMATION,
    CONF_PROB_VPD_MILD_STRESS_VEG,
    CONF_PROB_VPD_STRESS_CLONE,
    CONF_PROB_VPD_STRESS_CLONE_ACCLIMATION,
    CONF_PROB_VPD_STRESS_CURE,
    CONF_PROB_VPD_STRESS_DRY,
    CONF_PROB_VPD_STRESS_FLOWER_EARLY,
    CONF_PROB_VPD_STRESS_FLOWER_LATE,
    CONF_PROB_VPD_STRESS_FLOWER_MID,
    CONF_PROB_VPD_STRESS_MOTHER,
    CONF_PROB_VPD_STRESS_SEEDLING,
    CONF_PROB_VPD_STRESS_SEEDLING_ACCLIMATION,
    CONF_PROB_VPD_STRESS_VEG,
)
from .domain.stage import BayesianStage

# =========================================================================
# GENERAL PROBABILITY CONSTANTS (P(Obs|True), P(Obs|False))
# =========================================================================

# Used by Optimal Sensor
PROB_PERFECT: Final = (0.95, 0.20)
PROB_GOOD: Final = (0.85, 0.30)
PROB_ACCEPTABLE: Final = (0.65, 0.45)

# Used by Stress Sensor
PROB_STRESS_OUT_OF_RANGE: Final = (0.20, 0.75)
PROB_VPD_STRESS_OUT_OF_RANGE: Final = (0.25, 0.70)
PROB_STRESS_SATURATION: Final = (0.99, 0.01)

# Used by Mold Risk Sensor
PROB_MOLD_STAGNANT_AIR: Final = (0.85, 0.15)
PROB_MOLD_HUMIDIFIER_ON: Final = (0.95, 0.10)

# Used by Soil Moisture Sensor
PROB_SOIL_MOISTURE_STRESS: Final = (0.85, 0.20)

# Type aliases for complex structures
VpdThresholdsDict = dict[str, dict[str, dict[str, Any]]]
DryingCuringThresholds = dict[
    str, tuple[float, float, tuple[float, float], tuple[float, float]]
]


# =========================================================================
# VPD STRESS THRESHOLDS
# Structure: stage -> time_of_day -> { 'stress': (low, high), 'mild': (low, high), ... }
# =========================================================================

VPD_STRESS_THRESHOLDS: Final[VpdThresholdsDict] = {
    BayesianStage.SEEDLING: {
        "day": {
            "stress": (-0.1, 0.3),
            "mild": (0.0, 0.2),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_SEEDLING_ACCLIMATION,
                CONF_PROB_VPD_MILD_STRESS_SEEDLING_ACCLIMATION,
            ),
            "prob_defaults": ((0.95, 0.05), (0.80, 0.20)),
        },
        "night": {
            "stress": (-0.1, 0.3),
            "mild": (0.0, 0.2),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_SEEDLING_ACCLIMATION,
                CONF_PROB_VPD_MILD_STRESS_SEEDLING_ACCLIMATION,
            ),
            "prob_defaults": ((0.95, 0.05), (0.80, 0.20)),
        },
    },
    BayesianStage.SEEDLING_STANDARD: {
        "day": {
            "stress": (0.3, 1.2),
            "mild": (0.4, 1.0),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_SEEDLING,
                CONF_PROB_VPD_MILD_STRESS_SEEDLING,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
        "night": {
            "stress": (0.4, 1.1),
            "mild": (0.5, 0.9),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_SEEDLING,
                CONF_PROB_VPD_MILD_STRESS_SEEDLING,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
    },
    BayesianStage.CLONE: {
        "day": {
            "stress": (-0.1, 0.3),
            "mild": (0.0, 0.2),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_CLONE_ACCLIMATION,
                CONF_PROB_VPD_MILD_STRESS_CLONE_ACCLIMATION,
            ),
            "prob_defaults": ((0.98, 0.02), (0.85, 0.15)),
        },
        "night": {
            "stress": (-0.1, 0.3),
            "mild": (0.0, 0.2),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_CLONE_ACCLIMATION,
                CONF_PROB_VPD_MILD_STRESS_CLONE_ACCLIMATION,
            ),
            "prob_defaults": ((0.98, 0.02), (0.85, 0.15)),
        },
    },
    BayesianStage.CLONE_STANDARD: {
        "day": {
            "stress": (0.2, 1.0),
            "mild": (0.3, 0.8),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_CLONE,
                CONF_PROB_VPD_MILD_STRESS_CLONE,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
        "night": {
            "stress": (0.3, 0.9),
            "mild": (0.4, 0.7),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_CLONE,
                CONF_PROB_VPD_MILD_STRESS_CLONE,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
    },
    BayesianStage.VEG: {
        "day": {
            "stress": (0.4, 1.4),
            "mild": (0.6, 1.2),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_VEG,
                CONF_PROB_VPD_MILD_STRESS_VEG,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
        "night": {
            "stress": (0.6, 1.2),
            "mild": (0.8, 1.1),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_VEG,
                CONF_PROB_VPD_MILD_STRESS_VEG,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
    },
    # Mother plants follow VEG-like environmental targets
    BayesianStage.MOTHER: {
        "day": {
            "stress": (0.4, 1.4),
            "mild": (0.6, 1.2),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_MOTHER,
                CONF_PROB_VPD_MILD_STRESS_MOTHER,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
        "night": {
            "stress": (0.6, 1.2),
            "mild": (0.8, 1.1),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_MOTHER,
                CONF_PROB_VPD_MILD_STRESS_MOTHER,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
    },
    BayesianStage.FLOWER_EARLY: {
        "day": {
            "stress": (0.8, 1.6),
            "mild": (1.0, 1.5),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_FLOWER_EARLY,
                CONF_PROB_VPD_MILD_STRESS_FLOWER_EARLY,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
        "night": {
            "stress": (0.5, 1.1),
            "mild": (0.7, 1.0),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_FLOWER_EARLY,
                CONF_PROB_VPD_MILD_STRESS_FLOWER_EARLY,
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
    },
    BayesianStage.FLOWER_MID: {
        "day": {
            "stress": (0.9, 1.6),
            "mild": (1.1, 1.5),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_FLOWER_MID,
                CONF_PROB_VPD_MILD_STRESS_FLOWER_MID,
            ),
            "prob_defaults": ((0.88, 0.14), (0.62, 0.29)),
        },
        "night": {
            "stress": (0.6, 1.2),
            "mild": (0.8, 1.1),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_FLOWER_MID,
                CONF_PROB_VPD_MILD_STRESS_FLOWER_MID,
            ),
            "prob_defaults": ((0.88, 0.14), (0.62, 0.29)),
        },
    },
    BayesianStage.FLOWER_LATE: {
        "day": {
            "stress": (1.0, 1.6),
            "mild": (1.2, 1.5),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_FLOWER_LATE,
                CONF_PROB_VPD_MILD_STRESS_FLOWER_LATE,
            ),
            "prob_defaults": ((0.90, 0.12), (0.65, 0.28)),
        },
        "night": {
            "stress": (0.6, 1.2),
            "mild": (0.8, 1.1),
            "prob_keys": (
                CONF_PROB_VPD_STRESS_FLOWER_LATE,
                CONF_PROB_VPD_MILD_STRESS_FLOWER_LATE,
            ),
            "prob_defaults": ((0.90, 0.12), (0.65, 0.28)),
        },
    },
    BayesianStage.DRY: {
        "day": {
            "stress": (0.6, 1.3),
            "mild": (0.8, 1.1),
            "prob_keys": (CONF_PROB_VPD_STRESS_DRY, CONF_PROB_VPD_MILD_STRESS_DRY),
            "prob_defaults": ((0.95, 0.10), (0.90, 0.10)),
        },
        "night": {
            "stress": (0.6, 1.3),
            "mild": (0.8, 1.1),
            "prob_keys": (CONF_PROB_VPD_STRESS_DRY, CONF_PROB_VPD_MILD_STRESS_DRY),
            "prob_defaults": ((0.95, 0.10), (0.90, 0.10)),
        },
    },
    BayesianStage.CURE: {
        "day": {
            "stress": (0.5, 1.1),
            "mild": (0.7, 0.9),
            "prob_keys": (CONF_PROB_VPD_STRESS_CURE, CONF_PROB_VPD_MILD_STRESS_CURE),
            "prob_defaults": ((0.95, 0.10), (0.90, 0.10)),
        },
        "night": {
            "stress": (0.5, 1.1),
            "mild": (0.7, 0.9),
            "prob_keys": (CONF_PROB_VPD_STRESS_CURE, CONF_PROB_VPD_MILD_STRESS_CURE),
            "prob_defaults": ((0.95, 0.10), (0.90, 0.10)),
        },
    },
}

# =========================================================================
# DRYING AND CURING THRESHOLDS
# Structure: sensor -> (optimal_low, optimal_high, prob_optimal, prob_out_of_range)
# =========================================================================

DRYING_THRESHOLDS: Final[DryingCuringThresholds] = {
    "temp": (15, 21, (0.95, 0.10), (0.10, 0.90)),
    "humidity": (45, 55, (0.95, 0.10), (0.10, 0.90)),
}

CURING_THRESHOLDS: Final[DryingCuringThresholds] = {
    "temp": (18, 21, (0.95, 0.10), (0.10, 0.90)),
    "humidity": (55, 60, (0.95, 0.10), (0.10, 0.90)),
}

# =========================================================================
# OPTIMAL CONDITIONS THRESHOLDS
# =========================================================================

# Structure: stage -> time_of_day -> [ (P_low, P_high, P_prob), (G_low, G_high, G_prob), ... ]

VPD_OPTIMAL_THRESHOLDS: Final[
    dict[str, dict[str, list[tuple[float, float, tuple[float, float]]]]]
] = {
    BayesianStage.SEEDLING: {
        "day": [(-0.1, 0.3, (0.98, 0.10)), (0.0, 0.4, (0.85, 0.20))],
        "night": [(-0.1, 0.3, (0.95, 0.15))],
    },
    BayesianStage.SEEDLING_STANDARD: {
        "day": [(0.4, 0.8, (0.95, 0.18)), (0.3, 0.9, (0.80, 0.28))],
        "night": [(0.4, 0.8, (0.90, 0.20))],
    },
    BayesianStage.CLONE: {
        "day": [(-0.1, 0.3, (0.98, 0.10)), (0.0, 0.4, (0.85, 0.20))],
        "night": [(-0.1, 0.3, (0.95, 0.15))],
    },
    BayesianStage.CLONE_STANDARD: {
        "day": [(0.3, 0.7, (0.95, 0.18)), (0.2, 0.8, (0.80, 0.28))],
        "night": [(0.3, 0.7, (0.90, 0.20))],
    },
    BayesianStage.VEG: {
        "day": [(0.5, 0.9, (0.95, 0.18)), (0.4, 0.8, (0.80, 0.28))],
        "night": [(0.4, 0.8, (0.90, 0.20))],
    },
    # Mother plants — VEG-like VPD targets
    BayesianStage.MOTHER: {
        "day": [(0.5, 0.9, (0.95, 0.18)), (0.4, 0.8, (0.80, 0.28))],
        "night": [(0.4, 0.8, (0.90, 0.20))],
    },
    BayesianStage.FLOWER_EARLY: {
        "day": [(0.9, 1.4, (0.95, 0.18)), (1.0, 1.5, (0.85, 0.25))],
        "night": [(0.8, 1.2, (0.90, 0.20))],
    },
    BayesianStage.FLOWER_MID: {
        "day": [(0.95, 1.45, (0.95, 0.17)), (1.1, 1.55, (0.85, 0.24))],
        "night": [(0.85, 1.2, (0.90, 0.20))],
    },
    BayesianStage.FLOWER_LATE: {
        "day": [(1.0, 1.5, (0.95, 0.15)), (1.2, 1.6, (0.85, 0.22))],
        "night": [(0.9, 1.2, (0.90, 0.20))],
    },
    # Dry — 0.8–1.1 kPa optimal; environment runs 24 h uniform
    BayesianStage.DRY: {
        "day": [(0.8, 1.1, (0.95, 0.10)), (0.7, 1.2, (0.85, 0.15))],
        "night": [(0.8, 1.1, (0.95, 0.10))],
    },
    # Cure — 0.6–0.9 kPa optimal; lower VPD to preserve terpenes
    BayesianStage.CURE: {
        "day": [(0.6, 0.9, (0.95, 0.10)), (0.5, 1.0, (0.85, 0.15))],
        "night": [(0.6, 0.9, (0.95, 0.10))],
    },
}

# Structure: stage -> [ (low, high, prob), ... ]
# CO2 optimal ranges for each growth stage
CO2_OPTIMAL_THRESHOLDS: Final[
    dict[str, list[tuple[float, float, tuple[float, float]]]]
] = {
    BayesianStage.SEEDLING: [
        (1000, 1400, PROB_PERFECT),  # Perfect range
        (800, 1500, PROB_GOOD),  # Good range
        (400, 600, PROB_ACCEPTABLE),  # Acceptable range
    ],
    BayesianStage.SEEDLING_STANDARD: [
        (1000, 1400, PROB_PERFECT),
        (800, 1500, PROB_GOOD),
        (400, 600, PROB_ACCEPTABLE),
    ],
    BayesianStage.CLONE: [
        (1000, 1400, PROB_PERFECT),
        (800, 1500, PROB_GOOD),
        (400, 600, PROB_ACCEPTABLE),
    ],
    BayesianStage.CLONE_STANDARD: [
        (1000, 1400, PROB_PERFECT),
        (800, 1500, PROB_GOOD),
        (400, 600, PROB_ACCEPTABLE),
    ],
    BayesianStage.VEG: [
        (1000, 1400, PROB_PERFECT),
        (800, 1500, PROB_GOOD),
        (400, 600, PROB_ACCEPTABLE),
    ],
    BayesianStage.FLOWER_EARLY: [
        (1000, 1400, PROB_PERFECT),
        (800, 1500, PROB_GOOD),
        (400, 600, PROB_ACCEPTABLE),
    ],
    BayesianStage.FLOWER_MID: [
        (1000, 1400, PROB_PERFECT),
        (800, 1500, PROB_GOOD),
        (400, 600, PROB_ACCEPTABLE),
    ],
    BayesianStage.FLOWER_LATE: [
        (400, 800, (0.90, 0.25)),  # Late flower optimal (lower CO2)
        (800, 1200, (0.4, 0.6)),  # Late flower acceptable
    ],
    # Mother — same as VEG, CO2 enrichment beneficial
    BayesianStage.MOTHER: [
        (1000, 1400, PROB_PERFECT),
        (800, 1500, PROB_GOOD),
        (400, 600, PROB_ACCEPTABLE),
    ],
    # Dry/Cure — CO2 enrichment irrelevant post-harvest; ambient range accepted
    BayesianStage.DRY: [
        (400, 700, (0.90, 0.15)),
        (300, 800, (0.70, 0.30)),
    ],
    BayesianStage.CURE: [
        (400, 700, (0.90, 0.15)),
        (300, 800, (0.70, 0.30)),
    ],
}

# structure: stage -> { 'critical': float, 'high': float }
CRITICAL_HUMIDITY_THRESHOLDS: Final[dict[str, dict[str, float]]] = {
    BayesianStage.SEEDLING: {"critical": 102.0, "high": 100.0},
    BayesianStage.CLONE: {"critical": 102.0, "high": 100.0},
    BayesianStage.SEEDLING_STANDARD: {"critical": 92.0, "high": 88.0},
    BayesianStage.CLONE_STANDARD: {"critical": 92.0, "high": 88.0},
    BayesianStage.MOTHER: {"critical": 85.0, "high": 80.0},
    BayesianStage.VEG: {"critical": 85.0, "high": 80.0},
    BayesianStage.FLOWER_EARLY: {"critical": 75.0, "high": 70.0},
    BayesianStage.FLOWER_MID: {"critical": 75.0, "high": 70.0},
    BayesianStage.FLOWER_LATE: {"critical": 65.0, "high": 60.0},
    # Dry — critical RH is much lower to prevent mold on buds
    BayesianStage.DRY: {"critical": 60.0, "high": 55.0},
    # Cure — slightly higher acceptable RH range in jars
    BayesianStage.CURE: {"critical": 68.0, "high": 65.0},
}
