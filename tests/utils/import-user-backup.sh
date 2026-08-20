#!/bin/bash
# Script to import a user's Home Assistant backup into the test instance for debugging
# This script stops the test instance, cleans the config volume, extracts the backup,
# patches SSL and external URL settings for local HTTP access, and restarts the instance.

set -e

# Check arguments
BACKUP_FILE="$1"
if [ -z "$BACKUP_FILE" ]; then
    echo "❌ Usage: $0 <path_to_backup.tar>"
    exit 1
fi

# Resolve absolute path of backup file
if [[ ! "$BACKUP_FILE" = /* ]]; then
    BACKUP_FILE="$(pwd)/$BACKUP_FILE"
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ Backup file not found: $BACKUP_FILE"
    exit 1
fi

# Locate the project directories
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"

# Switch to the docker-compose project directory
cd "$PROJECT_DIR"

echo "🔍 Validating backup file: $(basename "$BACKUP_FILE")..."
if ! tar -tf "$BACKUP_FILE" | grep -q "homeassistant.tar.gz"; then
    echo "❌ Invalid Home Assistant backup. Could not find 'homeassistant.tar.gz' in $(basename "$BACKUP_FILE")."
    exit 1
fi

echo "⏹️  Stopping homeassistant-test container..."
docker compose stop homeassistant-test

echo "🧹 Clearing existing configuration from test volume..."
docker compose run --rm --entrypoint "" homeassistant-test-init sh -c "rm -rf /config/* /config/.[!.]* /config/..?* 2>/dev/null || true"

echo "📦 Extracting user configuration into test volume..."
# Extract homeassistant.tar.gz from backup.tar, and pipe it to tar inside the busybox init container
tar -xOf "$BACKUP_FILE" homeassistant.tar.gz | docker compose run --rm -T --entrypoint "" homeassistant-test-init tar -xz -C /config --strip-components=1

echo "🛡️  Checking and patching configuration for local testing..."
docker compose run --rm --entrypoint "" homeassistant-test-init sh -c '
  if [ -f /config/configuration.yaml ]; then
    echo "  📄 Checking configuration.yaml..."
    
    # Disable SSL certificate and key
    if grep -E -q "^[[:space:]]*ssl_certificate:" /config/configuration.yaml; then
      echo "  ⚠️  SSL configuration found! Commenting out for local HTTP access..."
      sed -i "s/^\([[:space:]]*ssl_certificate:.*\)/# \1/g" /config/configuration.yaml
      sed -i "s/^\([[:space:]]*ssl_key:.*\)/# \1/g" /config/configuration.yaml
    fi
    
    # Comment out external_url
    if grep -E -q "^[[:space:]]*external_url:" /config/configuration.yaml; then
      echo "  ⚠️  External URL configuration found! Commenting out to prevent redirect loops..."
      sed -i "s/^\([[:space:]]*external_url:.*\)/# \1/g" /config/configuration.yaml
    fi
  else
    echo "  ⚠️  No configuration.yaml found in restored backup root!"
  fi
'

echo "👤 Fixing permissions for non-root user (1000:1000)..."
docker compose run --rm --entrypoint "" homeassistant-test-init chown -R 1000:1000 /config

echo "🚀 Starting test instance..."
docker compose up -d homeassistant-test

# Give it a moment to initialize the container before running setup
sleep 2

echo "🔧 Re-applying Lovelace card and resource configurations..."
"$SCRIPT_DIR/setup-test-instance.sh"

echo ""
echo "🎉 Import complete!"
echo "The user backup has been successfully imported into the test instance."
echo "Access it at: http://localhost:8124"
echo ""
echo "To view logs, run:"
echo "  docker compose logs -f homeassistant-test"
echo ""
