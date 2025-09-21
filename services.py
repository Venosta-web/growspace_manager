"""Service schemas for Growspace Manager."""

from __future__ import annotations

import voluptuous as vol
from homeassistant.helpers import config_validation as cv

# Growspace services
ADD_GROWSPACE_SCHEMA = vol.Schema(
    {
        vol.Required("name"): cv.string,
        vol.Required("rows"): cv.positive_int,
        vol.Required("plants_per_row"): cv.positive_int,
        vol.Optional("notification_target"): cv.string,
    }
)

REMOVE_GROWSPACE_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): cv.string,
    }
)

# Plant services
ADD_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("growspace_id"): cv.string,
        vol.Required("strain"): cv.string,
        vol.Required("row"): cv.positive_int,
        vol.Required("col"): cv.positive_int,
        vol.Optional("phenotype"): cv.string,
        vol.Optional("veg_start"): cv.datetime,
        vol.Optional("flower_start"): cv.datetime,
        vol.Optional("dry_start"): cv.datetime,
        vol.Optional("cure_start"): cv.datetime,
        vol.Optional("mother_start"): cv.datetime,
        vol.Optional("clone_start"): cv.datetime,
    }
)

UPDATE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Optional("strain"): cv.string,
        vol.Optional("row"): cv.positive_int,
        vol.Optional("col"): cv.positive_int,
        vol.Optional("phenotype"): cv.string,
        vol.Optional("veg_start"): cv.datetime,
        vol.Optional("flower_start"): cv.datetime,
        vol.Optional("dry_start"): cv.datetime,
        vol.Optional("cure_start"): cv.datetime,
        vol.Optional("mother_start"): cv.datetime,
        vol.Optional("clone_start"): cv.datetime,
    }
)

REMOVE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
    }
)

MOVE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Required("new_row"): cv.positive_int,
        vol.Required("new_col"): cv.positive_int,
    }
)
SWITCH_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id_1"): cv.string,
        vol.Required("plant_id_2"): cv.string,
    }
)
TRANSITION_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Required("new_stage"): cv.string,
        vol.Optional("transition_date"): cv.datetime,
    }
)
MOVE_CLONE_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Required("target_growspace_id"): cv.string,
        vol.Optional("transition_date"): cv.datetime,
    }
)
EXPORT_STRAIN_LIBRARY_SCHEMA = vol.Schema({})

IMPORT_STRAIN_LIBRARY_SCHEMA = vol.Schema(
    {
        vol.Required("strains"): [cv.string],
        vol.Optional("replace", default=False): cv.boolean,
    }
)

CLEAR_STRAIN_LIBRARY_SCHEMA = vol.Schema({})

HARVEST_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Optional("target_growspace_id"): cv.string,
        vol.Optional("target_growspace_name"): cv.string,
        vol.Optional("transition_date"): cv.datetime,
    }
)
TAKE_CLONE_SCHEMA = vol.Schema(
    {
        vol.Required("mother_plant_id"): cv.string,
        vol.Optional("target_growspace_id"): cv.string,
        vol.Optional("target_growspace_name"): cv.string,
        vol.Optional("transition_date"): cv.datetime,
        vol.Optional("num_clones"): cv.positive_int,
    },
)
# Debug/maintenance services
DEBUG_CLEANUP_LEGACY_SCHEMA = vol.Schema(
    {
        vol.Optional("dry_only", default=False): cv.boolean,
        vol.Optional("cure_only", default=False): cv.boolean,
        vol.Optional("force", default=False): cv.boolean,
    }
)

DEBUG_LIST_GROWSPACES_SCHEMA = vol.Schema({})

DEBUG_RESET_SPECIAL_GROWSPACES_SCHEMA = vol.Schema(
    {
        vol.Optional("reset_dry", default=True): cv.boolean,
        vol.Optional("reset_cure", default=True): cv.boolean,
        vol.Optional("preserve_plants", default=True): cv.boolean,
    }
)

DEBUG_CONSOLIDATE_DUPLICATE_SPECIAL_SCHEMA = vol.Schema({})
