"""The read path's single answer to "how old is this Plant's stage, and which band?".

[[Plant Lifecycle]] owns [[Current Stage Age]] and [[Cultivation Band]], but the
environmental controllers each classified flower on their own and disagreed at
the band boundaries (#635):

* ``determine_coordinator_stage`` — the dehumidifier, humidifier, circulation
  fan, and exhaust fan — used strict ``> 21`` / ``> 42`` comparisons, so day 21
  still read as Early Flower and day 42 still read as Mid Flower.
* ``classify_stages`` and the Bayesian ``_determine_stage_key`` used ``>= 21`` /
  ``>= 42``, so the same plant on the same day read one band further along.

Every one of them now derives its band from ``cultivation_band_for``, so the
boundary lives in the lifecycle module and nowhere else.

Current Stage Age is the age of the *current open interval* only, so after a
Reveg a stale ``flower_start`` cannot keep driving a plant that is back in veg.
Older Plants without Stage History are reconstructed by the lifecycle module;
malformed present history fails closed to Unknown.

Scope note: only the flower bands are routed here. Seedling and Clone
acclimation keeps ``classify_stages``' own four-day blend between
``ACCLIMATION_START_DAYS`` and ``ACCLIMATION_END_DAYS`` — those factors are
tuned against the acclimation humidity and VPD targets, and the flower boundary
is the disagreement #635 exists to remove.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from homeassistant.util import dt as dt_util

from .current_stage import resolve_stage_and_age
from .plant_lifecycle import CultivationBand, CultivationBandId, cultivation_band_for
from .stage import PlantStage

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from custom_components.growspace_manager.models import Plant

# Most-demanding band first, matching the priority ladder the coordinator stage
# has always applied: cure > dry > late > mid > early flower > mother > veg >
# seedling > clone. Within a two-band stage the established band outranks the
# acclimating one, for the same "furthest along wins" reason.
_BAND_PRIORITY: Final[tuple[CultivationBandId, ...]] = (
    CultivationBandId.CURING,
    CultivationBandId.DRYING,
    CultivationBandId.LATE_FLOWER,
    CultivationBandId.MID_FLOWER,
    CultivationBandId.EARLY_FLOWER,
    CultivationBandId.MOTHER,
    CultivationBandId.VEGETATIVE,
    CultivationBandId.ESTABLISHED_SEEDLING,
    CultivationBandId.ACCLIMATING_SEEDLING,
    CultivationBandId.ESTABLISHED_CLONE,
    CultivationBandId.ACCLIMATING_CLONE,
)

_BAND_PLANT_STAGE: Final[dict[CultivationBandId, PlantStage]] = {
    CultivationBandId.CURING: PlantStage.CURE,
    CultivationBandId.DRYING: PlantStage.DRY,
    CultivationBandId.LATE_FLOWER: PlantStage.FLOWER_LATE,
    CultivationBandId.MID_FLOWER: PlantStage.FLOWER_MID,
    CultivationBandId.EARLY_FLOWER: PlantStage.FLOWER_EARLY,
    CultivationBandId.MOTHER: PlantStage.MOTHER,
    CultivationBandId.VEGETATIVE: PlantStage.VEG,
    CultivationBandId.ESTABLISHED_SEEDLING: PlantStage.SEEDLING,
    CultivationBandId.ACCLIMATING_SEEDLING: PlantStage.SEEDLING,
    CultivationBandId.ESTABLISHED_CLONE: PlantStage.CLONE,
    CultivationBandId.ACCLIMATING_CLONE: PlantStage.CLONE,
}


def current_stage_age(plant: Plant, *, observed_on: date | None = None) -> int:
    """Return the Plant's Current Stage Age as the lifecycle module reports it.

    Args:
        plant: The Plant to measure.
        observed_on: The [[Observed Date]] the history is evaluated on; defaults
            to today in the Home Assistant timezone.

    Returns:
        Whole days since the current open interval started.
    """
    on_date = observed_on if observed_on is not None else dt_util.now().date()
    return resolve_stage_and_age(plant, observed_on=on_date)[1]


def current_stage_age_in(
    plant: Plant, stage: str, *, observed_on: date | None = None
) -> int | None:
    """Return Current Stage Age when ``stage`` is the Current Stage, else None.

    A day-of-stage question only has an answer while the Plant is in that stage:
    "veg day 14" means the fourteenth day of the *current* veg interval, not the
    fourteenth day of a veg stint the Plant has already left or, after a Reveg,
    of an earlier one.
    """
    on_date = observed_on if observed_on is not None else dt_util.now().date()
    current, age = resolve_stage_and_age(plant, observed_on=on_date)
    if current != str(stage).lower():
        return None
    return age


def plant_cultivation_band(
    plant: Plant, *, observed_on: date | None = None
) -> CultivationBand:
    """Return the Plant's Cultivation Band on ``observed_on``."""
    on_date = observed_on if observed_on is not None else dt_util.now().date()
    stage, age = resolve_stage_and_age(plant, observed_on=on_date)
    return cultivation_band_for(stage, age)


def growspace_cultivation_band(
    plants: Sequence[Plant], *, observed_on: date | None = None
) -> CultivationBand:
    """Return the most demanding Cultivation Band across ``plants``.

    Environmental control serves the whole growspace, so the plant with the most
    demanding band sets the targets. Unknown bands (a Plant whose stage cannot be
    resolved at all) never win — they carry no environmental requirement.
    """
    on_date = observed_on if observed_on is not None else dt_util.now().date()
    bands = [plant_cultivation_band(plant, observed_on=on_date) for plant in plants]
    by_identity = {band.identity: band for band in bands}
    for identity in _BAND_PRIORITY:
        band = by_identity.get(identity)
        if band is not None:
            return band
    return CultivationBand(CultivationBandId.UNKNOWN)


def band_plant_stage(band: CultivationBand) -> PlantStage:
    """Map a Cultivation Band onto the ``PlantStage`` the threshold tables key on.

    Unknown falls back to veg, the same neutral default the coordinator stage has
    always used for a growspace it cannot classify.
    """
    return _BAND_PLANT_STAGE.get(band.identity, PlantStage.VEG)
