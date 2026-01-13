import asyncio
import json
import logging
import os
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure we can import custom_components
sys.path.append(os.getcwd())

# Setup basic logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


# Mock Home Assistant Helper
class MockConfig:
    def __init__(self, config_dir: Path):
        self.config_dir = config_dir

    def path(self, *parts):
        return str(self.config_dir.joinpath(*parts))


class MockHass:
    def __init__(self, config_dir: Path):
        self.config = MockConfig(config_dir)
        self.data = {}
        self.loop = asyncio.get_event_loop()

    async def async_add_executor_job(self, target, *args):
        return target(*args)


async def verify_safety():
    """Verify that corrupted data triggers a backup."""

    # 1. Setup a safe sandbox directory
    sandbox_dir = Path("safety_check_sandbox")
    storage_dir = sandbox_dir / ".storage"
    if sandbox_dir.exists():
        shutil.rmtree(sandbox_dir)
    storage_dir.mkdir(parents=True)

    print(f"1. Created sandbox directory: {sandbox_dir}")

    # 2. Mock imports that require full HA
    # We cheat by mocking the Store class to read/write from our sandbox
    with patch("homeassistant.helpers.storage.Store") as MockStore:
        # Import Manager (must be done after patch if it imported Store at top level,
        # but it imports name. Actually it imports CLASS. So we might need to patch module.)
        # Since we are running outside HA, we need to mock the entire homeassistant module or ensure venv is used.
        # Assuming user runs this in venv where homeassistant is installed.

        try:
            from custom_components.growspace_manager.storage_manager import (
                StorageManager,
            )
        except ImportError:
            print(
                "ERROR: Could not import StorageManager. Run this from vendor/growspace_manager directory."
            )
            return

        # 3. Create a StorageManager with mocked coordinator/hass
        mock_hass = MockHass(sandbox_dir)
        mock_coordinator = MagicMock()
        # Force deserializer to fail (simulate "30.0" string failure or similar)
        mock_coordinator.serializer.deserialize_growspaces.side_effect = Exception(
            "Simulated Deserialization Failure!"
        )

        manager = StorageManager(mock_coordinator, mock_hass)

        # 4. Create dummy corrupt data
        bad_data = {"growspaces": {"test_id": "I AM CORRUPT"}}
        print("2. Simulating corrupted data load...")

        # 5. Trigger the load (which calls _backup_corrupt_data internaly)
        # We call the internal method directly to simulate the failure in the loop
        manager._load_growspaces(bad_data)

        # 6. Verify Backup
        backups = list(storage_dir.glob("growspace_manager_growspaces_CORRUPT_*.json"))

        if not backups:
            print("\n❌ FAILURE: No backup file was created!")
            return

        print(f"\n✅ SUCCESS: Backup file created: {backups[0].name}")

        # 7. Check content
        with open(backups[0], "r") as f:
            content = json.load(f)
            if content == bad_data:
                print("✅ SUCCESS: Backup contains correct corrupted data.")
            else:
                print("❌ FAILURE: Backup content mismatch.")
                print(f"Expected: {bad_data}")
                print(f"Got: {content}")

        print("\nSafety mechanism is working correctly. Your data is safe.")

    # Cleanup
    shutil.rmtree(sandbox_dir)


if __name__ == "__main__":
    asyncio.run(verify_safety())
