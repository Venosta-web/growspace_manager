"""Tests for soil-moisture stress evaluation against the Acceptable Moisture Band.

These pin the evidence side of the band: which readings add moisture-stress
evidence, which add none, and that the reasons name both the reading and the
effective boundary a grower needs to act on.
"""

from __future__ import annotations

import pytest

from custom_components.growspace_manager.bayesian_data import (
    PROB_SOIL_MOISTURE_STRESS,
)
from custom_components.growspace_manager.bayesian_evaluator import (
    evaluate_soil_moisture_stress,
)
from custom_components.growspace_manager.models import (
    EnvironmentConfig,
    EnvironmentState,
)


def _state(soil_moisture: float | None) -> EnvironmentState:
    """Build an EnvironmentState carrying only a moisture reading."""
    return EnvironmentState(soil_moisture=soil_moisture)


def _env(minimum: float | None = None, maximum: float | None = None) -> dict:
    """Serialize an EnvironmentConfig the way StressEvaluatorStrategy does."""
    return EnvironmentConfig(
        soil_moisture_min=minimum, soil_moisture_max=maximum
    ).to_dict()


@pytest.mark.parametrize(
    ("moisture", "expected_fragment"),
    [
        pytest.param(15.0, "Soil Moisture Low (15.0% < 20%)", id="below-default-min"),
        pytest.param(65.0, "Soil Moisture High (65.0% > 60%)", id="above-default-max"),
    ],
)
def test_default_band_reasons_name_reading_and_boundary(
    moisture: float, expected_fragment: str
) -> None:
    """An inherited band still explains itself with the effective boundary."""
    observations, reasons = evaluate_soil_moisture_stress(_state(moisture), _env())

    assert observations == [PROB_SOIL_MOISTURE_STRESS]
    assert [reason for _, reason in reasons] == [expected_fragment]


@pytest.mark.parametrize(
    "moisture",
    [
        pytest.param(20.0, id="exactly-on-minimum"),
        pytest.param(40.0, id="mid-band"),
        pytest.param(60.0, id="exactly-on-maximum"),
    ],
)
def test_in_band_readings_add_no_evidence(moisture: float) -> None:
    """Inclusive boundaries: on-bound and in-band readings add nothing.

    Nothing positive either — the absence of moisture-stress evidence must not
    become evidence that conditions are optimal.
    """
    observations, reasons = evaluate_soil_moisture_stress(_state(moisture), _env())

    assert observations == []
    assert reasons == []


def test_custom_band_narrows_what_counts_as_stress() -> None:
    """A reading acceptable under the default is stress under a tighter band."""
    in_default, _ = evaluate_soil_moisture_stress(_state(56.0), _env())
    assert in_default == []

    observations, reasons = evaluate_soil_moisture_stress(
        _state(56.0), _env(32.5, 54.0)
    )
    assert observations == [PROB_SOIL_MOISTURE_STRESS]
    assert reasons[0][1] == "Soil Moisture High (56.0% > 54%)"


def test_custom_band_widens_what_counts_as_stress() -> None:
    """A reading that is stress under the default can be fine under a wider band."""
    observations, reasons = evaluate_soil_moisture_stress(
        _state(15.0), _env(10.0, 80.0)
    )
    assert observations == []
    assert reasons == []


def test_custom_band_reason_reports_the_custom_boundary() -> None:
    """The boundary in the reason is the effective one, not the default."""
    _, reasons = evaluate_soil_moisture_stress(_state(30.0), _env(32.5, 54.0))
    assert reasons[0][1] == "Soil Moisture Low (30.0% < 32.5%)"


def test_missing_reading_produces_no_evidence() -> None:
    """An unavailable or excluded sensor leaves stress evaluation untouched."""
    observations, reasons = evaluate_soil_moisture_stress(
        _state(None), _env(32.5, 54.0)
    )
    assert observations == []
    assert reasons == []


def test_partial_stored_band_falls_back_to_the_default() -> None:
    """A half-written config (pre-dating the write seam) still classifies sanely."""
    observations, reasons = evaluate_soil_moisture_stress(
        _state(15.0), _env(minimum=32.5)
    )
    assert observations == [PROB_SOIL_MOISTURE_STRESS]
    assert reasons[0][1] == "Soil Moisture Low (15.0% < 20%)"
