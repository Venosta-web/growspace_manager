"""Constants for the Growspace Manager integration."""

from enum import StrEnum

DOMAIN = "growspace_manager"
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_storage"
PLATFORMS: list[str] = [
    "binary_sensor",
    "sensor",
    "switch",
]

PARALLEL_UPDATES = 0

# Dehumidifier Control Timing Defaults
DEFAULT_DEHUMIDIFIER_MIN_RUNTIME = 300  # 5 minutes in seconds
DEFAULT_DEHUMIDIFIER_MIN_OFFTIME = 300  # 5 minutes in seconds
DEFAULT_VPD_HYSTERESIS = 0.2  # kPa (fallback if not using stage thresholds)

DEFAULT_NAME = "Growspace Manager"

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
CONF_HUMIDIFIER_ENTITY = "humidifier_entity"
CONF_SOIL_MOISTURE_SENSOR = "soil_moisture_sensor"
CONF_CONTROL_DEHUMIDIFIER = "control_dehumidifier"

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
ATTR_STRAIN = "strain"
ATTR_PHENOTYPE = "phenotype"
ATTR_ROW = "row"
ATTR_COL = "col"
ATTR_STAGE = "stage"
ATTR_TRANSITION_DATE = "transition_date"
ATTR_MOTHER_PLANT_ID = "mother_plant_id"
ATTR_TARGET_GROWSPACE_ID = "target_growspace_id"
ATTR_NUM_CLONES = "num_clones"

ATTR_TOTAL_DAYS = "total_days"

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

# Events
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


class PlantStage(StrEnum):
    SEEDLING = "seedling"
    CLONE = "clone"
    MOTHER = "mother"
    VEG = "veg"
    FLOWER = "flower"
    DRY = "dry"
    CURE = "cure"


class GrowspaceSensorType(StrEnum):
    STRESS = "stress"
    MOLD = "mold"
    OPTIMAL = "optimal"
    DRYING = "drying"
    CURING = "curing"


class GrowspaceService(StrEnum):
    """Growspace Manager Services."""

    ADD_GROWSPACE = "add_growspace"
    REMOVE_GROWSPACE = "remove_growspace"
    UPDATE_GROWSPACE = "update_growspace"
    ADD_PLANT = "add_plant"
    REMOVE_PLANT = "remove_plant"
    UPDATE_PLANT = "update_plant"
    MOVE_PLANT = "move_plant"
    SWITCH_PLANTS = "switch_plants"
    TAKE_CLONE = "take_clone"
    MOVE_CLONE = "move_clone"
    TRANSITION_PLANT_STAGE = "transition_plant_stage"
    HARVEST_PLANT = "harvest_plant"
    ADD_STRAIN = "add_strain"
    REMOVE_STRAIN = "remove_strain"
    UPDATE_STRAIN_META = "update_strain_meta"
    IMPORT_STRAIN_LIBRARY = "import_strain_library"
    EXPORT_STRAIN_LIBRARY = "export_strain_library"
    CLEAR_STRAIN_LIBRARY = "clear_strain_library"
    STRAIN_RECOMMENDATION = "strain_recommendation"
    ASK_GROW_ADVICE = "ask_grow_advice"
    ANALYZE_ALL_GROWSPACES = "analyze_all_growspaces"
    CONFIGURE_ENVIRONMENT = "configure_environment"
    REMOVE_ENVIRONMENT = "remove_environment"
    SET_DEHUMIDIFIER_CONTROL = "set_dehumidifier_control"
    SET_IRRIGATION_SETTINGS = "set_irrigation_settings"
    ADD_IRRIGATION_TIME = "add_irrigation_time"
    REMOVE_IRRIGATION_TIME = "remove_irrigation_time"
    ADD_DRAIN_TIME = "add_drain_time"
    REMOVE_DRAIN_TIME = "remove_drain_time"
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
CATEGORY_TRAINING = "training"
CATEGORY_IPM = "ipm"


# Plant stages
PLANT_STAGES = [stage.value for stage in PlantStage]
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
MAX_ROWS = 20
MAX_PLANTS_PER_ROW = 20

# Strain Library defaults
DB_FILE_STRAIN_LIBRARY = "strain_library.db"
STORAGE_KEY_STRAIN_LIBRARY = "strain_library"

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


# --- Service Schemas (Moved to schemas.py) ---
