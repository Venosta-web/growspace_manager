"""An upgrade that keeps a growspace's irrigation armed asks for a review (#791).

The safety store is written the first time 1.3.0 starts. A growspace that
already had a pump before then is migrated armed, so watering does not stop on
upgrade, and setup raises a Repairs issue asking the grower to check it.
"""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.growspace_manager.const import (
    DOMAIN,
    STORAGE_KEY_CONFIG,
    STORAGE_VERSION,
)
from custom_components.growspace_manager.models import Growspace, IrrigationConfig
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from tests.common import MockConfigEntry


def _seed(hass_storage: dict, *growspaces: Growspace) -> None:
    """Store growspaces as a build without a safety store left them."""
    hass_storage[STORAGE_KEY_CONFIG] = {
        "version": STORAGE_VERSION,
        "minor_version": 1,
        "key": STORAGE_KEY_CONFIG,
        "data": {"growspaces": {gs.id: asdict(gs) for gs in growspaces}},
    }


async def _setup(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    entry.add_to_hass(hass)
    hass.http = MagicMock(async_register_static_paths=AsyncMock())
    with patch(
        "custom_components.growspace_manager.async_register_sidebar_panel",
        new_callable=AsyncMock,
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()


async def test_setup_raises_a_review_only_for_growspaces_migrated_armed(
    hass: HomeAssistant,
    hass_storage: dict,
    mock_config_entry: MockConfigEntry,
    enable_custom_integrations: None,
    recorder_mock: None,
) -> None:
    """A piped growspace is kept armed and flagged; a dry one is neither."""
    _seed(
        hass_storage,
        Growspace(
            id="piped",
            name="Piped",
            irrigation_config=IrrigationConfig(irrigation_pump_entity="switch.pump"),
        ),
        Growspace(id="dry", name="Dry"),
    )

    await _setup(hass, mock_config_entry)

    safety = mock_config_entry.runtime_data.irrigation_safety
    assert safety.irrigation_armed("piped")
    assert not safety.irrigation_armed("dry")
    issues = ir.async_get(hass)
    issue = issues.async_get_issue(DOMAIN, "irrigation_arm_review_piped")
    assert issue is not None
    assert issue.translation_key == "irrigation_arm_review"
    assert issue.translation_placeholders == {"growspace": "Piped"}
    assert issues.async_get_issue(DOMAIN, "irrigation_arm_review_dry") is None

    await hass.config_entries.async_unload(mock_config_entry.entry_id)
    await hass.async_block_till_done()
