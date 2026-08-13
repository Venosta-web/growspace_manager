"""Tests for the Debug services."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.models import Plant
from custom_components.growspace_manager.services.debug import (
    _consolidate_plants_to_canonical_growspace,
    _handle_reset_cure_growspace,
    _handle_reset_dry_growspace,
    _restore_plants_to_canonical_growspace,
    handle_debug_consolidate_duplicate_special,
    handle_debug_list_growspaces,
    handle_debug_reset_special_growspaces,
    handle_test_notification,
)
from custom_components.growspace_manager.strain_library import StrainLibrary
from homeassistant.core import HomeAssistant, ServiceCall

from .common import create_plant


@pytest.fixture
def mock_hass():
    """Fixture for a mock HomeAssistant instance."""
    hass = MagicMock(spec=HomeAssistant)
    hass.bus = MagicMock()
    return hass


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
) -> None:
    """Test handle_test_notification service."""
    mock_call.data = {"message": "Test Message"}

    await handle_test_notification(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_create_notification.assert_called_once_with(
        mock_hass, "Test Message", title="Growspace Manager Test"
    )


@pytest.mark.asyncio
async def test_debug_list_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_list_growspaces service."""
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
    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[plant]
    )

    with patch("logging.Logger.debug") as mock_debug:
        await handle_debug_list_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_debug.call_count > 0


@pytest.mark.asyncio
async def test_debug_list_growspaces_no_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_list_growspaces service when no growspaces are found."""
    mock_coordinator.growspaces = {}  # Ensure growspaces is empty

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.debug"
    ) as mock_debug:
        await handle_debug_list_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        mock_debug.assert_any_call("No growspaces found")


@pytest.mark.asyncio
async def test_debug_reset_special_growspaces(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_reset_special_growspaces service."""
    mock_coordinator.growspaces = {
        "dry": MagicMock(layout_revision=0),
        "cure": MagicMock(layout_revision=0),
    }
    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        side_effect=["dry", "cure"]
    )

    await handle_debug_reset_special_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_reset_special_growspaces_preserve_plants(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_reset_special_growspaces service with preserve_plants flag."""
    mock_call.data = {"preserve_plants": True}
    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        side_effect=["dry", "cure"]
    )
    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[MagicMock(plant_id="p1")]
    )
    mock_coordinator.plants = {
        "p1": create_plant(plant_id="p1", growspace_id="dry", strain="test")
    }
    mock_coordinator.validator.find_first_available_position = MagicMock(
        return_value=(1, 1)
    )

    await handle_debug_reset_special_growspaces(
        mock_hass, mock_coordinator, mock_strain_library, mock_call
    )

    mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_consolidate_duplicate_special service."""
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
    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        side_effect=["dry", "cure"]
    )

    with patch(
        "custom_components.growspace_manager.services.debug._consolidate_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_consolidate:
        await handle_debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_consolidate.call_count > 0
        mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_no_duplicates(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_consolidate_duplicate_special service with no duplicates."""
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
        await handle_debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        assert mock_consolidate.call_count == 0
        mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_with_missing_canonical_and_multiple_cure(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_consolidate_duplicate_special service with missing canonical growspaces and multiple cure growspaces."""
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

    # Mock ensure_special_growspace to return the canonical IDs when called
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

    mock_coordinator._growspace_manager.ensure_special_growspace.reset_mock()
    mock_coordinator._growspace_manager.ensure_special_growspace.side_effect = (
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
            await handle_debug_consolidate_duplicate_special(
                mock_hass, mock_coordinator, mock_strain_library, mock_call
            )

            # Assert that ensure_special_growspace was called for both dry and cure
            mock_coordinator._growspace_manager.ensure_special_growspace.assert_any_call(
                "dry", "dry"
            )
            mock_coordinator._growspace_manager.ensure_special_growspace.assert_any_call(
                "cure", "cure"
            )
            assert (
                mock_coordinator._growspace_manager.ensure_special_growspace.call_count
                == 2
            )

            # Assert that _consolidate_plants_to_canonical_growspace was called twice
            assert mock_consolidate.call_count == 2
            mock_consolidate.assert_any_call(
                mock_coordinator, ["dry_1", "dry_2"], "dry", "dry"
            )
            mock_consolidate.assert_any_call(
                mock_coordinator, ["cure_1", "cure_2"], "cure", "cure"
            )

            mock_coordinator.async_commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_reset_dry_growspace_preserve_plants_no_plants(
    mock_hass, mock_coordinator
) -> None:
    """Test _handle_reset_dry_growspace when preserve_plants is true but no plants are found."""
    preserve_plants = True

    mock_coordinator.growspaces = MagicMock(spec=dict)
    mock_coordinator.growspaces.keys.return_value = ["dry"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x == "dry"
    mock_coordinator.growspaces.__getitem__.side_effect = lambda x: MagicMock(
        name="Dry", layout_revision=0
    )

    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[]
    )  # No plants

    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        return_value="dry"
    )
    # mock_coordinator.growspaces.pop is already a MagicMock from the fixture

    await _handle_reset_dry_growspace(mock_hass, mock_coordinator, preserve_plants)

    mock_coordinator.growspaces.pop.assert_called_once_with("dry", None)
    mock_coordinator._growspace_manager.ensure_special_growspace.assert_called_once_with(
        "dry", "dry"
    )
    # Assert that _restore_plants_to_canonical_growspace was NOT called
    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace"
    ) as mock_restore:
        await _handle_reset_dry_growspace(mock_hass, mock_coordinator, preserve_plants)
        mock_restore.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reset_dry_growspace_preserve_plants_with_plants(
    mock_hass, mock_coordinator
) -> None:
    """Test _handle_reset_dry_growspace when preserve_plants is true and plants are found."""
    preserve_plants = True

    mock_coordinator.growspaces = MagicMock(spec=dict)
    mock_coordinator.growspaces.keys.return_value = ["dry", "dry_overview_1"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: (
        x
        in [
            "dry",
            "dry_overview_1",
        ]
    )
    mock_coordinator.growspaces.__getitem__.side_effect = lambda x: MagicMock(
        name="Dry", layout_revision=0
    )

    # Configure mock_coordinator.services.growspaces.get_growspace_plants to return mock plants
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
    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        side_effect=lambda gs_id: {
            "dry": [mock_plant_1],
            "dry_overview_1": [mock_plant_2],
        }.get(gs_id, [])
    )

    # Configure mock_coordinator.plants to contain these mock plants
    mock_coordinator.plants = {"p1": mock_plant_1, "p2": mock_plant_2}

    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        return_value="dry"
    )

    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_restore:
        await _handle_reset_dry_growspace(mock_hass, mock_coordinator, preserve_plants)

        # Assert that growspaces were popped
        mock_coordinator.growspaces.pop.assert_any_call("dry", None)
        mock_coordinator.growspaces.pop.assert_any_call("dry_overview_1", None)
        assert mock_coordinator.growspaces.pop.call_count == 2

        # Assert that ensure_special_growspace was called
        mock_coordinator._growspace_manager.ensure_special_growspace.assert_called_once_with(
            "dry", "dry"
        )

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
) -> None:
    """Test _handle_reset_cure_growspace when preserve_plants is true but no plants are found."""
    preserve_plants = True

    mock_coordinator.growspaces = MagicMock(spec=dict)
    mock_coordinator.growspaces.keys.return_value = ["cure"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x == "cure"
    mock_coordinator.growspaces.__getitem__.side_effect = lambda x: MagicMock(
        name="Cure", layout_revision=0
    )

    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[]
    )  # No plants

    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        return_value="cure"
    )
    # mock_coordinator.growspaces.pop is already a MagicMock from the fixture

    await _handle_reset_cure_growspace(mock_hass, mock_coordinator, preserve_plants)

    mock_coordinator.growspaces.pop.assert_called_once_with("cure", None)
    mock_coordinator._growspace_manager.ensure_special_growspace.assert_called_once_with(
        "cure", "cure"
    )
    # Assert that _restore_plants_to_canonical_growspace was NOT called
    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace"
    ) as mock_restore:
        await _handle_reset_cure_growspace(mock_hass, mock_coordinator, preserve_plants)
        mock_restore.assert_not_called()


@pytest.mark.asyncio
async def test_handle_reset_cure_growspace_preserve_plants_with_plants(
    mock_hass, mock_coordinator
) -> None:
    """Test _handle_reset_cure_growspace when preserve_plants is true and plants are found."""
    preserve_plants = True

    mock_coordinator.growspaces = MagicMock(spec=dict)
    mock_coordinator.growspaces.keys.return_value = ["cure", "cure_overview_1"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: (
        x
        in [
            "cure",
            "cure_overview_1",
        ]
    )
    mock_coordinator.growspaces.__getitem__.side_effect = lambda x: MagicMock(
        name="Cure", layout_revision=0
    )

    # Configure mock_coordinator.services.growspaces.get_growspace_plants to return mock plants
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
    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        side_effect=lambda gs_id: {
            "cure": [mock_plant_1],
            "cure_overview_1": [mock_plant_2],
        }.get(gs_id, [])
    )

    # Configure mock_coordinator.plants to contain these mock plants
    mock_coordinator.plants = {"p1": mock_plant_1, "p2": mock_plant_2}

    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        return_value="cure"
    )

    with patch(
        "custom_components.growspace_manager.services.debug._restore_plants_to_canonical_growspace",
        new_callable=AsyncMock,
    ) as mock_restore:
        await _handle_reset_cure_growspace(mock_hass, mock_coordinator, preserve_plants)

        # Assert that growspaces were popped
        mock_coordinator.growspaces.pop.assert_any_call("cure", None)
        mock_coordinator.growspaces.pop.assert_any_call("cure_overview_1", None)
        assert mock_coordinator.growspaces.pop.call_count == 2

        # Assert that ensure_special_growspace was called
        mock_coordinator._growspace_manager.ensure_special_growspace.assert_called_once_with(
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


@pytest.mark.asyncio
async def test_consolidate_plants_to_canonical_growspace_plant_not_in_coordinator(
    mock_coordinator,
) -> None:
    """Test _consolidate_plants_to_canonical_growspace when plant is not in coordinator.plants."""
    duplicate_ids = ["dry_1"]
    canonical_id = "dry"
    log_prefix = "dry"

    mock_coordinator.growspaces = MagicMock(spec=dict)
    mock_coordinator.growspaces.keys.return_value = ["dry_1"]
    mock_coordinator.growspaces.__contains__.side_effect = lambda x: x == "dry_1"
    mock_coordinator.growspaces.__getitem__.side_effect = lambda x: MagicMock(
        name="Dry", layout_revision=0
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


@pytest.mark.asyncio
async def test_debug_reset_special_growspaces_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_reset_special_growspaces service with an exception."""
    mock_coordinator.growspaces = {"dry": MagicMock(layout_revision=0)}
    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        side_effect=RuntimeError("Test Exception")
    )

    with pytest.raises(RuntimeError):
        await handle_debug_reset_special_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_debug_consolidate_duplicate_special_exception(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_consolidate_duplicate_special service with an exception."""
    mock_dry1 = MagicMock()
    mock_dry1.name = "Dry"
    mock_dry2 = MagicMock()
    mock_dry2.name = "Dry"
    mock_coordinator.growspaces = {
        "dry_1": mock_dry1,
        "dry_2": mock_dry2,
    }
    mock_coordinator._growspace_manager.ensure_special_growspace = MagicMock(
        side_effect=RuntimeError("Test Exception")
    )

    with pytest.raises(RuntimeError):
        await handle_debug_consolidate_duplicate_special(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )


@pytest.mark.asyncio
async def test_debug_list_growspaces_zero_plants(
    mock_hass, mock_coordinator, mock_strain_library, mock_call
) -> None:
    """Test handle_debug_list_growspaces with a growspace that has 0 plants (covers line 217)."""
    mock_growspace = MagicMock()
    mock_growspace.name = "Empty GS"
    mock_growspace.rows = 2
    mock_growspace.plants_per_row = 2
    mock_coordinator.growspaces = {"gs_empty": mock_growspace}
    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[]
    )

    with patch(
        "custom_components.growspace_manager.services.debug._LOGGER.debug"
    ) as mock_debug:
        await handle_debug_list_growspaces(
            mock_hass, mock_coordinator, mock_strain_library, mock_call
        )
        mock_debug.assert_any_call("%s has 0 plants", "gs_empty")


@pytest.mark.asyncio
async def test_restore_plants_routes_through_the_plant_manager(
    mock_coordinator,
) -> None:
    """Preserved plants are relocated through the plant-manager seam."""
    plants_data_to_restore = [
        {"plant_id": "p1", "strain": "Test Strain", "old_pos": "(1,1)"},
        {"plant_id": "p2", "strain": "Other Strain", "old_pos": "(2,2)"},
    ]

    await _restore_plants_to_canonical_growspace(
        mock_coordinator, "dry", plants_data_to_restore, "dry"
    )

    mock_coordinator._plant_manager.relocate_plants_to_growspace.assert_awaited_once_with(
        "dry", ["p1", "p2"]
    )


@pytest.mark.asyncio
async def test_consolidate_routes_through_the_plant_manager(
    mock_coordinator,
) -> None:
    """Duplicates are emptied through the seam before they are removed."""
    mock_plant = MagicMock(spec=Plant, plant_id="p1", growspace_id="dry_1")
    mock_coordinator.plants = {"p1": mock_plant}
    mock_coordinator.growspaces = {"dry_1": MagicMock(layout_revision=1)}
    mock_coordinator.services.growspaces.get_growspace_plants = MagicMock(
        return_value=[mock_plant]
    )

    await _consolidate_plants_to_canonical_growspace(
        mock_coordinator, ["dry_1"], "dry", "dry"
    )

    mock_coordinator._plant_manager.relocate_plants_to_growspace.assert_awaited_once_with(
        "dry", ["p1"]
    )
    assert "dry_1" not in mock_coordinator.growspaces
