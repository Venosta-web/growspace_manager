"""add_growspace keeps the notification target a real phone is reachable by.

Run against a live Home Assistant with a real device registry: the filter this
replaces passed every MagicMock test and matched no device Home Assistant ever
registers, because a device's `config_entries` holds entry ids, not domains.
"""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.const import DOMAIN
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.helpers import device_registry as dr
from tests.common import MockConfigEntry


@callback
def _ignore(call: ServiceCall) -> None:
    """Stand in for mobile_app's push handler."""


@pytest.mark.usefixtures("init_integration")
async def test_add_growspace_keeps_a_mobile_app_notify_target(
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
) -> None:
    """The mobile_app notify service the card offers is what gets stored."""
    phone_entry = MockConfigEntry(domain="mobile_app", title="Pixel 7")
    phone_entry.add_to_hass(hass)
    phone = dr.async_get(hass).async_get_or_create(
        config_entry_id=phone_entry.entry_id,
        identifiers={("mobile_app", "pixel-7-webhook")},
        name="Pixel 7",
    )
    # mobile_app registers one notify service per device, named after it.
    hass.services.async_register("notify", "mobile_app_pixel_7", _ignore)
    assert phone.config_entries == {phone_entry.entry_id}

    await hass.services.async_call(
        DOMAIN,
        "add_growspace",
        {
            "name": "Phone Tent",
            "rows": 2,
            "plants_per_row": 2,
            "notification_target": "mobile_app_pixel_7",
        },
        blocking=True,
    )
    await hass.async_block_till_done()

    growspace = next(
        gs
        for gs in mock_config_entry.runtime_data.growspaces.values()
        if gs.name == "Phone Tent"
    )
    assert growspace.notification_target == "mobile_app_pixel_7"
    assert hass.services.has_service("notify", growspace.notification_target)
