# Service API Reference

All services provided by the Growspace Manager integration can be invoked from Home Assistant automations, Lovelace buttons, developer tools, or custom scripts.

## Table of Services

1. [Database & Library Management](#database--library-management)
   - [growspace_manager.export_strain_library](#growspace_managerexport_strain_library)
   - [growspace_manager.import_strain_library](#growspace_managerimport_strain_library)
   - [growspace_manager.clear_strain_library](#growspace_managerclear_strain_library)
   - [growspace_manager.get_strain_library](#growspace_managerget_strain_library)
   - [growspace_manager.add_strain](#growspace_manageradd_strain)
   - [growspace_manager.update_strain_meta](#growspace_managerupdate_strain_meta)
   - [growspace_manager.remove_strain](#growspace_managerremove_strain)
2. [Facility & Growspace Management](#facility--growspace-management)
   - [growspace_manager.add_growspace](#growspace_manageradd_growspace)
   - [growspace_manager.update_growspace](#growspace_managerupdate_growspace)
   - [growspace_manager.remove_growspace](#growspace_managerremove_growspace)
   - [growspace_manager.analyze_all_growspaces](#growspace_manageranalyze_all_growspaces)
3. [Plant & Lifecycle Stage Tracking](#plant--lifecycle-stage-tracking)
   - [growspace_manager.add_plant](#growspace_manageradd_plant)
   - [growspace_manager.add_plants](#growspace_manageradd_plants)
   - [growspace_manager.update_plant](#growspace_managerupdate_plant)
   - [growspace_manager.remove_plant](#growspace_managerremove_plant)
   - [growspace_manager.move_plant](#growspace_managermove_plant)
   - [growspace_manager.switch_plants](#growspace_managerswitch_plants)
   - [growspace_manager.transition_plant_stage](#growspace_managertransition_plant_stage)
   - [growspace_manager.harvest_plant](#growspace_managerharvest_plant)
   - [growspace_manager.take_clone](#growspace_managertake_clone)
   - [growspace_manager.move_clone](#growspace_managermove_clone)
   - [growspace_manager.set_visual_tag](#growspace_managerset_visual_tag)
   - [growspace_manager.reset_plant_last_watered](#growspace_managerreset_plant_last_watered)
   - [growspace_manager.batch_action](#growspace_managerbatch_action)
4. [Environmental & HVAC Controls](#environmental--hvac-controls)
   - [growspace_manager.configure_environment](#growspace_managerconfigure_environment)
   - [growspace_manager.remove_environment](#growspace_managerremove_environment)
   - [growspace_manager.set_dehumidifier_control](#growspace_managerset_dehumidifier_control)
5. [Smart Irrigation & Steering](#smart-irrigation--steering)
   - [growspace_manager.set_irrigation_settings](#growspace_managerset_irrigation_settings)
   - [growspace_manager.set_irrigation_strategy](#growspace_managerset_irrigation_strategy)
   - [growspace_manager.add_irrigation_time](#growspace_manageradd_irrigation_time)
   - [growspace_manager.remove_irrigation_time](#growspace_managerremove_irrigation_time)
   - [growspace_manager.reset_water_tracking](#growspace_managerreset_water_tracking)
6. [Drainage & Runoff Monitoring](#drainage--runoff-monitoring)
   - [growspace_manager.add_drain_time](#growspace_manageradd_drain_time)
   - [growspace_manager.remove_drain_time](#growspace_managerremove_drain_time)
   - [growspace_manager.log_drain_reading](#growspace_managerlog_drain_reading)
   - [growspace_manager.configure_drain_monitoring](#growspace_managerconfigure_drain_monitoring)
7. [Nutrition & Integrated Pest Management](#nutrition--integrated-pest-management)
   - [growspace_manager.save_nutrient_preset](#growspace_managersave_nutrient_preset)
   - [growspace_manager.remove_nutrient_preset](#growspace_managerremove_nutrient_preset)
   - [growspace_manager.save_ec_ramp_curve](#growspace_managersave_ec_ramp_curve)
   - [growspace_manager.remove_ec_ramp_curve](#growspace_managerremove_ec_ramp_curve)
   - [growspace_manager.save_ipm_preset](#growspace_managersave_ipm_preset)
   - [growspace_manager.remove_ipm_preset](#growspace_managerremove_ipm_preset)
   - [growspace_manager.apply_ipm](#growspace_managerapply_ipm)
8. [AI Assistant & Diagnostics](#ai-assistant--diagnostics)
   - [growspace_manager.ask_grow_advice](#growspace_managerask_grow_advice)
   - [growspace_manager.strain_recommendation](#growspace_managerstrain_recommendation)
   - [growspace_manager.trigger_vision_checkup](#growspace_managertrigger_vision_checkup)
9. [Genetics & Breeding Registry](#genetics--breeding-registry)
   - [growspace_manager.add_seed_batch](#growspace_manageradd_seed_batch)
   - [growspace_manager.update_seed_batch](#growspace_managerupdate_seed_batch)
   - [growspace_manager.log_pollination](#growspace_managerlog_pollination)
   - [growspace_manager.score_phenotype](#growspace_managerscore_phenotype)
   - [growspace_manager.harvest_seeds](#growspace_managerharvest_seeds)
10. [Post-Harvest Drying & Curing](#post-harvest-drying--curing)
    - [growspace_manager.log_drying_weight](#growspace_managerlog_drying_weight)
    - [growspace_manager.log_moisture_reading](#growspace_managerlog_moisture_reading)
11. [Alerts & Utility](#alerts--utility)
    - [growspace_manager.test_notification](#growspace_managertest_notification)
    - [growspace_manager.print_label](#growspace_managerprint_label)
    - [growspace_manager.log_training_event](#growspace_managerlog_training_event)
12. [Debugging & Maintenance Utilities](#debugging--maintenance-utilities)
    - [growspace_manager.debug_cleanup_legacy](#growspace_managerdebug_cleanup_legacy)
    - [growspace_manager.debug_list_growspaces](#growspace_managerdebug_list_growspaces)
    - [growspace_manager.debug_reset_special_growspaces](#growspace_managerdebug_reset_special_growspaces)

---

## Database & Library Management

### `growspace_manager.export_strain_library`

Exports the entire strain catalog including descriptions, breeder logos, and gallery images to a single, easily portable ZIP archive.
_No parameters required._

### `growspace_manager.import_strain_library`

Imports a strain library from a previously exported ZIP file.

| Parameter    | Type      | Required | Default | Description                                                         |
| :----------- | :-------- | :------- | :------ | :------------------------------------------------------------------ |
| `file_path`  | `string`  | No       | -       | Full server path to the ZIP archive.                                |
| `zip_base64` | `string`  | No       | -       | Base64-encoded ZIP file payload (used for direct frontend uploads). |
| `replace`    | `boolean` | No       | `false` | If `true`, completely replaces existing catalog; otherwise merges.  |

_Example:_

```yaml
service: growspace_manager.import_strain_library
data:
  file_path: "/home/homeassistant/.homeassistant/share/strain_library_backup.zip"
  replace: true
```

### `growspace_manager.clear_strain_library`

Completely resets the local strain catalog database, removing all strain, phenotype, and breeder records.
_No parameters required._

### `growspace_manager.get_strain_library`

Fetches and returns the full strain library database (primarily utilized by frontend dashboards).
_No parameters required._

### `growspace_manager.add_strain`

Directly inserts a new strain variety with detailed genetic metadata into the library.

| Parameter           | Type      | Required | Default | Description                                                                       |
| :------------------ | :-------- | :------- | :------ | :-------------------------------------------------------------------------------- |
| `strain`            | `string`  | Yes      | -       | Name of the strain (e.g., "Gorilla Glue #4").                                     |
| `phenotype`         | `string`  | No       | -       | Phenotype description or identifier (e.g., "Sour Cut").                           |
| `breeder`           | `string`  | No       | -       | Name of the breeder or seed company.                                              |
| `type`              | `string`  | No       | -       | Strain classification (e.g., "Indica", "Sativa Hybrid").                          |
| `lineage`           | `string`  | No       | -       | Parent strains (e.g., "Sour Dubb x Chem Sis").                                    |
| `sex`               | `string`  | No       | -       | Genetic sex (e.g., "Feminized", "Regular", "Autoflower").                         |
| `flower_days_min`   | `integer` | No       | -       | Minimum expected flowering time (days).                                           |
| `flower_days_max`   | `integer` | No       | -       | Maximum expected flowering time (days).                                           |
| `sativa_percentage` | `integer` | No       | -       | Sativa ratio (0 to 100).                                                          |
| `indica_percentage` | `integer` | No       | -       | Indica ratio (0 to 100).                                                          |
| `breeder_logo`      | `string`  | No       | -       | URL or local path to breeder's logo image.                                        |
| `description`       | `string`  | No       | -       | Rich description of characteristics, flavor profile, and aromas.                  |
| `image_base64`      | `string`  | No       | -       | Base64-encoded image string for the main strain photo.                            |
| `image_path`        | `string`  | No       | -       | Local server path to the main strain photo.                                       |
| `image_crop_meta`   | `object`  | No       | -       | Crop coordinates and metadata for the main image.                                 |
| `images`            | `list`    | No       | -       | Gallery image configurations, list of objects: `{path, crop_meta, is_thumbnail}`. |

_Example:_

```yaml
service: growspace_manager.add_strain
data:
  strain: "Mac1"
  breeder: "Capulator"
  type: "Hybrid"
  sex: "Clonely"
  flower_days_min: 63
  flower_days_max: 70
```

### `growspace_manager.update_strain_meta`

Updates genetic metadata, logs, or photos for an existing strain catalog entry.

| Parameter           | Type      | Required | Default | Description                                                                       |
| :------------------ | :-------- | :------- | :------ | :-------------------------------------------------------------------------------- |
| `strain`            | `string`  | Yes      | -       | Name of the strain to modify.                                                     |
| `phenotype`         | `string`  | No       | -       | Phenotype matching key.                                                           |
| `breeder`           | `string`  | No       | -       | Name of the breeder or seed company.                                              |
| `type`              | `string`  | No       | -       | Strain classification (e.g., "Indica", "Sativa Hybrid").                          |
| `lineage`           | `string`  | No       | -       | Parent strains (e.g., "Sour Dubb x Chem Sis").                                    |
| `sex`               | `string`  | No       | -       | Genetic sex (e.g., "Feminized", "Regular", "Autoflower").                         |
| `flower_days_min`   | `integer` | No       | -       | Minimum expected flowering time (days).                                           |
| `flower_days_max`   | `integer` | No       | -       | Maximum expected flowering time (days).                                           |
| `description`       | `string`  | No       | -       | Rich description of characteristics, flavor profile, and aromas.                  |
| `image_base64`      | `string`  | No       | -       | Base64-encoded image string for the main strain photo.                            |
| `image_path`        | `string`  | No       | -       | Local server path to the main strain photo.                                       |
| `image_crop_meta`   | `object`  | No       | -       | Crop coordinates and metadata for the main image.                                 |
| `images`            | `list`    | No       | -       | Gallery image configurations, list of objects: `{path, crop_meta, is_thumbnail}`. |
| `sativa_percentage` | `integer` | No       | -       | Sativa ratio (0 to 100).                                                          |
| `indica_percentage` | `integer` | No       | -       | Indica ratio (0 to 100).                                                          |
| `breeder_logo`      | `string`  | No       | -       | URL or local path to breeder's logo image.                                        |

### `growspace_manager.remove_strain`

Deletes a strain record and all associated images from the catalog.

| Parameter   | Type     | Required | Default | Description                   |
| :---------- | :------- | :------- | :------ | :---------------------------- |
| `strain`    | `string` | Yes      | -       | Name of the strain to remove. |
| `phenotype` | `string` | No       | -       | Specific phenotype to remove. |

---

## Facility & Growspace Management

### `growspace_manager.add_growspace`

Registers a new physical growspace zone.

| Parameter             | Type      | Required | Default | Description                       |
| :-------------------- | :-------- | :------- | :------ | :-------------------------------- |
| `name`                | `string`  | Yes      | -       | Name of the growspace zone.       |
| `rows`                | `integer` | Yes      | -       | Number of rows in grid (1-20).    |
| `plants_per_row`      | `integer` | Yes      | -       | Number of columns in grid (1-20). |
| `notification_target` | `string`  | No       | -       | Mobile notification service name. |

### `growspace_manager.update_growspace`

Updates configuration of an existing growspace.

| Parameter             | Type      | Required | Default | Description                  |
| :-------------------- | :-------- | :------- | :------ | :--------------------------- |
| `growspace_id`        | `string`  | Yes      | -       | Target growspace unique ID.  |
| `name`                | `string`  | No       | -       | New descriptive name.        |
| `rows`                | `integer` | No       | -       | New row grid count.          |
| `plants_per_row`      | `integer` | No       | -       | New columns per row count.   |
| `notification_target` | `string`  | No       | -       | Updated notification target. |

_Example:_

```yaml
service: growspace_manager.update_growspace
data:
  growspace_id: "room_1"
  notification_target: "notify.mobile_app_ipad"
```

### `growspace_manager.remove_growspace`

Deletes a growspace zone and permanently un-registers all plants housed inside it.

| Parameter      | Type     | Required | Default | Description             |
| :------------- | :------- | :------- | :------ | :---------------------- |
| `growspace_id` | `string` | Yes      | -       | Growspace ID to delete. |

### `growspace_manager.analyze_all_growspaces`

Triggers an automated evaluation of all facility zones, producing a detailed markdown summary of environment statuses, plant health indicators, and recommendations.

| Parameter    | Type      | Required | Default | Description                                            |
| :----------- | :-------- | :------- | :------ | :----------------------------------------------------- |
| `max_length` | `integer` | No       | `1000`  | Max character limit for the generated facility report. |

---

## Plant & Lifecycle Stage Tracking

### `growspace_manager.add_plant`

Places a single plant into a specific coordinate on the growspace grid.

| Parameter        | Type      | Required | Default | Description                             |
| :--------------- | :-------- | :------- | :------ | :-------------------------------------- |
| `growspace_id`   | `string`  | Yes      | -       | Target growspace ID.                    |
| `strain`         | `string`  | Yes      | -       | Strain name.                            |
| `row`            | `integer` | Yes      | -       | Grid row coordinate (starts at 1).      |
| `col`            | `integer` | Yes      | -       | Grid column coordinate (starts at 1).   |
| `phenotype`      | `string`  | No       | -       | Phenotype description.                  |
| `seedling_start` | `date`    | No       | -       | Seedling stage start date (YYYY-MM-DD). |
| `mother_start`   | `date`    | No       | -       | Mother stage start date.                |
| `clone_start`    | `date`    | No       | -       | Clone stage start.                      |
| `veg_start`      | `date`    | No       | -       | Veg stage start date.                   |
| `flower_start`   | `date`    | No       | -       | Flower stage start date.                |
| `dry_start`      | `date`    | No       | -       | Dry stage start date.                   |
| `cure_start`     | `date`    | No       | -       | Cure stage start date.                  |
| `notes`          | `string`  | No       | -       | Rich notes about plant history.         |

### `growspace_manager.add_plants`

Batch-inserts multiple plants of the same variety into consecutive empty spots in a growspace.

| Parameter        | Type      | Required | Default | Description                                                          |
| :--------------- | :-------- | :------- | :------ | :------------------------------------------------------------------- |
| `growspace_id`   | `string`  | Yes      | -       | Target growspace ID.                                                 |
| `strain`         | `string`  | Yes      | -       | Strain name.                                                         |
| `amount`         | `integer` | Yes      | -       | Quantity of plants to insert.                                        |
| `start_number`   | `integer` | No       | `1`     | Suffix numbering starting index (e.g. "Chem Dog #1", "Chem Dog #2"). |
| `seedling_start` | `date`    | No       | -       | Seedling stage start date (YYYY-MM-DD).                              |
| `mother_start`   | `date`    | No       | -       | Mother stage start date (YYYY-MM-DD).                                |
| `clone_start`    | `date`    | No       | -       | Clone stage start date (YYYY-MM-DD).                                 |
| `veg_start`      | `date`    | No       | -       | Vegetative stage start date (YYYY-MM-DD).                            |
| `flower_start`   | `date`    | No       | -       | Flowering stage start date (YYYY-MM-DD).                             |
| `dry_start`      | `date`    | No       | -       | Drying stage start date (YYYY-MM-DD).                                |
| `cure_start`     | `date`    | No       | -       | Curing stage start date (YYYY-MM-DD).                                |

### `growspace_manager.update_plant`

Edits attributes, stages, or coordinate locations of a plant.

| Parameter        | Type      | Required | Default | Description                                                                         |
| :--------------- | :-------- | :------- | :------ | :---------------------------------------------------------------------------------- |
| `plant_id`       | `string`  | Yes      | -       | Target plant ID.                                                                    |
| `growspace_id`   | `string`  | No       | -       | Target growspace ID.                                                                |
| `strain`         | `string`  | No       | -       | New strain name.                                                                    |
| `phenotype`      | `string`  | No       | -       | Phenotype.                                                                          |
| `position`       | `string`  | No       | -       | Grid position string (e.g. "A1", "B2").                                             |
| `row`            | `integer` | No       | -       | New grid row.                                                                       |
| `col`            | `integer` | No       | -       | New grid column.                                                                    |
| `seedling_start` | `date`    | No       | -       | Seedling stage start date (YYYY-MM-DD).                                             |
| `mother_start`   | `date`    | No       | -       | Mother stage start date (YYYY-MM-DD).                                               |
| `clone_start`    | `date`    | No       | -       | Clone stage start date (YYYY-MM-DD).                                                |
| `veg_start`      | `date`    | No       | -       | Vegetative stage start date (YYYY-MM-DD).                                           |
| `flower_start`   | `date`    | No       | -       | Flowering stage start date (YYYY-MM-DD).                                            |
| `dry_start`      | `date`    | No       | -       | Drying stage start date (YYYY-MM-DD).                                               |
| `cure_start`     | `date`    | No       | -       | Curing stage start date (YYYY-MM-DD).                                               |
| `stage`          | `string`  | No       | -       | Directly set stage (`seedling`, `mother`, `clone`, `veg`, `flower`, `dry`, `cure`). |
| `notes`          | `string`  | No       | -       | Update notes.                                                                       |

### `growspace_manager.remove_plant`

Deletes a plant and removes its sensor entity.

| Parameter  | Type     | Required | Default | Description         |
| :--------- | :------- | :------- | :------ | :------------------ |
| `plant_id` | `string` | Yes      | -       | Plant ID to remove. |

### `growspace_manager.move_plant`

Relocates a plant to new coordinates. If another plant occupies the target spot, their positions switch.

| Parameter  | Type      | Required | Default | Description                    |
| :--------- | :-------- | :------- | :------ | :----------------------------- |
| `plant_id` | `string`  | Yes      | -       | Target plant ID.               |
| `new_row`  | `integer` | Yes      | -       | Target grid row coordinate.    |
| `new_col`  | `integer` | Yes      | -       | Target grid column coordinate. |

### `growspace_manager.switch_plants`

Explicitly swaps the grid positions of two plants.

| Parameter   | Type     | Required | Default | Description      |
| :---------- | :------- | :------- | :------ | :--------------- |
| `plant1_id` | `string` | Yes      | -       | First plant ID.  |
| `plant2_id` | `string` | Yes      | -       | Second plant ID. |

### `growspace_manager.transition_plant_stage`

Transitions a plant to a new growth phase (e.g. flipping from Vegetative to Flowering).

| Parameter         | Type     | Required | Default | Description                                                           |
| :---------------- | :------- | :------- | :------ | :-------------------------------------------------------------------- |
| `plant_id`        | `string` | Yes      | -       | Plant ID.                                                             |
| `new_stage`       | `string` | Yes      | -       | Stage: `seedling`, `mother`, `clone`, `veg`, `flower`, `dry`, `cure`. |
| `transition_date` | `date`   | No       | _Today_ | Optional date transition occurred.                                    |

### `growspace_manager.harvest_plant`

Harvests a plant, records its metrics, and auto-routes it to the drying or curing growspaces.

| Parameter             | Type     | Required | Default  | Description                                               |
| :-------------------- | :------- | :------- | :------- | :-------------------------------------------------------- |
| `plant_id`            | `string` | Yes      | -        | Plant ID.                                                 |
| `target_growspace_id` | `string` | No       | _drying_ | Destination growspace zone.                               |
| `transition_date`     | `date`   | No       | _Today_  | Date of harvest.                                          |
| `wet_weight`          | `float`  | No       | -        | Wet weight at harvest in grams.                           |
| `dry_weight`          | `float`  | No       | -        | Final cured dry weight in grams.                          |
| `trim_weight`         | `float`  | No       | -        | Sugar leaf and trim weight in grams.                      |
| `thc_percentage`      | `float`  | No       | -        | THC lab test score (0-100%).                              |
| `cbd_percentage`      | `float`  | No       | -        | CBD lab test score (0-100%).                              |
| `terpene_profile`     | `string` | No       | -        | Rich description of terpenes (e.g., "Limonene dominant"). |

### `growspace_manager.take_clone`

Creates multiple new clone seedlings from a mother plant and places them into the clones growspace.

| Parameter             | Type      | Required | Default  | Description                       |
| :-------------------- | :-------- | :------- | :------- | :-------------------------------- |
| `mother_plant_id`     | `string`  | Yes      | -        | Mother donor plant ID.            |
| `target_growspace_id` | `string`  | No       | _clones_ | Destination clones zone.          |
| `transition_date`     | `date`    | No       | _Today_  | Date clones were cut.             |
| `num_clones`          | `integer` | No       | `1`      | Quantity of clone cuttings taken. |

### `growspace_manager.move_clone`

Relocates a rooted clone to a vegetative or mother growspace grid coordinate.

| Parameter             | Type     | Required | Default | Description                  |
| :-------------------- | :------- | :------- | :------ | :--------------------------- |
| `plant_id`            | `string` | Yes      | -       | Clone plant ID.              |
| `target_growspace_id` | `string` | Yes      | -       | Target veg/mother growspace. |
| `transition_date`     | `date`   | No       | _Today_ | Date of transplanting.       |

### `growspace_manager.set_visual_tag`

Attaches or clears a visual identification label (e.g. colored ties, nursery tags) to track physical plants easily.

| Parameter    | Type     | Required | Default | Description                                     |
| :----------- | :------- | :------- | :------ | :---------------------------------------------- |
| `plant_id`   | `string` | Yes      | -       | Target plant ID.                                |
| `visual_tag` | `string` | No       | -       | Tag label (e.g., "Orange Clip"). Omit to clear. |

### `growspace_manager.reset_plant_last_watered`

_Warning: E2E and Test Fixture Use Only._ Manually clears a plant's `last_watered` timestamp.

| Parameter  | Type     | Required | Default | Description         |
| :--------- | :------- | :------- | :------ | :------------------ |
| `plant_id` | `string` | Yes      | -       | Plant ID to modify. |

### `growspace_manager.batch_action`

Executes a synchronized action across a list of plants.

| Parameter    | Type     | Required | Default | Description                                               |
| :----------- | :------- | :------- | :------ | :-------------------------------------------------------- |
| `entity_ids` | `list`   | Yes      | -       | Array of plant IDs.                                       |
| `action`     | `string` | Yes      | -       | Action: `transition`, `harvest`, `remove`, `take_clone`.  |
| `data`       | `object` | No       | -       | Dictionary parameters corresponding to the action chosen. |

_Example:_

```yaml
service: growspace_manager.batch_action
data:
  entity_ids:
    - "plant_uuid_1"
    - "plant_uuid_2"
  action: "transition"
  data:
    new_stage: "flower"
```

---

## Environmental & HVAC Controls

### `growspace_manager.configure_environment`

Binds physical environmental monitors, light schedules, and active climate controls to a growspace zone.

| Parameter              | Type      | Required | Default | Description                                                  |
| :--------------------- | :-------- | :------- | :------ | :----------------------------------------------------------- |
| `growspace_id`         | `string`  | Yes      | -       | Growspace zone ID.                                           |
| `temperature_sensor`   | `string`  | Yes      | -       | Ambient temperature sensor entity.                           |
| `humidity_sensor`      | `string`  | Yes      | -       | Ambient relative humidity sensor entity.                     |
| `vpd_sensor`           | `string`  | Yes      | -       | Vapor Pressure Deficit sensor entity (kPa).                  |
| `co2_sensor`           | `string`  | No       | -       | Carbon Dioxide sensor entity (ppm).                          |
| `circulation_fan`      | `string`  | No       | -       | Circulation fan switch/fan entity.                           |
| `exhaust_entity`       | `string`  | No       | -       | Exhaust fan/damper switch/fan entity.                        |
| `humidifier_entity`    | `string`  | No       | -       | Humidifier controller or switch.                             |
| `dehumidifier_entity`  | `string`  | No       | -       | Dehumidifier controller or switch.                           |
| `light_sensor`         | `string`  | No       | -       | Light level sensor or light switch status entity.            |
| `soil_moisture_sensor` | `string`  | No       | -       | Substrate VWC soil moisture sensor entity.                   |
| `stress_threshold`     | `float`   | No       | `0.70`  | Bayesian stress alert confidence threshold (0.50-0.95).      |
| `mold_threshold`       | `float`   | No       | `0.75`  | Bayesian mold alert confidence threshold (0.50-0.95).        |
| `control_dehumidifier` | `boolean` | No       | `false` | Enable active automated target steering of the dehumidifier. |
| `sensor_groups`        | `object`  | No       | -       | Configuration mapping for multidimensional heatmaps.         |
| `sensor_coordinates`   | `object`  | No       | -       | Coordinates map for multi-sensor configurations.             |
| `irrigation_tanks`     | `object`  | No       | -       | Irrigation nutrient tank volume & EC configurations.         |

### `growspace_manager.remove_environment`

Permanently disconnects all climate monitors and automated climate steering controllers from a growspace.

| Parameter      | Type     | Required | Default | Description               |
| :------------- | :------- | :------- | :------ | :------------------------ |
| `growspace_id` | `string` | Yes      | -       | Target growspace zone ID. |

### `growspace_manager.set_dehumidifier_control`

Toggles active dynamic climate steering on/off.

| Parameter      | Type      | Required | Default | Description                        |
| :------------- | :-------- | :------- | :------ | :--------------------------------- |
| `growspace_id` | `string`  | Yes      | -       | Growspace ID.                      |
| `enabled`      | `boolean` | Yes      | -       | Whether active control is enabled. |

---

## Smart Irrigation & Steering

### `growspace_manager.set_irrigation_settings`

Sets the basic plumbing hardware profiles and default cycle times for simple timer waterings.

| Parameter                | Type      | Required | Default | Description                                    |
| :----------------------- | :-------- | :------- | :------ | :--------------------------------------------- |
| `growspace_id`           | `string`  | Yes      | -       | Target growspace zone ID.                      |
| `irrigation_pump_entity` | `string`  | No       | -       | Feed pump switch entity ID.                    |
| `drain_pump_entity`      | `string`  | No       | -       | Drainage pump switch entity ID.                |
| `irrigation_duration`    | `integer` | No       | -       | Standard duration to run feed pump (seconds).  |
| `drain_duration`         | `integer` | No       | -       | Standard duration to run drain pump (seconds). |

### `growspace_manager.set_irrigation_strategy`

Configures high-level Volumetric Water Content (VWC) crop-steering automation schedules.

| Parameter                           | Type      | Required | Default    | Description                                                     |
| :---------------------------------- | :-------- | :------- | :--------- | :-------------------------------------------------------------- |
| `growspace_id`                      | `string`  | Yes      | -          | Target growspace zone ID.                                       |
| `enabled`                           | `boolean` | No       | `true`     | Toggles strategy-guided pump control.                           |
| `lights_on_time`                    | `string`  | No       | "06:00:00" | Time of day lights switch on (HH:MM:SS format).                 |
| `p0_duration_minutes`               | `integer` | No       | `120`      | Root warmup time post-sunrise before first irrigation.          |
| `p2_stop_before_lights_off_minutes` | `integer` | No       | `120`      | Stop irrigating before sunset to allow overnight dryback.       |
| `target_vwc_percent`                | `float`   | No       | `65.0`     | Target VWC percentage during Phase 1 (irrigation ramp).         |
| `maintenance_dryback_percent`       | `float`   | No       | `5.0`      | Target dryback drop before triggering single maintenance shots. |
| `shot_duration_seconds`             | `integer` | No       | `30`       | Duration of each individual steering shot (seconds).            |
| `shot_interval_minutes`             | `integer` | No       | `15`       | Minimum rest interval between steering shots.                   |

### `growspace_manager.add_irrigation_time`

Manually schedules a daily fixed-time watering event.

| Parameter      | Type      | Required | Default | Description                       |
| :------------- | :-------- | :------- | :------ | :-------------------------------- |
| `growspace_id` | `string`  | Yes      | -       | Growspace zone ID.                |
| `time`         | `string`  | Yes      | -       | Watering trigger time (HH:MM:SS). |
| `duration`     | `integer` | No       | -       | Run duration override (seconds).  |

### `growspace_manager.remove_irrigation_time`

Removes a specific scheduled fixed watering time.

| Parameter      | Type     | Required | Default | Description                |
| :------------- | :------- | :------- | :------ | :------------------------- |
| `growspace_id` | `string` | Yes      | -       | Growspace zone ID.         |
| `time`         | `string` | Yes      | -       | Time to delete (HH:MM:SS). |

### `growspace_manager.reset_water_tracking`

Resets the cumulative water consumption counter (liters/gallons) to zero.

| Parameter      | Type     | Required | Default | Description               |
| :------------- | :------- | :------- | :------ | :------------------------ |
| `growspace_id` | `string` | Yes      | -       | Target growspace zone ID. |

---

## Drainage & Runoff Monitoring

### `growspace_manager.add_drain_time`

Schedules a fixed time to trigger the drainage pump manually (useful for flushing).

| Parameter      | Type      | Required | Default | Description                           |
| :------------- | :-------- | :------- | :------ | :------------------------------------ |
| `growspace_id` | `string`  | Yes      | -       | Growspace zone ID.                    |
| `time`         | `string`  | Yes      | -       | Trigger time (HH:MM:SS).              |
| `duration`     | `integer` | No       | -       | Pump run duration override (seconds). |

### `growspace_manager.remove_drain_time`

Removes a scheduled drain time.

| Parameter      | Type     | Required | Default | Description                |
| :------------- | :------- | :------- | :------ | :------------------------- |
| `growspace_id` | `string` | Yes      | -       | Growspace zone.            |
| `time`         | `string` | Yes      | -       | Time to delete (HH:MM:SS). |

### `growspace_manager.log_drain_reading`

Manually documents runoff chemistry and volumes to track root-zone dynamics.

| Parameter         | Type      | Required | Default | Description                                                 |
| :---------------- | :-------- | :------- | :------ | :---------------------------------------------------------- |
| `growspace_id`    | `string`  | Yes      | -       | Growspace ID.                                               |
| `feed_ec`         | `float`   | Yes      | -       | Electrical conductivity of the feed input water (mS/cm).    |
| `drain_ec`        | `float`   | Yes      | -       | Electrical conductivity of the runoff/drain output (mS/cm). |
| `drain_volume_ml` | `integer` | No       | -       | Total volume of runoff collected (mL).                      |
| `feed_volume_ml`  | `integer` | No       | -       | Total volume of feed solution applied (mL).                 |

_Example:_

```yaml
service: growspace_manager.log_drain_reading
data:
  growspace_id: "tent_1"
  feed_ec: 1.8
  drain_ec: 2.2
  drain_volume_ml: 600
  feed_volume_ml: 3000
```

### `growspace_manager.configure_drain_monitoring`

Sets alarms and tracking guidelines for runoff performance.

| Parameter               | Type      | Required | Default | Description                                                                   |
| :---------------------- | :-------- | :------- | :------ | :---------------------------------------------------------------------------- |
| `growspace_id`          | `string`  | Yes      | -       | Growspace zone ID.                                                            |
| `enabled`               | `boolean` | No       | `true`  | Toggle active runoff monitoring alerts.                                       |
| `max_ec_delta`          | `float`   | No       | `1.0`   | Maximum delta (Drain EC - Feed EC) allowed before salt buildup alert (mS/cm). |
| `target_runoff_percent` | `integer` | No       | `20`    | Target runoff percentage (drainage volume / feed volume \* 100).              |

---

## Nutrition & Integrated Pest Management

### `growspace_manager.save_nutrient_preset`

Schedules a nutrient feeding recipe and binds it to a plant stage.

| Parameter           | Type      | Required | Default | Description                                                                                            |
| :------------------ | :-------- | :------- | :------ | :----------------------------------------------------------------------------------------------------- |
| `name`              | `string`  | Yes      | -       | Name of the feeding preset (e.g. "Late Bloom Recipe").                                                 |
| `nutrients`         | `object`  | Yes      | -       | Dictionary mapping nutrients and volumes (e.g., `{"Base A": 5.0, "Base B": 5.0, "Bloom Boost": 2.5}`). |
| `preset_id`         | `string`  | No       | -       | Preset ID to overwrite.                                                                                |
| `stage`             | `string`  | No       | -       | Stage constraint: `seedling`, `mother`, `clone`, `veg`, `flower`.                                      |
| `min_days_in_stage` | `integer` | No       | `0`     | Minimum growth phase days required before recommending this recipe.                                    |

### `growspace_manager.remove_nutrient_preset`

Deletes a feeding recipe.

| Parameter   | Type     | Required | Default | Description                   |
| :---------- | :------- | :------- | :------ | :---------------------------- |
| `preset_id` | `string` | Yes      | -       | Nutrient preset ID to delete. |

### `growspace_manager.save_ec_ramp_curve`

Saves an Electrical Conductivity ramp schedule to guide automate dosers as plants mature in a stage.

A curve is owned by exactly one growspace and a growspace has at most one curve per stage (ADR-0046); saving a second curve for a stage the growspace already covers is refused.

| Parameter      | Type     | Required | Default | Description                                                                                 |
| :------------- | :------- | :------- | :------ | :------------------------------------------------------------------------------------------ |
| `growspace_id` | `string` | Yes      | -       | The growspace that owns the curve.                                                          |
| `name`         | `string` | Yes      | -       | Ramp curve name (e.g., "9-Week Bloom Ramp").                                                |
| `stage`        | `string` | Yes      | -       | Targeted stage (e.g., `flower`).                                                            |
| `points`       | `list`   | Yes      | -       | List of target EC boundaries per week (e.g. `[{"week": 1, "ec_min": 1.2, "ec_max": 1.5}]`). |
| `curve_id`     | `string` | No       | -       | Curve ID to update.                                                                         |

### `growspace_manager.remove_ec_ramp_curve`

Deletes an EC ramp curve.

| Parameter  | Type     | Required | Default | Description                 |
| :--------- | :------- | :------- | :------ | :-------------------------- |
| `curve_id` | `string` | Yes      | -       | EC ramp curve ID to remove. |

### `growspace_manager.save_ipm_preset`

Creates an Integrated Pest Management protocol preset.

| Parameter           | Type      | Required | Default | Description                                                         |
| :------------------ | :-------- | :------- | :------ | :------------------------------------------------------------------ |
| `name`              | `string`  | Yes      | -       | Preset protocol name (e.g., "Weekly Preventive Foliar").            |
| `type`              | `string`  | Yes      | -       | Type: `preventative`, `treatment`, `repopulation`.                  |
| `items`             | `list`    | Yes      | -       | List of pest control ingredients or actions.                        |
| `preset_id`         | `string`  | No       | -       | Overwrite target preset ID.                                         |
| `stage`             | `string`  | No       | -       | Safety restriction stage (e.g., `veg` - spray will block in bloom). |
| `min_days_in_stage` | `integer` | No       | `0`     | Days elapsed restriction.                                           |

_Example:_

```yaml
service: growspace_manager.save_ipm_preset
data:
  name: "Spider Mite Treatment"
  type: "treatment"
  items:
    - "Spinosad Spray at 10mL/gal"
    - "Deploy Phytoseiulus persimilis"
  stage: "veg"
```

### `growspace_manager.remove_ipm_preset`

Deletes an IPM protocol preset.

| Parameter   | Type     | Required | Default | Description    |
| :---------- | :------- | :------- | :------ | :------------- |
| `preset_id` | `string` | Yes      | -       | IPM preset ID. |

### `growspace_manager.apply_ipm`

Logs a physical IPM application at a growspace or specific plant coordinates.

| Parameter      | Type     | Required | Default | Description                          |
| :------------- | :------- | :------- | :------ | :----------------------------------- |
| `preset_id`    | `string` | Yes      | -       | IPM preset ID applied.               |
| `growspace_id` | `string` | No       | -       | Target growspace zone ID.            |
| `plant_ids`    | `list`   | No       | -       | Specific array of plant IDs treated. |
| `notes`        | `string` | No       | -       | Rich notes regarding observation.    |

---

## AI Assistant & Diagnostics

### `growspace_manager.ask_grow_advice`

Interrogates the Virtual Grow Master regarding environmental state or general cultivation strategies.

| Parameter      | Type      | Required | Default     | Description                                                   |
| :------------- | :-------- | :------- | :---------- | :------------------------------------------------------------ |
| `growspace_id` | `string`  | Yes      | -           | Target growspace zone ID.                                     |
| `user_query`   | `string`  | No       | -           | Question (e.g., "Why are my leaves yellowing?").              |
| `context_type` | `string`  | No       | `"general"` | Options: `general`, `diagnostic`, `optimization`, `planning`. |
| `max_length`   | `integer` | No       | `1000`      | Character ceiling for returned advice text.                   |

### `growspace_manager.strain_recommendation`

Generates a context-aware strain recommendation based on your garden history and goals.

| Parameter      | Type      | Required | Default | Description                                               |
| :------------- | :-------- | :------- | :------ | :-------------------------------------------------------- |
| `user_query`   | `string`  | No       | -       | Natural language description of what you are looking for. |
| `preferences`  | `object`  | No       | -       | Key-value pairs defining preferences.                     |
| `growspace_id` | `string`  | No       | -       | Specific growspace zone intended.                         |
| `max_length`   | `integer` | No       | `1000`  | Character ceiling for response.                           |

### `growspace_manager.trigger_vision_checkup`

Instructs your camera system to snap a photo and run deep visual diagnosis on the canopy.

| Parameter      | Type     | Required | Default | Description               |
| :------------- | :------- | :------- | :------ | :------------------------ |
| `growspace_id` | `string` | Yes      | -       | Target growspace zone ID. |

---

## Genetics & Breeding Registry

### `growspace_manager.add_seed_batch`

Registers a new seed collection batch in the inventory.

| Parameter          | Type      | Required | Default | Description                                            |
| :----------------- | :-------- | :------- | :------ | :----------------------------------------------------- |
| `strain_name`      | `string`  | Yes      | -       | Name of the strain variety.                            |
| `breeder`          | `string`  | Yes      | -       | Seed company/breeder.                                  |
| `quantity`         | `integer` | Yes      | -       | Quantity of seeds.                                     |
| `acquisition_date` | `string`  | Yes      | -       | Acquisition date (YYYY-MM-DD).                         |
| `generation`       | `string`  | Yes      | -       | Genetic stage (e.g. F1, F3, S1, IBL).                  |
| `lineage`          | `string`  | Yes      | -       | Parental cross lineage (e.g. "Sour Kush x Blueberry"). |
| `notes`            | `string`  | No       | -       | Custom notes.                                          |

### `growspace_manager.update_seed_batch`

Modifies inventory quantities or genetic parameters of an existing seed batch.

| Parameter          | Type      | Required | Default | Description                                            |
| :----------------- | :-------- | :------- | :------ | :----------------------------------------------------- |
| `batch_id`         | `string`  | Yes      | -       | Unique Seed Batch ID.                                  |
| `strain_name`      | `string`  | No       | -       | Name of the strain variety.                            |
| `breeder`          | `string`  | No       | -       | Seed company/breeder.                                  |
| `quantity`         | `integer` | No       | -       | Quantity of seeds.                                     |
| `acquisition_date` | `string`  | No       | -       | Acquisition date (YYYY-MM-DD).                         |
| `generation`       | `string`  | No       | -       | Genetic stage (e.g. F1, F3, S1, IBL).                  |
| `lineage`          | `string`  | No       | -       | Parental cross lineage (e.g. "Sour Kush x Blueberry"). |
| `notes`            | `string`  | No       | -       | Custom notes.                                          |

### `growspace_manager.log_pollination`

Registers a pollination event between two active plants to establish pedigree tracking.

| Parameter           | Type     | Required | Default | Description                            |
| :------------------ | :------- | :------- | :------ | :------------------------------------- |
| `date`              | `string` | Yes      | -       | Pollination date (YYYY-MM-DD).         |
| `donor_plant_id`    | `string` | Yes      | -       | Pollen donor plant ID (Male/Reversed). |
| `receiver_plant_id` | `string` | Yes      | -       | Seed receiver plant ID (Female).       |
| `notes`             | `string` | No       | -       | Cross details.                         |

### `growspace_manager.score_phenotype`

Evaluates a plant selection's characteristics on a 1-10 scale.

| Parameter            | Type      | Required | Default | Description                                 |
| :------------------- | :-------- | :------- | :------ | :------------------------------------------ |
| `plant_id`           | `string`  | Yes      | -       | Target plant ID.                            |
| `vigor`              | `integer` | No       | -       | Vigor score (1-10).                         |
| `internodal_spacing` | `integer` | No       | -       | Internodal density score (1-10).            |
| `terpene_intensity`  | `integer` | No       | -       | Aromatics score (1-10).                     |
| `resin`              | `integer` | No       | -       | Trichome coverage score (1-10).             |
| `mold_resistance`    | `integer` | No       | -       | Humidity tolerance / rot resistance (1-10). |
| `yield_potential`    | `integer` | No       | -       | Yield productivity potential (1-10).        |
| `keeper`             | `boolean` | No       | `false` | Tag this selection as an elite keeper.      |
| `notes`              | `string`  | No       | -       | Descriptive traits.                         |

### `growspace_manager.harvest_seeds`

Converts a documented pollination event into a finalized seed batch inventory record.

| Parameter  | Type      | Required | Default | Description                       |
| :--------- | :-------- | :------- | :------ | :-------------------------------- |
| `event_id` | `string`  | Yes      | -       | Pollination event ID.             |
| `quantity` | `integer` | Yes      | -       | Number of viable seeds harvested. |
| `notes`    | `string`  | No       | -       | Harvest information.              |

---

## Post-Harvest Drying & Curing

### `growspace_manager.log_drying_weight`

Inputs daily weight checkpoints of a drying plant to calculate moisture decay curves.

| Parameter      | Type     | Required | Default | Description                           |
| :------------- | :------- | :------- | :------ | :------------------------------------ |
| `plant_id`     | `string` | Yes      | -       | Drying plant ID.                      |
| `weight_grams` | `float`  | Yes      | -       | Current weight in grams.              |
| `date`         | `string` | No       | _Today_ | Reading date (ISO format YYYY-MM-DD). |

_Example:_

```yaml
service: growspace_manager.log_drying_weight
data:
  plant_id: "dried_plant_01"
  weight_grams: 420.5
```

### `growspace_manager.log_moisture_reading`

Records stem-moisture percentage values using material meters to pinpoint cure windows.

| Parameter          | Type     | Required | Default | Description                             |
| :----------------- | :------- | :------- | :------ | :-------------------------------------- |
| `plant_id`         | `string` | Yes      | -       | Plant ID.                               |
| `moisture_percent` | `float`  | Yes      | -       | Substrate or stem moisture (0 to 100%). |
| `date`             | `string` | No       | _Today_ | Reading date.                           |

---

## Alerts & Utility

### `growspace_manager.test_notification`

Simulates a scheduled milestone notification event to verify correct push routing.

| Parameter  | Type      | Required | Default | Description                                      |
| :--------- | :-------- | :------- | :------ | :----------------------------------------------- |
| `plant_id` | `string`  | Yes      | -       | Target plant ID.                                 |
| `stage`    | `string`  | Yes      | -       | Stage: `veg` or `flower`.                        |
| `days`     | `integer` | Yes      | -       | Simulated day index (matches specific triggers). |

### `growspace_manager.print_label`

Dispatches label files directly to a paired Niimbot bluetooth printer.

| Parameter      | Type      | Required | Default | Description                                      |
| :------------- | :-------- | :------- | :------ | :----------------------------------------------- |
| `plant_id`     | `string`  | No       | -       | Plant ID. If provided, prints individual tag.    |
| `strain`       | `string`  | No       | -       | Strain name (fallback if no plant ID).           |
| `phenotype`    | `string`  | No       | -       | Phenotype name.                                  |
| `breeder`      | `string`  | No       | -       | Breeder override.                                |
| `lineage`      | `string`  | No       | -       | Genetic parents override.                        |
| `breeder_logo` | `string`  | No       | -       | Breeder logo image URL.                          |
| `device_id`    | `string`  | No       | -       | Specific bluetooth MAC address override.         |
| `preview`      | `boolean` | No       | `false` | If `true`, returns base64 image preview in logs. |
| `base_url`     | `string`  | No       | -       | Custom base URL for the QR code.                 |

### `growspace_manager.log_training_event`

Logs physical canopy modifications (e.g. topping, lollipopping, defoliating) to build a plant timeline.

| Parameter      | Type     | Required | Default | Description                                     |
| :------------- | :------- | :------- | :------ | :---------------------------------------------- |
| `technique`    | `string` | Yes      | -       | Technique (e.g. "Topped", "LST", "Defoliated"). |
| `growspace_id` | `string` | No       | -       | Target growspace zone.                          |
| `plant_ids`    | `list`   | No       | -       | Specific treated plant ID array.                |
| `notes`        | `string` | No       | -       | Rich notes describing training.                 |

---

## Debugging & Maintenance Utilities

### `growspace_manager.debug_cleanup_legacy`

Utility to remove orphans and legacy data rows from state databases.

| Parameter   | Type      | Required | Default | Description            |
| :---------- | :-------- | :------- | :------ | :--------------------- |
| `dry_only`  | `boolean` | No       | `false` | Only purges dry logs.  |
| `cure_only` | `boolean` | No       | `false` | Only purges cure logs. |

### `growspace_manager.debug_list_growspaces`

Dumps facility configurations and active registry maps directly into the Home Assistant system log for debugging.
_No parameters required._

### `growspace_manager.debug_reset_special_growspaces`

Resets system-managed physical zones (`drying`, `curing`, `clones`, `mothers`) back to standard state definitions.

| Parameter         | Type      | Required | Default | Description                             |
| :---------------- | :-------- | :------- | :------ | :-------------------------------------- |
| `reset_dry`       | `boolean` | No       | `true`  | Re-initializes dry overview zone.       |
| `reset_cure`      | `boolean` | No       | `true`  | Re-initializes cure overview zone.      |
| `preserve_plants` | `boolean` | No       | `true`  | Preserves plant registers during reset. |
