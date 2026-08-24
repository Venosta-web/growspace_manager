"""Regression coverage for Lifetime Stage Days consumers."""

from unittest.mock import MagicMock

from custom_components.growspace_manager.models import Growspace, Plant, PlantGenetics
from custom_components.growspace_manager.services.ai_assistant import GrowAssistant
from homeassistant.core import HomeAssistant


def test_ai_grow_context_uses_lifetime_days_after_reveg() -> None:
    """AI grow context sums every historical veg and flower interval."""
    plant = Plant(
        plant_id="reveg-summary",
        growspace_id="tent",
        genetics=PlantGenetics(strain_name="Strain A"),
        stage="dry",
        # The legacy calculation sees only these latest starts: 20d veg, 10d flower.
        veg_start="2025-07-21",
        flower_start="2025-08-10",
        dry_start="2025-08-20",
        stage_history=[
            {"stage": "veg", "start": "2025-07-01", "end": "2025-07-11"},
            {"stage": "flower", "start": "2025-07-11", "end": "2025-07-21"},
            {"stage": "veg", "start": "2025-07-21", "end": "2025-08-10"},
            {"stage": "flower", "start": "2025-08-10", "end": "2025-08-20"},
            {"stage": "dry", "start": "2025-08-20", "end": None},
        ],
    )
    growspace = Growspace(id="tent", name="Tent")
    coordinator = MagicMock()
    coordinator._data_repository.get_growspace.return_value = growspace
    coordinator._data_repository.get_growspace_plants.return_value = [plant]
    hass = MagicMock(spec=HomeAssistant)
    hass.states = MagicMock()
    hass.states.get.return_value = None
    strain_library = MagicMock()
    strain_library.get_all.return_value = {}

    data = GrowAssistant(hass, coordinator, strain_library).gather_growspace_data(
        "tent"
    )

    assert (
        data["plants"]["max_veg_days"],
        data["plants"]["max_flower_days"],
    ) == (30, 20)
