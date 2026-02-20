#!/bin/bash
# Reset the Home Assistant test instance to a fresh state

set -e

echo "🧹 Resetting Home Assistant test instance..."

# Stop all services
echo "⏹️  Stopping services..."
docker compose down

# Remove the test instance volume
echo "🗑️  Removing test instance volume..."
docker volume rm growspace_manager_ha-config-test 2>/dev/null || echo "Volume already removed or doesn't exist"

# Start services again
echo "🚀 Starting services..."
docker compose up -d

echo "✅ Test instance reset complete!"
echo ""
echo "The test instance is now running with a fresh configuration."
echo "Access it at: http://localhost:8124"
echo ""
echo "To view logs, run:"
echo "  docker compose logs -f homeassistant-test"
