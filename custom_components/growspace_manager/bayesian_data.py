from __future__ import annotations
from typing import Final, Any, Dict, List, Tuple

# =========================================================================
# GENERAL PROBABILITY CONSTANTS (P(Obs|True), P(Obs|False))
# =========================================================================

# Used by Optimal Sensor (if implemented here)
PROB_PERFECT: Final = (0.95, 0.20)
PROB_GOOD: Final = (0.85, 0.30)
PROB_ACCEPTABLE: Final = (0.65, 0.45)

# Used by Stress Sensor
PROB_STRESS_OUT_OF_RANGE: Final = (0.20, 0.75)
PROB_VPD_STRESS_OUT_OF_RANGE: Final = (0.25, 0.70)

# Type aliases for complex structures
VpdThresholdsDict = Dict[str, Dict[str, Dict[str, Any]]]
DryingCuringThresholds = Dict[
    str, Tuple[float, float, Tuple[float, float], Tuple[float, float]]
]


# =========================================================================
# VPD STRESS THRESHOLDS
# Structure: stage -> time_of_day -> { 'stress': (low, high), 'mild': (low, high), ... }
# =========================================================================

VPD_STRESS_THRESHOLDS: Final[VpdThresholdsDict] = {
    "veg_early": {
        "day": {
            "stress": (0.3, 1.0),
            "mild": (0.4, 0.8),
            "prob_keys": (
                "prob_vpd_stress_veg_early",
                "prob_vpd_mild_stress_veg_early",
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
        "night": {
            "stress": (0.3, 1.0),
            "mild": (0.4, 0.8),
            "prob_keys": (
                "prob_vpd_stress_veg_early",
                "prob_vpd_mild_stress_veg_early",
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
    },
    "veg_late": {
        "day": {
            "stress": (0.6, 1.4),
            "mild": (0.8, 1.2),
            "prob_keys": ("prob_vpd_stress_veg_late", "prob_vpd_mild_stress_veg_late"),
            "prob_defaults": ((0.80, 0.18), (0.55, 0.35)),
        },
        "night": {
            "stress": (0.3, 1.0),
            "mild": (0.5, 0.8),
            "prob_keys": ("prob_vpd_stress_veg_late", "prob_vpd_mild_stress_veg_late"),
            "prob_defaults": ((0.80, 0.18), (0.55, 0.35)),
        },
    },
    "flower_early": {
        "day": {
            "stress": (0.8, 1.6),
            "mild": (1.0, 1.5),
            "prob_keys": (
                "prob_vpd_stress_flower_early",
                "prob_vpd_mild_stress_flower_early",
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
        "night": {
            "stress": (0.5, 1.1),
            "mild": (0.7, 1.0),
            "prob_keys": (
                "prob_vpd_stress_flower_early",
                "prob_vpd_mild_stress_flower_early",
            ),
            "prob_defaults": ((0.85, 0.15), (0.60, 0.30)),
        },
    },
    "flower_late": {
        "day": {
            "stress": (1.0, 1.6),
            "mild": (1.2, 1.5),
            "prob_keys": (
                "prob_vpd_stress_flower_late",
                "prob_vpd_mild_stress_flower_late",
            ),
            "prob_defaults": ((0.90, 0.12), (0.65, 0.28)),
        },
        "night": {
            "stress": (0.6, 1.2),
            "mild": (0.8, 1.1),
            "prob_keys": (
                "prob_vpd_stress_flower_late",
                "prob_vpd_mild_stress_flower_late",
            ),
            "prob_defaults": ((0.90, 0.12), (0.65, 0.28)),
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
    Dict[str, Dict[str, List[Tuple[float, float, Tuple[float, float]]]]]
] = {
    "veg_early": {
        "day": [(0.5, 0.7, (0.95, 0.18)), (0.4, 0.8, (0.80, 0.28))],
        "night": [(0.4, 0.8, (0.90, 0.20))],
    },
    "veg_late": {
        "day": [(0.9, 1.1, (0.95, 0.18)), (0.8, 1.2, (0.85, 0.25))],
        "night": [(0.6, 1.1, (0.90, 0.20))],
    },
    "flower_early": {
        "day": [(1.1, 1.4, (0.95, 0.18)), (1.0, 1.5, (0.85, 0.25))],
        "night": [(0.8, 1.2, (0.90, 0.20))],
    },
    "flower_late": {
        "day": [(1.3, 1.5, (0.95, 0.15)), (1.2, 1.6, (0.85, 0.22))],
        "night": [(0.9, 1.2, (0.90, 0.20))],
    },
}
