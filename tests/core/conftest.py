from unittest.mock import AsyncMock, MagicMock, Mock, patch

from freezegun.api import FrozenDateTimeFactory
import pytest

from custom_components.growspace_manager.date_time_helper import DateTimeHelper
from custom_components.growspace_manager.services.facade import ServiceFacade


@pytest.fixture(autouse=True)
def freeze_time(freezer: FrozenDateTimeFactory) -> None:
    """Freeze time to a fixed value to avoid off-by-one date errors.

    We choose a time in the middle of the day to avoid UTC midnight issues.
    Today is 2026-01-12 according to system context.
    """
    freezer.move_to("2026-01-12 12:00:00")


@pytest.fixture
def mock_coordinator():
    """Create a comprehensive mock coordinator with all services mocked."""
    coordinator = MagicMock()
    coordinator.hass = MagicMock()
    coordinator.growspaces = {}
    coordinator.plants = {}
    coordinator.data = {}
    coordinator.options = {}

    # Initialize managers
    coordinator.storage_manager = MagicMock()
    coordinator.plant_manager = MagicMock()
    coordinator.growspace_manager = MagicMock()
    coordinator.special_growspace_manager = MagicMock()
    coordinator.clone_manager = MagicMock()
    coordinator.nutrient_manager = MagicMock()
    coordinator.training_manager = MagicMock()
    coordinator.harvest_manager = MagicMock()

    # Core coordinator-level async methods (Awaited by production logic)
    coordinator.async_commit = AsyncMock()
    coordinator.async_refresh = AsyncMock()
    coordinator.async_request_refresh = AsyncMock()

    # Plant manager methods
    coordinator.plant_manager.async_add_plant = AsyncMock()
    coordinator.plant_manager.async_update_plant = AsyncMock()
    coordinator.plant_manager.async_move_plant = AsyncMock()
    coordinator.plant_manager.async_switch_plants = AsyncMock()
    coordinator.plant_manager.async_transition_plant_stage = AsyncMock()
    coordinator.plant_manager.async_transition_plant = AsyncMock()
    coordinator.plant_manager.async_remove_plant = AsyncMock()

    # Growspace manager methods
    coordinator.growspace_manager.async_add_growspace = AsyncMock()
    coordinator.growspace_manager.async_update_growspace = AsyncMock()
    coordinator.growspace_manager.async_remove_growspace = AsyncMock()
    coordinator.growspace_manager.async_update_environment_config = AsyncMock()
    coordinator.growspace_manager.ensure_special_growspace = MagicMock(return_value="special_gs")
    coordinator.growspace_manager.get_sorted_growspace_options = MagicMock(return_value=[])

    # Clone manager methods
    coordinator.clone_manager.async_take_clones = AsyncMock(return_value=["clone_1"])
    coordinator.clone_manager.async_promote_clone = AsyncMock()

    # Nutrient manager methods
    coordinator.nutrient_manager.async_commit_preset = AsyncMock()
    coordinator.nutrient_manager.async_remove_preset = AsyncMock()

    # Training manager methods
    coordinator.training_manager.async_record_training = AsyncMock()

    # Harvest manager methods
    coordinator.harvest_manager.async_record_harvest = AsyncMock()

    # Helper properties for legacy access if needed
    type(coordinator).growspace_service = property(lambda self: self.growspace_manager)
    type(coordinator).plant_service = property(lambda self: self.plant_manager)

    # Mock components
    coordinator.cache = MagicMock()
    coordinator.view_model_builder = MagicMock()
    coordinator.validator = MagicMock()
    coordinator.notification_manager = MagicMock()
    coordinator.serializer = MagicMock()

    # Utility methods
    coordinator.calculate_days = MagicMock(side_effect=DateTimeHelper.calculate_days)
    coordinator.to_date = MagicMock(side_effect=DateTimeHelper.to_date)
    coordinator.get_growspace_plants = MagicMock(return_value=[])

    # Subsystem manager with async-safe fan coordinator mock
    _fan_coord_mock = MagicMock()
    _fan_coord_mock.async_restart = AsyncMock()
    coordinator.subsystem_manager = MagicMock()
    coordinator.subsystem_manager.get_circulation_fan_controller = MagicMock(
        return_value=_fan_coord_mock
    )

    # Initialize ServiceFacade AFTER all async mocks are set so the facade's
    # internal _coordinator reference sees the correct AsyncMock attributes.
    coordinator.services = ServiceFacade(coordinator)

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
