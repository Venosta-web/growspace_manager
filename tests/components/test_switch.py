from unittest.mock import AsyncMock, Mock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.switch import (
    AUTOMATION_SWITCH,
    IRRIGATION_ARM_SWITCH,
    NOTIFICATION_SWITCH,
    GrowspaceNotificationSwitch,
    GrowspaceSafetySwitch,
    async_setup_entry,
)


# --------------------
# Fixtures
# --------------------
@pytest.fixture
def mock_coordinator() -> GrowspaceCoordinator:
    """Return a mock coordinator with sample growspaces."""
    coordinator = Mock()
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
def mock_hass(mock_coordinator: GrowspaceCoordinator):
    """Return a mock Home Assistant object."""
    hass = Mock()
    hass.data = {DOMAIN: {"entry1": {"coordinator": mock_coordinator}}}
    return hass


# --------------------
# Tests
# --------------------
@pytest.mark.asyncio
async def test_async_setup_entry_creates_entities(mock_hass, mock_coordinator) -> None:
    added_entities = []

    # synchronous callback as Home Assistant expects
    def fake_add_entities(new_entities, update_before_add=False):
        added_entities.extend(new_entities)

    # Mock coordinator growspaces - use objects with attributes for typed access compatibility
    gs1 = Mock()
    gs1.name = "Growspace 1"
    gs1.notification_target = "notify_target_1"

    gs2 = Mock()
    gs2.name = "Growspace 2"
    gs2.notification_target = None

    mock_coordinator.growspaces = {"gs1": gs1, "gs2": gs2}
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.ensure_special_growspace = AsyncMock(return_value="special_gs")
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator.async_set_updated_data = Mock()

    mock_coordinator.services = Mock()
    mock_coordinator.services.notifications.is_notifications_enabled = Mock(
        return_value=True
    )

    await async_setup_entry(
        mock_hass,
        Mock(entry_id="entry1", runtime_data=mock_coordinator),
        fake_add_entities,
    )

    assert len(added_entities) == 5
    assert (
        sum(isinstance(entity, GrowspaceSafetySwitch) for entity in added_entities) == 4
    )
    switch = next(
        entity
        for entity in added_entities
        if isinstance(entity, GrowspaceNotificationSwitch)
    )
    assert isinstance(switch, GrowspaceNotificationSwitch)
    assert switch._growspace_id == "gs1"
    assert switch.is_on is True
    # The name may be None if has_entity_name is True, as HA constructs the full name from device name + entity name
    # But let's check the logic inside
    assert switch.entity_description == NOTIFICATION_SWITCH

    gs3 = Mock()
    gs3.name = "Growspace 3"
    gs3.notification_target = None
    mock_coordinator.growspaces["gs3"] = gs3
    add_new = mock_coordinator.async_add_listener.call_args.args[0]
    add_new()
    assert len(added_entities) == 7
    add_new()
    assert len(added_entities) == 7


@pytest.mark.asyncio
async def test_safety_switch_persists_actor_and_updates_state(mock_coordinator) -> None:
    growspace = Growspace(id="gs1", name="Growspace 1")
    mock_coordinator.irrigation_safety.controls = {
        "gs1": {"automation": True, "irrigation_armed": False}
    }
    mock_coordinator.irrigation_safety.async_set_control = AsyncMock()
    for description, initial in (
        (AUTOMATION_SWITCH, True),
        (IRRIGATION_ARM_SWITCH, False),
    ):
        switch = GrowspaceSafetySwitch(mock_coordinator, "gs1", growspace, description)
        assert switch.is_on is initial
        with (
            patch.object(switch, "async_write_ha_state"),
            patch("custom_components.growspace_manager.switch.async_delete_issue"),
        ):
            await switch.async_turn_on()
            await switch.async_turn_off()
        mock_coordinator.irrigation_safety.async_set_control.assert_any_await(
            "gs1", description.key, True, None
        )
        mock_coordinator.irrigation_safety.async_set_control.assert_any_await(
            "gs1", description.key, False, None
        )


@pytest.mark.asyncio
async def test_growspace_notification_switch_on_off(mock_coordinator) -> None:
    # Growspace object
    growspace = Growspace(id="gs1", name="Growspace 1", notification_target="notify_me")

    # Mock coordinator methods
    mock_coordinator.services = Mock()
    mock_coordinator.services.notifications.set_notifications_enabled = AsyncMock()
    mock_coordinator.services.notifications.is_notifications_enabled = Mock(
        return_value=True
    )

    switch = GrowspaceNotificationSwitch(
        mock_coordinator, "gs1", growspace, NOTIFICATION_SWITCH
    )

    # Patch async_write_ha_state so HA internals are not invoked
    switch.hass = Mock()
    with patch.object(switch, "async_write_ha_state", return_value=None):
        # Default state should be on
        assert switch.is_on is True

        # Turn off
        mock_coordinator.services.notifications.is_notifications_enabled.return_value = False
        await switch.async_turn_off()
        assert switch.is_on is False

        # Turn on
        mock_coordinator.services.notifications.is_notifications_enabled.return_value = True
        await switch.async_turn_on()
        assert switch.is_on is True


@pytest.mark.asyncio
async def test_async_added_to_hass_calls_add_listener(mock_coordinator) -> None:
    growspace = Growspace(id="gs1", name="Growspace 1", notification_target="notify_me")
    switch = GrowspaceNotificationSwitch(
        mock_coordinator, "gs1", growspace, NOTIFICATION_SWITCH
    )

    await switch.async_added_to_hass()
    # async_add_listener should be called once with async_write_ha_state
    mock_coordinator.async_add_listener.assert_called_once_with(
        switch.async_write_ha_state
    )
