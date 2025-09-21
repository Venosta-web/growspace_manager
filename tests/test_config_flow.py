import pytest
from homeassistant.core import HomeAssistant
from homeassistant import config_entries

from custom_components.growspace_manager.const import DOMAIN


@pytest.mark.asyncio
async def test_options_flow_triggers_reload(hass: HomeAssistant):
    """Test that updating options triggers automatic reload."""

    entry = config_entries.ConfigEntry(
        version=1,
        domain=DOMAIN,
        title="Growspace Manager",
        data={},
        options={},
        source="user",
        entry_id="test123",
    )
    hass.config_entries._entries[entry.entry_id] = entry

    called = {}

    async def mock_setup(hass, entry):
        called["setup"] = called.get("setup", 0) + 1
        return True

    async def mock_unload(hass, entry):
        called["unload"] = called.get("unload", 0) + 1
        return True

    hass.config_entries._setup_entry = mock_setup
    hass.config_entries._unload_entry = mock_unload

    # Init options flow
    result = await hass.config_entries.options.async_init(entry.entry_id, data=None)
    assert result["type"] == "form"

    # Submit new options
    result2 = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={"notification_interval": 30},
    )
    assert result2["type"] == "create_entry"
    assert result2["data"]["notification_interval"] == 30

    # Check reload happened
    assert called["unload"] == 1
    assert called["setup"] == 1
