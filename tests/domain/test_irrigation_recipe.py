"""Tests for Irrigation Recipe capture (ADR-0045)."""

import pytest

from custom_components.growspace_manager.const import ShotSizingMode, SubstrateMediaType
from custom_components.growspace_manager.domain.irrigation_recipe import (
    RecipeCaptureError,
    capture_crop_steering,
    capture_provenance,
    capture_schedule,
)
from custom_components.growspace_manager.domain.shot_sizing import percent_to_seconds
from custom_components.growspace_manager.models import (
    ECTargetRange,
    IrrigationConfig,
    IrrigationStrategy,
    SubstrateProfile,
)


def _strategy(**overrides) -> IrrigationStrategy:
    """Return a strategy with a usable substrate profile."""
    strategy = IrrigationStrategy(
        substrate_profile=SubstrateProfile(
            media_type=SubstrateMediaType.COCO, liters_per_pot=6.0
        ),
    )
    for key, value in overrides.items():
        setattr(strategy, key, value)
    return strategy


def _config(**overrides) -> IrrigationConfig:
    """Return a config with a measured pump flow rate."""
    config = IrrigationConfig(pump_flow_rate_ml_per_sec=50.0)
    for key, value in overrides.items():
        setattr(config, key, value)
    return config


# --- Volume Mode: the percent is already the stored truth ------------------


def test_volume_mode_stores_the_percent_values_directly() -> None:
    """Nothing is derived when the growspace already thinks in percent."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.VOLUME,
        p1_shot_volume_percent=3.5,
        p2_shot_volume_percent=6.25,
    )

    recipe = capture_crop_steering(strategy, _config(), live_plant_count=4)

    assert recipe.p1_shot_volume_percent == 3.5
    assert recipe.p2_shot_volume_percent == 6.25


def test_volume_mode_needs_no_live_plants() -> None:
    """An empty tent can still author a Volume Mode recipe."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.VOLUME, p1_shot_volume_percent=4.0
    )

    recipe = capture_crop_steering(strategy, _config(), live_plant_count=0)

    assert recipe.p1_shot_volume_percent == 4.0


# --- Seconds Mode: the percent is recovered --------------------------------


def test_seconds_mode_derives_the_percent_from_the_growspace_plumbing() -> None:
    """12s at 50 ml/s into 6 L pots is 600 ml, i.e. 10% of one pot."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.SECONDS,
        p1_shot_duration_seconds=12,
        p2_shot_duration_seconds=6,
    )

    recipe = capture_crop_steering(strategy, _config(), live_plant_count=1)

    assert recipe.p1_shot_volume_percent == pytest.approx(10.0)
    assert recipe.p2_shot_volume_percent == pytest.approx(5.0)


@pytest.mark.parametrize("live_plant_count", [1, 4, 12])
def test_derived_percent_is_computed_plant_count_independently(
    live_plant_count,
) -> None:
    """Two tents dosing the same per-pot percent recover that same percent.

    They need different seconds to do it — the forward conversion multiplies
    the live count in — so the inverse must divide it back out. Skipping that
    division would stamp the source tent's plant count into the stored value
    and mis-water every growspace the recipe is later applied to.
    """
    # 5% of a 6 L pot is 300 ml, an exact 6 s at 50 ml/s, so the round trip
    # is not blunted by the forward direction rounding to whole pump seconds.
    seconds = percent_to_seconds(
        5.0,
        liters_per_pot=6.0,
        live_plant_count=live_plant_count,
        flow_rate_ml_per_sec=50.0,
    )
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.SECONDS, p1_shot_duration_seconds=seconds
    )

    recipe = capture_crop_steering(
        strategy, _config(), live_plant_count=live_plant_count
    )

    assert recipe.p1_shot_volume_percent == pytest.approx(5.0)


@pytest.mark.parametrize(
    ("strategy_kwargs", "config_kwargs", "live_plant_count", "expected_phrase"),
    [
        ({}, {"pump_flow_rate_ml_per_sec": 0.0}, 4, "no pump flow rate"),
        (
            {"substrate_profile": SubstrateProfile(liters_per_pot=0.0)},
            {},
            4,
            "no substrate volume per pot",
        ),
        ({}, {}, 0, "no live plants"),
    ],
)
def test_seconds_mode_refuses_and_names_the_missing_prerequisite(
    strategy_kwargs, config_kwargs, live_plant_count, expected_phrase
) -> None:
    """The refusal says which input is missing, not just that it failed."""
    strategy = _strategy(shot_sizing_mode=ShotSizingMode.SECONDS, **strategy_kwargs)

    with pytest.raises(RecipeCaptureError) as err:
        capture_crop_steering(
            strategy, _config(**config_kwargs), live_plant_count=live_plant_count
        )

    assert expected_phrase in str(err.value)


# --- What a recipe deliberately leaves behind ------------------------------


def test_crop_steering_recipe_excludes_hardware_live_state_and_feed_ec() -> None:
    """The named exclusions are structurally absent, not merely unset."""
    strategy = _strategy(
        shot_sizing_mode=ShotSizingMode.VOLUME,
        detected_lights_on_time="05:12:00",
        enabled=True,
    )
    config = _config(
        irrigation_pump_entity="switch.pump",
        drain_pump_entity="switch.drain",
        active_steering_phase="p1",
        phase_changed_at="2026-08-11T09:00:00+00:00",
        ec_target_ranges=[ECTargetRange(stage="flower", feed_ec_min=1.0)],
    )

    stored = capture_crop_steering(strategy, config, live_plant_count=4).to_dict()

    for excluded in (
        "irrigation_pump_entity",
        "drain_pump_entity",
        "active_steering_phase",
        "phase_changed_at",
        "detected_lights_on_time",
        "ec_target_ranges",
        "enabled",
        "declared_steering_mode",
        "p1_shot_duration_seconds",
        "p2_shot_duration_seconds",
    ):
        assert excluded not in stored


def test_schedule_recipe_carries_the_times_and_leaves_the_pumps_behind() -> None:
    """The schedule half is when to fire, never what fires it."""
    config = _config(
        irrigation_times=[{"time": "08:00:00", "duration": 30}],
        drain_times=[{"time": "20:00:00", "duration": 10}],
        irrigation_duration=30,
        drain_duration=10,
        daily_volume_cap_liters=12.5,
        max_cycles_per_day=6,
        skip_during_dark=True,
        irrigation_pump_entity="switch.pump",
        ec_target_ranges=[ECTargetRange(stage="flower", feed_ec_min=1.0)],
    )

    recipe = capture_schedule(config)
    stored = recipe.to_dict()

    assert recipe.irrigation_times == [{"time": "08:00:00", "duration": 30}]
    assert recipe.daily_volume_cap_liters == 12.5
    assert recipe.max_cycles_per_day == 6
    assert recipe.skip_during_dark is True
    for excluded in ("irrigation_pump_entity", "drain_pump_entity", "ec_target_ranges"):
        assert excluded not in stored


def test_captured_schedule_times_do_not_alias_the_growspace() -> None:
    """A later edit to the growspace must not rewrite a saved recipe."""
    config = _config(irrigation_times=[{"time": "08:00:00", "duration": 30}])

    recipe = capture_schedule(config)
    config.irrigation_times[0]["duration"] = 999

    assert recipe.irrigation_times[0]["duration"] == 30


# --- Provenance -------------------------------------------------------------


def test_provenance_records_the_authoring_context() -> None:
    """Media, pot volume, flow rate and the week it was authored in."""
    strategy = _strategy(
        substrate_profile=SubstrateProfile(
            media_type=SubstrateMediaType.ROCKWOOL, liters_per_pot=3.0
        )
    )

    provenance = capture_provenance(strategy, _config(), stage="flower", week=3)

    assert provenance.media_type is SubstrateMediaType.ROCKWOOL
    assert provenance.liters_per_pot == 3.0
    assert provenance.pump_flow_rate_ml_per_sec == 50.0
    assert provenance.stage == "flower"
    assert provenance.week == 3
