"""Boundary tests for the one Cultivation Band answer (#635).

Environmental control used to hold three independent flower classifiers that
disagreed at day 21 and day 42: the coordinator stage compared ``> 21`` / ``> 42``,
while ``classify_stages`` and the Bayesian stage key compared ``>= 21`` / ``>= 42``.
Every consumer now derives its band from the Plant Lifecycle module, so on any
given day they select the same band for the same plant.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.bayesian_evaluator import _determine_stage_key
from custom_components.growspace_manager.domain.cultivation_band import (
    band_plant_stage,
    current_stage_age,
    current_stage_age_in,
    growspace_cultivation_band,
    plant_cultivation_band,
)
from custom_components.growspace_manager.domain.fan_control import (
    resolve_stage_vpd_target,
)
from custom_components.growspace_manager.domain.plant_lifecycle import CultivationBandId
from custom_components.growspace_manager.domain.stage import (
    BayesianStage,
    PlantStage,
    StageDays,
    classify_stages,
)
from custom_components.growspace_manager.domain.stage_calculator import (
    determine_coordinator_stage,
)
from custom_components.growspace_manager.managers.nutrient import NutrientManager
from custom_components.growspace_manager.models import (
    EnvironmentState,
    NutrientPreset,
    Plant,
)
from custom_components.growspace_manager.notification_manager import NotificationManager
from homeassistant.util import dt as dt_util

# The consumers that take no explicit date measure against "today", so the
# fixtures are built backwards from it rather than from a frozen calendar date.
OBSERVED_ON = dt_util.now().date()

# The two boundaries every consumer used to answer differently, plus the day on
# either side of each so an off-by-one in any of them still shows up.
BOUNDARY_DAYS = (20, 21, 22, 41, 42, 43)

_EXPECTED_BAND = {
    20: CultivationBandId.EARLY_FLOWER,
    21: CultivationBandId.MID_FLOWER,
    22: CultivationBandId.MID_FLOWER,
    41: CultivationBandId.MID_FLOWER,
    42: CultivationBandId.LATE_FLOWER,
    43: CultivationBandId.LATE_FLOWER,
}

_BAND_PLANT_STAGE = {
    CultivationBandId.EARLY_FLOWER: PlantStage.FLOWER_EARLY,
    CultivationBandId.MID_FLOWER: PlantStage.FLOWER_MID,
    CultivationBandId.LATE_FLOWER: PlantStage.FLOWER_LATE,
}

_BAND_BAYESIAN_STAGE = {
    CultivationBandId.EARLY_FLOWER: BayesianStage.FLOWER_EARLY,
    CultivationBandId.MID_FLOWER: BayesianStage.FLOWER_MID,
    CultivationBandId.LATE_FLOWER: BayesianStage.FLOWER_LATE,
}


def _flowering_plant(flower_day: int) -> Plant:
    """A Plant on day ``flower_day`` of a single, uninterrupted flower interval."""
    flower_start = OBSERVED_ON - timedelta(days=flower_day)
    veg_start = flower_start - timedelta(days=30)
    return Plant(
        plant_id=f"flower-{flower_day}",
        growspace_id="main",
        stage="flower",
        veg_start=veg_start.isoformat(),
        flower_start=flower_start.isoformat(),
        stage_history=[
            {
                "stage": "veg",
                "start": veg_start.isoformat(),
                "end": flower_start.isoformat(),
            },
            {"stage": "flower", "start": flower_start.isoformat(), "end": None},
        ],
    )


def _environment_state(flower_days: int) -> EnvironmentState:
    return EnvironmentState(
        flower_days=flower_days,
        veg_days=-1,
        seedling_days=-1,
        clone_days=-1,
        dry_days=-1,
        cure_days=-1,
        mother_days=-1,
    )


# ---------------------------------------------------------------------------
# AC1 — one band for one plant on one day, across every consumer
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("flower_day", BOUNDARY_DAYS)
def test_every_consumer_selects_the_same_band_on_the_boundary_days(
    flower_day: int,
) -> None:
    """Dehumidifier, humidifier, both fans, and Bayesian agree on days 21 and 42.

    The dehumidifier and humidifier (``VpdOnOffController``) and the circulation
    and exhaust fans (``resolve_stage_vpd_target``) all key their thresholds on
    ``determine_coordinator_stage``; the Bayesian VPD and humidity evaluation
    keys on ``classify_stages`` and ``_determine_stage_key``. All four call sites
    are checked here against the band the lifecycle module reports.
    """
    expected = _EXPECTED_BAND[flower_day]
    plant = _flowering_plant(flower_day)

    assert plant_cultivation_band(plant, observed_on=OBSERVED_ON).identity == expected
    assert (
        growspace_cultivation_band([plant], observed_on=OBSERVED_ON).identity
        == expected
    )
    # Threshold tables for the actuators are keyed by PlantStage.
    assert determine_coordinator_stage([plant]) == _BAND_PLANT_STAGE[expected]
    # Bayesian evaluation is keyed by BayesianStage. `stage_a` is the band the
    # growspace is in; `stage_b`/`factor` are the interpolation hint toward the
    # next one, and never move the band identity early.
    assert (
        classify_stages(StageDays(flower=flower_day)).stage_a
        == _BAND_BAYESIAN_STAGE[expected]
    )
    assert (
        _determine_stage_key(_environment_state(flower_days=flower_day))
        == _BAND_BAYESIAN_STAGE[expected]
    )


@pytest.mark.parametrize("flower_day", BOUNDARY_DAYS)
def test_band_plant_stage_round_trips_the_coordinator_stage(flower_day: int) -> None:
    """The band → PlantStage map is what the coordinator stage actually returns."""
    plant = _flowering_plant(flower_day)
    band = growspace_cultivation_band([plant], observed_on=OBSERVED_ON)

    assert band_plant_stage(band) == determine_coordinator_stage([plant])


def test_day_21_and_42_are_the_days_the_band_changes() -> None:
    """Day 21 enters Mid and day 42 enters Late — not the day after either."""
    bands = {
        day: plant_cultivation_band(
            _flowering_plant(day), observed_on=OBSERVED_ON
        ).identity
        for day in (20, 21, 41, 42)
    }

    assert bands[20] is CultivationBandId.EARLY_FLOWER
    assert bands[21] is CultivationBandId.MID_FLOWER
    assert bands[41] is CultivationBandId.MID_FLOWER
    assert bands[42] is CultivationBandId.LATE_FLOWER


@pytest.mark.parametrize(
    ("flower_day", "expected_stage"),
    [
        (20, BayesianStage.FLOWER_EARLY),
        (41, BayesianStage.FLOWER_MID),
    ],
)
def test_current_stage_vpd_override_matches_the_reported_granular_stage(
    flower_day: int,
    expected_stage: BayesianStage,
) -> None:
    """The card's Current row names the override the fan resolver applies."""
    overrides = {
        "flower_early": {"day": 1.01, "night": 1.02},
        "flower_mid": {"day": 1.21, "night": 1.22},
        "flower_late": {"day": 1.41, "night": 1.42},
    }
    classification = classify_stages(StageDays(flower=flower_day))

    # EnvironmentAnalyzer publishes display_stage as granular_stage; the card
    # marks that key Current. It must name the same override used by both fans.
    granular_stage = classification.display_stage
    applied_target = resolve_stage_vpd_target(
        [_flowering_plant(flower_day)], overrides, fallback_vpd_target=0.5, is_day=True
    )

    assert granular_stage is expected_stage
    assert applied_target == overrides[granular_stage.value]["day"]


def test_the_growspace_band_is_the_most_demanding_plant() -> None:
    """A mixed growspace takes the furthest-along plant's band, as it always did."""
    plants = [_flowering_plant(5), _flowering_plant(42), _flowering_plant(21)]

    band = growspace_cultivation_band(plants, observed_on=OBSERVED_ON)

    assert band.identity is CultivationBandId.LATE_FLOWER
    assert determine_coordinator_stage(plants) == PlantStage.FLOWER_LATE


def test_an_empty_growspace_still_reports_veg() -> None:
    """The neutral default for a growspace with no plants is unchanged."""
    assert determine_coordinator_stage([]) == PlantStage.VEG


# ---------------------------------------------------------------------------
# Current Stage Age — the current open interval only
# ---------------------------------------------------------------------------


def _revegged_plant() -> Plant:
    """Second veg stint, five days old, after a 40-day first stint and flower."""
    reveg = OBSERVED_ON - timedelta(days=5)
    flower_start = reveg - timedelta(days=56)
    first_veg_start = flower_start - timedelta(days=40)
    return Plant(
        plant_id="reveg",
        growspace_id="main",
        stage="flower",
        veg_start=reveg.isoformat(),
        flower_start=flower_start.isoformat(),
        stage_history=[
            {
                "stage": "veg",
                "start": first_veg_start.isoformat(),
                "end": flower_start.isoformat(),
            },
            {
                "stage": "flower",
                "start": flower_start.isoformat(),
                "end": reveg.isoformat(),
            },
            {"stage": "veg", "start": reveg.isoformat(), "end": None},
        ],
    )


def test_current_stage_age_is_the_open_interval_not_the_lifetime() -> None:
    """A revegged plant is five days into veg, not forty-five."""
    plant = _revegged_plant()

    assert current_stage_age(plant, observed_on=OBSERVED_ON) == 5


def test_current_stage_age_falls_back_with_the_stage_it_resolved() -> None:
    """With no stored history the legacy day count answers, for the same stage."""
    flower_start = OBSERVED_ON - timedelta(days=19)
    plant = Plant(
        plant_id="legacy",
        growspace_id="main",
        stage="",
        veg_start=(flower_start - timedelta(days=30)).isoformat(),
        flower_start=flower_start.isoformat(),
        stage_history=[],
    )

    assert current_stage_age(plant, observed_on=OBSERVED_ON) == 19


def test_current_stage_age_in_answers_only_for_the_current_stage() -> None:
    """ "Veg day N" has no answer while the plant is in flower."""
    plant = _revegged_plant()

    assert current_stage_age_in(plant, "veg", observed_on=OBSERVED_ON) == 5
    assert current_stage_age_in(plant, "flower", observed_on=OBSERVED_ON) is None


# ---------------------------------------------------------------------------
# AC2 — nutrient eligibility is gated on Current Stage Age
# ---------------------------------------------------------------------------


def _nutrient_manager(plant: Plant, min_days_in_stage: int) -> NutrientManager:
    repository = MagicMock()
    repository.get_plant.return_value = plant
    manager = NutrientManager(repository=repository, save_callback=MagicMock())
    manager.nutrient_presets = {
        "veg": NutrientPreset(
            id="veg",
            name="Veg",
            items=[],
            stage="veg",
            min_days_in_stage=min_days_in_stage,
            created_at="2025-01-01",
        )
    }
    return manager


def test_min_days_in_stage_counts_only_the_current_veg_stint() -> None:
    """A plant five days into its second veg stint is not a 30-day veg plant."""
    plant = _revegged_plant()
    manager = _nutrient_manager(plant, min_days_in_stage=30)

    assert manager.get_applicable_presets("reveg") == []


def test_min_days_in_stage_still_admits_a_long_enough_current_stint() -> None:
    """The gate opens on the current interval's own age."""
    plant = _revegged_plant()
    manager = _nutrient_manager(plant, min_days_in_stage=5)

    assert [preset.id for preset in manager.get_applicable_presets("reveg")] == ["veg"]


# ---------------------------------------------------------------------------
# AC3 — timed-notification day triggers fire on Current Stage Age
# ---------------------------------------------------------------------------


async def _run_timed_notification(
    plant: Plant, *, trigger_type: str, day: int
) -> AsyncMock:
    """Drive one day-of-stage timed notification over a single plant."""
    hass = MagicMock()
    coordinator = MagicMock()
    coordinator.options = {
        "timed_notifications": [
            {
                "id": "day_trigger",
                "trigger_type": trigger_type,
                "day": day,
                "message": f"{trigger_type} Day {day}",
                "growspace_ids": ["main"],
            }
        ]
    }
    coordinator.plants = {plant.plant_id: plant}
    coordinator.growspaces = {"main": MagicMock(id="main")}
    coordinator.notification_state.sent = {plant.plant_id: {}}
    coordinator.async_commit = AsyncMock()

    manager = NotificationManager(hass, coordinator, MagicMock())
    manager.async_send_notification = AsyncMock()
    await manager.async_check_timed_notifications()
    return manager.async_send_notification


async def test_day_trigger_excludes_the_veg_time_before_a_reveg() -> None:
    """ "Veg day 30" does not fire on day five of the second veg stint."""
    send = await _run_timed_notification(_revegged_plant(), trigger_type="veg", day=30)

    send.assert_not_awaited()


async def test_day_trigger_fires_on_the_current_stints_own_age() -> None:
    """ "Veg day 5" fires once the current interval reaches day five."""
    send = await _run_timed_notification(_revegged_plant(), trigger_type="veg", day=5)

    send.assert_awaited_once()


async def test_day_trigger_is_silent_for_a_stage_the_plant_has_left() -> None:
    """A flower-day trigger has nothing to say about a plant back in veg."""
    send = await _run_timed_notification(
        _revegged_plant(), trigger_type="flower", day=1
    )

    send.assert_not_awaited()
