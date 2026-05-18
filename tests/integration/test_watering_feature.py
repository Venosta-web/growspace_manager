"""Tests for the Manual Watering feature.

This module contains tests for the `water_plant` and `water_growspace`
functionality, including coordinator methods, service handlers, and
sensor attribute integration.
"""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

from .common import create_plant
import pytest
from tests.common import (
    MockConfigEntry,
    async_capture_events,
)

from custom_components.growspace_manager.const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
)
from custom_components.growspace_manager.models import Growspace
from custom_components.growspace_manager.sensor import PlantEntity
from custom_components.growspace_manager.services.irrigation_watering import (
    handle_water_growspace,
    handle_water_plant,
)
from homeassistant.core import HomeAssistant


def create_test_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Create a test coordinator with mocked config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    # Mock background task create to actually schedule the coroutine to avoid unawaited coroutines
    entry.async_create_background_task = MagicMock(
        side_effect=lambda _hass, coroutine, name: hass.async_create_task(coroutine)
    )

    coordinator = GrowspaceCoordinator(hass, entry, data={})
    coordinator.async_save = AsyncMock()  # type: ignore[method-assign]
    coordinator.async_commit = AsyncMock()  # type: ignore[method-assign]
    coordinator.async_set_updated_data = MagicMock()
    # Mock services.save to be an AsyncMock for assertions and functionality
    coordinator.services.save = AsyncMock(side_effect=coordinator.async_commit)
    # Mock save callback on watering service since it now handles saves
    coordinator._watering_service.save_callback = coordinator.services.save
    return coordinator


@pytest.fixture
def watering_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Provide a coordinator for watering tests with a growspace and plant."""
    coordinator = create_test_coordinator(hass)

    # Manually add a growspace and plant for testing
    coordinator.data_repository.add_growspace(Growspace(
        id="test_gs",
        name="Test Growspace",
        rows=3,
        plants_per_row=3,
    ))

    coordinator.data_repository.add_plant(create_plant(
        plant_id="test_plant",
        growspace_id="test_gs",
        strain="Test Strain",
        phenotype="Phenotype A",
        row=1,
        col=1,
    ))

    coordinator.data_repository.add_plant(create_plant(
        plant_id="test_plant_2",
        growspace_id="test_gs",
        strain="Test Strain 2",
        phenotype="Phenotype B",
        row=2,
        col=1,
    ))

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
        await watering_coordinator.services.water_plant(plant_id, amount=1.5)

        # Verify last_watered is now set
        plant = watering_coordinator.plants[plant_id]
        assert plant.last_watered is not None

        # Verify it's a valid ISO timestamp
        parsed = datetime.fromisoformat(plant.last_watered)
        assert isinstance(parsed, datetime)

        # Verify save was called to persist the change
        assert watering_coordinator.services.save.called  # type: ignore[attr-defined]
        assert watering_coordinator.services.save.call_count == 1  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_water_plant_with_nutrients(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering a plant with nutrient information."""
        plant_id = "test_plant"
        nutrients = {"CalMag": 2.0, "Bloom": 3.5}

        # Water with nutrients
        await watering_coordinator.services.water_plant(
            plant_id, amount=2.0, nutrients=nutrients
        )

        # Verify plant was watered
        plant = watering_coordinator.plants[plant_id]
        assert plant.last_watered is not None

    @pytest.mark.asyncio
    async def test_water_plant_creates_event(
        self, hass: HomeAssistant, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering creates a GrowspaceEvent."""
        plant_id = "test_plant"

        # Capture events
        events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

        # Water the plant
        await watering_coordinator.services.water_plant(plant_id, amount=1.0)

        # Verify an event was created
        assert len(events) == 1
        event_data = events[0].data

        assert event_data["sensor_type"] == "irrigation"
        assert event_data["category"] == "watering"
        assert "Watered with 1.0L" in str(event_data.get("reasons", []))

    @pytest.mark.asyncio
    async def test_water_plant_event_includes_nutrients(
        self, hass: HomeAssistant, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering event includes nutrient information."""
        plant_id = "test_plant"
        nutrients = {"Nitrogen": 5.0}

        events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

        await watering_coordinator.services.water_plant(
            plant_id, amount=1.5, nutrients=nutrients
        )

        assert len(events) == 1
        event_data = events[0].data
        reasons = str(event_data.get("reasons", []))
        assert "Nutrients:" in reasons

    @pytest.mark.asyncio
    async def test_water_plant_nonexistent_raises(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a nonexistent plant raises an error."""

        with pytest.raises(PlantNotFoundError):
            await watering_coordinator.services.water_plant("nonexistent", amount=1.0)


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
        count = await watering_coordinator.services.water_growspace(
            "test_gs", amount_per_plant=2.0
        )

        # Verify all plants were watered
        assert count == 2
        for plant_id in ["test_plant", "test_plant_2"]:
            plant = watering_coordinator.plants[plant_id]
            assert plant.last_watered is not None

        # Verify save was called ensures persistence
        assert watering_coordinator.services.save.called  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_water_growspace_with_nutrients(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering a growspace with nutrients updates all plants."""
        nutrients = {"PK": 4.0}

        count = await watering_coordinator.services.water_growspace(
            "test_gs", amount_per_plant=1.0, nutrients=nutrients
        )

        assert count == 2
        # All plants should have watering timestamps
        for plant_id in ["test_plant", "test_plant_2"]:
            assert watering_coordinator.plants[plant_id].last_watered is not None

    @pytest.mark.asyncio
    async def test_water_growspace_creates_events(
        self, hass: HomeAssistant, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a growspace creates events for each plant."""
        events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)

        await watering_coordinator.services.water_growspace(
            "test_gs", amount_per_plant=1.5
        )

        # Should have 2 events (one per plant)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_water_empty_growspace(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering an empty growspace returns 0."""
        # Add an empty growspace
        watering_coordinator.data_repository.add_growspace(
            Growspace(id="empty_gs", name="Empty", rows=2, plants_per_row=2)
        )

        count = await watering_coordinator.services.water_growspace(
            "empty_gs", amount_per_plant=1.0
        )

        assert count == 0

    @pytest.mark.asyncio
    async def test_water_growspace_nonexistent_raises(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a nonexistent growspace raises an error."""

        with pytest.raises(GrowspaceNotFoundError):
            await watering_coordinator.services.water_growspace(
                "nonexistent", amount_per_plant=1.0
            )


class TestPlantWateringDays:
    """Tests for the Plant.get_days_since_watering method."""

    def test_get_days_since_watering_none(self) -> None:
        """Test that get_days_since_watering returns None when never watered."""
        plant = create_plant(
            plant_id="p1",
            growspace_id="gs1",
            strain="Test",
            last_watered=None,
        )

        assert plant.get_days_since_watering() is None

    def test_get_days_since_watering_today(self) -> None:
        """Test get_days_since_watering returns 0 for today."""
        now = datetime.now().isoformat()
        plant = create_plant(
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
        plant = create_plant(
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

        # Water the plant first
        await watering_coordinator.services.water_plant("test_plant", amount=1.0)

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

        # Create a PlantEntity without watering
        plant = watering_coordinator.plants["test_plant"]
        entity = PlantEntity(watering_coordinator, plant)

        # Get extra state attributes
        attributes = entity.extra_state_attributes

        # Verify watering attributes show no history
        assert attributes["last_watered"] is None
        assert attributes["days_since_last_watering"] is None
