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
    # Re-read: the stamp replaces both models rather than mutating them.
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
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
    assert (
        coordinator.growspaces["tent_a"].irrigation_strategy.target_vwc_percent == 61.0
    )
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


def _arm(coordinator: GrowspaceCoordinator, growspace_id: str = "tent_a") -> None:
    """Turn auto-advance on *after* binding, so the next evaluation owes a stamp.

    ``_bind`` sets the flag first on purpose, which makes the assignment itself
    perform the stamp. The cases below need the stamp to happen in an
    evaluation they control, with the store already sabotaged — and set the
    field rather than writing it through the settings seam, whose own refresh
    would spend the stamp before the test got to it.
    """
    coordinator.growspaces[growspace_id].irrigation_config.program_auto_advance = True


@pytest.mark.asyncio
async def test_a_failed_advance_changes_nothing_and_is_retried(
    hass, coordinator
) -> None:
    """The write module's restoration, reached through the automatic path.

    The failure is injected into the real store, underneath the real stamp, so
    what is under test is the seam Program Progression actually calls rather
    than a stand-in for it.
    """
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id))
    _arm(coordinator)

    target = coordinator.growspaces["tent_a"]
    prior_config, prior_strategy = target.irrigation_config, target.irrigation_strategy
    before = target.to_dict()
    events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    coordinator.async_request_refresh = AsyncMock()

    async def fail_save() -> None:
        # Mid-stamp: both models already carry the recipe that is about to be
        # taken back off them.
        assert target.irrigation_strategy.applied_recipe_id == recipe_id
        raise RuntimeError("store failed")

    coordinator.storage_manager.async_force_save.side_effect = fail_save
    with pytest.raises(RuntimeError, match="store failed"):
        await coordinator.program_progression.async_evaluate("tent_a")
    await hass.async_block_till_done()

    assert target.irrigation_config is prior_config
    assert target.irrigation_strategy is prior_strategy
    assert target.to_dict() == before
    assert events == []
    coordinator.async_request_refresh.assert_not_awaited()

    # Nothing was written, so the week is still owed: the next tick retries.
    coordinator.storage_manager.async_force_save.side_effect = None
    progression = await coordinator.program_progression.async_evaluate("tent_a")
    await hass.async_block_till_done()

    assert progression.state is ProgramProgressionState.DUE
    strategy = coordinator.growspaces["tent_a"].irrigation_strategy
    assert strategy.target_vwc_percent == 61.0
    assert strategy.applied_recipe_id == recipe_id
    assert len(events) == 1
    assert "advanced to flower week 3" in events[0].data["message"]

    # And having succeeded, it is done: the retry does not become a loop.
    progression = await coordinator.program_progression.async_evaluate("tent_a")
    await hass.async_block_till_done()
    assert progression.state is ProgramProgressionState.UP_TO_DATE
    assert len(events) == 1


@pytest.mark.asyncio
async def test_one_failing_growspace_does_not_stop_the_refresh(
    hass, coordinator
) -> None:
    """The hold promise is inertness; an exception here would break far more."""
    coordinator._data_repository.add_plant(
        Plant(
            plant_id="p2",
            growspace_id="tent_b",
            stage=PlantStage.FLOWER.value,
            flower_start=(dt_util.now().date() - timedelta(days=15)).isoformat(),
        )
    )
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    for growspace_id in ("tent_a", "tent_b"):
        await _bind(
            coordinator,
            (CURRENT_STAGE, CURRENT_WEEK, recipe_id),
            growspace_id=growspace_id,
        )
    # Armed only once both are bound: binding refreshes, and a refresh
    # evaluates, which would spend the stamp this test wants to watch.
    for growspace_id in ("tent_a", "tent_b"):
        _arm(coordinator, growspace_id)

    async def fail_for_tent_a() -> None:
        # tent_a is the only growspace whose stamp is in flight when its own
        # provenance already names the recipe.
        if (
            coordinator.growspaces["tent_a"].irrigation_strategy.applied_recipe_id
            == recipe_id
        ):
            raise RuntimeError("store failed")

    coordinator.storage_manager.async_force_save.side_effect = fail_for_tent_a

    await coordinator.program_progression.async_evaluate_all()
    await hass.async_block_till_done()

    assert coordinator.growspaces["tent_a"].irrigation_strategy.applied_recipe_id is (
        None
    )
    assert coordinator.growspaces["tent_a"].irrigation_strategy.target_vwc_percent == (
        55.0
    )
    tent_b = coordinator.growspaces["tent_b"].irrigation_strategy
    assert tent_b.applied_recipe_id == recipe_id
    assert tent_b.target_vwc_percent == 61.0


@pytest.mark.asyncio
async def test_a_schedule_slot_advances_the_config_half(hass, coordinator) -> None:
    """Both recipe kinds advance through the one write module, unchanged.

    Also the assignment-with-consent path: the flag is already on when the
    program is bound, so the binding itself performs this stamp.
    """
    for growspace_id in ("tent_a", "tent_b"):
        coordinator.growspaces[growspace_id].irrigation_strategy.enabled = False
    source = coordinator.growspaces["tent_b"].irrigation_config
    source.max_cycles_per_day = 8
    source.skip_during_dark = True
    source.irrigation_times = [{"time": "07:30:00", "duration": 45}]
    recipe = await coordinator.services.config.save_irrigation_recipe(
        "tent_b", "Flower timer", IrrigationRecipeKind.SCHEDULE
    )

    events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    await _bind(
        coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe.id), auto_advance=True
    )
    await hass.async_block_till_done()

    config = coordinator.growspaces["tent_a"].irrigation_config
    assert config.max_cycles_per_day == 8
    assert config.skip_during_dark is True
    assert config.irrigation_times == [{"time": "07:30:00", "duration": 45}]
    assert (
        coordinator.growspaces["tent_a"].irrigation_strategy.applied_recipe_id
        == recipe.id
    )
    assert len(events) == 1
    assert "advanced to flower week 3" in events[0].data["message"]

    # Detached from the library's copy, exactly as an explicit stamp is.
    config.irrigation_times[0]["duration"] = 99
    assert recipe.schedule.irrigation_times[0]["duration"] == 45
    assert source.irrigation_times[0]["duration"] == 45


@pytest.mark.asyncio
async def test_an_automatic_advance_respects_the_logbook_opt_out(
    hass, coordinator
) -> None:
    """Opting out of logbook entries opts out of the automatic ones too."""
    recipe_id = await _recipe(coordinator, "Flower wk3", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id))
    coordinator.growspaces["tent_a"].irrigation_config.log_to_logbook = False
    _arm(coordinator)

    events = async_capture_events(hass, EVENT_GROWSPACE_LOG_ENTRY)
    await coordinator.program_progression.async_evaluate("tent_a")
    await hass.async_block_till_done()

    assert events == []
    assert (
        coordinator.growspaces["tent_a"].irrigation_strategy.applied_recipe_id
        == recipe_id
    )


@pytest.mark.parametrize("failure", ["band", "flow", "pot"])
@pytest.mark.parametrize("auto_advance", [False, True])
@pytest.mark.asyncio
async def test_program_and_explicit_apply_share_complete_validation(
    hass, coordinator, notified, failure, auto_advance
) -> None:
    """An invalid candidate is displayed as held and cannot reach the auto writer."""
    recipe_id = await _recipe(coordinator, "Invalid week", target_vwc=61.0)
    await _bind(coordinator, (CURRENT_STAGE, CURRENT_WEEK, recipe_id))
    target = coordinator.growspaces["tent_a"]
    target.irrigation_config.program_auto_advance = auto_advance
    if failure == "band":
        await coordinator.services.config.update_irrigation_recipe(
            recipe_id,
            crop_steering={"pore_ec_target_min": 5.0, "pore_ec_target_max": 2.0},
        )
    elif failure == "flow":
        target.irrigation_config.pump_flow_rate_ml_per_sec = 0.0
    else:
        target.irrigation_strategy.substrate_profile.liters_per_pot = 0.0
    before = target.to_dict()
    coordinator.storage_manager.async_force_save.reset_mock()
    with pytest.raises(ValueError) as refused:
        await coordinator.services.growspaces.apply_irrigation_recipe(
            "tent_a", recipe_id
        )
    reported = _reported(coordinator)["progression"]
    assert reported["hold"] == ProgramHold.NOT_APPLICABLE.value
    assert reported["detail"] == str(refused.value)
    result = await coordinator.program_progression.async_evaluate("tent_a")
    assert result.hold is ProgramHold.NOT_APPLICABLE
    assert result.detail == str(refused.value)
    assert target.to_dict() == before
    coordinator.storage_manager.async_force_save.assert_not_awaited()
    if auto_advance:
        notified.assert_awaited_once()
    else:
        notified.assert_not_awaited()
    # Already carrying the slot still wins over applicability, as before.
    target.irrigation_strategy.applied_recipe_id = recipe_id
    result = await coordinator.program_progression.async_evaluate("tent_a")
    assert result.state is ProgramProgressionState.UP_TO_DATE
    coordinator.storage_manager.async_force_save.assert_not_awaited()
