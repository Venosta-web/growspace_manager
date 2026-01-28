"""Tests for presentation module initialization."""

from custom_components.growspace_manager.presentation import (
    EntityQueries,
    GrowspaceViewModelBuilder,
    PlantViewModelBuilder,
)


def test_imports():
    """Test that all expected classes are exported from the presentation module."""
    assert EntityQueries is not None
    assert GrowspaceViewModelBuilder is not None
    assert PlantViewModelBuilder is not None
