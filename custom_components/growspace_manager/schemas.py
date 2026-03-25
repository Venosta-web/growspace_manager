"""Validation schemas for the Growspace Manager integration."""

from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ACQUISITION_DATE,
    ATTR_AMOUNT_ML,
    ATTR_AROMA,
    ATTR_BREEDER,
    ATTR_CBD_PERCENTAGE,
    ATTR_COL,
    ATTR_CURVE_ID,
    ATTR_DATE,
    ATTR_DONOR_PLANT_ID,
    ATTR_DRAIN_EC,
    ATTR_DRAIN_VOLUME_ML,
    ATTR_DRY_WEIGHT,
    ATTR_EC,
    ATTR_EVENT_ID,
    ATTR_FEED_EC,
    ATTR_FEED_VOLUME_ML,
    ATTR_GENERATION,
    ATTR_GROWSPACE_ID,
    ATTR_IMAGES,
    ATTR_INTERNODAL_SPACING,
    ATTR_ITEMS,
    ATTR_KEEPER,
    ATTR_LINEAGE,
    ATTR_MAX_EC_DELTA,
    ATTR_METADATA,
    ATTR_MIN_DAYS_IN_STAGE,
    ATTR_MOLD_RESISTANCE,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_PEST_RESISTANCE,
    ATTR_PH,
    ATTR_PHENOTYPE,
    ATTR_PLANT_ID,
    ATTR_POINTS,
    ATTR_PRESET_ID,
    ATTR_QUANTITY,
    ATTR_RECEIVER_PLANT_ID,
    ATTR_RESIN,
    ATTR_ROW,
    ATTR_STAGE,
    ATTR_STRAIN,
    ATTR_STRAIN_NAME,
    ATTR_STRUCTURE,
    ATTR_TAGS,
    ATTR_TANK_ENTITY,
    ATTR_TARGET_RUNOFF_PERCENT,
    ATTR_TECHNIQUE,
    ATTR_TERPENE_INTENSITY,
    ATTR_TERPENE_PROFILE,
    ATTR_THC_PERCENTAGE,
    ATTR_TRANSITION_DATE,
    ATTR_TRIM_WEIGHT,
    ATTR_TYPE,
    ATTR_VIGOR,
    ATTR_VOLUME_LITERS,
    ATTR_WET_WEIGHT,
    ATTR_YIELD_POTENTIAL,
    CONF_CAMERA_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_CONTROL_DEHUMIDIFIER,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_ELECTRICITY_COST,
    CONF_ENERGY_SENSORS,
    CONF_EXHAUST_ENTITY,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDITY_SENSOR,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_MOLD_THRESHOLD,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_STRESS_THRESHOLD,
    CONF_SUBSTRATE_TEMP_SENSORS,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    DATE_FIELDS,
    PLANT_STAGES,
)
from .validation import valid_date_or_none, valid_growspace_id

# Shared Schema Dictionaries
_PLANT_DATE_FIELDS: dict[Any, Any] = {
    vol.Optional(field): valid_date_or_none for field in DATE_FIELDS
}

_PLANT_DAYS_FIELDS: dict[Any, Any] = {
    vol.Optional(f"{stage}_days"): vol.All(vol.Coerce(int)) for stage in PLANT_STAGES
}


# Add Growspace
ADD_GROWSPACE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("rows"): vol.All(int, vol.Range(min=1)),
        vol.Required("plants_per_row"): vol.All(int, vol.Range(min=1)),
        vol.Optional("notification_target"): str,
    }
)

# Remove Growspace
REMOVE_GROWSPACE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
    }
)

# Update Growspace
UPDATE_GROWSPACE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Optional("name"): str,
        vol.Optional("rows"): vol.All(int, vol.Range(min=1)),
        vol.Optional("plants_per_row"): vol.All(int, vol.Range(min=1)),
        vol.Optional("notification_target"): str,
    }
)

# Add Plant
ADD_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_STRAIN): str,
        vol.Required(ATTR_ROW): vol.All(int, vol.Range(min=1)),
        vol.Required(ATTR_COL): vol.All(int, vol.Range(min=1)),
        vol.Optional(ATTR_PHENOTYPE): str,
        **_PLANT_DATE_FIELDS,
    }
)

# Batch Add Plants
ADD_PLANTS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_STRAIN): str,
        vol.Required("amount"): vol.All(int, vol.Range(min=1)),
        vol.Optional("start_number", default=1): vol.All(int, vol.Range(min=1)),
        vol.Optional(ATTR_PHENOTYPE): str,
        **_PLANT_DATE_FIELDS,
    }
)

LOG_TRAINING_EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_TECHNIQUE): cv.string,
        vol.Optional(ATTR_GROWSPACE_ID): cv.string,
        vol.Optional(ATTR_PLANT_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_NOTES): cv.string,
    }
)

# Update Plant
UPDATE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_GROWSPACE_ID): str,
        vol.Optional(ATTR_STRAIN): str,
        vol.Optional(ATTR_PHENOTYPE): str,
        vol.Optional("position"): str,
        vol.Optional(ATTR_ROW): vol.All(int, vol.Range(min=1)),
        vol.Optional(ATTR_COL): vol.All(int, vol.Range(min=1)),
        vol.Optional(ATTR_STAGE): str,  # Assuming stage can be updated
        **_PLANT_DATE_FIELDS,
        **_PLANT_DAYS_FIELDS,
    },
    extra=vol.ALLOW_EXTRA,
)


# Remove Plant
REMOVE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
    }
)

# Move Plant
MOVE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required("new_row"): vol.All(int, vol.Range(min=1)),
        vol.Required("new_col"): vol.All(int, vol.Range(min=1)),
    }
)

# Switch Plants
SWITCH_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant1_id"): str,
        vol.Required("plant2_id"): str,
    }
)

# Transition Plant Stage
TRANSITION_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required("new_stage"): str,
        vol.Optional(ATTR_TRANSITION_DATE): valid_date_or_none,
    }
)

# Take Clone
TAKE_CLONE_SCHEMA = vol.Schema(
    {
        vol.Required("mother_plant_id"): str,
        vol.Optional("num_clones"): vol.All(int, vol.Range(min=1)),
        vol.Optional(
            "target_growspace_id"
        ): str,  # If you want to specify where clones go
        vol.Optional(
            "transition_date"
        ): valid_date_or_none,  # Date for when clone starts
    }
)

# Move Clone (typically from clone stage to veg)
MOVE_CLONE_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): str,  # The ID of the clone to move
        vol.Required(
            "target_growspace_id"
        ): str,  # Where to move it (e.g., 'veg_stage_growspace')
        vol.Optional(
            "transition_date"
        ): valid_date_or_none,  # Date to transition to next stage (e.g., veg_start)
    }
)

# Harvest Plant
HARVEST_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): str,
        vol.Optional(
            "target_growspace_id"
        ): str,  # Optional: where to move harvested material (e.g., 'dry_stage_growspace')
        vol.Optional("transition_date"): valid_date_or_none,  # Date of harvest
        # Yield metrics
        vol.Optional(ATTR_WET_WEIGHT): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_DRY_WEIGHT): vol.All(vol.Coerce(float), vol.Range(min=0)),
        vol.Optional(ATTR_TRIM_WEIGHT): vol.All(vol.Coerce(float), vol.Range(min=0)),
        # Lab results
        vol.Optional(ATTR_THC_PERCENTAGE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Optional(ATTR_CBD_PERCENTAGE): vol.All(
            vol.Coerce(float), vol.Range(min=0, max=100)
        ),
        vol.Optional(ATTR_TERPENE_PROFILE): str,
    }
)

# Update Harvest Metrics
UPDATE_HARVEST_METRICS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_WET_WEIGHT): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0))
        ),
        vol.Optional(ATTR_DRY_WEIGHT): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0))
        ),
        vol.Optional(ATTR_TRIM_WEIGHT): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0))
        ),
        vol.Optional(ATTR_THC_PERCENTAGE): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
        ),
        vol.Optional(ATTR_CBD_PERCENTAGE): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0, max=100))
        ),
        vol.Optional(ATTR_TERPENE_PROFILE): vol.Any(None, str),
    }
)

# Score Plant
_SCORE_VALIDATOR = vol.Any(None, vol.All(vol.Coerce(int), vol.Range(min=1, max=5)))
SCORE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_VIGOR): _SCORE_VALIDATOR,
        vol.Optional(ATTR_STRUCTURE): _SCORE_VALIDATOR,
        vol.Optional(ATTR_AROMA): _SCORE_VALIDATOR,
        vol.Optional(ATTR_RESIN): _SCORE_VALIDATOR,
        vol.Optional(ATTR_PEST_RESISTANCE): _SCORE_VALIDATOR,
    }
)

# Strain Library Schemas
EXPORT_STRAIN_LIBRARY_SCHEMA = vol.Schema(
    {
        # No required parameters for export, usually just triggers action
        # Optionally, could specify which strains to export, but current logic exports all
    }
)

EXPORT_GROW_REPORT_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_GROWSPACE_ID): str,
        vol.Optional("format", default="pdf"): vol.In(["pdf", "json"]),
    }
)

IMPORT_STRAIN_LIBRARY_SCHEMA = vol.Schema(
    {
        vol.Optional("file_path"): str,
        vol.Optional("zip_base64"): str,
        vol.Optional("replace", default=False): bool,
    }
)

CLEAR_STRAIN_LIBRARY_SCHEMA = vol.Schema(
    {
        # No parameters needed to clear all strains
    }
)

# Shared Strain Fields
STRAIN_BASE_FIELDS: dict[Any, Any] = {
    vol.Optional("phenotype"): str,
    vol.Optional("breeder"): str,
    vol.Optional("breeder_logo"): str,
    vol.Optional("type"): str,
    vol.Optional("lineage"): str,
    vol.Optional("sex"): str,
    vol.Optional("flower_days_min"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("flower_days_max"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("flowering_days_min"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("flowering_days_max"): vol.All(vol.Coerce(int), vol.Range(min=0)),
    vol.Optional("description"): str,
    vol.Optional("image_base64"): str,
    vol.Optional("image"): str,
    vol.Optional("image_path"): str,
    vol.Optional("image_crop_meta"): dict,
    vol.Optional("sativa_percentage"): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=100)
    ),
    vol.Optional("indica_percentage"): vol.All(
        vol.Coerce(int), vol.Range(min=0, max=100)
    ),
}

ADD_STRAIN_SCHEMA = vol.Schema(
    {
        vol.Required("strain"): str,
        **STRAIN_BASE_FIELDS,
    }
)

REMOVE_STRAIN_SCHEMA = vol.Schema(
    {
        vol.Required("strain"): str,
        vol.Optional("phenotype"): str,
    }
)

UPDATE_STRAIN_META_SCHEMA = vol.Schema(
    {
        vol.Required("strain"): str,
        **STRAIN_BASE_FIELDS,
    }
)

# Print Label
PRINT_LABEL_SCHEMA = vol.Schema(
    {
        vol.Optional(ATTR_PLANT_ID): str,
        vol.Optional(ATTR_STRAIN): str,
        vol.Optional(ATTR_PHENOTYPE): str,
        vol.Optional("breeder"): str,
        vol.Optional("lineage"): str,
        vol.Optional("breeder_logo"): str,
        vol.Optional("device_id"): str,
        vol.Optional("preview", default=False): bool,
        vol.Optional("base_url"): str,
    }
)

# Debug Schemas
DEBUG_CLEANUP_LEGACY_SCHEMA = vol.Schema(
    {
        vol.Optional("dry_only", default=False): bool,
        vol.Optional("cure_only", default=False): bool,
    }
)

DEBUG_LIST_GROWSPACES_SCHEMA = vol.Schema({})  # No parameters

DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA = vol.Schema(
    {
        vol.Optional("reset_dry", default=True): bool,
        vol.Optional("reset_cure", default=True): bool,
        vol.Optional("preserve_plants", default=True): bool,
    }
)

DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA = vol.Schema({})  # No parameters

CONFIGURE_ENVIRONMENT_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): str,
        vol.Required(CONF_TEMP_SENSOR): str,
        vol.Required(CONF_HUMIDITY_SENSOR): str,
        vol.Optional(CONF_VPD_SENSOR): str,
        vol.Optional(CONF_CO2_SENSOR): str,
        vol.Optional(CONF_DEHUMIDIFIER_ENTITY): str,
        vol.Optional(CONF_CIRCULATION_FAN_ENTITY): str,
        vol.Optional(CONF_LIGHT_SENSOR): str,
        vol.Optional(CONF_EXHAUST_ENTITY): str,
        vol.Optional(CONF_HUMIDIFIER_ENTITY): str,
        vol.Optional(CONF_SOIL_MOISTURE_SENSOR): str,
        vol.Optional(CONF_CONTROL_DEHUMIDIFIER, default=False): bool,
        vol.Optional(CONF_DEHUMIDIFIER_THRESHOLDS): dict,
        vol.Optional(CONF_STRESS_THRESHOLD, default=0.70): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Optional(CONF_MOLD_THRESHOLD, default=0.75): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        # Multi-device support
        vol.Optional(CONF_LIGHT_SENSORS): cv.ensure_list,
        vol.Optional(CONF_DEHUMIDIFIER_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_CIRCULATION_FAN_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_HUMIDIFIER_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_EXHAUST_FAN_ENTITIES): cv.ensure_list,
        vol.Optional("sensor_groups"): list,
        vol.Optional("sensor_coordinates"): dict,
        vol.Optional("irrigation_tanks"): list,
        vol.Optional(CONF_SUBSTRATE_TEMP_SENSORS): cv.ensure_list,
        vol.Optional(CONF_CAMERA_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_ENERGY_SENSORS): cv.ensure_list,
        vol.Optional(CONF_ELECTRICITY_COST): vol.Coerce(float),
    }
)

REMOVE_ENVIRONMENT_SCHEMA = vol.Schema(
    {
        # Erfordert nur die ID des Growspace, um die Konfiguration zu entfernen.
        vol.Required("growspace_id"): str
    }
)

# AI Service Schemas
ASK_GROW_ADVICE_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Optional("user_query"): str,
        vol.Optional("context_type", default="general"): vol.In(
            ["general", "diagnostic", "optimization", "planning"]
        ),
        vol.Optional("max_length"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

ANALYZE_ALL_GROWSPACES_SCHEMA = vol.Schema(
    {
        vol.Optional("max_length"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

STRAIN_RECOMMENDATION_SCHEMA = vol.Schema(
    {
        vol.Optional("preferences"): dict,
        vol.Optional("growspace_id"): str,
        vol.Optional("user_query"): str,
        vol.Optional("max_length"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

# --- Irrigation Service Schemas ---

SET_IRRIGATION_SETTINGS_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Optional("irrigation_pump_entity"): str,
        vol.Optional("drain_pump_entity"): str,
        vol.Optional("irrigation_duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional("drain_duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

_ADD_SCHEDULE_TIME_BASE = {
    vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
    vol.Required("time"): str,  # Use string for HH:MM:SS format
    vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
}

ADD_IRRIGATION_TIME_SCHEMA = vol.Schema(_ADD_SCHEDULE_TIME_BASE)
ADD_DRAIN_TIME_SCHEMA = vol.Schema(_ADD_SCHEDULE_TIME_BASE)

REMOVE_TIME_BASE = {
    vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
    vol.Required("time"): str,
}

REMOVE_IRRIGATION_TIME_SCHEMA = vol.Schema(REMOVE_TIME_BASE)
REMOVE_DRAIN_TIME_SCHEMA = vol.Schema(REMOVE_TIME_BASE)

SET_DEHUMIDIFIER_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Required("enabled"): bool,
    }
)

# --- Manual Watering Service Schemas ---

WATER_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
        vol.Required("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional("nutrients"): vol.Schema({str: vol.Coerce(float)}),
        vol.Optional(ATTR_PRESET_ID): str,
    }
)

WATER_GROWSPACE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Optional("amount_per_plant"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional("amount"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional("nutrients"): vol.Schema({str: vol.Coerce(float)}),
        vol.Optional(ATTR_PRESET_ID): str,
    }
)

# --- Nutrient Preset Schemas ---

NUTRIENT_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required("name"): str,
        vol.Required("dose_ml_l"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    }
)

SAVE_NUTRIENT_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): str,
        vol.Required("nutrients"): vol.All([NUTRIENT_ITEM_SCHEMA], vol.Length(min=1)),
        vol.Optional(ATTR_PRESET_ID): str,
        vol.Optional(ATTR_STAGE): vol.Any(vol.In(PLANT_STAGES), None),
        vol.Optional(ATTR_MIN_DAYS_IN_STAGE): vol.All(int, vol.Range(min=0)),
    }
)

REMOVE_NUTRIENT_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRESET_ID): str,
    }
)

# --- IPM Preset Schemas ---

IPM_ITEM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): str,
        vol.Required("dose_amount"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Required("dose_unit"): str,
        vol.Optional("phi_days", default=0): vol.All(vol.Coerce(int), vol.Range(min=0)),
    }
)

SAVE_IPM_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): str,
        vol.Required(ATTR_TYPE): str,
        vol.Required(ATTR_ITEMS): vol.All([IPM_ITEM_SCHEMA], vol.Length(min=1)),
        vol.Optional(ATTR_PRESET_ID): str,
        vol.Optional(ATTR_STAGE): vol.Any(vol.In(PLANT_STAGES), None),
        vol.Optional(ATTR_MIN_DAYS_IN_STAGE): vol.All(int, vol.Range(min=0)),
    }
)

REMOVE_IPM_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRESET_ID): str,
    }
)

APPLY_IPM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRESET_ID): str,
        vol.Optional(ATTR_GROWSPACE_ID): str,
        vol.Optional(ATTR_PLANT_ID): vol.All(cv.ensure_list, [str]),
        vol.Optional(ATTR_NOTES): str,
    }
)


BATCH_ACTION_SCHEMA = vol.Schema(
    {
        vol.Required("entity_ids"): cv.ensure_list,
        vol.Required("action"): cv.string,
        vol.Optional("data"): dict,
    }
)

ADD_TIMELINE_NOTE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): vol.Any(str, cv.ensure_list),
        vol.Required(ATTR_NOTES): str,
        vol.Optional(ATTR_TRANSITION_DATE): cv.string,
        vol.Optional(ATTR_IMAGES): cv.ensure_list,
        vol.Optional(ATTR_TAGS): cv.ensure_list,
        vol.Optional(ATTR_PH): vol.Coerce(float),
        vol.Optional(ATTR_EC): vol.Coerce(float),
        vol.Optional(ATTR_AMOUNT_ML): vol.Coerce(float),
        vol.Optional(ATTR_METADATA): dict,
    }
)

# --- Drain EC Monitoring Schemas ---

LOG_DRAIN_READING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_FEED_EC): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Required(ATTR_DRAIN_EC): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(ATTR_DRAIN_VOLUME_ML): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional(ATTR_FEED_VOLUME_ML): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
    }
)

CONFIGURE_DRAIN_MONITORING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Optional("enabled"): bool,
        vol.Optional(ATTR_MAX_EC_DELTA): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(ATTR_TARGET_RUNOFF_PERCENT): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
    }
)

# --- Tank Configuration Schemas ---

CONFIGURE_TANK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_TANK_ENTITY): cv.string,
        vol.Optional(ATTR_VOLUME_LITERS): vol.All(
            vol.Coerce(float), vol.Range(min=0.1)
        ),
    }
)

# --- Water Tracking Schemas ---

RESET_WATER_TRACKING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
    }
)

# --- EC Ramp Curve Schemas ---

EC_RAMP_POINT_SCHEMA = vol.Schema(
    {
        vol.Required("week"): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required("ec_min"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Required("ec_max"): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    }
)

SAVE_EC_RAMP_CURVE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): str,
        vol.Required(ATTR_STAGE): str,
        vol.Required(ATTR_POINTS): vol.All([EC_RAMP_POINT_SCHEMA], vol.Length(min=1)),
        vol.Optional(ATTR_CURVE_ID): str,
    }
)

REMOVE_EC_RAMP_CURVE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CURVE_ID): str,
    }
)

# --- Vision Checkup Schemas ---

SERVICE_TRIGGER_VISION_CHECKUP_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): cv.string,
    }
)

# --- Genetics Schemas ---

_PHENO_SCORE_VALIDATOR = vol.Any(
    None, vol.All(vol.Coerce(int), vol.Range(min=1, max=10))
)

ADD_SEED_BATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_STRAIN_NAME): cv.string,
        vol.Required(ATTR_BREEDER): cv.string,
        vol.Required(ATTR_QUANTITY): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Required(ATTR_ACQUISITION_DATE): cv.string,
        vol.Required(ATTR_GENERATION): cv.string,
        vol.Required(ATTR_LINEAGE): cv.string,
        vol.Optional(ATTR_NOTES, default=""): cv.string,
    }
)

LOG_POLLINATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DATE): cv.string,
        vol.Required(ATTR_DONOR_PLANT_ID): cv.string,
        vol.Required(ATTR_RECEIVER_PLANT_ID): cv.string,
        vol.Optional(ATTR_NOTES, default=""): cv.string,
    }
)

SCORE_PHENOTYPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Optional(ATTR_VIGOR): _PHENO_SCORE_VALIDATOR,
        vol.Optional(ATTR_INTERNODAL_SPACING): _PHENO_SCORE_VALIDATOR,
        vol.Optional(ATTR_TERPENE_INTENSITY): _PHENO_SCORE_VALIDATOR,
        vol.Optional(ATTR_RESIN): _PHENO_SCORE_VALIDATOR,
        vol.Optional(ATTR_MOLD_RESISTANCE): _PHENO_SCORE_VALIDATOR,
        vol.Optional(ATTR_YIELD_POTENTIAL): _PHENO_SCORE_VALIDATOR,
        vol.Optional(ATTR_KEEPER): cv.boolean,
        vol.Optional(ATTR_NOTES): vol.Any(None, cv.string),
    }
)

HARVEST_SEEDS_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_ID): cv.string,
        vol.Required(ATTR_QUANTITY): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_NOTES, default=""): cv.string,
    }
)
