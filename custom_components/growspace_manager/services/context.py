"""ServiceContext and BaseService for the Growspace Manager integration."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from custom_components.growspace_manager.models import GrowspaceEvent


@dataclass
class ServiceContext:
    """Orchestration wiring shared by all services and managers.

    Bundles the four callbacks that every mutating service needs, so they
    can be constructed once in the coordinator and passed as a single
    dependency rather than four separate positional arguments.
    """

    save_callback: Callable[[], Awaitable[None]]
    lock: asyncio.Lock
    add_event: Callable[[str, GrowspaceEvent], None]
    invalidate_cache: Callable[[str | None], None]
    save_layout_callback: (
        Callable[[str, int, list[dict[str, Any]], str, int, int], Awaitable[None]]
        | None
    ) = None
    publish_callback: Callable[[], Awaitable[None]] | None = None


class BaseService:
    """Base class for all services and managers that mutate growspace data."""

    def __init__(self, ctx: ServiceContext) -> None:
        """Initialise the service with orchestration context."""
        self._ctx = ctx

    async def _save(self) -> None:
        await self._ctx.save_callback()

    def _emit(self, growspace_id: str, event: GrowspaceEvent) -> None:
        self._ctx.add_event(growspace_id, event)

    def _invalidate(self, growspace_id: str | None = None) -> None:
        self._ctx.invalidate_cache(growspace_id)

    async def _save_layout_snapshot(
        self,
        growspace_id: str,
        layout_revision: int,
        placements: list[dict[str, Any]],
        updated_at: str,
        rows: int,
        plants_per_row: int,
    ) -> bool:
        """Persist a staged layout when the coordinator provides that seam."""
        if self._ctx.save_layout_callback is None:
            return False
        await self._ctx.save_layout_callback(
            growspace_id,
            layout_revision,
            placements,
            updated_at,
            rows,
            plants_per_row,
        )
        return True

    async def _publish(self) -> None:
        """Publish already-persisted domain state to projections."""
        if self._ctx.publish_callback is not None:
            await self._ctx.publish_callback()

    @property
    def _lock(self) -> asyncio.Lock:
        return self._ctx.lock
