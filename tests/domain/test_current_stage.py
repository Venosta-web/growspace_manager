"""Tests for the read path's Current Stage resolution (#634).

The plant view model, the plant sensor, and nutrient-preset matching all read
Current Stage through ``resolve_current_stage``, so they agree with the Plant
Lifecycle module and with each other. The legacy date heuristic survives only
where no trustworthy Stage History is stored.
"""

from datetime import date
from unittest.mock import MagicMock

from custom_components.growspace_manager.domain.current_stage import (
    resolve_current_stage,
)
from custom_components.growspace_manager.managers.nutrient import NutrientManager
from custom_components.growspace_manager.models import NutrientPreset, Plant
from custom_components.growspace_manager.presentation.plant_view_model import (
    PlantViewModelBuilder,
)
from custom_components.growspace_manager.sensor.plant import PlantEntity
from custom_components.growspace_manager.utils import calculate_plant_stage

OBSERVED_ON = date(2025, 8, 20)


def _revegged_plant() -> Plant:
    """A Plant taken back to veg out of flower, legacy flower date still set.

    This is the shape the old heuristic got wrong: it scans the legacy
    ``*_start`` fields from the latest stage backwards, so a stale
    ``flower_start`` beat the newer ``veg_start`` and the card kept showing
    "flower" after the Reveg.
    """
    return Plant(
        plant_id="reveg",
        growspace_id="main",
        stage="flower",
        veg_start="2025-08-10",
        flower_start="2025-08-01",
        stage_history=[
            {"stage": "veg", "start": "2025-07-01", "end": "2025-08-01"},
            {"stage": "flower", "start": "2025-08-01", "end": "2025-08-10"},
            {"stage": "veg", "start": "2025-08-10", "end": None},
        ],
    )


def test_reveg_history_beats_the_stale_legacy_date_heuristic() -> None:
    """The Reveg regression: history says veg, the old heuristic said flower."""
    plant = _revegged_plant()

    assert calculate_plant_stage(plant) == "flower"
    assert resolve_current_stage(plant, observed_on=OBSERVED_ON) == "veg"


def test_clone_promotion_beats_the_special_growspace_shortcut() -> None:
    """A promoted clone still sitting in the clone growspace reads as veg."""
    plant = Plant(
        plant_id="promoted",
        growspace_id="clone",
        stage="clone",
        clone_start="2025-07-01",
        veg_start="2025-08-10",
        stage_history=[
            {"stage": "clone", "start": "2025-07-01", "end": "2025-08-10"},
            {"stage": "veg", "start": "2025-08-10", "end": None},
        ],
    )

    assert calculate_plant_stage(plant) == "clone"
    assert resolve_current_stage(plant, observed_on=OBSERVED_ON) == "veg"


def test_consistent_history_displays_the_same_stage_as_before() -> None:
    """A Plant whose history already agreed keeps its displayed stage."""
    plant = Plant(
        plant_id="ordinary",
        growspace_id="main",
        stage="flower",
        veg_start="2025-07-01",
        flower_start="2025-08-01",
        stage_history=[
            {"stage": "veg", "start": "2025-07-01", "end": "2025-08-01"},
            {"stage": "flower", "start": "2025-08-01", "end": None},
        ],
    )

    assert resolve_current_stage(plant, observed_on=OBSERVED_ON) == "flower"
    assert resolve_current_stage(
        plant, observed_on=OBSERVED_ON
    ) == calculate_plant_stage(plant)


def test_absent_history_keeps_the_legacy_heuristic() -> None:
    """Plants that store no Stage History are still read from legacy dates."""
    plant = Plant(
        plant_id="legacy",
        growspace_id="main",
        stage="",
        veg_start="2025-07-01",
        flower_start="2025-08-01",
        stage_history=[],
    )

    assert resolve_current_stage(plant, observed_on=OBSERVED_ON) == "flower"


def test_untrustworthy_history_falls_back_to_the_legacy_heuristic() -> None:
    """History that needs repair never silently reports Unknown to the card."""
    plant = Plant(
        plant_id="broken",
        growspace_id="main",
        stage="flower",
        flower_start="2025-08-01",
        stage_history=[
            {"stage": "veg", "start": "not-a-date", "end": None},
        ],
    )

    assert resolve_current_stage(plant, observed_on=OBSERVED_ON) == "flower"


def test_sensor_state_and_attributes_agree_with_the_module() -> None:
    """The sensor state, its ``stage`` attribute, and the module are one answer."""
    plant = _revegged_plant()
    coordinator = MagicMock()
    coordinator.plants = {plant.plant_id: plant}
    coordinator.growspaces = {}

    entity = PlantEntity(coordinator, plant)

    assert entity.native_value == "veg"
    assert entity.extra_state_attributes["stage"] == "veg"


def test_view_model_payload_agrees_with_the_module(hass) -> None:
    """The card's plant payload carries the module's Current Stage."""
    plant = _revegged_plant()
    builder = PlantViewModelBuilder(hass)
    builder.entity_queries = MagicMock()
    builder.entity_queries.lookup_plant_entity_id.return_value = "sensor.reveg"

    assert builder.build(plant)["stage"] == "veg"


def test_nutrient_presets_match_the_modules_current_stage() -> None:
    """Preset stage matching follows the Reveg, not the stale legacy shadow."""
    plant = _revegged_plant()
    repository = MagicMock()
    repository.get_plant.return_value = plant
    manager = NutrientManager(repository=repository, save_callback=MagicMock())
    manager.nutrient_presets = {
        "veg": NutrientPreset(
            id="veg", name="Veg", items=[], stage="veg", created_at="2025-01-01"
        ),
        "flower": NutrientPreset(
            id="flower",
            name="Flower",
            items=[],
            stage="flower",
            created_at="2025-01-01",
        ),
    }

    applicable = {preset.id for preset in manager.get_applicable_presets("reveg")}

    assert applicable == {"veg"}
