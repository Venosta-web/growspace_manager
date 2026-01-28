"""Common test utilities."""

from typing import Any

from custom_components.growspace_manager.models import Plant, PlantGenetics


def create_plant(**kwargs: Any) -> Plant:
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
