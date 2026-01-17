"""Global fixtures for integration tests."""

import pytest
from freezegun.api import FrozenDateTimeFactory

from custom_components.growspace_manager.models import Plant, PlantGenetics

pytest_plugins = "pytest_homeassistant_custom_component"


@pytest.fixture(autouse=True)
def freeze_time(freezer: FrozenDateTimeFactory):
    """Freeze time to a fixed value to avoid off-by-one date errors.

    We choose a time in the middle of the day to avoid UTC midnight issues.
    Today is 2026-01-12 according to system context.
    """
    freezer.move_to("2026-01-12 12:00:00")


def create_plant(**kwargs):
    """Factory function for creating Plant instances with backward compatibility.

    Accepts 'strain' and 'phenotype' as kwargs and converts them to PlantGenetics.
    """

    # Extract strain/phenotype if provided
    strain = kwargs.pop("strain", "")
    phenotype = kwargs.pop("phenotype", "")

    # Create genetics if not provided
    if "genetics" not in kwargs:
        kwargs["genetics"] = PlantGenetics(
            strain_name=strain,
            phenotype_name=phenotype,
        )

    return Plant(**kwargs)
