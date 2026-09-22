"""Tests for the EC ramp curve service handlers.

These drive the **real** path: a real ``NutrientManager`` behind a real
``ConfigFacade``, with nothing mocked between the service handler and the stored
``ECRampCurve``. The previous version of this file replaced the facade method
with an ``AsyncMock`` and asserted it was called, which is exactly why the
dropped ``stage`` keyword and the positional misalignment behind it went
unnoticed for the whole life of the feature (workspace#108).
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    ATTR_CURVE_ID,
    ATTR_GROWSPACE_ID,
    ATTR_NAME,
    ATTR_POINTS,
    ATTR_STAGE,
)
from custom_components.growspace_manager.domain.ec_state import resolve_active_feed_ec
from custom_components.growspace_manager.managers.nutrient import NutrientManager
from custom_components.growspace_manager.models import ECTargetRange
from custom_components.growspace_manager.services.config_facade import ConfigFacade
from custom_components.growspace_manager.services.ec_ramp import (
    handle_remove_ec_ramp_curve,
    handle_save_ec_ramp_curve,
)

POINTS = [
    {"week": 1, "ec_min": 1.2, "ec_max": 1.6},
    {"week": 2, "ec_min": 1.4, "ec_max": 1.8},
]


@pytest.fixture
def nutrient_manager():
    """A real NutrientManager with a mocked repository and save callback."""
    repository = MagicMock()
    repository.get_plant.return_value = None
    return NutrientManager(repository=repository, save_callback=AsyncMock())


@pytest.fixture
def coordinator(nutrient_manager):
    """Coordinator stub carrying the real manager behind the real facade."""
    mock = MagicMock()
    mock._nutrient_manager = nutrient_manager
    mock.services.config = ConfigFacade(mock)
    return mock


def _call(**data):
    call = MagicMock()
    call.data = data
    return call


@pytest.mark.asyncio
async def test_save_stores_the_growers_name_stage_and_growspace(
    coordinator, nutrient_manager
) -> None:
    """The stored curve carries what the grower typed, in the right fields."""
    await handle_save_ec_ramp_curve(
        MagicMock(),
        coordinator,
        _call(
            **{
                ATTR_GROWSPACE_ID: "gs_1",
                ATTR_NAME: "9-Week Bloom Ramp",
                ATTR_STAGE: "flower",
                ATTR_POINTS: POINTS,
            }
        ),
    )

    (curve,) = nutrient_manager.ec_ramp_curves.values()
    assert curve.name == "9-Week Bloom Ramp"
    assert curve.stage == "flower"
    assert curve.growspace_id == "gs_1"
    assert [(p.week, p.ec_min, p.ec_max) for p in curve.points] == [
        (1, 1.2, 1.6),
        (2, 1.4, 1.8),
    ]


@pytest.mark.asyncio
async def test_save_with_curve_id_updates_in_place(
    coordinator, nutrient_manager
) -> None:
    """An explicit curve_id edits that curve rather than adding a second one."""
    await handle_save_ec_ramp_curve(
        MagicMock(),
        coordinator,
        _call(
            **{
                ATTR_GROWSPACE_ID: "gs_1",
                ATTR_NAME: "Veg Ramp",
                ATTR_STAGE: "veg",
                ATTR_POINTS: POINTS,
                ATTR_CURVE_ID: "curve-abc-123",
            }
        ),
    )
    await handle_save_ec_ramp_curve(
        MagicMock(),
        coordinator,
        _call(
            **{
                ATTR_GROWSPACE_ID: "gs_1",
                ATTR_NAME: "Veg Ramp v2",
                ATTR_STAGE: "veg",
                ATTR_POINTS: POINTS,
                ATTR_CURVE_ID: "curve-abc-123",
            }
        ),
    )

    assert list(nutrient_manager.ec_ramp_curves) == ["curve-abc-123"]
    assert nutrient_manager.ec_ramp_curves["curve-abc-123"].name == "Veg Ramp v2"


@pytest.mark.asyncio
async def test_saved_curve_drives_active_feed_ec_over_the_stage_range(
    coordinator, nutrient_manager
) -> None:
    """The acceptance case: a curve saved through the service wins over ECTargetRange.

    This is the end of the path the bug broke — the curve reached storage in a
    shape ``resolve_active_feed_ec`` could never match, so feed EC always fell
    through to the per-stage range.
    """
    await handle_save_ec_ramp_curve(
        MagicMock(),
        coordinator,
        _call(
            **{
                ATTR_GROWSPACE_ID: "gs_1",
                ATTR_NAME: "9-Week Bloom Ramp",
                ATTR_STAGE: "flower",
                ATTR_POINTS: POINTS,
            }
        ),
    )

    ranges = [ECTargetRange(stage="flower", feed_ec_min=9.0, feed_ec_max=9.9)]

    band, source = resolve_active_feed_ec(
        "gs_1", "flower", 2, nutrient_manager.ec_ramp_curves, ranges
    )
    assert (band, source) == ((1.4, 1.8), "ramp_curve")

    # A different growspace does not inherit it; it gets its own stage range.
    band, source = resolve_active_feed_ec(
        "gs_2", "flower", 2, nutrient_manager.ec_ramp_curves, ranges
    )
    assert (band, source) == ((9.0, 9.9), "stage_range")


@pytest.mark.asyncio
async def test_facade_refuses_an_unknown_keyword(coordinator) -> None:
    """The regression guard for the ``**kwargs`` that silently ate ``stage``.

    A caller whose keywords no longer match the facade must fail at the call, not
    store a curve missing whatever the facade did not recognise.
    """
    with pytest.raises(TypeError):
        await coordinator.services.config.save_ec_ramp_curve(
            growspace_id="gs_1",
            name="Bloom",
            stage="flower",
            points=POINTS,
            phase="p2",
        )


@pytest.mark.asyncio
async def test_handle_remove_ec_ramp_curve(coordinator, nutrient_manager) -> None:
    """Removing by curve_id deletes that curve."""
    await handle_save_ec_ramp_curve(
        MagicMock(),
        coordinator,
        _call(
            **{
                ATTR_GROWSPACE_ID: "gs_1",
                ATTR_NAME: "Bloom",
                ATTR_STAGE: "flower",
                ATTR_POINTS: POINTS,
                ATTR_CURVE_ID: "curve-xyz-456",
            }
        ),
    )

    await handle_remove_ec_ramp_curve(
        MagicMock(), coordinator, _call(**{ATTR_CURVE_ID: "curve-xyz-456"})
    )

    assert nutrient_manager.ec_ramp_curves == {}
