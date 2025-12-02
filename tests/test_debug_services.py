"""Tests for the Debug services."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.core import HomeAssistant, ServiceCall

from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.services.debug import (
    debug_cleanup_legacy,
    debug_consolidate_duplicate_special,
    debug_list_growspaces,
    debug_reset_special_growspaces,
    handle_test_notification,
)
from custom_components.growspace_manager.strain_library import StrainLibrary


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    return hass


@pytest.fixture
def mock_coordinator():
    """Fixture for a mock GrowspaceCoordinator instance."""
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.async_save = AsyncMock()
    coordinator.get_growspace_plants = MagicMock(return_value=[])

    # Make growspaces a MagicMock that can be configured
    coordinator.growspaces = MagicMock(spec=dict)
    coordinator.growspaces.keys.return_value = []  # Default empty keys
    coordinator.growspaces.__contains__.return_value = False  # Default not in
    coordinator.growspaces.__getitem__.side_effect = (
        KeyError  # Default item access raises KeyError
    )
    coordinator.growspaces.pop = MagicMock()  # Mock the pop method

    coordinator.plants = {}
    coordinator.data = {"growspaces": {}, "plants": {}}
    coordinator.find_first_available_position = MagicMock()
    coordinator._find_first_available_position = MagicMock()
    coordinator._ensure_special_growspace = MagicMock()
    return coordinator


@pytest.fixture
def mock_strain_library():
    """Fixture for a mock StrainLibrary instance."""
    return MagicMock(spec=StrainLibrary)


@pytest.fixture
def mock_call():
    """Fixture for a mock ServiceCall instance."""
    call = MagicMock(spec=ServiceCall)
    call.data = {}
    return call


@pytest.mark.asyncio
@patch("custom_components.growspace_manager.services.debug.create_notification")
async def test_handle_test_notification(
    mock_create_notification,
    mock_hass,
    mock_coordinator,
    mock_strain_library,
    mock_call,
):
    """Test handle_test_notification service."""
    mock_call.data = {"message": "Test Message"}

    await handle_test_notification(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_create_notification.assert_called_once_with(
        mock_hass, "Test Message", title="Growspace Manager Test"
    )


@pytest.mark.asyncio
async def test_debug_cleanup_legacy(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service."""
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
        "cure_overview_1": {},
        "regular_gs": {},
    }
    mock_coordinator.plants = {
        "p1": Plant(plant_id="p1", growspace_id="dry_overview_1", strain="test")
    }
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_cleanup_legacy(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert "dry_overview_1" not in mock_coordinator.growspaces
    assert "cure_overview_1" not in mock_coordinator.growspaces
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_cleanup_legacy_dry_only(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service with dry_only flag."""
    mock_call.data = {"dry_only": True}
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
        "cure_overview_1": {},
        "regular_gs": {},
    }
    mock_coordinator._ensure_special_growspace = MagicMock(side_effect=["dry"])
    mock_coordinator.get_growspace_plants.return_value = [MagicMock(plant_id="p1")]
    mock_coordinator.plants = {
        "p1": Plant(plant_id="p1", growspace_id="dry_overview_1", strain="test")
    }
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_cleanup_legacy(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert "dry_overview_1" not in mock_coordinator.growspaces
    assert "cure_overview_1" in mock_coordinator.growspaces
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_cleanup_legacy_cure_only(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service with cure_only flag."""
    mock_call.data = {"cure_only": True}
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
        "cure_overview_1": {},
        "regular_gs": {},
    }
    mock_coordinator._ensure_special_growspace = MagicMock(side_effect=["cure"])
    mock_coordinator.get_growspace_plants.return_value = [MagicMock(plant_id="p1")]
    mock_coordinator.plants = {
        "p1": Plant(plant_id="p1", growspace_id="cure_overview_1", strain="test")
    }
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_cleanup_legacy(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    assert "dry_overview_1" in mock_coordinator.growspaces
    assert "cure_overview_1" not in mock_coordinator.growspaces
    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_list_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_list_growspaces service."""
    mock_growspace = MagicMock()
    mock_growspace.name = "Test GS"
    mock_growspace.rows = 2
    mock_growspace.plants_per_row = 3
    mock_coordinator.growspaces = {"gs1": mock_growspace}
    plant = MagicMock()
    plant.strain = "OG Kush"
    plant.plant_id = "p1"
    plant.row = 1
    plant.col = 1
    mock_coordinator.get_growspace_plants.return_value = [plant]

    with patch("logging.Logger.debug") as mock_debug:
        await debug_list_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_debug.call_count > 0


@pytest.mark.asyncio
async def test_debug_list_growspaces_no_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_list_growspaces service when no growspaces are found."""
    mock_coordinator.growspaces = {}  # Ensure growspaces is empty

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.debug"
    ) as mock_debug:
        await debug_list_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        mock_debug.assert_any_call("No growspaces found.")


@pytest.mark.asyncio
async def test_debug_reset_special_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_reset_special_growspaces service."""
    mock_coordinator.growspaces = {"dry": {}, "cure": {}}
    mock_coordinator._ensure_special_growspace = MagicMock(side_effect=["dry", "cure"])

    await debug_reset_special_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_reset_special_growspaces_preserve_plants(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_reset_special_growspaces service with preserve_plants flag."""
    mock_call.data = {"preserve_plants": True}
    mock_coordinator._ensure_special_growspace = MagicMock(side_effect=["dry", "cure"])
    mock_coordinator.get_growspace_plants.return_value = [MagicMock(plant_id="p1")]
    mock_coordinator.plants = {
        "p1": Plant(plant_id="p1", growspace_id="dry", strain="test")
    }
    mock_coordinator.find_first_available_position = MagicMock(return_value=(1, 1))

    await debug_reset_special_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_consolidate_duplicate_special service."""
    mock_dry_gs = MagicMock()
    mock_dry_gs.name = "Dry"
    mock_dry_1_gs = MagicMock()
    mock_dry_1_gs.name = "Dry"
    mock_cure_gs = MagicMock()
    mock_cure_gs.name = "Cure"
    mock_coordinator.growspaces = {
        "dry": mock_dry_gs,
        "dry_1": mock_dry_1_gs,
        "cure": mock_cure_gs,
    }
    mock_coordinator._ensure_special_growspace = MagicMock(side_effect=["dry", "cure"])

    with patch(
        "custom_components.growspace_manager.services.debug._consolidate_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_consolidate:
        await debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_consolidate.call_count > 0
        mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_no_duplicates(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_consolidate_duplicate_special service with no duplicates."""
    mock_dry_gs = MagicMock()
    mock_dry_gs.name = "Dry"
    mock_cure_gs = MagicMock()
    mock_cure_gs.name = "Cure"
    mock_coordinator.growspaces = {
        "dry": mock_dry_gs,
        "cure": mock_cure_gs,
    }

    with patch(
        "custom_components.growspace_manager.services.debug._consolidate_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_consolidate:
        await debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_consolidate.call_count == 0
        mock_coordinator.async_save.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_with_missing_canonical_and_multiple_cure(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_consolidate_duplicate_special service with missing canonical growspaces and multiple cure growspaces."""
    mock_dry_1_gs = MagicMock()
    mock_dry_1_gs.name = "Dry"  # Add this
    mock_dry_2_gs = MagicMock()
    mock_dry_2_gs.name = "Dry"  # Add this
    mock_cure_1_gs = MagicMock()
    mock_cure_1_gs.name = "Cure"  # Add this
    mock_cure_2_gs = MagicMock()
    mock_cure_2_gs.name = "Cure"  # Add this

    # Create a real dictionary to hold the growspaces
    test_growspaces_dict = {
        "dry_1": mock_dry_1_gs,
        "dry_2": mock_dry_2_gs,
        "cure_1": mock_cure_1_gs,
        "cure_2": mock_cure_2_gs,
    }

    # Mock _ensure_special_growspace to return the canonical IDs when called
    # and also add them to our test_growspaces_dict dictionary
    def ensure_special_growspace_side_effect(gs_id, name, *args, **kwargs):
        if gs_id == "dry":
            mock_gs = MagicMock()
            mock_gs.name = "Dry"
            test_growspaces_dict["dry"] = mock_gs
            return "dry"
        if gs_id == "cure":
            mock_gs = MagicMock()
            mock_gs.name = "Cure"
            test_growspaces_dict["cure"] = mock_gs
            return "cure"
        return gs_id

    mock_coordinator._ensure_special_growspace.reset_mock()
    mock_coordinator._ensure_special_growspace.side_effect = (
        ensure_special_growspace_side_effect
    )

    # Use patch.object to temporarily replace the 'growspaces' attribute with our dictionary
    with patch.object(mock_coordinator, "growspaces", new=test_growspaces_dict):
        # Ensure that 'dry' and 'cure' are not initially in the dictionary
        test_growspaces_dict.pop("dry", None)
        test_growspaces_dict.pop("cure", None)

        with patch(
            "custom_components.growspace_manager.services.debug._consolidate_plants_to_canonical_growspace",
            new_callable=AsyncMock,
        ) as mock_consolidate:
            await debug_consolidate_duplicate_special(
                mock_hass, mock_coordinator, mock_strain_library, mock_call
            )

            # Assert that _ensure_special_growspace was called for both dry and cure
            mock_coordinator._ensure_special_growspace.assert_any_call("dry", "dry")
            mock_coordinator._ensure_special_growspace.assert_any_call("cure", "cure")
            assert mock_coordinator._ensure_special_growspace.call_count == 2

            # Assert that _consolidate_plants_to_canonical_growspace was called twice
            assert mock_consolidate.call_count == 2
            mock_consolidate.assert_any_call(
                mock_coordinator, ["dry_1", "dry_2"], "dry", "dry"
            )
            mock_consolidate.assert_any_call(
                mock_coordinator, ["cure_1", "cure_2"], "cure", "cure"
            )

            mock_coordinator.async_save.assert_awaited_once()


from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.services.debug import (
    _migrate_plants_from_legacy_growspace,
)


@pytest.mark.asyncio
async def test_migrate_plants_from_legacy_growspace_find_position_exception(
    mock_coordinator,
):
    """Test _migrate_plants_from_legacy_growspace when find_first_available_position raises an exception."""
    legacy_id = "dry_overview_1"
    canonical_id = "dry"
    migrated_plants_info = []

    mock_coordinator.growspaces = {legacy_id: {}}
    mock_coordinator.plants = {
        "p1": Plant(plant_id="p1", growspace_id=legacy_id, strain="test")
    }
    mock_coordinator.get_growspace_plants.return_value = [
        MagicMock(spec=Plant, plant_id="p1", strain="Test Strain", row=1, col=1)
    ]
    mock_coordinator.find_first_available_position.side_effect = Exception(
        "No position"
    )

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _migrate_plants_from_legacy_growspace(
            mock_coordinator, legacy_id, canonical_id, migrated_plants_info
        )
        mock_warning.assert_called_once()
        assert legacy_id not in mock_coordinator.growspaces
        assert not migrated_plants_info


@pytest.mark.asyncio
async def test_migrate_plants_from_legacy_growspace_plant_not_in_coordinator(
    mock_coordinator,
):
    """Test _migrate_plants_from_legacy_growspace when plant is not in coordinator.plants."""
    legacy_id = "dry_overview_1"
    canonical_id = "dry"
    migrated_plants_info = []

    mock_coordinator.growspaces = {legacy_id: {}}
    mock_coordinator.plants = {}  # Plant not in here
    mock_coordinator.get_growspace_plants.return_value = [
        MagicMock(spec=Plant, plant_id="p1", strain="Test Strain", row=1, col=1)
    ]

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _migrate_plants_from_legacy_growspace(
            mock_coordinator, legacy_id, canonical_id, migrated_plants_info
        )
        mock_warning.assert_called_once()
        assert legacy_id not in mock_coordinator.growspaces
        assert not migrated_plants_info


@pytest.mark.asyncio
async def test_migrate_plants_from_legacy_growspace_success(
    mock_coordinator,
):
    """Test _migrate_plants_from_legacy_growspace when a plant is successfully migrated."""
    legacy_id = "dry_overview_1"
    canonical_id = "dry"
    migrated_plants_info = []

    mock_coordinator.growspaces = {legacy_id: {}}
    mock_plant = MagicMock(
        spec=Plant,
        plant_id="p1",
        growspace_id=legacy_id,
        strain="Test Strain",
        row=1,
        col=1,
    )
    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.get_growspace_plants.return_value = [mock_plant]
    mock_coordinator._find_first_available_position.return_value = (2, 2)

    await _migrate_plants_from_legacy_growspace(
        mock_coordinator, legacy_id, canonical_id, migrated_plants_info
    )

    assert mock_plant.growspace_id == canonical_id
    assert mock_plant.row == 2
    assert mock_plant.col == 2
    assert migrated_plants_info == ["Test Strain (p1) to dry at (2,2)"]
    assert legacy_id not in mock_coordinator.growspaces


from custom_components.growspace_manager.services.debug import (
    _restore_plants_to_canonical_growspace,
)


@pytest.mark.asyncio
async def test_restore_plants_to_canonical_growspace_find_position_exception(
    mock_coordinator,
):
    """Test _restore_plants_to_canonical_growspace when find_first_available_position raises an exception."""
    canonical_id = "dry"
    plants_data_to_restore = [
        {"plant_id": "p1", "strain": "Test Strain", "old_pos": "(1,1)"}
    ]
    log_prefix = "dry"

    mock_coordinator.plants = {
        "p1": Plant(plant_id="p1", growspace_id="old_dry", strain="test")
    }
    mock_coordinator.find_first_available_position.side_effect = Exception(
        "No position"
    )

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _restore_plants_to_canonical_growspace(
            mock_coordinator, canonical_id, plants_data_to_restore, log_prefix
        )
        mock_warning.assert_called_once()
        assert (
            mock_coordinator.plants["p1"].growspace_id == "old_dry"
        )  # Should not change


@pytest.mark.asyncio
async def test_restore_plants_to_canonical_growspace_plant_not_in_coordinator(
    mock_coordinator,
):
    """Test _restore_plants_to_canonical_growspace when plant is not in coordinator.plants."""
    canonical_id = "dry"
    plants_data_to_restore = [
        {"plant_id": "p1", "strain": "Test Strain", "old_pos": "(1,1)"}
    ]
    log_prefix = "dry"

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _restore_plants_to_canonical_growspace(
            mock_coordinator, canonical_id, plants_data_to_restore, log_prefix
        )
        mock_warning.assert_called_once()


@pytest.mark.asyncio
async def test_restore_plants_to_canonical_growspace_success(
    mock_coordinator,
):
    """Test _restore_plants_to_canonical_growspace when a plant is successfully restored."""
    canonical_id = "dry"
    plants_data_to_restore = [
        {"plant_id": "p1", "strain": "Test Strain", "old_pos": "(1,1)"}
    ]
    log_prefix = "dry"

    mock_plant = MagicMock(
        spec=Plant, plant_id="p1", growspace_id="old_dry", strain="test", row=1, col=1
    )
    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator._find_first_available_position.return_value = (2, 2)

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.debug"
    ) as mock_debug:
        await _restore_plants_to_canonical_growspace(
            mock_coordinator, canonical_id, plants_data_to_restore, log_prefix
        )
        assert mock_plant.growspace_id == canonical_id
        assert mock_plant.row == 2
        assert mock_plant.col == 2
        mock_debug.assert_any_call(
            "Restored %s to %s at (%d,%d) from %s",
            "p1",
            canonical_id,
            2,
            2,
            "(1,1)",
        )


from custom_components.growspace_manager.services.debug import (
    _handle_reset_cure_growspace,
    _handle_reset_dry_growspace,
)


@pytest.mark.asyncio
async def test_handle_reset_dry_growspace_preserve_plants_no_plants(
    mock_hass, mock_coordinator
):
    """Test _handle_reset_dry_growspace when preserve_plants is true but no plants are found."""
    preserve_plants = True

    # Configure mock_coordinator.growspaces to behave like {"dry": {"name": "Dry"}}
    mock_coordinator.growspaces.keys.return_value = ["dry"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x == "dry"
    mock_coordinator.growspaces.__getitem__.side_effect = (
        lambda x: {"name": "Dry"} if x == "dry" else KeyError
    )

    mock_coordinator.get_growspace_plants.return_value = []  # No plants

    mock_coordinator._ensure_special_growspace = MagicMock(return_value="dry")
    # mock_coordinator.growspaces.pop is already a MagicMock from the fixture

    await _handle_reset_dry_growspace(mock_hass, mock_coordinator, preserve_plants)

    mock_coordinator.growspaces.pop.assert_called_once_with("dry", None)
    mock_coordinator._ensure_special_growspace.assert_called_once_with("dry", "dry")
    # Assert that _restore_plants_to_canonical_growspace was NOT called
    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace"
    ) as mock_restore:
        await _handle_reset_dry_growspace(mock_hass, mock_coordinator, preserve_plants)
        mock_restore.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reset_dry_growspace_preserve_plants_with_plants(
    mock_hass, mock_coordinator
):
    """Test _handle_reset_dry_growspace when preserve_plants is true and plants are found."""
    preserve_plants = True

    # Configure mock_coordinator.growspaces to include dry and dry_overview growspaces
    mock_coordinator.growspaces.keys.return_value = ["dry", "dry_overview_1"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x in [
        "dry",
        "dry_overview_1",
    ]
    mock_coordinator.growspaces.__getitem__.side_effect = (
        lambda x: {"name": "Dry"} if x in ["dry", "dry_overview_1"] else KeyError
    )

    # Configure mock_coordinator.get_growspace_plants to return mock plants
    mock_plant_1 = MagicMock(
        plant_id="p1", growspace_id="dry", strain="Test Strain 1", row=1, col=1
    )
    mock_plant_2 = MagicMock(
        plant_id="p2",
        growspace_id="dry_overview_1",
        strain="Test Strain 2",
        row=2,
        col=2,
    )
    mock_coordinator.get_growspace_plants.side_effect = lambda gs_id: {
        "dry": [mock_plant_1],
        "dry_overview_1": [mock_plant_2],
    }.get(gs_id, [])

    # Configure mock_coordinator.plants to contain these mock plants
    mock_coordinator.plants = {"p1": mock_plant_1, "p2": mock_plant_2}

    mock_coordinator._ensure_special_growspace = MagicMock(return_value="dry")

    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_restore:
        await _handle_reset_dry_growspace(mock_hass, mock_coordinator, preserve_plants)

        # Assert that growspaces were popped
        mock_coordinator.growspaces.pop.assert_any_call("dry", None)
        mock_coordinator.growspaces.pop.assert_any_call("dry_overview_1", None)
        assert mock_coordinator.growspaces.pop.call_count == 2

        # Assert that _ensure_special_growspace was called
        mock_coordinator._ensure_special_growspace.assert_called_once_with("dry", "dry")

        # Assert that _restore_plants_to_canonical_growspace was called with correct data
        expected_plants_data = [
            {"plant_id": "p1", "strain": "Test Strain 1", "old_pos": "(1,1)"},
            {"plant_id": "p2", "strain": "Test Strain 2", "old_pos": "(2,2)"},
        ]
        mock_restore.assert_called_once_with(
            mock_coordinator, "dry", expected_plants_data, "dry"
        )


@pytest.mark.asyncio
async def test_handle_reset_cure_growspace_preserve_plants_no_plants(
    mock_hass, mock_coordinator
):
    """Test _handle_reset_cure_growspace when preserve_plants is true but no plants are found."""
    preserve_plants = True

    # Configure mock_coordinator.growspaces to behave like {"cure": {"name": "Cure"}}
    mock_coordinator.growspaces.keys.return_value = ["cure"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x == "cure"
    mock_coordinator.growspaces.__getitem__.side_effect = (
        lambda x: {"name": "Cure"} if x == "cure" else KeyError
    )

    mock_coordinator.get_growspace_plants.return_value = []  # No plants

    mock_coordinator._ensure_special_growspace = MagicMock(return_value="cure")
    # mock_coordinator.growspaces.pop is already a MagicMock from the fixture

    await _handle_reset_cure_growspace(mock_hass, mock_coordinator, preserve_plants)

    mock_coordinator.growspaces.pop.assert_called_once_with("cure", None)
    mock_coordinator._ensure_special_growspace.assert_called_once_with("cure", "cure")
    # Assert that _restore_plants_to_canonical_growspace was NOT called
    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace"
    ) as mock_restore:
        await _handle_reset_cure_growspace(mock_hass, mock_coordinator, preserve_plants)
        mock_restore.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reset_cure_growspace_preserve_plants_with_plants(
    mock_hass, mock_coordinator
):
    """Test _handle_reset_cure_growspace when preserve_plants is true and plants are found."""
    preserve_plants = True

    # Configure mock_coordinator.growspaces to include cure and cure_overview growspaces
    mock_coordinator.growspaces.keys.return_value = ["cure", "cure_overview_1"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x in [
        "cure",
        "cure_overview_1",
    ]
    mock_coordinator.growspaces.__getitem__.side_effect = (
        lambda x: {"name": "Cure"} if x in ["cure", "cure_overview_1"] else KeyError
    )

    # Configure mock_coordinator.get_growspace_plants to return mock plants
    mock_plant_1 = MagicMock(
        plant_id="p1", growspace_id="cure", strain="Test Strain 1", row=1, col=1
    )
    mock_plant_2 = MagicMock(
        plant_id="p2",
        growspace_id="cure_overview_1",
        strain="Test Strain 2",
        row=2,
        col=2,
    )
    mock_coordinator.get_growspace_plants.side_effect = lambda gs_id: {
        "cure": [mock_plant_1],
        "cure_overview_1": [mock_plant_2],
    }.get(gs_id, [])

    # Configure mock_coordinator.plants to contain these mock plants
    mock_coordinator.plants = {"p1": mock_plant_1, "p2": mock_plant_2}

    mock_coordinator._ensure_special_growspace = MagicMock(return_value="cure")

    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_restore:
        await _handle_reset_cure_growspace(mock_hass, mock_coordinator, preserve_plants)

        # Assert that growspaces were popped
        mock_coordinator.growspaces.pop.assert_any_call("cure", None)
        mock_coordinator.growspaces.pop.assert_any_call("cure_overview_1", None)
        assert mock_coordinator.growspaces.pop.call_count == 2

        # Assert that _ensure_special_growspace was called
        mock_coordinator._ensure_special_growspace.assert_called_once_with(
            "cure", "cure"
        )

        # Assert that _restore_plants_to_canonical_growspace was called with correct data
        expected_plants_data = [
            {"plant_id": "p1", "strain": "Test Strain 1", "old_pos": "(1,1)"},
            {"plant_id": "p2", "strain": "Test Strain 2", "old_pos": "(2,2)"},
        ]
        mock_restore.assert_called_once_with(
            mock_coordinator, "cure", expected_plants_data, "cure"
        )


from custom_components.growspace_manager.services.debug import (
    _consolidate_plants_to_canonical_growspace,
)


@pytest.mark.asyncio
async def test_consolidate_plants_to_canonical_growspace_find_position_exception(
    mock_coordinator,
):
    """Test _consolidate_plants_to_canonical_growspace when find_first_available_position raises an exception."""
    duplicate_ids = ["dry_1"]
    canonical_id = "dry"
    log_prefix = "dry"

    mock_coordinator.growspaces.keys.return_value = [
        "dry_1"
    ]  # Configure growspaces mock
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x == "dry_1"
    mock_coordinator.growspaces.__getitem__.side_effect = (
        lambda x: {} if x == "dry_1" else KeyError
    )

    mock_coordinator.plants = {
        "p1": Plant(plant_id="p1", growspace_id="dry_1", strain="test")
    }
    mock_coordinator.get_growspace_plants.return_value = [
        MagicMock(spec=Plant, plant_id="p1", strain="Test Strain", row=1, col=1)
    ]
    mock_coordinator.find_first_available_position.side_effect = Exception(
        "No position"
    )

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _consolidate_plants_to_canonical_growspace(
            mock_coordinator, duplicate_ids, canonical_id, log_prefix
        )
        mock_warning.assert_called_once()
        mock_coordinator.growspaces.pop.assert_called_once_with(
            "dry_1", None
        )  # Should still remove duplicate


@pytest.mark.asyncio
async def test_consolidate_plants_to_canonical_growspace_plant_not_in_coordinator(
    mock_coordinator,
):
    """Test _consolidate_plants_to_canonical_growspace when plant is not in coordinator.plants."""
    duplicate_ids = ["dry_1"]
    canonical_id = "dry"
    log_prefix = "dry"

    mock_coordinator.growspaces.keys.return_value = [
        "dry_1"
    ]  # Configure growspaces mock
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x == "dry_1"
    mock_coordinator.growspaces.__getitem__.side_effect = (
        lambda x: {} if x == "dry_1" else KeyError
    )

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.warning"
    ) as mock_warning:
        await _consolidate_plants_to_canonical_growspace(
            mock_coordinator, duplicate_ids, canonical_id, log_prefix
        )
        mock_warning.assert_not_called()  # No warning expected here
        mock_coordinator.growspaces.pop.assert_called_once_with(
            "dry_1", None
        )  # Should still remove duplicate


from custom_components.growspace_manager.services.debug import (
    _cleanup_cure_legacy_growspaces,
    _cleanup_dry_legacy_growspaces,
)


@pytest.mark.asyncio
async def test_cleanup_dry_legacy_growspaces(mock_hass, mock_coordinator):
    """Test _cleanup_dry_legacy_growspaces function."""
    migrated_plants_info = []
    removed_growspaces = []
    legacy_dry = ["dry_overview_1", "dry_overview_2"]

    mock_coordinator._ensure_special_growspace.return_value = "dry"
    with patch(
        "custom_components.growspace_manager.services.debug._migrate_plants_from_legacy_growspace",
        new_callable=AsyncMock,
    ) as mock_migrate:
        await _cleanup_dry_legacy_growspaces(
            mock_hass,
            mock_coordinator,
            migrated_plants_info,
            removed_growspaces,
            legacy_dry,
        )
        assert mock_coordinator._ensure_special_growspace.call_count == len(legacy_dry)
        assert mock_migrate.call_count == len(legacy_dry)
        assert removed_growspaces == legacy_dry


@pytest.mark.asyncio
async def test_cleanup_cure_legacy_growspaces(mock_hass, mock_coordinator):
    """Test _cleanup_cure_legacy_growspaces function."""
    migrated_plants_info = []
    removed_growspaces = []
    legacy_cure = ["cure_overview_1", "cure_overview_2"]

    mock_coordinator._ensure_special_growspace.return_value = "cure"
    with patch(
        "custom_components.growspace_manager.services.debug._migrate_plants_from_legacy_growspace",
        new_callable=AsyncMock,
    ) as mock_migrate:
        await _cleanup_cure_legacy_growspaces(
            mock_hass,
            mock_coordinator,
            migrated_plants_info,
            removed_growspaces,
            legacy_cure,
        )
        assert mock_coordinator._ensure_special_growspace.call_count == len(legacy_cure)
        assert mock_migrate.call_count == len(legacy_cure)
        assert removed_growspaces == legacy_cure


@pytest.mark.asyncio
async def test_debug_cleanup_legacy_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_cleanup_legacy service with an exception."""
    mock_coordinator.growspaces = {
        "dry_overview_1": {},
    }
    mock_coordinator._ensure_special_growspace = MagicMock(
        side_effect=Exception("Test Exception")
    )

    with pytest.raises(Exception):
        await debug_cleanup_legacy(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_debug_reset_special_growspaces_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_reset_special_growspaces service with an exception."""
    mock_coordinator.growspaces = {"dry": {}}
    mock_coordinator._ensure_special_growspace = MagicMock(
        side_effect=Exception("Test Exception")
    )

    with pytest.raises(Exception):
        await debug_reset_special_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
):
    """Test debug_consolidate_duplicate_special service with an exception."""
    mock_coordinator.growspaces = {
        "dry_1": {"name": "Dry"},
        "dry_2": {"name": "Dry"},
    }
    mock_coordinator._ensure_special_growspace = MagicMock(
        side_effect=Exception("Test Exception")
    )

    with pytest.raises(Exception):
        await debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
