"""Atomic persistence-shell tests for Plant Lifecycle mutations."""

from __future__ import annotations

import asyncio
from datetime import date
from unittest.mock import AsyncMock, Mock

import pytest

from custom_components.growspace_manager.const import PlantStage
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
