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
        vol.Optional("seedling_start"): cv.date,
        vol.Optional("veg_start"): cv.date,
        vol.Optional("flower_start"): cv.date,
        vol.Optional("dry_start"): cv.date,
        vol.Optional("cure_start"): cv.date,
        vol.Optional("mother_start"): cv.date,
        vol.Optional("clone_start"): cv.date,
    }
)

UPDATE_PLANT_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Optional("growspace_id"): cv.string,
        vol.Optional("strain"): cv.string,
        vol.Optional("row"): cv.positive_int,
        vol.Optional("col"): cv.positive_int,
        vol.Optional("position"): cv.string,
        vol.Optional("phenotype"): cv.string,
        vol.Optional("seedling_start"): cv.date,
        vol.Optional("veg_start"): cv.date,
        vol.Optional("flower_start"): cv.date,
        vol.Optional("dry_start"): cv.date,
        vol.Optional("cure_start"): cv.date,
        vol.Optional("mother_start"): cv.date,
        vol.Optional("clone_start"): cv.date,
        # Extra fields you might want
        vol.Optional("stage"): cv.string,
        vol.Optional("position"): cv.string,
        vol.Optional("seedling_days"): vol.All(vol.Coerce(int)),
        vol.Optional("veg_days"): vol.All(vol.Coerce(int)),
        vol.Optional("flower_days"): vol.All(vol.Coerce(int)),
        vol.Optional("dry_days"): vol.All(vol.Coerce(int)),
        vol.Optional("cure_days"): vol.All(vol.Coerce(int)),
    },
    extra=vol.ALLOW_EXTRA,  # <-- allows any other keys from frontend
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
        vol.Optional("transition_date"): cv.date,
    }
)
MOVE_CLONE_SCHEMA = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Required("target_growspace_id"): cv.string,
        vol.Optional("transition_date"): cv.date,
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
        vol.Optional("transition_date"): cv.date,
    }
)
TAKE_CLONE_SCHEMA = vol.Schema(
    {
        vol.Required("mother_plant_id"): cv.string,
        vol.Optional("target_growspace_id"): cv.string,
        vol.Optional("target_growspace_name"): cv.string,
        vol.Optional("transition_date"): cv.date,
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

configure_environment:
  name: Configure Environment Monitoring
  description: Set up environment sensors for Bayesian monitoring on a growspace
  fields:
    growspace_id:
      name: Growspace ID
      description: The ID of the growspace to configure
      required: true
      example: "4x4_tent"
      selector:
        text:

    temperature_sensor:
      name: Temperature Sensor
      description: Temperature sensor entity (degrees C)
      required: true
      example: "sensor.4x4_tent_temperature"
      selector:
        entity:
          domain: sensor
          device_class: temperature

    humidity_sensor:
      name: Humidity Sensor
      description: Humidity sensor entity (%)
      required: true
      example: "sensor.4x4_tent_humidity"
      selector:
        entity:
          domain: sensor
          device_class: humidity

    vpd_sensor:
      name: VPD Sensor
      description: VPD sensor entity (kPa)
      required: true
      example: "sensor.4x4_tent_vpd"
      selector:
        entity:
          domain: sensor

    co2_sensor:
      name: CO2 Sensor (Optional)
      description: CO2 sensor entity (ppm)
      required: false
      example: "sensor.4x4_tent_co2"
      selector:
        entity:
          domain: sensor
          device_class: carbon_dioxide

    circulation_fan:
      name: Circulation Fan (Optional)
      description: Fan entity for mold risk detection
      required: false
      example: "fan.4x4_tent_circulation"
      selector:
        entity:
          domain: fan

    stress_threshold:
      name: Stress Detection Threshold
      description: Probability threshold for stress detection (0-1)
      required: false
      default: 0.70
      example: 0.70
      selector:
        number:
          min: 0.5
          max: 0.95
          step: 0.05

    mold_threshold:
      name: Mold Risk Threshold
      description: Probability threshold for mold risk detection (0-1)
      required: false
      default: 0.75
      example: 0.75
      selector:
        number:
          min: 0.5
          max: 0.95
          step: 0.05