"""Constants for the Growspace Manager integration."""

from datetime import date

import voluptuous as vol

DOMAIN = "growspace_manager"
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_storage"
PLATFORMS: list[str] = [
    "binary_sensor",
    "sensor",
    "switch",
]

DEFAULT_NAME = "Growspace Manager"
ATTR_TOTAL_DAYS = "total_days"

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

# Plant stages
PLANT_STAGES = ["seedling", "clone", "mother", "veg", "flower", "dry", "cure"]
VALID_STAGES = ["seedling", "clone", "mother", "veg", "flower", "dry", "cure"]

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
    if isinstance(value, date):
        return value
    try:
        # Attempt to parse ISO format, handling potential timezone 'Z'
        # Ensure value is converted to string to handle potential datetime objects directly
        return date.fromisoformat(str(value).replace("Z", ""))
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
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
    }
)

# Add Plant
ADD_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): vol.All(str, valid_growspace_id),
        vol.Required("strain"): str,
        vol.Required("row"): vol.All(int, vol.Range(min=1)),
        vol.Required("col"): vol.All(int, vol.Range(min=1)),
        vol.Optional("phenotype"): str,
        vol.Optional("seedling_start"): valid_date_or_none,
        vol.Optional("mother_start"): valid_date_or_none,
        vol.Optional("clone_start"): valid_date_or_none,
        vol.Optional("veg_start"): valid_date_or_none,
        vol.Optional("flower_start"): valid_date_or_none,
        vol.Optional("dry_start"): valid_date_or_none,
        vol.Optional("cure_start"): valid_date_or_none,
    }
)

# Update Plant
UPDATE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): str,
        vol.Optional("growspace_id"): str,
        vol.Optional("strain"): str,
        vol.Optional("phenotype"): str,
        vol.Optional("position"): str,
        vol.Optional("row"): vol.All(int, vol.Range(min=1)),
        vol.Optional("col"): vol.All(int, vol.Range(min=1)),
        vol.Optional("stage"): str,  # Assuming stage can be updated
        vol.Optional("seedling_start"): valid_date_or_none,
        vol.Optional("mother_start"): valid_date_or_none,
        vol.Optional("clone_start"): valid_date_or_none,
        vol.Optional("veg_start"): valid_date_or_none,
        vol.Optional("flower_start"): valid_date_or_none,
        vol.Optional("dry_start"): valid_date_or_none,
        vol.Optional("cure_start"): valid_date_or_none,
        vol.Optional("seedling_days"): vol.All(vol.Coerce(int)),
        vol.Optional("veg_days"): vol.All(vol.Coerce(int)),
        vol.Optional("flower_days"): vol.All(vol.Coerce(int)),
        vol.Optional("dry_days"): vol.All(vol.Coerce(int)),
        vol.Optional("cure_days"): vol.All(vol.Coerce(int)),
        vol.Optional("mother_days"): vol.All(vol.Coerce(int)),
        vol.Optional("clone_days"): vol.All(vol.Coerce(int)),
    },
    extra=vol.ALLOW_EXTRA,
)


# Remove Plant
REMOVE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): str,
    }
)

# Move Plant
MOVE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): str,
        vol.Required("new_row"): vol.All(int, vol.Range(min=1)),
        vol.Required("new_col"): vol.All(int, vol.Range(min=1)),
    }
)

# Switch Plants
SWITCH_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id_1"): str,
        vol.Required("plant_id_2"): str,
    }
)

# Transition Plant Stage
TRANSITION_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): str,
        vol.Required("new_stage"): str,
        vol.Optional("transition_date"): valid_date_or_none,
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
        vol.Optional("sativa_percentage"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("indica_percentage"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
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
        vol.Optional("sativa_percentage"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
        vol.Optional("indica_percentage"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
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
        vol.Required("vpd_sensor"): str,
        vol.Optional("co2_sensor"): str,
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
    }
)

ANALYZE_ALL_GROWSPACES_SCHEMA = vol.Schema({})  # No required parameters

STRAIN_RECOMMENDATION_SCHEMA = vol.Schema(
    {
        vol.Optional("preferences"): dict,
        vol.Optional("growspace_id"): str,
    }
)
