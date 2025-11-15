"""Fixtures for Growspace Manager integration tests."""
from unittest.mock import MagicMock

import pytest
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from custom_components.growspace_manager.const import DOMAIN


@pytest.fixture
def hass() -> HomeAssistant:
    """Fixture for a Home Assistant instance."""
    return MagicMock()


@pytest.fixture
def mock_config_entry() -> ConfigEntry:
    """Fixture for a mock config entry."""
    return MagicMock(
        domain=DOMAIN,
        data={"name": "Test Growspace"},
        options={},
        entry_id="test_entry_id",
    )


@pytest.fixture
def mock_store() -> Store:
    """Fixture for a mock storage."""
    return MagicMock()
