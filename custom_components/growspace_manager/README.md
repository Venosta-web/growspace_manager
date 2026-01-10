# Growspace Manager

**Growspace Manager** is a comprehensive Home Assistant integration for meticulously managing cannabis cultivation environments. It provides a powerful and intuitive way to track plants, organize growspace layouts, monitor environmental conditions, and receive intelligent notifications to ensure your plants thrive.

## Features

- **Detailed Plant Tracking**: Monitor individual plants from seed to cure, tracking their strain, phenotype, position, and key dates (veg, flower, etc.).
- **Visual Growspace Layouts**: Organize your plants in a grid system for each growspace. Visualize your entire setup at a glance using the companion Lovelace card.
- **Smart Irrigation**: Automate simple daily watering or advanced "Crop Steering" strategies with support for multiple irrigation events and drainage control.
- **Advanced Environmental Monitoring**: Utilizes a sophisticated Bayesian inference engine to provide intelligent binary sensors for Plant Stress, Mold Risk, and Optimal Conditions.
- **Environment Control**: Automate dehumidifier operation based on dynamic VPD and humidity targets that adapt to the day/night cycle and growth stage.
- **Strain Recommendations**: Get AI-powered strain suggestions based on your preferences and previous harvest data.
- **Integrated Pest Management (IPM)**: Track pest prevention and treatment tasks directly within your growspace management workflow.
- **Strain Analytics**: Automatically tracks harvest data to provide average veg and flower times for each strain.
- **Task Calendar**: Generates a dedicated calendar for each growspace with scheduled tasks based on your timed notifications.
- **Dynamic Entity Creation**: Automatically generates a rich set of sensors and controls for each growspace and plant.
- **Notification Control**: Easily toggle notifications for each growspace with a dedicated switch.
- **Strain Library**: Automatically catalogs all your unique strains for easy reference.
- **Specialized Growspaces**: Comes with pre-configured logical spaces for managing clones, mothers, drying, and curing.

## Advanced Features

### Smart Irrigation & Crop Steering
The integration includes a robust irrigation coordinator that can handle:
- **Simple Schedules**: Set a daily duration for watering.
- **Multi-Feed Events**: Configure specific times for irrigation events throughout the day.
- **Crop Steering Strategies**:
  - **Vegetative**: Focuses on building biomass with frequent, smaller waterings.
  - **Generative**: Encourages flower production with larger dry-backs.
  - **Balanced**: A middle-ground approach for general maintenance.
- **Drainage Control**: Automatically triggers a drain pump after irrigation to manage runoff (waste).

### Environment Control (VPD & Humidity)
Go beyond monitoring with active control. The generic **Dehumidifier Integration** allows you to:
- **Target VPD or Humidity**: Choose your preferred metric.
- **Stage-Specific Targets**: Different targets for Veg, Early Flower, Mid Flower, and Late Flower (e.g., lower humidity in late flower to prevent mold).
- **Day/Night Cycles**: Automatically adjusts targets when lights go off.
- **Smart Hysteresis**: Prevents short-cycling of your equipment.

### Strain Recommendations (AI)
Leverage the power of LLMs (like Google Gemini or OpenAI) to get personalized strain recommendations.
- **Context-Aware**: The AI knows your growspace setup (biomass, lighting).
- **History-Based**: Takes into account strains you've successfully grown before.
- **Goal-Oriented**: Ask for "high yield," "short flowering time," or specific terpene profiles.

### Strain Analytics
The `StrainLibrarySensor` does more than just list your strains; it automatically compiles harvest data to provide valuable insights. When a plant is moved to the "dry" growspace, its veg and flower durations are recorded. The sensor then calculates and exposes the average veg and flower times for each strain and phenotype, allowing you to refine your cultivation cycles and compare results over time.

### Light-Aware Monitoring
By configuring an optional light sensor for your growspace, you unlock more intelligent environmental monitoring:
- **Day/Night Logic**: The Bayesian sensors will automatically switch between day and night thresholds for temperature and VPD, leading to more accurate stress and mold risk detection.
- **Schedule Verification**: A `LightCycleVerificationSensor` is created to monitor your light's on/off cycles. It verifies that the light is running for the correct duration for the current growth stage (e.g., 18/6 for veg, 12/12 for flower) and will turn off if the schedule is incorrect, alerting you to potential timer malfunctions.

## Installation

This integration requires two components: the main integration (installed via HACS) and the Lovelace card (also installed via HACS).

**Step 1: Install the Lovelace Card**

1.  Navigate to **HACS** > **Frontend**.
2.  Click the three dots in the top right and select **Custom repositories**.
3.  Enter the repository URL: `https://github.com/Venosta-web/lovelace-growspace-manager-card` and select the category **Lovelace**.
4.  Click **Add**.
5.  Find the "Growspace Manager Card" in the list and click **Install**.

**Step 2: Install the Growspace Manager Integration**

1.  Navigate to **HACS** > **Integrations**.
2.  Click the three dots in the top right and select **Custom repositories**.
3.  Enter the repository URL: `https://github.com/Venosta-web/growspace_manager` and select the category **Integration**.
4.  Click **Add**.
5.  Find "Growspace Manager" in the list and click **Install**.
6.  Restart Home Assistant when prompted.

## Configuration: A Step-by-Step Guide

### Step 1: Add the Growspace Manager Integration

1.  Go to **Settings** > **Devices & Services**.
2.  Click **+ Add Integration** and search for **Growspace Manager**.
3.  Follow the initial prompt to add the integration.

### Step 2: Create Your First Growspace

The integration is managed through its configuration menu.

1.  On the integration's card, click **Configure**.
2.  Select **Manage Growspaces** and click **Submit**.
3.  For the "Action", select **Add Growspace**.
4.  Fill in the details for your growspace:
    - **Name**: e.g., "4x4 Tent"
    - **Rows**: The number of plant rows.
    - **Plants Per Row**: The number of plants in each row.
    - **Notification Target**: (Optional) The notification service you want to use (e.g., `mobile_app_your_phone_name`).
5.  Click **Submit**.

### Step 3: Add Your First Plant

1.  Go back to the integration's **Configure** menu.
2.  Select **Manage Plants** and click **Submit**.
3.  For the "Action", select **Add New Plant** and click **Submit**.
4.  First, select the growspace you just created from the dropdown and click **Submit**.
5.  Now, fill in your plant's details:
    - **Strain**: The name of the strain.
    - **Row / Col**: The position in the grid.
    - **Veg Start / Flower Start**: Set the date when the stage began.
6.  Click **Submit**.

### Step 4: Configure Environment Sensors & Control

This is where the magic happens. By linking your existing sensors and devices, you enable intelligent monitoring and control.

1.  Go back to the integration's **Configure** menu.
2.  Select **Configure Growspace Environment** and click **Submit**.
3.  Select the growspace you want to configure.
4.  Link your sensor entities:
    - **Required**: Temperature, Humidity, and VPD sensors.
    - **Optional (Monitoring)**: CO2 sensor, Mold Risk Fan (circulation fan), Light Sensor (for Day/Night logic).
    - **Optional (Control)**: **Dehumidifier** entity (switch or humidifier domain). You can also enable **Control Dehumidifier** to let Growspace Manager automate it based on VPD targets.
5.  (If Dehumidifier Control is enabled) Set your VPD or Humidity targets for each growth stage (Veg, Early Flower, Mid Flower, Late Flower) and for Day/Night cycles.
6.  Click **Submit** to save.

### Step 5: Configure Irrigation (Optional)

1.  Select **Configure Irrigation** from the main menu.
2.  Choose your growspace.
3.  Link your **Irrigation Pump** and **Drain Pump** entities.
4.  Set a **Default Duration** for watering events.
5.  Once configured, you can add specific watering times using the `growspace_manager.add_irrigation_time` service or manage them via the dashboard if supported.

### Step 6: Configure AI Assistant (Optional)

To enable the Virtual Grow Master and Strain Recommendations:
1.  Select **Configure AI Settings** from the main menu.
2.  Check **Enable AI Features**.
3.  Select a Home Assistant **Conversation Agent** (e.g., Google Gemini, OpenAI).
4.  Click **Submit**.

### Step 7: Add the Card to Your Dashboard

1.  Navigate to the dashboard where you want to display your growspace.
2.  Click the three dots in the top right and select **Edit Dashboard**.
3.  Click **+ Add Card** and search for the **Custom: Growspace Card**.
4.  Select the **Growspace Overview Sensor** that corresponds to the growspace you created (e.g., `sensor.4x4_tent`).
5.  Click **Save**.

## Services

This integration provides a comprehensive set of services to manage your growspaces and plants from automations or scripts.

### Growspace Services

#### `growspace_manager.add_growspace`

Creates a new growspace for managing plants.

| Field                 | Description                     | Required | Example                 |
| :-------------------- | :------------------------------ | :------- | :---------------------- |
| `name`                | Name of the growspace           | Yes      | `"4x8 Tent"`            |
| `rows`                | Number of rows in the growspace | Yes      | `2`                     |
| `plants_per_row`      | Number of plants per row        | Yes      | `4`                     |
| `notification_target` | Notification service target     | No       | `"mobile_app_my_phone"` |

#### `growspace_manager.remove_growspace`

Removes a growspace and all of its plants.

| Field          | Description                   | Required | Example        |
| :------------- | :---------------------------- | :------- | :------------- |
| `growspace_id` | ID of the growspace to remove | Yes      | `"uuid-12345"` |

---

### Plant Services

#### `growspace_manager.add_plant`

Adds a plant to a specific growspace.

| Field          | Description                                            | Required | Example        |
| :------------- | :----------------------------------------------------- | :------- | :------------- |
| `growspace_id` | ID of the target growspace                             | Yes      | `"uuid-12345"` |
| `strain`       | Plant strain name                                      | Yes      | `"Blue Dream"` |
| `row`          | Row position in the growspace                          | Yes      | `1`            |
| `col`          | Column position in the growspace                       | Yes      | `3`            |
| `phenotype`    | Plant phenotype (optional)                             | No       | `"A"`          |
| `veg_start`    | Vegetative start date                                  | No       | `"2025-10-01"` |
| `flower_start` | Flowering start date                                   | No       | `"2025-11-01"` |
| `..._start`    | Dates for `seedling`, `mother`, `clone`, `dry`, `cure` | No       | `"2025-09-20"` |

#### `growspace_manager.update_plant`

Updates information for an existing plant.

| Field       | Description               | Required | Example            |
| :---------- | :------------------------ | :------- | :----------------- |
| `plant_id`  | ID of the plant to update | Yes      | `"uuid-plant-abc"` |
| `strain`    | New plant strain name     | No       | `"Sour Diesel"`    |
| `phenotype` | New plant phenotype       | No       | `"B"`              |
| `row`       | New row position          | No       | `2`                |
| `col`       | New column position       | No       | `1`                |
| `veg_start` | New vegetative start date | No       | `"2025-10-02"`     |
| `..._start` | New dates for any stage   | No       | `"2025-11-02"`     |

#### `growspace_manager.remove_plant`

Removes a plant from the growspace.

| Field      | Description               | Required | Example            |
| :--------- | :------------------------ | :------- | :----------------- |
| `plant_id` | ID of the plant to remove | Yes      | `"uuid-plant-abc"` |

#### `growspace_manager.move_plant`

Moves a plant to a new position. If the new position is occupied, it will switch places with the other plant.

| Field      | Description             | Required | Example            |
| :--------- | :---------------------- | :------- | :----------------- |
| `plant_id` | ID of the plant to move | Yes      | `"uuid-plant-abc"` |
| `new_row`  | New row position        | Yes      | `1`                |
| `new_col`  | New column position     | Yes      | `2`                |

#### `growspace_manager.switch_plants`

Switches the positions of two plants.

| Field        | Description            | Required | Example            |
| :----------- | :--------------------- | :------- | :----------------- |
| `plant_id_1` | ID of the first plant  | Yes      | `"uuid-plant-abc"` |
| `plant_id_2` | ID of the second plant | Yes      | `"uuid-plant-def"` |

#### `growspace_manager.transition_plant_stage`

Transitions a plant to a new growth stage and sets the corresponding start date.

| Field             | Description                                      | Required | Example            |
| :---------------- | :----------------------------------------------- | :------- | :----------------- |
| `plant_id`        | ID of the plant                                  | Yes      | `"uuid-plant-abc"` |
| `new_stage`       | New stage (`veg`, `flower`, `dry`, `cure`, etc.) | Yes      | `"flower"`         |
| `transition_date` | Date of the transition (defaults to today)       | No       | `"2025-11-01"`     |

#### `growspace_manager.harvest_plant`

Harvests a plant. This will record analytics (veg/flower time) and move the plant to the "dry" growspace.

| Field                 | Description                                | Required | Example            |
| :-------------------- | :----------------------------------------- | :------- | :----------------- |
| `plant_id`            | ID of the plant to harvest                 | Yes      | `"uuid-plant-abc"` |
| `target_growspace_id` | Optional target growspace ID (e.g., "dry") | No       | `"dry"`            |
| `transition_date`     | Optional harvest date (defaults to today)  | No       | `"2025-11-17"`     |

#### `growspace_manager.take_clone`

Creates one or more clones from a mother plant and places them in the "clone" growspace.

| Field             | Description                                | Required | Example             |
| :---------------- | :----------------------------------------- | :------- | :------------------ |
| `mother_plant_id` | ID of the mother plant                     | Yes      | `"uuid-mother-abc"` |
| `num_clones`      | Number of clones to create (defaults to 1) | No       | `5`                 |
| `transition_date` | Optional date the clones were taken        | No       | `"2025-11-17"`      |

#### `growspace_manager.move_clone`

Moves a plant from the "clone" growspace to a new growspace (e.g., "veg") and sets its new stage start date.

| Field                 | Description                                 | Required | Example            |
| :-------------------- | :------------------------------------------ | :------- | :----------------- |
| `plant_id`            | ID of the clone plant to move               | Yes      | `"uuid-clone-123"` |
| `target_growspace_id` | ID of the target growspace (e.g., "veg")    | Yes      | `"veg"`            |
| `transition_date`     | Date of transition (e.g., `veg_start` date) | No       | `"2025-11-17"`     |

---

### Environment & Control Services

#### `growspace_manager.configure_environment`

Sets up or updates the environment sensors for a growspace to enable Bayesian monitoring.

| Field                | Description                                   | Required | Example                  |
| :------------------- | :-------------------------------------------- | :------- | :----------------------- |
| `growspace_id`       | ID of the growspace to configure              | Yes      | `"uuid-12345"`           |
| `temperature_sensor` | Temperature sensor entity ID                  | Yes      | `"sensor.tent_temp"`     |
| `humidity_sensor`    | Humidity sensor entity ID                     | Yes      | `"sensor.tent_humidity"` |
| `vpd_sensor`         | VPD sensor entity ID                          | Yes      | `"sensor.tent_vpd"`      |
| `co2_sensor`         | CO2 sensor entity ID                          | No       | `"sensor.tent_co2"`      |
| `circulation_fan`    | Circulation fan switch/fan entity ID          | No       | `"switch.tent_fan"`      |
| `light_sensor`       | Light or switch entity ID for day/night logic | No       | `"light.grow_light"`     |
| `stress_threshold`   | Probability threshold for stress (0.0-1.0)    | No       | `0.7`                    |
| `mold_threshold`     | Probability threshold for mold (0.0-1.0)      | No       | `0.75`                   |
| `control_dehumidifier`| Enable automated dehumidifier                 | No       | `true`                   |
| `dehumidifier_entity`| Dehumidifier switch or device                 | No       | `"switch.dehumidifier"`  |

#### `growspace_manager.remove_environment`

Removes the environment sensor configuration from a growspace.

| Field          | Description                               | Required | Example        |
| :------------- | :---------------------------------------- | :------- | :------------- |
| `growspace_id` | ID of the growspace to remove config from | Yes      | `"uuid-12345"` |

---

### Irrigation Services

#### `growspace_manager.set_irrigation_settings`

Configures the irrigation and drain pumps, and default durations for a growspace.

| Field                | Description                                   | Required | Example                  |
| :------------------- | :-------------------------------------------- | :------- | :----------------------- |
| `growspace_id`       | ID of the growspace                           | Yes      | `"uuid-12345"`           |
| `irrigation_pump_entity` | Entity ID for the irrigation pump switch      | No       | `"switch.irrigation"`    |
| `drain_pump_entity`  | Entity ID for the drain pump switch           | No       | `"switch.drain_pump"`    |
| `irrigation_duration`| Default duration in seconds to water          | No       | `60`                     |
| `drain_duration`     | Default duration in seconds to drain          | No       | `120`                    |

#### `growspace_manager.add_irrigation_time`

Schedules a daily irrigation event at a specific time.

| Field                | Description                                   | Required | Example                  |
| :------------------- | :-------------------------------------------- | :------- | :----------------------- |
| `growspace_id`       | ID of the growspace                           | Yes      | `"uuid-12345"`           |
| `time`               | Time of day to run (HH:MM:SS)                 | Yes      | `"08:00:00"`             |
| `duration`           | Override default duration (seconds)           | No       | `30`                     |

#### `growspace_manager.remove_irrigation_time`

Removes a specific scheduled irrigation time.

| Field                | Description                                   | Required | Example                  |
| :------------------- | :-------------------------------------------- | :------- | :----------------------- |
| `growspace_id`       | ID of the growspace                           | Yes      | `"uuid-12345"`           |
| `time`               | Time of day to remove (HH:MM:SS)              | Yes      | `"08:00:00"`             |

---

### Intelligence & AI Services

#### `growspace_manager.ask_grow_advice`

Query the Virtual Grow Master about a specific growspace. It uses the current sensor data and plant stage to provide context-aware advice.

| Field          | Description                               | Required | Example                  |
| :------------- | :---------------------------------------- | :------- | :----------------------- |
| `growspace_id` | ID of the growspace to analyze            | Yes      | `"uuid-12345"`           |
| `user_query`   | Specific question (optional)              | No       | `"Is my VPD too high?"`  |

#### `growspace_manager.strain_recommendation`

Get AI-curated strain suggestions based on your preferences and previous harvest data.

| Field          | Description                               | Required | Example                  |
| :------------- | :---------------------------------------- | :------- | :----------------------- |
| `user_query`   | Description of what you are looking for   | No       | `"Fruity sativa for day"`|
| `preferences`  | Key-value pairs for specific goals        | No       | `{"yield": "high"}`      |
| `growspace_id` | Target growspace for recommendation       | No       | `"uuid-12345"`           |

---

### Strain Library Services

#### `growspace_manager.get_strain_library`

Returns the list of all strains in the library. This is typically used in scripts.

#### `growspace_manager.export_strain_library`

Fires an event (`growspace_manager_strain_library_exported`) containing all strains.

#### `growspace_manager.import_strain_library`

Imports a list of strains.

| Field     | Description                             | Required | Example                    |
| :-------- | :-------------------------------------- | :------- | :------------------------- |
| `strains` | List of strain data to import           | Yes      | `["Strain A", "Strain B"]` |
| `replace` | Whether to replace the existing library | No       | `false`                    |

#### `growspace_manager.clear_strain_library`

Removes all strains from the library.

---

## Entities Created

This integration will create the following entities for you:

- **Growspace Overview Sensor**: (`sensor.<growspace_name>`) The primary sensor for a growspace. Its state is the number of plants, and its attributes contain the grid layout and stage information. This is the entity you use with the Lovelace card.
- **Plant Sensor**: (`sensor.<plant_strain>_<row>_<col>`) A detailed sensor for each individual plant. Its state is the current growth stage (e.g., "veg", "flower").
- **Notification Switch**: (`switch.<growspace_name>_notifications`) Allows you to enable or disable notifications for a specific growspace.
- **Strain Library Sensor**: (`sensor.growspace_strain_library`) A sensor whose state is the number of unique strains and whose attributes contain detailed harvest analytics, including average veg/flower times.
- **Growspaces List Sensor**: (`sensor.growspaces_list`) A sensor whose attributes contain a list of all your configured growspaces.
- **Task Calendar**: (`calendar.<growspace_name>_tasks`) A calendar entity for each growspace that displays scheduled tasks based on timed notifications.

### Environmental Monitoring Sensors

When you configure environmental sensors for a growspace, the following powerful binary sensors are created:

- **Plants Under Stress**: (`binary_sensor.<growspace_name>_plants_under_stress`) This sensor turns **ON** when the combination of temperature, humidity, VPD, and other factors indicates a high probability of plant stress. This is your primary indicator that something in the environment needs attention.
- **High Mold Risk**: (`binary_sensor.<growspace_name>_high_mold_risk`) This sensor turns **ON** when conditions are favorable for mold and bud rot, particularly during the lights-off period in late flower. It monitors for high humidity, low VPD, and poor air circulation.
- **Optimal Conditions**: (`binary_sensor.<growspace_name>_optimal_conditions`) This sensor turns **ON** when your environment is perfectly dialed in for the current growth stage. When this sensor is on, you know your plants are happy. It turns **OFF** as a warning that conditions have drifted out of the ideal range.
- **Light Schedule Correct**: (`binary_sensor.<growspace_name>_light_schedule_correct`) An optional sensor (created when a light entity is configured) that turns **ON** if the light's on/off cycle duration is correct for the current growth stage.
