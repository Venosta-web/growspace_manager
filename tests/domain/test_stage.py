"""Tests for the stage domain logic."""

from custom_components.growspace_manager.domain.stage import (
    PLANT_STAGES,
    SPECIAL_GROWSPACE_STAGES,
    STAGE_REGISTRY,
    STAGES_ORDERED,
    PlantStage,
    StageDefinition,
    get_stage_definition,
)


def test_stage_definition_defaults():
    """Test StageDefinition defaults and post-init."""
    # Test default display name
    stage_def = StageDefinition(
        id=PlantStage.SEEDLING,
        start_field="seedling_start",
        order=10,
    )
    assert stage_def.display_name == "Seedling"

    # Test explicit display name
    stage_def_explicit = StageDefinition(
        id=PlantStage.VEG,
        start_field="veg_start",
        order=40,
        display_name="Vegetative",
    )
    assert stage_def_explicit.display_name == "Vegetative"


def test_get_stage_definition():
    """Test get_stage_definition with various inputs."""
    # Test valid enum (covers line 134)
    stage_def = get_stage_definition(PlantStage.FLOWER)
    assert stage_def is not None
    assert stage_def.id == PlantStage.FLOWER

    # Test valid string (covers lines 128-130)
    stage_def_str = get_stage_definition("flower")
    assert stage_def_str is not None
    assert stage_def_str.id == PlantStage.FLOWER

    # Test invalid string
    assert get_stage_definition("invalid_stage") is None

    # Test case sensitivity (StrEnum is case-sensitive by default usually)
    assert get_stage_definition("FLOWER") is None


def test_constants():
    """Test stage constants and derived lists."""
    # Verify PLANT_STAGES contents
    assert "seedling" in PLANT_STAGES
    assert "flower" in PLANT_STAGES
    assert len(PLANT_STAGES) == len(PlantStage)

    # Verify SPECIAL_GROWSPACE_STAGES
    assert "clone" in SPECIAL_GROWSPACE_STAGES
    assert "dry" in SPECIAL_GROWSPACE_STAGES
    assert "seedling" not in SPECIAL_GROWSPACE_STAGES

    # Verify STAGES_ORDERED
    orders = [s.order for s in STAGES_ORDERED]
    assert orders == sorted(orders)
    assert len(STAGES_ORDERED) == len(STAGE_REGISTRY)
