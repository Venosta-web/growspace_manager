"""Tests for the Growspace Manager switch platform."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.switch import (
    GrowspaceNotificationSwitch,
    async_setup_entry,
)


# --------------------
# Fixtures
# --------------------
@pytest.fixture
def mock_coordinator() -> GrowspaceCoordinator:
    """Return a mock coordinator with sample growspaces."""
    coordinator = Mock(spec=GrowspaceCoordinator)
    coordinator.hass = Mock()
    coordinator.growspaces = {
        "gs1": {
            "id": "gs1",
            "name": "Growspace 1",
            "notification_target": "notify_me",
        },
        "gs2": {
            "id": "gs2",
            "name": "Growspace 2",
            "notification_target": None,  # Should not create a switch
        },
    }
    coordinator.async_add_listener = Mock()
    return coordinator


@pytest.fixture
def mock_hass(mock_coordinator: GrowspaceCoordinator) -> Mock:
    """Return a mock Home Assistant object."""
    hass = Mock()
    hass.data = {DOMAIN: {"entry1": {"coordinator": mock_coordinator}}}
    return hass


# --------------------
# Tests
# --------------------
@pytest.mark.asyncio
async def test_async_setup_entry_creates_entities(
    mock_hass: Mock, mock_coordinator: GrowspaceCoordinator
) -> None:
    """Test that async_setup_entry creates notification switch entities."""
    added_entities: list = []

    # synchronous callback as Home Assistant expects
    def fake_add_entities(
        new_entities: list, *, update_before_add: bool = False
    ) -> None:
        added_entities.extend(new_entities)

    # Mock coordinator growspaces
    gs1 = Mock()
    gs1.name = "Growspace 1"
    gs1.notification_target = "notify_target_1"

    gs2 = Mock()
    gs2.name = "Growspace 2"
    gs2.notification_target = None

    mock_coordinator.growspaces = {"gs1": gs1, "gs2": gs2}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    # Accessing private member _ensure_special_growspace is necessary for testing internal behavior
    mock_coordinator._ensure_special_growspace = AsyncMock(return_value="special_gs")
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.async_set_updated_data = Mock()

    mock_coordinator.is_notifications_enabled = Mock(return_value=True)

    mock_hass.data = {DOMAIN: {"entry1": {"coordinator": mock_coordinator}}}

    await async_setup_entry(mock_hass, Mock(entry_id="entry1"), fake_add_entities)

    assert len(added_entities) == 1
    switch = added_entities[0]
    assert isinstance(switch, GrowspaceNotificationSwitch)
    assert switch.unique_id == f"{DOMAIN}_gs1_notifications"
    assert switch.is_on is True
    assert switch.name == "Notifications"


@pytest.mark.asyncio
async def test_growspace_notification_switch_on_off(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test the GrowspaceNotificationSwitch can be turned on and off."""
    # Growspace object
    growspace = SimpleNamespace(
        id="gs1",
        name="Growspace 1",
        notification_target="notify_me",
    )

    # Mock coordinator methods
    mock_coordinator.async_set_growspace_notification = AsyncMock()
    mock_coordinator.is_notifications_enabled = Mock(return_value=True)

    switch = GrowspaceNotificationSwitch(mock_coordinator, "gs1", growspace)

    # Patch async_write_ha_state so HA internals are not invoked
    switch.hass = Mock()
    with patch.object(switch, "async_write_ha_state", return_value=None):
        # Default state should be on
        assert switch.is_on is True

        # Turn off
        mock_coordinator.is_notifications_enabled.return_value = False
        await switch.async_turn_off()
        assert switch.is_on is False

        # Turn on
        mock_coordinator.is_notifications_enabled.return_value = True
        await switch.async_turn_on()
        assert switch.is_on is True


@pytest.mark.asyncio
async def test_async_added_to_hass_calls_add_listener(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test that async_added_to_hass registers a listener."""
    growspace = SimpleNamespace(
        id="gs1",
        name="Growspace 1",
        notification_target="notify_me",
    )
    switch = GrowspaceNotificationSwitch(mock_coordinator, "gs1", growspace)

    await switch.async_added_to_hass()
    # async_add_listener should be called once with async_write_ha_state
    mock_coordinator.async_add_listener.assert_called_once_with(
        switch.async_write_ha_state,
    )
