# Growspace Manager

**Growspace Manager** is a comprehensive Home Assistant integration for meticulously managing cannabis cultivation environments. It provides a powerful and intuitive way to track plants, organize growspace layouts, monitor environmental conditions, and receive intelligent notifications to ensure your plants thrive.

## Features

*   **Detailed Plant Tracking**: Monitor individual plants from seed to cure, tracking their strain, phenotype, position, and key dates (veg, flower, etc.).
*   **Visual Growspace Layouts**: Organize your plants in a grid system for each growspace. Visualize your entire setup at a glance using the companion Lovelace card.
*   **Advanced Environmental Monitoring**: Utilizes a sophisticated Bayesian inference engine to provide intelligent binary sensors for:
    *   **Plant Stress**: Detects when conditions like temperature, humidity, or VPD are likely causing stress to your plants.
    *   **Mold Risk**: Proactively warns you of conditions favorable to mold growth, especially during the critical late-flowering stage.
    *   **Optimal Conditions**: Confirms when your environmental parameters are within the ideal range for the current growth stage.
*   **Dynamic Entity Creation**: Automatically generates a rich set of sensors and controls for each growspace and plant.
*   **Notification Control**: Easily toggle notifications for each growspace with a dedicated switch.
*   **Strain Library**: Automatically catalogs all your unique strains for easy reference.
*   **Specialized Growspaces**: Comes with pre-configured logical spaces for managing clones, mothers, drying, and curing.

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
    *   **Optional**: A light or switch to determine if the lights are on/off, a CO2 sensor, and a circulation fan switch.
5.  Click **Submit** to save. The Bayesian binary sensors will be created automatically.

### Step 5: Add the Card to Your Dashboard
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
*   **Strain Library Sensor**: (`sensor.growspace_strain_library`) A sensor whose attributes contain a list of all unique strains you have added.
*   **Growspaces List Sensor**: (`sensor.growspaces_list`) A sensor whose attributes contain a list of all your configured growspaces.

### Environmental Monitoring Sensors
When you configure environmental sensors for a growspace, three powerful binary sensors are created:

*   **Plants Under Stress**: (`binary_sensor.<growspace_name>_plants_under_stress`) This sensor turns **ON** when the combination of temperature, humidity, VPD, and other factors indicates a high probability of plant stress. This is your primary indicator that something in the environment needs attention.
*   **High Mold Risk**: (`binary_sensor.<growspace_name>_high_mold_risk`) This sensor turns **ON** when conditions are favorable for mold and bud rot, particularly during the lights-off period in late flower. It monitors for high humidity, low VPD, and poor air circulation.
*   **Optimal Conditions**: (`binary_sensor.<growspace_name>_optimal_conditions`) This sensor turns **ON** when your environment is perfectly dialed in for the current growth stage. When this sensor is on, you know your plants are happy. It turns **OFF** as a warning that conditions have drifted out of the ideal range.
