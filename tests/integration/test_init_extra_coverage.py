"""Extra tests for init module coverage."""

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.growspace_manager import (
    _async_remove_dynamic_entities,
    async_register_sidebar_panel,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.growspace_manager.const import CONF_SHOW_SIDEBAR, DOMAIN
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry


async def test_async_setup_entry_pending_growspace_success(hass: HomeAssistant) -> None:
    """Test successful pending growspace creation and cleanup (Line 127)."""
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            "pending_growspace": {"name": "Test Room", "rows": 1, "plants_per_row": 1}
        },
        options={},
    )
    entry.add_to_hass(hass)

    mock_store_instance = MagicMock()
    mock_store_instance.async_load = AsyncMock(return_value={})
    mock_store_cls = MagicMock()
    mock_store_cls.__getitem__.return_value.return_value = mock_store_instance

    mock_coordinator = MagicMock()
    mock_coordinator.async_load = AsyncMock()
    mock_coordinator.async_initialize_sub_coordinators = AsyncMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()

    # Mock services.growspaces facade
    mock_coordinator.services = MagicMock()
    mock_coordinator.services.growspaces = MagicMock()
    mock_coordinator.services.growspaces.add_growspace = AsyncMock()

    mock_strain_lib = MagicMock()
    mock_strain_lib.async_setup = AsyncMock()

    mock_scraper = MagicMock()
    hass.data[DOMAIN] = {
        "strain_library": mock_strain_lib,
        "seedfinder_scraper": mock_scraper,
    }
    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()

    with (
        patch("custom_components.growspace_manager.Store", mock_store_cls),
        patch(
            "custom_components.growspace_manager.coordinator.GrowspaceCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.service_registration.register_services",
            new_callable=AsyncMock,
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
        patch.object(hass.config_entries, "async_update_entry") as mock_update,
    ):
        assert await async_setup_entry(hass, entry) is True

        # Verify pending_growspace was processed and entry updated
        mock_coordinator.services.growspaces.add_growspace.assert_called_once()
        mock_update.assert_called_once()
        assert "pending_growspace" not in mock_update.call_args[1]["data"]


async def test_async_setup_entry_strain_library_init(hass: HomeAssistant) -> None:
    """Test StrainLibrary initialization when not already in hass.data (Line 56)."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    # Empty hass.data[DOMAIN]
    hass.data[DOMAIN] = {}

    mock_store_instance = MagicMock()
    mock_store_instance.async_load = AsyncMock(return_value={})
    mock_store_cls = MagicMock()
    mock_store_cls.__getitem__.return_value.return_value = mock_store_instance

    mock_coordinator = MagicMock()
    mock_coordinator.async_load = AsyncMock()
    mock_coordinator.async_initialize_sub_coordinators = AsyncMock()
    mock_coordinator.async_config_entry_first_refresh = AsyncMock()

    mock_strain_lib = MagicMock()
    mock_strain_lib.async_setup = AsyncMock()

    hass.http = MagicMock()
    hass.http.async_register_static_paths = AsyncMock()

    with (
        patch("custom_components.growspace_manager.Store", mock_store_cls),
        patch(
            "custom_components.growspace_manager.StrainLibrary",
            return_value=mock_strain_lib,
        ) as mock_strain_lib_cls,
        patch(
            "custom_components.growspace_manager.coordinator.GrowspaceCoordinator",
            return_value=mock_coordinator,
        ),
        patch(
            "custom_components.growspace_manager.async_setup_intents",
            new_callable=AsyncMock,
        ),
        patch(
            "custom_components.growspace_manager.service_registration.register_services",
            new_callable=AsyncMock,
        ),
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new_callable=AsyncMock
        ),
    ):
        assert await async_setup_entry(hass, entry) is True

        # Verify StrainLibrary was instantiated and setup
        mock_strain_lib_cls.assert_called_once_with(hass)
        mock_strain_lib.async_setup.assert_called_once()
        assert hass.data[DOMAIN]["strain_library"] == mock_strain_lib


async def test_async_register_sidebar_panel_remove(hass: HomeAssistant) -> None:
    """Test unregistering the sidebar panel (Line 185-191)."""
    entry = MockConfigEntry(domain=DOMAIN, options={CONF_SHOW_SIDEBAR: False})

    # Set up panel in hass.data
    hass.data["frontend_panels"] = {DOMAIN: MagicMock()}

    with patch(
        "custom_components.growspace_manager.frontend_async_remove_panel"
    ) as mock_remove_panel:
        await async_register_sidebar_panel(hass, entry)

    mock_remove_panel.assert_called_once_with(hass, DOMAIN)


async def test_async_unload_entry_domain_checks(hass: HomeAssistant) -> None:
    """Test async_unload_entry domain checks (Line 232)."""
    entry = MagicMock()
    entry.entry_id = "test"
    entry.runtime_data = MagicMock()
    entry.runtime_data.async_shutdown = AsyncMock()

    # Case 1: DOMAIN NOT in hass.data
    hass.data = {}
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry) is True

    # Case 2: DOMAIN in hass.data but strain_library NOT in it
    hass.data[DOMAIN] = {}
    with patch.object(hass.config_entries, "async_unload_platforms", return_value=True):
        assert await async_unload_entry(hass, entry) is True


def test_async_remove_dynamic_entities_coverage(hass: HomeAssistant) -> None:
    """Test _async_remove_dynamic_entities (Line 208)."""
    coordinator = MagicMock()
    _async_remove_dynamic_entities(hass, coordinator)
    # It's a no-op, just ensure it runs


async def test_async_unload_entry_removes_panel(hass: HomeAssistant) -> None:
    """Test async_unload_entry removes sidebar panel if present (Line 231)."""
    entry = MagicMock()
    entry.entry_id = "test"
    entry.runtime_data = MagicMock()
    entry.runtime_data.async_shutdown = AsyncMock()

    # Create mock hass with frontend panels
    hass.data = {}
    hass.data[DOMAIN] = {}  # Needed for line 234 check to pass or fail gracefully?
    # Actually line 229: if DOMAIN in hass.data.get("frontend_panels", {}):
    hass.data["frontend_panels"] = {DOMAIN: MagicMock()}

    with (
        patch.object(hass.config_entries, "async_unload_platforms", return_value=True),
        patch(
            "custom_components.growspace_manager.frontend_async_remove_panel"
        ) as mock_remove_panel,
    ):
        assert await async_unload_entry(hass, entry) is True

    # Verify remove_panel was called
    mock_remove_panel.assert_called_once_with(hass, DOMAIN)
