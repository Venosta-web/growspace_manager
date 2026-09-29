"""The safety store refuses to act on a record it cannot trust (#791).

An operator control or an emergency stop reset is reported as done only once it
is on disk. A store that could not be read, or could not be written, refuses
every later change instead of acting on a record that is not the persisted one.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from custom_components.growspace_manager.irrigation_safety_store import (
    IrrigationSafetyStore,
)
from custom_components.growspace_manager.models import Growspace
from homeassistant.core import HomeAssistant


async def _store(hass: HomeAssistant, key: str) -> IrrigationSafetyStore:
    store = IrrigationSafetyStore(hass, key)
    await store.async_load()
    await store.async_initialize_controls({"tent": Growspace(id="tent", name="Tent")})
    return store


async def test_an_unreadable_store_migrates_nothing(hass: HomeAssistant) -> None:
    """No growspace is armed from a record that could not be read."""
    store = IrrigationSafetyStore(hass, "unreadable-init")
    await store.async_load()
    store.unreadable = True
    store._store.async_save = AsyncMock()

    assert (
        await store.async_initialize_controls({"tent": Growspace("tent", "Tent")}) == []
    )
    assert store.controls == {}
    store._store.async_save.assert_not_awaited()


async def test_an_unreadable_store_refuses_controls_and_resets(
    hass: HomeAssistant,
) -> None:
    """Neither an arm nor a reset is reported against an untrusted record."""
    store = await _store(hass, "unreadable-controls")
    await store.async_latch_emergency_stop("tent", "test", ("switch.pump",), "op")
    store.unreadable = True

    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_set_control("tent", "irrigation_armed", True, "op")
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_reset_emergency_stop("tent", "op")
    assert not store.controls["tent"]["irrigation_armed"]
    assert "tent" in store.emergency_stops


async def test_an_unknown_control_is_refused(hass: HomeAssistant) -> None:
    store = await _store(hass, "unknown-control")

    with pytest.raises(ValueError, match="Unknown safety control"):
        await store.async_set_control("tent", "lights", True, "op")
    assert "lights" not in store.controls["tent"]


async def test_setting_a_control_to_its_value_records_nothing(
    hass: HomeAssistant,
) -> None:
    """A repeated switch press is not a second decision in the ledger."""
    store = await _store(hass, "idempotent-control")
    rows = len(store.ledger)
    store._store.async_save = AsyncMock()

    await store.async_set_control("tent", "automation", True, "op")

    assert len(store.ledger) == rows
    store._store.async_save.assert_not_awaited()


async def test_a_reset_without_a_latched_stop_is_refused(hass: HomeAssistant) -> None:
    store = await _store(hass, "no-stop")

    with pytest.raises(ValueError, match="No emergency stop"):
        await store.async_reset_emergency_stop("tent", "op")


async def test_a_control_that_cannot_be_saved_fails_closed(
    hass: HomeAssistant,
) -> None:
    """The caller hears the failure, and later changes are refused."""
    store = await _store(hass, "control-save-fails")
    store._store.async_save = AsyncMock(side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        await store.async_set_control("tent", "irrigation_armed", True, "op")

    assert store.unreadable
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_set_control("tent", "automation", False, "op")


async def test_a_reset_that_cannot_be_saved_fails_closed(
    hass: HomeAssistant,
) -> None:
    """A reset that is not on disk is not reported as done."""
    store = await _store(hass, "reset-save-fails")
    await store.async_latch_emergency_stop("tent", "test", ("switch.pump",), "op")
    store._store.async_save = AsyncMock(side_effect=OSError("disk full"))

    with pytest.raises(OSError, match="disk full"):
        await store.async_reset_emergency_stop("tent", "op")

    assert store.unreadable
    with pytest.raises(RuntimeError, match="unreadable"):
        await store.async_set_control("tent", "automation", False, "op")
