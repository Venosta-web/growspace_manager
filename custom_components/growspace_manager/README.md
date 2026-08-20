# Growspace Manager

[![hacs_badge](https://img.shields.io/badge/HACS-Custom-41BDF5.svg?style=for-the-badge)](https://github.com/hacs/integration)
[![Quality Scale](https://img.shields.io/badge/Quality%20Scale-Gold-gold.svg?style=for-the-badge)](https://developers.home-assistant.io/docs/integration-quality-scale/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg?style=for-the-badge)](LICENSE)

**Growspace Manager** is an enterprise-grade Home Assistant custom integration designed for professional and home cultivators alike to meticulously orchestrate, monitor, and automate cannabis cultivation environments. By combining advanced sensor integration, dynamic environment profiles, a Bayesian statistical inference engine, and a context-aware AI assistant, Growspace Manager elevates home automation into a precise crop-steering and cultivation operating system.

---

## Table of Contents

1. [Core Features](#core-features)
2. [Advanced Capabilities](#advanced-capabilities)
   - [Smart Irrigation & Crop Steering](#smart-irrigation--crop-steering)
   - [Environmental VPD Control & Mold Risk Logic](#environmental-vpd-control--mold-risk-logic)
   - [AI Diagnostics & Vision Checkup Engine](#ai-diagnostics--vision-checkup-engine)
   - [Genetics, Breeding & Phenotype Scoring](#genetics-breeding--phenotype-scoring)
   - [Post-Harvest Drying & Curing Metrics](#post-harvest-drying--curing-metrics)
   - [Integrated Pest Management (IPM) & Nutrients](#integrated-pest-management-ipm--nutrients)
   - [QR Label Printing](#qr-label-printing)
3. [Installation Walkthrough](#installation-walkthrough)
4. [Step-by-Step Configuration Guide](#step-by-step-configuration-guide)
5. [Exhaustive Service API Reference](#exhaustive-service-api-reference)
6. [Generated Entities Directory](#generated-entities-directory)
7. [Real-World Automation Examples](#real-world-automation-examples)
8. [Troubleshooting & Diagnostics](#troubleshooting--diagnostics)

---

## Core Features

- **Detailed Plant Tracking**: Track individual plants from seedling/clone to harvest and final cure, documenting their growth stages, strains, phenotypes, grid positions, and health history.
- **Visual Grid Layouts**: Define multi-row and multi-column grid layouts for your growspaces. Interact with your facility visually via the companion [Lovelace Growspace Card](https://github.com/Venosta-web/lovelace-growspace-manager-card).
- **Smart Irrigation & Crop Steering**: Set VWC targets, trigger automatic pump and drainage controls, and switch between generative and vegetative watering profiles.
- **Active Environment Control**: Automate dehumidifiers and HVAC devices using day/night dynamic VPD and relative humidity (RH) stage-specific targets.
- **Bayesian Environmental Analytics**: Leverage a state-of-the-art Bayesian inference model to detect plant stress, mold risks, and optimal environment status before physical symptoms manifest.
- **Genetics & Breeding Registry**: Catalog seed batches, log crosses, track parentage (donor/receiver), and score phenotypes to preserve keeper mother plants.
- **Drying & Curing Analytics**: Track weight loss curves and stem-moisture decay during drying, automatically alerting you when the **Cure-Ready Threshold** is achieved.
- **Integrated Pest Management (IPM) & Nutrition**: Schedule, track, and log preventative and reactive IPM/feeding cycles with stage-specific presets.
- **Niimbot Label Printing**: Direct Bluetooth integration to print QR-enabled plant tags containing strains, breeder logos, genetic lineage, and lifecycle dates.
- **Interactive AI Assistant**: Call on the Virtual Grow Master to analyze real-time sensors, diagnose environmental issues, and suggest ideal strain matches.

---

## Advanced Capabilities

### Smart Irrigation & Crop Steering

Growspace Manager implements professional **Crop Steering** principles by adjusting watering frequency and volume to influence plant behavior:

- **Vegetative Steering**: Encourages structural biomass, root growth, and node density. It employs a higher frequency of smaller irrigation events (shots) during the day, maintaining higher Volumetric Water Content (VWC) in the substrate and keeping drybacks small (e.g., under 8 VWC percentage points; a 55% -> 48% drop is a 7% dryback).
- **Generative Steering**: Signals the plant to focus energy on reproductive flower and resin production. It utilizes fewer, larger watering events with a significant overnight dryback (e.g., more than 15 VWC percentage points), prompting slight osmotic stress that increases flower formation.
- **Balanced Steering**: A middle-ground maintenance profile designed for transition stages or stable mother environments.
- **Runoff & Drainage Control**: Link runoff sensors and a drain pump. The integration monitors feed EC versus drain EC to calculate salt buildup, triggers the drain pump automatically post-irrigation, and alerts you if runoff volume drifts from target percentages.

### Environmental VPD Control & Mold Risk Logic

Unlike simple threshold sensors, Growspace Manager orchestrates active climate control:

- **VPD Target Ramps**: Automatically computes VPD targets based on the current lifecycle stage (e.g., Veg: 0.8–1.1 kPa, Flower: 1.2–1.6 kPa) and adapts targets dynamically when lights transition between day and night cycles.
- **Day/Night Hysteresis**: Prevents HVAC short-cycling by applying smart buffer margins and recognizing light status.
- **Active Mold Risk Fan Control**: Incorporates relative humidity, canopy temperature, dew point, and circulation fan telemetry. If air circulation is stagnant and humidity spikes during the dark period, the Bayesian engine flags a high mold risk and triggers circulation fans or exhaust dampers to protect flowers.

### AI Diagnostics & Vision Checkup Engine

Combine computer vision with LLM smarts to secure your facility:

- **Vision Checkups**: Trigger a high-resolution camera snapshot when lights are on, sending the image to an AI vision agent to inspect the canopy for drooping leaves (under/over-watering), pest damage, or chlorosis (nutrient deficiency).
- **Context-Aware Advice**: The Virtual Grow Master integrates real-time ambient parameters (canopy VPD, substrate temp, CO2 ppm) and plant stage history to deliver hyper-specific advice compared to generic LLM chatbots.

### Genetics, Breeding & Phenotype Scoring

Never lose track of your breeding projects or elite selections:

- **Breeding Registry**: Track seed batches, acquisition dates, generations (F1, F2, S1, IBL), and cross-parentage.
- **Pollination Logs**: Document donor (pollen source) and receiver (seed-bearing) plant IDs, along with fertilization dates, which automatically schedules seed harvest tasks.
- **Phenotype Scoring**: Evaluate selections using a standardized 1–10 scoring metric across:
  - _Vigor_: Growth rate and branching robustness.
  - _Internodal Spacing_: Density of budding sites.
  - _Terpene Intensity_: Olfactory intensity and complexity.
  - _Resin Production_: Trichome density and quality.
  - _Mold Resistance_: Natural resilience to environmental stress.
- **Keeper Flag**: Flag top-scoring phenotypes to easily trace and organize mother and clone groups.

### Post-Harvest Drying & Curing Metrics

Harvesting is only half the battle. Manage drying and curing with scientific precision:

- **Weight Decay Curves**: Log daily weights during the drying stage to chart moisture loss over time. The integration computes the weight reduction percent (e.g., targeting a 60-65% drop from wet weight).
- **Stem Moisture Meter Logs**: Input readings from wood/material moisture meters.
- **Cure-Ready Threshold**: The system combines weight decay velocity and moisture readings. When the decay curve plateaus in the safe zone (typically 10-12% moisture), it triggers a notification that the harvest is ready for curing, protecting your terpenes from over-drying.

### Integrated Pest Management (IPM) & Nutrients

Establish strict facility protocols with scheduled presets:

- **Nutrient Presets**: Save complex chemical and organic feeding recipes. Schedule feed cycles by days in veg/flower to automatically send alerts or update automated doser parameters.
- **IPM Presets**: Save recipes for foliar sprays (e.g., Neem oil, Bacillus amyloliquefaciens) or predatory insect releases. Set maximum stage restrictions (e.g., never apply foliar sprays after Week 3 of Flower) to prevent bud contamination.

### QR Label Printing

Keep your physical garden perfectly synced with your digital records:

- **Niimbot Integration**: Connects via Bluetooth to thermal label printers (e.g., Niimbot D11/D110/B21).
- **Smart Labels**: Prints barcodes or QR codes linking directly to the plant sensor entity in Home Assistant. Includes the strain name, phenotype, breeder logo, parental lineage, and key dates.

---

## Installation Walkthrough

The Growspace Manager system requires the main integration and the companion custom Lovelace card.

### Step 1: Install the Lovelace Card via HACS

1.  Navigate to **HACS** > **Frontend** in Home Assistant.
2.  Click the three vertical dots in the top-right corner and select **Custom repositories**.
3.  Enter the URL: `https://github.com/Venosta-web/lovelace-growspace-manager-card`
4.  Select **Lovelace** as the category and click **Add**.
5.  Search for `Growspace Manager Card` in HACS and click **Download / Install**.

### Step 2: Install the Integration via HACS

1.  Navigate to **HACS** > **Integrations** in Home Assistant.
2.  Click the three vertical dots in the top-right corner and select **Custom repositories**.
3.  Enter the URL: `https://github.com/Venosta-web/growspace_manager`
4.  Select **Integration** as the category and click **Add**.
5.  Search for `Growspace Manager` in HACS and click **Download / Install**.
6.  **Restart Home Assistant** when prompted.

---

## Step-by-Step Configuration Guide

### Step 1: Initialize the Integration

1.  Navigate to **Settings** > **Devices & Services** in Home Assistant.
2.  Click **+ Add Integration** in the bottom right.
3.  Search for **Growspace Manager** and click to install.
4.  Once initialized, you will see a Growspace Manager integration card.

### Step 2: Define Your Growspaces

1.  Click **Configure** on the Growspace Manager card.
2.  Select **Manage Growspaces** from the menu and click **Submit**.
3.  Choose **Add Growspace**.
4.  Configure the details:
    - **Name**: A descriptive name (e.g., "Veg Tent", "Flower Room").
    - **Rows & Plants Per Row**: Sets up your layout grid dimensions (e.g., 2 rows, 4 plants per row).
    - **Notification Target**: Specify your notification service (e.g., `notify.mobile_app_my_phone`).
5.  Click **Submit** to create. Logical special spaces (`mothers`, `clones`, `drying`, `curing`) are automatically managed or can be configured.

### Step 3: Set Up Environmental Sensors and Climate Control

1.  In the integration **Configure** menu, select **Configure Growspace Environment** and click **Submit**.
2.  Select your target growspace.
3.  Configure sensor associations:
    - **Temperature / Humidity / VPD Sensors**: Bind your physical DHT22, RuuviTag, or Ecowitt sensor entities.
    - **Light Sensor**: Link a light switch or photodiode sensor. This enables Day/Night environmental analysis.
    - **Circulation Fan / Exhaust Fan / Humidifier**: Bind active switches or fan controllers.
    - **Dehumidifier Entity**: Bind your dehumidifier switch.
    - **Control Dehumidifier**: Toggle `true` to let the integration automatically switch the dehumidifier on/off based on live VPD targets.
4.  Input Stage-Specific targets (RH or VPD values for Veg, Early Flower, Mid Flower, Late Flower) and click **Submit**.

### Step 4: Bind Irrigation & Drainage Hardware

1.  Select **Configure Irrigation** from the configuration menu.
2.  Select your growspace.
3.  Link your **Irrigation Pump** (switch) and **Drain Pump** (switch) entities.
4.  Define default watering and drain run durations (in seconds). Click **Submit**.

### Step 5: Configure AI Settings

1.  Select **Configure AI Settings** from the configuration menu.
2.  Check **Enable AI Features**.
3.  Choose your configured Home Assistant **Conversation Agent** (e.g., OpenAI, Google Gemini).
4.  Click **Submit**.

---

## Exhaustive Service API Reference

All services can be invoked from automations, Lovelace buttons, or custom scripts.

### Database & Library Management

#### `growspace_manager.export_strain_library`

Exports the entire strain catalog including descriptions, breeder logos, and gallery images to a single, easily portable ZIP archive.
_No parameters required._

#### `growspace_manager.import_strain_library`

Imports a strain library from a previously exported ZIP file.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `file_path` | `string` | No | - | Full server path to the ZIP archive. |
| `zip_base64` | `string` | No | - | Base64-encoded ZIP file payload (used for direct frontend uploads). |
| `replace` | `boolean` | No | `false` | If `true`, completely replaces existing catalog; otherwise merges. |

_Example:_

```yaml
service: growspace_manager.import_strain_library
data:
  file_path: "/home/homeassistant/.homeassistant/share/strain_library_backup.zip"
  replace: true
```

#### `growspace_manager.clear_strain_library`

Completely resets the local strain catalog database, removing all strain, phenotype, and breeder records.
_No parameters required._

#### `growspace_manager.get_strain_library`

Fetches and returns the full strain library database (primarily utilized by frontend dashboards).
_No parameters required._

#### `growspace_manager.add_strain`

Directly inserts a new strain variety with detailed genetic metadata into the library.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `strain` | `string` | Yes | - | Name of the strain (e.g., "Gorilla Glue #4"). |
| `phenotype` | `string` | No | - | Phenotype description or identifier (e.g., "Sour Cut"). |
| `breeder` | `string` | No | - | Name of the breeder or seed company. |
| `type` | `string` | No | - | Strain classification (e.g., "Indica", "Sativa Hybrid"). |
| `lineage` | `string` | No | - | Parent strains (e.g., "Sour Dubb x Chem Sis"). |
| `sex` | `string` | No | - | Genetic sex (e.g., "Feminized", "Regular", "Autoflower"). |
| `flower_days_min` | `integer` | No | - | Minimum expected flowering time (days). |
| `flower_days_max` | `integer` | No | - | Maximum expected flowering time (days). |
| `sativa_percentage` | `integer` | No | - | Sativa ratio (0 to 100). |
| `indica_percentage` | `integer` | No | - | Indica ratio (0 to 100). |
| `breeder_logo` | `string` | No | - | URL or local path to breeder's logo image. |
| `description` | `string` | No | - | Rich description of characteristics, flavor profile, and aromas. |
| `image_base64` | `string` | No | - | Base64-encoded image string for the main strain photo. |
| `image_path` | `string` | No | - | Local server path to the main strain photo. |
| `image_crop_meta` | `object` | No | - | Crop coordinates and metadata for the main image. |
| `images` | `list` | No | - | Gallery image configurations, list of objects: `{path, crop_meta, is_thumbnail}`. |

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

#### `growspace_manager.update_strain_meta`

Updates genetic metadata, logs, or photos for an existing strain catalog entry.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `strain` | `string` | Yes | - | Name of the strain to modify. |
| `phenotype` | `string` | No | - | Phenotype matching key. |
| `breeder` | `string` | No | - | Name of the breeder or seed company. |
| `type` | `string` | No | - | Strain classification (e.g., "Indica", "Sativa Hybrid"). |
| `lineage` | `string` | No | - | Parent strains (e.g., "Sour Dubb x Chem Sis"). |
| `sex` | `string` | No | - | Genetic sex (e.g., "Feminized", "Regular", "Autoflower"). |
| `flower_days_min` | `integer` | No | - | Minimum expected flowering time (days). |
| `flower_days_max` | `integer` | No | - | Maximum expected flowering time (days). |
| `description` | `string` | No | - | Rich description of characteristics, flavor profile, and aromas. |
| `image_base64` | `string` | No | - | Base64-encoded image string for the main strain photo. |
| `image_path` | `string` | No | - | Local server path to the main strain photo. |
| `image_crop_meta` | `object` | No | - | Crop coordinates and metadata for the main image. |
| `images` | `list` | No | - | Gallery image configurations, list of objects: `{path, crop_meta, is_thumbnail}`. |
| `sativa_percentage` | `integer` | No | - | Sativa ratio (0 to 100). |
| `indica_percentage` | `integer` | No | - | Indica ratio (0 to 100). |
| `breeder_logo` | `string` | No | - | URL or local path to breeder's logo image. |

#### `growspace_manager.remove_strain`

Deletes a strain record and all associated images from the catalog.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `strain` | `string` | Yes | - | Name of the strain to remove. |
| `phenotype` | `string` | No | - | Specific phenotype to remove. |

---

### Facility & Growspace Management

#### `growspace_manager.add_growspace`

Registers a new physical growspace zone.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `name` | `string` | Yes | - | Name of the growspace zone. |
| `rows` | `integer` | Yes | - | Number of rows in grid (1-20). |
| `plants_per_row` | `integer` | Yes | - | Number of columns in grid (1-20). |
| `notification_target` | `string` | No | - | Mobile notification service name. |

#### `growspace_manager.update_growspace`

Updates configuration of an existing growspace.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace unique ID. |
| `name` | `string` | No | - | New descriptive name. |
| `rows` | `integer` | No | - | New row grid count. |
| `plants_per_row` | `integer` | No | - | New columns per row count. |
| `notification_target` | `string` | No | - | Updated notification target. |

_Example:_

```yaml
service: growspace_manager.update_growspace
data:
  growspace_id: "room_1"
  notification_target: "notify.mobile_app_ipad"
```

#### `growspace_manager.remove_growspace`

Deletes a growspace zone and permanently un-registers all plants housed inside it.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace ID to delete. |

#### `growspace_manager.analyze_all_growspaces`

Triggers an automated evaluation of all facility zones, producing a detailed markdown summary of environment statuses, plant health indicators, and recommendations.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `max_length` | `integer` | No | `1000` | Max character limit for the generated facility report. |

---

### Plant & Lifecycle Stage Tracking

#### `growspace_manager.add_plant`

Places a single plant into a specific coordinate on the growspace grid.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace ID. |
| `strain` | `string` | Yes | - | Strain name. |
| `row` | `integer` | Yes | - | Grid row coordinate (starts at 1). |
| `col` | `integer` | Yes | - | Grid column coordinate (starts at 1). |
| `phenotype` | `string` | No | - | Phenotype description. |
| `seedling_start` | `date` | No | - | Seedling stage start date (YYYY-MM-DD). |
| `mother_start` | `date` | No | - | Mother stage start date. |
| `clone_start` | `date` | No | - | Clone stage start. |
| `veg_start` | `date` | No | - | Veg stage start date. |
| `flower_start` | `date` | No | - | Flower stage start date. |
| `dry_start` | `date` | No | - | Dry stage start date. |
| `cure_start` | `date` | No | - | Cure stage start date. |
| `notes` | `string` | No | - | Rich notes about plant history. |

#### `growspace_manager.add_plants`

Batch-inserts multiple plants of the same variety into consecutive empty spots in a growspace.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace ID. |
| `strain` | `string` | Yes | - | Strain name. |
| `amount` | `integer` | Yes | - | Quantity of plants to insert. |
| `start_number` | `integer` | No | `1` | Suffix numbering starting index (e.g. "Chem Dog #1", "Chem Dog #2"). |
| `seedling_start` | `date` | No | - | Seedling stage start date (YYYY-MM-DD). |
| `mother_start` | `date` | No | - | Mother stage start date (YYYY-MM-DD). |
| `clone_start` | `date` | No | - | Clone stage start date (YYYY-MM-DD). |
| `veg_start` | `date` | No | - | Vegetative stage start date (YYYY-MM-DD). |
| `flower_start` | `date` | No | - | Flowering stage start date (YYYY-MM-DD). |
| `dry_start` | `date` | No | - | Drying stage start date (YYYY-MM-DD). |
| `cure_start` | `date` | No | - | Curing stage start date (YYYY-MM-DD). |

#### `growspace_manager.update_plant`

Edits attributes, stages, or coordinate locations of a plant.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Target plant ID. |
| `growspace_id` | `string` | No | - | Target growspace ID. |
| `strain` | `string` | No | - | New strain name. |
| `phenotype` | `string` | No | - | Phenotype. |
| `position` | `string` | No | - | Grid position string (e.g. "A1", "B2"). |
| `row` | `integer` | No | - | New grid row. |
| `col` | `integer` | No | - | New grid column. |
| `seedling_start` | `date` | No | - | Seedling stage start date (YYYY-MM-DD). |
| `mother_start` | `date` | No | - | Mother stage start date (YYYY-MM-DD). |
| `clone_start` | `date` | No | - | Clone stage start date (YYYY-MM-DD). |
| `veg_start` | `date` | No | - | Vegetative stage start date (YYYY-MM-DD). |
| `flower_start` | `date` | No | - | Flowering stage start date (YYYY-MM-DD). |
| `dry_start` | `date` | No | - | Drying stage start date (YYYY-MM-DD). |
| `cure_start` | `date` | No | - | Curing stage start date (YYYY-MM-DD). |
| `stage` | `string` | No | - | Directly set stage (`seedling`, `mother`, `clone`, `veg`, `flower`, `dry`, `cure`). |
| `notes` | `string` | No | - | Update notes. |

#### `growspace_manager.remove_plant`

Deletes a plant and removes its sensor entity.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Plant ID to remove. |

#### `growspace_manager.move_plant`

Relocates a plant to new coordinates. If another plant occupies the target spot, their positions switch.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Target plant ID. |
| `new_row` | `integer` | Yes | - | Target grid row coordinate. |
| `new_col` | `integer` | Yes | - | Target grid column coordinate. |

#### `growspace_manager.switch_plants`

Explicitly swaps the grid positions of two plants.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant1_id` | `string` | Yes | - | First plant ID. |
| `plant2_id` | `string` | Yes | - | Second plant ID. |

#### `growspace_manager.transition_plant_stage`

Transitions a plant to a new growth phase (e.g. flipping from Vegetative to Flowering).
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Plant ID. |
| `new_stage` | `string` | Yes | - | Stage: `seedling`, `mother`, `clone`, `veg`, `flower`, `dry`, `cure`. |
| `transition_date`| `date` | No | _Today_ | Optional date transition occurred. |

#### `growspace_manager.harvest_plant`

Harvests a plant, records its metrics, and auto-routes it to the **Drying** growspace.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Plant ID. |
| `target_growspace_id`| `string`| No | _drying_ | Destination growspace zone. |
| `transition_date`| `date` | No | _Today_ | Date of harvest. |
| `wet_weight` | `float` | No | - | Wet weight at harvest in grams. |
| `dry_weight` | `float` | No | - | Final cured dry weight in grams. |
| `trim_weight` | `float` | No | - | Sugar leaf and trim weight in grams. |
| `thc_percentage`| `float` | No | - | THC lab test score (0-100%). |
| `cbd_percentage`| `float` | No | - | CBD lab test score (0-100%). |
| `terpene_profile`| `string`| No | - | Rich description of terpenes (e.g., "Limonene dominant"). |

#### `growspace_manager.take_clone`

Creates multiple new clone seedlings from a mother plant and places them into the clones growspace.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `mother_plant_id`| `string` | Yes | - | Mother donor plant ID. |
| `target_growspace_id`|`string`| No | _clones_ | Destination clones zone. |
| `transition_date`| `date` | No | _Today_ | Date clones were cut. |
| `num_clones` | `integer` | No | `1` | Quantity of clone cuttings taken. |

#### `growspace_manager.move_clone`

Relocates a rooted clone to a vegetative or mother growspace grid coordinate.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Clone plant ID. |
| `target_growspace_id`|`string`| Yes | - | Target veg/mother growspace. |
| `transition_date`| `date` | No | _Today_ | Date of transplanting. |

#### `growspace_manager.set_visual_tag`

Attaches or clears a visual identification label (e.g. colored ties, nursery tags) to track physical plants easily.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Target plant ID. |
| `visual_tag` | `string` | No | - | Tag label (e.g., "Orange Clip"). Omit to clear. |

#### `growspace_manager.reset_plant_last_watered`

_Warning: E2E and Test Fixture Use Only._ Manually clears a plant's `last_watered` timestamp.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Plant ID to modify. |

#### `growspace_manager.batch_action`

Executes a synchronized action across a list of plants.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `entity_ids` | `list` | Yes | - | Array of plant IDs. |
| `action` | `string` | Yes | - | Action: `transition`, `harvest`, `remove`, `take_clone`. |
| `data` | `object` | No | - | Dictionary parameters corresponding to the action chosen. |

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

### Environmental & HVAC Controls

#### `growspace_manager.configure_environment`

Binds physical environmental monitors, light schedules, and active climate controls to a growspace zone.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace zone ID. |
| `temperature_sensor`| `string`| Yes | - | Ambient temperature sensor entity. |
| `humidity_sensor`| `string`| Yes | - | Ambient relative humidity sensor entity. |
| `vpd_sensor` | `string` | Yes | - | Vapor Pressure Deficit sensor entity (kPa). |
| `co2_sensor` | `string` | No | - | Carbon Dioxide sensor entity (ppm). |
| `circulation_fan`| `string` | No | - | Circulation fan switch/fan entity. |
| `exhaust_entity` | `string` | No | - | Exhaust fan/damper switch/fan entity. |
| `humidifier_entity`|`string` | No | - | Humidifier controller or switch. |
| `dehumidifier_entity`|`string`| No | - | Dehumidifier controller or switch. |
| `light_sensor` | `string` | No | - | Light level sensor or light switch status entity. |
| `soil_moisture_sensor`|`string`| No | - | Substrate VWC soil moisture sensor entity. |
| `stress_threshold`|`float` | No | `0.70` | Bayesian stress alert confidence threshold (0.50-0.95). |
| `mold_threshold` | `float` | No | `0.75` | Bayesian mold alert confidence threshold (0.50-0.95). |
| `control_dehumidifier`|`boolean`|No| `false`| Enable active automated target steering of the dehumidifier. |
| `sensor_groups` | `object` | No | - | Configuration mapping for multidimensional heatmaps. |
| `sensor_coordinates`|`object`| No | - | Coordinates map for multi-sensor configurations. |
| `irrigation_tanks`| `object` | No | - | Irrigation nutrient tank volume & EC configurations. |

#### `growspace_manager.remove_environment`

Permanently disconnects all climate monitors and automated climate steering controllers from a growspace.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace zone ID. |

#### `growspace_manager.set_dehumidifier_control`

Toggles active dynamic climate steering on/off.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace ID. |
| `enabled` | `boolean`| Yes | - | Whether active control is enabled. |

---

### Smart Irrigation & Steering

#### `growspace_manager.set_irrigation_settings`

Sets the basic plumbing hardware profiles and default cycle times for simple timer waterings.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace zone ID. |
| `irrigation_pump_entity`|`string`| No | - | Feed pump switch entity ID. |
| `drain_pump_entity`| `string` | No | - | Drainage pump switch entity ID. |
| `irrigation_duration`|`integer`| No | - | Standard duration to run feed pump (seconds). |
| `drain_duration` | `integer`| No | - | Standard duration to run drain pump (seconds). |

#### `growspace_manager.set_irrigation_strategy`

Configures high-level Volumetric Water Content (VWC) crop-steering automation schedules.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace zone ID. |
| `enabled` | `boolean`| No | `true` | Toggles strategy-guided pump control. |
| `lights_on_time` | `string` | No | "06:00:00"| Time of day lights switch on (HH:MM:SS format). |
| `p0_duration_minutes`|`integer`|No | `120` | Root warmup time post-sunrise before first irrigation. |
| `p2_stop_before_lights_off_minutes`|`integer`|No| `120`| Stop irrigating before sunset to allow overnight dryback. |
| `target_vwc_percent`|`float` | No | `65.0` | Target VWC percentage during Phase 1 (irrigation ramp). |
| `maintenance_dryback_percent`|`float`|No| `5.0`| Target dryback drop (absolute VWC percentage points below target) before triggering single maintenance shots. |
| `shot_duration_seconds`|`integer`|No | `30` | Duration of each individual steering shot (seconds). |
| `shot_interval_minutes`|`integer`|No | `15` | Minimum rest interval between steering shots. |

#### `growspace_manager.add_irrigation_time`

Manually schedules a daily fixed-time watering event.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace zone ID. |
| `time` | `string` | Yes | - | Watering trigger time (HH:MM:SS). |
| `duration` | `integer`| No | - | Run duration override (seconds). |

#### `growspace_manager.remove_irrigation_time`

Removes a specific scheduled fixed watering time.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace zone ID. |
| `time` | `string` | Yes | - | Time to delete (HH:MM:SS). |

#### `growspace_manager.reset_water_tracking`

Resets the cumulative water consumption counter (liters/gallons) to zero.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace zone ID. |

---

### Drainage & Runoff Monitoring

#### `growspace_manager.add_drain_time`

Schedules a fixed time to trigger the drainage pump manually (useful for flushing).
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace zone ID. |
| `time` | `string` | Yes | - | Trigger time (HH:MM:SS). |
| `duration` | `integer`| No | - | Pump run duration override (seconds). |

#### `growspace_manager.remove_drain_time`

Removes a scheduled drain time.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace zone. |
| `time` | `string` | Yes | - | Time to delete (HH:MM:SS). |

#### `growspace_manager.log_drain_reading`

Manually documents runoff chemistry and volumes to track root-zone dynamics.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace ID. |
| `feed_ec` | `float` | Yes | - | Electrical conductivity of the feed input water (mS/cm). |
| `drain_ec` | `float` | Yes | - | Electrical conductivity of the runoff/drain output (mS/cm). |
| `drain_volume_ml`| `integer`| No | - | Total volume of runoff collected (mL). |
| `feed_volume_ml` | `integer`| No | - | Total volume of feed solution applied (mL). |

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

#### `growspace_manager.configure_drain_monitoring`

Sets alarms and tracking guidelines for runoff performance.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Growspace zone ID. |
| `enabled` | `boolean`| No | `true` | Toggle active runoff monitoring alerts. |
| `max_ec_delta` | `float` | No | `1.0` | Maximum delta (Drain EC - Feed EC) allowed before salt buildup alert (mS/cm). |
| `target_runoff_percent`|`integer`| No | `20` | Target runoff percentage (drainage volume / feed volume \* 100). |

---

### Nutrition & Integrated Pest Management

#### `growspace_manager.save_nutrient_preset`

Schedules a nutrient feeding recipe and binds it to a plant stage.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `name` | `string` | Yes | - | Name of the feeding preset (e.g. "Late Bloom Recipe"). |
| `nutrients` | `object` | Yes | - | Dictionary mapping nutrients and volumes (e.g., `{"Base A": 5.0, "Base B": 5.0, "Bloom Boost": 2.5}`). |
| `preset_id` | `string` | No | - | Preset ID to overwrite. |
| `stage` | `string` | No | - | Stage constraint: `seedling`, `mother`, `clone`, `veg`, `flower`. |
| `min_days_in_stage`|`integer`| No | `0` | Minimum growth phase days required before recommending this recipe. |

#### `growspace_manager.remove_nutrient_preset`

Deletes a feeding recipe.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `preset_id` | `string` | Yes | - | Nutrient preset ID to delete. |

#### `growspace_manager.save_ec_ramp_curve`

Saves an Electrical Conductivity ramp schedule to guide automate dosers as plants mature in a stage.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `name` | `string` | Yes | - | Ramp curve name (e.g., "9-Week Bloom Ramp"). |
| `stage` | `string` | Yes | - | Targeted stage (e.g., `flower`). |
| `points` | `list` | Yes | - | List of target EC boundaries per week (e.g. `[{"week": 1, "ec_min": 1.2, "ec_max": 1.5}]`). |
| `curve_id` | `string` | No | - | Curve ID to update. |

#### `growspace_manager.remove_ec_ramp_curve`

Deletes an EC ramp curve.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `curve_id` | `string` | Yes | - | EC ramp curve ID to remove. |

#### `growspace_manager.save_ipm_preset`

Creates an Integrated Pest Management protocol preset.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `name` | `string` | Yes | - | Preset protocol name (e.g., "Weekly Preventive Foliar"). |
| `type` | `string` | Yes | - | Type: `preventative`, `treatment`, `repopulation`. |
| `items` | `list` | Yes | - | List of pest control ingredients or actions. |
| `preset_id` | `string` | No | - | Overwrite target preset ID. |
| `stage` | `string` | No | - | Safety restriction stage (e.g., `veg` - spray will block in bloom). |
| `min_days_in_stage`|`integer`| No | `0` | Days elapsed restriction. |

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

#### `growspace_manager.remove_ipm_preset`

Deletes an IPM protocol preset.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `preset_id` | `string` | Yes | - | IPM preset ID. |

#### `growspace_manager.apply_ipm`

Logs a physical IPM application at a growspace or specific plant coordinates.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `preset_id` | `string` | Yes | - | IPM preset ID applied. |
| `growspace_id` | `string` | No | - | Target growspace zone ID. |
| `plant_ids` | `list` | No | - | Specific array of plant IDs treated. |
| `notes` | `string` | No | - | Rich notes regarding observation. |

---

### AI Assistant & Diagnostics

#### `growspace_manager.ask_grow_advice`

Interrogates the Virtual Grow Master regarding environmental state or general cultivation strategies.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace zone ID. |
| `user_query` | `string` | No | - | Question (e.g., "Why are my leaves yellowing?"). |
| `context_type` | `string` | No | `"general"` | Options: `general`, `diagnostic`, `optimization`, `planning`. |
| `max_length` | `integer` | No | `1000` | Character ceiling for returned advice text. |

#### `growspace_manager.strain_recommendation`

Generates a context-aware strain recommendation based on your garden history and goals.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `user_query` | `string` | No | - | Natural language description of what you are looking for. |
| `preferences` | `object` | No | - | Key-value pairs defining preferences. |
| `growspace_id` | `string` | No | - | Specific growspace zone intended. |
| `max_length` | `integer` | No | `1000` | Character ceiling for response. |

#### `growspace_manager.trigger_vision_checkup`

Instructs your camera system to snap a photo and run deep visual diagnosis on the canopy.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `growspace_id` | `string` | Yes | - | Target growspace zone ID. |

---

### Genetics & Breeding Registry

#### `growspace_manager.add_seed_batch`

Registers a new seed collection batch in the inventory.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `strain_name` | `string` | Yes | - | Name of the strain variety. |
| `breeder` | `string` | Yes | - | Seed company/breeder. |
| `quantity` | `integer` | Yes | - | Quantity of seeds. |
| `acquisition_date`|`string`| Yes | - | Acquisition date (YYYY-MM-DD). |
| `generation` | `string` | Yes | - | Genetic stage (e.g. F1, F3, S1, IBL). |
| `lineage` | `string` | Yes | - | Parental cross lineage (e.g. "Sour Kush x Blueberry"). |
| `notes` | `string` | No | - | Custom notes. |

#### `growspace_manager.update_seed_batch`

Modifies inventory quantities or genetic parameters of an existing seed batch.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `batch_id` | `string` | Yes | - | Unique Seed Batch ID. |
| `strain_name` | `string` | No | - | Name of the strain variety. |
| `breeder` | `string` | No | - | Seed company/breeder. |
| `quantity` | `integer` | No | - | Quantity of seeds. |
| `acquisition_date`| `string` | No | - | Acquisition date (YYYY-MM-DD). |
| `generation` | `string` | No | - | Genetic stage (e.g. F1, F3, S1, IBL). |
| `lineage` | `string` | No | - | Parental cross lineage (e.g. "Sour Kush x Blueberry"). |
| `notes` | `string` | No | - | Custom notes. |

#### `growspace_manager.log_pollination`

Registers a pollination event between two active plants to establish pedigree tracking.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `date` | `string` | Yes | - | Pollination date (YYYY-MM-DD). |
| `donor_plant_id` | `string` | Yes | - | Pollen donor plant ID (Male/Reversed). |
| `receiver_plant_id`|`string` | Yes | - | Seed receiver plant ID (Female). |
| `notes` | `string` | No | - | Cross details. |

#### `growspace_manager.score_phenotype`

Evaluates a plant selections characteristics on a 1-10 scale.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Target plant ID. |
| `vigor` | `integer` | No | - | Vigor score (1-10). |
| `internodal_spacing`|`integer`|No | - | Internodal density score (1-10). |
| `terpene_intensity`|`integer`| No | - | Aromatics score (1-10). |
| `resin` | `integer` | No | - | Trichome coverage score (1-10). |
| `mold_resistance`|`integer`| No | - | Humidity tolerance / rot resistance (1-10). |
| `yield_potential`|`integer` | No | - | Yield productivity potential (1-10). |
| `keeper` | `boolean`| No | `false` | Tag this selection as an elite keeper. |
| `notes` | `string` | No | - | Descriptive traits. |

#### `growspace_manager.harvest_seeds`

Converts a documented pollination event into a finalized seed batch inventory record.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `event_id` | `string` | Yes | - | Pollination event ID. |
| `quantity` | `integer` | Yes | - | Number of viable seeds harvested. |
| `notes` | `string` | No | - | Harvest information. |

---

### Post-Harvest Drying & Curing

#### `growspace_manager.log_drying_weight`

Inputs daily weight checkpoints of a drying plant to calculate moisture decay curves.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Drying plant ID. |
| `weight_grams` | `float` | Yes | - | Current weight in grams. |
| `date` | `string` | No | _Today_ | Reading date (ISO format YYYY-MM-DD). |

_Example:_

```yaml
service: growspace_manager.log_drying_weight
data:
  plant_id: "dried_plant_01"
  weight_grams: 420.5
```

#### `growspace_manager.log_moisture_reading`

Records stem-moisture percentage values using material meters to pinpoint cure windows.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Plant ID. |
| `moisture_percent`|`float` | Yes | - | Substrate or stem moisture (0 to 100%). |
| `date` | `string` | No | _Today_ | Reading date. |

---

### Alerts & Utility

#### `growspace_manager.test_notification`

Simulates a scheduled milestone notification event to verify correct push routing.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | Yes | - | Target plant ID. |
| `stage` | `string` | Yes | - | Stage: `veg` or `flower`. |
| `days` | `integer` | Yes | - | Simulated day index (matches specific triggers). |

#### `growspace_manager.print_label`

Dispatches label files directly to a paired Niimbot bluetooth printer.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `plant_id` | `string` | No | - | Plant ID. If provided, prints individual tag. |
| `strain` | `string` | No | - | Strain name (fallback if no plant ID). |
| `phenotype` | `string` | No | - | Phenotype name. |
| `breeder` | `string` | No | - | Breeder override. |
| `lineage` | `string` | No | - | Genetic parents override. |
| `breeder_logo` | `string` | No | - | Breeder logo image URL. |
| `device_id` | `string` | No | - | Specific bluetooth MAC address override. |
| `preview` | `boolean`| No | `false` | If `true`, returns base64 image preview in logs. |
| `base_url` | `string` | No | - | Custom base URL for the QR code. |

#### `growspace_manager.log_training_event`

Logs physical canopy modifications (e.g. topping, lollipopping, defoliating) to build a plant timeline.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `technique` | `string` | Yes | - | Technique (e.g. "Topped", "LST", "Defoliated"). |
| `growspace_id` | `string` | No | - | Target growspace zone. |
| `plant_ids` | `list` | No | - | Specific treated plant ID array. |
| `notes` | `string` | No | - | Rich notes describing training. |

---

### Debugging & Maintenance Utilities

#### `growspace_manager.debug_cleanup_legacy`

Utility to remove orphans and legacy data rows from state databases.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `dry_only` | `boolean`| No | `false` | Only purges dry logs. |
| `cure_only` | `boolean`| No | `false` | Only purges cure logs. |

#### `growspace_manager.debug_list_growspaces`

Dumps facility configurations and active registry maps directly into the Home Assistant system log for debugging.
_No parameters required._

#### `growspace_manager.debug_reset_special_growspaces`

Resets system-managed physical zones (`drying`, `curing`, `clones`, `mothers`) back to standard state definitions.
| Parameter | Type | Required | Default | Description |
| :--- | :--- | :--- | :--- | :--- |
| `reset_dry` | `boolean`| No | `true` | Re-initializes dry overview zone. |
| `reset_cure` | `boolean`| No | `true` | Re-initializes cure overview zone. |
| `preserve_plants`|`boolean`| No | `true` | Preserves plant registers during reset. |

---

## Generated Entities Directory

Each growspace and registered plant dynamically populates a suite of entities in Home Assistant.

### Facility & Zone Sensors

- **Growspace Overview Sensor** (`sensor.<growspace_name>`): The heart of each zone. The state represents the active plant count, while the attributes maintain the layout grid dimensions, specific coordinates occupied, and detailed plant records. Used directly by the Lovelace Card.
- **Growspaces List Sensor** (`sensor.growspaces_list`): Exposes an array of all registered facility zones.
- **Notification Switch** (`switch.<growspace_name>_notifications`): Simple toggle to mute or unmute scheduled push alerts.
- **Task Calendar** (`calendar.<growspace_name>_tasks`): Dedicated calendar mapping out feeding days, IPM sprays, tissue tests, and anticipated harvest targets.
- **Strain Library Sensor** (`sensor.growspace_strain_library`): Displays cataloged strain counts. The attributes expose the average vegetative and flowering periods computed from historical harvest logs.

### Plant Registry Sensors

- **Plant Sensor** (`sensor.<plant_strain>_<row>_<col>`): Tracks lifecycle stage (`seedling`, `veg`, `flower`, etc.). Attributes preserve genetic details, acquisition dates, training events, watering counters, and unique plant ID strings.

### Bayesian Environmental Monitors

When environment sensors are bound to a zone, these high-intelligence binary sensors are spawned:

- **Plants Under Stress** (`binary_sensor.<growspace_name>_plants_under_stress`): Evaluates temperature, humidity, VPD, and substrate moisture. Turns **ON** if conditions signal high osmotic or thermal stress.
- **High Mold Risk** (`binary_sensor.<growspace_name>_high_mold_risk`): Monitored during dark cycles in mid-to-late flower. Combines dew point, RH, and air circulation fan statuses. Turns **ON** to warn of powdery mildew or bud rot risk.
- **Optimal Conditions** (`binary_sensor.<growspace_name>_optimal_conditions`): Turns **ON** when environment parameters reside perfectly in the ideal VPD envelope for the current stage.
- **Light Schedule Correct** (`binary_sensor.<growspace_name>_light_schedule_correct`): Matches the daily photoperiod run hours against stage constraints (e.g. 18/6 for veg, 12/12 for flower). Turns **OFF** to signal timer failures or accidental light leaks.

---

## Real-World Automation Examples

### 1. Stage-Adaptive Humidifier & Dehumidifier Target Automation

Automatically dynamically steers climate settings as plants mature through growth stages.

```yaml
alias: "Climate: Stage-Adaptive VPD Targets"
description: "Sync dehumidifier and humidifier targets to the current growth stage"
trigger:
  - platform: state
    entity_id: sensor.flower_tent_overview
action:
  - choose:
      # Vegetative stage environmental setup
      - conditions:
          - condition: state
            entity_id: sensor.flower_tent_overview
            attribute: dominant_stage
            state: "veg"
        sequence:
          - service: growspace_manager.set_dehumidifier_control
            data:
              growspace_id: "flower_tent"
              enabled: true
              target_vpd: 0.9
      # Flowering stage environmental setup
      - conditions:
          - condition: state
            entity_id: sensor.flower_tent_overview
            attribute: dominant_stage
            state: "flower"
        sequence:
          - service: growspace_manager.set_dehumidifier_control
            data:
              growspace_id: "flower_tent"
              enabled: true
              target_vpd: 1.4
```

### 2. High Mold Risk Emergency Mitigation Automation

Activates exhaust fans and increases internal air movement when Bayesian analysis flags mold threats.

```yaml
alias: "IPM: High Mold Risk Mitigation"
trigger:
  - platform: state
    entity_id: binary_sensor.flower_tent_high_mold_risk
    to: "on"
action:
  - service: fan.turn_on
    target:
      entity_id: fan.tent_circulation
    data:
      percentage: 100
  - service: switch.turn_on
    target:
      entity_id: switch.tent_exhaust_boost
  - service: notify.mobile_app_iphone
    data:
      title: "⚠️ Facility Alert: High Mold Risk!"
      message: "Relative humidity spiking during dark cycle in bloom. Exhaust fans boosted to 100%."
```

### 3. VWC-Guided Steering Automation

Triggers micro-watering shots based on live substrate moisture and crop steering guidelines.

```yaml
alias: "Irrigation: Substrate Steering Shot"
trigger:
  - platform: numeric_state
    entity_id: sensor.flower_tent_substrate_moisture
    below: 55 # VWC dryback target reached
condition:
  # Verify light cycle is on (steering occurs during day phase)
  - condition: state
    entity_id: binary_sensor.flower_tent_optimal_conditions
    attribute: light_status
    state: "on"
action:
  - service: switch.turn_on
    target:
      entity_id: switch.irrigation_pump
  - delay: "00:00:30" # Run for standard shot duration
  - service: switch.turn_off
    target:
      entity_id: switch.irrigation_pump
  - service: growspace_manager.log_training_event
    data:
      technique: "Irrigation Shot"
      notes: "Steering shot triggered at 55% VWC"
```

---

## Troubleshooting & Diagnostics

### Q: Why are my Bayesian environment sensors showing "Unavailable"?

- **Check Sensor Binding**: Verify that the temperature, humidity, and VPD entities are correctly spelled and functioning.
- **Initial Baseline**: The Bayesian engine needs a short warm-up period to gather baseline data. Ensure that the associated sensors have updated at least once since restarting Home Assistant.

### Q: My Niimbot printer is paired but fails to print.

- **Bluetooth Range**: Thermal printers require a strong BLE connection. Move the printer closer to your Home Assistant server or use a BLE proxy.
- **Correct MAC Address**: Make sure to enter the printer's Bluetooth MAC address in the `device_id` field if auto-discovery fails.

### Q: Database issues after upgrading the integration version.

- **Run Diagnostics**: Use `growspace_manager.debug_cleanup_legacy` to clean orphaned records.
- **Re-initialize Special Zones**: Run `growspace_manager.debug_reset_special_growspaces` to repair drying/curing registers.

---

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
