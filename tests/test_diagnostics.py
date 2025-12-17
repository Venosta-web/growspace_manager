"""Test the Growspace Manager diagnostics."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.core import HomeAssistant

from custom_components.growspace_manager.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.mark.asyncio
async def test_async_get_config_entry_diagnostics(hass: HomeAssistant) -> None:
    """Test diagnostics."""
    entry = MagicMock()
    entry.as_dict.return_value = {
        "entry_id": "test_entry",
        "data": {"some": "data", "latitude": 12.34},
    }

    coordinator = MagicMock()
    coordinator.data = {
        "growspaces": {"gs1": {"name": "Test Growspace", "unique_id": "sensitive"}},
        "plants": {},
    }
    entry.runtime_data = coordinator

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert "entry" in result
    assert "coordinator_data" in result

    # Check redaction
    assert result["entry"]["data"]["latitude"] == "**REDACTED**"
    assert (
        result["coordinator_data"]["growspaces"]["gs1"]["unique_id"] == "**REDACTED**"
    )
    assert result["coordinator_data"]["growspaces"]["gs1"]["name"] == "Test Growspace"
