"""Tests for the Manual Watering feature.

This module contains tests for the `water_plant` and `water_growspace`
functionality, including coordinator methods, service handlers, and
sensor attribute integration.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant


def create_test_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Create a test coordinator with mocked config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    # Mock background task create to actually schedule the coroutine to avoid unawaited coroutines
    entry.async_create_background_task = MagicMock(
        side_effect=lambda _hass, coroutine, name: hass.async_create_task(coroutine)
    )

    coordinator = GrowspaceCoordinator(hass, entry, data={})
    coordinator.async_save = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


@pytest.fixture
def watering_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Provide a coordinator for watering tests with a growspace and plant."""
    coordinator = create_test_coordinator(hass)

    # Manually add a growspace and plant for testing
    coordinator.growspaces["test_gs"] = Growspace(
        id="test_gs",
        name="Test Growspace",
        rows=3,
        plants_per_row=3,
    )

    coordinator.plants["test_plant"] = Plant(
        plant_id="test_plant",
        growspace_id="test_gs",
        strain="Test Strain",
        phenotype="Phenotype A",
        row=1,
        col=1,
    )

    coordinator.plants["test_plant_2"] = Plant(
        plant_id="test_plant_2",
        growspace_id="test_gs",
        strain="Test Strain 2",
        phenotype="Phenotype B",
        row=2,
        col=1,
    )

    return coordinator


class TestAsyncWaterPlant:
    """Tests for the async_water_plant coordinator method."""

    @pytest.mark.asyncio
    async def test_water_plant_updates_last_watered(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a plant sets the last_watered timestamp."""
        plant_id = "test_plant"

        # Verify plant starts with no watering history
        assert watering_coordinator.plants[plant_id].last_watered is None

        # Water the plant
        await watering_coordinator.async_water_plant(plant_id, amount=1.5)

        # Verify last_watered is now set
        plant = watering_coordinator.plants[plant_id]
        assert plant.last_watered is not None

        # Verify it's a valid ISO timestamp
        parsed = datetime.fromisoformat(plant.last_watered)
        assert isinstance(parsed, datetime)

    @pytest.mark.asyncio
    async def test_water_plant_with_nutrients(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering a plant with nutrient information."""
        plant_id = "test_plant"
        nutrients = {"CalMag": 2.0, "Bloom": 3.5}

        # Water with nutrients
        await watering_coordinator.async_water_plant(
            plant_id, amount=2.0, nutrients=nutrients
        )

        # Verify plant was watered
        plant = watering_coordinator.plants[plant_id]
        assert plant.last_watered is not None

    @pytest.mark.asyncio
    async def test_water_plant_creates_event(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering creates a GrowspaceEvent."""
        plant_id = "test_plant"

        # Ensure events dict is initialized
        watering_coordinator.events = {}

        # Water the plant
        await watering_coordinator.async_water_plant(plant_id, amount=1.0)

        # Verify an event was created
        assert "test_gs" in watering_coordinator.events
        assert len(watering_coordinator.events["test_gs"]) == 1

        event = watering_coordinator.events["test_gs"][0]
        assert event.sensor_type == "irrigation"
        assert event.category == "environmental"
        assert "Plant: Test Strain (Phenotype A)" in event.reasons
        assert "Watered with 1.0L" in event.reasons

    @pytest.mark.asyncio
    async def test_water_plant_event_includes_nutrients(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering event includes nutrient information."""
        plant_id = "test_plant"
        nutrients = {"Nitrogen": 5.0}

        watering_coordinator.events = {}

        await watering_coordinator.async_water_plant(
            plant_id, amount=1.5, nutrients=nutrients
        )

        event = watering_coordinator.events["test_gs"][0]
        assert any("Nutrients:" in reason for reason in event.reasons)

    @pytest.mark.asyncio
    async def test_water_plant_nonexistent_raises(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a nonexistent plant raises an error."""
        from custom_components.growspace_manager.exceptions import PlantNotFoundError

        with pytest.raises(PlantNotFoundError):
            await watering_coordinator.async_water_plant("nonexistent", amount=1.0)


class TestAsyncWaterGrowspace:
    """Tests for the async_water_growspace coordinator method."""

    @pytest.mark.asyncio
    async def test_water_growspace_updates_all_plants(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a growspace updates all plants within it."""
        # Verify plants start with no watering history
        for plant_id in ["test_plant", "test_plant_2"]:
            assert watering_coordinator.plants[plant_id].last_watered is None

        # Water the growspace
        count = await watering_coordinator.async_water_growspace(
            "test_gs", amount_per_plant=2.0
        )

        # Verify all plants were watered
        assert count == 2
        for plant_id in ["test_plant", "test_plant_2"]:
            plant = watering_coordinator.plants[plant_id]
            assert plant.last_watered is not None

    @pytest.mark.asyncio
    async def test_water_growspace_with_nutrients(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering a growspace with nutrients updates all plants."""
        nutrients = {"PK": 4.0}

        count = await watering_coordinator.async_water_growspace(
            "test_gs", amount_per_plant=1.0, nutrients=nutrients
        )

        assert count == 2
        # All plants should have watering timestamps
        for plant_id in ["test_plant", "test_plant_2"]:
            assert watering_coordinator.plants[plant_id].last_watered is not None

    @pytest.mark.asyncio
    async def test_water_growspace_creates_events(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a growspace creates events for each plant."""
        watering_coordinator.events = {}

        await watering_coordinator.async_water_growspace(
            "test_gs", amount_per_plant=1.5
        )

        # Should have 2 events (one per plant)
        assert "test_gs" in watering_coordinator.events
        assert len(watering_coordinator.events["test_gs"]) == 2

    @pytest.mark.asyncio
    async def test_water_empty_growspace(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering an empty growspace returns 0."""
        # Add an empty growspace
        watering_coordinator.growspaces["empty_gs"] = Growspace(
            id="empty_gs", name="Empty", rows=2, plants_per_row=2
        )

        count = await watering_coordinator.async_water_growspace(
            "empty_gs", amount_per_plant=1.0
        )

        assert count == 0

    @pytest.mark.asyncio
    async def test_water_growspace_nonexistent_raises(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a nonexistent growspace raises an error."""
        from custom_components.growspace_manager.exceptions import (
            GrowspaceNotFoundError,
        )

        with pytest.raises(GrowspaceNotFoundError):
            await watering_coordinator.async_water_growspace(
                "nonexistent", amount_per_plant=1.0
            )


class TestPlantWateringDays:
    """Tests for the Plant.get_days_since_watering method."""

    def test_get_days_since_watering_none(self) -> None:
        """Test that get_days_since_watering returns None when never watered."""
        plant = Plant(
            plant_id="p1",
            growspace_id="gs1",
            strain="Test",
            last_watered=None,
        )

        assert plant.get_days_since_watering() is None

    def test_get_days_since_watering_today(self) -> None:
        """Test get_days_since_watering returns 0 for today."""
        now = datetime.now().isoformat()
        plant = Plant(
            plant_id="p1",
            growspace_id="gs1",
            strain="Test",
            last_watered=now,
        )

        days = plant.get_days_since_watering()
        assert days == 0

    def test_get_days_since_watering_past(self) -> None:
        """Test get_days_since_watering calculates correctly for past dates."""
        past = (datetime.now() - timedelta(days=3)).isoformat()
        plant = Plant(
            plant_id="p1",
            growspace_id="gs1",
            strain="Test",
            last_watered=past,
        )

        days = plant.get_days_since_watering()
        assert days == 3


class TestServiceHandlers:
    """Tests for the watering service handlers."""

    @pytest.mark.asyncio
    async def test_handle_water_plant(
        self, hass: HomeAssistant, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test the handle_water_plant service handler."""
        from custom_components.growspace_manager.services.irrigation_watering import (
            handle_water_plant,
        )

        # Create a mock service call
        call = MagicMock()
        call.data = {
            "plant_id": "test_plant",
            "amount": 2.0,
            "nutrients": {"CalMag": 1.5},
        }

        await handle_water_plant(hass, watering_coordinator, call)

        # Verify plant was watered
        assert watering_coordinator.plants["test_plant"].last_watered is not None

    @pytest.mark.asyncio
    async def test_handle_water_growspace(
        self, hass: HomeAssistant, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test the handle_water_growspace service handler."""
        from custom_components.growspace_manager.services.irrigation_watering import (
            handle_water_growspace,
        )

        # Create a mock service call
        call = MagicMock()
        call.data = {
            "growspace_id": "test_gs",
            "amount_per_plant": 1.5,
            "nutrients": None,
        }

        result = await handle_water_growspace(hass, watering_coordinator, call)

        # Verify result
        assert result == {"plants_watered": 2}


class TestPlantEntityWateringAttributes:
    """Tests for watering attributes in PlantEntity."""

    @pytest.mark.asyncio
    async def test_plant_entity_extra_state_attributes_watering(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that PlantEntity exposes watering attributes correctly."""
        from custom_components.growspace_manager.sensor import PlantEntity

        # Water the plant first
        await watering_coordinator.async_water_plant("test_plant", amount=1.0)

        # Create a PlantEntity
        plant = watering_coordinator.plants["test_plant"]
        entity = PlantEntity(watering_coordinator, plant)

        # Get extra state attributes
        attributes = entity.extra_state_attributes

        # Verify watering attributes are present
        assert "last_watered" in attributes
        assert "days_since_last_watering" in attributes
        assert attributes["last_watered"] is not None
        assert attributes["days_since_last_watering"] == 0

    @pytest.mark.asyncio
    async def test_plant_entity_no_watering_history(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test PlantEntity shows None when plant was never watered."""
        from custom_components.growspace_manager.sensor import PlantEntity

        # Create a PlantEntity without watering
        plant = watering_coordinator.plants["test_plant"]
        entity = PlantEntity(watering_coordinator, plant)

        # Get extra state attributes
        attributes = entity.extra_state_attributes

        # Verify watering attributes show no history
        assert attributes["last_watered"] is None
        assert attributes["days_since_last_watering"] is None
