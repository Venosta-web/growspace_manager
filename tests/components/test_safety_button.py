"""Emergency stop buttons follow growspaces added after platform setup."""

from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.growspace_manager.button import (
    GrowspaceEmergencyStopButton,
    async_setup_entry,
)
from custom_components.growspace_manager.models import Growspace


async def test_button_added_for_new_growspace_and_invokes_stop() -> None:
    coordinator = MagicMock()
    coordinator.growspaces = {"tent": Growspace(id="tent", name="Tent")}
    entry = MagicMock(runtime_data=coordinator)
    added: list[GrowspaceEmergencyStopButton] = []
    await async_setup_entry(MagicMock(), entry, lambda entities: added.extend(entities))
    assert len(added) == 1
    coordinator.growspaces["new"] = Growspace(id="new", name="New")
    add_new = coordinator.async_add_listener.call_args.args[0]
    add_new()
    add_new()
    assert len(added) == 2
    button = added[1]
    with patch(
        "custom_components.growspace_manager.button.async_emergency_stop_growspace",
        new_callable=AsyncMock,
    ) as stop:
        await button.async_press()
    stop.assert_awaited_once_with(None, coordinator, "new", None)
