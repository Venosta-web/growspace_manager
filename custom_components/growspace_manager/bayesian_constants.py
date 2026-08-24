"""Bayesian evaluator probability constants and thresholds.

This module contains all probability tuples, thresholds, and configuration
values used by the Bayesian evaluator for environmental condition assessment.
"""

from __future__ import annotations

# =========================================================================
# TREND EVALUATION PROBABILITIES
# =========================================================================

# Probability tuples for trend detection: (true_prob, false_prob)
PROB_TREND_FAST_RISE = (0.95, 0.15)
"""Fast rising trend probability."""

PROB_TREND_SLOW_RISE = (0.75, 0.30)
"""Slow rising trend probability."""

PROB_TREND_RISE = (0.85, 0.25)
"""General rising trend probability."""

PROB_TREND_EXTERNAL = (0.90, 0.20)
"""External trend sensor probability."""

PROB_TREND_STATS = (0.85, 0.25)
"""Statistics sensor trend probability."""

# =========================================================================
# TEMPERATURE STRESS PROBABILITIES
# =========================================================================

PROB_NIGHT_TEMP_HIGH = (0.80, 0.20)
"""Probability for high nighttime temperature."""

PROB_TEMP_EXTREME_HEAT = (0.98, 0.05)
"""Probability for extreme heat conditions."""

PROB_TEMP_HIGH_HEAT = (0.85, 0.15)
"""Probability for high heat conditions."""

PROB_TEMP_WARM_LATE_FLOWER = (0.70, 0.30)
"""Probability for warm temperature during late flower."""

PROB_TEMP_WARM = (0.65, 0.30)
"""Probability for warm temperature."""

PROB_TEMP_EXTREME_COLD = (0.95, 0.08)
"""Probability for extreme cold conditions."""

PROB_TEMP_COLD = (0.80, 0.20)
"""Probability for cold temperature."""

# =========================================================================
# HUMIDITY STRESS PROBABILITIES
# =========================================================================

PROB_HUMIDITY_TOO_DRY = (0.85, 0.20)
"""Probability for excessively low humidity."""

PROB_HUMIDITY_HIGH_VEG = (0.80, 0.20)
"""Probability for high humidity during vegetative stage."""

PROB_HUMIDITY_FLOWER_MID_OUT_OF_RANGE = (0.75, 0.25)
"""Probability for humidity out of range during mid-flower."""

PROB_HUMIDITY_FLOWER_LATE_OUT_OF_RANGE = (0.85, 0.15)
"""Probability for humidity out of range during late-flower."""

# =========================================================================
# CO2 STRESS PROBABILITIES
# =========================================================================

PROB_CO2_LOW = (0.80, 0.25)
"""Probability for low CO2 levels."""

PROB_CO2_HIGH = (0.95, 0.10)
"""Probability for high CO2 levels."""

PROB_CO2_LATE_FLOWER_OPTIMAL = (0.90, 0.25)
"""Probability for optimal CO2 during late flower."""

PROB_CO2_LATE_FLOWER_ACCEPTABLE = (0.4, 0.6)
"""Probability for acceptable CO2 during late flower."""

# =========================================================================
# ACTIVE STRESS PROBABILITIES
# =========================================================================

PROB_ACTIVE_DESICCATION = (0.95, 0.05)
"""Probability for active desiccation (dehumidifier on with low humidity or high VPD)."""

PROB_ACTIVE_SATURATION = (0.85, 0.15)
"""Probability for active saturation (humidifier on with high humidity)."""

# =========================================================================
# TEMPERATURE THRESHOLDS (°C)
# =========================================================================

TEMP_NIGHT_HIGH_THRESHOLD = 24
"""Temperature threshold for high nighttime temperature."""

TEMP_EXTREME_HEAT_THRESHOLD = 32
"""Temperature threshold for extreme heat."""

TEMP_HIGH_HEAT_THRESHOLD = 30
"""Temperature threshold for high heat."""

TEMP_WARM_LATE_FLOWER_THRESHOLD = 27
"""Temperature threshold for warm conditions during late flower."""

TEMP_WARM_THRESHOLD = 28
"""Temperature threshold for warm conditions."""

TEMP_EXTREME_COLD_THRESHOLD = 15
"""Temperature threshold for extreme cold."""

TEMP_COLD_THRESHOLD = 18
"""Temperature threshold for cold conditions."""

# Temperature optimal ranges
TEMP_LATE_FLOWER_MIN = 22
"""Minimum optimal temperature for late flower."""

TEMP_LATE_FLOWER_MAX = 26
"""Maximum optimal temperature for late flower."""

TEMP_LIGHTS_ON_PERFECT_MIN = 24
"""Minimum perfect temperature for lights on."""

TEMP_LIGHTS_ON_PERFECT_MAX = 26
"""Maximum perfect temperature for lights on."""

TEMP_LIGHTS_ON_GOOD_MIN = 22
"""Minimum good temperature for lights on."""

TEMP_LIGHTS_ON_GOOD_MAX = 28
"""Maximum good temperature for lights on."""

TEMP_LIGHTS_ON_ACCEPTABLE_MIN = 20
"""Minimum acceptable temperature for lights on."""

TEMP_LIGHTS_ON_ACCEPTABLE_MAX = 29
"""Maximum acceptable temperature for lights on."""

TEMP_LIGHTS_OFF_PERFECT_MIN = 20
"""Minimum perfect temperature for lights off."""

TEMP_LIGHTS_OFF_PERFECT_MAX = 23
"""Maximum perfect temperature for lights off."""

# =========================================================================
# HUMIDITY THRESHOLDS (%)
# =========================================================================

HUMIDITY_TOO_DRY_THRESHOLD = 35
"""Humidity threshold for too dry conditions."""

HUMIDITY_HIGH_VEG_THRESHOLD = 80
"""Humidity threshold for high humidity during vegetative stage."""

HUMIDITY_FLOWER_MID_MIN = 45
"""Minimum humidity for mid-flower stage."""

HUMIDITY_FLOWER_MID_MAX = 60
"""Maximum humidity for mid-flower stage."""

HUMIDITY_FLOWER_LATE_MIN = 40
"""Minimum humidity for late-flower stage."""

HUMIDITY_FLOWER_LATE_MAX = 60
"""Maximum humidity for late-flower stage."""

HUMIDITY_ACTIVE_DESICCATION_THRESHOLD = 40
"""Humidity threshold for active desiccation check."""

HUMIDITY_SATURATION_VEG_THRESHOLD = 80
"""Humidity threshold for saturation during vegetative stage."""

HUMIDITY_SATURATION_FLOWER_THRESHOLD = 60
"""Humidity threshold for saturation during flower stage."""

# Trend detection thresholds
HUMIDITY_CHANGE_THRESHOLD = 1.0
"""Humidity change threshold for stats sensor (%)."""


# Acclimation period for seedlings and clones
ACCLIMATION_START_DAYS = 3
"""End of full acclimation (start of transition)."""

ACCLIMATION_END_DAYS = 7
"""End of transition to standard stage."""

HUMIDITY_ACCLIMATION_MIN = 95
"""Minimum humidity for acclimation stage."""

HUMIDITY_ACCLIMATION_MAX = 100
"""Maximum humidity for acclimation stage."""

# =========================================================================
# VPD THRESHOLDS (kPa)
# =========================================================================

VPD_DANGER_ZONE_VEG = 0.5
"""VPD danger zone threshold for vegetative stage."""

VPD_DANGER_ZONE_FLOWER = 0.8
"""VPD danger zone threshold for flower stage."""

VPD_ACTIVE_DESICCATION_THRESHOLD = 1.6
"""VPD threshold for active desiccation check."""

# Trend detection thresholds
VPD_CHANGE_THRESHOLD = -0.1
"""VPD change threshold for stats sensor (kPa)."""

# =========================================================================
# CO2 THRESHOLDS (ppm)
# =========================================================================

CO2_LOW_THRESHOLD = 400
"""CO2 threshold for low levels."""

CO2_HIGH_THRESHOLD = 1600
"""CO2 threshold for high levels."""

# CO2 optimal ranges
CO2_LATE_FLOWER_OPTIMAL_MIN = 400
"""Minimum optimal CO2 for late flower."""

CO2_LATE_FLOWER_OPTIMAL_MAX = 800
"""Maximum optimal CO2 for late flower."""

CO2_LATE_FLOWER_ACCEPTABLE_MIN = 800
"""Minimum acceptable CO2 for late flower."""

CO2_LATE_FLOWER_ACCEPTABLE_MAX = 1200
"""Maximum acceptable CO2 for late flower."""

CO2_PERFECT_MIN = 1000
"""Minimum perfect CO2 level."""

CO2_PERFECT_MAX = 1400
"""Maximum perfect CO2 level."""

CO2_GOOD_MIN = 800
"""Minimum good CO2 level."""

CO2_GOOD_MAX = 1500
"""Maximum good CO2 level."""

CO2_ACCEPTABLE_MIN = 400
"""Minimum acceptable CO2 level."""

CO2_ACCEPTABLE_MAX = 600
"""Maximum acceptable CO2 level."""

# =========================================================================
# SOIL MOISTURE THRESHOLDS (%)
# =========================================================================

SOIL_MOISTURE_LOW_THRESHOLD = 20
"""Soil moisture threshold for low/dry conditions."""

SOIL_MOISTURE_HIGH_THRESHOLD = 60
"""Soil moisture threshold for high/wet conditions."""

# =========================================================================
# TREND ANALYSIS DEFAULTS
# =========================================================================

DEFAULT_TREND_DURATION = 30
"""Default duration for trend analysis (minutes)."""

DEFAULT_TREND_THRESHOLD_TEMP = 26.0
"""Default temperature threshold for trend analysis."""

TREND_GRADIENT_FAST_THRESHOLD = 0.1
"""Gradient threshold for distinguishing fast vs slow trend rising."""

DEFAULT_TREND_SENSITIVITY = 0.5
"""Default sensitivity for trend detection (0.0-1.0)."""

# Sensitivity calculation constants
SENSITIVITY_TRUE_MULTIPLIER = 0.45
"""Multiplier for true probability calculation."""

SENSITIVITY_FALSE_MULTIPLIER = 0.4
"""Multiplier for false probability calculation."""

SENSITIVITY_BASE_PROB = 0.5
"""Base probability for sensitivity calculations."""

# Mold trend analysis defaults
MOLD_TREND_THRESHOLD_HUMIDITY = 101
"""Default humidity threshold for mold trend analysis."""

MOLD_TREND_THRESHOLD_VPD = -1
"""Default VPD threshold for mold trend analysis."""

# =========================================================================
# MISC THRESHOLDS
# =========================================================================

HUMIDIFIER_ACTIVE_THRESHOLD = 0
"""Value threshold to determine if humidifier is active."""

TREND_SIGNIFICANCE_THRESHOLD = 0.2
"""Threshold for determining trend significance."""

TREND_FALLBACK_THRESHOLD = 1.0
"""Fallback threshold for other sensors."""

# =========================================================================
# SUBSTRATE TEMPERATURE THRESHOLDS AND PROBABILITIES
# =========================================================================

SUBSTRATE_TEMP_OPTIMAL_MIN = 18
"""Minimum optimal substrate temperature (°C)."""

SUBSTRATE_TEMP_OPTIMAL_MAX = 22
"""Maximum optimal substrate temperature (°C)."""

SUBSTRATE_TEMP_STRESS_LOW = 15
"""Substrate temperature below which stress occurs (°C)."""

SUBSTRATE_TEMP_STRESS_HIGH = 26
"""Substrate temperature above which stress occurs (°C)."""

PROB_SUBSTRATE_TEMP_STRESS = (0.80, 0.20)
"""Probability for substrate temperature stress conditions."""

PROB_SUBSTRATE_TEMP_EXTREME = (0.95, 0.08)
"""Probability for extreme substrate temperature stress."""
