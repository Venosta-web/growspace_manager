"""Coverage-focused tests for GrowspaceService."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.exceptions import GrowspaceNotFoundError
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    Growspace,
    GrowspaceType,
    Plant,
)
from custom_components.growspace_manager.services.growspace_service import (
    GrowspaceService,
)


@pytest.fixture
def mock_coordinator():
    """Mock coordinator."""
    coordinator = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.notifications_enabled = {}
    coordinator.lock = AsyncMock()
    coordinator.async_commit = AsyncMock()
    coordinator.validator = MagicMock()
    coordinator.cache = MagicMock()
    coordinator.view_model_builder = MagicMock()
    coordinator.canonical_special.side_effect = lambda x: (x, x)
    return coordinator


@pytest.fixture
def service(mock_coordinator):
    """GrowspaceService fixture."""
    return GrowspaceService(mock_coordinator)


@pytest.mark.asyncio
async def test_add_growspace_no_notification_target(service, mock_coordinator) -> None:
    """Test add_growspace with empty notification target."""
    await service.add_growspace("Test", notification_target="")
    gs = list(mock_coordinator.growspaces.values())[0]
    assert gs.notification_target is None


@pytest.mark.asyncio
async def test_update_growspace_no_changes(service, mock_coordinator) -> None:
    """Test update_growspace with no changes."""
    gs = Growspace(id="gs1", name="Test")
    mock_coordinator.growspaces = {"gs1": gs}
    await service.update_growspace("gs1")
    mock_coordinator.async_commit.assert_not_called()


@pytest.mark.asyncio
async def test_resize_growspace_with_invalid_plants(service, mock_coordinator) -> None:
    """Test resizing growspace when plants become out of bounds."""
    gs = Growspace(id="gs1", name="Test", rows=2, plants_per_row=2)
    mock_coordinator.growspaces = {"gs1": gs}

    plant = Plant(plant_id="p1", growspace_id="gs1", row=2, col=2)
    mock_coordinator.get_growspace_plants.return_value = [plant]

    # Resize to 1x1
    await service.update_growspace("gs1", rows=1, plants_per_row=1)
    # Should log warning (we just verify it completes)
    assert gs.rows == 1
    assert gs.plants_per_row == 1


def test_generate_unique_name(service, mock_coordinator) -> None:
    """Test unique name generation."""
    mock_coordinator.growspaces = {
        "gs1": Growspace(id="gs1", name="Test"),
        "gs2": Growspace(id="gs2", name="Test 1"),
    }
    assert service.generate_unique_name("Test") == "Test 2"
    assert service.generate_unique_name("New") == "New"


def test_get_sorted_growspace_options(service, mock_coordinator) -> None:
    """Test getting sorted growspace options."""
    mock_coordinator.growspaces = {
        "gs1": Growspace(id="gs1", name="B"),
        "gs2": Growspace(id="gs2", name="A"),
    }
    options = service.get_sorted_growspace_options()
    assert options == [("gs2", "A"), ("gs1", "B")]


def test_ensure_special_growspace_existing_migrate_type(
    service, mock_coordinator
) -> None:
    """Test ensure_special_growspace updating type for existing one."""
    gs = Growspace(id="dry", name="dry", growspace_type=GrowspaceType.FLOWER)
    mock_coordinator.growspaces = {"dry": gs}

    service.ensure_special_growspace("dry", "dry", growspace_type=GrowspaceType.DRY)
    assert gs.growspace_type == GrowspaceType.DRY


def test_ensure_calculated_sensors_padding(service, mock_coordinator) -> None:
    """Test ensure_calculated_sensors padding and updating singular."""
    env = EnvironmentConfig(
        temperature_sensors=["sensor.t1", "sensor.t2"],
        humidity_sensors=["sensor.h1", "sensor.h2"],
        vpd_sensors=["sensor.v1"],  # Only 1, needs padding
    )
    gs = Growspace(id="gs1", name="GS", environment_config=env)
    mock_coordinator.growspaces = {"gs1": gs}

    service.ensure_calculated_sensors()
    assert len(env.vpd_sensors) == 2
    assert env.vpd_sensors[1] == "sensor.gs_calculated_vpd_2"
    assert env.vpd_sensor == "sensor.v1"  # singular should match index 0


def test_ensure_calculated_sensors_no_sensors(service, mock_coordinator) -> None:
    """Test ensure_calculated_sensors with no env config."""
    gs = Growspace(id="gs1", name="GS", environment_config=None)
    mock_coordinator.growspaces = {"gs1": gs}
    service.ensure_calculated_sensors()
    # Should not crash


@pytest.mark.asyncio
async def test_remove_growspace(service, mock_coordinator) -> None:
    """Test removing a growspace."""
    gs = Growspace(id="gs1", name="Test")
    mock_coordinator.growspaces = {"gs1": gs}
    mock_coordinator.plants = {"p1": Plant(plant_id="p1", growspace_id="gs1")}
    mock_coordinator.notifications_enabled = {"gs1": True}

    with patch("homeassistant.helpers.device_registry.async_get") as mock_dr:
        mock_dr.return_value.async_get_device.return_value = MagicMock(id="dev1")
        await service.remove_growspace("gs1")

        assert "gs1" not in mock_coordinator.growspaces
        assert "p1" not in mock_coordinator.plants
        assert "gs1" not in mock_coordinator.notifications_enabled
        mock_dr.return_value.async_remove_device.assert_called_once_with("dev1")


@pytest.mark.asyncio
async def test_update_growspace_not_found(service, mock_coordinator) -> None:
    """Test update_growspace with non-existent ID."""

    with pytest.raises(GrowspaceNotFoundError):
        await service.update_growspace("unknown")


@pytest.mark.asyncio
async def test_update_growspace_full_config(service, mock_coordinator) -> None:
    """Test updating all config fields of a growspace."""
    gs = Growspace(id="gs1", name="Old")
    mock_coordinator.growspaces = {"gs1": gs}

    await service.update_growspace(
        "gs1",
        name="New",
        notification_target="mobile",
        environment_config={"foo": "bar"},
        irrigation_config={"baz": "qux"},
        dimensions={"h": 1},
    )

    assert gs.name == "New"
    assert gs.notification_target == "mobile"
    assert gs.environment_config == {"foo": "bar"}
    assert gs.irrigation_config == {"baz": "qux"}
    assert gs.dimensions == {"h": 1}


@pytest.mark.asyncio
async def test_ensure_default_growspaces(service, mock_coordinator) -> None:
    """Test ensuring default growspaces."""
    await service.ensure_default_growspaces()
    assert "dry" in mock_coordinator.growspaces
    assert "cure" in mock_coordinator.growspaces
    assert "mother" in mock_coordinator.growspaces
    assert "clone" in mock_coordinator.growspaces
    assert "veg" in mock_coordinator.growspaces
    mock_coordinator.view_model_builder.build_data_property.assert_called_once()


@pytest.mark.asyncio
async def test_add_growspace_with_configs(service, mock_coordinator) -> None:
    """Test add_growspace with optional configs."""
    await service.add_growspace(
        "Test",
        dimensions={"h": 200},
        environment_config={"temp": "sensor.t1"},
        irrigation_config={"pump": "switch.p1"},
    )
    gs = list(mock_coordinator.growspaces.values())[0]
    assert gs.dimensions == {"h": 200}
    assert gs.environment_config == {"temp": "sensor.t1"}
    assert gs.irrigation_config == {"pump": "switch.p1"}


@pytest.mark.asyncio
async def test_remove_growspace_registry_error(service, mock_coordinator) -> None:
    """Test remove_growspace when registry throws."""
    gs = Growspace(id="gs1", name="Test")
    mock_coordinator.growspaces = {"gs1": gs}

    with patch("homeassistant.helpers.device_registry.async_get") as mock_dr:
        mock_dr.side_effect = Exception("Registry fail")
        await service.remove_growspace("gs1")
        # Should not raise
        assert "gs1" not in mock_coordinator.growspaces


def test_get_growspace_options(service, mock_coordinator) -> None:
    """Test get_growspace_options."""
    mock_coordinator.growspaces = {"gs1": Growspace(id="gs1", name="Test")}
    assert service.get_growspace_options() == {"gs1": "Test"}


def test_ensure_mother_growspace(service, mock_coordinator) -> None:
    """Test ensure_mother_growspace."""
    with patch.object(
        service, "ensure_special_growspace", return_value="mother"
    ) as mock_ens:
        assert service.ensure_mother_growspace() == "mother"
        mock_ens.assert_called_once()


def test_ensure_calculated_sensors_legacy_sync(service, mock_coordinator) -> None:
    """Test ensure_calculated_sensors syncing from legacy singular fields."""
    env = EnvironmentConfig(
        temperature_sensor="sensor.t1",
        humidity_sensor="sensor.h1",
        vpd_sensor="sensor.v1",
    )
    # Post init should have synced them to plural, but we can force it
    env.temperature_sensors = []  # Force empty plural
    env.humidity_sensors = []
    env.vpd_sensors = []  # Force empty plural

    gs = Growspace(id="gs1", name="GS", environment_config=env)
    mock_coordinator.growspaces = {"gs1": gs}

    service.ensure_calculated_sensors()
    # It should have used vpd_sensor to populate vpd_sensors first
    assert "sensor.v1" in env.vpd_sensors


def test_ensure_calculated_sensors_missing_singular(service, mock_coordinator) -> None:
    """Test ensure_calculated_sensors with missing humidity sensors."""
    env = EnvironmentConfig(
        temperature_sensors=["sensor.t1"],
        humidity_sensors=[],
    )
    gs = Growspace(id="gs1", name="GS", environment_config=env)
    mock_coordinator.growspaces = {"gs1": gs}
    service.ensure_calculated_sensors()
    assert not env.vpd_sensors


def test_ensure_calculated_sensors_vpd_sync(service, mock_coordinator) -> None:
    """Test ensure_calculated_sensors syncing vpd_sensor if plural is empty."""
    env = EnvironmentConfig(
        temperature_sensors=["sensor.t1"],
        humidity_sensors=["sensor.h1"],
        vpd_sensors=[],
        vpd_sensor="sensor.v1",
    )
    gs = Growspace(id="gs1", name="GS", environment_config=env)
    mock_coordinator.growspaces = {"gs1": gs}

    service.ensure_calculated_sensors()
    # It should have used vpd_sensor since vpd_sensors was empty
    assert env.vpd_sensors[0] == "sensor.v1"


def test_update_special_growspace_name_logic(service, mock_coordinator) -> None:
    """Test direct call to _update_special_growspace_name with different name."""
    gs = Growspace(id="dry", name="Old")
    mock_coordinator.growspaces = {"dry": gs}
    service._update_special_growspace_name("dry", "New")
    assert gs.name == "New"
