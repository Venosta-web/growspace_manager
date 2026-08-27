#!/bin/bash
# Setup script for Home Assistant test instance
# This script prepares the test instance with necessary resources

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
FIXTURE="$PROJECT_DIR/tests/fixtures/lovelace/growspace-manager-card.js"

cd "$PROJECT_DIR"

echo "🔧 Setting up Home Assistant test instance..."

echo "🔎 Validating and preparing isolated Lovelace fixtures..."
python3 "$SCRIPT_DIR/prepare_lovelace_fixtures.py"

# Wait for test instance to be ready
echo "⏳ Waiting for test instance to initialize..."
sleep 5

# Check if container is running
if ! docker ps | grep -q homeassistant-test; then
    echo "❌ Test instance is not running. Start it first with:"
    echo "   docker compose up -d homeassistant-test"
    exit 1
fi

echo "📁 Creating www directory in test instance..."
docker exec homeassistant-test mkdir -p /config/www

echo "📦 Copying Lovelace card to test instance..."
docker cp "$FIXTURE" homeassistant-test:/config/www/growspace-manager-card.js
echo "✅ Authoritative Lovelace fixture copied successfully"

echo "📁 Creating themes directory..."
docker exec homeassistant-test mkdir -p /config/themes

echo "🔄 Restarting test instance to apply configuration..."
docker compose restart homeassistant-test

echo ""
echo "✅ Setup complete!"
echo ""
echo "📋 Next steps:"
echo "1. Access test instance at: http://localhost:8124"
echo "2. Complete onboarding (create user account)"
echo "3. Go to Settings → Devices & Services"
echo "4. Add the Growspace Manager integration"
echo "5. Configure it with the test sensors:"
echo "   - Temperature: sensor.test_temperature"
echo "   - Humidity: sensor.test_humidity"
echo "   - VPD: sensor.test_vpd"
echo "   - CO2: sensor.test_co2"
echo "   - Light (PPFD): sensor.test_ppfd"
echo "   - Soil Moisture: sensor.test_soil_moisture"
echo ""
echo "6. Add a Lovelace card (the resource is already configured)"
echo ""
echo "💡 Tip: Check logs with: docker compose logs -f homeassistant-test"
