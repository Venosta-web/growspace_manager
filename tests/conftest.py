"""Global fixtures for integration tests."""
import sys
from unittest.mock import MagicMock

# Mock fcntl for Windows
if sys.platform.startswith("win"):
    sys.modules["fcntl"] = MagicMock()

pytest_plugins = "pytest_homeassistant_custom_component"
