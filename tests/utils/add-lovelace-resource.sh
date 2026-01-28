#!/bin/bash
# Add Lovelace card resource to the dev instance
# This script copies the card and adds it to the dashboard resources

set -e

INSTANCE_NAME="${1:-homeassistant}"
CONTAINER_NAME="${2:-homeassistant-dev}"

echo "🔧 Adding Lovelace card resource to ${INSTANCE_NAME}..."

# Check if container is running
if ! docker ps | grep -q "${CONTAINER_NAME}"; then
    echo "❌ ${CONTAINER_NAME} is not running. Start it first with:"
    echo "   docker compose up -d ${INSTANCE_NAME}"
    exit 1
fi

echo "📁 Creating www directory..."
docker exec "${CONTAINER_NAME}" mkdir -p /config/www

echo "📦 Copying Lovelace card..."
if [ -f "../lovelace-growspace-manager-card/dist/growspace-manager-card.js" ]; then
    docker cp ../lovelace-growspace-manager-card/dist/growspace-manager-card.js "${CONTAINER_NAME}":/config/www/
    echo "✅ Lovelace card copied from dist/"
elif [ -f "../lovelace-growspace-manager-card/growspace-manager-card.js" ]; then
    docker cp ../lovelace-growspace-manager-card/growspace-manager-card.js "${CONTAINER_NAME}":/config/www/
    echo "✅ Lovelace card copied from root"
else
    echo "⚠️  Lovelace card not found. Build it first with:"
    echo "   cd ../lovelace-growspace-manager-card && npm run build"
    exit 1
fi

echo ""
echo "✅ Lovelace card deployed to ${CONTAINER_NAME}!"
echo ""
echo "📋 Next steps:"
echo "1. Access instance at: http://localhost:8123 (dev) or http://localhost:8124 (test)"
echo "2. Go to Settings → Dashboards → Resources"
echo "3. Click '+ Add Resource'"
echo "4. Add:"
echo "   URL: /local/growspace-manager-card.js"
echo "   Type: JavaScript Module"
echo ""
echo "Or add to your configuration.yaml:"
echo ""
echo "lovelace:"
echo "  mode: storage"
echo "  resources:"
echo "    - url: /local/growspace-manager-card.js"
echo "      type: module"
echo ""
echo "💡 Tip: Restart instance after config changes:"
echo "   docker compose restart ${INSTANCE_NAME}"
