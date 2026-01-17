# Adding Lovelace Card Resource to Home Assistant Instances

This guide explains how to add the Growspace Manager Lovelace card to your Home Assistant instances.

## Quick Method: Using the Helper Script

### For Dev Instance (Port 8123)
```bash
./tests/add-lovelace-resource.sh homeassistant homeassistant-dev
```

### For Test Instance (Port 8124)
```bash
./tests/add-lovelace-resource.sh homeassistant-test homeassistant-test
```

The script will:
1. Create the `/config/www/` directory
2. Copy the built card file
3. Provide instructions for adding the resource

## Manual Method: Via Home Assistant UI

### Step 1: Deploy the Card File

First, copy the card to the instance's www directory:

```bash
# For dev instance
docker exec homeassistant-dev mkdir -p /config/www
docker cp ../lovelace-growspace-manager-card/growspace-manager-card.js homeassistant-dev:/config/www/

# For test instance  
docker exec homeassistant-test mkdir -p /config/www
docker cp ../lovelace-growspace-manager-card/growspace-manager-card.js homeassistant-test:/config/www/
```

### Step 2: Add Resource via UI

1. Access your Home Assistant instance:
   - Dev: http://localhost:8123
   - Test: http://localhost:8124

2. Go to **Settings** → **Dashboards** → **Resources** tab

3. Click **+ Add Resource**

4. Enter:
   - **URL**: `/local/growspace-manager-card.js`
   - **Resource type**: **JavaScript Module**

5. Click **Create**

6. Refresh your browser (Ctrl+F5 or Cmd+Shift+R)

## Method 3: Via Configuration File

If you prefer to manage resources in YAML:

### For Dev Instance

1. Check if the dev instance has a configuration file at `config/configuration.yaml`

2. Add this section:
```yaml
lovelace:
  mode: storage
  resources:
    - url: /local/growspace-manager-card.js
      type: module
```

3. Restart the instance:
```bash
docker compose restart homeassistant
```

### For Test Instance

The test instance already has this configured in `tests/configs/configuration.yaml`.

## Verifying the Resource

After adding the resource, verify it's loaded:

1. Open browser developer console (F12)
2. Go to the Network tab
3. Refresh the page
4. Look for `growspace-manager-card.js` in the network requests
5. It should return status 200

## Troubleshooting

### Card file not found (404 error)

Check if the file exists:
```bash
docker exec homeassistant-dev ls -lh /config/www/
```

If missing, copy it again using the script or manual method.

### Card not updating after changes

1. Rebuild the card:
```bash
cd ../lovelace-growspace-manager-card
npm run build
```

2. Copy to instance:
```bash
docker cp growspace-manager-card.js homeassistant-dev:/config/www/
```

3. Hard refresh browser (Ctrl+F5)

### Resource already exists error

The resource is already added. Just refresh your browser.

## Using the Card

Once the resource is added, you can use the card in your dashboard:

1. Edit your dashboard
2. Click **+ Add Card**
3. Scroll to bottom and click **Manual**
4. Enter:
```yaml
type: custom:growspace-manager-card
entity: sensor.your_growspace_name
```

5. Click **Save**

## Notes

- The test instance (`homeassistant-test`) already has the resource configured in its `configuration.yaml`
- The dev instance (`homeassistant-dev`) needs the resource added manually via UI or configuration
- Both instances share the same `custom_components` directory
- Card updates require copying the new file and hard refreshing the browser
