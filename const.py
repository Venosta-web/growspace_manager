"""Constants for the Growspace Manager integration."""

DOMAIN = "growspace_manager"
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}_storage"
PLATFORMS: list[str] = ["sensor", "switch"]

DEFAULT_NAME = "Growspace Manager"

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
DATE_FIELDS = [
    "seedling_start",
    "veg_start",
    "flower_start",
    "dry_start",
    "cure_start",
    "mother_start",
    "clone_start",
]
SPECIAL_GROWSPACES = {
    "dry": {
        "canonical_id": "dry",
        "canonical_name": "dry",
        "aliases": ["dry_overview"],
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
