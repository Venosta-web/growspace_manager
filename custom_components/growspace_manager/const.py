"""Constants for the Growspace Manager integration."""

from enum import StrEnum
from typing import Final

from .domain.stage import PLANT_STAGES, PlantStage  # noqa: F401

DOMAIN: Final = "growspace_manager"
STORAGE_VERSION: Final = 1
VERSION: Final = "0.3.5"
STORAGE_KEY: Final = f"{DOMAIN}_storage"  # Legacy Key
STORAGE_KEY_CONFIG: Final = f"{DOMAIN}.config"
STORAGE_KEY_PLANTS: Final = f"{DOMAIN}.plants"
STORAGE_KEY_GENETICS: Final = f"{DOMAIN}.genetics"
STORAGE_KEY_AI_BRIEFING: Final = f"{DOMAIN}.ai_briefing"
STORAGE_KEY_AI_CONVERSATIONS: Final = f"{DOMAIN}.ai_conversations"
PLATFORMS: Final[list[str]] = [
    "binary_sensor",
    "calendar",
    "sensor",
    "switch",
]

PARALLEL_UPDATES: Final = 0

# Coordinator Update Interval
COORDINATOR_UPDATE_INTERVAL_MINUTES = 15  # How often coordinator refreshes data

# WebSocket Event Log Lookback Periods
EVENT_LOG_LOOKBACK_DAYS = 30  # Days to look back for manual event logs
ALERT_LOG_LOOKBACK_DAYS = 120  # Days to look back for environmental alerts

# Dehumidifier Control Timing Defaults
DEFAULT_DEHUMIDIFIER_MIN_RUNTIME = 300  # 5 minutes in seconds
DEFAULT_DEHUMIDIFIER_MIN_OFFTIME = 300  # 5 minutes in seconds
DEFAULT_HUMIDIFIER_MIN_RUNTIME = 300  # 5 minutes in seconds
DEFAULT_HUMIDIFIER_MIN_OFFTIME = 300  # 5 minutes in seconds
DEFAULT_VPD_HYSTERESIS = 0.2  # kPa (fallback if not using stage thresholds)

DEFAULT_NAME = "Growspace Manager"

# Canonical IDs for special growspaces
CANONICAL_ID_DRY: Final = "dry"
CANONICAL_ID_CURE: Final = "cure"
CANONICAL_ID_MOTHER: Final = "mother"
CANONICAL_ID_CLONE: Final = "clone"
CANONICAL_ID_VEG: Final = "veg"

# Configuration Keys
CONF_TEMP_SENSOR = "temperature_sensor"
CONF_HUMIDITY_SENSOR = "humidity_sensor"
CONF_VPD_SENSOR = "vpd_sensor"
CONF_CO2_SENSOR = "co2_sensor"
CONF_DEHUMIDIFIER_ENTITY = "dehumidifier_entity"
CONF_CIRCULATION_FAN_ENTITY = "circulation_fan_entity"
CONF_LIGHT_SENSOR = "light_sensor"
CONF_STRESS_THRESHOLD = "stress_threshold"
CONF_MOLD_THRESHOLD = "mold_threshold"
CONF_DEHUMIDIFIER_THRESHOLDS = "dehumidifier_thresholds"
CONF_AI_ENABLED = "ai_enabled"
CONF_ASSISTANT_ID = "assistant_id"
CONF_GROWSPACE = "growspace"
CONF_EXHAUST_ENTITY = "exhaust_entity"
CONF_EXHAUST_FAN_ENTITY = "exhaust_fan_entity"
CONF_HUMIDIFIER_ENTITY = "humidifier_entity"
CONF_SOIL_MOISTURE_SENSOR = "soil_moisture_sensor"
CONF_IRRIGATION_TANK_SENSORS = "irrigation_tank_sensors"
CONF_IRRIGATION_TANK_WARNING_LEVEL = "irrigation_tank_warning_level"
CONF_IRRIGATION_TANK_VOLUME = "irrigation_tank_volume"  # litres
CONF_CONTROL_DEHUMIDIFIER = "control_dehumidifier"
CONF_CONTROL_HUMIDIFIER = "control_humidifier"
CONF_HUMIDIFIER_THRESHOLDS = "humidifier_thresholds"
CONF_BLACKLIST_BREEDERS = "blacklist_breeders"

# Tank water inference service attributes
ATTR_TANK_ENTITY = "tank_entity"
ATTR_VOLUME_LITERS = "volume_liters"

# DLI Tracking Defaults
DEFAULT_DLI_TARGET_VEG: Final = 30.0
DEFAULT_DLI_TARGET_FLOWER: Final = 45.0

# Substrate Temperature Thresholds
SUBSTRATE_TEMP_OPTIMAL_MIN: Final = 18.0
SUBSTRATE_TEMP_OPTIMAL_MAX: Final = 22.0
SUBSTRATE_TEMP_STRESS_LOW: Final = 15.0
SUBSTRATE_TEMP_STRESS_HIGH: Final = 26.0

# Drain EC Defaults
DEFAULT_MAX_EC_DELTA: Final = 0.7
DEFAULT_TARGET_RUNOFF_PERCENT: Final = 20.0

# Multi-Device Config Keys (new)
CONF_SUBSTRATE_TEMP_SENSORS = "substrate_temperature_sensors"
CONF_CAMERA_ENTITIES = "camera_entities"
CONF_LUNG_ROOM_TEMP_SENSORS = "lung_room_temp_sensors"
CONF_SNAPSHOT_INTERVAL = "snapshot_interval_hours"
CONF_POWER_SENSORS = "power_sensors"
CONF_ENERGY_SENSORS = "energy_sensors"
CONF_ELECTRICITY_COST = "electricity_cost_per_kwh"

# Photoperiod Config Keys
CONF_SEEDLING_DAY_HOURS = "seedling_day_hours"
CONF_CLONE_DAY_HOURS = "clone_day_hours"
CONF_MOTHER_DAY_HOURS = "mother_day_hours"
CONF_VEG_DAY_HOURS = "veg_day_hours"
CONF_FLOWER_EARLY_DAY_HOURS = "flower_early_day_hours"
CONF_FLOWER_MID_DAY_HOURS = "flower_mid_day_hours"
CONF_FLOWER_LATE_DAY_HOURS = "flower_late_day_hours"

STAGE_PHOTOPERIOD_KEYS: Final[dict[PlantStage, str]] = {
    PlantStage.SEEDLING: CONF_SEEDLING_DAY_HOURS,
    PlantStage.CLONE: CONF_CLONE_DAY_HOURS,
    PlantStage.MOTHER: CONF_MOTHER_DAY_HOURS,
    PlantStage.VEG: CONF_VEG_DAY_HOURS,
    PlantStage.FLOWER_EARLY: CONF_FLOWER_EARLY_DAY_HOURS,
    PlantStage.FLOWER_MID: CONF_FLOWER_MID_DAY_HOURS,
    PlantStage.FLOWER_LATE: CONF_FLOWER_LATE_DAY_HOURS,
}

# Trend Analysis Constants
CONF_TREND_VPD_THRESHOLD = "trend_vpd_threshold"
CONF_TREND_TEMPERATURE_THRESHOLD = "trend_temperature_threshold"
CONF_TREND_TEMP_THRESHOLD = CONF_TREND_TEMPERATURE_THRESHOLD  # Alias for backward compatibility
CONF_TREND_HUMIDITY_THRESHOLD = "trend_humidity_threshold"
CONF_TREND_VPD_DURATION = "trend_vpd_duration"
CONF_TREND_TEMPERATURE_DURATION = "trend_temperature_duration"
CONF_TREND_TEMP_DURATION = CONF_TREND_TEMPERATURE_DURATION  # Alias
CONF_TREND_HUMIDITY_DURATION = "trend_humidity_duration"
CONF_TREND_VPD_SENSITIVITY = "trend_vpd_sensitivity"
CONF_TREND_TEMPERATURE_SENSITIVITY = "trend_temperature_sensitivity"
CONF_TREND_TEMP_SENSITIVITY = CONF_TREND_TEMPERATURE_SENSITIVITY  # Alias
CONF_TREND_HUMIDITY_SENSITIVITY = "trend_humidity_sensitivity"

CONF_TEMPERATURE_TREND_SENSOR = "temperature_trend_sensor"
CONF_HUMIDITY_TREND_SENSOR = "humidity_trend_sensor"
CONF_VPD_TREND_SENSOR = "vpd_trend_sensor"
CONF_TEMPERATURE_STATS_SENSOR = "temperature_stats_sensor"
CONF_HUMIDITY_STATS_SENSOR = "humidity_stats_sensor"
CONF_VPD_STATS_SENSOR = "vpd_stats_sensor"

CONF_TEMP_TREND_THRESHOLD_RAW = "temp_trend_threshold"  # Legacy/Special case

# Threshold Keys
CONF_ON = "on"
CONF_OFF = "off"
CONF_DAY = "day"
CONF_NIGHT = "night"

# Environment Config Keys
CONF_MIN_SOURCE_AIR_TEMP = "minimum_source_air_temperature"
CONF_CONFIGURE_DEHUMIDIFIER = "configure_dehumidifier"
CONF_CONFIGURE_HUMIDIFIER = "configure_humidifier"
CONF_CONFIGURE_ADVANCED = "configure_advanced"
CONF_CONFIGURE_FAN_CONTROLLER = "configure_fan_controller"
CONF_LST_OFFSET = "lst_offset"

# Mappings for Bayesian Evaluator
CONF_SENSOR_MAP: Final[dict[str, str]] = {
    "temperature": CONF_TEMP_SENSOR,
    "humidity": CONF_HUMIDITY_SENSOR,
    "vpd": CONF_VPD_SENSOR,
}

CONF_TREND_SENSOR_MAP: Final[dict[str, str]] = {
    "temperature": CONF_TEMPERATURE_TREND_SENSOR,
    "humidity": CONF_HUMIDITY_TREND_SENSOR,
    "vpd": CONF_VPD_TREND_SENSOR,
}

CONF_STATS_SENSOR_MAP: Final[dict[str, str]] = {
    "temperature": CONF_TEMPERATURE_STATS_SENSOR,
    "humidity": CONF_HUMIDITY_STATS_SENSOR,
    "vpd": CONF_VPD_STATS_SENSOR,
}

CONF_TREND_DURATION_MAP: Final[dict[str, str]] = {
    "temperature": CONF_TREND_TEMPERATURE_DURATION,
    "humidity": CONF_TREND_HUMIDITY_DURATION,
    "vpd": CONF_TREND_VPD_DURATION,
}

CONF_TREND_THRESHOLD_MAP: Final[dict[str, str]] = {
    "temperature": CONF_TREND_TEMPERATURE_THRESHOLD,
    "humidity": CONF_TREND_HUMIDITY_THRESHOLD,
    "vpd": CONF_TREND_VPD_THRESHOLD,
}

CONF_TREND_SENSITIVITY_MAP: Final[dict[str, str]] = {
    "temperature": CONF_TREND_TEMPERATURE_SENSITIVITY,
    "humidity": CONF_TREND_HUMIDITY_SENSITIVITY,
    "vpd": CONF_TREND_VPD_SENSITIVITY,
}

# Bayesian Probability Config Keys
CONF_PROB_HUMIDITY_HIGH_VEG_EARLY = "prob_humidity_high_veg_early"
CONF_PROB_HUMIDITY_HIGH_VEG_LATE = "prob_humidity_high_veg_late"
CONF_PROB_HUMIDITY_TOO_HUMID_FLOWER = "prob_humidity_too_humid_flower"
CONF_PROB_HUMIDITY_HIGH_FLOWER = "prob_humidity_high_flower"

# Bayesian VPD Stress Probability Config Keys
CONF_PROB_VPD_STRESS_SEEDLING_ACCLIMATION = "prob_vpd_stress_seedling_acclimation"
CONF_PROB_VPD_MILD_STRESS_SEEDLING_ACCLIMATION = (
    "prob_vpd_mild_stress_seedling_acclimation"
)
CONF_PROB_VPD_STRESS_SEEDLING = "prob_vpd_stress_seedling"
CONF_PROB_VPD_MILD_STRESS_SEEDLING = "prob_vpd_mild_stress_seedling"
CONF_PROB_VPD_STRESS_CLONE_ACCLIMATION = "prob_vpd_stress_clone_acclimation"
CONF_PROB_VPD_MILD_STRESS_CLONE_ACCLIMATION = "prob_vpd_mild_stress_clone_acclimation"
CONF_PROB_VPD_STRESS_CLONE = "prob_vpd_stress_clone"
CONF_PROB_VPD_MILD_STRESS_CLONE = "prob_vpd_mild_stress_clone"
CONF_PROB_VPD_STRESS_VEG = "prob_vpd_stress_veg"
CONF_PROB_VPD_MILD_STRESS_VEG = "prob_vpd_mild_stress_veg"
CONF_PROB_VPD_STRESS_VEG_EARLY = "prob_vpd_stress_veg_early"
CONF_PROB_VPD_MILD_STRESS_VEG_EARLY = "prob_vpd_mild_stress_veg_early"
CONF_PROB_VPD_STRESS_VEG_LATE = "prob_vpd_stress_veg_late"
CONF_PROB_VPD_MILD_STRESS_VEG_LATE = "prob_vpd_mild_stress_veg_late"
CONF_PROB_VPD_STRESS_MOTHER = "prob_vpd_stress_mother"
CONF_PROB_VPD_MILD_STRESS_MOTHER = "prob_vpd_mild_stress_mother"
CONF_PROB_VPD_STRESS_FLOWER_EARLY = "prob_vpd_stress_flower_early"
CONF_PROB_VPD_MILD_STRESS_FLOWER_EARLY = "prob_vpd_mild_stress_flower_early"
CONF_PROB_VPD_STRESS_FLOWER_MID = "prob_vpd_stress_flower_mid"
CONF_PROB_VPD_MILD_STRESS_FLOWER_MID = "prob_vpd_mild_stress_flower_mid"
CONF_PROB_VPD_STRESS_FLOWER_LATE = "prob_vpd_stress_flower_late"
CONF_PROB_VPD_MILD_STRESS_FLOWER_LATE = "prob_vpd_mild_stress_flower_late"
CONF_PROB_VPD_STRESS_DRY = "prob_vpd_stress_dry"
CONF_PROB_VPD_MILD_STRESS_DRY = "prob_vpd_mild_stress_dry"
CONF_PROB_VPD_STRESS_CURE = "prob_vpd_stress_cure"
CONF_PROB_VPD_MILD_STRESS_CURE = "prob_vpd_mild_stress_cure"

# Bayesian Temperature Probabilities
CONF_PROB_TEMP_EXTREME_HEAT = "prob_temp_extreme_heat"
CONF_PROB_TEMP_HIGH_HEAT = "prob_temp_high_heat"
CONF_PROB_TEMP_WARM = "prob_temp_warm"
CONF_PROB_TEMP_EXTREME_COLD = "prob_temp_extreme_cold"
CONF_PROB_TEMP_COLD = "prob_temp_cold"
CONF_PROB_NIGHT_TEMP_HIGH = "prob_night_temp_high"

# Bayesian Humidity/Mold Probabilities
CONF_PROB_HUMIDITY_TOO_DRY = "prob_humidity_too_dry"
CONF_PROB_MOLD_TEMP_DANGER_ZONE = "prob_mold_temp_danger_zone"
CONF_PROB_MOLD_HUMIDITY_HIGH_NIGHT = "prob_mold_humidity_high_night"
CONF_PROB_MOLD_VPD_LOW_NIGHT = "prob_mold_vpd_low_night"
CONF_PROB_MOLD_LIGHTS_OFF = "prob_mold_lights_off"
CONF_PROB_MOLD_HUMIDITY_HIGH_DAY = "prob_mold_humidity_high_day"
CONF_PROB_MOLD_VPD_LOW_DAY = "prob_mold_vpd_low_day"
CONF_PROB_MOLD_FAN_OFF = "prob_mold_fan_off"

# Bayesian Trend Probabilities
CONF_PROB_TREND_FAST_RISE = "prob_trend_fast_rise"
CONF_PROB_TREND_SLOW_RISE = "prob_trend_slow_rise"

# Tank Depletion Predictor Defaults
DEFAULT_PREDICTION_WINDOW_HOURS = 72
DEPLETION_DEADBAND_THRESHOLD = 0.1  # %/hour
VPD_WEIGHTING_BASE = 1.2  # kPa threshold for multiplier

# Tank water tracker thresholds (capacity limits and detection)
TANK_MAX_SNAPSHOTS = 2016  # 7d * 24h * 12 readings/h (5-min updates)
TANK_MAX_EVENTS = 500  # rolling event window
TANK_REFILL_THRESHOLD_PCT = 3.0  # % rise → classified as refill
TANK_NOISE_FLOOR_PCT = 1.0  # % change too small to record


# Multi-Device Config Keys
CONF_LIGHT_SENSORS = "light_sensors"
CONF_DEHUMIDIFIER_ENTITIES = "dehumidifier_entities"
CONF_CIRCULATION_FAN_ENTITIES = "circulation_fan_entities"
CONF_HUMIDIFIER_ENTITIES = "humidifier_entities"
CONF_EXHAUST_FAN_ENTITIES = "exhaust_fan_entities"
CONF_TEMP_SENSORS = "temperature_sensors"
CONF_HUMIDITY_SENSORS = "humidity_sensors"
CONF_VPD_SENSORS = "vpd_sensors"
CONF_PH_SENSORS = "ph_sensors"
CONF_FEED_EC_SENSORS = "feed_ec_sensors"
CONF_BULK_EC_SENSORS = "bulk_ec_sensors"
CONF_PORE_EC_SENSORS = "pore_ec_sensors"
CONF_RUNOFF_EC_SENSORS = "runoff_ec_sensors"
CONF_DRAIN_VOLUME_SENSORS = "drain_volume_sensors"
CONF_IRRIGATION_FLOW_SENSORS = "irrigation_flow_sensors"

# Metric Names
METRIC_STRESS = "stress"
METRIC_MOLD_RISK = "mold_risk"
METRIC_OPTIMAL = "optimal"
METRIC_DRYING = "drying"
METRIC_CURING = "curing"
METRIC_LIGHT_MANAGEMENT = "light_management"
METRIC_AIR_EXCHANGE = "air_exchange"
METRIC_VPD = "vpd"
METRIC_TEMPERATURE = "temperature"
METRIC_HUMIDITY = "humidity"

# Attributes
ATTR_GROWSPACE_ID = "growspace_id"
ATTR_PLANT_ID = "plant_id"
ATTR_PLANT_IDS = "plant_ids"
ATTR_STRAIN = "strain"
ATTR_PHENOTYPE = "phenotype"
ATTR_BREEDER = "breeder"
ATTR_LINEAGE = "lineage"
ATTR_BREEDER_LOGO = "breeder_logo"
ATTR_ROW = "row"
ATTR_COL = "col"
ATTR_STAGE = "stage"
ATTR_TRANSITION_DATE = "transition_date"
ATTR_MOTHER_PLANT_ID = "mother_plant_id"
ATTR_TARGET_GROWSPACE_ID = "target_growspace_id"
ATTR_NUM_CLONES = "num_clones"

ATTR_TOTAL_DAYS = "total_days"

# Plant Scores
ATTR_VIGOR = "vigor"
ATTR_STRUCTURE = "structure"
ATTR_AROMA = "aroma"
ATTR_RESIN = "resin"
ATTR_PEST_RESISTANCE = "pest_resistance"

# Harvest Yield & Lab Results
ATTR_WET_WEIGHT = "wet_weight"
ATTR_DRY_WEIGHT = "dry_weight"
ATTR_TRIM_WEIGHT = "trim_weight"
ATTR_THC_PERCENTAGE = "thc_percentage"
ATTR_CBD_PERCENTAGE = "cbd_percentage"
ATTR_TERPENE_PROFILE = "terpene_profile"

# DLI Attributes
ATTR_DLI = "dli"
ATTR_DLI_TARGET = "target_dli"
ATTR_DLI_PERCENTAGE = "percentage_of_target"
ATTR_DLI_ESTIMATED_FINAL = "estimated_final_dli"
ATTR_PPFD_CURRENT = "ppfd_current"

# PHI Attributes
ATTR_PHI_CLEARANCE_DATE = "phi_clearance_date"
ATTR_PHI_DAYS_REMAINING = "phi_days_remaining"

# Substrate Temperature
ATTR_SUBSTRATE_TEMP = "substrate_temp"

# Crop Steering Attributes
ATTR_DRYBACK_PERCENT = "dryback_percent"
ATTR_PEAK_VWC = "peak_vwc"
ATTR_TROUGH_VWC = "trough_vwc"
ATTR_STEERING_MODE = "steering_mode"
ATTR_EC_TREND = "ec_trend"

# Drain EC Attributes
ATTR_FEED_EC = "feed_ec"
ATTR_DRAIN_EC = "drain_ec"
ATTR_DRAIN_VOLUME_ML = "drain_volume_ml"
ATTR_FEED_VOLUME_ML = "feed_volume_ml"
ATTR_MAX_EC_DELTA = "max_ec_delta"
ATTR_TARGET_RUNOFF_PERCENT = "target_runoff_percent"

# Energy Monitoring Attributes
ATTR_DAILY_KWH = "daily_kwh"
ATTR_COST_TOTAL = "cost_total"
ATTR_COST_PER_GRAM = "cost_per_gram"
ATTR_CYCLE_START_DATE = "cycle_start_date"

# Water Usage Attributes
ATTR_LITERS_PER_PLANT_PER_DAY = "liters_per_plant_per_day"
ATTR_LITERS_TODAY = "liters_today"
ATTR_WATER_EFFICIENCY = "water_efficiency"

# EC Ramp Curve Attributes
ATTR_EC_MIN = "ec_min"
ATTR_EC_MAX = "ec_max"

# EC Target Range Attributes
ATTR_FEED_EC_MIN = "feed_ec_min"
ATTR_FEED_EC_MAX = "feed_ec_max"
ATTR_CURRENT_WEEK = "current_week"
ATTR_CURVE_NAME = "curve_name"
ATTR_LAST_MEASURED_EC = "last_measured_ec"
ATTR_DEVIATION = "deviation"
ATTR_CURVE_ID = "curve_id"
ATTR_POINTS = "points"

# Genetics & Seed Attributes
ATTR_ACQUISITION_DATE = "acquisition_date"
ATTR_GENERATION = "generation"
ATTR_DONOR_PLANT_ID = "donor_plant_id"
ATTR_RECEIVER_PLANT_ID = "receiver_plant_id"
ATTR_EVENT_ID = "event_id"
ATTR_BATCH_ID = "batch_id"
ATTR_SEED_BATCH_ID = "seed_batch_id"
ATTR_STRAIN_NAME = "strain_name"
ATTR_DATE = "date"
ATTR_QUANTITY = "quantity"
ATTR_WEIGHT_GRAMS = "weight_grams"
ATTR_MOISTURE_PERCENT = "moisture_percent"
ATTR_VISUAL_TAG = "visual_tag"

ATTR_PROBABILITY = "probability"
ATTR_THRESHOLD = "threshold"
ATTR_OBSERVATIONS = "observations"
ATTR_REASONS = "reasons"
ATTR_EXPECTED_SCHEDULE = "expected_schedule"
ATTR_LIGHT_ENTITY_ID = "light_entity_id"
ATTR_TIME_IN_CURRENT_STATE = "time_in_current_state"

ATTR_NAME = "name"
ATTR_ROWS = "rows"
ATTR_PLANTS_PER_ROW = "plants_per_row"
ATTR_NOTIFICATION_TARGET = "notification_target"

# Watering Attributes
ATTR_WATER_AMOUNT = "amount"
ATTR_NUTRIENTS = "nutrients"
ATTR_AMOUNT_PER_PLANT = "amount_per_plant"
ATTR_PRESET_ID = "preset_id"
ATTR_PRESET_NAME = "preset_name"
ATTR_MIN_DAYS_IN_STAGE = "min_days_in_stage"

# Timeline Attributes
ATTR_IMAGES = "images"
ATTR_TAGS = "tags"
ATTR_METADATA = "metadata"
ATTR_AMOUNT_ML = "amount_ml"
ATTR_PH = "ph"
ATTR_EC = "ec"
ATTR_TRIGGER_TYPE = "trigger_type"
ATTR_AMOUNT = "amount"
ATTR_START_NUMBER = "start_number"
ATTR_PLANT1_ID = "plant1_id"
ATTR_PLANT2_ID = "plant2_id"
ATTR_NEW_ROW = "new_row"
ATTR_NEW_COL = "new_col"
ATTR_NEW_STAGE = "new_stage"
ATTR_DURATION = "duration"
ATTR_TIME = "time"
ATTR_IRRIGATION_TIMES = "irrigation_times"
ATTR_DRAIN_TIMES = "drain_times"

# Events
EVENT_GROWSPACE_LOG_ENTRY: Final = f"{DOMAIN}_log_entry"

# Icons
ICON_NOTIFICATION = "mdi:bell"

# Default Photoperiods (Hours of Light)
DEFAULT_VEG_DAY_HOURS = 18
DEFAULT_FLOWER_DAY_HOURS = 12

# Stage Durations (Days)
DEFAULT_VEG_EARLY_DAYS = 14
DEFAULT_FLOWER_EARLY_DAYS = 21
DEFAULT_FLOWER_MID_DAYS = 21  # Duration of mid flower (21-42 days)

# AI Configuration
CONF_AI_ENABLED = "ai_enabled"
CONF_ASSISTANT_ID = "assistant_id"
CONF_NOTIFICATION_PERSONALITY = "notification_personality"
CONF_AI_AUTO_ALERTS = "ai_auto_alerts"
CONF_BRIEFING_INTERVAL_MINUTES = "briefing_interval_minutes"
CONF_BRIEFING_TRIGGER_ENTITIES = "briefing_trigger_entities"
DEFAULT_BRIEFING_INTERVAL_MINUTES = 30

# Vision Checkup Constants
CONF_VISION_CHECKUP_ENABLED = "vision_checkup_enabled"
CONF_AI_TASK_ENTITY_ID = "ai_task_entity_id"
CONF_VISION_DEBUG_ENABLED = "vision_debug_enabled"
DEFAULT_VISION_EARLY_OFFSET_MINUTES = 60
DEFAULT_VISION_MID_CHECK_HOURS = 6
DEFAULT_VISION_LATE_OFFSET_MINUTES = 60
DEFAULT_VISION_HISTORY_LIMIT = 10

# Notification Defaults
DEFAULT_COOLDOWN_MINUTES = 5

CRITICAL_PROBABILITY_THRESHOLD: Final = 0.9
"""Probability at or above which an alert is considered critical."""

WARNING_PERSISTENCE_MINUTES: Final = 20
"""Minutes a warning-tier alert must persist before notification is sent."""

CRITICAL_COOLDOWN_MINUTES: Final = 30
"""Cooldown after sending a critical notification (per growspace)."""

WARNING_COOLDOWN_MINUTES: Final = 120
"""Cooldown after sending a warning notification (per growspace)."""

RECOVERY_COOLDOWN_MINUTES: Final = 10
PHOTOPERIOD_FLIP_COOLDOWN_MINUTES: Final = 23 * 60
"""Cooldown after sending a recovery notification (per growspace)."""

ESCALATION_DELAY_MINUTES: Final = 30
"""Minutes after critical notification before sending escalation reminder."""

AI_PERSONALITIES = [
    "Standard",
    "Scientific",
    "Chill Stoner",
    "Strict Coach",
    "Pirate",
]

# Notification events - configurable per growspace
DEFAULT_NOTIFICATION_EVENTS = {
    "day_21_veg": {
        "days": 21,
        "stage": "veg",
        "message": "Day 21 in veg - Get ready for last defoliation and last IPMD",
    },
    "day_21_flower": {
        "days": 21,
        "stage": "flower",
        "message": "Day 21 in flower - Time for lollipopping",
    },
    "day_56_flower": {
        "days": 56,
        "stage": "flower",
        "message": "Day 56 in flower - Harvest time approaching",
    },
    "day_7_dry": {"days": 7, "stage": "dry", "message": "Day 7 in dry"},
}


# Dehumidifier Stages (Unified)
DEHUMIDIFIER_STAGES: Final = [
    PlantStage.SEEDLING.value,
    PlantStage.VEG.value,
    PlantStage.FLOWER_EARLY.value,
    PlantStage.FLOWER_MID.value,
    PlantStage.FLOWER_LATE.value,
    PlantStage.DRY.value,
    PlantStage.CURE.value,
]


class NotificationTier(StrEnum):
    """Notification severity tiers."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"
    PHOTOPERIOD_FLIP = "photoperiod_flip"


class GrowspaceSensorType(StrEnum):
    """Types of growspace sensors."""

    STRESS = "stress"
    MOLD = "mold"
    OPTIMAL = "optimal"
    DRYING = "drying"
    CURING = "curing"
    DLI = "dli"
    CROP_STEERING = "crop_steering"
    ENERGY_USAGE = "energy_usage"
    WATER_USAGE = "water_usage"
    EC_TARGET = "ec_target"


class GrowspaceService(StrEnum):
    """Growspace Manager Services."""

    ADD_GROWSPACE = "add_growspace"
    REMOVE_GROWSPACE = "remove_growspace"
    UPDATE_GROWSPACE = "update_growspace"
    ADD_PLANT = "add_plant"
    ADD_PLANTS = "add_plants"
    REMOVE_PLANT = "remove_plant"
    UPDATE_PLANT = "update_plant"
    MOVE_PLANT = "move_plant"
    SWITCH_PLANTS = "switch_plants"
    TAKE_CLONE = "take_clone"
    MOVE_CLONE = "move_clone"
    TRANSITION_PLANT_STAGE = "transition_plant_stage"
    HARVEST_PLANT = "harvest_plant"
    UPDATE_HARVEST_METRICS = "update_harvest_metrics"
    SCORE_PLANT = "score_plant"
    ADD_STRAIN = "add_strain"
    REMOVE_STRAIN = "remove_strain"
    UPDATE_STRAIN_META = "update_strain_meta"
    IMPORT_STRAIN_LIBRARY = "import_strain_library"
    EXPORT_STRAIN_LIBRARY = "export_strain_library"
    EXPORT_GROW_REPORT = "export_grow_report"
    CLEAR_STRAIN_LIBRARY = "clear_strain_library"
    STRAIN_RECOMMENDATION = "strain_recommendation"
    ASK_GROW_ADVICE = "ask_grow_advice"
    ANALYZE_ALL_GROWSPACES = "analyze_all_growspaces"
    PRINT_LABEL = "print_label"
    CONFIGURE_ENVIRONMENT = "configure_environment"
    CONFIGURE_CIRCULATION_FAN = "configure_circulation_fan"
    REMOVE_ENVIRONMENT = "remove_environment"
    SET_DEHUMIDIFIER_CONTROL = "set_dehumidifier_control"
    SET_HUMIDIFIER_CONTROL = "set_humidifier_control"
    SET_IRRIGATION_SETTINGS = "set_irrigation_settings"
    SET_IRRIGATION_STRATEGY = "set_irrigation_strategy"
    ADD_IRRIGATION_TIME = "add_irrigation_time"
    REMOVE_IRRIGATION_TIME = "remove_irrigation_time"
    ADD_DRAIN_TIME = "add_drain_time"
    REMOVE_DRAIN_TIME = "remove_drain_time"
    RUN_IRRIGATION_CYCLE = "run_irrigation_cycle"
    DEBUG_LIST_GROWSPACES = "debug_list_growspaces"
    DEBUG_RESET_SPECIAL_GROWSPACES = "debug_reset_special_growspaces"
    DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL = "debug_consolidate_duplicate_special"

    TEST_NOTIFICATION = "test_notification"
    GET_STRAIN_LIBRARY = "get_strain_library"
    # Watering Services
    WATER_PLANT = "water_plant"
    WATER_GROWSPACE = "water_growspace"
    # Nutrient Preset Services
    SAVE_NUTRIENT_PRESET = "save_nutrient_preset"
    REMOVE_NUTRIENT_PRESET = "remove_nutrient_preset"
    # Training Services
    LOG_TRAINING_EVENT = "log_training_event"
    # IPM Services
    SAVE_IPM_PRESET = "save_ipm_preset"
    REMOVE_IPM_PRESET = "remove_ipm_preset"
    APPLY_IPM = "apply_ipm"
    BATCH_ACTION = "batch_action"
    ADD_TIMELINE_NOTE = "add_timeline_note"
    # Drain EC Services
    LOG_DRAIN_READING = "log_drain_reading"
    CONFIGURE_DRAIN_MONITORING = "configure_drain_monitoring"
    # Water Tracking Services
    RESET_WATER_TRACKING = "reset_water_tracking"
    RESET_PLANT_LAST_WATERED = "reset_plant_last_watered"
    # EC Ramp Curve Services
    SAVE_EC_RAMP_CURVE = "save_ec_ramp_curve"
    REMOVE_EC_RAMP_CURVE = "remove_ec_ramp_curve"
    # EC Target Range Services
    SET_EC_TARGET_RANGE = "set_ec_target_range"
    # Vision Checkup Services
    TRIGGER_VISION_CHECKUP = "trigger_vision_checkup"
    # Tank Configuration Services
    CONFIGURE_TANK = "configure_tank"
    # Drying & Curing Services
    LOG_DRYING_WEIGHT = "log_drying_weight"
    LOG_MOISTURE_READING = "log_moisture_reading"
    SET_VISUAL_TAG = "set_visual_tag"
    # Genetics Services
    ADD_SEED_BATCH = "add_seed_batch"
    UPDATE_SEED_BATCH = "update_seed_batch"
    LOG_POLLINATION = "log_pollination"
    SCORE_PHENOTYPE = "score_phenotype"
    HARVEST_SEEDS = "harvest_seeds"
    UPDATE_POLLINATION = "update_pollination"
    DELETE_POLLINATION = "delete_pollination"
    SOW_SEED = "sow_seed"
    SET_PLANT_SEX = "set_plant_sex"
    UNLINK_SEED_BATCH = "unlink_seed_batch"


class FanRegulationMode(StrEnum):
    """Regulation variable for the circulation fan controller."""

    HUMIDITY = "humidity"
    TEMPERATURE = "temperature"
    VPD = "vpd"


class TrainingTechnique(StrEnum):
    """Horticultural training techniques."""

    TOPPING = "topping"
    FIM = "fim"
    LST = "lst"
    SUPER_CROPPING = "super_cropping"
    SCROG = "scrog"
    DEFOLIATING = "defoliating"
    LOLLIPOPPING = "lollipopping"


# Training Attributes
ATTR_TECHNIQUE = "technique"
ATTR_NOTES = "notes"
ATTR_ITEMS = "items"
ATTR_TYPE = "type"

# Genetics Attributes
ATTR_STRAIN_NAME = "strain_name"
ATTR_BREEDER = "breeder"
ATTR_QUANTITY = "quantity"
ATTR_ACQUISITION_DATE = "acquisition_date"
ATTR_HEIGHT = "height"
ATTR_AWARDS = "awards"
ATTR_LINEAGE_TREE = "lineage_tree"
ATTR_GENERATION = "generation"
ATTR_LINEAGE = "lineage"
ATTR_PARENT_1_STRAIN = "parent_1_strain"
ATTR_PARENT_1_PHENOTYPE = "parent_1_phenotype"
ATTR_PARENT_2_STRAIN = "parent_2_strain"
ATTR_PARENT_2_PHENOTYPE = "parent_2_phenotype"
ATTR_DONOR_PLANT_ID = "donor_plant_id"
ATTR_RECEIVER_PLANT_ID = "receiver_plant_id"
ATTR_EVENT_ID = "event_id"
ATTR_DATE = "date"
ATTR_SEX = "sex"
# PhenotypeScore rubric fields (1-10 scale)
ATTR_INTERNODAL_SPACING = "internodal_spacing"
ATTR_TERPENE_INTENSITY = "terpene_intensity"
ATTR_MOLD_RESISTANCE = "mold_resistance"
ATTR_YIELD_POTENTIAL = "yield_potential"
ATTR_KEEPER = "keeper"
CATEGORY_TRAINING = "training"
CATEGORY_IPM = "ipm"
CATEGORY_NOTE = "note"
CATEGORY_WATERING = "watering"
CATEGORY_DEHUMIDIFIER = "dehumidifier"
CATEGORY_HUMIDIFIER = "humidifier"
CATEGORY_MILESTONE = "milestone"
CATEGORY_ALERT = "alert"
CATEGORY_IRRIGATION_ERROR = "irrigation_error"


# Plant stages
VALID_STAGES = [stage.value for stage in PlantStage]

# Existing DATE_FIELDS - Ensure consistency with schema definitions if adding more
DATE_FIELDS = [
    "seedling_start",
    "veg_start",
    "flower_start",
    "dry_start",
    "cure_start",
    "mother_start",
    "clone_start",
    "transition_date",  # Also include transition_date as it's used in some services
]

SPECIAL_GROWSPACES = {
    "dry": {
        "canonical_id": "dry",
        "canonical_name": "dry",
        "aliases": ["dry_overview", "drying"],
    },
    "cure": {
        "canonical_id": "cure",
        "canonical_name": "cure",
        "aliases": ["cure_overview"],
    },
    "mother": {
        "canonical_id": "mother",
        "canonical_name": "mother",
        "aliases": ["mother_overview"],
    },
    "clone": {
        "canonical_id": "clone",
        "canonical_name": "clone",
        "aliases": ["clone_overview"],
    },
    "veg": {"canonical_id": "veg", "canonical_name": "veg", "aliases": []},
}
# Grid layout options
DEFAULT_ROWS = 4
DEFAULT_PLANTS_PER_ROW = 4
MAX_ROWS = 20
MAX_PLANTS_PER_ROW = 20

# Strain Library defaults
DB_FILE_STRAIN_LIBRARY = "strain_library.db"
STORAGE_KEY_STRAIN_LIBRARY = "strain_library"
CONF_STRAIN_LIBRARY: Final = "strain_library"
CONF_UNIT_SYSTEM: Final = "unit_system"
CONF_SHOW_SIDEBAR: Final = "show_sidebar"

# State Constants
DEFAULT_BAYESIAN_PRIORS = {
    "stress": 0.15,
    "mold_risk": 0.10,
    "optimal": 0.40,
    "drying": 0.50,
    "curing": 0.50,
}

DEFAULT_BAYESIAN_THRESHOLDS = {
    "stress": 0.80,
    "mold_risk": 0.80,
    "optimal": 0.90,
    "drying": 0.80,
    "curing": 0.80,
}

# Notification constants
MAX_NOTIFICATION_LENGTH: Final = 240
"""Maximum notification message length for modern mobile displays."""

NOTIFICATION_DEBOUNCE_SECONDS: Final = 5
"""Debounce time for batched notifications in seconds."""

MIN_STRESS_DURATION_SECONDS: Final = 180
"""Minimum seconds a stress event must persist before any notification is sent."""

SENSOR_SETTLING_DELAY_CAP_SECONDS: Final = 15
"""Upper bound on how long to wait for a moisture sensor to settle after a cycle."""

NOTIFICATION_GROUP: Final = "growspace-manager"
"""Notification group/thread identifier for grouping on Android and iOS."""

NOTIFICATION_CHANNEL: Final = "Growspace Manager"
"""Android notification channel name."""

NOTIFICATION_ICON: Final = "mdi:sprout"
"""Default Android status bar icon for growspace notifications."""

# WebSocket constants
MERGE_ALERT_GAP_SECONDS: Final = 600
"""Maximum time gap (in seconds) between alerts for merging (10 minutes)."""


# --- Service Schemas (Moved to schemas.py) ---
