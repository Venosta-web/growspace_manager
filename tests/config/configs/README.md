# Home Assistant Test Instance

This directory contains configuration for a second, independent Home Assistant instance used for integration testing.

## Overview

The test instance runs alongside your main development instance with:

- **Separate configuration volume**: `ha-config-test`
- **Separate port**: `8124` (vs. `8123` for dev instance)
- **Shared custom components**: Both instances use the same `./custom_components` directory
- **Pre-configured test sensors**: Template sensors for temperature, humidity, VPD, CO2, PPFD, and soil moisture
- **Lovelace resources**: Dashboard resources pre-configured for the Growspace Manager card

## Quick Setup

### Automated Setup (Recommended)

Run the setup script to automatically configure the test instance:

```bash
./tests/setup-test-instance.sh
```

This script will:

1. Create the `www` directory in the test instance
2. Copy the Lovelace card JavaScript file
3. Create necessary theme directories
4. Restart the instance to apply changes

### Adding Lovelace Resource to Dev Instance

The test instance has the Lovelace resource pre-configured. For the dev instance:

```bash
./tests/add-lovelace-resource.sh homeassistant homeassistant-dev
```

Or add manually via **Settings → Dashboards → Resources**:

- URL: `/local/growspace-manager-card.js`
- Type: JavaScript Module

See [`LOVELACE_RESOURCE.md`](LOVELACE_RESOURCE.md) for detailed instructions.

### Manual Setup

If you prefer manual setup or need to troubleshoot:

### Starting Both Instances

```bash
docker compose up -d
```

This starts both `homeassistant-dev` (port 8123) and `homeassistant-test` (port 8124).

### Accessing the Test Instance

Open your browser to:

```
http://localhost:8124
```

### Starting Only the Test Instance

```bash
docker compose up -d homeassistant-test
```

### Viewing Logs

```bash
# Test instance logs
docker compose logs -f homeassistant-test

# Dev instance logs
docker compose logs -f homeassistant
```

## Resetting the Test Instance

To completely wipe the test instance and start fresh:

```bash
# Stop all services
docker compose down

# Remove the test instance volume
docker volume rm growspace_manager_ha-config-test

# Start services again (test instance will be fresh)
docker compose up -d
```

Or use the provided script:

```bash
./tests/reset-test-instance.sh
```

## Configuration

The test instance uses the configuration file at:

```
tests/configs/configuration.yaml
```

### Pre-configured Test Sensors

The configuration includes template sensors that simulate a grow environment:

| Sensor        | Entity ID                   | Type      | Range        | Notes                                |
| ------------- | --------------------------- | --------- | ------------ | ------------------------------------ |
| Temperature   | `sensor.test_temperature`   | °C        | 22-28°C      | Random variation                     |
| Humidity      | `sensor.test_humidity`      | %         | 55-70%       | Random variation                     |
| VPD           | `sensor.test_vpd`           | kPa       | 1.0-1.5 kPa  | Calculated range                     |
| CO2           | `sensor.test_co2`           | ppm       | 800-1200 ppm | Random variation                     |
| PPFD (Light)  | `sensor.test_ppfd`          | µmol/m²/s | 0-600        | Simulates day/night cycle (6am-10pm) |
| Soil Moisture | `sensor.test_soil_moisture` | %         | 40-70%       | Random variation                     |

These sensors update automatically and can be used to configure the Growspace Manager integration.

### Lovelace Resources

The dashboard is pre-configured with the Growspace Manager card resource:

- **URL**: `/local/growspace-manager-card.js`
- **Type**: Module
- **Mode**: Storage (UI-managed dashboards)

### Customization

You can modify the configuration to add:

- Custom integrations for testing
- Specific test entities
- Mock devices
- Test automations

Changes to this file require restarting the test instance:

```bash
docker compose restart homeassistant-test
```

## Key Differences from Dev Instance

| Feature           | Dev Instance                   | Test Instance                        |
| ----------------- | ------------------------------ | ------------------------------------ |
| Container Name    | `homeassistant-dev`            | `homeassistant-test`                 |
| Port              | `8123`                         | `8124`                               |
| Volume            | `ha-config`                    | `ha-config-test`                     |
| Config Source     | `./config/configuration.yaml`  | `./tests/configs/configuration.yaml` |
| Custom Components | `./custom_components` (shared) | `./custom_components` (shared)       |

## Testing Workflow

1. **Make changes** to your custom component code
2. **Restart test instance** to load changes:
   ```bash
   docker compose restart homeassistant-test
   ```
3. **Test in browser** at `http://localhost:8124`
4. **Reset if needed** using the reset script
5. **Verify in dev instance** at `http://localhost:8123` before committing

## Notes

- Both instances share the same `custom_components` directory, so code changes affect both
- The test instance maintains its own entity registry, user accounts, and state
- Resetting the test instance does NOT affect your dev instance
- You can run both instances simultaneously for comparison testing
