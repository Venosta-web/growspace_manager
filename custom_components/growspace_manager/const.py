"""Constants for the Growspace Manager integration."""

from datetime import date, datetime
from enum import StrEnum

import voluptuous as vol

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

# Events
EVENT_GROWSPACE_UPDATED = f"{DOMAIN}_updated"
EVENT_GROWSPACE_ADDED = f"{DOMAIN}_growspace_added"
EVENT_GROWSPACE_REMOVED = f"{DOMAIN}_growspace_removed"
EVENT_PLANT_ADDED = f"{DOMAIN}_plant_added"
EVENT_PLANT_UPDATED = f"{DOMAIN}_plant_updated"
EVENT_PLANT_REMOVED = f"{DOMAIN}_plant_removed"
EVENT_PLANT_MOVED = f"{DOMAIN}_plant_moved"
EVENT_PLANT_SWITCHED = f"{DOMAIN}_plant_switched"
EVENT_PLANT_TRANSITIONED = f"{DOMAIN}_plant_transitioned"
EVENT_PLANT_HARVESTED = f"{DOMAIN}_plant_harvested"
EVENT_CLONES_TAKEN = f"{DOMAIN}_clones_taken"

# Icons
ICON_CANNABIS = "mdi:cannabis"
ICON_GROWSPACE = "mdi:home-group"
ICON_VPD = "mdi:cloud-check-variant"
ICON_CALCULATED_VPD = "mdi:cloud-percent"
ICON_AIR_EXCHANGE = "mdi:air-filter"
ICON_STRAIN_LIBRARY = "mdi:leaf"
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
    "stress": 0.70,
    "mold_risk": 0.75,
    "optimal": 0.80,
    "drying": 0.80,
    "curing": 0.80,
}


# --- Service Schemas ---


# Helper for common date/datetime parsing
def valid_date_or_none(value):
    """Validate that a value is a valid date or None for voluptuous schemas.

    Args:
        value: The value to validate.

    Returns:
        The parsed date object or None.

    Raises:
        vol.Invalid: If the value is not a valid date format.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return value

    value_str = str(value).replace("Z", "")

    # Try parsing as datetime first (most specific)
    try:
        return datetime.fromisoformat(value_str)
    except ValueError:
        pass

    # Try parsing as date
    try:
        return date.fromisoformat(value_str)
    except ValueError:
        raise vol.Invalid(
            f"'{value}' is not a valid date or ISO format string"
        ) from None


def valid_growspace_id(value):
    """Validate that a value is a non-empty string for a growspace ID.

    Args:
        value: The value to validate.

    Returns:
        The validated string.

    Raises:
        vol.Invalid: If the value is not a valid growspace ID.
    """

    if not isinstance(value, str) or not value:
        raise vol.Invalid("Growspace ID cannot be empty")
    return value


# Shared Schema Dictionaries
_PLANT_DATE_FIELDS = {vol.Optional(field): valid_date_or_none for field in DATE_FIELDS}

_PLANT_DAYS_FIELDS = {
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
    }
)

# Strain Library Schemas
EXPORT_STRAIN_LIBRARY_SCHEMA = vol.Schema(
    {
        # No required parameters for export, usually just triggers action
        # Optionally, could specify which strains to export, but current logic exports all
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

ADD_STRAIN_SCHEMA = vol.Schema(
    {
        vol.Required("strain"): str,
        vol.Optional("phenotype"): str,
        vol.Optional("breeder"): str,
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
        vol.Optional("phenotype"): str,
        vol.Optional("breeder"): str,
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
        vol.Required("temperature_sensor"): str,
        vol.Required("humidity_sensor"): str,
        vol.Optional("vpd_sensor"): str,
        vol.Optional("co2_sensor"): str,
        vol.Optional("dehumidifier_entity"): str,
        vol.Optional("circulation_fan"): str,
        vol.Optional("light_sensor"): str,
        vol.Optional("stress_threshold", default=0.70): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
        ),
        vol.Optional("mold_threshold", default=0.75): vol.All(
            vol.Coerce(float), vol.Range(min=0.0, max=1.0)
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
