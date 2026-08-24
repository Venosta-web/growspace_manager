"""Common test utilities."""

from datetime import timedelta
from typing import Any

from custom_components.growspace_manager.models import Plant, PlantGenetics
from homeassistant.util import dt as dt_util


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


def plant_on_stage_day(stage: str, day: int, *, plant_id: str = "p1") -> Plant:
    """A Plant whose Current Stage is ``stage`` and Current Stage Age is ``day``.

    Environmental control reads the [[Cultivation Band]] out of the Plant
    Lifecycle module, so tests that used to patch a day-count helper now hand it
    a Plant with the Stage History that produces the age they mean (#635).
    """
    started_on = dt_util.now().date() - timedelta(days=day)
    return Plant(
        plant_id=plant_id,
        growspace_id="gs1",
        stage=stage,
        stage_history=[{"stage": stage, "start": started_on.isoformat(), "end": None}],
        **{f"{stage}_start": started_on.isoformat()},
    )
