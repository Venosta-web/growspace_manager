"""Tests for plant handler shared utilities."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.services.plant_utils import (
    _ensure_plant_loaded,
    _resolve_plant_id,
)
from homeassistant.exceptions import ServiceValidationError


def test_resolve_plant_id_no_dot_returns_unchanged() -> None:
    """Raw plant IDs (no dot) are returned as-is without touching hass."""
    hass = MagicMock()
    assert _resolve_plant_id(hass, "plant_abc123") == "plant_abc123"
    hass.states.get.assert_not_called()


def test_resolve_plant_id_entity_id_resolved_via_state() -> None:
    """Entity IDs (containing a dot) resolve to plant_id via state attributes."""
    hass = MagicMock()
    state = MagicMock()
    state.attributes = {"plant_id": "resolved_plant_1"}
    hass.data = {"entity_registry": MagicMock()}
    hass.states.get.return_value = state
    assert _resolve_plant_id(hass, "sensor.my_plant") == "resolved_plant_1"


def test_resolve_plant_id_no_state_returns_original() -> None:
    """When state is not found, returns the original entity_id unchanged."""
    hass = MagicMock()
    hass.data = {"entity_registry": MagicMock()}
    hass.states.get.return_value = None
    assert _resolve_plant_id(hass, "sensor.missing") == "sensor.missing"


def test_resolve_plant_id_state_without_plant_id_attr_returns_original() -> None:
    """When state has no plant_id attribute, returns the original entity_id."""
    hass = MagicMock()
    state = MagicMock()
    state.attributes = {}
    hass.data = {"entity_registry": MagicMock()}
    hass.states.get.return_value = state
    assert _resolve_plant_id(hass, "sensor.no_attr") == "sensor.no_attr"


@pytest.mark.asyncio
async def test_ensure_plant_loaded_plant_exists_returns_true() -> None:
    """When plant is already in coordinator, returns True without reloading."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.plants = {"p1": MagicMock()}
    result = await _ensure_plant_loaded(hass, coordinator, "p1")
    assert result is True
    coordinator.async_load.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_plant_loaded_reloads_and_finds_plant() -> None:
    """When plant is missing, reloads coordinator and returns True if found after reload."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.async_load = AsyncMock()

    loaded = {}

    async def side_effect() -> None:
        loaded["p1"] = MagicMock()
        coordinator.plants = loaded

    coordinator.plants = {}
    coordinator.async_load.side_effect = side_effect

    result = await _ensure_plant_loaded(hass, coordinator, "p1")
    assert result is True
    coordinator.async_load.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_plant_loaded_raises_when_still_missing_after_reload() -> None:
    """When plant is still absent after reload, raises ServiceValidationError."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.async_load = AsyncMock()
    coordinator.plants = {}

    with pytest.raises(ServiceValidationError, match="not found"):
        await _ensure_plant_loaded(hass, coordinator, "ghost_plant")
