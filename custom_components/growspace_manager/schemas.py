"""Validation schemas for the Growspace Manager integration."""

from typing import Any

import voluptuous as vol

from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_ACQUISITION_DATE,
    ATTR_AMOUNT_ML,
    ATTR_BATCH_ID,
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
    ATTR_FEED_EC_MAX,
    ATTR_FEED_EC_MIN,
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
    ATTR_MOISTURE_PERCENT,
    ATTR_MOLD_RESISTANCE,
    ATTR_NAME,
    ATTR_NOTES,
    ATTR_PARENT_1_PHENOTYPE,
    ATTR_PARENT_1_STRAIN,
    ATTR_PARENT_2_PHENOTYPE,
    ATTR_PARENT_2_STRAIN,
    ATTR_PH,
    ATTR_PHENOTYPE,
    ATTR_PLANT_ID,
    ATTR_PLANT_IDS,
    ATTR_POINTS,
    ATTR_PRESET_ID,
    ATTR_PROGRAM_ID,
    ATTR_PROGRAM_SLOTS,
    ATTR_QUANTITY,
    ATTR_RECEIVER_PLANT_ID,
    ATTR_RECIPE_CROP_STEERING,
    ATTR_RECIPE_ID,
    ATTR_RECIPE_KIND,
    ATTR_RECIPE_SCHEDULE,
    ATTR_RESIN,
    ATTR_ROW,
    ATTR_SEED_BATCH_ID,
    ATTR_SEX,
    ATTR_STAGE,
    ATTR_STEERING_MODE,
    ATTR_STRAIN,
    ATTR_STRAIN_NAME,
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
    ATTR_VISUAL_TAG,
    ATTR_VOLUME_LITERS,
    ATTR_WEIGHT_GRAMS,
    ATTR_WET_WEIGHT,
    ATTR_YIELD_POTENTIAL,
    CONF_BULK_EC_SENSORS,
    CONF_CAMERA_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITIES,
    CONF_CIRCULATION_FAN_ENTITY,
    CONF_CO2_SENSOR,
    CONF_CONTROL_DEHUMIDIFIER,
    CONF_CONTROL_HUMIDIFIER,
    CONF_DEHUMIDIFIER_ENTITIES,
    CONF_DEHUMIDIFIER_ENTITY,
    CONF_DEHUMIDIFIER_THRESHOLDS,
    CONF_DRAIN_VOLUME_SENSORS,
    CONF_ELECTRICITY_COST,
    CONF_ENERGY_SENSORS,
    CONF_EXHAUST_ENTITY,
    CONF_EXHAUST_FAN_ENTITIES,
    CONF_FEED_EC_SENSORS,
    CONF_HUMIDIFIER_ENTITIES,
    CONF_HUMIDIFIER_ENTITY,
    CONF_HUMIDIFIER_THRESHOLDS,
    CONF_HUMIDITY_SENSOR,
    CONF_IRRIGATION_FLOW_SENSORS,
    CONF_LIGHT_SENSOR,
    CONF_LIGHT_SENSORS,
    CONF_LST_OFFSET,
    CONF_LUNG_ROOM_TEMP_SENSORS,
    CONF_MOLD_THRESHOLD,
    CONF_PH_SENSORS,
    CONF_PORE_EC_SENSORS,
    CONF_POWER_SENSORS,
    CONF_RUNOFF_EC_SENSORS,
    CONF_SNAPSHOT_INTERVAL,
    CONF_SOIL_MOISTURE_SENSOR,
    CONF_STRESS_THRESHOLD,
    CONF_SUBSTRATE_TEMP_SENSORS,
    CONF_TEMP_SENSOR,
    CONF_VPD_SENSOR,
    DATE_FIELDS,
    PLANT_STAGES,
    FanRegulationMode,
    IrrigationRecipeKind,
    ShotSizingMode,
    SteeringMode,
    SubstrateMediaType,
)
from .validation import valid_date_or_none, valid_growspace_id


def _validate_pump_entities(config: dict) -> dict:
    """Validate that irrigation and drain pumps are not the same entity."""
    irr = config.get("irrigation_pump_entity")
    drain = config.get("drain_pump_entity")
    if irr and drain and irr == drain:
        raise vol.Invalid("Irrigation and drain pump cannot be the same entity")
    return config


def _validate_genetic_percentages(config: dict) -> dict:
    """Validate that sativa and indica percentages sum to <= 100."""
    sativa = config.get("sativa_percentage")
    indica = config.get("indica_percentage")
    if sativa is not None and indica is not None:
        if sativa + indica > 100:
            raise vol.Invalid(
                f"Sativa ({sativa}%) and Indica ({indica}%) sum to {sativa + indica}%, which exceeds 100%"
            )
    return config


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
        vol.Optional(ATTR_SEED_BATCH_ID): cv.string,
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
        vol.Optional(ATTR_SEED_BATCH_ID): cv.string,
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
        vol.Optional(ATTR_INTERNODAL_SPACING): _SCORE_VALIDATOR,
        vol.Optional(ATTR_TERPENE_INTENSITY): _SCORE_VALIDATOR,
        vol.Optional(ATTR_RESIN): _SCORE_VALIDATOR,
        vol.Optional(ATTR_MOLD_RESISTANCE): _SCORE_VALIDATOR,
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
    vol.Optional("flower_days_min"): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=0))
    ),
    vol.Optional("flower_days_max"): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=0))
    ),
    vol.Optional("flowering_days_min"): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=0))
    ),
    vol.Optional("flowering_days_max"): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=0))
    ),
    vol.Optional("description"): str,
    vol.Optional("image_base64"): str,
    vol.Optional("image"): str,
    vol.Optional("image_path"): str,
    vol.Optional("image_crop_meta"): dict,
    vol.Optional("sativa_percentage"): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
    ),
    vol.Optional("indica_percentage"): vol.Any(
        None, vol.All(vol.Coerce(int), vol.Range(min=0, max=100))
    ),
    vol.Optional("yield_potential"): str,
    vol.Optional("height"): str,
    vol.Optional("thc"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("cbd"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("cbg"): vol.Any(None, vol.Coerce(float)),
    vol.Optional("awards"): [str],
    vol.Optional("lineage_tree"): dict,
    vol.Optional("images"): [dict],
}

ADD_STRAIN_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("strain"): str,
            **STRAIN_BASE_FIELDS,
        }
    ),
    _validate_genetic_percentages,
)

REMOVE_STRAIN_SCHEMA = vol.Schema(
    {
        vol.Required("strain"): str,
        vol.Optional("phenotype"): str,
    }
)

UPDATE_STRAIN_META_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("strain"): str,
            **STRAIN_BASE_FIELDS,
        }
    ),
    _validate_genetic_percentages,
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
        vol.Optional("fields"): dict,
        vol.Optional("density"): vol.In(["low", "normal", "high"]),
        vol.Optional("qr_target"): vol.In(["web", "deeplink"]),
        vol.Optional("label_size"): str,
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

# An AC Infinity actuator bundle: a mode `select` + speed `number` entity, plus
# the intensity used for the binary on path (ADR-0022).
AC_INFINITY_DEVICE_SCHEMA = vol.Schema(
    {
        vol.Required("mode_entity"): str,
        vol.Required("speed_entity"): str,
        vol.Optional("on_speed", default=10): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=10)
        ),
    }
)

# The grow-light AC Infinity bundle is a configurator (ADR-0024): a different
# entity set from the fan bundle above (mode select + on/off time + on_power +
# native sunrise switch/duration).
AC_INFINITY_GROWLIGHT_SCHEMA = vol.Schema(
    {
        vol.Required("mode_entity"): str,
        vol.Required("on_time_entity"): str,
        vol.Required("off_time_entity"): str,
        vol.Required("power_entity"): str,
        vol.Optional("sunrise_switch_entity", default=""): str,
        vol.Optional("sunrise_duration_entity", default=""): str,
    }
)

CONFIGURE_ENVIRONMENT_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): str,
        # Singular (legacy / backward compat)
        vol.Optional(CONF_TEMP_SENSOR): str,
        vol.Optional(CONF_HUMIDITY_SENSOR): str,
        vol.Optional(CONF_VPD_SENSOR): str,
        vol.Optional(CONF_CO2_SENSOR): str,
        vol.Optional(CONF_DEHUMIDIFIER_ENTITY): str,
        vol.Optional(CONF_CIRCULATION_FAN_ENTITY): str,
        vol.Optional(CONF_LIGHT_SENSOR): str,
        vol.Optional(CONF_EXHAUST_ENTITY): str,
        vol.Optional(CONF_HUMIDIFIER_ENTITY): str,
        vol.Optional(CONF_SOIL_MOISTURE_SENSOR): str,
        # No defaults on any optional key: the patch seam (ADR-0026) distinguishes
        # an omitted field from an explicit set, so a schema-injected default would
        # turn every sparse caller into a silent write.
        vol.Optional(CONF_CONTROL_DEHUMIDIFIER): bool,
        vol.Optional(CONF_DEHUMIDIFIER_THRESHOLDS): dict,
        vol.Optional(CONF_CONTROL_HUMIDIFIER): bool,
        vol.Optional(CONF_HUMIDIFIER_THRESHOLDS): dict,
        vol.Optional(CONF_STRESS_THRESHOLD): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Optional(CONF_MOLD_THRESHOLD): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        # Multi-device support — basic sensors
        vol.Optional("temperature_sensors"): cv.ensure_list,
        vol.Optional("humidity_sensors"): cv.ensure_list,
        vol.Optional("vpd_sensors"): cv.ensure_list,
        vol.Optional(CONF_LIGHT_SENSORS): cv.ensure_list,
        vol.Optional(CONF_DEHUMIDIFIER_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_CIRCULATION_FAN_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_HUMIDIFIER_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_EXHAUST_FAN_ENTITIES): cv.ensure_list,
        vol.Optional("sensor_groups"): list,
        vol.Optional("sensor_coordinates"): dict,
        vol.Optional("irrigation_tanks"): list,
        vol.Optional(CONF_SUBSTRATE_TEMP_SENSORS): cv.ensure_list,
        vol.Optional(CONF_LUNG_ROOM_TEMP_SENSORS): cv.ensure_list,
        vol.Optional(CONF_CAMERA_ENTITIES): cv.ensure_list,
        vol.Optional(CONF_SNAPSHOT_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=1, max=168)
        ),
        # Advanced / irrigation monitoring sensors
        vol.Optional(CONF_PH_SENSORS): cv.ensure_list,
        vol.Optional(CONF_FEED_EC_SENSORS): cv.ensure_list,
        vol.Optional(CONF_BULK_EC_SENSORS): cv.ensure_list,
        vol.Optional(CONF_PORE_EC_SENSORS): cv.ensure_list,
        vol.Optional(CONF_RUNOFF_EC_SENSORS): cv.ensure_list,
        vol.Optional(CONF_DRAIN_VOLUME_SENSORS): cv.ensure_list,
        vol.Optional(CONF_IRRIGATION_FLOW_SENSORS): cv.ensure_list,
        vol.Optional(CONF_POWER_SENSORS): cv.ensure_list,
        vol.Optional(CONF_ENERGY_SENSORS): cv.ensure_list,
        vol.Optional(CONF_ELECTRICITY_COST): vol.Coerce(float),
        # Acceptable Moisture Band. Both edges are nullable so the pair can be
        # cleared back to the inherited default; the atomic pair and the
        # 0 ≤ min < max ≤ 100 relation are enforced by the Environment Patch
        # builder, which sees both values at once.
        vol.Optional("soil_moisture_min"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0))
        ),
        vol.Optional("soil_moisture_max"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0))
        ),
        vol.Optional("circulation_fan_config"): dict,
        vol.Optional("vpd_optimal_overrides"): dict,
        # AC Infinity actuator bundles, parallel to the plain *_entities lists.
        vol.Optional("exhaust_fan_ac_infinity_devices"): [AC_INFINITY_DEVICE_SCHEMA],
        vol.Optional("circulation_fan_ac_infinity_devices"): [
            AC_INFINITY_DEVICE_SCHEMA
        ],
        vol.Optional("humidifier_ac_infinity_devices"): [AC_INFINITY_DEVICE_SCHEMA],
        vol.Optional("dehumidifier_ac_infinity_devices"): [AC_INFINITY_DEVICE_SCHEMA],
        vol.Optional("growlight_entities"): cv.ensure_list,
        vol.Optional("growlight_config"): dict,
        vol.Optional("growlight_ac_infinity_devices"): [AC_INFINITY_GROWLIGHT_SCHEMA],
        vol.Optional(CONF_LST_OFFSET): vol.All(
            vol.Coerce(float), vol.Range(min=-10.0, max=10.0)
        ),
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


SET_IRRIGATION_STRATEGY_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Optional("enabled"): bool,
        vol.Optional("lights_on_time"): str,
        vol.Optional("p0_duration_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("p2_stop_before_lights_off_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("target_vwc_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        vol.Optional("maintenance_dryback_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        vol.Optional("p1_shot_duration_seconds"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("p1_shot_interval_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("p2_shot_duration_seconds"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("p2_shot_interval_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        # Deprecated shared shot fields: still accepted, write both phases
        vol.Optional("shot_duration_seconds"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("shot_interval_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("auto_light_tracking"): bool,
        # Shot Sizing Mode + Substrate Profile (Volume Mode, ADR-0011).
        vol.Optional("shot_sizing_mode"): vol.In(
            [mode.value for mode in ShotSizingMode]
        ),
        vol.Optional("substrate_media_type"): vol.In(
            [media.value for media in SubstrateMediaType]
        ),
        vol.Optional("substrate_liters_per_pot"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional("p1_shot_volume_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        vol.Optional("p2_shot_volume_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        # Adaptive Shot Control (ADR-0014).
        vol.Optional("dynamic_shot_enabled"): bool,
        vol.Optional("dynamic_aggressiveness"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=5.0)
        ),
        vol.Optional("dynamic_recovery"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Optional("dynamic_shot_size_floor"): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=1.0)
        ),
        vol.Optional("dynamic_interval_ceiling"): vol.All(
            vol.Coerce(float), vol.Range(min=1.0, max=5.0)
        ),
        # Pore EC Target Band + EC Modulation. min/max are nullable to allow
        # clearing the band; both edges share the non-negative float coercion.
        vol.Optional("pore_ec_target_min"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0.0))
        ),
        vol.Optional("pore_ec_target_max"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=0.0))
        ),
        vol.Optional("ec_modulation_enabled"): bool,
    }
)


SET_IRRIGATION_SETTINGS_SCHEMA = vol.All(
    vol.Schema(
        {
            vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
            vol.Optional("irrigation_pump_entity"): str,
            vol.Optional("pump_flow_rate_ml_per_sec"): vol.All(
                vol.Coerce(float), vol.Range(min=0.0)
            ),
            # [[Dripper Throughput]]: the grower-facing spelling of the one
            # value above. Submitting the pair stores the derived ml/s; no
            # second field is persisted.
            vol.Optional("dripper_liters_per_hour"): vol.All(
                vol.Coerce(float), vol.Range(min=0.0)
            ),
            vol.Optional("emitter_count"): vol.All(vol.Coerce(int), vol.Range(min=0)),
            vol.Optional("drain_pump_entity"): str,
            vol.Optional("irrigation_duration"): vol.All(
                vol.Coerce(int), vol.Range(min=1)
            ),
            vol.Optional("drain_duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Optional("soil_trigger_percent"): vol.Any(
                None, vol.All(vol.Coerce(float), vol.Range(min=0.0, max=100.0))
            ),
            vol.Optional("daily_volume_cap_liters"): vol.Any(
                None, vol.All(vol.Coerce(float), vol.Range(min=0.0))
            ),
            vol.Optional("max_cycles_per_day"): vol.Any(
                None, vol.All(vol.Coerce(int), vol.Range(min=0))
            ),
            vol.Optional("skip_during_dark"): bool,
            vol.Optional("pause_on_low_tank"): bool,
            vol.Optional("log_to_logbook"): bool,
            vol.Optional("auto_advance_p1_to_p2"): bool,
            vol.Optional("auto_advance_p2_to_p3"): bool,
            vol.Optional("halt_on_runoff_ec_threshold"): vol.Any(
                None, vol.All(vol.Coerce(float), vol.Range(min=0.0))
            ),
        }
    ),
    _validate_pump_entities,
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

RUN_IRRIGATION_CYCLE_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Optional("duration"): vol.All(vol.Coerce(int), vol.Range(min=1)),
    }
)

SET_DEHUMIDIFIER_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Required("enabled"): bool,
    }
)

SET_HUMIDIFIER_CONTROL_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Required("enabled"): bool,
    }
)

CONFIGURE_CIRCULATION_FAN_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Required("enabled"): bool,
        vol.Required("regulation_mode"): vol.In([m.value for m in FanRegulationMode]),
        vol.Required("min_speed"): vol.All(vol.Coerce(int), vol.Range(min=0, max=99)),
        vol.Required("max_speed"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Required("vpd_target"): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=3.0)
        ),
        vol.Required("vpd_tolerance"): vol.All(
            vol.Coerce(float), vol.Range(min=0.01, max=1.0)
        ),
        vol.Required("humidity_target"): vol.All(
            vol.Coerce(float), vol.Range(min=20, max=90)
        ),
        vol.Required("humidity_tolerance"): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=20)
        ),
        vol.Required("temperature_target"): vol.All(
            vol.Coerce(float), vol.Range(min=15, max=35)
        ),
        vol.Required("temperature_tolerance"): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=10)
        ),
        vol.Optional("critical_temp_low"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=10, max=40))
        ),
        vol.Optional("critical_temp_high"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=10, max=50))
        ),
        vol.Required("critical_temp_hysteresis"): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=5.0)
        ),
        vol.Required("wind_enabled"): bool,
        vol.Required("wind_period_seconds"): vol.All(
            vol.Coerce(int), vol.Range(min=10, max=600)
        ),
        vol.Required("wind_amplitude_pct"): vol.All(
            vol.Coerce(int), vol.Range(min=5, max=50)
        ),
    }
)

CONFIGURE_EXHAUST_FAN_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Required("enabled"): bool,
        vol.Required("min_speed"): vol.All(vol.Coerce(int), vol.Range(min=0, max=99)),
        vol.Required("max_speed"): vol.All(vol.Coerce(int), vol.Range(min=1, max=100)),
        vol.Required("temperature_target"): vol.All(
            vol.Coerce(float), vol.Range(min=15, max=35)
        ),
        vol.Required("temperature_tolerance"): vol.All(
            vol.Coerce(float), vol.Range(min=0.5, max=10)
        ),
        vol.Required("humidity_target"): vol.All(
            vol.Coerce(float), vol.Range(min=20, max=90)
        ),
        vol.Required("humidity_tolerance"): vol.All(
            vol.Coerce(float), vol.Range(min=1, max=20)
        ),
        vol.Required("vpd_target"): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=3.0)
        ),
        vol.Required("vpd_tolerance"): vol.All(
            vol.Coerce(float), vol.Range(min=0.01, max=1.0)
        ),
        vol.Optional("stage_vpd_enabled"): bool,
        vol.Optional("stage_vpd_overrides"): dict,
        vol.Optional("critical_temp_low"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=10, max=40))
        ),
        vol.Optional("critical_temp_high"): vol.Any(
            None, vol.All(vol.Coerce(float), vol.Range(min=10, max=50))
        ),
        vol.Required("critical_temp_hysteresis"): vol.All(
            vol.Coerce(float), vol.Range(min=0.1, max=5.0)
        ),
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

RESET_PLANT_LAST_WATERED_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): str,
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
        vol.Required("nutrient_id"): str,
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
        vol.Optional("week", default=1): vol.All(int, vol.Range(min=1)),
        vol.Optional("ec_target"): vol.Any(
            vol.All(vol.Coerce(float), vol.Range(min=0.0)), None
        ),
        vol.Optional("ph_target"): vol.Any(
            vol.All(vol.Coerce(float), vol.Range(min=0.0, max=14.0)), None
        ),
    }
)

REMOVE_NUTRIENT_PRESET_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PRESET_ID): str,
    }
)

# --- Irrigation Recipe Schemas ---

SAVE_IRRIGATION_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_NAME): str,
        vol.Required(ATTR_RECIPE_KIND): vol.In([k.value for k in IrrigationRecipeKind]),
        # Present to overwrite an existing recipe in place; absent mints a new one.
        vol.Optional(ATTR_RECIPE_ID): str,
    }
)

# An edit is sparse: every value is optional and an unnamed field keeps what
# the recipe stores. The key sets below must stay equal to the editable fields
# `domain/irrigation_recipe.py` derives from the halves themselves — a contract
# test asserts exactly that, because a field missing here would be silently
# uneditable rather than loudly wrong.
_RECIPE_SCHEDULE_ITEM_SCHEMA = vol.Schema(
    {
        vol.Optional("time"): str,
        vol.Optional("duration"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("start_time"): str,
        vol.Optional("duration_seconds"): vol.Any(None, vol.Coerce(float)),
    }
)

CROP_STEERING_RECIPE_VALUES_SCHEMA = vol.Schema(
    {
        vol.Optional("lights_on_time"): str,
        vol.Optional("p0_duration_minutes"): vol.All(vol.Coerce(int), vol.Range(min=0)),
        vol.Optional("p2_stop_before_lights_off_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=0)
        ),
        vol.Optional("target_vwc_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        vol.Optional("maintenance_dryback_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        # Percents of substrate volume, never pump seconds
        # ([[Substrate-Relative Shot Storage]]).
        vol.Optional("p1_shot_volume_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        vol.Optional("p1_shot_interval_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Optional("p2_shot_volume_percent"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        vol.Optional("p2_shot_interval_minutes"): vol.All(
            vol.Coerce(int), vol.Range(min=1)
        ),
        vol.Optional("auto_light_tracking"): bool,
        vol.Optional("dynamic_shot_enabled"): bool,
        vol.Optional("dynamic_aggressiveness"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional("dynamic_recovery"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional("dynamic_shot_size_floor"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional("dynamic_interval_ceiling"): vol.All(
            vol.Coerce(float), vol.Range(min=0.0)
        ),
        vol.Optional("pore_ec_target_min"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("pore_ec_target_max"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("ec_modulation_enabled"): bool,
    }
)

SCHEDULE_RECIPE_VALUES_SCHEMA = vol.Schema(
    {
        vol.Optional("irrigation_times"): [_RECIPE_SCHEDULE_ITEM_SCHEMA],
        vol.Optional("drain_times"): [_RECIPE_SCHEDULE_ITEM_SCHEMA],
        vol.Optional("irrigation_duration"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("drain_duration"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("daily_volume_cap_liters"): vol.Any(None, vol.Coerce(float)),
        vol.Optional("max_cycles_per_day"): vol.Any(None, vol.Coerce(int)),
        vol.Optional("skip_during_dark"): bool,
    }
)

UPDATE_IRRIGATION_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE_ID): str,
        # Rename, correct the values, or both. The half must be the one this
        # recipe's kind holds; neither kind nor provenance is writable here.
        vol.Optional(ATTR_NAME): str,
        vol.Optional(ATTR_RECIPE_CROP_STEERING): CROP_STEERING_RECIPE_VALUES_SCHEMA,
        vol.Optional(ATTR_RECIPE_SCHEDULE): SCHEDULE_RECIPE_VALUES_SCHEMA,
    }
)

REMOVE_IRRIGATION_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_RECIPE_ID): str,
    }
)

APPLY_IRRIGATION_RECIPE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_RECIPE_ID): str,
    }
)

# --- Irrigation Program Schemas ---

# One (stage, week) slot. The stage set and the 1-indexed weeks are enforced by
# `domain/irrigation_program.py`, which owns what a reachable slot is; this
# schema only fixes the wire shape.
PROGRAM_SLOT_SCHEMA = vol.Schema(
    {
        vol.Required("stage"): str,
        vol.Required("week"): vol.Coerce(int),
        vol.Required("recipe_id"): str,
    }
)

SAVE_IRRIGATION_PROGRAM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_NAME): str,
        # The whole plan: saving replaces the slot list rather than merging
        # into it, so an empty list is a program a grower has emptied.
        vol.Required(ATTR_PROGRAM_SLOTS): [PROGRAM_SLOT_SCHEMA],
        # Present to overwrite an existing program in place; absent mints a new one.
        vol.Optional(ATTR_PROGRAM_ID): str,
    }
)

REMOVE_IRRIGATION_PROGRAM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROGRAM_ID): str,
    }
)

ASSIGN_IRRIGATION_PROGRAM_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        # Omitted or null unbinds. Binding applies nothing, so neither spelling
        # can change what a pump does.
        vol.Optional(ATTR_PROGRAM_ID): vol.Any(None, str),
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
        vol.Optional(ATTR_PLANT_IDS): vol.All(cv.ensure_list, [str]),
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
        vol.Optional(ATTR_TRANSITION_DATE): valid_date_or_none,
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

# --- EC Target Range Schema ---

SET_EC_TARGET_RANGE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_STAGE): vol.In(PLANT_STAGES),
        vol.Required(ATTR_FEED_EC_MIN): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Required(ATTR_FEED_EC_MAX): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
    }
)

APPLY_STEERING_MODE_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_GROWSPACE_ID): vol.All(str, valid_growspace_id),
        vol.Required(ATTR_STEERING_MODE): vol.In([m.value for m in SteeringMode]),
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
        vol.Required(ATTR_ACQUISITION_DATE): cv.date,
        vol.Required(ATTR_GENERATION): cv.string,
        vol.Optional(ATTR_LINEAGE, default=""): cv.string,
        vol.Optional(ATTR_PARENT_1_STRAIN): vol.Any(cv.string, None),
        vol.Optional(ATTR_PARENT_1_PHENOTYPE): vol.Any(cv.string, None),
        vol.Optional(ATTR_PARENT_2_STRAIN): vol.Any(cv.string, None),
        vol.Optional(ATTR_PARENT_2_PHENOTYPE): vol.Any(cv.string, None),
        vol.Optional(ATTR_NOTES, default=""): cv.string,
    }
)

LOG_POLLINATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DATE): cv.date,
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

UPDATE_SEED_BATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BATCH_ID): cv.string,
        vol.Optional(ATTR_STRAIN_NAME): cv.string,
        vol.Optional(ATTR_BREEDER): cv.string,
        vol.Optional(ATTR_QUANTITY): vol.All(vol.Coerce(int), vol.Range(min=1)),
        vol.Optional(ATTR_ACQUISITION_DATE): cv.date,
        vol.Optional(ATTR_GENERATION): cv.string,
        vol.Optional(ATTR_LINEAGE): cv.string,
        vol.Optional(ATTR_PARENT_1_STRAIN): vol.Any(cv.string, None),
        vol.Optional(ATTR_PARENT_1_PHENOTYPE): vol.Any(cv.string, None),
        vol.Optional(ATTR_PARENT_2_STRAIN): vol.Any(cv.string, None),
        vol.Optional(ATTR_PARENT_2_PHENOTYPE): vol.Any(cv.string, None),
        vol.Optional(ATTR_NOTES): cv.string,
    }
)

UPDATE_POLLINATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_ID): cv.string,
        vol.Optional(ATTR_DATE): cv.date,
        vol.Optional(ATTR_DONOR_PLANT_ID): cv.string,
        vol.Optional(ATTR_RECEIVER_PLANT_ID): cv.string,
        vol.Optional(ATTR_NOTES): cv.string,
    }
)

DELETE_POLLINATION_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_ID): cv.string,
    }
)

SOW_SEED_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_BATCH_ID): cv.string,
        vol.Required(ATTR_PLANT_ID): cv.string,
    }
)

SET_PLANT_SEX_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Required(ATTR_SEX): vol.In(["male", "female", "hermaphrodite"]),
    }
)

UNLINK_SEED_BATCH_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
    }
)

# --- Drying & Curing Schemas ---

LOG_DRYING_WEIGHT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Required(ATTR_WEIGHT_GRAMS): vol.All(vol.Coerce(float), vol.Range(min=0.0)),
        vol.Optional(ATTR_DATE): cv.string,
    }
)

LOG_MOISTURE_READING_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Required(ATTR_MOISTURE_PERCENT): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=100.0)
        ),
        vol.Optional(ATTR_DATE): cv.string,
    }
)

SET_VISUAL_TAG_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PLANT_ID): cv.string,
        vol.Optional(ATTR_VISUAL_TAG): vol.Any(cv.string, None),
    }
)
