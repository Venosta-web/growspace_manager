"""Tests for plant training logic."""

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.growspace_manager.const import (
    ATTR_GROWSPACE_ID,
    ATTR_NOTES,
    ATTR_TECHNIQUE,
    CATEGORY_TRAINING,
    TrainingTechnique,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.services.training import (
    handle_log_training_event,
)
from homeassistant.core import HomeAssistant, ServiceCall

from .common import create_plant


@pytest.fixture
def mock_plants():
    return {
        "plant_1": create_plant(
            plant_id="plant_1",
            growspace_id="gs_1",
            strain="Blue Dream",
            stage="vegetative",
        ),
        "plant_2": create_plant(
            plant_id="plant_2",
            growspace_id="gs_1",
            strain="OG Kush",
            stage="vegetative",
        ),
        "plant_3": create_plant(
            plant_id="plant_3",
            growspace_id="gs_2",
            strain="Haze",
            stage="flower",
        ),
    }


@pytest.fixture
def mock_coordinator(hass: HomeAssistant, mock_plants):
    coordinator = MagicMock(spec=GrowspaceCoordinator)
    coordinator.hass = hass
    coordinator.plants = mock_plants
    coordinator.get_growspace_plants = lambda gid: [
        p for p in mock_plants.values() if p.growspace_id == gid
    ]
    coordinator.async_save = AsyncMock()
    coordinator.add_event = MagicMock()

    # Bind the method to test and its helpers
    coordinator.async_log_training_event = (
        GrowspaceCoordinator.async_log_training_event.__get__(
            coordinator, GrowspaceCoordinator
        )
    )
    coordinator._get_target_plants = GrowspaceCoordinator._get_target_plants.__get__(
        coordinator, GrowspaceCoordinator
    )
    coordinator._create_training_reasons = (
        GrowspaceCoordinator._create_training_reasons.__get__(
            coordinator, GrowspaceCoordinator
        )
    )

    return coordinator


@pytest.mark.asyncio
async def test_log_training_single_plant(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test logging training for a single plant."""
    technique = TrainingTechnique.TOPPING
    notes = "Main stem topped"
    full_technique_name = "Topping"

    with patch(
        "homeassistant.util.dt.now", return_value=datetime(2023, 1, 1, 12, 0, 0)
    ):
        await mock_coordinator.async_log_training_event(
            growspace_id=None, technique=technique, notes=notes, plant_ids=["plant_1"]
        )

    # Check plant update
    assert mock_coordinator.plants["plant_1"].last_trained is not None
    assert mock_coordinator.plants["plant_1"].last_training_technique == technique

    # Check event creation
    mock_coordinator.add_event.assert_called_once()  # type: ignore[attr-defined]
    args, _ = mock_coordinator.add_event.call_args  # type: ignore[attr-defined]
    gid, event = args

    assert gid == "gs_1"
    assert event.category == CATEGORY_TRAINING
    assert event.sensor_type == technique
    assert f"Technique: {full_technique_name}" in event.reasons
    assert f"Notes: {notes}" in event.reasons


@pytest.mark.asyncio
async def test_log_training_growspace_all(
    mock_coordinator: GrowspaceCoordinator,
) -> None:
    """Test logging training for an entire growspace."""
    technique = "defoliating"

    with patch(
        "homeassistant.util.dt.now", return_value=datetime(2023, 1, 1, 12, 0, 0)
    ):
        await mock_coordinator.async_log_training_event(
            growspace_id="gs_1", technique=technique
        )

    # Check all plants in gs_1 updated
    assert mock_coordinator.plants["plant_1"].last_training_technique == technique
    assert mock_coordinator.plants["plant_2"].last_training_technique == technique
    # plant_3 in gs_2 should be untouched
    assert mock_coordinator.plants["plant_3"].last_training_technique is None

    # Check event
    mock_coordinator.add_event.assert_called_once()  # type: ignore[attr-defined]
    args, _ = mock_coordinator.add_event.call_args  # type: ignore[attr-defined]
    _, event = args
    assert event.growspace_id == "gs_1"
    # Should not list specific plants if all were affected (implementation detail check)
    assert not any("Plants:" in r for r in event.reasons)


@pytest.mark.asyncio
async def test_log_training_subset(mock_coordinator: GrowspaceCoordinator) -> None:
    """Test logging training for a subset of plants in a growspace."""
    plant_ids = ["plant_1"]
    technique = "lst"

    await mock_coordinator.async_log_training_event(
        growspace_id=None, technique=technique, plant_ids=plant_ids
    )

    assert mock_coordinator.plants["plant_1"].last_training_technique == technique
    assert mock_coordinator.plants["plant_2"].last_training_technique is None

    # Check event lists specific plants
    args, _ = mock_coordinator.add_event.call_args  # type: ignore[attr-defined]
    _, event = args
    # Access as dict or object depending on what it is.
    # If it is a dataclass, it should have attributes.
    reasons = event.reasons
    assert any("Plants: Blue Dream" in r for r in reasons)


@pytest.mark.asyncio
async def test_handle_log_training_event_service(
    hass: HomeAssistant, mock_coordinator: GrowspaceCoordinator
) -> None:
    """Test the service handler function directly."""

    call = ServiceCall(
        hass,
        domain="growspace_manager",
        service="log_training_event",
        data={
            ATTR_TECHNIQUE: "topping",
            ATTR_GROWSPACE_ID: "gs_1",
            ATTR_NOTES: "Service call test",
        },
    )

    with patch.object(
        mock_coordinator, "async_log_training_event", new_callable=AsyncMock
    ) as mock_method:
        await handle_log_training_event(hass, mock_coordinator, call)

        mock_method.assert_awaited_once_with(
            growspace_id="gs_1",
            technique="topping",
            notes="Service call test",
            plant_ids=None,
        )
