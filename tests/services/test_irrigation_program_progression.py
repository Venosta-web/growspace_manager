"""Tests for Irrigation Program progression and the Program Hold (ADR-0045).

Every case here is one of two questions: did anything get written, and does the
payload say why. The [[Program Hold]] promise is that an ambiguous week changes
nothing, so the assertions that matter most are the ones checking a *setpoint*
did not move.
"""

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.growspace_manager.const import (
    DOMAIN,
    EVENT_GROWSPACE_LOG_ENTRY,
    IrrigationRecipeKind,
    PlantStage,
    ShotSizingMode,
    SubstrateMediaType,
)
from custom_components.growspace_manager.coordinator import GrowspaceCoordinator
from custom_components.growspace_manager.domain.irrigation_program import (
    ProgramHold,
    ProgramProgressionState,
)
from custom_components.growspace_manager.models import (
    Growspace,
    Plant,
    SubstrateProfile,
)
from custom_components.growspace_manager.view_model_builder import ViewModelBuilder
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from tests.common import MockConfigEntry, async_capture_events

# Where the feed seam puts tent_a: 15 days into flower is week 3.
CURRENT_STAGE, CURRENT_WEEK = "flower", 3


def _growspace(growspace_id: str) -> Growspace:
    """Return a Volume Mode growspace with usable plumbing."""
    growspace = Growspace(id=growspace_id, name=growspace_id.title())
    growspace.irrigation_strategy.enabled = True
    growspace.irrigation_strategy.substrate_profile = SubstrateProfile(
        media_type=SubstrateMediaType.COCO, liters_per_pot=6.0
    )
    growspace.irrigation_strategy.shot_sizing_mode = ShotSizingMode.VOLUME
    growspace.irrigation_strategy.p1_shot_volume_percent = 3.0
    growspace.irrigation_strategy.target_vwc_percent = 55.0
    growspace.irrigation_config.pump_flow_rate_ml_per_sec = 50.0
    return growspace


@pytest.fixture
def coordinator(hass: HomeAssistant) -> GrowspaceCoordinator:
    """A coordinator holding tent_a in flower week 3, and an empty tent_b."""
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    coordinator = GrowspaceCoordinator.build(hass, entry, data={})
    coordinator.storage_manager.async_force_save = AsyncMock()
    coordinator.view_model_builder = MagicMock()
    coordinator.view_model_builder.build_data_property.return_value = {}
    coordinator._data_repository.add_growspace(_growspace("tent_a"))
    coordinator._data_repository.add_growspace(_growspace("tent_b"))
    coordinator._data_repository.add_plant(
        Plant(
            plant_id="p1",
            growspace_id="tent_a",
            stage=PlantStage.FLOWER.value,
            flower_start=(dt_util.now().date() - timedelta(days=15)).isoformat(),
        )
    )
    return coordinator


@pytest.fixture
def notified(coordinator: GrowspaceCoordinator) -> AsyncMock:
    """Capture what the grower is told, without a real notification target."""
    sent = AsyncMock()
    coordinator.services.notifications.manager.async_send_notification = sent
    return sent


def _slots(*slots: tuple[str, int, str]) -> list[dict]:
    """Return raw slot payloads for ``(stage, week, recipe_id)`` triples."""
    return [
        {"stage": stage, "week": week, "recipe_id": recipe_id}
        for stage, week, recipe_id in slots
    ]


async def _recipe(
    coordinator: GrowspaceCoordinator, name: str, *, target_vwc: float
) -> str:
    """Save a crop-steering recipe that asks for ``target_vwc``.

    Captured from tent_b, which is otherwise identical to tent_a, so the only
    difference a stamp makes to tent_a is the one the test is watching.
    """
    tent_b = coordinator.growspaces["tent_b"]
    tent_b.irrigation_strategy.target_vwc_percent = target_vwc
    recipe = await coordinator.services.config.save_irrigation_recipe(
        "tent_b", name, IrrigationRecipeKind.CROP_STEERING
    )
    return recipe.id


async def _bind(
    coordinator: GrowspaceCoordinator,
    *slots: tuple[str, int, str],
    auto_advance: bool = False,
    growspace_id: str = "tent_a",
) -> str:
    """Set the auto-advance flag, then bind a program holding ``slots``.

    In that order because assigning with auto-advance already on applies the
    current slot — which several tests are here to check.
    """
    await coordinator.services.growspaces.set_irrigation_settings(
        growspace_id, {"program_auto_advance": auto_advance}
    )
    program = await coordinator.services.config.save_irrigation_program(
        "Full run", _slots(*slots)
    )
    await coordinator.services.growspaces.assign_irrigation_program(
        growspace_id, program.id
    )
    return program.id


def _reported(coordinator: GrowspaceCoordinator, growspace_id: str = "tent_a") -> dict:
    """Return the growspace payload's ``irrigation.program`` block."""
    coordinator.cache.invalidate(growspace_id)
    payload = ViewModelBuilder(coordinator).build_serialized_growspace(growspace_id)
    return payload["irrigation"]["program"]


# ---------------------------------------------------------------------------
# The opt-in flag
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_auto_advance_defaults_off(hass, coordinator) -> None:
    """Opt-in, exactly as the two steering-phase flags beside it are."""
    assert coordinator.growspaces["tent_a"].irrigation_config.program_auto_advance is (
        False
    )


@pytest.mark.asyncio
async def test_auto_advance_round_trips_through_the_settings_seam(
    hass, coordinator
) -> None:
    """It is an ordinary irrigation setting, written the ordinary way."""
    await coordinator.services.growspaces.set_irrigation_settings(
        "tent_a", {"program_auto_advance": True}
    )

    assert coordinator.growspaces["tent_a"].irrigation_config.program_auto_advance
    assert _reported(coordinator) is None  # nothing bound yet

    await coordinator.services.growspaces.set_irrigation_settings(
        "tent_a", {"program_auto_advance": False}
    )
    assert not coordinator.growspaces["tent_a"].irrigation_config.program_auto_advance


# ---------------------------------------------------------------------------
# Auto-advance on: the stamp
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crossing_into_a_week_with_a_slot_stamps_it_once(
    hass, coordinator
) -> None:
    """The load-bearing happy path, and the "exactly once" that guards it."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, ("veg", 1, recipe_id), auto_advance=True)
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    assert strategy.target_vwc_percent == 55.0  # veg week 1 is not where tent_a is

    events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    await coordinator.services.config.save_irrigation_program(
        "Full run",
        _slots(("veg", 1, recipe_id), (CURRENT_STAGE, CURRENT_WEEK, recipe_id)),
        program_id=strategy.irrigation_program_id,
    )

    assert await coordinator.program_progression.async_evaluate("tent_a") is not None
    assert strategy.target_vwc_percent == 61.0
    assert strategy.applied_recipe_id == recipe_id
    await hass.async_block_till_done()
    assert len(events) == 1
    assert "advanced to flower week 3" in events[0].data["message"]

    # The second evaluation finds the growspace already holding it.
    progression = await coordinator.program_progression.async_evaluate("tent_a")
    await hass.async_block_till_done()
    assert progression.state is ProgramProgressionState.UP_TO_DATE
    assert len(events) == 1


@pytest.mark.asyncio
async def test_a_hand_tweak_after_the_stamp_is_never_written_back_over(
    hass, coordinator
) -> None:
    """Re-stamping the week's own recipe would discard hand-tuning."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(
        coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id), auto_advance=True
    )

    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    assert strategy.target_vwc_percent == 61.0
    strategy.target_vwc_percent = 58.0

    await coordinator.program_progression.async_evaluate("tent_a")

    assert strategy.target_vwc_percent == 58.0


@pytest.mark.asyncio
async def test_a_drifted_growspace_is_held_and_the_grower_is_told(
    hass, coordinator, notified
) -> None:
    """Auto-advance never overwrites a hand tweak; it stops and says so."""
    week_two = await _recipe(coordinator, "Flower wk2", target_vwc=59.0)
    week_three = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, 2, week_two), auto_advance=True)

    # Applied at week 2, then hand-tuned; week 3 now calls for a different one.
    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", week_two)
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    strategy.target_vwc_percent = 57.0
    await coordinator.services.config.save_irrigation_program(
        "Full run",
        _slots((CURRENT_STAGE, 2, week_two), (CURRENT_STAGE, CURRENT_WEEK, week_three)),
        program_id=strategy.irrigation_program_id,
    )
    notified.reset_mock()

    events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    progression = await coordinator.program_progression.async_evaluate("tent_a")

    assert progression.hold is ProgramHold.DRIFTED
    assert strategy.target_vwc_percent == 57.0
    assert strategy.applied_recipe_id == week_two
    assert events == []
    notified.assert_awaited_once()
    assert "no longer match" in notified.await_args.args[2]

    # Still stuck on the same week for the same reason: said once, not per tick.
    notified.reset_mock()
    await coordinator.program_progression.async_evaluate("tent_a")
    notified.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_hold_with_auto_advance_off_is_reported_but_not_announced(
    hass, coordinator, notified
) -> None:
    """Nothing was going to be written, so there is nothing to interrupt for."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id))
    await coordinator.services.config.remove_irrigation_recipe(recipe_id)
    notified.reset_mock()

    progression = await coordinator.program_progression.async_evaluate("tent_a")

    assert progression.hold is ProgramHold.RECIPE_MISSING
    notified.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_deleted_recipe_behaves_as_a_gap_and_never_actuates(
    hass, coordinator, notified
) -> None:
    """Deleting a recipe empties slots rather than cascading (ADR-0045)."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id))
    await coordinator.services.config.remove_irrigation_recipe(recipe_id)
    await coordinator.services.growspaces.set_irrigation_settings(
        "tent_a", {"program_auto_advance": True}
    )

    progression = await coordinator.program_progression.async_evaluate("tent_a")

    assert progression.hold is ProgramHold.RECIPE_MISSING
    assert coordinator.growspaces["tent_a"].irrigation_strategy.target_vwc_percent == (
        55.0
    )
    assert _reported(coordinator)["progression"]["hold"] == "recipe_missing"


@pytest.mark.asyncio
async def test_a_recipe_the_growspace_cannot_run_holds_rather_than_raising(
    hass, coordinator, notified
) -> None:
    """A refusal inside the tick must become a hold, never an exception."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    # tent_a switches to the time-schedule half, which the recipe does not hold.
    coordinator.growspaces["tent_a"].irrigation_strategy.enabled = False
    await _bind(
        coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id), auto_advance=True
    )

    progression = await coordinator.program_progression.async_evaluate("tent_a")

    assert progression.hold is ProgramHold.NOT_APPLICABLE
    assert coordinator.growspaces["tent_a"].irrigation_strategy.applied_recipe_id is (
        None
    )
    notified.assert_awaited_once()
    assert _reported(coordinator)["progression"]["hold"] == "not_applicable"


@pytest.mark.asyncio
async def test_a_deleted_applied_recipe_leaves_nothing_to_call_drift(
    hass, coordinator
) -> None:
    """Absence of evidence of a tweak is not evidence of one, so it advances."""
    week_two = await _recipe(coordinator, "Flower wk2", target_vwc=59.0)
    week_three = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, 2, week_two))

    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", week_two)
    await coordinator.services.config.remove_irrigation_recipe(week_two)
    await coordinator.services.config.save_irrigation_program(
        "Full run",
        _slots((CURRENT_STAGE, CURRENT_WEEK, week_three)),
        program_id=coordinator.growspaces[
            "tent_a"
        ].irrigation_strategy.irrigation_program_id,
    )
    await coordinator.services.growspaces.set_irrigation_settings(
        "tent_a", {"program_auto_advance": True}
    )

    await coordinator.program_progression.async_evaluate("tent_a")

    # Re-read: the settings seam replaces the strategy rather than mutating it.
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    assert strategy.target_vwc_percent == 61.0
    assert strategy.applied_recipe_id == week_three


@pytest.mark.asyncio
async def test_a_growspace_that_is_gone_evaluates_to_nothing(hass, coordinator) -> None:
    """The refresh iterates a snapshot; a removal between the two is not a fault."""
    assert await coordinator.program_progression.async_evaluate("no_such_tent") is None


# ---------------------------------------------------------------------------
# The holds that change nothing under either setting
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("auto_advance", [True, False])
@pytest.mark.asyncio
async def test_a_week_with_no_slot_changes_nothing(
    hass, coordinator, auto_advance
) -> None:
    """Carrying the previous week forward would actuate on absent data."""
    recipe_id = await _recipe(coordinator, "Flower wk1", target_vwc=61.0)
    await _bind(
        coordinator,
        (CURRENT_STAGE, 1, recipe_id),
        (CURRENT_STAGE, 5, recipe_id),
        auto_advance=auto_advance,
    )

    progression = await coordinator.program_progression.async_evaluate("tent_a")

    assert progression.hold is ProgramHold.NO_SLOT
    assert coordinator.growspaces["tent_a"].irrigation_strategy.target_vwc_percent == (
        55.0
    )
    reported = _reported(coordinator)
    assert reported["progression"]["state"] == "held"
    assert reported["progression"]["hold"] == "no_slot"
    assert reported["slot"] is None


@pytest.mark.parametrize("auto_advance", [True, False])
@pytest.mark.asyncio
async def test_passing_the_last_week_reports_the_program_complete(
    hass, coordinator, auto_advance
) -> None:
    """A finished run reads as finished, not as a plan that broke."""
    recipe_id = await _recipe(coordinator, "Flower wk1", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, 1, recipe_id), auto_advance=auto_advance)

    progression = await coordinator.program_progression.async_evaluate("tent_a")

    assert progression.hold is ProgramHold.PROGRAM_COMPLETE
    assert coordinator.growspaces["tent_a"].irrigation_strategy.target_vwc_percent == (
        55.0
    )
    assert _reported(coordinator)["progression"]["hold"] == "program_complete"


@pytest.mark.asyncio
async def test_a_growspace_with_no_live_plants_holds_without_a_position(
    hass, coordinator
) -> None:
    """No live cohort, so no week to be in and nothing to apply."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(
        coordinator,
        (CURRENT_STAGE, CURRENT_WEEK, recipe_id),
        auto_advance=True,
        growspace_id="tent_b",
    )

    progression = await coordinator.program_progression.async_evaluate("tent_b")

    assert progression.hold is ProgramHold.NO_POSITION
    assert _reported(coordinator, "tent_b")["progression"]["hold"] == "no_position"


# ---------------------------------------------------------------------------
# Auto-advance off: recommend, never write
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_with_auto_advance_off_the_payload_recommends_and_nothing_moves(
    hass, coordinator
) -> None:
    """The default: the card recommends, the grower confirms."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id))

    events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    progression = await coordinator.program_progression.async_evaluate("tent_a")

    assert progression.state is ProgramProgressionState.AVAILABLE
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    assert strategy.target_vwc_percent == 55.0
    assert strategy.applied_recipe_id is None
    assert events == []

    reported = _reported(coordinator)
    assert reported["auto_advance"] is False
    assert reported["progression"]["state"] == "available"
    assert reported["recipe"]["id"] == recipe_id

    # Until the grower applies it explicitly.
    await coordinator.services.growspaces.apply_irrigation_recipe("tent_a", recipe_id)
    assert strategy.target_vwc_percent == 61.0
    assert _reported(coordinator)["progression"]["state"] == "up_to_date"


# ---------------------------------------------------------------------------
# Assignment
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_assigning_with_auto_advance_on_applies_the_current_slot(
    hass, coordinator
) -> None:
    """Consent given in advance is still consent."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(
        coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id), auto_advance=True
    )

    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    assert strategy.target_vwc_percent == 61.0
    assert strategy.applied_recipe_id == recipe_id


@pytest.mark.asyncio
async def test_assigning_with_auto_advance_off_applies_nothing(
    hass, coordinator
) -> None:
    """Picking a program from a dropdown must not change what a pump does."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id))

    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    assert strategy.target_vwc_percent == 55.0
    assert strategy.applied_recipe_id is None
    assert strategy.irrigation_program_id is not None


@pytest.mark.asyncio
async def test_unassigning_reports_no_program_at_all(hass, coordinator) -> None:
    """An unbound growspace has no position, not a held one."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(
        coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id), auto_advance=True
    )
    await coordinator.services.growspaces.assign_irrigation_program("tent_a", None)

    assert await coordinator.program_progression.async_evaluate("tent_a") is None
    assert _reported(coordinator) is None


# ---------------------------------------------------------------------------
# The refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_impossible_growspace_does_not_break_the_refresh(
    hass, coordinator
) -> None:
    """The hold promise is inertness; an exception here would break far more."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(
        coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id), auto_advance=True
    )
    coordinator.program_progression.async_evaluate = AsyncMock(
        side_effect=RuntimeError("boom")
    )

    await coordinator.program_progression.async_evaluate_all()
