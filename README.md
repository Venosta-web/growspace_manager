# Growspace Manager

**Growspace Manager** is a comprehensive Home Assistant integration for meticulously managing cannabis cultivation environments. It provides a powerful and intuitive way to track plants, organize growspace layouts, monitor environmental conditions, and receive intelligent notifications to ensure your plants thrive.

## Features

*   **Detailed Plant Tracking**: Monitor individual plants from seed to harvest and cure. Track precise dates for each phase, phenotype details, and positional layout.
*   **Batch Cloning & Seed Management**: Effortlessly generate multiple clones from a single mother, manage seed runs, and track them in batch operations.
*   **Visual Growspace Layouts & 3D Mapping**: Organize your plants in a grid system for each growspace. Configure sensor coordinates for advanced 3D heatmap visualizations in the companion Lovelace card.
*   **Nutrient Inventory & Feeding**: Track your liquid nutrient bottles, calculate precise ml/L dosages, set up feeding presets, and execute EC ramps tailored to specific growth phases. 
*   **Irrigation & Substrate Control**: Leverage Volumetric Water Content (VWC) tracking, crop steering strategies (vegetative/generative), and accurate water tank depletion prediction.
*   **Plant Harvest Analytics**: Execute detailed harvests logging wet, dry, and trim weights alongside THC/CBD percentages and custom terpene profiles.
*   **AI Assistant**: Built-in AI integration (powered by Home Assistant's conversation agents) provides:
    *   **Diagnostics**: Analyze sensor data and plant images (via Vision Checkup) to identify issues like heat stress or nutrient lockout.
    *   **Optimization**: Get tailored advice to improve your environment for the specific growth stage.
    *   **Planning**: Ask for help with scheduling, training techniques, or harvest timing.
*   **Advanced Environmental Monitoring & Device Control**: Utilizes a sophisticated Bayesian inference engine to provide intelligent binary sensors for:
    *   **Plant Stress**: Detects when conditions like temperature, humidity, or VPD are causing stress.
    *   **Mold Risk**: Proactively warns you of conditions favorable to mold growth.
    *   **Optimal Conditions**: Confirms when your environmental parameters are within the ideal range.
    *   **Device Automation**: Direct automated control over humidifiers, dehumidifiers, and circulation fans.
    *   **Light-Aware Logic**: Uses an optional light sensor to apply more accurate day/night thresholds and verifies your light schedule.
*   **Strain Analytics & Library Management**: Automatically tracks harvest data. Import/Export your custom Strain Library (including breeder data and images) easily using ZIP files.
*   **Specialized Growspaces**: Comes with pre-configured logical spaces for managing seedlings, clones, mothers, veg, flower, drying, and curing.
*   **Task Calendar & Notification Control**: Dedicated Home Assistant Calendar entity generated per growspace, with flexible notification controls.
*   **Dynamic Entity Creation**: Automatically generates a rich set of sensors and controls for each growspace and plant.
*   **Notification Control**: Easily toggle notifications for each growspace with a dedicated switch.
*   **Strain Library**: Automatically catalogs all your unique strains for easy reference.
*   **Specialized Growspaces**: Comes with pre-configured logical spaces for managing clones, mothers, drying, and curing.

## Advanced Features

### Strain Library Import/Export
Share your strain catalog with friends or easily back up your hard work. The integration supports bidirectional `.zip` imports and exports containing all your textual strain metadata, phenotypes, and custom image galleries.

### Crop Steering & Active Irrigation
Take your cultivation to a commercial level by enabling crop steering. Use connected substrate moisture sensors to schedule automated drybacks and precisely trigger vegetative or generative steering phases. Combine this with the **Nutrient Inventory** capabilities to calculate complex EC ramps automatically.

### Water Tank Depletion Predictor
Know exactly when your irrigation reservoir will run dry. The `Tank Water Tracker` uses historical watering events and current tank volume to predict depletion dates so your plants never miss a feeding.

### Strain Analytics & Harvest Precision
The `StrainLibrarySensor` does more than just list your strains; it automatically compiles harvest data to provide valuable insights. When a plant is moved to the "dry" growspace, its veg, flower, and total cycle durations are recorded. By entering precise data during the harvest action—like wet/dry/trim weights and lab test results (THC, CBD, Terpenes)—the sensor exposes average yields and timelines for each strain and phenotype.

### Task Calendar & Vision Checkups
For each growspace, the integration creates a dedicated Home Assistant calendar entity automatically populated with tasks and reminders from your timed configurations. Additionally, **Vision Checkup Schedulers** can be integrated to routinely prompt for image-based analyses using local or cloud AI models.

### Light-Aware & Active Environmental Control
By configuring an optional light sensor, humidifier, or dehumidifier for your growspace, you unlock more intelligent environmental monitoring:
*   **Day/Night Logic**: The Bayesian sensors will automatically switch between day and night thresholds for temperature and VPD, leading to more accurate stress and mold risk detection.
*   **Schedule Verification**: A `LightCycleVerificationSensor` is created to verify your light's on/off cycles for the current growth stage (e.g., 18/6 for veg, 12/12 for flower).
*   **Active Climate Intervention**: The integration can proactively command your exhaust, humidifier, or dehumidifier based on its probabilistic inferences before conditions drift out of range.

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
2.  You will see three options: "Manage Growspaces", "Manage Plants", and "Configure Environment Sensors". Select **Manage Growspaces** and click **Submit**.
3.  For the "Action", select **Add Growspace**.
4.  Fill in the details for your growspace:
    *   **Name**: e.g., "4x4 Tent"
    *   **Rows**: The number of plant rows.
    *   **Plants Per Row**: The number of plants in each row.
    *   **Notification Target**: (Optional) The notification service you want to use (e.g., `mobile_app_your_phone_name`).
5.  Click **Submit**.

### Step 3: Add Your First Plant
1.  Go back to the integration's **Configure** menu.
2.  Select **Manage Plants** and click **Submit**.
3.  For the "Action", select **Add New Plant** and click **Submit**.
4.  First, select the growspace you just created from the dropdown and click **Submit**.
5.  Now, fill in your plant's details:
    *   **Strain**: The name of the strain.
    *   **Row / Col**: The position in the grid.
    *   **Veg Start / Flower Start**: Set the date when the stage began.
6.  Click **Submit**.

### Step 4: Configure Environment Sensors
This is where the magic happens. By linking your existing sensors, you enable the intelligent Bayesian monitoring.
1.  Go back to the integration's **Configure** menu.
2.  Select **Configure Environment Sensors** and click **Submit**.
3.  Select the growspace you want to configure and click **Submit**.
4.  Link your sensor entities:
    *   **Required**: Temperature, Humidity, and VPD sensors.
*   **Optional**: A light or switch to determine if the lights are on/off, a CO2 sensor, and a circulation fan switch. Linking a light sensor enables more accurate day/night logic and activates the `LightCycleVerificationSensor`.
5.  Click **Submit** to save. The Bayesian binary sensors will be created automatically.

### Step 5: Configure AI Assistant (Optional)
Unlock intelligent insights by connecting a conversation agent.
1.  Go back to the integration's **Configure** menu.
2.  Select **Configure AI Assistant** and click **Submit**.
3.  **Enable AI Assistant**: Toggle this on.
4.  **Select Assistant**: Choose your preferred conversation agent (e.g., OpenAI, Google Generative AI, or a local LLM).
5.  **Personality**: Choose a personality style (e.g., "Professional", "Friendly", "Scientist").
6.  **Max Response Length**: Set a limit for the advice length to keep it concise.
7.  Click **Submit**.

### Step 6: Add the Card to Your Dashboard
1.  Navigate to the dashboard where you want to display your growspace.
2.  Click the three dots in the top right and select **Edit Dashboard**.
3.  Click **+ Add Card** and search for the **Custom: Growspace Card**.
4.  Select the **Growspace Overview Sensor** that corresponds to the growspace you created (e.g., `sensor.4x4_tent`).
5.  Click **Save**.

Your dashboard should now display a visual grid of your growspace!

![Growspace Manager Card Example](images/growspace_manager_card_example.png)


## Entities Created
This integration will create the following entities for you:

*   **Growspace Overview Sensor**: (`sensor.<growspace_name>`) The primary sensor for a growspace. Its state is the number of plants, and its attributes contain the grid layout and stage information. This is the entity you use with the Lovelace card.
*   **Plant Sensor**: (`sensor.<plant_strain>_<row>_<col>`) A detailed sensor for each individual plant. Its state is the current growth stage (e.g., "veg", "flower").
*   **Notification Switch**: (`switch.<growspace_name>_notifications`) Allows you to enable or disable notifications for a specific growspace.
*   **Strain Library Sensor**: (`sensor.growspace_strain_library`) A sensor whose state is the number of unique strains and whose attributes contain detailed harvest analytics, including average veg/flower times.
*   **Growspaces List Sensor**: (`sensor.growspaces_list`) A sensor whose attributes contain a list of all your configured growspaces.
*   **Task Calendar**: (`calendar.<growspace_name>_tasks`) A calendar entity for each growspace that displays scheduled tasks based on your timed notifications.

### Services
The integration exposes the following services:

*   **`growspace_manager.ask_grow_advice`**: Ask the AI assistant for advice on a specific growspace.
    *   **Targets**: A growspace overview sensor (e.g., `sensor.4x4_tent`).
    *   **Fields**:
        *   `user_query` (Optional): A specific question to ask. If omitted, the AI provides a general status update.
        *   `context_type`: The type of advice needed (`general`, `diagnostic`, `optimization`, `planning`).
        *   `max_length`: Maximum length of the response.

### Environmental Monitoring Sensors
When you configure environmental sensors for a growspace, the following powerful binary sensors are created:

*   **Plants Under Stress**: (`binary_sensor.<growspace_name>_plants_under_stress`) This sensor turns **ON** when the combination of temperature, humidity, VPD, and other factors indicates a high probability of plant stress. This is your primary indicator that something in the environment needs attention.
*   **High Mold Risk**: (`binary_sensor.<growspace_name>_high_mold_risk`) This sensor turns **ON** when conditions are favorable for mold and bud rot, particularly during the lights-off period in late flower. It monitors for high humidity, low VPD, and poor air circulation.
*   **Optimal Conditions**: (`binary_sensor.<growspace_name>_optimal_conditions`) This sensor turns **ON** when your environment is perfectly dialed in for the current growth stage. When this sensor is on, you know your plants are happy. It turns **OFF** as a warning that conditions have drifted out of the ideal range.
*   **Light Schedule Correct**: (`binary_sensor.<growspace_name>_light_schedule_correct`) An optional sensor (created when a light entity is configured) that turns **ON** if the light's on/off cycle duration is correct for the current growth stage.

## Automation Examples

Maximize the power of Growspace Manager with these automation ideas:

**1. High Heat Alert**
Send a critical notification to your phone if the "Plant Stress" sensor is triggered for more than 5 minutes.

```yaml
trigger:
  - platform: state
    entity_id: binary_sensor.4x4_tent_plants_under_stress
    to: "on"
    for: "00:05:00"
action:
  - service: notify.mobile_app_your_phone
    data:
      message: "CRITICAL: Plants in 4x4 Tent are under stress! Check environment immediately."
      title: "🔥 High Heat Stress"
```

**2. Auto-Adjustment for VPD**
If the "Optimal Conditions" sensor turns off, automatically toggle your humidifier (if connected to a smart plug).

```yaml
trigger:
  - platform: state
    entity_id: binary_sensor.4x4_tent_optimal_conditions
    to: "off"
    for: "00:10:00"
condition:
  - condition: numeric_state
    entity_id: sensor.4x4_tent_vpd
    above: 1.5 # Too dry
action:
  - service: switch.turn_on
    target:
      entity_id: switch.humidifier_plug
```

## Troubleshooting

**Q: My "Plants Under Stress" sensor is stuck on "Unknown".**
*   **Cause**: One or more of the required source sensors (Temperature, Humidity, VPD) is unavailable or not configured.
*   **Fix**: Go to **Configure** > **Configure Environment Sensors** and ensure all required sensors are linked and currently providing data.

**Q: I don't see the "Light Schedule Correct" sensor.**
*   **Cause**: You haven't linked a light entity to your growspace.
*   **Fix**: Go to **Configure** > **Configure Environment Sensors** > **Enable Light Monitoring** and select your light entity.

**Q: The AI Assistant isn't responding.**
*   **Cause**: The notification target might be invalid or the AI agent service is down.
*   **Fix**: Check your Home Assistant logs for "Growspace Manager" errors. Ensure the correct "Notification Target" service string is used in the growspace configuration.

## Known Limitations

*   **Manual Entity Deletion**: If you remove a growspace, you may need to manually delete some orphan entities from Home Assistant's entity registry if they were not cleaned up automatically.
*   **Restart Required**: Renaming a growspace currently requires a Home Assistant restart to fully update all related entity names.

## Data Updates

*   **Sensors**: Data from linked environmental sensors (temperature, humidity, etc.) is updated in real-time as Home Assistant receives state changes.
*   **Bayesian Sensors**: Stress and Mold risk probabilities are recalculated immediately upon any change in the underlying environmental sensors.
*   **Calculated Sensors**: VPD and other derived metrics are updated whenever their source sensors change.
*   **Plant Age**: Plant age (days in veg/flower) is recalculated daily at midnight.


