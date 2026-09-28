"""Tests for the Manual Watering feature.

This module contains tests for the `water_plant` and `water_growspace`
functionality, including coordinator methods, service handlers, and
sensor attribute integration.
"""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import DOMAIN, EVENT_GROWSPACE_LOG_ENTRY
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.water_aggregation import (
    compute_growspace_water,
)
from custom_components.growspace_manager.exceptions import (
    GrowspaceError,
    GrowspaceNotFoundError,
    PlantNotFoundError,
)
from custom_components.growspace_manager.models import Growspace, IrrigationTank
from custom_components.growspace_manager.sensor import PlantEntity
from custom_components.growspace_manager.services.irrigation_watering import (
    handle_water_growspace,
    handle_water_plant,
)
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry, async_capture_events

from .common import create_plant


def create_test_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Create a test coordinator with mocked config entry."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)

    # Mock background task create to actually schedule the coroutine to avoid unawaited coroutines
    entry.async_create_background_task = MagicMock(
        side_effect=lambda _hass, coroutine, name: hass.async_create_task(coroutine)
    )

    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    coordinator.async_commit = AsyncMock()  # type: ignore[method-assign]
    coordinator.async_set_updated_data = MagicMock()
    return coordinator


@pytest.fixture
def watering_coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """Provide a coordinator for watering tests with a growspace and plant."""
    coordinator = create_test_coordinator(hass)

    # Manually add a growspace and plant for testing
    coordinator._data_repository.add_growspace(
        Growspace(
            id="test_gs",
            name="Test Growspace",
            rows=3,
            plants_per_row=3,
        )
    )

    coordinator._data_repository.add_plant(
        create_plant(
            plant_id="test_plant",
            growspace_id="test_gs",
            strain="Test Strain",
            phenotype="Phenotype A",
            row=1,
            col=1,
        )
    )

    coordinator._data_repository.add_plant(
        create_plant(
            plant_id="test_plant_2",
            growspace_id="test_gs",
            strain="Test Strain 2",
            phenotype="Phenotype B",
            row=2,
            col=1,
        )
    )

    return coordinator


class TestAsyncWaterPlant:
    """Tests for the async_water_plant coordinator method."""

    @pytest.mark.asyncio
    async def test_report_identity_and_actor_are_persisted(
        self, hass: HomeAssistant, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
        await watering_coordinator.services.plants.water_plant(
            "test_plant",
            amount=1.25,
            user_id="ha-user",
            from_monitored_tank=True,
        )
        reading = watering_coordinator.growspaces["test_gs"].water_usage.daily_readings[
            0
        ]
        assert reading["watering_id"]
        assert reading["user_id"] == "ha-user"
        assert reading["plant_id"] == "test_plant"
        assert reading["from_monitored_tank"] is True
        assert events[0].data["watering_id"] == reading["watering_id"]
        assert events[0].data["user_id"] == "ha-user"
        assert events[0].data["start_time"] == reading["watered_at"]

    @pytest.mark.asyncio
    async def test_report_time_bounds(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        now = dt_util.now()
        await watering_coordinator.services.plants.water_plant(
            "test_plant", 1.0, watered_at=(now - timedelta(days=7)).isoformat()
        )
        for invalid in (now - timedelta(days=7, seconds=1), now + timedelta(seconds=1)):
            with pytest.raises(GrowspaceError):
                await watering_coordinator.services.plants.water_plant(
                    "test_plant", 1.0, watered_at=invalid.isoformat()
                )
        with pytest.raises(GrowspaceError):
            await watering_coordinator.services.plants.water_plant(
                "test_plant", 1.0, watered_at="2026-01-10T10:00:00"
            )
        assert (
            len(watering_coordinator.growspaces["test_gs"].water_usage.daily_readings)
            == 1
        )

    @pytest.mark.asyncio
    async def test_late_report_uses_earlier_local_day_without_abandoning_feedback(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        irrigation = MagicMock()
        watering_coordinator._subsystem_manager.irrigation_coordinators["test_gs"] = (
            irrigation
        )
        now = datetime(2026, 1, 12, 0, 5, tzinfo=UTC)
        past = datetime(2026, 1, 11, 23, 55, tzinfo=UTC)
        watering_coordinator.plants["test_plant"].last_watered = now.isoformat()
        with patch(
            "custom_components.growspace_manager.services.watering_service.dt_util.now",
            return_value=now,
        ):
            await watering_coordinator.services.plants.water_plant(
                "test_plant", 1.0, watered_at=past.isoformat()
            )
        reading = watering_coordinator.growspaces["test_gs"].water_usage.daily_readings[
            0
        ]
        assert reading["date"] == dt_util.as_local(past).date().isoformat()
        assert watering_coordinator.plants["test_plant"].last_watered == now.isoformat()
        irrigation.abandon_pending_observation.assert_not_called()

    @pytest.mark.asyncio
    async def test_date_only_last_watered_does_not_regress(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        plant = watering_coordinator.plants["test_plant"]
        plant.last_watered = "2026-01-12"
        now = datetime(2026, 1, 12, 13, 0, tzinfo=UTC)
        with patch(
            "custom_components.growspace_manager.services.watering_service.dt_util.now",
            return_value=now,
        ):
            await watering_coordinator.services.plants.water_plant(
                "test_plant", 1.0, watered_at="2026-01-11T13:00:00+00:00"
            )
        assert plant.last_watered == "2026-01-12"

    @pytest.mark.asyncio
    async def test_monitored_tank_report_is_excluded_from_tank_figures(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        growspace = watering_coordinator.growspaces["test_gs"]
        growspace.environment_config.irrigation_tanks = [
            IrrigationTank(sensor_entity="sensor.tank", volume_liters=200.0)
        ]
        await watering_coordinator.services.plants.water_plant(
            "test_plant", 2.0, from_monitored_tank=True
        )
        await watering_coordinator.services.plants.water_plant("test_plant_2", 1.0)
        tracker = MagicMock()
        tracker.get_total_liters_today.return_value = 4.0
        tracker.get_total_liters_since.return_value = 10.0
        figures = compute_growspace_water(growspace, [tracker])
        assert figures.today == 5.0
        assert figures.cycle == 11.0
        growspace.environment_config.irrigation_tanks = []
        assert compute_growspace_water(growspace, []).today == 3.0

    @pytest.mark.asyncio
    async def test_hand_watering_abandons_pending_feedback(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        irrigation = MagicMock()
        watering_coordinator._subsystem_manager.irrigation_coordinators["test_gs"] = (
            irrigation
        )
        await watering_coordinator.services.plants.water_plant("test_plant", amount=1.0)
        irrigation.abandon_pending_observation.assert_called_once_with()

    @pytest.mark.asyncio
    async def test_water_plant_updates_last_watered(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a plant sets the last_watered timestamp."""
        plant_id = "test_plant"

        # Verify plant starts with no watering history
        assert watering_coordinator.plants[plant_id].last_watered is None

        # Water the plant
        await watering_coordinator.services.plants.water_plant(plant_id, amount=1.5)

        # Verify last_watered is now set
        plant = watering_coordinator.plants[plant_id]
        assert plant.last_watered is not None

        # Verify it's a valid ISO timestamp
        parsed = datetime.fromisoformat(plant.last_watered)
        assert isinstance(parsed, datetime)

        # Verify save was called to persist the change
        assert watering_coordinator.async_commit.called  # type: ignore[attr-defined]
        assert watering_coordinator.async_commit.call_count == 1  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_water_plant_with_nutrients(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering a plant with nutrient information."""
        plant_id = "test_plant"
        nutrients = {"CalMag": 2.0, "Bloom": 3.5}

        # Water with nutrients
        await watering_coordinator.services.plants.water_plant(
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
        await watering_coordinator.services.plants.water_plant(plant_id, amount=1.0)

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

        await watering_coordinator.services.plants.water_plant(
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
            await watering_coordinator.services.plants.water_plant(
                "nonexistent", amount=1.0
            )


class TestAsyncWaterGrowspace:
    """Tests for the async_water_growspace coordinator method."""

    @pytest.mark.asyncio
    async def test_bulk_report_splits_amount_and_ids_by_plant(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        count = await watering_coordinator.services.growspaces.water_growspace(
            "test_gs",
            amount=3.0,
            watered_at=(dt_util.now() - timedelta(days=1)).isoformat(),
            user_id="ha-user",
            from_monitored_tank=True,
        )
        assert count == 2
        readings = watering_coordinator.growspaces["test_gs"].water_usage.daily_readings
        assert {item["plant_id"] for item in readings} == {"test_plant", "test_plant_2"}
        assert len({item["watering_id"] for item in readings}) == 2
        assert all(item["liters"] == 1.5 for item in readings)
        assert all(item["user_id"] == "ha-user" for item in readings)

    @pytest.mark.asyncio
    async def test_water_growspace_updates_all_plants(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a growspace updates all plants within it."""
        # Verify plants start with no watering history
        for plant_id in ["test_plant", "test_plant_2"]:
            assert watering_coordinator.plants[plant_id].last_watered is None

        # Water the growspace
        count = await watering_coordinator.services.growspaces.water_growspace(
            "test_gs", amount_per_plant=2.0
        )

        # Verify all plants were watered
        assert count == 2
        for plant_id in ["test_plant", "test_plant_2"]:
            plant = watering_coordinator.plants[plant_id]
            assert plant.last_watered is not None

        # Verify save was called ensures persistence
        assert watering_coordinator.async_commit.called  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_water_growspace_with_nutrients(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test watering a growspace with nutrients updates all plants."""
        nutrients = {"PK": 4.0}

        count = await watering_coordinator.services.growspaces.water_growspace(
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

        await watering_coordinator.services.growspaces.water_growspace(
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
        watering_coordinator._data_repository.add_growspace(
            Growspace(id="empty_gs", name="Empty", rows=2, plants_per_row=2)
        )

        count = await watering_coordinator.services.growspaces.water_growspace(
            "empty_gs", amount_per_plant=1.0
        )

        assert count == 0

    @pytest.mark.asyncio
    async def test_water_growspace_nonexistent_raises(
        self, watering_coordinator: GrowspaceCoordinator
    ) -> None:
        """Test that watering a nonexistent growspace raises an error."""

        with pytest.raises(GrowspaceNotFoundError):
            await watering_coordinator.services.growspaces.water_growspace(
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
            "from_monitored_tank": True,
        }
        call.context.user_id = "ha-user"

        await handle_water_plant(hass, watering_coordinator, call)

        # Verify plant was watered
        assert watering_coordinator.plants["test_plant"].last_watered is not None
        reading = watering_coordinator.growspaces["test_gs"].water_usage.daily_readings[
            0
        ]
        assert reading["user_id"] == "ha-user"
        assert reading["from_monitored_tank"] is True

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
        call.context.user_id = "ha-user"

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
        await watering_coordinator.services.plants.water_plant("test_plant", amount=1.0)

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
