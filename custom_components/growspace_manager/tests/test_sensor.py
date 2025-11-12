from datetime import date, timedelta
from unittest.mock import AsyncMock, Mock

import pytest

from ..sensor import (
    GrowspaceListSensor,
    GrowspaceOverviewSensor,
    PlantEntity,
    StrainLibrarySensor,
    async_setup_entry,
)


# --------------------
# Fixtures
# --------------------
@pytest.fixture
def mock_coordinator():
    coordinator = Mock()
    coordinator.hass = Mock()
    coordinator.growspaces = {
        "gs1": Mock(
            id="gs1",
            name="Growspace 1",
            rows=2,
            plants_per_row=2,
            notification_target="notify_me",
        ),
    }
    coordinator.plants = {
        "p1": Mock(
            plant_id="p1",
            growspace_id="gs1",
            strain="Strain A",
            phenotype="A",
            row=1,
            col=1,
            stage="veg",
            seedling_start=str(date.today() - timedelta(days=5)),
            veg_start=str(date.today() - timedelta(days=3)),
            flower_start=None,
            mother_start=None,
            clone_start=None,
            dry_start=None,
            cure_start=None,
        ),
    }
    coordinator.get_growspace_plants.return_value = list(coordinator.plants.values())
    coordinator.calculate_days_in_stage.side_effect = lambda plant, stage: 1
    coordinator.should_send_notification.return_value = True
    coordinator.mark_notification_sent = AsyncMock()
    coordinator.async_add_listener = Mock()
    coordinator.get_strain_options.return_value = ["Strain A", "Strain B"]
    coordinator.get_growspace_options.return_value = ["gs1"]
    return coordinator


# --------------------
# async_setup_entry
# --------------------
@pytest.mark.asyncio
async def test_async_setup_entry_adds_entities() -> None:
    hass = Mock()

    # Coordinator mock
    mock_coordinator = Mock()
    mock_coordinator.growspaces = {
        "gs1": Mock(id="gs1", name="Growspace 1", rows=2, plants_per_row=2),
    }
    mock_coordinator.get_growspace_plants = Mock(return_value=[])
    mock_coordinator.async_save = AsyncMock()
    mock_coordinator._ensure_special_growspace = Mock(
        side_effect=lambda x, y, rows, plants_per_row: x,
    )
    mock_coordinator.async_set_updated_data = AsyncMock()

    hass.data = {"growspace_manager": {"entry_1": {"coordinator": mock_coordinator}}}

    added_entities = []

    # Regular function, not async
    def async_add_entities(entities, update_before_add=False):
        added_entities.extend(entities)

    await async_setup_entry(hass, Mock(entry_id="entry_1"), async_add_entities)

    # Now entities should be added
    assert added_entities
    assert all(hasattr(e, "unique_id") for e in added_entities)


# --------------------
# GrowspaceOverviewSensor
# --------------------
def test_growspace_overview_sensor_state_and_attributes(mock_coordinator):
    gs = GrowspaceOverviewSensor(
        coordinator=mock_coordinator,
        growspace_id="gs1",
        growspace=mock_coordinator.growspaces["gs1"],
    )

    # State should return number of plants
    assert gs.state == 1

    attrs = gs.extra_state_attributes
    assert attrs["total_plants"] == 1
    assert "grid" in attrs
    # Grid positions
    assert attrs["grid"]["position_1_1"]["plant_id"] == "p1"


def test_growspace_overview_sensor_max_stage_attributes(mock_coordinator):
    """Test max stage attributes are included in GrowspaceOverviewSensor."""
    coordinator = mock_coordinator
    # Add two plants with veg and flower stages
    coordinator.plants = {
        "p1": Mock(
            plant_id="p1",
            growspace_id="gs1",
            strain="Strain A",
            phenotype="A",
            row=1,
            col=1,
            stage="veg",
            seedling_start=None,
            veg_start=str(date.today() - timedelta(days=10)),
            flower_start=None,
            mother_start=None,
            clone_start=None,
            dry_start=None,
            cure_start=None,
        ),
        "p2": Mock(
            plant_id="p2",
            growspace_id="gs1",
            strain="Strain B",
            phenotype="B",
            row=1,
            col=2,
            stage="flower",
            seedling_start=None,
            veg_start=str(date.today() - timedelta(days=30)),
            flower_start=str(date.today() - timedelta(days=15)),
            mother_start=None,
            clone_start=None,
            dry_start=None,
            cure_start=None,
        ),
    }
    coordinator.get_growspace_plants.return_value = list(coordinator.plants.values())

    gs = GrowspaceOverviewSensor(
        coordinator=coordinator,
        growspace_id="gs1",
        growspace=coordinator.growspaces["gs1"],
    )

    attrs = gs.extra_state_attributes

    assert "max_veg_days" in attrs
    assert "max_flower_days" in attrs
    assert "max_stage_summary" in attrs
    assert attrs["max_veg_days"] == 30
    assert attrs["max_flower_days"] == 15
    assert "Veg: 30d" in attrs["max_stage_summary"]
    assert "Flower: 15d" in attrs["max_stage_summary"]


def test_growspace_overview_sensor_max_stage_no_plants(mock_coordinator):
    coordinator = mock_coordinator
    coordinator.plants = {}
    coordinator.get_growspace_plants.return_value = []

    gs = GrowspaceOverviewSensor(
        coordinator=coordinator,
        growspace_id="gs1",
        growspace=coordinator.growspaces["gs1"],
    )

    attrs = gs.extra_state_attributes
    assert attrs["max_veg_days"] == 0
    assert attrs["max_flower_days"] == 0
    assert attrs["max_stage_summary"] == "Veg: 0d (W0), Flower: 0d (W0)"


# --------------------
# PlantEntity
# --------------------
def test_plant_entity_state_and_attributes(mock_coordinator):
    plant = list(mock_coordinator.plants.values())[0]
    entity = PlantEntity(mock_coordinator, plant)
    state = entity.state
    assert state in [
        "veg",
        "seedling",
        "flower",
        "dry",
        "cure",
        "clone",
        "mother",
        "unknown",
    ]

    attrs = entity.extra_state_attributes
    assert attrs["plant_id"] == plant.plant_id
    assert attrs["strain"] == plant.strain
    assert "veg_days" in attrs


# --------------------
# StrainLibrarySensor
# --------------------
def test_strain_library_sensor_state_and_attributes(mock_coordinator):
    sensor = StrainLibrarySensor(mock_coordinator)
    assert sensor.state == "ok"
    attrs = sensor.extra_state_attributes
    assert "strains" in attrs
    assert attrs["strains"] == ["Strain A", "Strain B"]


# --------------------
# GrowspaceListSensor
# --------------------
def test_growspace_list_sensor_state_and_attributes(mock_coordinator):
    sensor = GrowspaceListSensor(mock_coordinator)
    assert sensor.state == 1
    attrs = sensor.extra_state_attributes
    assert "growspaces" in attrs
    assert attrs["growspaces"] == ["gs1"]
