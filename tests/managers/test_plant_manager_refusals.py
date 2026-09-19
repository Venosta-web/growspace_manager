"""What the Plant Manager refuses, and what it puts back when a save fails.

Two properties, and the file is organized as them.

**A refused mutation names what is missing.** Every guard here is a state a
correct caller can reach — a growspace that has been deleted, a plant ID from
a stale client, a lifecycle edit that names two stages at once — so each says
which thing was not found or which rule was broken rather than failing
somewhere further in with a `KeyError` or an `AttributeError`.

**A failed persistence write leaves the repository exactly as it was.** The
manager mutates in-memory models first and saves afterwards, so every mutation
carries a compensating rollback: the plant that was added is removed, the one
it replaced is put back, the growspace's Layout Revision returns to what it
was, and the cache is invalidated. That rollback is only ever executed when the
store fails, which is why it is the half of this module a suite has to make
fail on purpose to see at all.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from custom_components.growspace_manager.const import PlantStage
from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.domain.plant_lifecycle import LifecycleStage
from custom_components.growspace_manager.exceptions import (
    GrowspaceNotFoundError,
    PlantNotFoundError,
    ValidationChangeError,
)
from custom_components.growspace_manager.managers.plant import _as_lifecycle_stage
from custom_components.growspace_manager.models import Growspace, Plant, PlantGenetics


def _seedling(
    plant_id: str = "resident",
    *,
    growspace_id: str = "main",
    started_on: str = "2026-08-01T09:00:00+00:00",
    row: int = 1,
    col: int = 1,
) -> Plant:
    """One ordinary plant, already standing somewhere."""
    return Plant(
        plant_id=plant_id,
        growspace_id=growspace_id,
        genetics=PlantGenetics(strain_name="Test", phenotype_name="Keeper"),
        stage=PlantStage.SEEDLING,
        row=row,
        col=col,
        created_at=started_on,
        seedling_start=started_on,
        stage_history=[{"stage": "seedling", "start": started_on, "end": None}],
    )


def _failing_save() -> AsyncMock:
    """A persistence callback that refuses, the way a full disk does."""
    return AsyncMock(side_effect=OSError("disk full"))


# ---------------------------------------------------------------------------
# A failed save puts the repository back
# ---------------------------------------------------------------------------


async def test_a_failed_save_removes_the_plant_it_had_just_added(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """Adding a plant is not half-done because the store went away.

    The plant is in the repository and the Layout Revision has advanced by the
    time the save is attempted, so both have to be undone — otherwise a client
    reading the manager's own state would see a plant that was never persisted
    and a revision number the next restart does not have.
    """
    manager = manager_factory(_failing_save())
    before = repository.require_growspace("main").layout_revision

    with pytest.raises(OSError, match="disk full"):
        await manager.add_plant(growspace_id="main", strain="Ghost")

    assert repository.get_growspace_plants("main") == []
    assert repository.require_growspace("main").layout_revision == before
    manager._ctx.invalidate_cache.assert_called_with("main")  # type: ignore[attr-defined]


async def test_a_failed_save_restores_the_plant_it_replaced(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """Re-adding under an existing ID must not cost the plant already there.

    Undoing by deletion would be right for a new ID and catastrophic for this
    one: the rollback restores what it displaced rather than removing whatever
    is in the slot.
    """
    resident = _seedling("shared-id")
    repository.add_plant(resident)
    manager = manager_factory(_failing_save())

    with pytest.raises(OSError, match="disk full"):
        await manager.add_plant(
            growspace_id="main", strain="Usurper", plant_id="shared-id"
        )

    restored = repository.require_plant("shared-id")
    assert restored.genetics.strain_name == "Test"
    assert restored is resident


# ---------------------------------------------------------------------------
# Refusals that name what is missing
# ---------------------------------------------------------------------------


async def test_adding_to_a_growspace_that_is_not_there(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """A plant needs somewhere to stand before anything else is decided."""
    manager = manager_factory()

    with pytest.raises(GrowspaceNotFoundError, match="nowhere"):
        await manager.add_plant(growspace_id="nowhere", strain="Test")

    assert repository.get_all_plants() == []


async def test_updating_a_plant_that_does_not_exist(manager_factory: Any) -> None:
    """A stale client's plant ID is absent rather than created."""
    manager = manager_factory()

    with pytest.raises(PlantNotFoundError, match="ghost"):
        await manager.update_plant("ghost", notes="anything")


async def test_a_lifecycle_edit_of_a_plant_that_does_not_exist(
    manager_factory: Any,
) -> None:
    """The lifecycle route answers the same way the ordinary one does."""
    manager = manager_factory()

    with pytest.raises(PlantNotFoundError, match="ghost"):
        await manager.update_plant(
            "ghost", stage="veg", veg_start="2026-08-10T09:00:00+00:00"
        )


async def test_moving_a_plant_to_a_growspace_that_is_not_there(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """The move is refused before the plant is touched."""
    repository.add_plant(_seedling())
    manager = manager_factory()

    with pytest.raises(GrowspaceNotFoundError, match="nowhere"):
        await manager.update_plant("resident", growspace_id="nowhere")

    assert repository.require_plant("resident").growspace_id == "main"


async def test_a_lifecycle_edit_that_also_moves_somewhere_that_is_not_there(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """Two changes in one call, and the missing growspace still stops it."""
    repository.add_plant(_seedling())
    manager = manager_factory()

    with pytest.raises(GrowspaceNotFoundError, match="nowhere"):
        await manager.update_plant(
            "resident",
            stage="veg",
            veg_start="2026-08-10T09:00:00+00:00",
            growspace_id="nowhere",
        )

    assert repository.require_plant("resident").stage == PlantStage.SEEDLING


async def test_a_plant_standing_in_a_growspace_that_has_gone(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """Advancing a Layout Revision says so rather than inventing a growspace.

    An orphan is a real state — a growspace removed while a plant still
    referenced it — and the honest answer is that the thing whose revision
    would move is not there.
    """
    repository.add_plant(_seedling(growspace_id="demolished"))
    manager = manager_factory()

    with pytest.raises(GrowspaceNotFoundError, match="demolished"):
        await manager.update_plant("resident", row=3)


# ---------------------------------------------------------------------------
# Lifecycle edits name exactly one stage
# ---------------------------------------------------------------------------


async def test_a_lifecycle_edit_may_only_set_the_selected_stage(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """Naming one stage and dating another is two edits wearing one payload."""
    repository.add_plant(_seedling())
    manager = manager_factory()

    with pytest.raises(ValidationChangeError, match="selected stage's start date"):
        await manager.update_plant(
            "resident", stage="flower", veg_start="2026-08-10T09:00:00+00:00"
        )

    assert repository.require_plant("resident").stage == PlantStage.SEEDLING


async def test_the_current_lifecycle_start_cannot_be_cleared(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """A stage the plant is in has to have begun at some point."""
    repository.add_plant(_seedling())
    manager = manager_factory()

    with pytest.raises(ValidationChangeError, match="cannot be cleared"):
        await manager.update_plant("resident", stage="seedling", seedling_start=None)


def test_presentation_substages_collapse_to_the_canonical_vocabulary() -> None:
    """The card's finer stages are a presentation, not a sixth lifecycle stage.

    `veg_early` and `flower_late` are things an interface says about a plant;
    the lifecycle has `veg` and `flower`. Mapping them here is what keeps the
    substages out of stage history, arithmetic and every refusal message.
    """
    assert _as_lifecycle_stage(PlantStage.VEG_EARLY) is LifecycleStage.VEG
    assert _as_lifecycle_stage(PlantStage.VEG_LATE) is LifecycleStage.VEG
    assert _as_lifecycle_stage("flower_early") is LifecycleStage.FLOWER
    assert _as_lifecycle_stage("flower_mid") is LifecycleStage.FLOWER
    assert _as_lifecycle_stage("flower_late") is LifecycleStage.FLOWER
    with pytest.raises(ValidationChangeError, match="Invalid lifecycle stage"):
        _as_lifecycle_stage("compost")


# ---------------------------------------------------------------------------
# Genetics are fields of their own, on both update routes
# ---------------------------------------------------------------------------


async def test_a_lifecycle_edit_can_rename_the_strain_and_phenotype(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """`strain` and `phenotype` are the genetics, not attributes of the plant.

    They arrive in the same payload as everything else and have to be routed
    into `plant.genetics`; set on the plant they would land nowhere, because
    `hasattr` is false for both and the loop would quietly skip them.
    """
    repository.add_plant(_seedling())
    manager = manager_factory()

    await manager.update_plant(
        "resident",
        stage="veg",
        veg_start="2026-08-10T09:00:00+00:00",
        strain="Renamed",
        phenotype="Cut #4",
    )

    plant = repository.require_plant("resident")
    assert plant.genetics.strain_name == "Renamed"
    assert plant.genetics.phenotype_name == "Cut #4"
    assert plant.stage == PlantStage.VEG


async def test_a_stage_start_is_stored_as_a_timestamp_and_none_clears_one(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """A date-only value is promoted; `None` is passed through as itself.

    ADR-0013: a stage start is stored as a datetime, never a date. Naming any
    `*_start` routes the update through the lifecycle commit, so this is the
    one path that promotion has to happen on — and the one a client sending
    `2026-09-01` from a date picker actually takes.
    """
    repository.add_plant(_seedling())
    manager = manager_factory()

    await manager.update_plant("resident", stage="cure", cure_start="2026-09-01")

    plant = repository.require_plant("resident")
    assert plant.cure_start is not None
    assert plant.cure_start.startswith("2026-09-01T")
    assert plant.stage == PlantStage.CURE


# ---------------------------------------------------------------------------
# Committing a whole Plant Layout
# ---------------------------------------------------------------------------


async def test_a_layout_for_a_growspace_that_is_not_there(
    manager_factory: Any,
) -> None:
    """Nothing about a layout can be judged without the grid it is for."""
    manager = manager_factory()

    with pytest.raises(GrowspaceNotFoundError, match="nowhere"):
        await manager.set_plant_layout("nowhere", 0, [])


@pytest.mark.parametrize(("rows", "plants_per_row"), [(0, 4), (4, 0), (-1, 4), (4, -1)])
async def test_a_grid_with_no_cells_in_it(
    manager_factory: Any,
    repository: GrowspaceRepository,
    rows: int,
    plants_per_row: int,
) -> None:
    """A dimension below one describes a growspace nothing can stand in."""
    manager = manager_factory()
    revision = repository.require_growspace("main").layout_revision

    with pytest.raises(ValidationChangeError, match="must be positive"):
        await manager.set_plant_layout(
            "main", revision, [], rows=rows, plants_per_row=plants_per_row
        )

    assert repository.require_growspace("main").rows == 5


async def test_a_complete_layout_commits_dimensions_and_placements(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """The shape the refusals above are guarding, once it is all valid."""
    repository.add_plant(_seedling("first", row=1, col=1))
    repository.add_plant(_seedling("second", row=1, col=2))
    manager = manager_factory()
    revision = repository.require_growspace("main").layout_revision

    await manager.set_plant_layout(
        "main",
        revision,
        [
            {"plant_id": "first", "row": 2, "col": 1},
            {"plant_id": "second", "row": 1, "col": 1},
        ],
        rows=2,
        plants_per_row=2,
    )

    growspace = repository.require_growspace("main")
    assert (growspace.rows, growspace.plants_per_row) == (2, 2)
    assert growspace.layout_revision == revision + 1
    assert (
        repository.require_plant("first").row,
        repository.require_plant("first").col,
    ) == (2, 1)
    assert (
        repository.require_plant("second").row,
        repository.require_plant("second").col,
    ) == (1, 1)


# ---------------------------------------------------------------------------
# The service-facing aliases
# ---------------------------------------------------------------------------


async def test_the_remove_plant_alias_removes_the_plant(
    manager_factory: Any, repository: GrowspaceRepository
) -> None:
    """`handle_remove_plant` is the service's name for one manager method.

    It exists so the service layer can dispatch by handler name, and it is
    exercised here because an alias that stopped forwarding would keep passing
    every test of the method it forwards to.
    """
    repository.add_growspace(Growspace(id="spare", name="Spare"))
    repository.add_plant(_seedling("doomed"))
    manager = manager_factory()

    await manager.handle_remove_plant("doomed")

    assert repository.get_plant("doomed") is None
