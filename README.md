# Growspace Manager for Home Assistant

A comprehensive HACS integration for managing grow spaces and plants in Home Assistant.

## Features

- **Multiple Growspaces**: Create and manage multiple grow spaces as individual devices
- **Grid Layout**: Visual representation of plants in configurable rows and columns
- **Plant Tracking**: Track individual plants with detailed attributes
- **Day Counters**: Automatic calculation of days in vegetative and flowering stages
- **Notifications**: Optional milestone notifications (Day 21 flower for lollipopping, etc.)
- **Lovelace Integration**: Beautiful grid cards for dashboard display

## Installation

### HACS Installation
1. Add this repository to HACS custom repositories
2. Search for "Growspace Manager" in HACS
3. Install the integration
4. Restart Home Assistant
5. Add the integration through Configuration > Integrations

### Manual Installation
1. Copy the `custom_components/growspace_manager` folder to your Home Assistant `custom_components` directory
2. Restart Home Assistant
3. Add the integration through Configuration > Integrations

## Configuration

### Adding a Growspace
Use the service `growspace_manager.add_growspace`:
```yaml
service: growspace_manager.add_growspace
data:
  name: "Main Tent"
  rows: 4
  plants_per_row: 4
  notification_target: "mobile_app_your_phone"  # Optional
```

### Adding Plants
Use the service `growspace_manager.add_plant`:
```yaml
service: growspace_manager.add_plant
data:
  growspace_id: "your-growspace-id"
  strain: "Blue Dream"
  phenotype: "Pheno #1"
  row: 1
  col: 1
  veg_start: "2025-01-01T00:00:00"
  flower_start: "2025-02-01T00:00:00"  # Optional
```

## Plant Attributes

Each plant tracks the following attributes:
- `plant_id`: Automatically generated unique ID
- `strain`: Strain name
- `phenotype`: Phenotype identifier (optional)
- `row`: Row position in growspace
- `col`: Column position in growspace  
- `veg_start`: Vegetative stage start date/time
- `flower_start`: Flowering stage start date/time (optional)

## Sensors

The integration creates the following sensors:

### Growspace Overview Sensor
- **Entity ID**: `sensor.{growspace_name}_overview`
- **State**: Number of plants in growspace
- **Attributes**: Grid layout data, growspace configuration

### Plant Day Counters
- **Veg Days**: `sensor.{plant_id}_veg_days` - Days in vegetative stage
- **Flower Days**: `sensor.{plant_id}_flower_days` - Days in flowering stage

## Notifications

Automatic notifications are sent for key milestones:
- Day 14 in flower: Defoliation reminder
- Day 21 in flower: Lollipopping reminder  
- Day 35 in flower: Mid-flower check
- Day 56 in flower: Harvest approaching

Configure notifications by setting the `notification_target` when creating a growspace.

## Dashboard Cards

See the included Lovelace configuration examples for:
- Mushroom Cards