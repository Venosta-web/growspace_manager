"""Tests for GrowspaceCoordinator data loading edge cases."""

from unittest.mock import MagicMock

import pytest

from custom_components.growspace_manager.const import DOMAIN
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.models import Growspace, Plant, PlantGenetics
from homeassistant.core import HomeAssistant
from tests.common import MockConfigEntry


@pytest.mark.asyncio
async def test_load_initial_data_pre_deserialized(hass: HomeAssistant) -> None:
    """Test loading initial data with objects already deserialized."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock()

    # Create pre-deserialized objects
    gs = Growspace(id="gs1", name="Pre-deserialized GS")
    genetics = PlantGenetics(strain_name="Pre-deserialized Strain")
    plant = Plant(plant_id="p1", growspace_id="gs1", genetics=genetics)

    data = {
        "growspaces": {"gs1": gs},
        "plants": {"p1": plant},
        "notifications_sent": {},
        "notifications_enabled": {},
    }

    coordinator = GrowspaceCoordinator.build(hass, entry, data=data)

    assert coordinator.growspaces["gs1"] is gs
    assert coordinator.plants["p1"] is plant


@pytest.mark.asyncio
async def test_load_initial_data_deserialization_failure(
    hass: HomeAssistant, caplog: pytest.LogCaptureFixture
) -> None:
    """Test loading initial data where deserialization fails."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    entry.async_create_background_task = MagicMock()

    # Create data with invalid structure that will cause failure
    # Growspace.from_dict will fail if required fields are missing
    data = {
        "growspaces": {
            "gs_fail": {"invalid": "data"},  # Missing 'id', 'name'
            "gs_invalid_type": "not_a_dict_or_object",
        },
        "plants": {
            "p_fail": {"invalid": "data"},  # Missing 'plant_id', 'growspace_id'
            "p_invalid_type": "not_a_dict_or_object",
        },
    }

    coordinator = GrowspaceCoordinator.build(hass, entry, data=data)

    # Verify that errors were logged
    assert (
        "Failed to load growspace gs_fail due to data structure mismatch" in caplog.text
    )
    assert (
        "Failed to load growspace gs_invalid_type (invalid type: <class 'str'>)"
        in caplog.text
    )
    assert "Failed to load plant p_fail due to data structure mismatch" in caplog.text
    assert (
        "Failed to load plant p_invalid_type (invalid type: <class 'str'>)"
        in caplog.text
    )

    # Verify that the invalid items were not added
    assert "gs_fail" not in coordinator.growspaces
    assert "p_fail" not in coordinator.plants
