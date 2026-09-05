"""Atomic persistence-shell tests for Plant Lifecycle mutations."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.growspace_manager.const import (
    EVENT_GROWSPACE_LOG_ENTRY,
    PlantStage,
)
from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.data_access.notification_state import (
    NotificationState,
)
from custom_components.growspace_manager.exceptions import ValidationChangeError
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Growspace, Plant, PlantGenetics
from custom_components.growspace_manager.services.context import ServiceContext


def _plant(
    plant_id: str,
    stage: PlantStage,
    started_on: str,
    growspace_id: str = "main",
) -> Plant:
    field = f"{stage.value}_start"
    return Plant(
        plant_id=plant_id,
        growspace_id=growspace_id,
        genetics=PlantGenetics(strain_name="Test"),
        stage=stage,
        created_at=started_on,
        stage_history=[{"stage": stage.value, "start": started_on, "end": None}],
        **{field: started_on},
    )


@pytest.fixture
def repository() -> GrowspaceRepository:
    """Repository with a normal cultivation growspace."""
    result = GrowspaceRepository()
    result.add_growspace(Growspace(id="main", name="Main", rows=5, plants_per_row=5))
    return result


@pytest.fixture
def manager_factory(repository: GrowspaceRepository):
    """Build a manager around real in-memory models and controllable persistence."""

    def build(save_callback: AsyncMock | None = None) -> PlantManager:
        growspace_manager = Mock()

        def ensure_special(
            growspace_id: str | PlantStage,
            name: str,
            rows: int = 5,
            plants_per_row: int = 5,
            **_: object,
        ) -> str:
            canonical = str(growspace_id)
            if not repository.has_growspace(canonical):
                repository.add_growspace(
                    Growspace(
                        id=canonical,
                        name=name,
                        rows=rows,
                        plants_per_row=plants_per_row,
                    )
                )
            return canonical

        growspace_manager.ensure_special_growspace.side_effect = ensure_special
        growspace_manager.ensure_mother_growspace.side_effect = lambda: ensure_special(
            PlantStage.MOTHER, "mother"
        )

        validator = Mock()
        validator.validate_position_not_occupied.return_value = None
        validator.validate_plant_exists.return_value = None
        validator.find_first_available_position.return_value = (1, 1)

        hass = Mock()
        hass.bus.async_fire = Mock()
        return PlantManager(
            ctx=ServiceContext(
                save_callback=save_callback or AsyncMock(),
                lock=asyncio.Lock(),
                add_event=Mock(),
                invalidate_cache=Mock(),
            ),
            hass=hass,
            repository=repository,
            notification_state=NotificationState(),
            validator=validator,
            growspace_manager=growspace_manager,
            strain_library=Mock(record_harvest=AsyncMock()),
            plant_view_builder=Mock(build=Mock(return_value={})),
        )

    return build


@pytest.mark.asyncio
async def test_creation_seeds_seedling_and_clone_stage_history(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """Both supported origins are valid lifecycle records immediately."""
    manager = manager_factory()
    clone_space = Growspace(id="clone", name="Clone", rows=5, plants_per_row=5)
    repository.add_growspace(clone_space)

    seed = await manager.add_plant(growspace_id="main", strain="Seed")
    clone = await manager.add_plant(
        growspace_id="clone",
        strain="Clone",
        plant_type=PlantStage.CLONE,
        stage=PlantStage.CLONE,
        clone_start="2026-08-20T10:00:00+00:00",
    )

    assert seed.stage == PlantStage.SEEDLING
    assert seed.stage_history == [
        {
            "stage": "seedling",
            "start": seed.seedling_start,
            "end": None,
        }
    ]
    assert clone.stage == PlantStage.CLONE
    assert clone.stage_history == [
        {
            "stage": "clone",
            "start": "2026-08-20T10:00:00+00:00",
            "end": None,
        }
    ]


@pytest.mark.asyncio
async def test_all_mutation_paths_append_stage_history(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """Ordinary, harvest, promotion, and mother placement share one domain seam."""
    manager = manager_factory()
    repository.add_plant(_plant("ordinary", PlantStage.VEG, "2026-08-01"))
    repository.add_plant(_plant("harvest", PlantStage.FLOWER, "2026-08-01"))
    repository.add_plant(_plant("promotion", PlantStage.CLONE, "2026-08-01", "clone"))
    repository.add_growspace(Growspace(id="clone", name="Clone"))
    repository.add_growspace(Growspace(id="veg-room", name="Veg"))
    repository.add_plant(_plant("mother", PlantStage.VEG, "2026-08-01"))

    await manager.transition_plant_stage(
        "ordinary", PlantStage.FLOWER, date(2026, 8, 10)
    )
    await manager.move_to_dry_growspace(
        "harvest", repository.require_plant("harvest"), "2026-08-10"
    )
    await manager.promote_clone("promotion", "veg-room", date(2026, 8, 10))
    await manager.transition_plant_stage("mother", PlantStage.MOTHER, date(2026, 8, 10))

    expected = {
        "ordinary": ("flower", "main"),
        "harvest": ("dry", "dry"),
        "promotion": ("veg", "veg-room"),
        "mother": ("mother", "mother"),
    }
    for plant_id, (stage, growspace_id) in expected.items():
        plant = repository.require_plant(plant_id)
        assert [item["stage"] for item in plant.stage_history] == [
            {
                "ordinary": "veg",
                "harvest": "flower",
                "promotion": "clone",
                "mother": "veg",
            }[plant_id],
            stage,
        ]
        assert plant.stage == stage
        assert plant.growspace_id == growspace_id


@pytest.mark.asyncio
async def test_harvest_analytics_record_lifetime_days_after_reveg(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """Harvest analytics sum every veg and flower interval after a Reveg."""
    manager = manager_factory()
    plant = Plant(
        plant_id="reveg-harvest",
        growspace_id="main",
        genetics=PlantGenetics(strain_name="Test", phenotype_name="Keeper"),
        stage=PlantStage.FLOWER,
        # The legacy calculation sees only these latest starts: 20d veg, 10d flower.
        veg_start="2025-07-21",
        flower_start="2025-08-10",
        stage_history=[
            {"stage": "veg", "start": "2025-07-01", "end": "2025-07-11"},
            {"stage": "flower", "start": "2025-07-11", "end": "2025-07-21"},
            {"stage": "veg", "start": "2025-07-21", "end": "2025-08-10"},
            {"stage": "flower", "start": "2025-08-10", "end": None},
        ],
    )
    repository.add_plant(plant)

    await manager.transition_plant_stage(
        plant.plant_id, PlantStage.DRY, date(2025, 8, 20)
    )

    recorded = manager.strain_library.record_harvest.await_args.args
    assert recorded[2:4] == (30, 20)


@pytest.mark.asyncio
async def test_reveg_clears_stale_later_stage_fields(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """A closed flower interval remains in history but not in legacy stage fields."""
    manager = manager_factory()
    plant = Plant(
        plant_id="reveg",
        growspace_id="main",
        stage=PlantStage.FLOWER,
        veg_start="2026-07-01",
        flower_start="2026-08-01",
        stage_history=[
            {"stage": "veg", "start": "2026-07-01", "end": "2026-08-01"},
            {"stage": "flower", "start": "2026-08-01", "end": None},
        ],
    )
    repository.add_plant(plant)

    await manager.transition_plant_stage("reveg", PlantStage.VEG, "2026-08-10")

    assert plant.stage == PlantStage.VEG
    assert plant.veg_start == "2026-08-10T00:00:00+00:00"
    assert plant.flower_start is None
    assert [item["stage"] for item in plant.stage_history] == [
        "veg",
        "flower",
        "veg",
    ]


@pytest.mark.asyncio
async def test_failed_atomic_save_restores_plant_and_special_placement(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """A partway persistence failure publishes no in-memory transition."""
    failing_save = AsyncMock(side_effect=RuntimeError("disk failed"))
    manager = manager_factory(failing_save)
    plant = _plant("rollback", PlantStage.FLOWER, "2026-08-01")
    repository.add_plant(plant)
    original_revision = repository.require_growspace("main").layout_revision

    with pytest.raises(RuntimeError, match="disk failed"):
        await manager.transition_plant_stage(
            "rollback", PlantStage.DRY, date(2026, 8, 10)
        )

    assert repository.require_plant("rollback") is plant
    assert plant.stage == PlantStage.FLOWER
    assert plant.growspace_id == "main"
    assert plant.dry_start is None
    assert plant.stage_history == [
        {"stage": "flower", "start": "2026-08-01", "end": None}
    ]
    assert repository.require_growspace("main").layout_revision == original_revision
    assert not repository.has_growspace("dry")


@pytest.mark.asyncio
async def test_concurrent_transitions_are_serialized(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """A second lifecycle mutation cannot observe the first half-written."""
    first_save_started = asyncio.Event()
    release_first_save = asyncio.Event()
    save_count = 0

    async def blocking_save() -> None:
        nonlocal save_count
        save_count += 1
        if save_count == 1:
            first_save_started.set()
            await release_first_save.wait()

    manager = manager_factory(AsyncMock(side_effect=blocking_save))
    plant = _plant("serial", PlantStage.SEEDLING, "2026-08-01")
    repository.add_plant(plant)

    to_veg = asyncio.create_task(
        manager._commit_lifecycle_transition("serial", PlantStage.VEG, "2026-08-10")
    )
    await first_save_started.wait()
    to_flower = asyncio.create_task(
        manager._commit_lifecycle_transition("serial", PlantStage.FLOWER, "2026-08-11")
    )
    await asyncio.sleep(0)

    assert not to_flower.done()
    assert plant.stage == PlantStage.VEG

    release_first_save.set()
    await asyncio.gather(to_veg, to_flower)

    assert [item["stage"] for item in plant.stage_history] == [
        "seedling",
        "veg",
        "flower",
    ]


@pytest.mark.asyncio
async def test_invalid_graph_transition_is_rejected_without_mutation(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """The persistence shell honors domain rejection decisions."""
    manager = manager_factory()
    plant = _plant("invalid", PlantStage.SEEDLING, "2026-08-01")
    repository.add_plant(plant)

    with pytest.raises(ValidationChangeError, match="not allowed"):
        await manager._commit_lifecycle_transition(
            "invalid", PlantStage.FLOWER, "2026-08-10"
        )

    assert plant.stage == PlantStage.SEEDLING
    assert len(plant.stage_history) == 1


@pytest.mark.asyncio
async def test_update_plant_forward_stage_edit_uses_lifecycle_transition(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """A graph-valid stage edit appends history instead of overwriting the shadow."""
    manager = manager_factory()
    plant = _plant("forward-edit", PlantStage.VEG, "2026-08-01")
    repository.add_plant(plant)

    await manager.update_plant(
        "forward-edit",
        stage=PlantStage.FLOWER,
        flower_start=date(2026, 8, 10),
        sex="female",
    )

    assert plant.stage == PlantStage.FLOWER
    assert plant.flower_start == "2026-08-10T00:00:00+00:00"
    assert plant.sex == "female"
    assert plant.stage_history == [
        {
            "stage": "veg",
            "start": "2026-08-01",
            "end": "2026-08-10T00:00:00+00:00",
        },
        {
            "stage": "flower",
            "start": "2026-08-10T00:00:00+00:00",
            "end": None,
        },
    ]


@pytest.mark.asyncio
async def test_update_plant_backdated_current_start_emits_repair_event(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """Editing the open interval's start is an explicit, timeline-visible repair."""
    manager = manager_factory()
    plant = _plant("backdated-edit", PlantStage.VEG, "2026-08-10")
    repository.add_plant(plant)

    await manager.update_plant("backdated-edit", veg_start=date(2026, 8, 5))

    assert plant.stage == PlantStage.VEG
    assert plant.veg_start == "2026-08-05T00:00:00+00:00"
    assert plant.stage_history == [
        {
            "stage": "veg",
            "start": "2026-08-05T00:00:00+00:00",
            "end": None,
        }
    ]
    repair_events = [
        call.args[1]
        for call in manager.hass.bus.async_fire.call_args_list
        if call.args[0] == EVENT_GROWSPACE_LOG_ENTRY
    ]
    assert repair_events == [
        {
            "plant_id": "backdated-edit",
            "growspace_id": "main",
            "sensor_type": "lifecycle_repair",
            "category": "milestone",
            "timestamp": repair_events[0]["timestamp"],
            "notes": "Lifecycle corrected through update_plant",
            "reasons": ["Corrected Veg start to 2026-08-05"],
            "previous_stage": "veg",
            "corrected_stage": "veg",
            "corrected_stage_started_on": "2026-08-05",
            "corrected_on": repair_events[0]["corrected_on"],
            "discarded_interval_count": 1,
            "warning_codes": [],
        }
    ]


@pytest.mark.asyncio
async def test_update_plant_ambiguous_correction_discards_later_intervals(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """A non-transition correction retains only a graph-compatible trusted prefix."""
    manager = manager_factory()
    plant = Plant(
        plant_id="ambiguous-edit",
        growspace_id="main",
        genetics=PlantGenetics(strain_name="Test"),
        stage=PlantStage.FLOWER,
        seedling_start="2026-08-01",
        veg_start="2026-08-05",
        flower_start="2026-08-10",
        stage_history=[
            {"stage": "seedling", "start": "2026-08-01", "end": "2026-08-05"},
            {"stage": "veg", "start": "2026-08-05", "end": "2026-08-10"},
            {"stage": "flower", "start": "2026-08-10", "end": None},
        ],
    )
    repository.add_plant(plant)

    await manager.update_plant(
        "ambiguous-edit",
        stage=PlantStage.MOTHER,
        mother_start=date(2026, 8, 7),
    )

    assert plant.stage == PlantStage.MOTHER
    assert plant.mother_start == "2026-08-07T00:00:00+00:00"
    assert plant.seedling_start is None
    assert plant.veg_start is None
    assert plant.flower_start is None
    assert plant.stage_history == [
        {
            "stage": "mother",
            "start": "2026-08-07T00:00:00+00:00",
            "end": None,
        }
    ]
    repair_event = next(
        call.args[1]
        for call in manager.hass.bus.async_fire.call_args_list
        if call.args[0] == EVENT_GROWSPACE_LOG_ENTRY
    )
    assert repair_event["discarded_interval_count"] == 3


@pytest.fixture
def rescheduled_plant(repository: GrowspaceRepository) -> Plant:
    """A grown plant whose three boundaries carry full stored timestamps."""
    plant = Plant(
        plant_id="multi-date-edit",
        growspace_id="main",
        genetics=PlantGenetics(strain_name="Test"),
        stage=PlantStage.FLOWER,
        seedling_start="2026-08-01T09:15:00+00:00",
        veg_start="2026-08-05T11:30:00+00:00",
        flower_start="2026-08-10T18:45:00+00:00",
        stage_history=[
            {
                "stage": "seedling",
                "start": "2026-08-01T09:15:00+00:00",
                "end": "2026-08-05T11:30:00+00:00",
            },
            {
                "stage": "veg",
                "start": "2026-08-05T11:30:00+00:00",
                "end": "2026-08-10T18:45:00+00:00",
            },
            {
                "stage": "flower",
                "start": "2026-08-10T18:45:00+00:00",
                "end": None,
            },
        ],
    )
    repository.add_plant(plant)
    return plant


@pytest.mark.asyncio
async def test_update_plant_multi_date_edit_rebuilds_stage_history(
    manager_factory, rescheduled_plant: Plant
) -> None:
    """Two corrected dates save at once and leave every value agreeing."""
    manager = manager_factory()

    await manager.update_plant(
        "multi-date-edit",
        veg_start=date(2026, 8, 3),
        flower_start=date(2026, 8, 12),
        sex="female",
    )

    assert rescheduled_plant.stage == PlantStage.FLOWER
    assert rescheduled_plant.sex == "female"
    assert rescheduled_plant.veg_start == "2026-08-03T00:00:00+00:00"
    assert rescheduled_plant.flower_start == "2026-08-12T00:00:00+00:00"
    # The untouched boundary keeps the precision it was stored with (ADR-0013).
    assert rescheduled_plant.seedling_start == "2026-08-01T09:15:00+00:00"
    assert rescheduled_plant.stage_history == [
        {
            "stage": "seedling",
            "start": "2026-08-01T09:15:00+00:00",
            "end": "2026-08-03T00:00:00+00:00",
        },
        {
            "stage": "veg",
            "start": "2026-08-03T00:00:00+00:00",
            "end": "2026-08-12T00:00:00+00:00",
        },
        {
            "stage": "flower",
            "start": "2026-08-12T00:00:00+00:00",
            "end": None,
        },
    ]


@pytest.mark.asyncio
async def test_update_plant_multi_date_edit_is_one_timeline_repair(
    manager_factory, rescheduled_plant: Plant
) -> None:
    """One save is one lifecycle repair, naming every boundary it moved."""
    manager = manager_factory()

    await manager.update_plant(
        "multi-date-edit",
        veg_start=date(2026, 8, 3),
        flower_start=date(2026, 8, 12),
    )

    repair_events = [
        call.args[1]
        for call in manager.hass.bus.async_fire.call_args_list
        if call.args[0] == EVENT_GROWSPACE_LOG_ENTRY
    ]
    assert len(repair_events) == 1
    assert repair_events[0]["sensor_type"] == "lifecycle_repair"
    assert repair_events[0]["reasons"] == [
        "Corrected Veg start to 2026-08-03",
        "Corrected Flower start to 2026-08-12",
    ]
    assert repair_events[0]["previous_stage"] == "flower"
    assert repair_events[0]["corrected_stage"] == "flower"
    assert repair_events[0]["corrected_stage_started_on"] == "2026-08-12"
    assert repair_events[0]["discarded_interval_count"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "message"),
    [
        (
            {"veg_start": date(2026, 8, 14), "flower_start": date(2026, 8, 12)},
            "veg start 2026-08-14 is after flower start 2026-08-12",
        ),
        (
            {"veg_start": date(2026, 8, 3), "flower_start": date(2099, 1, 1)},
            "flower start 2099-01-01 is in the future",
        ),
        (
            {"veg_start": date(2026, 8, 3), "cure_start": date(2026, 8, 15)},
            "Stage order flower->cure is not allowed",
        ),
    ],
)
async def test_update_plant_rejects_contradictory_multi_date_edit(
    manager_factory,
    rescheduled_plant: Plant,
    updates: dict[str, object],
    message: str,
) -> None:
    """A contradictory set is named and leaves the Plant completely untouched."""
    manager = manager_factory()
    before = deepcopy(rescheduled_plant)

    with pytest.raises(ValidationChangeError, match=message):
        await manager.update_plant("multi-date-edit", sex="female", **updates)

    assert rescheduled_plant.stage == before.stage
    assert rescheduled_plant.sex is None
    assert rescheduled_plant.stage_history == before.stage_history
    assert {
        field: getattr(rescheduled_plant, field)
        for field in ("seedling_start", "veg_start", "flower_start", "cure_start")
    } == {
        "seedling_start": "2026-08-01T09:15:00+00:00",
        "veg_start": "2026-08-05T11:30:00+00:00",
        "flower_start": "2026-08-10T18:45:00+00:00",
        "cure_start": None,
    }
    manager.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_update_plant_multi_date_edit_can_add_a_stage(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """Filling in an unrecorded stage alongside a correction flips the plant."""
    manager = manager_factory()
    plant = _plant("added-stage", PlantStage.VEG, "2026-08-01")
    repository.add_plant(plant)

    await manager.update_plant(
        "added-stage",
        veg_start=date(2026, 7, 30),
        flower_start=date(2026, 8, 20),
    )

    assert plant.stage == PlantStage.FLOWER
    assert plant.veg_start == "2026-07-30T00:00:00+00:00"
    assert plant.flower_start == "2026-08-20T00:00:00+00:00"
    assert plant.stage_history == [
        {
            "stage": "veg",
            "start": "2026-07-30T00:00:00+00:00",
            "end": "2026-08-20T00:00:00+00:00",
        },
        {
            "stage": "flower",
            "start": "2026-08-20T00:00:00+00:00",
            "end": None,
        },
    ]


@pytest.mark.asyncio
async def test_multi_date_edit_keeps_legacy_timestamp_precision(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """A Plant whose history is reconstructed still keeps its stored moments."""
    manager = manager_factory()
    plant = Plant(
        plant_id="legacy-edit",
        growspace_id="main",
        genetics=PlantGenetics(strain_name="Test"),
        stage=PlantStage.VEG,
        seedling_start="2026-08-01T09:15:00+00:00",
        veg_start="2026-08-05T11:30:00+00:00",
        stage_history=[],
    )
    repository.add_plant(plant)

    await manager.update_plant(
        "legacy-edit",
        veg_start=date(2026, 8, 3),
        flower_start=date(2026, 8, 12),
    )

    assert plant.seedling_start == "2026-08-01T09:15:00+00:00"
    assert plant.stage_history[0] == {
        "stage": "seedling",
        "start": "2026-08-01T09:15:00+00:00",
        "end": "2026-08-03T00:00:00+00:00",
    }
    assert [item["stage"] for item in plant.stage_history] == [
        "seedling",
        "veg",
        "flower",
    ]


@pytest.mark.asyncio
async def test_failed_multi_date_edit_restores_every_lifecycle_field(
    manager_factory, rescheduled_plant: Plant
) -> None:
    """A persistence failure rolls the whole reschedule back as one write."""
    manager = manager_factory(AsyncMock(side_effect=RuntimeError("disk failed")))
    before = deepcopy(rescheduled_plant)

    with pytest.raises(RuntimeError, match="disk failed"):
        await manager.update_plant(
            "multi-date-edit",
            veg_start=date(2026, 8, 3),
            flower_start=date(2026, 8, 12),
            sex="female",
        )

    assert rescheduled_plant.sex is None
    assert rescheduled_plant.veg_start == before.veg_start
    assert rescheduled_plant.flower_start == before.flower_start
    assert rescheduled_plant.stage_history == before.stage_history


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"stage": "unknown-stage"}, "Invalid lifecycle stage"),
        (
            {"stage": PlantStage.FLOWER, "flower_start": date(2026, 7, 31)},
            "predate the open interval",
        ),
        ({"veg_start": date(2099, 1, 1)}, "after corrected_on"),
    ],
)
async def test_update_plant_rejects_invalid_lifecycle_edit_without_mutation(
    manager_factory,
    repository: GrowspaceRepository,
    updates: dict[str, object],
    message: str,
) -> None:
    """Unknown, too-early, and future lifecycle edits leave the Plant untouched."""
    manager = manager_factory()
    plant = _plant("rejected-edit", PlantStage.VEG, "2026-08-01")
    repository.add_plant(plant)

    with pytest.raises(ValidationChangeError, match=message):
        await manager.update_plant("rejected-edit", **updates)

    assert plant.stage == PlantStage.VEG
    assert plant.veg_start == "2026-08-01"
    assert plant.flower_start is None
    assert plant.stage_history == [{"stage": "veg", "start": "2026-08-01", "end": None}]


@pytest.mark.asyncio
async def test_update_plant_plain_edit_skips_lifecycle_parse(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """Notes and position edits retain the ordinary update cost."""
    manager = manager_factory()
    plant = _plant("plain-edit", PlantStage.VEG, "2026-08-01")
    repository.add_plant(plant)
    manager._plant_lifecycle = Mock(wraps=manager._plant_lifecycle)

    await manager.update_plant("plain-edit", sex="female", row=2)

    assert plant.sex == "female"
    assert plant.row == 2
    manager._plant_lifecycle.assert_not_called()


@pytest.mark.asyncio
async def test_failed_lifecycle_update_restores_mixed_fields_and_placement(
    manager_factory, repository: GrowspaceRepository
) -> None:
    """Lifecycle, ordinary fields, layout, and placement roll back as one write."""
    repository.add_growspace(Growspace(id="target", name="Target"))
    manager = manager_factory(AsyncMock(side_effect=RuntimeError("disk failed")))
    plant = _plant("mixed-rollback", PlantStage.VEG, "2026-08-01")
    repository.add_plant(plant)
    revisions = {
        growspace_id: repository.require_growspace(growspace_id).layout_revision
        for growspace_id in ("main", "target")
    }

    with pytest.raises(RuntimeError, match="disk failed"):
        await manager.update_plant(
            "mixed-rollback",
            stage=PlantStage.FLOWER,
            flower_start=date(2026, 8, 10),
            growspace_id="target",
            sex="female",
        )

    assert plant.stage == PlantStage.VEG
    assert plant.growspace_id == "main"
    assert plant.sex is None
    assert plant.flower_start is None
    assert plant.stage_history == [{"stage": "veg", "start": "2026-08-01", "end": None}]
    assert {
        growspace_id: repository.require_growspace(growspace_id).layout_revision
        for growspace_id in ("main", "target")
    } == revisions
