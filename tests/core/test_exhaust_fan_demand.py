"""Unit tests for the exhaust fan demand pure functions."""

import pytest

from custom_components.growspace_manager.domain.fan_control import (
    compute_exhaust_demand,
    compute_inverted_fan_speed,
)

_BANDS = {
    "temperature_target": 25.0,
    "temperature_tolerance": 2.0,
    "humidity_target": 60.0,
    "humidity_tolerance": 5.0,
    "vpd_target": 1.0,
    "vpd_tolerance": 0.2,
    "min_speed": 10,
    "max_speed": 90,
}


@pytest.mark.parametrize(
    ("value", "target", "tolerance", "min_speed", "max_speed", "expected"),
    [
        # VPD below (target - tolerance) → too humid → exhaust hard → max_speed
        (0.5, 1.0, 0.2, 10, 90, 90),
        # VPD at exactly lower bound → max_speed
        (0.8, 1.0, 0.2, 10, 90, 90),
        # VPD above (target + tolerance) → dry enough → exhaust min → min_speed
        (1.5, 1.0, 0.2, 10, 90, 10),
        # VPD at exactly upper bound → min_speed
        (1.2, 1.0, 0.2, 10, 90, 10),
        # VPD at target midpoint → midpoint speed
        (1.0, 1.0, 0.2, 10, 90, 50),
        # ¼ of the way up the band → ¾ exhaust (inverted)
        (0.9, 1.0, 0.2, 0, 100, 75),
    ],
)
def test_compute_inverted_fan_speed(
    value: float,
    target: float,
    tolerance: float,
    min_speed: int,
    max_speed: int,
    expected: int,
) -> None:
    """Inverted mapping: lower VPD → higher exhaust speed."""
    assert (
        compute_inverted_fan_speed(value, target, tolerance, min_speed, max_speed)
        == expected
    )


def test_combined_demand_takes_the_highest_term() -> None:
    """Demand is the max of the temperature, humidity and inverted-VPD terms.

    Hot tent (temp above band → 90), comfortable humidity (at target → 50),
    dry VPD (above band → inverted min → 10): the temperature term wins.
    """
    assert compute_exhaust_demand(30.0, 60.0, 1.5, **_BANDS) == 90


def test_combined_demand_vpd_inversion_can_dominate() -> None:
    """A too-humid VPD (below target) drives demand even when temp/humidity are calm."""
    # temp at target → 50, humidity at target → 50, vpd well below band → 90
    assert compute_exhaust_demand(25.0, 60.0, 0.5, **_BANDS) == 90


def test_combined_demand_skips_missing_terms() -> None:
    """A None reading drops that term from the max; remaining terms still count."""
    # No temperature reading; humidity above band → 90 should still win
    assert compute_exhaust_demand(None, 70.0, 1.5, **_BANDS) == 90


def test_combined_demand_all_missing_returns_none() -> None:
    """No readings at all → no demand to compute."""
    assert compute_exhaust_demand(None, None, None, **_BANDS) is None


# ---------------------------------------------------------------------------
# Source-air gate (ADR 0018 — suppress a term when incoming air won't help)
# ---------------------------------------------------------------------------


def test_temperature_term_suppressed_when_source_air_not_cooler() -> None:
    """A hot tent demands cooling, but lung-room air at/above tent temp can't help.

    Only the temperature sensor reads; with source air no cooler than the tent
    the term is dropped, so the (present-but-gated) reading floors at min_speed.
    """
    assert (
        compute_exhaust_demand(
            30.0,
            None,
            None,
            **_BANDS,
            lung_room_temperature=30.0,
            minimum_source_air_temperature=18.0,
        )
        == 10  # min_speed
    )


def test_temperature_term_suppressed_when_source_air_below_minimum() -> None:
    """Source air cooler than the tent but below the minimum is still suppressed."""
    assert (
        compute_exhaust_demand(
            30.0,
            None,
            None,
            **_BANDS,
            lung_room_temperature=15.0,  # cooler than tent, but below 18.0 floor
            minimum_source_air_temperature=18.0,
        )
        == 10  # min_speed
    )


def test_temperature_term_kept_when_source_air_cooler_and_warm_enough() -> None:
    """Cooler source air at/above the minimum keeps the cooling term in play."""
    assert (
        compute_exhaust_demand(
            30.0,  # hot tent → temp term = max_speed (90)
            None,
            None,
            **_BANDS,
            lung_room_temperature=22.0,  # cooler than tent and above 18.0 floor
            minimum_source_air_temperature=18.0,
        )
        == 90
    )


def test_moisture_terms_suppressed_when_source_air_not_drier() -> None:
    """A humid tent demands dehumidify-exhaust, but wetter source air can't help.

    Tent VPD 0.5 is below the 1.0 target (too humid); lung-room VPD 0.4 is even
    further from target, so admitting it would not dry the tent. Both the
    humidity and inverted-VPD terms are dropped; the readings still exist, so
    the suppressed demand floors at min_speed.
    """
    assert (
        compute_exhaust_demand(
            None,
            70.0,  # humid → humidity term = max_speed
            0.5,  # too humid → inverted-VPD term = max_speed
            **_BANDS,
            lung_room_vpd=0.4,  # not drier than the tent (further from target)
        )
        == 10  # min_speed
    )


def test_all_terms_gated_with_readings_returns_min_speed() -> None:
    """Readings present but every term gated → suppressed demand floors at min_speed.

    A no-op (``None``) is reserved for the no-readings case; once a sensor reads,
    a fully-gated tick still drives the fan down rather than leaving it running.
    """
    assert (
        compute_exhaust_demand(
            30.0,  # hot tent, but…
            70.0,  # humid, but…
            0.5,  # too humid, but…
            **_BANDS,
            lung_room_temperature=30.0,  # not cooler → temp term gated
            lung_room_vpd=0.4,  # not drier → moisture terms gated
            minimum_source_air_temperature=18.0,
        )
        == 10  # min_speed
    )


def test_moisture_terms_kept_when_source_air_drier() -> None:
    """Source air closer to the VPD target keeps the moisture terms in play."""
    assert (
        compute_exhaust_demand(
            None,
            70.0,
            0.5,
            **_BANDS,
            lung_room_vpd=0.8,  # drier than the tent (closer to 1.0 target)
        )
        == 90
    )
