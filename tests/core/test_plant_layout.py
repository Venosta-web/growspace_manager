"""Tests for the revision-guarded Plant Layout contract."""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock

from freezegun import freeze_time
import pytest

from custom_components.growspace_manager.data_access.growspace_repository import (
    GrowspaceRepository,
)
from custom_components.growspace_manager.data_access.notification_state import (
    NotificationState,
)
from custom_components.growspace_manager.events import EVENT_PLANT_LAYOUT_CHANGED
from custom_components.growspace_manager.exceptions import (
    LayoutConflictError,
    PlantNotFoundError,
    ValidationChangeError,
)
from custom_components.growspace_manager.growspace_validator import GrowspaceValidator
from custom_components.growspace_manager.managers.growspace import GrowspaceManager
from custom_components.growspace_manager.managers.plant import PlantManager
from custom_components.growspace_manager.models import Growspace, Plant
from custom_components.growspace_manager.presentation.growspace_view_model import (
    GrowspaceViewModelBuilder,
)
from custom_components.growspace_manager.services.context import ServiceContext
from homeassistant.core import HomeAssistant
from tests.common import async_capture_events


@pytest.fixture
def repository() -> GrowspaceRepository:
    """Return a repository with one populated growspace."""
    repository = GrowspaceRepository()
    repository.add_growspace(
        Growspace(id="tent", name="Tent", rows=2, plants_per_row=2)
    )
    repository.add_plant(Plant(plant_id="p1", growspace_id="tent", row=1, col=1))
    repository.add_plant(Plant(plant_id="p2", growspace_id="tent", row=1, col=2))
    return repository


@pytest.fixture
def save_callback() -> AsyncMock:
    """Return the persistence seam used by managers."""
    return AsyncMock()


@pytest.fixture
def service_context(save_callback: AsyncMock) -> ServiceContext:
    """Return the shared mutation context."""
    return ServiceContext(
        save_callback=save_callback,
        lock=asyncio.Lock(),
        add_event=MagicMock(),
        invalidate_cache=MagicMock(),
    )


@pytest.fixture
def manager(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    service_context: ServiceContext,
) -> PlantManager:
    """Return a PlantManager wired to the real repository and validator."""
    return PlantManager(
        ctx=service_context,
        hass=hass,
        repository=repository,
        notification_state=NotificationState(),
        validator=GrowspaceValidator(repository),
        growspace_manager=MagicMock(),
        strain_library=MagicMock(),
        plant_view_builder=MagicMock(),
    )


async def test_set_plant_layout_commits_once_and_emits_one_event(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """A swap-equivalent mapping is one revision, save, and event."""
    events = async_capture_events(hass, EVENT_PLANT_LAYOUT_CHANGED)

    result = await manager.set_plant_layout(
        "tent",
        0,
        [
            {"plant_id": "p1", "row": 1, "col": 2},
            {"plant_id": "p2", "row": 1, "col": 1},
        ],
    )

    assert result == {
        "growspace_id": "tent",
        "layout_revision": 1,
        "rows": 2,
        "plants_per_row": 2,
        "placements": [
            {"plant_id": "p1", "row": 1, "col": 2},
            {"plant_id": "p2", "row": 1, "col": 1},
        ],
    }
    assert repository.require_growspace("tent").layout_revision == 1
    assert (repository.require_plant("p1").row, repository.require_plant("p1").col) == (
        1,
        2,
    )
    save_callback.assert_awaited_once_with()
    assert [event.data for event in events] == [
        {"growspace_id": "tent", "layout_revision": 1}
    ]


@freeze_time("2026-01-12 12:00:00", tz_offset=0)
async def test_layout_and_ordinary_update_share_updated_at_representation(
    repository: GrowspaceRepository,
    manager: PlantManager,
) -> None:
    """Layout commits and ordinary mutations stamp the same date-only value."""
    await manager.set_plant_layout(
        "tent",
        0,
        [
            {"plant_id": "p1", "row": 2, "col": 1},
            {"plant_id": "p2", "row": 2, "col": 2},
        ],
    )
    layout_updated_at = repository.require_plant("p1").updated_at

    await manager.update_plant("p1", phenotype="Keeper")
    ordinary_updated_at = repository.require_plant("p1").updated_at

    assert layout_updated_at == ordinary_updated_at == "2026-01-12"


async def test_set_plant_layout_no_op_has_no_write_or_event(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """An authoritative no-op leaves its revision and event stream unchanged."""
    events = async_capture_events(hass, EVENT_PLANT_LAYOUT_CHANGED)

    result = await manager.set_plant_layout(
        "tent",
        0,
        [
            {"plant_id": "p2", "row": 1, "col": 2},
            {"plant_id": "p1", "row": 1, "col": 1},
        ],
    )

    assert result["layout_revision"] == 0
    assert repository.require_growspace("tent").layout_revision == 0
    save_callback.assert_not_awaited()
    assert events == []


async def test_set_plant_layout_rejects_stale_revision(
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """A stale draft raises the dedicated conflict without changing state."""
    repository.require_growspace("tent").layout_revision = 3

    with pytest.raises(LayoutConflictError, match="expected 2, current 3"):
        await manager.set_plant_layout(
            "tent",
            2,
            [
                {"plant_id": "p1", "row": 2, "col": 1},
                {"plant_id": "p2", "row": 2, "col": 2},
            ],
            rows=3,
        )

    assert (repository.require_plant("p1").row, repository.require_plant("p1").col) == (
        1,
        1,
    )
    assert repository.require_growspace("tent").rows == 2
    save_callback.assert_not_awaited()


async def test_resize_with_layout_commits_dimensions_and_positions_once(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """A valid shrinking layout publishes one indivisible revision."""
    repository.require_plant("p2").row = 2
    events = async_capture_events(hass, EVENT_PLANT_LAYOUT_CHANGED)

    result = await manager.set_plant_layout(
        "tent",
        0,
        [
            {"plant_id": "p1", "row": 1, "col": 1},
            {"plant_id": "p2", "row": 1, "col": 2},
        ],
        rows=1,
        plants_per_row=2,
    )

    assert result["layout_revision"] == 1
    assert result["rows"] == 1
    assert result["plants_per_row"] == 2
    growspace = repository.require_growspace("tent")
    assert (growspace.rows, growspace.plants_per_row) == (1, 2)
    assert repository.require_plant("p2").row == 1
    save_callback.assert_awaited_once_with()
    assert [event.data for event in events] == [
        {"growspace_id": "tent", "layout_revision": 1}
    ]


async def test_resize_with_layout_rejects_layout_outside_target_bounds(
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """Target dimensions validate the staged layout before any mutation."""
    with pytest.raises(ValidationChangeError, match="outside growspace"):
        await manager.set_plant_layout(
            "tent",
            0,
            [
                {"plant_id": "p1", "row": 1, "col": 1},
                {"plant_id": "p2", "row": 2, "col": 2},
            ],
            rows=1,
        )

    growspace = repository.require_growspace("tent")
    assert (growspace.rows, growspace.plants_per_row) == (2, 2)
    assert growspace.layout_revision == 0
    assert repository.require_plant("p2").row == 1
    save_callback.assert_not_awaited()


async def test_resize_with_layout_repairs_existing_out_of_bounds_plant(
    repository: GrowspaceRepository,
    manager: PlantManager,
) -> None:
    """The atomic path can recover a historically invalid stored layout."""
    repository.require_plant("p2").row = 3

    await manager.set_plant_layout(
        "tent",
        0,
        [
            {"plant_id": "p1", "row": 1, "col": 1},
            {"plant_id": "p2", "row": 1, "col": 2},
        ],
        rows=1,
    )

    growspace = repository.require_growspace("tent")
    assert (growspace.rows, growspace.plants_per_row) == (1, 2)
    assert repository.require_plant("p2").row == 1
    assert growspace.layout_revision == 1


@pytest.mark.parametrize(
    ("placements", "error"),
    [
        pytest.param(
            [{"plant_id": "p1", "row": 1, "col": 1}],
            PlantNotFoundError,
            id="incomplete",
        ),
        pytest.param(
            [
                {"plant_id": "p1", "row": 1, "col": 1},
                {"plant_id": "p1", "row": 2, "col": 1},
            ],
            ValidationChangeError,
            id="duplicate-plant",
        ),
        pytest.param(
            [
                {"plant_id": "p1", "row": 1, "col": 1},
                {"plant_id": "p2", "row": 1, "col": 1},
            ],
            ValidationChangeError,
            id="duplicate-cell",
        ),
        pytest.param(
            [
                {"plant_id": "p1", "row": 3, "col": 1},
                {"plant_id": "p2", "row": 1, "col": 2},
            ],
            ValidationChangeError,
            id="out-of-bounds",
        ),
        pytest.param(
            [
                {"plant_id": "p1", "row": 1, "col": 1},
                {"plant_id": "missing", "row": 1, "col": 2},
            ],
            PlantNotFoundError,
            id="unknown-plant",
        ),
    ],
)
async def test_set_plant_layout_rejects_invalid_complete_mapping(
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
    placements: list[dict[str, Any]],
    error: type[Exception],
) -> None:
    """Malformed complete mappings leave positions and revisions untouched."""
    before = {
        plant.plant_id: (plant.row, plant.col)
        for plant in repository.get_growspace_plants("tent")
    }

    with pytest.raises(error):
        await manager.set_plant_layout("tent", 0, placements)

    assert {
        plant.plant_id: (plant.row, plant.col)
        for plant in repository.get_growspace_plants("tent")
    } == before
    assert repository.require_growspace("tent").layout_revision == 0
    save_callback.assert_not_awaited()


async def test_set_plant_layout_rolls_back_persistence_failure(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """A failed save restores positions, timestamps, and revision without an event."""
    events = async_capture_events(hass, EVENT_PLANT_LAYOUT_CHANGED)
    previous_updated_at = repository.require_plant("p1").updated_at
    repository.require_plant("p2").row = 2
    save_callback.side_effect = RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        await manager.set_plant_layout(
            "tent",
            0,
            [
                {"plant_id": "p1", "row": 1, "col": 1},
                {"plant_id": "p2", "row": 1, "col": 2},
            ],
            rows=1,
        )

    assert (repository.require_plant("p1").row, repository.require_plant("p1").col) == (
        1,
        1,
    )
    assert repository.require_plant("p1").updated_at == previous_updated_at
    assert repository.require_plant("p2").row == 2
    growspace = repository.require_growspace("tent")
    assert (growspace.rows, growspace.plants_per_row) == (2, 2)
    assert growspace.layout_revision == 0
    assert events == []


async def test_set_plant_layout_persists_staged_state_before_publish(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    manager: PlantManager,
    service_context: ServiceContext,
    save_callback: AsyncMock,
) -> None:
    """Production persistence sees a snapshot while readers still see old state."""
    persisted: list[tuple[int, list[dict[str, Any]]]] = []
    events = async_capture_events(hass, EVENT_PLANT_LAYOUT_CHANGED)

    async def save_snapshot(
        growspace_id: str,
        revision: int,
        placements: list[dict[str, Any]],
        updated_at: str,
        rows: int,
        plants_per_row: int,
    ) -> None:
        assert growspace_id == "tent"
        assert updated_at
        assert (rows, plants_per_row) == (2, 2)
        assert repository.require_growspace("tent").layout_revision == 0
        assert repository.require_plant("p1").col == 1
        persisted.append((revision, placements))

    async def publish() -> None:
        assert repository.require_growspace("tent").layout_revision == 1
        assert repository.require_plant("p1").col == 2
        assert events == []

    service_context.save_layout_callback = save_snapshot
    service_context.publish_callback = publish

    await manager.set_plant_layout(
        "tent",
        0,
        [
            {"plant_id": "p1", "row": 1, "col": 2},
            {"plant_id": "p2", "row": 1, "col": 1},
        ],
    )

    assert persisted == [
        (
            1,
            [
                {"plant_id": "p1", "row": 1, "col": 2},
                {"plant_id": "p2", "row": 1, "col": 1},
            ],
        )
    ]
    assert [event.data for event in events] == [
        {"growspace_id": "tent", "layout_revision": 1}
    ]
    save_callback.assert_not_awaited()


async def test_staged_persistence_failure_never_publishes_candidate_state(
    repository: GrowspaceRepository,
    manager: PlantManager,
    service_context: ServiceContext,
) -> None:
    """The production staged seam fails before mutating the live repository."""
    repository.require_plant("p2").row = 2
    service_context.save_layout_callback = AsyncMock(
        side_effect=RuntimeError("store unavailable")
    )
    publish_callback = AsyncMock()
    service_context.publish_callback = publish_callback

    with pytest.raises(RuntimeError, match="store unavailable"):
        await manager.set_plant_layout(
            "tent",
            0,
            [
                {"plant_id": "p1", "row": 1, "col": 1},
                {"plant_id": "p2", "row": 1, "col": 2},
            ],
            rows=1,
        )

    growspace = repository.require_growspace("tent")
    assert (growspace.rows, growspace.plants_per_row) == (2, 2)
    assert growspace.layout_revision == 0
    assert (repository.require_plant("p1").row, repository.require_plant("p1").col) == (
        1,
        1,
    )
    assert repository.require_plant("p2").row == 2
    publish_callback.assert_not_awaited()


async def test_set_plant_layout_rejects_foreign_plant(
    repository: GrowspaceRepository,
    manager: PlantManager,
    save_callback: AsyncMock,
) -> None:
    """A real plant from another growspace cannot replace a layout member."""
    repository.add_growspace(Growspace(id="other", name="Other"))
    repository.add_plant(Plant(plant_id="foreign", growspace_id="other"))

    with pytest.raises(ValidationChangeError, match="does not belong"):
        await manager.set_plant_layout(
            "tent",
            0,
            [
                {"plant_id": "p1", "row": 1, "col": 1},
                {"plant_id": "foreign", "row": 1, "col": 2},
            ],
        )

    assert repository.require_growspace("tent").layout_revision == 0
    save_callback.assert_not_awaited()


async def test_individual_layout_mutations_advance_revision(
    repository: GrowspaceRepository,
    manager: PlantManager,
) -> None:
    """Add, move, swap, and remove each advance the affected layout once."""
    growspace = repository.require_growspace("tent")

    plant = await manager.add_plant("tent", "Kush", plant_id="p3", row=2, col=1)
    assert growspace.layout_revision == 1
    await manager.move_plant(plant.plant_id, 2, 2)
    assert growspace.layout_revision == 2
    await manager.switch_plants("p1", "p2")
    assert growspace.layout_revision == 3
    await manager.remove_plant(plant.plant_id)
    assert growspace.layout_revision == 4


async def test_transplant_advances_source_and_destination_revisions(
    repository: GrowspaceRepository,
    manager: PlantManager,
) -> None:
    """Changing plant membership advances both complete layouts."""
    repository.add_growspace(
        Growspace(id="other", name="Other", rows=2, plants_per_row=2)
    )

    await manager.update_plant("p1", growspace_id="other", row=2, col=2)

    assert repository.require_growspace("tent").layout_revision == 1
    assert repository.require_growspace("other").layout_revision == 1


async def test_grid_resize_advances_revision_and_rejects_stranding(
    hass: HomeAssistant,
    repository: GrowspaceRepository,
    service_context: ServiceContext,
) -> None:
    """Grid bounds are part of the layout revision contract."""
    manager = GrowspaceManager(
        service_context,
        hass,
        repository,
        NotificationState(),
        GrowspaceValidator(repository),
        MagicMock(),
    )

    await manager.update_growspace("tent", rows=3)
    assert repository.require_growspace("tent").layout_revision == 1
    with pytest.raises(ValidationChangeError, match="strand plant p2"):
        await manager.update_growspace("tent", plants_per_row=1)
    assert repository.require_growspace("tent").plants_per_row == 2
    assert repository.require_growspace("tent").layout_revision == 1


def test_existing_growspace_migrates_to_revision_zero() -> None:
    """Legacy serialized growspaces acquire revision zero without layout loss."""
    growspace = Growspace.from_dict(
        {"id": "legacy", "name": "Legacy", "rows": 4, "plants_per_row": 5}
    )

    assert growspace.layout_revision == 0
    assert (growspace.rows, growspace.plants_per_row) == (4, 5)


def test_serialized_growspace_advertises_atomic_layout(
    hass: HomeAssistant,
) -> None:
    """Every growspace payload exposes its authoritative revision and capability."""
    growspace = Growspace(id="tent", name="Tent", layout_revision=7)

    payload = GrowspaceViewModelBuilder(hass).build(growspace, [], {})

    assert payload["layout_revision"] == 7
    assert payload["capabilities"] == {"atomic_plant_layout": True}
