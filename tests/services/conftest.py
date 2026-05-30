import asyncio
import inspect
from unittest.mock import AsyncMock, MagicMock, Mock, patch

from freezegun import freeze_time as fg_freeze_time
import pytest

from custom_components.growspace_manager.date_time_helper import DateTimeHelper
from custom_components.growspace_manager.services.facade import ServiceFacade


@pytest.fixture(autouse=True)
def freeze_time():
    """Freeze time to a fixed value to avoid off-by-one date errors."""
    with fg_freeze_time("2026-01-12 12:00:00"):
        yield


@pytest.fixture
def mock_coordinator(mock_plant, mock_growspace):
    """Create a comprehensive mock coordinator with all services mocked."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.data = {}
    coordinator.options = {}

    # Initialize managers
    coordinator.storage_manager = MagicMock()
    coordinator.data_repository = MagicMock()
    coordinator.plant_manager = MagicMock()
    coordinator.growspace_manager = MagicMock()
    coordinator.special_growspace_manager = MagicMock()
    coordinator.clone_manager = MagicMock()
    coordinator.nutrient_manager = MagicMock()
    coordinator.training_manager = MagicMock()
    coordinator.harvest_manager = MagicMock()
    
    # Other services
    coordinator.watering_service = MagicMock()
    coordinator.ipm_service = MagicMock()
    coordinator.training_service = MagicMock()
    coordinator.notification_manager = MagicMock()
    coordinator.strain_library = MagicMock()
    coordinator.subsystem_manager = MagicMock()

    # Initialize plant_manager methods as AsyncMock
    coordinator.plant_manager.add_plant = AsyncMock()
    coordinator.plant_manager.update_plant = AsyncMock()
    coordinator.plant_manager.remove_plant = AsyncMock()
    coordinator.plant_manager.take_clones = AsyncMock()
    coordinator.plant_manager.promote_clone = AsyncMock()
    coordinator.plant_manager.switch_plants = AsyncMock()
    coordinator.plant_manager.move_plant = AsyncMock()
    coordinator.plant_manager.transition_plant = AsyncMock()
    coordinator.plant_manager.archive_plant = AsyncMock()
    coordinator.plant_manager.kill_plant = AsyncMock()
    coordinator.plant_manager.transition_plant_stage = AsyncMock()
    coordinator.plant_manager.log_growth_stage = AsyncMock()
    coordinator.plant_manager.log_observation = AsyncMock()
    coordinator.plant_manager.add_mother_plant = AsyncMock()

    # Initialize growspace_manager methods as AsyncMock
    coordinator.growspace_manager.add_growspace = AsyncMock()
    coordinator.growspace_manager.update_growspace = AsyncMock()
    coordinator.growspace_manager.remove_growspace = AsyncMock()
    coordinator.growspace_manager.add_subarea = AsyncMock()
    coordinator.growspace_manager.update_subarea = AsyncMock()
    coordinator.growspace_manager.remove_subarea = AsyncMock()
    coordinator.growspace_manager.update_environment_config = AsyncMock()

    # Initialize nutrient_manager methods as AsyncMock
    coordinator.nutrient_manager.async_save_nutrient_preset = AsyncMock()
    coordinator.nutrient_manager.async_remove_nutrient_preset = AsyncMock()
    coordinator.nutrient_manager.async_save_ec_ramp_curve = AsyncMock()
    coordinator.nutrient_manager.async_remove_ec_ramp_curve = AsyncMock()

    # Other async methods
    coordinator.async_commit = AsyncMock()
    coordinator.async_load = AsyncMock()
    coordinator.async_save = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()
    coordinator.watering_service.async_water_plant = AsyncMock()
    coordinator.watering_service.async_water_growspace = AsyncMock()
    coordinator.ipm_service.async_save_ipm_preset = AsyncMock()
    coordinator.ipm_service.async_remove_ipm_preset = AsyncMock()
    coordinator.ipm_service.async_apply_ipm = AsyncMock()
    coordinator.training_service.async_log_training_event = AsyncMock()
    coordinator.notification_manager.async_send_notification = AsyncMock()
    coordinator.strain_library.clear = AsyncMock()
    coordinator.subsystem_manager.async_setup_growspace_sub_coordinators = AsyncMock()

    # Link data_repository methods to local mocks so ServiceFacade sees them
    mock_get_growspace_plants = MagicMock(
        name="get_growspace_plants",
        side_effect=lambda gid: [p for p in coordinator.plants.values() if p.growspace_id == gid]
    )
    mock_get_plant = MagicMock(
        name="get_plant",
        side_effect=lambda pid: coordinator.plants.get(pid)
    )
    mock_get_growspace = MagicMock(
        name="get_growspace",
        side_effect=lambda gid: coordinator.growspaces.get(gid)
    )
    mock_get_subareas = MagicMock(name="get_subareas", return_value=[])

    coordinator.data_repository.get_growspace_plants = mock_get_growspace_plants
    coordinator.data_repository.get_plant = mock_get_plant
    coordinator.data_repository.get_growspace = mock_get_growspace
    coordinator.growspace_manager.get_subareas = mock_get_subareas


    # Initialize ServiceFacade, then wrap both the container and each sub-facade in
    # MagicMocks so tests can assert on calls (assert_called_once_with, etc.)
    facade = ServiceFacade(coordinator)

    def _wrap_sub_facade(sub_facade):
        """Wrap a sub-facade so async methods are AsyncMocks."""
        wrapped = MagicMock(wraps=sub_facade)
        for name, attr in inspect.getmembers(sub_facade, predicate=inspect.iscoroutinefunction):
            setattr(wrapped, name, AsyncMock(side_effect=attr))
        return wrapped

    coordinator.services = MagicMock(wraps=facade)
    coordinator.services.growspaces = _wrap_sub_facade(facade.growspaces)
    coordinator.services.plants = _wrap_sub_facade(facade.plants)
    coordinator.services.config = _wrap_sub_facade(facade.config)
    coordinator.services.notifications = _wrap_sub_facade(facade.notifications)

    # Wrap container-level async methods
    for name, attr in inspect.getmembers(facade, predicate=inspect.iscoroutinefunction):
        setattr(coordinator.services, name, AsyncMock(side_effect=attr))

    # Legacy Aliases and helper properties
    type(coordinator).growspace_service = property(lambda self: self.growspace_manager)
    type(coordinator).plant_service = property(lambda self: self.plant_manager)

    
    coordinator.growspace_manager.async_add_growspace = coordinator.growspace_manager.add_growspace
    coordinator.growspace_manager.async_update_growspace = coordinator.growspace_manager.update_growspace
    coordinator.growspace_manager.async_remove_growspace = coordinator.growspace_manager.remove_growspace
    coordinator.growspace_manager.async_update_environment_config = coordinator.growspace_manager.update_environment_config
    
    coordinator.nutrient_manager.async_commit_preset = coordinator.nutrient_manager.async_save_nutrient_preset
    coordinator.nutrient_manager.async_remove_preset = coordinator.nutrient_manager.async_remove_nutrient_preset
    
    coordinator.training_manager.async_record_training = coordinator.training_service.async_log_training_event

    coordinator.growspace_manager.ensure_special_growspace = MagicMock(return_value="special_gs")
    coordinator.growspace_manager.get_sorted_growspace_options = MagicMock(return_value=[])

    # Utility methods
    coordinator.calculate_days = MagicMock(side_effect=DateTimeHelper.calculate_days)
    coordinator.to_date = MagicMock(side_effect=DateTimeHelper.to_date)

    # Final defaults for common mocks on coordinator/data_repository
    coordinator.data_repository.get_growspace_plants.return_value = []
    coordinator.data_repository.get_plant.return_value = None
    coordinator.data_repository.get_growspace.return_value = None



    return coordinator



@pytest.fixture
def mock_strain_library():
    """Create a mock strain library."""
    library = Mock()
    library.strains = {}
    library.add_strain = AsyncMock()
    library.get_strain = Mock(return_value=None)
    return library


@pytest.fixture
def mock_growspace():
    """Create a mock growspace."""
    growspace = Mock()
    growspace.name = "Test Growspace"
    growspace.rows = 5
    growspace.plants_per_row = 5
    growspace.id = "gs1"
    return growspace


@pytest.fixture
def mock_plant():
    """Create a mock plant."""
    plant = Mock()
    plant.plant_id = "plant_1"
    plant.strain = "Test Strain"
    plant.phenotype = "Pheno A"
    plant.growspace_id = "gs1"
    plant.row = 2
    plant.col = 3
    plant.clone_start = None
    plant.source_mother = None
    plant.type = "veg"
    return plant
